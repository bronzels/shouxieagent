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
