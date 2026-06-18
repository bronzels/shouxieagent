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
