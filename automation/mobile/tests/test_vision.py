import sys
import base64
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))

import pytest
import vision


@pytest.fixture
def tiny_png(tmp_path):
    # 1x1 PNG
    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    p = tmp_path / "s.png"
    p.write_bytes(data)
    return str(p)


@pytest.mark.asyncio
async def test_locate_parses_uitars_point(tiny_png, monkeypatch):
    async def fake_call_uitars(image_path, task_prompt):
        return "Thought: click button\nAction: click(start_box='<point>500 250</point>')"
    monkeypatch.setattr(vision, "call_uitars", fake_call_uitars)
    xy = await vision.locate(tiny_png, "点击看广告按钮", 1000, 1000)
    # ui_tars 解析器(qwen25vl)有 smart_resize 取整，点击坐标允许小幅误差
    assert xy is not None
    assert abs(xy[0] - 500) <= 10 and abs(xy[1] - 250) <= 10


@pytest.mark.asyncio
async def test_read_text_uses_uitars_ocr(tiny_png, monkeypatch):
    # read_text 走 UI-TARS（本地 server），不走独立文字模型
    def fake_local_sync(payload):
        return {"choices": [{"message": {"content": "剩余3小时20分"}}]}
    monkeypatch.setattr(vision, "_post_uitars_local_sync", fake_local_sync)
    out = await vision.read_text(tiny_png, "VIP剩余时长是多少")
    assert "3小时20分" in out


def test_no_text_model_chain():
    # 确认没有照搬 web 的文字/多模态模型链
    assert not hasattr(vision, "VERIFY_MODELS_MULTIMODAL")
    assert not hasattr(vision, "VERIFY_MODELS_TEXT")
