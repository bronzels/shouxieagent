"""
UI-TARS 推理服务启动脚本

后端选择策略：
  单卡（任意显存，含本地 3060/T4/P100） → llama-cpp-python server + GGUF Q4_K_M (~4.7GB)
  双卡 32GB+（Kaggle T4 x2）           → vLLM tp=2 BF16 (~15GB)
  无 GPU                               → llama-cpp-python CPU 模式（慢）

两种后端均提供 OpenAI 兼容 API（http://host:port/v1），inference_client.py 无需修改。

环境自动检测：
  Kaggle → 从 /kaggle/input/ 读取已挂载模型（未挂载则打印操作步骤退出）
  Colab  → 自动从 HuggingFace 下载模型到 /content/models/
  本地   → 从项目根目录 models/ 加载（未下载则打印下载命令退出）
"""

import subprocess
import sys
import os
import glob

# ── 模型常量 ──────────────────────────────────────────────────────────────────

# 双卡 BF16 模型（官方，~15GB）
BF16_MODEL_ID   = "ByteDance-Seed/UI-TARS-1.5-7B"
BF16_DIR_NAME   = "UI-TARS-1.5-7B"

# 单卡 GGUF Q4_K_M（社区，~4.7GB）
GGUF_REPO_ID    = "Mungert/UI-TARS-1.5-7B-GGUF"
GGUF_FILENAME   = "UI-TARS-1.5-7B.Q4_K_M.gguf"
GGUF_DIR_NAME   = "UI-TARS-1.5-7B-GGUF"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_MODELS_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "models"))


# ── 环境检测 ──────────────────────────────────────────────────────────────────

def detect_env():
    """返回 'kaggle' | 'colab' | 'local'"""
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
    """
    返回 'llamacpp'（单卡/无卡）或 'vllm'（双卡）
    """
    print(f"[GPU] {gpu_count} 张  每卡约 {vram_gb}GB  {gpu_names}")
    if gpu_count >= 2:
        print("[后端] 双卡 → vLLM tp=2 BF16")
        return "vllm"
    print(f"[后端] {'单卡' if gpu_count == 1 else '无 GPU'} → llama.cpp GGUF Q4_K_M")
    return "llamacpp"


# ── 模型路径解析 ──────────────────────────────────────────────────────────────

def resolve_model_path(env, backend):
    """
    根据环境和后端返回模型路径，不满足条件则打印提示退出。
    llamacpp → gguf 文件路径
    vllm     → 模型目录路径
    """
    if backend == "llamacpp":
        dir_name, file_name = GGUF_DIR_NAME, GGUF_FILENAME
        dl_func = _download_gguf
    else:
        dir_name, file_name = BF16_DIR_NAME, None
        dl_func = _download_bf16

    if env == "kaggle":
        return _kaggle_model_path(dir_name, file_name, dl_func, backend)
    elif env == "colab":
        return _colab_model_path(dir_name, file_name, dl_func, backend)
    else:
        return _local_model_path(dir_name, file_name, dl_func, backend)


def _kaggle_model_path(dir_name, file_name, dl_func, backend):
    """Kaggle 只读 /kaggle/input，不下载（带宽受限）"""
    path = _find_in_kaggle_input(dir_name, file_name)
    if not path:
        _abort_kaggle_missing(dir_name, backend)
    print(f"[模型] Kaggle 挂载: {path}")
    return path


def _colab_model_path(dir_name, file_name, dl_func, backend):
    target_dir = f"/content/models/{dir_name}"
    full_path   = os.path.join(target_dir, file_name) if file_name else target_dir
    if not _model_ready(full_path, file_name):
        dl_func(target_dir)
    print(f"[模型] Colab 本地: {full_path}")
    return full_path


def _local_model_path(dir_name, file_name, dl_func, backend):
    target_dir = os.path.join(LOCAL_MODELS_ROOT, dir_name)
    full_path   = os.path.join(target_dir, file_name) if file_name else target_dir
    if not _model_ready(full_path, file_name):
        print(f"\n[错误] 本地模型不存在: {full_path}")
        if backend == "llamacpp":
            print("请运行以下命令下载 GGUF 模型（约 4.7GB）：")
            print(f"  huggingface-cli download {GGUF_REPO_ID} {GGUF_FILENAME} --local-dir {target_dir}")
        else:
            print("请运行以下命令下载模型（约 15GB）：")
            print(f"  huggingface-cli download {BF16_MODEL_ID} --local-dir {target_dir}")
        sys.exit(1)
    print(f"[模型] 本地: {full_path}")
    return full_path


def _model_ready(path, file_name):
    if file_name:
        return os.path.isfile(path) and os.path.getsize(path) > 1_000_000
    return os.path.isdir(path) and os.path.isfile(os.path.join(path, "config.json"))


def _find_in_kaggle_input(dir_name, file_name):
    """在 /kaggle/input 下递归查找模型文件或目录"""
    # 精确目录名
    for entry in os.listdir("/kaggle/input"):
        base = os.path.join("/kaggle/input", entry)
        # GGUF 文件
        if file_name:
            candidate = os.path.join(base, file_name)
            if os.path.isfile(candidate):
                return candidate
            # 直接就是文件
            if entry == file_name and os.path.isfile(base):
                return base
        # BF16 目录
        else:
            if os.path.isfile(os.path.join(base, "config.json")):
                return base
            sub = os.path.join(base, dir_name)
            if os.path.isfile(os.path.join(sub, "config.json")):
                return sub
    return None


# ── 下载函数 ──────────────────────────────────────────────────────────────────

def _download_gguf(target_dir):
    print(f"\n[下载] GGUF Q4_K_M ({GGUF_FILENAME}, ~4.7GB) → {target_dir}")
    os.makedirs(target_dir, exist_ok=True)
    subprocess.run([
        sys.executable, "-m", "huggingface_hub", "download",
        GGUF_REPO_ID, GGUF_FILENAME,
        "--local-dir", target_dir,
    ], check=True)
    print("[下载] 完成")


def _download_bf16(target_dir):
    print(f"\n[下载] BF16 完整模型 ({BF16_MODEL_ID}, ~15GB) → {target_dir}")
    os.makedirs(target_dir, exist_ok=True)
    subprocess.run([
        sys.executable, "-m", "huggingface_hub", "download",
        BF16_MODEL_ID,
        "--local-dir", target_dir,
        "--local-dir-use-symlinks", "False",
    ], check=True)
    print("[下载] 完成")


# ── Kaggle 错误提示 ───────────────────────────────────────────────────────────

def _abort_kaggle_missing(dir_name, backend):
    print("\n" + "=" * 60)
    if backend == "llamacpp":
        print("[Kaggle] 未找到 GGUF 模型文件")
        print()
        print("请在 Notebook 右侧面板操作：")
        print("  1. 点击 '+ Add Input' → 'Models'")
        print(f"  2. 搜索 '{GGUF_REPO_ID}'")
        print("  3. Add 后重新运行脚本")
        print()
        print("或者直接在 notebook cell 中运行：")
        print(f"  !huggingface-cli download {GGUF_REPO_ID} {GGUF_FILENAME} \\")
        print(f"      --local-dir /kaggle/working/{GGUF_DIR_NAME}")
    else:
        print("[Kaggle] 未找到 BF16 模型目录")
        print()
        print("请在 Notebook 右侧面板操作：")
        print("  1. 点击 '+ Add Input' → 'Models'")
        print(f"  2. 搜索 '{BF16_MODEL_ID}'")
        print("  3. Add 后重新运行脚本")
    print("=" * 60)
    sys.exit(1)


# ── 依赖安装 ──────────────────────────────────────────────────────────────────

def install_dependencies(backend):
    if backend == "llamacpp":
        print("[依赖] 安装 llama-cpp-python (CUDA) + huggingface_hub ...")
        # 预编译 CUDA wheel，避免从源码编译
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-q",
            "llama-cpp-python[server]",
            "--extra-index-url",
            "https://abetlen.github.io/llama-cpp-python/whl/cu124",
        ], check=True)
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-q",
            "huggingface_hub>=0.24.0",
            "ui-tars",
        ], check=True)
    else:
        print("[依赖] 安装 vLLM + transformers + huggingface_hub ...")
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-q",
            "vllm==0.6.6",
            "transformers>=4.45.0",
            "huggingface_hub>=0.24.0",
            "ui-tars",
            "--extra-index-url", "https://download.pytorch.org/whl/cu124",
        ], check=True)
    print("[依赖] 完成")


# ── 服务启动 ──────────────────────────────────────────────────────────────────

def launch_llamacpp(model_path, gpu_count, host, port):
    """启动 llama-cpp-python OpenAI 兼容服务"""
    # -1 = 所有层放 GPU；无 GPU 则设 0
    n_gpu_layers = -1 if gpu_count > 0 else 0
    cmd = [
        sys.executable, "-m", "llama_cpp.server",
        "--model", model_path,
        "--host", host,
        "--port", str(port),
        "--n_gpu_layers", str(n_gpu_layers),
        "--n_ctx", "8192",
    ]
    print(f"\n[启动] llama.cpp server")
    print("  " + " ".join(cmd))
    print(f"\n服务就绪后访问: http://{host}:{port}/v1\n")
    subprocess.run(cmd, check=True)


def launch_vllm(model_path, host, port):
    """启动 vLLM OpenAI 兼容服务（双卡 BF16）"""
    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--served-model-name", "ui-tars",
        "--model", model_path,
        "--limit-mm-per-prompt", "image=5",
        "--host", host,
        "--port", str(port),
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
    parser.add_argument("--skip-install", action="store_true", help="跳过依赖安装")
    args = parser.parse_args()

    env                      = detect_env()
    gpu_count, vram_gb, names = detect_gpus()
    backend                  = decide_backend(gpu_count, vram_gb, names)

    print(f"[环境] {env.upper()}  后端: {backend}")

    if not args.skip_install:
        install_dependencies(backend)

    model_path = resolve_model_path(env, backend)

    if backend == "llamacpp":
        launch_llamacpp(model_path, gpu_count, args.host, args.port)
    else:
        launch_vllm(model_path, args.host, args.port)


if __name__ == "__main__":
    main()
