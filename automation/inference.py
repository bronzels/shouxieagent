# -*- coding: utf-8 -*-
"""
UI-TARS-1.5-7B 推理服务（无幻觉版）
- 支持直接推理（--image_path + --query）
- 支持 OpenAI 兼容 API 服务（--serve），供任意前端使用
- 自动将图像文件转为 base64
- 全平台路径兼容（Windows/Linux）
"""

import os
import sys
import base64
import io
import argparse
from pathlib import Path

if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"


def setup_environment():
    os.environ["TOKENIZERS_PARALLELISM"] = "false"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run UI-TARS-1.5-7B (Qwen2-VL based) with 4-bit quantization"
    )
    parser.add_argument(
        "--model_path",
        type=str,
        default="./models/ui-tars-1.5-7b",
        help="Path to model directory (Hugging Face format)",
    )

    # === 直接推理模式 ===
    parser.add_argument(
        "--image_path", type=str, help="Path to input image (e.g., screenshot.png)"
    )
    parser.add_argument("--query", type=str, help="Text instruction")
    parser.add_argument("--max_new_tokens", type=int, default=512)

    # === API 服务模式 ===
    parser.add_argument(
        "--serve", action="store_true", help="Start OpenAI-compatible API server"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="API port (default: 8000)"
    )
    parser.add_argument("--host", type=str, default="127.0.0.1", help="API host")

    args = parser.parse_args()

    if not args.serve and (not args.image_path or not args.query):
        parser.error("Either --serve OR (--image_path and --query) must be provided.")

    return args


def load_image_as_base64(image_path):
    """从文件路径加载图像并返回 base64 字符串"""
    try:
        path = Path(image_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")

        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/png;base64,{encoded}"
    except Exception as e:
        raise ValueError(f"Failed to load image '{image_path}': {e}")


def image_to_pil(base64_str):
    """将 base64 转为 PIL Image"""
    from PIL import Image

    if base64_str.startswith("data:image"):
        base64_str = base64_str.split(",", 1)[1]
    image_data = base64.b64decode(base64_str)
    return Image.open(io.BytesIO(image_data)).convert("RGB")


# ===== 模型缓存 =====
_model = None
_tokenizer = None


def get_model(model_path):
    global _model, _tokenizer
    if _model is None:
        print("[INFO] Loading UI-TARS model...")
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA not available. GPU required.")

        _tokenizer = AutoTokenizer.from_pretrained(
            model_path, trust_remote_code=True, use_fast=False
        )
        _model = AutoModelForCausalLM.from_pretrained(
            model_path,
            device_map="auto",
            trust_remote_code=True,
            torch_dtype=torch.float16,
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )
        print("[INFO] Model loaded.")
    return _model, _tokenizer


def run_inference(model_path, image_b64, query, max_new_tokens):
    model, tokenizer = get_model(model_path)
    image = image_to_pil(image_b64)

    with torch.no_grad():
        response, _ = model.chat(
            tokenizer,
            image=image,
            query=query,
            history=None,
            max_new_tokens=max_new_tokens,
        )
    return response


# ===== OpenAI 兼容 API 服务 =====
def start_api_server(model_path, host, port):
    try:
        from fastapi import FastAPI, HTTPException
        from pydantic import BaseModel
        from typing import List, Union, Optional
        import uvicorn
        import torch
    except ImportError as e:
        print(f"[ERROR] Install API deps: pip install fastapi uvicorn", file=sys.stderr)
        sys.exit(1)

    app = FastAPI(title="UI-TARS Local Server")

    class ContentItem(BaseModel):
        type: str
        text: Optional[str] = None
        image_url: Optional[dict] = None

    class Message(BaseModel):
        role: str
        content: Union[str, List[ContentItem]]

    class ChatRequest(BaseModel):
        model: str
        messages: List[Message]
        max_tokens: int = 512

    @app.post("/v1/chat/completions")
    async def chat_completions(request: ChatRequest):
        try:
            text_query = ""
            image_url = None

            # 遍历所有消息，拼接文本并提取最后一张图片
            for msg in request.messages:
                if msg.role == "user":
                    if isinstance(msg.content, str):
                        text_query += msg.content + "\n"
                    elif isinstance(msg.content, list):
                        for item in msg.content:
                            if item.type == "text" and item.text:
                                text_query += item.text + "\n"
                            elif item.type == "image_url" and item.image_url:
                                image_url = item.image_url["url"]

            text_query = text_query.strip()

            if not text_query or not image_url:
                raise HTTPException(
                    status_code=400, detail="Both text and image required in messages"
                )

            # 支持 URL 或 base64
            if image_url.startswith("http"):
                raise HTTPException(
                    status_code=400, detail="Remote images not supported. Use base64."
                )

            response = run_inference(
                model_path, image_url, text_query, request.max_tokens
            )
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": response},
                        "finish_reason": "stop",
                    }
                ]
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    print(
        f"\n✅ UI-TARS API server running at http://{host}:{port}/v1/chat/completions"
    )
    print("Compatible with any OpenAI-multimodal frontend.\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


# ===== 主程序 =====
def main():
    setup_environment()
    args = parse_args()
    model_path = str(Path(args.model_path).resolve())

    try:
        if args.serve:
            start_api_server(model_path, args.host, args.port)
        else:
            # 将图像文件转为 base64
            image_b64 = load_image_as_base64(args.image_path)
            response = run_inference(
                model_path, image_b64, args.query, args.max_new_tokens
            )
            print("\n[RESULT]")
            print(response)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
