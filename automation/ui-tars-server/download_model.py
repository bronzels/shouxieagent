"""
UI-TARS GGUF 模型下载脚本
优先 hf-mirror.com，失败自动回退到 ModelScope

用法（在服务器上执行）：
  python3 download_model.py
  python3 download_model.py --source modelscope   # 强制用 ModelScope
  python3 download_model.py --target-dir /your/path
"""

import os
import sys
import argparse

REPO_ID      = "Mungert/UI-TARS-1.5-7B-GGUF"
FILES        = ["UI-TARS-1.5-7B-q4_k_m.gguf", "UI-TARS-1.5-7B-q8_0.mmproj"]

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DIR  = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", "models", "UI-TARS-1.5-7B-GGUF"))


def download_hf(target_dir):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    from huggingface_hub import hf_hub_download
    for fname in FILES:
        out = os.path.join(target_dir, fname)
        if os.path.isfile(out) and os.path.getsize(out) > 1_000_000:
            print(f"[skip] {fname} 已存在")
            continue
        print(f"[hf-mirror] 下载 {fname} ...")
        hf_hub_download(repo_id=REPO_ID, filename=fname, local_dir=target_dir)
        print(f"[hf-mirror] 完成 {fname}")


def download_modelscope(target_dir):
    from modelscope.hub.file_download import model_file_download
    for fname in FILES:
        out = os.path.join(target_dir, fname)
        if os.path.isfile(out) and os.path.getsize(out) > 1_000_000:
            print(f"[skip] {fname} 已存在")
            continue
        print(f"[ModelScope] 下载 {fname} ...")
        model_file_download(
            model_id=REPO_ID,
            file_path=fname,
            local_dir=target_dir,
            cache_dir=os.path.join(target_dir, ".ms_cache"),
        )
        print(f"[ModelScope] 完成 {fname}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["hf", "modelscope", "auto"], default="auto",
                        help="下载源: hf(hf-mirror) / modelscope / auto(hf优先，失败回退)")
    parser.add_argument("--target-dir", default=DEFAULT_DIR)
    args = parser.parse_args()

    os.makedirs(args.target_dir, exist_ok=True)
    print(f"[目标目录] {args.target_dir}")

    if args.source == "modelscope":
        download_modelscope(args.target_dir)
        return

    if args.source == "hf":
        download_hf(args.target_dir)
        return

    # auto: hf-mirror 优先，失败回退 ModelScope
    try:
        download_hf(args.target_dir)
    except Exception as e:
        print(f"[hf-mirror] 失败: {e}")
        print("[fallback] 切换 ModelScope ...")
        download_modelscope(args.target_dir)

    print("\n[完成] 所有文件已下载")


if __name__ == "__main__":
    main()
