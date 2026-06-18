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
