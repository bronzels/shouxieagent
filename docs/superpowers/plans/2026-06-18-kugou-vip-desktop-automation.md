# 酷狗刷 VIP 桌面自动化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Windows 桌面自动化（scrcpy 投屏 + pyautogui）操作手机酷狗 app，反复看广告领 VIP 时长到 14 小时，任意手机状态可启动。

**Architecture:** 四个聚焦模块——`scrcpy_window`（找窗口/截图/坐标映射）、`desktop_input`（UI-TARS 动作→pyautogui→scrcpy 手势翻译）、`uitars_agent`（薄封装复用 `UITarsClient`）、`task_kugou`（状态机编排）。主程序 `kugou_vip.py` 串起命令行入口。单模型 UI-TARS，本地优先 OpenRouter 兜底。

**Tech Stack:** Python 3.10、pyautogui、pygetwindow、pywin32（win32gui）、Pillow、mss、pytest、复用 `automation/ui-tars-server/inference_client.py` 的 `UITarsClient`。

## Global Constraints

- 开发根目录在 `automation/`；本项目代码全部在 `automation/desktop/`。
- 测试基于根目录 `.venv`，不用裸 python；新装包后 `pip freeze > requirements-test.txt` 并提交。
- 强制 TDD：实现代码 → 跑该 step 测试 → 全 PASS → commit/push → 下一步。
- 单元测试不连手机、不留数据；连手机的集成/E2E 测试**仅在用户显式说"开始测试"后执行**。
- agent 所有回复用中文。
- 复用 `automation/ui-tars-server/inference_client.py` 的 `UITarsClient`，不重写；不借鉴文字大模型管线。
- UI-TARS 坐标为 0–1000 相对坐标，`parse_action_simple` 已归一化为「截图像素坐标」。
- 小修改直接在 `main` 上做并 commit/push。

---

## File Structure

```
automation/desktop/
├── __init__.py
├── config.py             # 配置常量 + 命令行参数解析
├── scrcpy_window.py      # ScrcpyWindow：定位/前置/截图/坐标映射
├── desktop_input.py      # DesktopInput：动作字典 → pyautogui 调用
├── uitars_agent.py       # UITarsAgent：薄封装 UITarsClient（本地+兜底+history）
├── task_kugou.py         # KugouTask：状态机
├── kugou_vip.py          # main 入口
└── tests/
    ├── __init__.py
    ├── test_coord_mapping.py    # 坐标映射单元测试
    ├── test_desktop_input.py    # 手势翻译单元测试（mock pyautogui）
    ├── test_uitars_agent.py     # agent 兜底逻辑单元测试（mock client）
    ├── test_task_kugou.py       # 状态机单元测试（mock agent+input+window）
    └── test_integration.py      # 连手机集成测试（需授权，默认 skip）
```

---

### Task 0: 环境与脚手架

**Files:**
- Create: `automation/desktop/__init__.py`
- Create: `automation/desktop/tests/__init__.py`
- Modify: `requirements-test.txt`

**Interfaces:**
- Consumes: 根目录 `.venv`
- Produces: 可 import 的 `automation.desktop` 包；测试依赖就位

- [ ] **Step 1: 安装测试依赖到 .venv**

Run:
```bash
.venv/Scripts/pip install pyautogui pygetwindow pywin32 pillow mss pytest openai
```
Expected: 安装成功（pyautogui、pygetwindow、pywin32 等）

- [ ] **Step 2: 创建包文件**

`automation/desktop/__init__.py`：
```python
# -*- coding: utf-8 -*-
"""酷狗刷 VIP 桌面自动化子项目。"""
```

`automation/desktop/tests/__init__.py`：
```python
```

- [ ] **Step 3: freeze 依赖**

Run:
```bash
.venv/Scripts/pip freeze > requirements-test.txt
```
Expected: 文件更新，含 pyautogui/pygetwindow/pywin32/mss/pillow

- [ ] **Step 4: 验证包可导入**

Run:
```bash
.venv/Scripts/python -c "import automation.desktop; print('ok')"
```
Expected: 打印 `ok`（在 D:\shouxieagent 根目录运行）

- [ ] **Step 5: Commit**

```bash
git add automation/desktop/__init__.py automation/desktop/tests/__init__.py requirements-test.txt
git commit -m "chore: desktop子项目脚手架+测试依赖(pyautogui/pygetwindow/pywin32/mss)"
git push origin main
```

---

### Task 1: config.py — 配置与命令行参数

**Files:**
- Create: `automation/desktop/config.py`
- Test: `automation/desktop/tests/test_config.py`

**Interfaces:**
- Produces:
  - `DEFAULTS: dict`（含 `target_hours=14`, `max_rounds=200`, `scrcpy_title="scrcpy"`, `local_url="http://127.0.0.1:8000/v1"`, `openrouter_key=None`, `dry_run=False`, `stale_limit=4`, `max_grounding_retries=3`）
  - `SCRCPY_GESTURE: dict`（动作→鼠标键映射：`{"press_back": "right", "press_home": "middle"}`）
  - `parse_args(argv=None) -> argparse.Namespace`

- [ ] **Step 1: 写失败测试**

`automation/desktop/tests/test_config.py`：
```python
# -*- coding: utf-8 -*-
from automation.desktop import config


def test_defaults_target_hours():
    assert config.DEFAULTS["target_hours"] == 14


def test_gesture_map_back_and_home():
    assert config.SCRCPY_GESTURE["press_back"] == "right"
    assert config.SCRCPY_GESTURE["press_home"] == "middle"


def test_parse_args_overrides_target_hours():
    ns = config.parse_args(["--target-hours", "8", "--openrouter-key", "sk-or-x"])
    assert ns.target_hours == 8
    assert ns.openrouter_key == "sk-or-x"
    assert ns.dry_run is False


def test_parse_args_dry_run_flag():
    ns = config.parse_args(["--dry-run"])
    assert ns.dry_run is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: config` 或属性缺失）

- [ ] **Step 3: 实现 config.py**

```python
# -*- coding: utf-8 -*-
"""配置常量与命令行参数解析。"""
import argparse

DEFAULTS = {
    "target_hours": 14,
    "max_rounds": 200,
    "scrcpy_title": "scrcpy",
    "local_url": "http://127.0.0.1:8000/v1",
    "openrouter_key": None,
    "dry_run": False,
    "stale_limit": 4,            # 连续 N 步画面无变化判定卡死
    "max_grounding_retries": 3,  # 单步 grounding 失败重试上限
}

# UI-TARS mobile 动作 → scrcpy 接收的鼠标键（scrcpy 默认：右键=BACK，中键=HOME）
SCRCPY_GESTURE = {
    "press_back": "right",
    "press_home": "middle",
}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="酷狗刷 VIP 桌面自动化")
    p.add_argument("--target-hours", type=float, default=DEFAULTS["target_hours"])
    p.add_argument("--max-rounds", type=int, default=DEFAULTS["max_rounds"])
    p.add_argument("--scrcpy-title", default=DEFAULTS["scrcpy_title"])
    p.add_argument("--local-url", default=DEFAULTS["local_url"])
    p.add_argument("--openrouter-key", default=DEFAULTS["openrouter_key"])
    p.add_argument("--dry-run", action="store_true", default=DEFAULTS["dry_run"])
    return p.parse_args(argv)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add automation/desktop/config.py automation/desktop/tests/test_config.py
git commit -m "feat(desktop): config配置常量+命令行参数+scrcpy手势映射"
git push origin main
```

---

### Task 2: scrcpy_window.py — 坐标映射（纯函数，先测最易测的）

本任务只做**坐标映射纯函数**（不连手机），窗口定位/截图放 Task 3。

**Files:**
- Create: `automation/desktop/scrcpy_window.py`
- Test: `automation/desktop/tests/test_coord_mapping.py`

**Interfaces:**
- Produces:
  - `map_img_to_screen(x_img, y_img, win_rect, img_size) -> tuple[int, int]`
    - `win_rect = (left, top, w_win, h_win)`（内容区屏幕坐标与尺寸）
    - `img_size = (w_img, h_img)`（截图像素尺寸）
    - 返回屏幕绝对坐标 `(x_screen, y_screen)`，四舍五入为 int

- [ ] **Step 1: 写失败测试**

`automation/desktop/tests/test_coord_mapping.py`：
```python
# -*- coding: utf-8 -*-
from automation.desktop.scrcpy_window import map_img_to_screen


def test_map_identity_no_offset_no_scale():
    # 窗口在(0,0)，窗口尺寸=图片尺寸 → 坐标不变
    assert map_img_to_screen(100, 200, (0, 0, 400, 800), (400, 800)) == (100, 200)


def test_map_with_offset():
    # 窗口左上角在 (50, 30)，无缩放
    assert map_img_to_screen(100, 200, (50, 30, 400, 800), (400, 800)) == (150, 230)


def test_map_with_scale():
    # 图片 800x1600，窗口内容区 400x800 → 缩放 0.5，再加偏移
    assert map_img_to_screen(200, 400, (50, 30, 400, 800), (800, 1600)) == (150, 230)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_coord_mapping.py -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现纯函数（先建文件，仅此函数）**

`automation/desktop/scrcpy_window.py`：
```python
# -*- coding: utf-8 -*-
"""scrcpy 窗口管理：定位、前置、截图、坐标映射。"""


def map_img_to_screen(x_img, y_img, win_rect, img_size):
    """截图像素坐标 → PC 屏幕绝对坐标。

    win_rect: (left, top, w_win, h_win) 窗口内容区屏幕位置与尺寸
    img_size: (w_img, h_img) 截图像素尺寸
    """
    left, top, w_win, h_win = win_rect
    w_img, h_img = img_size
    x_screen = left + x_img * (w_win / w_img)
    y_screen = top + y_img * (h_win / h_img)
    return (round(x_screen), round(y_screen))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_coord_mapping.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add automation/desktop/scrcpy_window.py automation/desktop/tests/test_coord_mapping.py
git commit -m "feat(desktop): scrcpy窗口坐标映射纯函数(图坐标→屏幕坐标)+单测"
git push origin main
```

---

### Task 3: scrcpy_window.py — 窗口定位与截图（ScrcpyWindow 类）

补完窗口定位/前置/截图。这些依赖真实窗口，单元测试用 mock 验证调用逻辑，真实跑通放集成测试（Task 8）。

**Files:**
- Modify: `automation/desktop/scrcpy_window.py`
- Test: `automation/desktop/tests/test_scrcpy_window.py`

**Interfaces:**
- Consumes: `map_img_to_screen`（Task 2）
- Produces:
  - `class ScrcpyWindow(title="scrcpy")`
    - `locate() -> tuple[int,int,int,int]`：返回内容区 `(left, top, w, h)`；找不到抛 `WindowNotFound`
    - `activate() -> None`：前置窗口
    - `grab() -> (PIL.Image, tuple[int,int,int,int])`：返回 (截图, 当时的 win_rect)
    - `to_screen(x_img, y_img, win_rect, img_size) -> tuple[int,int]`：调用 `map_img_to_screen`
  - `class WindowNotFound(Exception)`

- [ ] **Step 1: 写失败测试（mock pygetwindow）**

`automation/desktop/tests/test_scrcpy_window.py`：
```python
# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch
import pytest
from automation.desktop.scrcpy_window import ScrcpyWindow, WindowNotFound


def test_locate_raises_when_no_window():
    with patch("automation.desktop.scrcpy_window.gw.getWindowsWithTitle", return_value=[]):
        w = ScrcpyWindow("scrcpy")
        with pytest.raises(WindowNotFound):
            w.locate()


def test_locate_returns_rect():
    fake = MagicMock()
    fake.left, fake.top, fake.width, fake.height = 50, 30, 400, 800
    with patch("automation.desktop.scrcpy_window.gw.getWindowsWithTitle", return_value=[fake]):
        w = ScrcpyWindow("scrcpy")
        assert w.locate() == (50, 30, 400, 800)


def test_to_screen_delegates_mapping():
    w = ScrcpyWindow("scrcpy")
    assert w.to_screen(100, 200, (50, 30, 400, 800), (400, 800)) == (150, 230)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_scrcpy_window.py -v`
Expected: FAIL（`ScrcpyWindow`/`WindowNotFound` 未定义）

- [ ] **Step 3: 实现 ScrcpyWindow（追加到 scrcpy_window.py）**

在 `scrcpy_window.py` 顶部加导入，文件追加：
```python
import io
import pygetwindow as gw
from PIL import Image
import mss


class WindowNotFound(Exception):
    pass


class ScrcpyWindow:
    def __init__(self, title="scrcpy"):
        self.title = title

    def locate(self):
        wins = gw.getWindowsWithTitle(self.title)
        if not wins:
            raise WindowNotFound(f"未找到标题含 '{self.title}' 的窗口")
        w = wins[0]
        return (w.left, w.top, w.width, w.height)

    def activate(self):
        wins = gw.getWindowsWithTitle(self.title)
        if not wins:
            raise WindowNotFound(f"未找到标题含 '{self.title}' 的窗口")
        win = wins[0]
        try:
            if win.isMinimized:
                win.restore()
            win.activate()
        except Exception:
            pass  # 某些窗口 activate 抛异常但实际已前置

    def grab(self):
        """截窗口内容区，返回 (PIL.Image, win_rect)。"""
        left, top, w, h = self.locate()
        with mss.mss() as sct:
            shot = sct.grab({"left": left, "top": top, "width": w, "height": h})
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return img, (left, top, w, h)

    def to_screen(self, x_img, y_img, win_rect, img_size):
        return map_img_to_screen(x_img, y_img, win_rect, img_size)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_scrcpy_window.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add automation/desktop/scrcpy_window.py automation/desktop/tests/test_scrcpy_window.py
git commit -m "feat(desktop): ScrcpyWindow窗口定位/前置/mss截图+mock单测"
git push origin main
```

---

### Task 4: desktop_input.py — 动作→pyautogui 手势翻译

**Files:**
- Create: `automation/desktop/desktop_input.py`
- Test: `automation/desktop/tests/test_desktop_input.py`

**Interfaces:**
- Consumes: `config.SCRCPY_GESTURE`
- Produces:
  - `class DesktopInput`
    - `do(action: dict, win, win_rect, img_size) -> None`
      - `action` 为 `parse_action_simple` 的输出（含 `type` 及坐标）
      - 内部用 `win.to_screen(...)` 换算坐标，再调 pyautogui
      - 支持类型：`click`→左键、`scroll`/`drag`→拖动、`long_press`→按住、
        `press_back`→右键、`press_home`→中键、`type`→typewrite、
        `wait`/`finished`→不操作
      - `dry_run=True` 时只记录不实际操作

- [ ] **Step 1: 写失败测试（mock pyautogui）**

`automation/desktop/tests/test_desktop_input.py`：
```python
# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch
from automation.desktop.desktop_input import DesktopInput


def _win():
    w = MagicMock()
    w.to_screen.side_effect = lambda x, y, r, s: (x + 1000, y + 2000)
    return w


def test_click_calls_pyautogui_click_at_mapped_coord():
    with patch("automation.desktop.desktop_input.pyautogui") as pg:
        di = DesktopInput(dry_run=False)
        di.do({"type": "click", "x": 100, "y": 200}, _win(), (0, 0, 400, 800), (400, 800))
        pg.click.assert_called_once_with(1100, 2200)


def test_press_back_uses_right_button():
    with patch("automation.desktop.desktop_input.pyautogui") as pg:
        di = DesktopInput(dry_run=False)
        di.do({"type": "press_back"}, _win(), (0, 0, 400, 800), (400, 800))
        # 右键点窗口中心
        assert pg.click.call_args.kwargs.get("button") == "right"


def test_press_home_uses_middle_button():
    with patch("automation.desktop.desktop_input.pyautogui") as pg:
        di = DesktopInput(dry_run=False)
        di.do({"type": "press_home"}, _win(), (0, 0, 400, 800), (400, 800))
        assert pg.click.call_args.kwargs.get("button") == "middle"


def test_dry_run_does_not_call_pyautogui():
    with patch("automation.desktop.desktop_input.pyautogui") as pg:
        di = DesktopInput(dry_run=True)
        di.do({"type": "click", "x": 1, "y": 2}, _win(), (0, 0, 400, 800), (400, 800))
        pg.click.assert_not_called()


def test_scroll_does_drag():
    with patch("automation.desktop.desktop_input.pyautogui") as pg:
        di = DesktopInput(dry_run=False)
        di.do({"type": "scroll", "x": 100, "y": 200, "direction": "down"},
              _win(), (0, 0, 400, 800), (400, 800))
        assert pg.moveTo.called and pg.dragTo.called
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_desktop_input.py -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现 desktop_input.py**

```python
# -*- coding: utf-8 -*-
"""UI-TARS 动作字典 → pyautogui 桌面操作（经 scrcpy 转发到手机）。"""
import pyautogui
from .config import SCRCPY_GESTURE

pyautogui.FAILSAFE = False


class DesktopInput:
    def __init__(self, dry_run=False, move_duration=0.2):
        self.dry_run = dry_run
        self.move_duration = move_duration

    def _center(self, win_rect):
        left, top, w, h = win_rect
        return (round(left + w / 2), round(top + h / 2))

    def do(self, action, win, win_rect, img_size):
        t = action.get("type")
        if t in ("wait", "finished", "call_user", None):
            return

        if t in ("press_back", "press_home"):
            cx, cy = self._center(win_rect)
            button = SCRCPY_GESTURE[t]
            if not self.dry_run:
                pyautogui.click(cx, cy, button=button)
            return

        if t == "type":
            if not self.dry_run:
                pyautogui.typewrite(action.get("content", ""), interval=0.05)
            return

        # 以下需坐标
        if "x" in action and "y" in action:
            sx, sy = win.to_screen(action["x"], action["y"], win_rect, img_size)
        else:
            return

        if t in ("click", "double_click", "right_click"):
            if self.dry_run:
                return
            if t == "click":
                pyautogui.click(sx, sy)
            elif t == "double_click":
                pyautogui.doubleClick(sx, sy)
            else:
                pyautogui.click(sx, sy, button="right")
            return

        if t == "long_press":
            if not self.dry_run:
                pyautogui.moveTo(sx, sy)
                pyautogui.mouseDown()
                pyautogui.sleep(1.0)
                pyautogui.mouseUp()
            return

        if t in ("scroll", "drag"):
            # scroll：从 (sx,sy) 朝 direction 拖动；drag：到 end 坐标
            if t == "drag" and "end_x" in action:
                ex, ey = win.to_screen(action["end_x"], action["end_y"], win_rect, img_size)
            else:
                ex, ey = self._scroll_target(sx, sy, action.get("direction", "down"))
            if not self.dry_run:
                pyautogui.moveTo(sx, sy)
                pyautogui.dragTo(ex, ey, duration=0.4)
            return

    @staticmethod
    def _scroll_target(sx, sy, direction):
        delta = 300
        if direction == "down":
            return sx, sy - delta   # 内容向下=手指上滑
        if direction == "up":
            return sx, sy + delta
        if direction == "left":
            return sx + delta, sy
        if direction == "right":
            return sx - delta, sy
        return sx, sy - delta
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_desktop_input.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add automation/desktop/desktop_input.py automation/desktop/tests/test_desktop_input.py
git commit -m "feat(desktop): DesktopInput动作→pyautogui手势翻译(click/scroll/back/home)+mock单测"
git push origin main
```

---

### Task 5: uitars_agent.py — 薄封装 UITarsClient（本地+兜底）

**Files:**
- Create: `automation/desktop/uitars_agent.py`
- Test: `automation/desktop/tests/test_uitars_agent.py`

**Interfaces:**
- Consumes: `automation/ui-tars-server/inference_client.py` 的 `UITarsClient`
- Produces:
  - `class UITarsAgent(local_url, openrouter_key=None)`
    - `step(instruction, screenshot) -> dict | None`：返回 `parse_action_simple` 的动作字典；
      本地 `ground` 失败/异常 → 若有 openrouter_key 则用 OpenRouter 重试；都失败返回 None
    - 内部保留 `history`（多轮），用 `predict`+`append_history`
    - `platform="mobile"`（scrcpy 投手机画面）

- [ ] **Step 1: 写失败测试（mock UITarsClient）**

`automation/desktop/tests/test_uitars_agent.py`：
```python
# -*- coding: utf-8 -*-
from unittest.mock import MagicMock, patch
from automation.desktop.uitars_agent import UITarsAgent


def test_step_uses_local_when_ok():
    local = MagicMock()
    local.predict.return_value = "Thought: x\nAction: click(start_box='(500,500)')"
    with patch("automation.desktop.uitars_agent.UITarsClient") as C:
        C.local.return_value = local
        agent = UITarsAgent(local_url="http://x/v1")
        # 用 800x800 假图
        from PIL import Image
        act = agent.step("点击", Image.new("RGB", (1000, 1000)))
        assert act["type"] == "click"
        assert act["x"] == 500 and act["y"] == 500


def test_step_falls_back_to_openrouter_on_local_error():
    local = MagicMock()
    local.predict.side_effect = RuntimeError("local down")
    remote = MagicMock()
    remote.predict.return_value = "Thought: x\nAction: click(start_box='(100,100)')"
    with patch("automation.desktop.uitars_agent.UITarsClient") as C:
        C.local.return_value = local
        C.openrouter.return_value = remote
        agent = UITarsAgent(local_url="http://x/v1", openrouter_key="sk-or-x")
        from PIL import Image
        act = agent.step("点击", Image.new("RGB", (1000, 1000)))
        assert act["type"] == "click" and act["x"] == 100
        remote.predict.assert_called_once()


def test_step_returns_none_when_all_fail():
    local = MagicMock()
    local.predict.side_effect = RuntimeError("down")
    with patch("automation.desktop.uitars_agent.UITarsClient") as C:
        C.local.return_value = local
        agent = UITarsAgent(local_url="http://x/v1")  # 无兜底
        from PIL import Image
        assert agent.step("点击", Image.new("RGB", (1000, 1000))) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_uitars_agent.py -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现 uitars_agent.py**

```python
# -*- coding: utf-8 -*-
"""薄封装 UITarsClient：本地优先，OpenRouter 兜底，保留多轮 history。"""
import sys
from pathlib import Path

# 复用 automation/ui-tars-server/inference_client.py（不重写）
_UITARS_DIR = Path(__file__).resolve().parents[1] / "ui-tars-server"
if str(_UITARS_DIR) not in sys.path:
    sys.path.insert(0, str(_UITARS_DIR))
from inference_client import UITarsClient, parse_action_simple  # noqa: E402


class UITarsAgent:
    def __init__(self, local_url, openrouter_key=None):
        self._local = UITarsClient.local(url=local_url)
        self._remote = (
            UITarsClient.openrouter(api_key=openrouter_key) if openrouter_key else None
        )
        self.history = []

    def step(self, instruction, screenshot):
        """单步：返回动作字典或 None。screenshot 为 PIL.Image。"""
        w, h = screenshot.size
        raw = self._predict_with_fallback(instruction, screenshot)
        if raw is None:
            return None
        # 维护 history（供下一轮上下文）
        try:
            client = self._last_client
            self.history = client.append_history(self.history, raw, screenshot) \
                if self.history else self._init_history(instruction, raw, screenshot, client)
        except Exception:
            pass
        return parse_action_simple(raw, w, h)

    def _predict_with_fallback(self, instruction, screenshot):
        try:
            self._last_client = self._local
            return self._local.predict(
                instruction, screenshot, history=self.history, platform="mobile"
            )
        except Exception:
            if self._remote is None:
                return None
            try:
                self._last_client = self._remote
                return self._remote.predict(
                    instruction, screenshot, history=self.history, platform="mobile"
                )
            except Exception:
                return None

    @staticmethod
    def _init_history(instruction, raw, screenshot, client):
        # 首轮：构造一个最小 history 起点
        return client.append_history([], raw, screenshot)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_uitars_agent.py -v`
Expected: 3 passed

> 注：若 `inference_client.py` import `openai` 失败，确认 Task 0 已装 `openai`。

- [ ] **Step 5: Commit**

```bash
git add automation/desktop/uitars_agent.py automation/desktop/tests/test_uitars_agent.py
git commit -m "feat(desktop): UITarsAgent薄封装(复用UITarsClient,本地优先OpenRouter兜底,多轮history)+mock单测"
git push origin main
```

---

### Task 6: task_kugou.py — 任务状态机

**Files:**
- Create: `automation/desktop/task_kugou.py`
- Test: `automation/desktop/tests/test_task_kugou.py`

**Interfaces:**
- Consumes: `UITarsAgent`、`DesktopInput`、`ScrcpyWindow`
- Produces:
  - `class KugouTask(window, agent, inp, target_hours=14, max_rounds=200, stale_limit=4)`
    - `run() -> dict`：返回 `{"status": "done"|"limit"|"failed"|"max_rounds", "rounds": int}`
    - `INSTRUCTIONS: dict`（各状态的中文指令文案）
    - 内部状态：`START → LOCATE_ENTRY → WATCH_AD → CHECK_PROGRESS`
    - `_screen_hash(img)`：感知 hash，连续 `stale_limit` 步不变 → 注入 `press_back` 跳出
    - 纯编排，所有外部副作用通过注入的 window/agent/inp（便于 mock 单测）

- [ ] **Step 1: 写失败测试（mock 三个依赖）**

`automation/desktop/tests/test_task_kugou.py`：
```python
# -*- coding: utf-8 -*-
from unittest.mock import MagicMock
from PIL import Image
from automation.desktop.task_kugou import KugouTask


def _mock_window():
    w = MagicMock()
    w.grab.return_value = (Image.new("RGB", (100, 100)), (0, 0, 100, 100))
    return w


def test_run_done_when_agent_signals_finished():
    win = _mock_window()
    agent = MagicMock()
    # 第一步就返回 finished → 状态机应判定 done
    agent.step.return_value = {"type": "finished"}
    inp = MagicMock()
    task = KugouTask(win, agent, inp, target_hours=14, max_rounds=5)
    result = task.run()
    assert result["status"] in ("done", "limit")


def test_run_failed_when_agent_returns_none_repeatedly():
    win = _mock_window()
    agent = MagicMock()
    agent.step.return_value = None  # 一直解析失败
    inp = MagicMock()
    task = KugouTask(win, agent, inp, max_rounds=5)
    result = task.run()
    assert result["status"] == "failed"


def test_run_hits_max_rounds():
    win = _mock_window()
    agent = MagicMock()
    # 一直返回普通 click，永不 finished
    agent.step.return_value = {"type": "click", "x": 50, "y": 50}
    inp = MagicMock()
    task = KugouTask(win, agent, inp, max_rounds=3)
    result = task.run()
    assert result["status"] == "max_rounds"
    assert result["rounds"] == 3


def test_each_round_activates_and_grabs():
    win = _mock_window()
    agent = MagicMock()
    agent.step.return_value = {"type": "finished"}
    inp = MagicMock()
    KugouTask(win, agent, inp, max_rounds=5).run()
    assert win.activate.called and win.grab.called
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_task_kugou.py -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现 task_kugou.py**

```python
# -*- coding: utf-8 -*-
"""酷狗刷 VIP 任务状态机。纯编排，外部副作用经注入依赖。"""
import hashlib

INSTRUCTIONS = {
    "START": "如果当前不在酷狗音乐app内，找到并打开酷狗音乐app；如果已在酷狗内，进入下一步。",
    "LOCATE_ENTRY": (
        "在酷狗音乐里找到『免费看广告领VIP』或『看视频得会员』『免费领会员时长』的入口并点击；"
        "若当前页没有，去『我的』或『VIP中心』页面下滑查找。"
    ),
    "WATCH_AD": (
        "如果有『看视频』『立即领取』按钮就点击开始看广告；"
        "如果广告正在播放就等待；广告播完后点击右上角『关闭/×/跳过』和『领取奖励』。"
    ),
    "CHECK_PROGRESS": (
        "查看当前VIP累计时长是否已达到或超过目标；"
        "如果页面提示『今日已领完』『暂无机会』就结束；否则返回继续看广告。"
    ),
}


class KugouTask:
    def __init__(self, window, agent, inp, target_hours=14, max_rounds=200, stale_limit=4):
        self.window = window
        self.agent = agent
        self.inp = inp
        self.target_hours = target_hours
        self.max_rounds = max_rounds
        self.stale_limit = stale_limit
        self.INSTRUCTIONS = INSTRUCTIONS

    @staticmethod
    def _screen_hash(img):
        small = img.resize((16, 16)).convert("L")
        return hashlib.md5(small.tobytes()).hexdigest()

    def run(self):
        rounds = 0
        fail_streak = 0
        stale_streak = 0
        last_hash = None
        instruction = self._compose()

        while rounds < self.max_rounds:
            rounds += 1
            self.window.activate()
            img, win_rect = self.window.grab()

            h = self._screen_hash(img)
            stale_streak = stale_streak + 1 if h == last_hash else 0
            last_hash = h

            action = self.agent.step(instruction, img)

            if action is None:
                fail_streak += 1
                if fail_streak >= 3:
                    return {"status": "failed", "rounds": rounds}
                continue
            fail_streak = 0

            if action.get("type") == "finished":
                return {"status": "done", "rounds": rounds}

            # 卡死：连续 stale_limit 步画面不变 → 注入返回键跳出
            if stale_streak >= self.stale_limit:
                self.inp.do({"type": "press_back"}, self.window, win_rect, img.size)
                stale_streak = 0
                continue

            self.inp.do(action, self.window, win_rect, img.size)

        return {"status": "max_rounds", "rounds": rounds}

    def _compose(self):
        # 单条综合指令，让 UI-TARS 自主决策完整任务路径
        return (
            f"任务：在酷狗音乐app里通过反复『免费看广告』把VIP听歌时长累计到{self.target_hours}小时。"
            f"{self.INSTRUCTIONS['START']} {self.INSTRUCTIONS['LOCATE_ENTRY']} "
            f"{self.INSTRUCTIONS['WATCH_AD']} {self.INSTRUCTIONS['CHECK_PROGRESS']} "
            f"全部完成或今日已达上限后输出 finished()。"
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_task_kugou.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add automation/desktop/task_kugou.py automation/desktop/tests/test_task_kugou.py
git commit -m "feat(desktop): KugouTask状态机(轮询截图/grounding/防卡死/停止条件)+mock单测"
git push origin main
```

---

### Task 7: kugou_vip.py — 主程序入口

**Files:**
- Create: `automation/desktop/kugou_vip.py`
- Test: `automation/desktop/tests/test_main.py`

**Interfaces:**
- Consumes: `config.parse_args`、`ScrcpyWindow`、`UITarsAgent`、`DesktopInput`、`KugouTask`
- Produces:
  - `build_task(args) -> KugouTask`：按参数装配各组件（便于测试）
  - `main(argv=None) -> int`：装配并 `run()`，打印中文结果，返回退出码

- [ ] **Step 1: 写失败测试（mock 组件，验证装配）**

`automation/desktop/tests/test_main.py`：
```python
# -*- coding: utf-8 -*-
from unittest.mock import patch, MagicMock
from automation.desktop import kugou_vip


def test_build_task_wires_target_hours():
    from automation.desktop.config import parse_args
    args = parse_args(["--target-hours", "10", "--dry-run"])
    with patch("automation.desktop.kugou_vip.UITarsAgent"), \
         patch("automation.desktop.kugou_vip.ScrcpyWindow"), \
         patch("automation.desktop.kugou_vip.DesktopInput"):
        task = kugou_vip.build_task(args)
        assert task.target_hours == 10


def test_main_returns_zero_on_done():
    with patch("automation.desktop.kugou_vip.build_task") as bt:
        fake = MagicMock()
        fake.run.return_value = {"status": "done", "rounds": 12}
        bt.return_value = fake
        assert kugou_vip.main(["--target-hours", "14"]) == 0


def test_main_returns_nonzero_on_failed():
    with patch("automation.desktop.kugou_vip.build_task") as bt:
        fake = MagicMock()
        fake.run.return_value = {"status": "failed", "rounds": 3}
        bt.return_value = fake
        assert kugou_vip.main([]) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_main.py -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现 kugou_vip.py**

```python
# -*- coding: utf-8 -*-
"""酷狗刷 VIP 桌面自动化 — 命令行入口。"""
import sys

from .config import parse_args
from .scrcpy_window import ScrcpyWindow
from .desktop_input import DesktopInput
from .uitars_agent import UITarsAgent
from .task_kugou import KugouTask


def build_task(args):
    window = ScrcpyWindow(title=args.scrcpy_title)
    agent = UITarsAgent(local_url=args.local_url, openrouter_key=args.openrouter_key)
    inp = DesktopInput(dry_run=args.dry_run)
    return KugouTask(
        window, agent, inp,
        target_hours=args.target_hours,
        max_rounds=args.max_rounds,
    )


def main(argv=None):
    args = parse_args(argv)
    task = build_task(args)
    result = task.run()
    status = result["status"]
    msgs = {
        "done": f"✅ 完成：已累计到 {args.target_hours} 小时（{result['rounds']} 轮）",
        "limit": f"⏸ 今日已达上限，请明日再运行（{result['rounds']} 轮）",
        "failed": f"❌ 失败：连续 grounding 解析失败（{result['rounds']} 轮）",
        "max_rounds": f"⚠ 达到最大轮数 {args.max_rounds} 仍未完成",
    }
    print(msgs.get(status, f"结束：{result}"))
    return 0 if status in ("done", "limit") else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_main.py -v`
Expected: 3 passed

- [ ] **Step 5: 跑全部单元测试**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/ -v --ignore=automation/desktop/tests/test_integration.py`
Expected: 全部 passed

- [ ] **Step 6: Commit**

```bash
git add automation/desktop/kugou_vip.py automation/desktop/tests/test_main.py
git commit -m "feat(desktop): kugou_vip主入口(装配组件+中文结果输出+退出码)+单测"
git push origin main
```

---

### Task 8: 集成/E2E 测试骨架（默认 skip，等用户授权 + 手机就位）

**Files:**
- Create: `automation/desktop/tests/test_integration.py`
- Create: `automation/desktop/README.md`

**Interfaces:**
- Consumes: 全部模块
- Produces: 真实连手机的测试用例（用 env 开关控制，默认 skip）

- [ ] **Step 1: 写集成测试骨架（默认 skip）**

`automation/desktop/tests/test_integration.py`：
```python
# -*- coding: utf-8 -*-
"""连手机集成/E2E 测试 —— 默认 skip。
启用：设置环境变量 KUGOU_LIVE=1，且 scrcpy 已投屏、UI-TARS 服务可用。
仅在用户显式『开始测试』后运行。"""
import os
import pytest

LIVE = os.environ.get("KUGOU_LIVE") == "1"
pytestmark = pytest.mark.skipif(not LIVE, reason="需 KUGOU_LIVE=1 且手机就位")


def test_locate_scrcpy_window():
    from automation.desktop.scrcpy_window import ScrcpyWindow
    rect = ScrcpyWindow("scrcpy").locate()
    assert len(rect) == 4 and rect[2] > 0 and rect[3] > 0


def test_grab_returns_image():
    from automation.desktop.scrcpy_window import ScrcpyWindow
    img, rect = ScrcpyWindow("scrcpy").grab()
    assert img.size[0] > 0 and img.size[1] > 0


def test_dry_run_grounding_on_real_screen():
    """--dry-run：UI-TARS 能在真实酷狗截图上给出坐标（不实际点击）。"""
    from automation.desktop.scrcpy_window import ScrcpyWindow
    from automation.desktop.uitars_agent import UITarsAgent
    win = ScrcpyWindow("scrcpy")
    img, _ = win.grab()
    agent = UITarsAgent(local_url=os.environ.get("KUGOU_LOCAL_URL", "http://127.0.0.1:8000/v1"))
    act = agent.step("找到屏幕上任意一个可点击的按钮", img)
    assert act is not None
```

- [ ] **Step 2: 跑确认全部 skip（无手机环境）**

Run: `.venv/Scripts/python -m pytest automation/desktop/tests/test_integration.py -v`
Expected: 3 skipped

- [ ] **Step 3: 写 README（运行说明）**

`automation/desktop/README.md`：
```markdown
# 酷狗刷 VIP 桌面自动化

## 前置
1. 手机 USB 连接，开启 USB 调试，`adb devices` 可见
2. 运行 `scrcpy` 投屏，窗口标题含 "scrcpy"
3. 本地起 UI-TARS 服务（见 automation/ui-tars-server）或用 --openrouter-key

## 运行
```bash
.venv/Scripts/python -m automation.desktop.kugou_vip --target-hours 14 \
    --openrouter-key sk-or-xxx
```

## 参数
- `--target-hours`：目标累计小时（默认 14）
- `--dry-run`：只看不点，验证 grounding
- `--scrcpy-title`：scrcpy 窗口标题（默认 scrcpy）
- `--local-url`：本地 UI-TARS 地址（默认 http://127.0.0.1:8000/v1）
- `--openrouter-key`：OpenRouter 兜底 key

## 测试
- 单元（不连手机）：`.venv/Scripts/python -m pytest automation/desktop/tests/ --ignore=automation/desktop/tests/test_integration.py`
- 集成/E2E（连手机）：`KUGOU_LIVE=1 .venv/Scripts/python -m pytest automation/desktop/tests/test_integration.py`
```

- [ ] **Step 4: Commit**

```bash
git add automation/desktop/tests/test_integration.py automation/desktop/README.md
git commit -m "test(desktop): 集成/E2E测试骨架(默认skip,需KUGOU_LIVE+手机)+运行README"
git push origin main
```

---

## Self-Review

**1. Spec 覆盖：**
- §3 单模型 UI-TARS + 兜底 → Task 5 ✅
- §4 架构目录 → Task 0–7 全覆盖 ✅
- §5 数据流 → Task 6 状态机循环 ✅
- §6 桌面核心（坐标映射 + 手势翻译表）→ Task 2（映射）+ Task 4（翻译）✅
- §7 状态机 → Task 6 ✅
- §8 健壮性（任意起点/重定位/兜底/防卡死/停止）→ Task 6 + Task 5 ✅
- §9 测试分层（单元/集成/E2E）→ Task 1–7 单元 + Task 8 集成/E2E ✅
- §10 单元边界 → 四模块各自单测 ✅

**2. 占位符扫描：** 无 TBD/TODO；每个 code step 含完整代码。

**3. 类型一致性：**
- `map_img_to_screen(x_img, y_img, win_rect, img_size)` — Task 2 定义，Task 3 `to_screen` 调用一致 ✅
- `DesktopInput.do(action, win, win_rect, img_size)` — Task 4 定义，Task 6 调用一致 ✅
- `UITarsAgent.step(instruction, screenshot) -> dict|None` — Task 5 定义，Task 6 调用一致 ✅
- `KugouTask(window, agent, inp, target_hours, max_rounds, stale_limit)` — Task 6 定义，Task 7 装配一致 ✅
- action 字典格式（`type`/`x`/`y`/`direction`/`end_x`/`content`）与 `parse_action_simple` 输出一致 ✅

**已知待测试时校准（spec §6 注 + §7）：**
- scrcpy 右键=BACK/中键=HOME 的默认快捷键，实测时按实际版本校准（已做成 config 可调）
- 酷狗"累计时长 vs 剩余时长"显示语义，看真实界面后微调 `INSTRUCTIONS["CHECK_PROGRESS"]`
- `finished()` 触发时机依赖 UI-TARS 判断，E2E 时观察并可补充显式时长读取
