"""
UI-TARS 推理服务启动脚本

后端选择策略：
  Docker 容器内         → 直接读 MODEL_PATH/MMPROJ_PATH 环境变量，启动 llama-cpp-python server
  单卡（任意显存）      → llama-cpp-python server + GGUF q4_k_m (~4.7GB) + mmproj
  双卡 32GB+            → vLLM tp=2 BF16 (~15GB)
  无 GPU                → llama-cpp-python CPU 模式（慢）

两种后端均提供 OpenAI 兼容 API（http://host:port/v1），inference_client.py 无需修改。

环境自动检测优先级：
  1. Docker（MODEL_PATH 环境变量存在）→ 直接启动，不再做其他检测
  2. Kaggle → 从 /kaggle/input/ 读取已挂载模型
  3. Colab  → 自动从 HuggingFace 下载
  4. 本地   → 从项目根目录 models/ 加载

GGUF 模型文件（Mungert/UI-TARS-1.5-7B-GGUF）：
  主模型:  UI-TARS-1.5-7B-q4_k_m.gguf  (~4.7GB)
  视觉投影: UI-TARS-1.5-7B-q8_0.mmproj  (~0.5GB，多模态必须）
"""

import subprocess
import sys
import os

# ── 模型常量 ──────────────────────────────────────────────────────────────────

BF16_MODEL_ID    = "ByteDance-Seed/UI-TARS-1.5-7B"
BF16_DIR_NAME    = "UI-TARS-1.5-7B"

GGUF_REPO_ID     = "Mungert/UI-TARS-1.5-7B-GGUF"
GGUF_FILENAME    = "UI-TARS-1.5-7B-q4_k_m.gguf"
MMPROJ_FILENAME  = "UI-TARS-1.5-7B-q8_0.mmproj"
GGUF_DIR_NAME    = "UI-TARS-1.5-7B-GGUF"

SCRIPT_DIR        = os.path.dirname(os.path.abspath(__file__))
LOCAL_MODELS_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "models"))


# ── 环境检测 ──────────────────────────────────────────────────────────────────

def detect_env():
    """返回 'docker' | 'kaggle' | 'colab' | 'local'"""
    if os.environ.get("MODEL_PATH"):
        return "docker"
    if os.path.isdir("/kaggle/working"):
        return "kaggle"
    try:
        import google.colab  # noqa: F401
        return "colab"
    except ImportError:
        pass
    if os.path.isdir("/content") and "COLAB_GPU" in os.environ:
        return "colab"
    return "local"


# ── GPU 检测 ──────────────────────────────────────────────────────────────────

def detect_gpus():
    """返回 (gpu_count, vram_per_gpu_gb, gpu_name_list)"""
    try:
        import torch
        count = torch.cuda.device_count()
        if count > 0:
            names = [torch.cuda.get_device_name(i) for i in range(count)]
            vram  = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            return count, int(vram), names
    except ImportError:
        pass

    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            rows = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
            names, vrams = [], []
            for row in rows:
                parts = row.split(",")
                names.append(parts[0].strip())
                vrams.append(int(parts[1].strip().split()[0]) // 1024)
            return len(names), vrams[0] if vrams else 0, names
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    return 0, 0, []


# ── 后端决策 ──────────────────────────────────────────────────────────────────

def decide_backend(gpu_count, vram_gb, gpu_names):
    """返回 'llamacpp' 或 'vllm'"""
    print(f"[GPU] {gpu_count} 张  每卡约 {vram_gb}GB  {gpu_names}")
    if gpu_count >= 2:
        print("[后端] 双卡 → vLLM tp=2 BF16")
        return "vllm"
    print(f"[后端] {'单卡' if gpu_count == 1 else '无 GPU'} → llama.cpp GGUF q4_k_m + mmproj")
    return "llamacpp"


# ── 模型路径解析 ──────────────────────────────────────────────────────────────

def resolve_model_paths(env, backend):
    """
    返回 (model_path, mmproj_path_or_None)
    llamacpp → (gguf文件路径, mmproj文件路径)
    vllm     → (模型目录路径, None)
    """
    if env == "docker":
        # Docker 容器内由 Dockerfile ENV / docker-compose environment 提供
        model  = os.environ["MODEL_PATH"]
        mmproj = os.environ.get("MMPROJ_PATH")
        print(f"[模型] Docker 挂载: {model}")
        return model, mmproj

    if backend == "llamacpp":
        return _resolve_gguf(env)
    else:
        return _resolve_bf16(env), None


def _resolve_gguf(env):
    if env == "kaggle":
        model  = _find_in_kaggle("/kaggle/input", GGUF_FILENAME)
        mmproj = _find_in_kaggle("/kaggle/input", MMPROJ_FILENAME)
        if not model or not mmproj:
            _abort_kaggle_gguf()
        return model, mmproj

    if env == "colab":
        target = f"/content/models/{GGUF_DIR_NAME}"
        model  = os.path.join(target, GGUF_FILENAME)
        mmproj = os.path.join(target, MMPROJ_FILENAME)
        if not _file_ok(model) or not _file_ok(mmproj):
            _download_gguf(target)
        return model, mmproj

    # local
    target = os.path.join(LOCAL_MODELS_ROOT, GGUF_DIR_NAME)
    model  = os.path.join(target, GGUF_FILENAME)
    mmproj = os.path.join(target, MMPROJ_FILENAME)
    if not _file_ok(model) or not _file_ok(mmproj):
        print(f"\n[错误] 本地 GGUF 模型不完整: {target}")
        print("请运行（两个文件都需要）：")
        print(f"  huggingface-cli download {GGUF_REPO_ID} \\")
        print(f"      {GGUF_FILENAME} {MMPROJ_FILENAME} \\")
        print(f"      --local-dir {target}")
        sys.exit(1)
    return model, mmproj


def _resolve_bf16(env):
    if env == "kaggle":
        path = _find_bf16_dir_in_kaggle()
        if not path:
            _abort_kaggle_bf16()
        return path

    if env == "colab":
        target = f"/content/models/{BF16_DIR_NAME}"
        if not _dir_ok(target):
            _download_bf16(target)
        return target

    # local
    target = os.path.join(LOCAL_MODELS_ROOT, BF16_DIR_NAME)
    if not _dir_ok(target):
        print(f"\n[错误] 本地 BF16 模型不存在: {target}")
        print(f"  huggingface-cli download {BF16_MODEL_ID} --local-dir {target}")
        sys.exit(1)
    return target


# ── 文件检测工具 ──────────────────────────────────────────────────────────────

def _file_ok(path):
    return os.path.isfile(path) and os.path.getsize(path) > 1_000_000


def _dir_ok(path):
    return os.path.isdir(path) and os.path.isfile(os.path.join(path, "config.json"))


def _find_in_kaggle(root, filename):
    for entry in os.listdir(root):
        candidate = os.path.join(root, entry, filename)
        if os.path.isfile(candidate):
            return candidate
        if entry == filename and os.path.isfile(os.path.join(root, entry)):
            return os.path.join(root, entry)
    return None


def _find_bf16_dir_in_kaggle():
    for entry in os.listdir("/kaggle/input"):
        base = os.path.join("/kaggle/input", entry)
        if _dir_ok(base):
            return base
        sub = os.path.join(base, BF16_DIR_NAME)
        if _dir_ok(sub):
            return sub
    return None


# ── 错误提示 ──────────────────────────────────────────────────────────────────

def _abort_kaggle_gguf():
    print("\n" + "=" * 60)
    print("[Kaggle] 未找到 GGUF 模型文件（需要主模型 + mmproj）")
    print()
    print("方法 A：Notebook 右侧面板 '+ Add Input → Models'")
    print(f"  搜索 '{GGUF_REPO_ID}' 并 Add")
    print()
    print("方法 B：在 notebook cell 中运行：")
    print(f"  !HF_ENDPOINT=https://hf-mirror.com hf download {GGUF_REPO_ID} \\")
    print(f"      {GGUF_FILENAME} {MMPROJ_FILENAME} \\")
    print(f"      --local-dir /kaggle/working/{GGUF_DIR_NAME}")
    print("=" * 60)
    sys.exit(1)


def _abort_kaggle_bf16():
    print("\n" + "=" * 60)
    print("[Kaggle] 未找到 BF16 模型目录")
    print()
    print("请在 Notebook 右侧面板 '+ Add Input → Models'")
    print(f"  搜索 '{BF16_MODEL_ID}' 并 Add")
    print("=" * 60)
    sys.exit(1)


# ── 下载函数 ──────────────────────────────────────────────────────────────────

def _download_gguf(target_dir):
    print(f"\n[下载] GGUF q4_k_m + mmproj → {target_dir}")
    os.makedirs(target_dir, exist_ok=True)
    subprocess.run([
        sys.executable, "-m", "huggingface_hub", "download",
        GGUF_REPO_ID, GGUF_FILENAME, MMPROJ_FILENAME,
        "--local-dir", target_dir,
    ], check=True)
    print("[下载] 完成")


def _download_bf16(target_dir):
    print(f"\n[下载] BF16 完整模型 (~15GB) → {target_dir}")
    os.makedirs(target_dir, exist_ok=True)
    subprocess.run([
        sys.executable, "-m", "huggingface_hub", "download",
        BF16_MODEL_ID,
        "--local-dir", target_dir,
        "--local-dir-use-symlinks", "False",
    ], check=True)
    print("[下载] 完成")


# ── 依赖安装 ──────────────────────────────────────────────────────────────────

def install_dependencies(backend):
    if backend == "llamacpp":
        print("[依赖] 安装 llama-cpp-python (CUDA) ...")
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-q",
            "llama-cpp-python[server]",
            "--extra-index-url",
            "https://abetlen.github.io/llama-cpp-python/whl/cu124",
        ], check=True)
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-q",
            "huggingface_hub>=0.24.0", "ui-tars",
        ], check=True)
    else:
        print("[依赖] 安装 vLLM + transformers ...")
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-q",
            "vllm==0.6.6", "transformers>=4.45.0",
            "huggingface_hub>=0.24.0", "ui-tars",
            "--extra-index-url", "https://download.pytorch.org/whl/cu124",
        ], check=True)
    print("[依赖] 完成")


# ── 服务启动 ──────────────────────────────────────────────────────────────────

def launch_llamacpp(model_path, mmproj_path, gpu_count, host, port):
    n_gpu_layers = -1 if gpu_count > 0 else 0
    cmd = [
        sys.executable, "-m", "llama_cpp.server",
        "--model", model_path,
        "--host", host,
        "--port", str(port),
        "--n_gpu_layers", str(n_gpu_layers),
        "--n_ctx", "8192",
    ]
    if mmproj_path:
        cmd += ["--clip_model_path", mmproj_path]
    print(f"\n[启动] llama.cpp server")
    print("  " + " ".join(cmd))
    print(f"\n服务就绪后访问: http://{host}:{port}/v1\n")
    subprocess.run(cmd, check=True)


def launch_vllm(model_path, host, port):
    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--served-model-name", "ui-tars",
        "--model", model_path,
        "--limit-mm-per-prompt", "image=5",
        "--host", host, "--port", str(port),
        "-tp", "2",
    ]
    print(f"\n[启动] vLLM server (tp=2 BF16)")
    print("  " + " ".join(cmd))
    print(f"\n服务就绪后访问: http://{host}:{port}/v1\n")
    subprocess.run(cmd, check=True)


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="UI-TARS 推理服务（自动检测环境和 GPU）")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--skip-install", action="store_true")
    args = parser.parse_args()

    env                       = detect_env()
    gpu_count, vram_gb, names = detect_gpus()

    print(f"[环境] {env.upper()}")

    if env == "docker":
        # Docker 内直接启动，跳过安装和后端决策
        model_path  = os.environ["MODEL_PATH"]
        mmproj_path = os.environ.get("MMPROJ_PATH")
        launch_llamacpp(model_path, mmproj_path, gpu_count, args.host, args.port)
        return

    backend = decide_backend(gpu_count, vram_gb, names)

    if not args.skip_install:
        install_dependencies(backend)

    model_path, mmproj_path = resolve_model_paths(env, backend)

    if backend == "llamacpp":
        launch_llamacpp(model_path, mmproj_path, gpu_count, args.host, args.port)
    else:
        launch_vllm(model_path, args.host, args.port)


if __name__ == "__main__":
    main()
