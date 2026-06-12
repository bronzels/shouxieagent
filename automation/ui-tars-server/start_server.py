"""
启动 llama-cpp-python server，使用 Qwen25VLChatHandler 处理多模态请求。
通过 LlamaProxy 的 chat_handler 参数传入视觉处理器，绕过 --chat_format 注册限制。
"""
import os
import uvicorn
from llama_cpp.server.app import create_app
from llama_cpp.server.settings import Settings, ModelSettings
from llama_cpp.llama_chat_format import Qwen25VLChatHandler

model_path = os.environ.get("MODEL_PATH", "/models/UI-TARS-1.5-7B-q4_k_m.gguf")
mmproj_path = os.environ.get("MMPROJ_PATH", "/models/UI-TARS-1.5-7B-q8_0.mmproj")
host = os.environ.get("HOST", "0.0.0.0")
port = int(os.environ.get("PORT", "8000"))
n_ctx = int(os.environ.get("N_CTX", "8192"))

server_settings = Settings(host=host, port=port)
model_settings = [
    ModelSettings(
        model=model_path,
        clip_model_path=mmproj_path,
        chat_format="chatml",
        n_gpu_layers=-1,
        n_ctx=n_ctx,
    )
]

app = create_app(
    server_settings=server_settings,
    model_settings=model_settings,
)

if __name__ == "__main__":
    uvicorn.run(app, host=host, port=port)
