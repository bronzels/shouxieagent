#!/usr/bin/env bash
# 监听本地 ui-tars-server 目录变更，自动 rsync 到 192.168.3.14
# 在 WSL 中运行：bash automation/ui-tars-server/sync_watch.sh
# 注：本脚本自定位（LOCAL_DIR=脚本所在目录），目录整体移动后无需改路径；
#     远程目标 /mnt/ext4disk/ui-tars 不变。ui-tars-server 为 web/desktop/mobile 共用基础设施。

set -euo pipefail

REMOTE_HOST="root@192.168.3.14"
REMOTE_DIR="/mnt/ext4disk/ui-tars"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

# 排除项：不同步 models（大文件）、pycache、临时文件
EXCLUDES=(
    --exclude="models/"
    --exclude=".venv/"
    --exclude=".ms_cache/"
    --exclude="__pycache__/"
    --exclude="*.pyc"
    --exclude=".git/"
    --exclude="docker-build.log"
    --exclude="download.log"
)

do_sync() {
    echo "[sync] $(date '+%H:%M:%S') → ${REMOTE_HOST}:${REMOTE_DIR}/"
    rsync -az --delete "${EXCLUDES[@]}" "${LOCAL_DIR}/" "${REMOTE_HOST}:${REMOTE_DIR}/"
}

# 检查 inotifywait 是否可用
if ! command -v inotifywait &>/dev/null; then
    echo "[error] inotifywait 未安装，运行: sudo apt-get install inotify-tools"
    exit 1
fi

echo "[sync] 初始同步..."
do_sync

echo "[sync] 监听 ${LOCAL_DIR} 中的文件变更..."
inotifywait -m -r -e modify,create,delete,move \
    --exclude "(\.git|__pycache__|\.pyc|models)" \
    "${LOCAL_DIR}" |
while read -r _dir _event _file; do
    do_sync
done
