FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip curl \
    && rm -rf /var/lib/apt/lists/*

# llama-cpp-python 预编译 CUDA wheel（含 server 组件）
RUN pip3 install --no-cache-dir \
    "llama-cpp-python[server]" \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124 \
    && pip3 install --no-cache-dir "openai>=1.0.0" "ui-tars"

WORKDIR /app
COPY inference_client.py .

# 模型文件通过 volume 挂载到 /models/
# 主模型 q4_k_m + 视觉投影 mmproj（多模态必须）
ENV MODEL_PATH=/models/UI-TARS-1.5-7B-q4_k_m.gguf
ENV MMPROJ_PATH=/models/UI-TARS-1.5-7B-q8_0.mmproj
ENV HOST=0.0.0.0
ENV PORT=8000
ENV N_CTX=8192

EXPOSE 8000

CMD python3 -m llama_cpp.server \
    --model "${MODEL_PATH}" \
    --clip_model_path "${MMPROJ_PATH}" \
    --host "${HOST}" \
    --port "${PORT}" \
    --n_gpu_layers -1 \
    --n_ctx "${N_CTX}"
