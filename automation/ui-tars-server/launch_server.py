"""
UI-TARS vLLM 服务启动脚本
自动检测 GPU 数量，单/双 T4 自动切换 tensor-parallel 配置

支持环境：
- Kaggle T4 (单卡 16GB)
- Kaggle T4 x2 (双卡 32GB)
- Kaggle P100 (单卡 16GB)
- Colab Free T4 (单卡 16GB)
"""

import subprocess
import sys
import os
import argparse

# 默认模型：UI-TARS-1.5-7B（最新，基于 Qwen2.5-VL）
DEFAULT_MODEL_ID = "ByteDance-Seed/UI-TARS-1.5-7B"

# 模型本地缓存路径（相对于脚本的两级上级目录下的 models/）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL_DIR = os.path.join(SCRIPT_DIR, "..", "..", "models", "UI-TARS-1.5-7B")


def detect_gpus():
    """返回 (gpu_count, gpu_name_list)"""
    try:
        import torch
        count = torch.cuda.device_count()
        names = [torch.cuda.get_device_name(i) for i in range(count)]
        return count, names
    except ImportError:
        pass

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            names = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
            return len(names), names
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return 0, []


def get_vllm_config(gpu_count, gpu_names):
    """根据 GPU 配置返回 vLLM 启动参数"""
    print(f"检测到 {gpu_count} 张 GPU: {gpu_names}")

    if gpu_count == 0:
        print("警告: 未检测到 GPU，将使用 CPU（速度极慢）")
        return {"tp": 1, "kv_cache_dtype": None, "extra_args": []}

    total_vram_gb = gpu_count * 16  # T4/P100 均为 16GB

    if gpu_count >= 2:
        # 双 T4: 32GB 总显存，可跑 BF16 无需 fp8
        print(f"双卡模式: tp=2, 总显存约 {total_vram_gb}GB，使用 BF16")
        return {"tp": 2, "kv_cache_dtype": None, "extra_args": []}
    else:
        # 单卡 16GB: 必须用 fp8 KV cache 节省显存
        print(f"单卡模式: tp=1, 显存约 16GB，启用 fp8 KV cache")
        return {"tp": 1, "kv_cache_dtype": "fp8", "extra_args": []}


def install_dependencies():
    """安装 vLLM 和相关依赖"""
    print("安装依赖...")
    subprocess.run([
        sys.executable, "-m", "pip", "install", "-q",
        "vllm==0.6.6",
        "transformers>=4.45.0",
        "ui-tars",
        "--extra-index-url", "https://download.pytorch.org/whl/cu124"
    ], check=True)


def download_model(model_id, model_dir):
    """下载模型到本地目录"""
    if os.path.exists(os.path.join(model_dir, "config.json")):
        print(f"模型已存在于 {model_dir}，跳过下载")
        return model_dir

    print(f"下载模型 {model_id} 到 {model_dir} ...")
    os.makedirs(model_dir, exist_ok=True)
    subprocess.run([
        sys.executable, "-m", "huggingface_hub",
        "download", model_id,
        "--local-dir", model_dir,
        "--local-dir-use-symlinks", "False"
    ], check=True)
    return model_dir


def launch_vllm_server(model_path, vllm_cfg, host="127.0.0.1", port=8000):
    """启动 vLLM OpenAI 兼容 API 服务"""
    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--served-model-name", "ui-tars",
        "--model", model_path,
        "--limit-mm-per-prompt", "image=5",
        "--host", host,
        "--port", str(port),
        "-tp", str(vllm_cfg["tp"]),
    ]

    if vllm_cfg["kv_cache_dtype"]:
        cmd += ["--kv-cache-dtype", vllm_cfg["kv_cache_dtype"]]

    cmd += vllm_cfg.get("extra_args", [])

    print(f"\n启动 vLLM 服务:")
    print("  " + " ".join(cmd))
    print(f"\n服务地址: http://{host}:{port}/v1\n")

    subprocess.run(cmd, check=True)


def main():
    parser = argparse.ArgumentParser(description="启动 UI-TARS vLLM 推理服务")
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID,
                        help=f"HuggingFace 模型 ID (默认: {DEFAULT_MODEL_ID})")
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR,
                        help="本地模型缓存目录")
    parser.add_argument("--host", default="0.0.0.0",
                        help="监听地址 (默认: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000,
                        help="监听端口 (默认: 8000)")
    parser.add_argument("--skip-install", action="store_true",
                        help="跳过依赖安装")
    parser.add_argument("--skip-download", action="store_true",
                        help="跳过模型下载（模型已在 --model-dir）")
    args = parser.parse_args()

    if not args.skip_install:
        install_dependencies()

    gpu_count, gpu_names = detect_gpus()
    vllm_cfg = get_vllm_config(gpu_count, gpu_names)

    model_path = args.model_dir
    if not args.skip_download:
        model_path = download_model(args.model_id, args.model_dir)

    launch_vllm_server(model_path, vllm_cfg, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
