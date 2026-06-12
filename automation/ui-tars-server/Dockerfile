FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-dev \
        build-essential cmake ninja-build \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 从源码编译 llama-cpp-python，启用 CUDA 后端
ENV CMAKE_ARGS="-DGGML_CUDA=on"
ENV FORCE_CMAKE=1
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir \
        "llama-cpp-python[server]" \
        "openai>=1.0.0" \
        "ui-tars"

WORKDIR /app
COPY inference_client.py .

# 模型文件通过 volume 挂载到 /models/
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
