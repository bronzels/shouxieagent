"""
UI-TARS vLLM 服务启动脚本

自动检测运行环境和 GPU 配置：

Kaggle:
  - 单卡(16GB): 读 /kaggle/input/，要求模型已挂载，使用 fp8 KV cache
  - 双卡(32GB): 读 /kaggle/input/，要求模型已挂载，tp=2 BF16
  - 未满足条件则打印提示并退出

Colab:
  - 自动从 HuggingFace 下载模型到 /content/models/

其他环境（本地等）:
  - 从项目根目录 /models/ 加载，使用 fp8 KV cache
"""

import subprocess
import sys
import os
import glob

MODEL_ID = "ByteDance-Seed/UI-TARS-1.5-7B"
MODEL_DIR_NAME = "UI-TARS-1.5-7B"

# Kaggle 挂载后模型目录名可能带连字符或下划线，用 glob 匹配
KAGGLE_INPUT_ROOT = "/kaggle/input"
KAGGLE_MODEL_GLOB = os.path.join(KAGGLE_INPUT_ROOT, "*ui-tars*", MODEL_DIR_NAME)

COLAB_MODEL_DIR = f"/content/models/{MODEL_DIR_NAME}"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_MODEL_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "models", MODEL_DIR_NAME))


# ── 环境检测 ────────────────────────────────────────────────────────────────

def detect_env():
    """返回 'kaggle' | 'colab' | 'local'"""
    if os.path.isdir("/kaggle/working"):
        return "kaggle"
    if os.path.isdir("/content") and "COLAB_GPU" in os.environ or _is_colab():
        return "colab"
    return "local"


def _is_colab():
    try:
        import google.colab  # noqa: F401
        return True
    except ImportError:
        return False


# ── GPU 检测 ────────────────────────────────────────────────────────────────

def detect_gpus():
    """返回 (gpu_count, vram_per_gpu_gb, gpu_name_list)"""
    try:
        import torch
        count = torch.cuda.device_count()
        if count > 0:
            names = [torch.cuda.get_device_name(i) for i in range(count)]
            # 从 torch 获取显存（字节转 GB）
            vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
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
                # memory.total 格式如 "16160 MiB"
                vram_mib = int(parts[1].strip().split()[0])
                vrams.append(vram_mib // 1024)
            return len(names), vrams[0] if vrams else 0, names
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    return 0, 0, []


# ── 模型路径解析 ─────────────────────────────────────────────────────────────

def find_kaggle_model_dir():
    """在 /kaggle/input 下 glob 匹配模型目录，返回路径或 None"""
    # 精确子目录名
    candidates = glob.glob(os.path.join(KAGGLE_INPUT_ROOT, "*", MODEL_DIR_NAME))
    if candidates:
        return candidates[0]
    # 宽松匹配：目录名含 ui-tars
    for entry in os.listdir(KAGGLE_INPUT_ROOT):
        if "ui-tars" in entry.lower() or "uitars" in entry.lower():
            full = os.path.join(KAGGLE_INPUT_ROOT, entry)
            if os.path.isdir(full) and os.path.isfile(os.path.join(full, "config.json")):
                return full
    return None


def model_ready(path):
    return path and os.path.isfile(os.path.join(path, "config.json"))


# ── 配置决策 ─────────────────────────────────────────────────────────────────

def resolve_model_and_config(env, gpu_count, vram_gb, gpu_names):
    """
    返回 (model_path, vllm_cfg) 或在配置不满足时打印提示并退出。

    vllm_cfg = {
        "tp": int,
        "kv_cache_dtype": str | None,
    }
    """
    print(f"\n[环境] {env.upper()}  |  GPU x{gpu_count}  |  每卡约 {vram_gb}GB  |  {gpu_names}")

    # ── Kaggle ──────────────────────────────────────────────────────────────
    if env == "kaggle":
        model_dir = find_kaggle_model_dir()

        if not model_ready(model_dir):
            _abort_kaggle_no_model()

        if gpu_count >= 2:
            # 双卡：BF16，tp=2，不需要 fp8
            print(f"[配置] Kaggle 双卡  tp=2  BF16  model={model_dir}")
            return model_dir, {"tp": 2, "kv_cache_dtype": None}

        # 单卡：必须 fp8
        if vram_gb < 15:
            _abort_kaggle_vram(gpu_count, vram_gb, need_fp8=True)

        print(f"[配置] Kaggle 单卡  tp=1  fp8 KV cache  model={model_dir}")
        return model_dir, {"tp": 1, "kv_cache_dtype": "fp8"}

    # ── Colab ────────────────────────────────────────────────────────────────
    if env == "colab":
        if not model_ready(COLAB_MODEL_DIR):
            _download_model(COLAB_MODEL_DIR)

        if gpu_count == 0:
            print("警告: Colab 未分配 GPU，将以 CPU 运行（速度极慢）")
            return COLAB_MODEL_DIR, {"tp": 1, "kv_cache_dtype": None}

        cfg = {"tp": 1, "kv_cache_dtype": "fp8"} if gpu_count == 1 else {"tp": 2, "kv_cache_dtype": None}
        print(f"[配置] Colab  tp={cfg['tp']}  kv={cfg['kv_cache_dtype'] or 'BF16'}  model={COLAB_MODEL_DIR}")
        return COLAB_MODEL_DIR, cfg

    # ── 本地 / 其他 ──────────────────────────────────────────────────────────
    if not model_ready(LOCAL_MODEL_DIR):
        print(f"\n[错误] 本地模型目录不存在或不完整: {LOCAL_MODEL_DIR}")
        print("请先下载模型:")
        print(f"  huggingface-cli download {MODEL_ID} --local-dir {LOCAL_MODEL_DIR}")
        sys.exit(1)

    cfg = {"tp": 1, "kv_cache_dtype": "fp8"}
    if gpu_count >= 2:
        cfg = {"tp": 2, "kv_cache_dtype": None}
    print(f"[配置] 本地  tp={cfg['tp']}  kv={cfg['kv_cache_dtype'] or 'BF16'}  model={LOCAL_MODEL_DIR}")
    return LOCAL_MODEL_DIR, cfg


# ── 错误提示 ──────────────────────────────────────────────────────────────────

def _abort_kaggle_no_model():
    print("\n" + "=" * 60)
    print("[Kaggle 配置错误] 未找到已挂载的 UI-TARS 模型")
    print()
    print("请在 Kaggle notebook 右侧面板操作：")
    print("  1. 点击 '+ Add Input'")
    print("  2. 选择 'Models'")
    print(f"  3. 搜索 '{MODEL_ID}'")
    print("  4. 点击 Add，然后重新运行此脚本")
    print("=" * 60)
    sys.exit(1)


def _abort_kaggle_vram(gpu_count, vram_gb, need_fp8=False):
    print("\n" + "=" * 60)
    if need_fp8:
        print(f"[Kaggle 配置错误] 单卡显存 {vram_gb}GB 不足以运行 UI-TARS-1.5-7B")
        print()
        print("解决方案（选其一）：")
        print("  A. 在 Notebook Settings 中切换到 T4 x2（双卡，申请后可用）")
        print("     → 双卡合计 32GB，可 BF16 全精度运行")
        print("  B. 确认已选 T4 或 P100（单卡 16GB），当前检测到:", vram_gb, "GB")
        print("     → 如显示 < 15GB 说明 GPU 分配异常，重启 notebook 再试")
    else:
        print(f"[Kaggle 配置错误] 双卡总显存不足，每卡 {vram_gb}GB")
    print("=" * 60)
    sys.exit(1)


# ── 模型下载 ──────────────────────────────────────────────────────────────────

def _download_model(target_dir):
    print(f"\n[下载] {MODEL_ID} → {target_dir}  (约 15GB，请耐心等待...)")
    os.makedirs(target_dir, exist_ok=True)
    subprocess.run([
        sys.executable, "-m", "huggingface_hub", "download",
        MODEL_ID,
        "--local-dir", target_dir,
        "--local-dir-use-symlinks", "False",
    ], check=True)
    print("[下载] 完成")


# ── 依赖安装 ──────────────────────────────────────────────────────────────────

def install_dependencies():
    print("[依赖] 安装 vLLM + transformers + ui-tars ...")
    subprocess.run([
        sys.executable, "-m", "pip", "install", "-q",
        "vllm==0.6.6",
        "transformers>=4.45.0",
        "huggingface_hub>=0.24.0",
        "ui-tars",
        "--extra-index-url", "https://download.pytorch.org/whl/cu124",
    ], check=True)
    print("[依赖] 安装完成")


# ── vLLM 启动 ─────────────────────────────────────────────────────────────────

def launch_vllm(model_path, cfg, host="0.0.0.0", port=8000):
    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--served-model-name", "ui-tars",
        "--model", model_path,
        "--limit-mm-per-prompt", "image=5",
        "--host", host,
        "--port", str(port),
        "-tp", str(cfg["tp"]),
    ]
    if cfg.get("kv_cache_dtype"):
        cmd += ["--kv-cache-dtype", cfg["kv_cache_dtype"]]

    print(f"\n[启动] {' '.join(cmd)}")
    print(f"\n服务就绪后访问: http://{host}:{port}/v1\n")
    subprocess.run(cmd, check=True)


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="UI-TARS vLLM 推理服务（自动检测环境）")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--skip-install", action="store_true", help="跳过依赖安装")
    args = parser.parse_args()

    if not args.skip_install:
        install_dependencies()

    env = detect_env()
    gpu_count, vram_gb, gpu_names = detect_gpus()
    model_path, vllm_cfg = resolve_model_and_config(env, gpu_count, vram_gb, gpu_names)
    launch_vllm(model_path, vllm_cfg, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
