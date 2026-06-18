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


# ── C1 回归测试：多轮 history 构造正确性 ──────────────────────────────────────

def test_history_structure_after_two_steps():
    """连续调用 step 两次，验证 history 顺序和内容符合 UI-TARS 多轮格式。"""
    from PIL import Image

    raw1 = "Thought: first\nAction: click(start_box='(200,300)')"
    raw2 = "Thought: second\nAction: click(start_box='(400,600)')"

    local = MagicMock()
    local.predict.side_effect = [raw1, raw2]

    with patch("automation.desktop.uitars_agent.UITarsClient") as C:
        C.local.return_value = local
        agent = UITarsAgent(local_url="http://x/v1")
        img = Image.new("RGB", (1000, 1000))

        agent.step("点击目标", img)
        agent.step("点击目标", img)

    # history 长度应为 4：[user, assistant, user, assistant]
    assert len(agent.history) == 4, f"期望4条，实际{len(agent.history)}"

    # history[0]：首轮 user，含 system prompt 文本 + image_url
    h0 = agent.history[0]
    assert h0["role"] == "user"
    assert isinstance(h0["content"], list)
    text_parts = [p for p in h0["content"] if p.get("type") == "text"]
    img_parts = [p for p in h0["content"] if p.get("type") == "image_url"]
    assert len(text_parts) == 1, "首轮 user 应有一个 text part"
    assert "GUI agent" in text_parts[0]["text"], "text 应含 system prompt 片段"
    assert len(img_parts) == 1, "首轮 user 应有一个 image_url"

    # history[1]：首轮 assistant
    h1 = agent.history[1]
    assert h1["role"] == "assistant"

    # history[2]：第二轮 user，只含 image（无 text）
    h2 = agent.history[2]
    assert h2["role"] == "user"
    assert isinstance(h2["content"], list)
    text_parts2 = [p for p in h2["content"] if p.get("type") == "text"]
    img_parts2 = [p for p in h2["content"] if p.get("type") == "image_url"]
    assert len(text_parts2) == 0, "第二轮 user 不应含 text（只含图片）"
    assert len(img_parts2) == 1, "第二轮 user 应有一个 image_url"

    # history[3]：第二轮 assistant
    h3 = agent.history[3]
    assert h3["role"] == "assistant"
