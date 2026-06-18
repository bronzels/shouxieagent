# -*- coding: utf-8 -*-
"""ScrcpyDevice 单元测试（mock，不连真机/scrcpy）。"""
import os
import asyncio
import tempfile
from unittest.mock import MagicMock, patch, call
import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# 辅助：构造带缓存状态的 ScrcpyDevice（跳过 start()）
# ---------------------------------------------------------------------------

def _make_device(win=None, inp=None):
    """创建 ScrcpyDevice，mock 掉 ScrcpyWindow/DesktopInput，不真正 start()。"""
    fake_img = Image.new("RGB", (1080, 1920))
    fake_win_rect = (100, 50, 1080, 1920)

    mock_win = win or MagicMock()
    mock_win.grab.return_value = (fake_img, fake_win_rect)
    mock_win.locate.return_value = fake_win_rect

    mock_inp = inp or MagicMock()

    with patch("automation.desktop.scrcpy_device.ScrcpyWindow", return_value=mock_win), \
         patch("automation.desktop.scrcpy_device.DesktopInput", return_value=mock_inp):
        from automation.desktop.scrcpy_device import ScrcpyDevice
        dev = ScrcpyDevice(scrcpy_dir=r"D:\fake-scrcpy", window_title="scrcpy-test")

    # 预填缓存（模拟 start() 已执行）
    dev._win_rect = fake_win_rect
    dev._img_size = fake_img.size
    dev.win = mock_win
    dev.inp = mock_inp
    return dev, mock_win, mock_inp, fake_img, fake_win_rect


# ---------------------------------------------------------------------------
# screenshot
# ---------------------------------------------------------------------------

def test_screenshot_calls_grab_saves_image_returns_path(tmp_path):
    dev, mock_win, _, fake_img, fake_win_rect = _make_device()
    path = str(tmp_path / "shot.png")
    result = dev.screenshot(path)
    mock_win.grab.assert_called_once()
    assert result == path
    assert os.path.exists(path)


def test_screenshot_caches_win_rect_and_img_size(tmp_path):
    dev, mock_win, _, fake_img, fake_win_rect = _make_device()
    dev._win_rect = None
    dev._img_size = None
    path = str(tmp_path / "shot2.png")
    dev.screenshot(path)
    assert dev._win_rect == fake_win_rect
    assert dev._img_size == fake_img.size


def test_screenshot_creates_parent_dir(tmp_path):
    dev, _, _, _, _ = _make_device()
    nested = str(tmp_path / "a" / "b" / "shot.png")
    dev.screenshot(nested)
    assert os.path.exists(nested)


# ---------------------------------------------------------------------------
# tap
# ---------------------------------------------------------------------------

def test_tap_activates_window_then_calls_inp_do(tmp_path):
    dev, mock_win, mock_inp, _, fake_win_rect = _make_device()
    dev.tap(540, 960)
    mock_win.activate.assert_called_once()
    mock_inp.do.assert_called_once_with(
        {"type": "click", "x": 540, "y": 960},
        mock_win,
        fake_win_rect,
        (1080, 1920),
    )


def test_tap_converts_to_int():
    dev, mock_win, mock_inp, _, fake_win_rect = _make_device()
    dev.tap(540.7, 960.3)
    args = mock_inp.do.call_args[0][0]
    assert args["x"] == 540
    assert args["y"] == 960


# ---------------------------------------------------------------------------
# back
# ---------------------------------------------------------------------------

def test_back_sends_press_back_action():
    dev, mock_win, mock_inp, _, fake_win_rect = _make_device()
    dev.back()
    mock_win.activate.assert_called_once()
    mock_inp.do.assert_called_once_with(
        {"type": "press_back"},
        mock_win,
        fake_win_rect,
        (1080, 1920),
    )


# ---------------------------------------------------------------------------
# swipe
# ---------------------------------------------------------------------------

def test_swipe_sends_drag_action():
    dev, mock_win, mock_inp, _, fake_win_rect = _make_device()
    dev.swipe(100, 800, 100, 200)
    args = mock_inp.do.call_args[0][0]
    assert args["type"] == "drag"
    assert args["x"] == 100
    assert args["y"] == 800
    assert args["end_x"] == 100
    assert args["end_y"] == 200


# ---------------------------------------------------------------------------
# current_package — 视觉判断
# ---------------------------------------------------------------------------

def test_current_package_yes_returns_kugou(tmp_path):
    dev, mock_win, _, _, _ = _make_device()
    # read_text 同步调用 _post_uitars_local_sync，这里 mock 整个 _read_text_sync
    dev._read_text_sync = MagicMock(return_value="是")
    pkg = dev.current_package()
    assert "com.kugou" in pkg


def test_current_package_no_returns_unknown():
    dev, mock_win, _, _, _ = _make_device()
    dev._read_text_sync = MagicMock(return_value="否")
    pkg = dev.current_package()
    assert pkg == "unknown"


def test_current_package_ambiguous_no_returns_unknown():
    dev, mock_win, _, _, _ = _make_device()
    dev._read_text_sync = MagicMock(return_value="不是酷狗，是其他App")
    pkg = dev.current_package()
    assert pkg == "unknown"


def test_current_package_exception_returns_unknown():
    dev, mock_win, _, _, _ = _make_device()
    dev._read_text_sync = MagicMock(side_effect=Exception("network error"))
    pkg = dev.current_package()
    assert pkg == "unknown"


# ---------------------------------------------------------------------------
# page_source
# ---------------------------------------------------------------------------

def test_page_source_returns_empty_string():
    dev, _, _, _, _ = _make_device()
    assert dev.page_source() == ""


# ---------------------------------------------------------------------------
# start — 窗口持续 locate 失败 → 超时抛 RuntimeError
# ---------------------------------------------------------------------------

def test_start_timeout_raises_runtime_error():
    """mock locate 抛异常，mock time.sleep 避免真等待，验证超时抛 RuntimeError。"""
    from unittest.mock import MagicMock, patch

    fake_img = Image.new("RGB", (1080, 1920))
    mock_win = MagicMock()
    mock_win.locate.side_effect = Exception("window not found")
    mock_inp = MagicMock()

    with patch("automation.desktop.scrcpy_device.ScrcpyWindow", return_value=mock_win), \
         patch("automation.desktop.scrcpy_device.DesktopInput", return_value=mock_inp), \
         patch("automation.desktop.scrcpy_device.subprocess") as mock_subproc, \
         patch("automation.desktop.scrcpy_device.time") as mock_time:

        mock_subproc.Popen.return_value = MagicMock()
        # time.time 返回递增序列（超过20秒触发超时）
        mock_time.time.side_effect = [0.0, 25.0, 25.0]
        mock_time.sleep = MagicMock()

        from automation.desktop import scrcpy_device as _mod
        import importlib
        importlib.reload(_mod)

        with patch("automation.desktop.scrcpy_device.ScrcpyWindow", return_value=mock_win), \
             patch("automation.desktop.scrcpy_device.DesktopInput", return_value=mock_inp), \
             patch("automation.desktop.scrcpy_device.subprocess") as mock_subproc2, \
             patch("automation.desktop.scrcpy_device.time") as mock_time2:

            mock_subproc2.Popen.return_value = MagicMock()
            mock_time2.time.side_effect = [0.0, 25.0, 25.0]
            mock_time2.sleep = MagicMock()

            from automation.desktop.scrcpy_device import ScrcpyDevice
            dev = ScrcpyDevice(scrcpy_dir=r"D:\fake-scrcpy", window_title="scrcpy-test")
            with pytest.raises(RuntimeError, match="scrcpy 窗口未出现"):
                dev.start()
