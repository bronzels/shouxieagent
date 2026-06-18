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
