# -*- coding: utf-8 -*-
"""scrcpy 窗口管理：定位、前置、截图、坐标映射。"""

import pygetwindow as gw
from PIL import Image
import mss


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
