# UI-TARS 推理服务
#
# 结构照抄 ragateway/inference/Dockerfile，相同 layer 内容复用 Docker 缓存，build 极快。
# 无私有镜像依赖，可独立构建。
#
# 模型通过 volume 挂载到 /models/：
#   /models/UI-TARS-1.5-7B-q4_k_m.gguf   主模型  ~4.7GB
#   /models/UI-TARS-1.5-7B-q8_0.mmproj   视觉投影 ~0.8GB
#
# Build（在项目根目录执行）:
#   docker build -f automation/ui-tars-server/Dockerfile -t ui-tars:latest .
# Run:
#   docker compose -f automation/ui-tars-server/docker-compose.yml up -d

FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
# 阿里云 apt 镜像（国内加速，与 ragateway 相同 layer）
RUN sed -i 's|http://archive.ubuntu.com|https://mirrors.aliyun.com|g' /etc/apt/sources.list && \
    sed -i 's|http://security.ubuntu.com|https://mirrors.aliyun.com|g' /etc/apt/sources.list && \
    apt-get update && apt-get install -y \
    python3.10 python3-pip python3.10-dev curl wget \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/bin/python3 \
    && ln -sf /usr/bin/python3 /usr/bin/python

# llama-cpp-python 0.3.19 CUDA 12.1 预编译 wheel（与 ragateway 相同，共享 layer）
# 下载地址：https://github.com/abetlen/llama-cpp-python/releases/download/v0.3.19-cu121/llama_cpp_python-0.3.19%2Bcu121-cp310-cp310-linux_x86_64.whl
# 去掉 +cu121 保存为：automation/ui-tars-server/llama_cpp_python-0.3.19-cp310-cp310-linux_x86_64.whl
COPY llama_cpp_python-0.3.19-cp310-cp310-linux_x86_64.whl /tmp/
RUN pip install --no-cache-dir /tmp/llama_cpp_python-0.3.19-cp310-cp310-linux_x86_64.whl && \
    pip install --no-cache-dir \
        pydantic-settings sse-starlette starlette-context \
        "openai>=1.0.0" \
        "ui-tars" \
        huggingface_hub modelscope \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

ENV HF_ENDPOINT=https://hf-mirror.com
ENV MODELSCOPE_CACHE=/models

WORKDIR /app
COPY inference_client.py .

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
