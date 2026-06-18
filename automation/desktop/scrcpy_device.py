# -*- coding: utf-8 -*-
"""ScrcpyDevice — 纯桌面 Device 适配器，通过 scrcpy 窗口操作手机。

坐标系说明：
  screenshot() 截 scrcpy 窗口内容区得到 PIL.Image(W, H)；
  screen_size() 返回相同的 (W, H)；
  vision.locate 据此返回截图像素坐标 (px, py)；
  tap/back/swipe 经 DesktopInput.do → ScrcpyWindow.to_screen 把截图像素→屏幕绝对坐标→pyautogui。
  全链坐标系一致，不存在 adb 逻辑尺寸与 CSS px 的换算问题。
"""
import os
import subprocess
import tempfile
import time

import sys as _sys
import os as _os
_pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
_root_dir = _os.path.dirname(_os.path.dirname(_pkg_dir))
for _d in [_root_dir, _pkg_dir]:
    if _d not in _sys.path:
        _sys.path.insert(0, _d)

from automation.desktop.scrcpy_window import ScrcpyWindow
from automation.desktop.desktop_input import DesktopInput

# vision 在 common 目录，由 CLI 入口在 sys.path 插入后可 import；
# 这里延迟导入，避免单元测试时 vision 模块（含 openai 等重依赖）未安装而崩溃。


class ScrcpyDevice:
    """等价于 mobile/device.py 的 Device，但全程走 scrcpy 窗口 + pyautogui。

    供 common/agent.py 注入使用：
        dev = ScrcpyDevice(scrcpy_dir, window_title, serial)
        dev.start()
        agent = KugouAdsAgent(device=dev, vision=vision)
    """

    def __init__(self, scrcpy_dir: str, window_title: str = "scrcpy-kugou",
                 serial: str | None = None):
        self._scrcpy_dir = scrcpy_dir
        self._window_title = window_title
        self._serial = serial
        self.win = ScrcpyWindow(window_title)
        self.inp = DesktopInput(dry_run=False)
        self._proc = None
        self._win_rect = None   # (left, top, w, h) 窗口屏幕区域
        self._img_size = None   # (w, h) 截图像素尺寸

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动 scrcpy 进程，等待窗口出现（最多 20 秒）。"""
        exe = os.path.join(self._scrcpy_dir, "scrcpy.exe")
        cmd = [exe, "--window-title", self._window_title, "--stay-awake"]
        if self._serial:
            cmd += ["-s", self._serial]
        self._proc = subprocess.Popen(cmd)

        deadline = time.time() + 20.0
        while time.time() < deadline:
            try:
                rect = self.win.locate()
                # 窗口出现
                self.win.activate()
                img, win_rect = self.win.grab()
                self._win_rect = win_rect
                self._img_size = img.size
                return
            except Exception:
                time.sleep(0.5)

        raise RuntimeError(
            f"scrcpy 窗口未出现（{self._window_title}），请检查 scrcpy 安装路径: {self._scrcpy_dir}"
        )

    def quit(self) -> None:
        """结束 scrcpy 进程。"""
        try:
            if self._proc is not None:
                self._proc.terminate()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 基础信息
    # ------------------------------------------------------------------

    def screen_size(self) -> tuple[int, int]:
        """返回截图像素空间尺寸 (w, h)，与 screenshot() 返回图同尺寸。"""
        if self._img_size is None:
            img, win_rect = self.win.grab()
            self._win_rect = win_rect
            self._img_size = img.size
        return self._img_size

    def page_source(self) -> str:
        """桌面无无障碍树 XML，返回空字符串（酷狗自绘文字，纯视觉）。"""
        return ""

    # ------------------------------------------------------------------
    # 截图 / 输入
    # ------------------------------------------------------------------

    def screenshot(self, path: str) -> str:
        """截 scrcpy 窗口内容区，保存到 path，返回 path。"""
        img, win_rect = self.win.grab()
        self._win_rect = win_rect
        self._img_size = img.size
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        img.save(path)
        return path

    def tap(self, x: int | float, y: int | float) -> None:
        """截图像素坐标点击。"""
        self.win.activate()
        self.inp.do(
            {"type": "click", "x": int(x), "y": int(y)},
            self.win,
            self._win_rect,
            self._img_size,
        )

    def back(self) -> None:
        """模拟 Android BACK 键（scrcpy 右键）。"""
        self.win.activate()
        self.inp.do(
            {"type": "press_back"},
            self.win,
            self._win_rect,
            self._img_size,
        )

    def swipe(self, x1: int | float, y1: int | float,
              x2: int | float, y2: int | float, ms: int = 400) -> None:
        """截图像素坐标拖动。"""
        self.win.activate()
        self.inp.do(
            {"type": "drag", "x": int(x1), "y": int(y1),
             "end_x": int(x2), "end_y": int(y2)},
            self.win,
            self._win_rect,
            self._img_size,
        )

    # ------------------------------------------------------------------
    # 视觉判断（同步，避免 async 嵌套）
    # ------------------------------------------------------------------

    def _read_text_sync(self, image_path: str, question: str) -> str:
        """同步调用 vision._post_uitars_local_sync 读屏（本地 UI-TARS）。
        失败时返回空字符串，调用方负责兜底。"""
        import vision as _vision
        img_b64 = _vision.image_to_base64(image_path)
        payload = {
            "model": _vision.UITARS_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": question},
                ],
            }],
            "max_tokens": 64,
        }
        result = _vision._post_uitars_sync(payload)   # 按 USE_LOCAL 选本地/OpenRouter
        return result["choices"][0]["message"]["content"] or ""

    def _locate_sync(self, image_path: str, instruction: str) -> tuple[int, int] | None:
        """同步调用 UI-TARS grounding，返回截图像素坐标或 None。"""
        import vision as _vision
        from ui_tars.prompt import COMPUTER_USE_DOUBAO
        img_b64 = _vision.image_to_base64(image_path)
        prompt_text = COMPUTER_USE_DOUBAO.format(instruction=instruction, language="Chinese")
        payload = {
            "model": _vision.UITARS_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": prompt_text},
                ],
            }],
            "max_tokens": 512,
        }
        result = _vision._post_uitars_sync(payload)   # 按 USE_LOCAL 选本地/OpenRouter
        resp = result["choices"][0]["message"]["content"] or ""
        w, h = self._img_size or (1080, 1920)
        norm = _vision._parse_point(resp, w, h)
        if norm is None:
            return None
        px = min(max(int(round(norm[0] * w)), 0), w - 1)
        py = min(max(int(round(norm[1] * h)), 0), h - 1)
        return (px, py)

    def _grab_temp(self) -> str:
        """抓一帧到临时文件，返回路径。"""
        runs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs")
        os.makedirs(runs_dir, exist_ok=True)
        path = os.path.join(runs_dir, "_pkgcheck.png")
        return self.screenshot(path)

    def current_package(self) -> str:
        """纯视觉判断当前是否在酷狗界面。

        返回 "com.kugou.android" 或 "unknown"。
        agent 里的 'com.kugou' in current_package() 判断因此成立。
        """
        question = (
            "这个手机屏幕当前是不是在酷狗音乐App的界面内部"
            "(不是桌面、不是其他App、不是广告)？只回答『是』或『否』。"
        )
        try:
            path = self._grab_temp()
            ans = self._read_text_sync(path, question)
            # 严格判断：必须以"是"开头或只含单独"是"，且不含"否"/"不是"/"否定"
            # 防止"不是酷狗"这类含"是"的否定句被误识别
            import re as _re
            ans_stripped = ans.strip()
            is_yes = bool(_re.search(r'^是\b|^是$', ans_stripped))
            is_no = ("否" in ans_stripped or "不是" in ans_stripped or "不在" in ans_stripped)
            if is_yes and not is_no:
                return "com.kugou.android"
            return "unknown"
        except Exception:
            return "unknown"

    def activate_app(self) -> None:
        """纯视觉拉起酷狗：HOME 回桌面 → 视觉定位图标 → 点击。

        同步方法，内部用 _locate_sync 避免 async 嵌套问题。
        """
        # 先按 HOME 回桌面
        self.inp.do(
            {"type": "press_home"},
            self.win,
            self._win_rect,
            self._img_size,
        )
        time.sleep(1.5)

        try:
            path = self._grab_temp()
            xy = self._locate_sync(path, "点击酷狗音乐(KuGou)App图标")
            if xy:
                self.tap(*xy)
                time.sleep(2.0)
                return
        except Exception:
            pass
        # 找不到图标：只 HOME 兜底，已经在桌面
