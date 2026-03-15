git clone https://github.com/bytedance/UI-TARS-desktop.git
cd UI-TARS-desktop
#node is preinstalled
node install -g pnpm
pnpm install
# 修复 "Missing script: dev" 报错：
# UI-TARS 项目的 package.json 中并没有 "dev" 脚本指令，而是使用了 "dev:ui-tars"。
# 因此将原先的 npm run dev 替换为正确的官方推荐启动命令：
# npm run dev
pnpm run dev:ui-tars

# 1. 升级 transformers 和 huggingface-hub
pip install -U "huggingface_hub>=0.20.0" "transformers>=4.38.0"
# 2. 启用 hf_transfer（官方加速插件）
pip install hf_transfer
export HF_HUB_ENABLE_HF_TRANSFER=1
# 3. 设置镜像源（关键！）
export HF_ENDPOINT=https://hf-mirror.com
# 4. 下载模型（自动走镜像）
mkdir models
python -c '''
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="ByteDance-Seed/UI-TARS-1.5-7B",
    local_dir="./models/ui-tars-1.5-7b",
    local_dir_use_symlinks=False,
    resume_download=True
)
'''

pip install -r requirements.txt

python inference.py 

:<<EOF

npx @agent-tars/cli@latest

EOF
