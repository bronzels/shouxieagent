# 酷狗看广告攒 VIP 时长自动化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `automation/mobile/` 下交付一个基于 Appium 的 Python 命令程序，无论 Android 手机当前处于任何屏幕/app 状态，运行后都能打开酷狗音乐、反复看广告，把 VIP/免费畅听剩余时长攒到 ≥14 小时。

**Architecture:** 分四层——`device.py`（Appium/UiAutomator2 驱动封装：截图、点击、读 XML、拉起 app）、`vision.py`（自包含复刻 web 的本地 UI-TARS grounding + OpenRouter 免费模型链 + fallback，对外暴露 `locate()`/`read_text()`）、`parsers.py`（纯函数：时长解析、坐标换算、XML 关键字匹配）、`agent.py`（主循环：状态归位 → 选择器优先+视觉兜底导航 → 看广告 → 读时长直到 ≥14h）。`kugou_vip_ads.py` 为 CLI 入口。

**Tech Stack:** Python 3.14（根目录 `.venv`）、Appium-Python-Client（UiAutomator2）、Android platform-tools(adb)、Appium Server(node)、`httpx`、`openai`（连本地 UI-TARS）、`ui_tars`（动作解析）、`pytest`/`pytest-asyncio`。

## Global Constraints

- 测试代码必须跑在根目录 `.venv`（`AGENTS.md` §17 隔离原则）；每次装新包后 `pip freeze > requirements-test.txt` 并提交。
- agent 所有面向用户的输出用**中文**。
- TDD 铁律：每个组件先写失败测试 → 实现 → 测试全过 → git commit/push 才进下一步（`AGENTS.md` §2）。
- 单元测试为纯函数/mock，测完不留数据；集成/E2E 测试需真机在线（`AGENTS.md` §11）。
- 酷狗包名预期 `com.kugou.android`，运行时以 `adb shell` 实测为准。
- 单次广告 ≤60 秒、无累计上限；目标默认 14 小时。
- 本地 UI-TARS 默认地址 `http://192.168.3.14:8000/v1`；OpenRouter key 由 `--openrouter-key`/环境变量 `OPENROUTER_API_KEY` 提供。
- `vision.py` **不得** import `automation/web/zhipin_apply.py`（其顶层引入 pyautogui/playwright），需自包含复刻所需逻辑。
- `automation/mobile/.tools/`（adb/JDK 解压目录）加入 `.gitignore`，不入库。
- **例外说明（需用户知悉）：** Appium Server 与 adb 作为开发/测试工具运行在宿主机（不进 Docker），因为 USB 真机直通在 Windows 容器内不可行；这是对 `AGENTS.md` §17「服务组件容器化」的合理例外。

---

## Task 1: 环境安装 `setup.sh` + `.gitignore`

**Files:**
- Create: `automation/mobile/setup.sh`
- Modify: `.gitignore`（追加 `automation/mobile/.tools/`）

**Interfaces:**
- Produces: 可用的 `adb`（在 `automation/mobile/.tools/platform-tools/`）、全局 `appium` + uiautomator2 驱动、`.venv` 内 `Appium-Python-Client`/`pytest`/`pytest-asyncio`/`ui_tars`/`openai`/`httpx`。脚本结束打印 `adb devices` 与 `appium driver list` 自检结果。

- [ ] **Step 1: 写 `.gitignore` 追加**

在 `.gitignore` 末尾追加：

```
# mobile automation 本地工具（adb/JDK 解压目录，不入库）
automation/mobile/.tools/
```

- [ ] **Step 2: 写 `setup.sh`**

```bash
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
```

- [ ] **Step 3: 运行 setup.sh 并自检**

Run: `cd automation/mobile && bash setup.sh`
Expected: 末尾 `adb devices` 列出真机（`<serial>\tdevice`），`appium driver list` 含 `uiautomator2`。若某步打印手工提示，按提示完成后重跑。

- [ ] **Step 4: 确认酷狗包名**

Run: `adb shell pm list packages | grep -i kugou`
Expected: 输出含 `package:com.kugou.android`（若不同，记录真实包名，后续任务用真实值替换）。

- [ ] **Step 5: Commit**

```bash
git add automation/mobile/setup.sh .gitignore requirements-test.txt
git commit -m "feat(mobile): 新增 Appium 环境安装脚本 setup.sh 与 .gitignore

安装 adb/JDK/Appium+uiautomator2/Python客户端，纯命令行优先，
不可CLI安装时停下提示手工完成。.tools/ 不入库。"
```

---

## Task 2: 纯函数工具 `parsers.py`

**Files:**
- Create: `automation/mobile/parsers.py`
- Test: `automation/mobile/tests/test_parsers.py`

**Interfaces:**
- Produces:
  - `parse_duration_to_minutes(text: str) -> int | None` — 从含时长的文本解析出分钟数；无法解析返回 `None`。
  - `norm_to_pixel(nx: float, ny: float, width: int, height: int) -> tuple[int, int]` — 0-1 归一化坐标 → 像素整数坐标。
  - `find_keyword_bounds(page_source_xml: str, keywords: list[str]) -> tuple[int, int] | None` — 在 UiAutomator2 XML 里找首个 text/content-desc 命中任一关键字的节点，返回其 `bounds` 中心像素坐标；无命中返回 `None`。
  - `extract_duration_from_xml(page_source_xml: str) -> int | None` — 扫描 XML 所有 text/content-desc 节点，对每个跑 `parse_duration_to_minutes`，返回**首个含「小时/分」时长**节点的分钟数（零模型读 VIP 剩余时长的首选路径）；无命中返回 `None`。

- [ ] **Step 1: 写失败测试**

```python
# automation/mobile/tests/test_parsers.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parsers import parse_duration_to_minutes, norm_to_pixel, find_keyword_bounds


def test_parse_hours_and_minutes():
    assert parse_duration_to_minutes("剩余3小时20分") == 200

def test_parse_minutes_only():
    assert parse_duration_to_minutes("免费畅听 200分钟") == 200

def test_parse_decimal_hours():
    assert parse_duration_to_minutes("VIP剩余3.5小时") == 210

def test_parse_hours_only():
    assert parse_duration_to_minutes("还有2小时") == 120

def test_parse_zero_or_expired():
    assert parse_duration_to_minutes("已过期") == 0

def test_parse_none_when_no_number():
    assert parse_duration_to_minutes("看广告领时长") is None

def test_norm_to_pixel():
    assert norm_to_pixel(0.5, 0.5, 1080, 2400) == (540, 1200)

def test_find_keyword_bounds_hit():
    xml = '<hierarchy><node text="看广告领时长" bounds="[100,200][300,260]"/></hierarchy>'
    assert find_keyword_bounds(xml, ["看广告"]) == (200, 230)

def test_find_keyword_bounds_miss():
    xml = '<hierarchy><node text="设置" bounds="[0,0][10,10]"/></hierarchy>'
    assert find_keyword_bounds(xml, ["看广告"]) is None

def test_extract_duration_from_xml_hit():
    xml = ('<hierarchy>'
           '<node text="看广告" bounds="[0,0][10,10]"/>'
           '<node content-desc="当前可听 剩余3小时20分" bounds="[0,0][10,10]"/>'
           '</hierarchy>')
    from parsers import extract_duration_from_xml
    assert extract_duration_from_xml(xml) == 200

def test_extract_duration_from_xml_miss():
    from parsers import extract_duration_from_xml
    xml = '<hierarchy><node text="看广告领时长" bounds="[0,0][10,10]"/></hierarchy>'
    assert extract_duration_from_xml(xml) is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest automation/mobile/tests/test_parsers.py -v`
Expected: FAIL（`ModuleNotFoundError: parsers` 或 `cannot import name`）。

- [ ] **Step 3: 实现 `parsers.py`**

```python
# automation/mobile/parsers.py
"""纯函数工具：时长解析、归一化坐标换算、UiAutomator2 XML 关键字定位。"""
import re
import xml.etree.ElementTree as ET


def parse_duration_to_minutes(text: str) -> int | None:
    """从含时长的文本解析分钟数。支持「X小时Y分」「X分钟」「X.Y小时」「X小时」；
    含「过期/已用完/0」等视为 0；无任何数字返回 None。"""
    if text is None:
        return None
    if re.search(r"过期|已用完|用完|结束", text):
        return 0
    # X小时Y分
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:小时|时|h)\s*(\d+)\s*(?:分钟|分|m)", text)
    if m:
        return int(round(float(m.group(1)) * 60)) + int(m.group(2))
    # X小时 / X.Y小时
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:小时|时|h)\b", text)
    if m:
        return int(round(float(m.group(1)) * 60))
    # X分钟
    m = re.search(r"(\d+)\s*(?:分钟|分|m)\b", text)
    if m:
        return int(m.group(1))
    # 仅一个数字（兜底，按分钟）
    m = re.search(r"(\d+)", text)
    if m:
        return int(m.group(1))
    return None


def norm_to_pixel(nx: float, ny: float, width: int, height: int) -> tuple[int, int]:
    """0-1 归一化坐标 → 像素整数坐标。"""
    return (int(round(nx * width)), int(round(ny * height)))


def find_keyword_bounds(page_source_xml: str, keywords: list[str]) -> tuple[int, int] | None:
    """在 UiAutomator2 dump 的 XML 中找首个 text/content-desc 命中任一关键字的节点，
    返回 bounds 中心像素坐标 (cx, cy)；无命中返回 None。"""
    try:
        root = ET.fromstring(page_source_xml)
    except ET.ParseError:
        return None
    for node in root.iter():
        label = (node.get("text") or "") + " " + (node.get("content-desc") or "")
        if any(kw in label for kw in keywords):
            b = node.get("bounds") or ""
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
            if m:
                x1, y1, x2, y2 = map(int, m.groups())
                return ((x1 + x2) // 2, (y1 + y2) // 2)
    return None


def extract_duration_from_xml(page_source_xml: str) -> int | None:
    """扫描 XML 所有 text/content-desc，返回首个**明确含时长单位**节点的分钟数；无则 None。
    只接受含「小时/时/分钟/分」单位的文本，避免误命中界面里的无关数字。"""
    try:
        root = ET.fromstring(page_source_xml)
    except ET.ParseError:
        return None
    for node in root.iter():
        label = (node.get("text") or "") + " " + (node.get("content-desc") or "")
        if not re.search(r"小时|时|分钟|分|畅听|时长", label):
            continue
        mins = parse_duration_to_minutes(label)
        if mins is not None and re.search(r"(\d+(?:\.\d+)?)\s*(?:小时|时|分钟|分|h|m)", label):
            return mins
    return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python -m pytest automation/mobile/tests/test_parsers.py -v`
Expected: `11 passed`。

- [ ] **Step 5: Commit**

```bash
git add automation/mobile/parsers.py automation/mobile/tests/test_parsers.py
git commit -m "feat(mobile): parsers.py 纯函数(时长解析/坐标换算/XML关键字定位)+单元测试"
```

---

## Task 3: 视觉/LLM 层 `vision.py`

**Files:**
- Create: `automation/mobile/vision.py`
- Test: `automation/mobile/tests/test_vision.py`

**Interfaces:**
- Consumes: 环境全局 `OPENROUTER_API_KEY`、`UITARS_LOCAL_URL`。
- Produces：**只用 UI-TARS 这一类模型**，不引入独立文字/多模态模型链。
  - `configure(openrouter_key: str, uitars_local_url: str) -> None` — 设置模块级配置。
  - `async locate(image_path: str, instruction: str, width: int, height: int) -> tuple[int, int] | None` — 返回点击像素坐标（本地 UI-TARS 优先，失败 fallback OpenRouter 同款 ui-tars）。
  - `async read_text(image_path: str, question: str) -> str` — **UI-TARS OCR 兜底**（仅当 page_source 拿不到时长才调）：给同一本地 UI-TARS 发普通 OCR 问题（不用 COMPUTER_USE_DOUBAO 动作 prompt），失败 fallback OpenRouter 同款 ui-tars。
  - 内部：`image_to_base64`、`_post_uitars_local_sync`、`_post_openrouter`（**仅用于以 `models=[UITARS_MODEL]` 调 OpenRouter 上的同款 ui-tars 做 fallback**）、`call_uitars`、`_parse_point`。借鉴自 `zhipin_apply.py`，去除 GUI 依赖与文字模型链。

- [ ] **Step 1: 写失败测试（mock 网络）**

```python
# automation/mobile/tests/test_vision.py
import sys, base64
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import vision


@pytest.fixture
def tiny_png(tmp_path):
    # 1x1 PNG
    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    p = tmp_path / "s.png"
    p.write_bytes(data)
    return str(p)


@pytest.mark.asyncio
async def test_locate_parses_uitars_point(tiny_png, monkeypatch):
    async def fake_call_uitars(image_path, task_prompt):
        return "Thought: click button\nAction: click(start_box='<point>500 250</point>')"
    monkeypatch.setattr(vision, "call_uitars", fake_call_uitars)
    xy = await vision.locate(tiny_png, "点击看广告按钮", 1000, 1000)
    assert xy == (500, 250)


@pytest.mark.asyncio
async def test_read_text_uses_uitars_ocr(tiny_png, monkeypatch):
    # read_text 走 UI-TARS（本地 server），不走独立文字模型
    def fake_local_sync(payload):
        return {"choices": [{"message": {"content": "剩余3小时20分"}}]}
    monkeypatch.setattr(vision, "_post_uitars_local_sync", fake_local_sync)
    out = await vision.read_text(tiny_png, "VIP剩余时长是多少")
    assert "3小时20分" in out


def test_no_text_model_chain():
    # 确认没有照搬 web 的文字/多模态模型链
    assert not hasattr(vision, "VERIFY_MODELS_MULTIMODAL")
    assert not hasattr(vision, "VERIFY_MODELS_TEXT")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest automation/mobile/tests/test_vision.py -v`
Expected: FAIL（`ModuleNotFoundError: vision`）。

- [ ] **Step 3: 实现 `vision.py`**

```python
# automation/mobile/vision.py
"""视觉/LLM 层：本地 UI-TARS grounding + OpenRouter 免费模型链 fallback。
自包含复刻自 automation/web/zhipin_apply.py（去除 pyautogui/playwright 依赖）。"""
import asyncio
import base64
import json
import re

import httpx

OPENROUTER_API_KEY = ""
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
UITARS_LOCAL_URL = "http://192.168.3.14:8000/v1"
UITARS_MODEL = "bytedance/ui-tars-1.5-7b"

# 本任务只用 UI-TARS 这一类 GUI grounding 模型，不引入独立文字/多模态模型链。
# OpenRouter 仅作本地 UI-TARS 不可达时的同款模型 fallback（models=[UITARS_MODEL]）。


def configure(openrouter_key: str, uitars_local_url: str) -> None:
    global OPENROUTER_API_KEY, UITARS_LOCAL_URL
    if openrouter_key:
        OPENROUTER_API_KEY = openrouter_key
    if uitars_local_url:
        UITARS_LOCAL_URL = uitars_local_url


def image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


async def _post_openrouter(payload: dict, models: list = None, paid_models: list = None) -> dict:
    """OpenRouter 免费模型 fallback 链：逐个 model 试，全失败退避重试整轮（最多3轮）。"""
    model_list = models or [payload.get("model")]
    delay = 4.0
    last_err = "unknown"
    async with httpx.AsyncClient(timeout=120.0) as client:
        for rnd in range(3):
            for model in model_list:
                body = dict(payload)
                body["model"] = model
                try:
                    r = await client.post(
                        f"{OPENROUTER_BASE_URL}/chat/completions",
                        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                        json=body,
                    )
                    if r.status_code == 200:
                        return r.json()
                    last_err = f"{model} HTTP {r.status_code}"
                except Exception as e:  # noqa: BLE001
                    last_err = f"{model} {str(e)[:60]}"
            if rnd < 2:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 40)
    raise RuntimeError(f"OpenRouter 免费模型多轮失败: {last_err}")


def _post_uitars_local_sync(payload: dict) -> dict:
    """连本地 llama-cpp-python server（OpenAI 兼容），同步调用。"""
    from openai import OpenAI
    client = OpenAI(base_url=UITARS_LOCAL_URL, api_key="none", timeout=120.0)
    model = client.models.list().data[0].id
    resp = client.chat.completions.create(
        model=model,
        messages=payload["messages"],
        max_tokens=payload.get("max_tokens", 512),
        frequency_penalty=1,
    )
    return {"choices": [{"message": {"content": resp.choices[0].message.content}}]}


async def call_uitars(image_path: str, task_prompt: str) -> str:
    """UI-TARS grounding：本地优先，连续失败 fallback 到 OpenRouter UI-TARS。返回含 Action 的文本。"""
    from ui_tars.prompt import COMPUTER_USE_DOUBAO
    img_b64 = image_to_base64(image_path)
    prompt_text = COMPUTER_USE_DOUBAO.format(instruction=task_prompt, language="Chinese")
    payload = {
        "model": UITARS_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": prompt_text},
            ],
        }],
        "max_tokens": 512,
    }
    # 本地优先，3 次重试
    for attempt in range(3):
        try:
            result = await asyncio.to_thread(_post_uitars_local_sync, payload)
            content = result["choices"][0]["message"]["content"]
            if content and content.strip():
                return content
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print(f"  ⚠️ 本地 UI-TARS 连续失败({str(e)[:60]})，fallback OpenRouter", flush=True)
            await asyncio.sleep(2.0 * (attempt + 1))
    # fallback：OpenRouter UI-TARS
    result = await _post_openrouter(payload, models=[UITARS_MODEL])
    return result["choices"][0]["message"]["content"]


def _parse_point(response: str) -> tuple[float, float] | None:
    """解析 UI-TARS 响应中的坐标，返回 0-1 归一化 (nx, ny)。支持 <point>X Y</point>/(X,Y)/[x1,y1,...]。
    优先用 ui_tars 包，失败则正则兜底（坐标系 0-1000）。"""
    try:
        from ui_tars.action_parser import parse_action_to_structure_output
        parsed = parse_action_to_structure_output(
            response, factor=1000, origin_resized_height=1000,
            origin_resized_width=1000, model_type="qwen25vl")
        if parsed:
            box = json.loads(parsed[0]["action_inputs"]["start_box"])
            return (box[0], box[1])
    except Exception:  # noqa: BLE001
        pass
    m = re.search(r"<point>\s*(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)\s*</point>", response) \
        or re.search(r"\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\)", response) \
        or re.search(r"\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)", response)
    if m:
        return (float(m.group(1)) / 1000.0, float(m.group(2)) / 1000.0)
    return None


async def locate(image_path: str, instruction: str, width: int, height: int) -> tuple[int, int] | None:
    """返回点击像素坐标 (px, py)；定位失败返回 None。"""
    resp = await call_uitars(image_path, instruction)
    norm = _parse_point(resp)
    if norm is None:
        return None
    return (int(round(norm[0] * width)), int(round(norm[1] * height)))


async def read_text(image_path: str, question: str) -> str:
    """UI-TARS OCR 兜底：用同一 UI-TARS 模型读屏回答（普通问题，非动作 prompt），
    不使用独立文字/多模态模型。本地优先，失败 fallback OpenRouter 同款 ui-tars。"""
    img_b64 = image_to_base64(image_path)
    payload = {
        "model": UITARS_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": question},
            ],
        }],
        "max_tokens": 256,
    }
    try:
        result = await asyncio.to_thread(_post_uitars_local_sync, payload)
        content = result["choices"][0]["message"]["content"]
        if content and content.strip():
            return content
    except Exception:  # noqa: BLE001
        pass
    result = await _post_openrouter(payload, models=[UITARS_MODEL])
    return result["choices"][0]["message"]["content"] or ""
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python -m pytest automation/mobile/tests/test_vision.py -v`
Expected: `3 passed`。

- [ ] **Step 5: Commit**

```bash
git add automation/mobile/vision.py automation/mobile/tests/test_vision.py
git commit -m "feat(mobile): vision.py 只用UI-TARS(定位+OCR兜底),不引入文字模型链,本地优先+OpenRouter同款fallback+单元测试"
```

---

## Task 4: 设备驱动层 `device.py`

**Files:**
- Create: `automation/mobile/device.py`
- Test: `automation/mobile/tests/test_device_integration.py`

**Interfaces:**
- Consumes: Appium Server（默认 `http://127.0.0.1:4723`）、真机在线。
- Produces: `Device` 类：
  - `Device(appium_url="http://127.0.0.1:4723", pkg="com.kugou.android")`
  - `start() -> None` / `quit() -> None`
  - `screen_size() -> tuple[int, int]`
  - `screenshot(path: str) -> str`
  - `tap(x: int, y: int) -> None`
  - `back() -> None`
  - `swipe(x1, y1, x2, y2, ms=400) -> None`
  - `page_source() -> str`
  - `activate_app() -> None`（把 `pkg` 拉到前台）
  - `current_package() -> str`

- [ ] **Step 1: 写集成测试（真机在线则跑，否则 skip）**

```python
# automation/mobile/tests/test_device_integration.py
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from device import Device

APPIUM = os.environ.get("APPIUM_URL", "http://127.0.0.1:4723")
PKG = os.environ.get("KUGOU_PKG", "com.kugou.android")


def _appium_up() -> bool:
    import httpx
    try:
        return httpx.get(f"{APPIUM}/status", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _appium_up(), reason="Appium server 未运行/真机未连接")


@pytest.fixture(scope="module")
def dev():
    d = Device(appium_url=APPIUM, pkg=PKG)
    d.start()
    yield d
    d.quit()


def test_screen_size_positive(dev):
    w, h = dev.screen_size()
    assert w > 0 and h > 0

def test_screenshot_created(dev, tmp_path):
    p = dev.screenshot(str(tmp_path / "shot.png"))
    assert Path(p).exists() and Path(p).stat().st_size > 0

def test_activate_kugou_foreground(dev):
    dev.activate_app()
    assert PKG in dev.current_package()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest automation/mobile/tests/test_device_integration.py -v`
Expected: FAIL（`ModuleNotFoundError: device`）；若 Appium 未启动则全部 SKIP（先确保 `appium` 在另一终端运行：`appium`）。

- [ ] **Step 3: 实现 `device.py`**

```python
# automation/mobile/device.py
"""Appium(UiAutomator2) 驱动封装。"""
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.extensions.android.nativekey import AndroidKey


class Device:
    def __init__(self, appium_url: str = "http://127.0.0.1:4723",
                 pkg: str = "com.kugou.android"):
        self.appium_url = appium_url
        self.pkg = pkg
        self.driver = None

    def start(self) -> None:
        opts = UiAutomator2Options()
        opts.platform_name = "Android"
        opts.automation_name = "UiAutomator2"
        # 不指定 appPackage/appActivity，连当前会话；用 activate_app 控制前台
        opts.no_reset = True
        opts.new_command_timeout = 600
        self.driver = webdriver.Remote(self.appium_url, options=opts)

    def quit(self) -> None:
        if self.driver:
            self.driver.quit()
            self.driver = None

    def screen_size(self) -> tuple[int, int]:
        s = self.driver.get_window_size()
        return (s["width"], s["height"])

    def screenshot(self, path: str) -> str:
        self.driver.get_screenshot_as_file(path)
        return path

    def tap(self, x: int, y: int) -> None:
        self.driver.tap([(x, y)])

    def back(self) -> None:
        self.driver.press_keycode(AndroidKey.BACK)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 400) -> None:
        self.driver.swipe(x1, y1, x2, y2, ms)

    def page_source(self) -> str:
        return self.driver.page_source

    def activate_app(self) -> None:
        self.driver.activate_app(self.pkg)

    def current_package(self) -> str:
        return self.driver.current_package or ""
```

- [ ] **Step 4: 运行测试确认通过**

前提：另一终端已运行 `appium`，真机已连。
Run: `.venv/Scripts/python -m pytest automation/mobile/tests/test_device_integration.py -v`
Expected: `3 passed`（酷狗被拉到前台）。

- [ ] **Step 5: Commit**

```bash
git add automation/mobile/device.py automation/mobile/tests/test_device_integration.py
git commit -m "feat(mobile): device.py Appium驱动封装(截图/点击/读XML/拉起app)+集成测试"
```

---

## Task 5: 主循环 `agent.py`

**Files:**
- Create: `automation/mobile/agent.py`
- Test: `automation/mobile/tests/test_agent.py`

**Interfaces:**
- Consumes: `Device`（Task 4）、`vision.locate`/`vision.read_text`（Task 3）、`parsers`（Task 2）。
- Produces:
  - `class KugouAdsAgent` 接受注入的 `device` 与 `vision` 模块（便于 mock 测试）。
  - `async def reset_to_kugou_home(self) -> None` — 状态归位：`activate_app` + 必要时多次 `back`。
  - `async def navigate_to_ads_page(self) -> bool` — 选择器优先 + 视觉兜底，进入看广告页。
  - `async def read_remaining_minutes(self) -> int | None` — **首选 `parsers.extract_duration_from_xml(page_source)`（零模型）**；XML 取不到才回退 截图 + `vision.read_text`（UI-TARS OCR） + `parse_duration_to_minutes`。
  - `async def watch_one_ad(self) -> bool` — 点看广告 → 等待 ≤60s → 关闭「×」。
  - `async def run(self, target_minutes: int, max_ads: int) -> int` — 主循环，返回最终剩余分钟数。停止条件：`remaining >= target_minutes` 或达到 `max_ads`。

- [ ] **Step 1: 写失败测试（注入 fake device + fake vision）**

```python
# automation/mobile/tests/test_agent.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from agent import KugouAdsAgent


class FakeDevice:
    def __init__(self):
        self.activated = 0
        self.taps = []
    def screen_size(self): return (1000, 2000)
    def screenshot(self, path): Path(path).write_bytes(b"x"); return path
    def tap(self, x, y): self.taps.append((x, y))
    def back(self): pass
    def page_source(self): return '<hierarchy><node text="看广告领时长" bounds="[0,0][100,100]"/></hierarchy>'
    def activate_app(self): self.activated += 1
    def current_package(self): return "com.kugou.android"


class FakeVision:
    def __init__(self, minutes_seq):
        self.minutes_seq = list(minutes_seq)
        self.read_calls = 0
    async def locate(self, image_path, instruction, w, h): return (50, 50)
    async def read_text(self, image_path, question):
        # 每次读屏返回序列里的下一个时长文本
        i = min(self.read_calls, len(self.minutes_seq) - 1)
        self.read_calls += 1
        return f"剩余{self.minutes_seq[i]}分钟"


@pytest.mark.asyncio
async def test_run_stops_when_target_reached():
    dev = FakeDevice()
    vis = FakeVision(minutes_seq=[60, 600, 900])  # 第三次读到 900>=840 停止
    agent = KugouAdsAgent(device=dev, vision=vis, sleep=_no_sleep)
    final = await agent.run(target_minutes=840, max_ads=50)
    assert final >= 840
    assert dev.activated >= 1  # 启动时归位过


@pytest.mark.asyncio
async def test_run_stops_at_max_ads():
    dev = FakeDevice()
    vis = FakeVision(minutes_seq=[10, 20, 30])  # 永远到不了 840
    agent = KugouAdsAgent(device=dev, vision=vis, sleep=_no_sleep)
    final = await agent.run(target_minutes=840, max_ads=2)
    assert final < 840  # 被 max_ads 截断


async def _no_sleep(_seconds):
    return None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest automation/mobile/tests/test_agent.py -v`
Expected: FAIL（`ModuleNotFoundError: agent`）。

- [ ] **Step 3: 实现 `agent.py`**

```python
# automation/mobile/agent.py
"""主循环：状态归位 → 导航到看广告页 → 看广告 → 读时长直到 ≥ 目标。"""
import asyncio

import parsers

ENTRY_KEYWORDS = ["看广告", "免费听歌", "免费畅听", "领时长", "广告得", "看视频"]
WATCH_KEYWORDS = ["看广告", "看视频", "立即领取", "领取", "观看"]
CLOSE_KEYWORDS = ["关闭", "跳过", "×", "X"]
REMAIN_QUESTION = "这个页面显示的VIP或免费畅听剩余时长是多少？只回答时长，如『3小时20分』。"


class KugouAdsAgent:
    def __init__(self, device, vision, sleep=asyncio.sleep):
        self.dev = device
        self.vis = vision
        self.sleep = sleep
        self._shot_i = 0

    def _shot(self) -> str:
        self._shot_i += 1
        path = f"automation/mobile/reports/screenshots/run-{self._shot_i:04d}.png"
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return self.dev.screenshot(path)

    async def _tap_keyword_or_vision(self, keywords, instruction) -> bool:
        """选择器优先：page_source 命中关键字直接点；否则视觉兜底定位。"""
        xml = self.dev.page_source()
        hit = parsers.find_keyword_bounds(xml, keywords)
        if hit:
            self.dev.tap(*hit)
            return True
        shot = self._shot()
        w, h = self.dev.screen_size()
        xy = await self.vis.locate(shot, instruction, w, h)
        if xy:
            self.dev.tap(*xy)
            return True
        return False

    async def reset_to_kugou_home(self) -> None:
        self.dev.activate_app()
        await self.sleep(2.0)
        # 若不在酷狗前台，再拉一次
        if "com.kugou" not in self.dev.current_package():
            self.dev.activate_app()
            await self.sleep(2.0)

    async def navigate_to_ads_page(self) -> bool:
        for _ in range(5):
            if await self._tap_keyword_or_vision(ENTRY_KEYWORDS, "点击进入看广告领VIP听歌时长的入口"):
                await self.sleep(2.0)
                return True
            self.dev.back()
            await self.sleep(1.0)
        return False

    async def read_remaining_minutes(self) -> int | None:
        # 首选：零模型从 page_source XML 直接取时长
        mins = parsers.extract_duration_from_xml(self.dev.page_source())
        if mins is not None:
            return mins
        # 回退：UI-TARS OCR 读屏
        shot = self._shot()
        txt = await self.vis.read_text(shot, REMAIN_QUESTION)
        return parsers.parse_duration_to_minutes(txt)

    async def watch_one_ad(self) -> bool:
        if not await self._tap_keyword_or_vision(WATCH_KEYWORDS, "点击『看广告』按钮开始看广告"):
            return False
        await self.sleep(35.0)   # 广告 ≤60s，先等一段
        # 轮询找关闭按钮，最多再等 40s
        for _ in range(8):
            shot = self._shot()
            w, h = self.dev.screen_size()
            xml = self.dev.page_source()
            hit = parsers.find_keyword_bounds(xml, CLOSE_KEYWORDS)
            if not hit:
                hit = await self.vis.locate(shot, "点击右上角关闭广告的×按钮", w, h)
            if hit:
                self.dev.tap(*hit)
                await self.sleep(2.0)
                return True
            await self.sleep(5.0)
        return False

    async def run(self, target_minutes: int, max_ads: int) -> int:
        await self.reset_to_kugou_home()
        await self.navigate_to_ads_page()
        remaining = await self.read_remaining_minutes() or 0
        print(f"  ▶ 初始剩余时长: {remaining} 分钟", flush=True)
        ads = 0
        while remaining < target_minutes and ads < max_ads:
            ok = await self.watch_one_ad()
            ads += 1
            await self.sleep(2.0)
            new_remaining = await self.read_remaining_minutes()
            if new_remaining is not None:
                remaining = new_remaining
            print(f"  ▶ 已看 {ads} 次广告，当前剩余: {remaining} 分钟 "
                  f"(目标 {target_minutes})", flush=True)
            if not ok:
                # 看广告失败 → 重新导航一次
                await self.navigate_to_ads_page()
        if remaining < target_minutes:
            print(f"  ⚠️ 达到 max_ads={max_ads} 仍未到目标，最终 {remaining} 分钟", flush=True)
        else:
            print(f"  ✅ 已达目标，最终剩余 {remaining} 分钟 (≥{target_minutes})", flush=True)
        return remaining
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python -m pytest automation/mobile/tests/test_agent.py -v`
Expected: `2 passed`。

- [ ] **Step 5: Commit**

```bash
git add automation/mobile/agent.py automation/mobile/tests/test_agent.py
git commit -m "feat(mobile): agent.py 主循环(归位/导航/看广告/读时长直到≥目标)+注入式单元测试"
```

---

## Task 6: CLI 入口 `kugou_vip_ads.py`

**Files:**
- Create: `automation/mobile/kugou_vip_ads.py`
- Test: `automation/mobile/tests/test_cli.py`

**Interfaces:**
- Consumes: `KugouAdsAgent`、`Device`、`vision`。
- Produces: CLI：`python kugou_vip_ads.py --target-hours 14 [--openrouter-key K] [--uitars-local-url U] [--max-ads N] [--dry-run] [--appium-url] [--pkg]`。
  - `build_arg_parser() -> argparse.ArgumentParser`（可单测）。
  - `async def main_async(args) -> int`。

- [ ] **Step 1: 写失败测试（只测参数解析，不连真机）**

```python
# automation/mobile/tests/test_cli.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kugou_vip_ads import build_arg_parser


def test_default_target_hours():
    args = build_arg_parser().parse_args([])
    assert args.target_hours == 14
    assert args.uitars_local_url == "http://192.168.3.14:8000/v1"

def test_override_args():
    args = build_arg_parser().parse_args(
        ["--target-hours", "2", "--max-ads", "5", "--dry-run"])
    assert args.target_hours == 2
    assert args.max_ads == 5
    assert args.dry_run is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest automation/mobile/tests/test_cli.py -v`
Expected: FAIL（`ModuleNotFoundError: kugou_vip_ads`）。

- [ ] **Step 3: 实现 `kugou_vip_ads.py`**

```python
# automation/mobile/kugou_vip_ads.py
"""CLI 入口：酷狗看广告攒 VIP 时长。任意手机状态下运行均可完成。"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import vision
from agent import KugouAdsAgent
from device import Device


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="酷狗看广告攒 VIP 听歌时长自动化")
    p.add_argument("--target-hours", type=float, default=14, help="目标累计时长(小时)，默认14")
    p.add_argument("--openrouter-key", default=os.environ.get("OPENROUTER_API_KEY", ""),
                   help="OpenRouter API key（默认读环境变量 OPENROUTER_API_KEY）")
    p.add_argument("--uitars-local-url", default="http://192.168.3.14:8000/v1",
                   help="本地 UI-TARS server 地址（/v1 前缀）")
    p.add_argument("--max-ads", type=int, default=100, help="安全上限：最多看多少次广告")
    p.add_argument("--appium-url", default="http://127.0.0.1:4723")
    p.add_argument("--pkg", default="com.kugou.android", help="酷狗包名")
    p.add_argument("--dry-run", action="store_true",
                   help="只归位+导航+读当前时长，不真正看广告")
    return p


async def main_async(args) -> int:
    vision.configure(args.openrouter_key, args.uitars_local_url)
    dev = Device(appium_url=args.appium_url, pkg=args.pkg)
    dev.start()
    try:
        agent = KugouAdsAgent(device=dev, vision=vision)
        if args.dry_run:
            await agent.reset_to_kugou_home()
            await agent.navigate_to_ads_page()
            mins = await agent.read_remaining_minutes()
            print(f"✅ dry-run：当前剩余时长 {mins} 分钟", flush=True)
            return 0
        target_minutes = int(round(args.target_hours * 60))
        final = await agent.run(target_minutes=target_minutes, max_ads=args.max_ads)
        return 0 if final >= target_minutes else 2
    finally:
        dev.quit()


def main() -> None:
    args = build_arg_parser().parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python -m pytest automation/mobile/tests/test_cli.py -v`
Expected: `2 passed`。

- [ ] **Step 5: 全量单测 + Commit**

Run: `.venv/Scripts/python -m pytest automation/mobile/tests/test_parsers.py automation/mobile/tests/test_vision.py automation/mobile/tests/test_agent.py automation/mobile/tests/test_cli.py -v`
Expected: 全部 PASS。

```bash
git add automation/mobile/kugou_vip_ads.py automation/mobile/tests/test_cli.py
git commit -m "feat(mobile): kugou_vip_ads.py CLI入口(--target-hours/--dry-run等)+参数解析单测"
```

---

## Task 7: 真机 E2E 验证 + 测试报告

**Files:**
- Create: `automation/mobile/tests/e2e/test_e2e_dryrun.py`
- Create: `reports/step-mobile-e2e-2026-06-18.md`（测试报告，含截图引用 + 多模态核验）

**Interfaces:**
- Consumes: 全部上游组件、真机在线、`appium` 运行中、本地 UI-TARS 或 OpenRouter 可达。

- [ ] **Step 1: 先跑 dry-run E2E（不真看广告，验证归位+导航+读时长链路）**

```python
# automation/mobile/tests/e2e/test_e2e_dryrun.py
import sys, os, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import vision
from agent import KugouAdsAgent
from device import Device

APPIUM = os.environ.get("APPIUM_URL", "http://127.0.0.1:4723")


def _appium_up():
    import httpx
    try:
        return httpx.get(f"{APPIUM}/status", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _appium_up(), reason="Appium/真机未就绪")


@pytest.mark.asyncio
async def test_dryrun_reaches_ads_page_and_reads_time():
    vision.configure(os.environ.get("OPENROUTER_API_KEY", ""),
                     os.environ.get("UITARS_LOCAL_URL", "http://192.168.3.14:8000/v1"))
    dev = Device(appium_url=APPIUM); dev.start()
    try:
        agent = KugouAdsAgent(device=dev, vision=vision)
        await agent.reset_to_kugou_home()
        assert "com.kugou" in dev.current_package()
        ok = await agent.navigate_to_ads_page()
        assert ok, "未能导航到看广告页"
        mins = await agent.read_remaining_minutes()
        assert mins is not None, "未能读出剩余时长"
        print(f"E2E dry-run 读到剩余 {mins} 分钟")
    finally:
        dev.quit()
```

Run: `.venv/Scripts/python -m pytest automation/mobile/tests/e2e/test_e2e_dryrun.py -v -s`
Expected: PASS；`reports/screenshots/` 下生成导航与读时长截图。

- [ ] **Step 2: Claude 亲自核验截图（AGENTS.md §4.0 强制）**

用 `Read` 读取 `automation/mobile/reports/screenshots/` 下关键截图，逐张判断：是否在酷狗看广告页、是否显示了真实剩余时长。在对话中按 §4.0 格式陈述结论（PASS/FAIL）。若空白/错页则停下修复 `navigate_to_ads_page`/关键字后重跑。

- [ ] **Step 3: 小目标真跑（`--target-hours` 设一个低值先验证看广告闭环）**

先用小目标验证「看广告→关闭→时长增长」闭环，避免一上来跑 14 小时：

Run: `.venv/Scripts/python automation/mobile/kugou_vip_ads.py --target-hours 0.5 --openrouter-key sk-or-... --max-ads 3`
Expected: 看 1～3 次广告，打印剩余时长有增长；`reports/screenshots/` 有看广告页与关闭后截图。

- [ ] **Step 4: 写测试报告 `reports/step-mobile-e2e-2026-06-18.md`**

按 AGENTS.md §3/§4.4 格式：测试环境、单元测试结果表、E2E case（截图引用 `![](screenshots/...)`、多模态核验结论）、pytest 输出摘要、已知问题。

- [ ] **Step 5: 正式跑满 14 小时（用户在场确认后）**

Run: `.venv/Scripts/python automation/mobile/kugou_vip_ads.py --target-hours 14 --openrouter-key sk-or-...`
Expected: 程序循环看广告直到读到剩余 ≥840 分钟后停止，打印 `✅ 已达目标`。

- [ ] **Step 6: Commit + Push**

```bash
git add automation/mobile/tests/e2e/ reports/step-mobile-e2e-2026-06-18.md
git commit -m "test(mobile): E2E dry-run+小目标真跑验证看广告闭环, 截图多模态核验, 测试报告"
git push origin main
```

---

## Self-Review

**Spec coverage:**
- §2 setup.sh → Task 1 ✅
- §3 device/vision/agent/CLI 分层 → Task 4/3/5/6 ✅
- §4 任意状态归位+选择器优先+视觉兜底+读时长停止 → Task 5（`reset_to_kugou_home`/`_tap_keyword_or_vision`/`run`）✅
- §5 测试（单元/集成/E2E + 多模态核验）→ Task 2/3（单元）、Task 4（集成）、Task 7（E2E+核验）✅
- §6 风险（视觉兜底、长时运行、本地不可达 fallback）→ Task 3 fallback、Task 5 失败重导航、Task 7 分阶段验证 ✅

**Placeholder scan:** 无 TBD/TODO；每个代码步骤含完整代码。E2E 真机步骤的「读屏关键字可能需按实际页面微调」属预期的真机适配，已在 Task 7 Step 2 给出「核验→修复关键字→重跑」闭环，非占位。

**Type consistency:** `locate(image_path, instruction, width, height) -> (px,py)|None`、`read_text(image_path, question) -> str`、`Device` 方法签名、`KugouAdsAgent(device, vision, sleep)` 在各 Task 间一致；`parse_duration_to_minutes`/`norm_to_pixel`/`find_keyword_bounds` 签名一致。

**已知需真机适配项（非计划缺陷）:** 酷狗看广告入口的确切文案/层级、广告关闭按钮形态因版本而异；Task 7 用「截图核验 + 调整 `ENTRY_KEYWORDS`/`CLOSE_KEYWORDS` 关键字 + UI-TARS 视觉兜底」吸收差异。
