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
