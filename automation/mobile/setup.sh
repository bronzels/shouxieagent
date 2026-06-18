#!/usr/bin/env bash
# 酷狗 VIP 看广告自动化 — 环境安装（纯 adb 方案，已弃用 Appium）
# 用法：cd automation/mobile && bash setup.sh
#
# 说明：实测 Appium/UiAutomator2 在酷狗上会把 screenshot/tap/getPageSource 拖到 50-88s
# 并崩溃，故弃用 Appium，全程走 adb 原语（screencap / input tap / monkey / wm size /
# uiautomator dump）。本脚本只需安装 adb(platform-tools) 与测试用 Python 依赖。
set -uo pipefail

MOBILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$MOBILE_DIR/.tools"
REPO_ROOT="$(cd "$MOBILE_DIR/../.." && pwd)"
VENV_PY="$REPO_ROOT/.venv/Scripts/python.exe"   # Windows venv
[ -f "$VENV_PY" ] || VENV_PY="$REPO_ROOT/.venv/bin/python"  # Linux/WSL venv
mkdir -p "$TOOLS_DIR"

echo "==== [1/3] Android platform-tools (adb) ===="
if command -v adb >/dev/null 2>&1; then
  echo "adb 已存在: $(command -v adb)"
elif [ -x "$TOOLS_DIR/platform-tools/adb.exe" ] || [ -x "$TOOLS_DIR/platform-tools/adb" ]; then
  echo "adb 已在 $TOOLS_DIR/platform-tools"
else
  echo "下载 platform-tools ..."
  curl -L -o "$TOOLS_DIR/platform-tools.zip" \
    https://dl.google.com/android/repository/platform-tools-latest-windows.zip \
    || { echo "❌ 下载失败，请手工下载 platform-tools 解压到 $TOOLS_DIR/platform-tools 后重跑"; exit 1; }
  unzip -o "$TOOLS_DIR/platform-tools.zip" -d "$TOOLS_DIR" >/dev/null
  rm -f "$TOOLS_DIR/platform-tools.zip"
fi
ADB_BIN="$(command -v adb || echo "$TOOLS_DIR/platform-tools/adb.exe")"

echo "==== [2/3] Python 依赖到 .venv ===="
[ -f "$VENV_PY" ] || { echo "❌ 未找到 .venv，请先在仓库根目录 python -m venv .venv"; exit 1; }
# device.py 纯 adb，无需 Appium-Python-Client；vision.py 需 ui_tars/openai/httpx
"$VENV_PY" -m pip install -U "ui_tars" "openai" "httpx" "pytest" "pytest-asyncio"
"$VENV_PY" -m pip freeze > "$REPO_ROOT/requirements-test.txt"

echo "==== [3/3] 自检 ===="
echo "--- adb devices ---"; "$ADB_BIN" devices
echo "✅ setup 完成。确保手机：USB 已连、USB 调试已开、已授权本机调试。"
echo "   page_source 走 adb shell uiautomator dump（系统内置，无需安装）。"
