#!/usr/bin/env bash
# 酷狗 VIP 看广告自动化 — Android + Appium 环境安装（Windows / Git-Bash 优先纯命令行）
# 用法：cd automation/mobile && bash setup.sh
set -uo pipefail

MOBILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$MOBILE_DIR/.tools"
REPO_ROOT="$(cd "$MOBILE_DIR/../.." && pwd)"
VENV_PY="$REPO_ROOT/.venv/Scripts/python.exe"   # Windows venv
[ -f "$VENV_PY" ] || VENV_PY="$REPO_ROOT/.venv/bin/python"  # Linux/WSL venv
mkdir -p "$TOOLS_DIR"

echo "==== [1/5] Android platform-tools (adb) ===="
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
export ANDROID_HOME="$TOOLS_DIR"
export PATH="$TOOLS_DIR/platform-tools:$PATH"

echo "==== [2/5] JDK 21 (Temurin) ===="
if command -v java >/dev/null 2>&1; then
  echo "java 已存在: $(java -version 2>&1 | head -1)"
elif command -v winget >/dev/null 2>&1; then
  winget install -e --id EclipseAdoptium.Temurin.21.JDK --accept-source-agreements --accept-package-agreements \
    || echo "⚠️ winget 安装 JDK 失败，若后续 appium uiautomator2 报缺 Java，请手工安装 Temurin 21 后重跑"
else
  echo "⚠️ 未找到 winget。请手工安装 Temurin JDK 21（https://adoptium.net/）后重跑 setup.sh。"
fi

echo "==== [3/5] Appium Server + uiautomator2 驱动 ===="
if command -v appium >/dev/null 2>&1; then
  echo "appium 已存在: $(appium --version)"
else
  npm install -g appium || { echo "❌ npm 安装 appium 失败"; exit 1; }
fi
appium driver list --installed 2>/dev/null | grep -q uiautomator2 \
  || appium driver install uiautomator2 \
  || echo "⚠️ uiautomator2 驱动安装失败，请检查网络后重跑"

echo "==== [4/5] Python 客户端到 .venv ===="
[ -f "$VENV_PY" ] || { echo "❌ 未找到 .venv，请先在仓库根目录 python -m venv .venv"; exit 1; }
"$VENV_PY" -m pip install -U "Appium-Python-Client" "ui_tars" "openai" "httpx" "pytest" "pytest-asyncio"
"$VENV_PY" -m pip freeze > "$REPO_ROOT/requirements-test.txt"

echo "==== [5/5] 自检 ===="
echo "--- adb devices ---"; adb devices
echo "--- appium driver list ---"; appium driver list --installed 2>/dev/null || true
echo "✅ setup 完成。若 adb devices 未列出设备：检查 USB 连接、手机已授权调试。"
