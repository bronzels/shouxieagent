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
