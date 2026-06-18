"""
单元测试 — inference_client.py
测试 parse_action_simple / encode_image / add_box_token
不依赖推理服务，不产生任何持久数据。
"""
import base64
import struct
import sys
import zlib
from io import BytesIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "ui-tars-server"))
from inference_client import parse_action_simple, encode_image, add_box_token


def _make_png(w: int = 2, h: int = 2) -> bytes:
    """生成最小合法 RGB PNG，避免 Pillow 版本差异导致的解码问题。"""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes([200, 200, 200] * w) for _ in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


# ── parse_action_simple ────────────────────────────────────────────────────────

class TestParseActionSimple:
    W, H = 1280, 720

    def test_click_plain(self):
        text = "Action: click(start_box='(500,300)')"
        r = parse_action_simple(text, self.W, self.H)
        assert r is not None
        assert r["type"] == "click"
        assert r["x"] == round(500 / 1000 * self.W)
        assert r["y"] == round(300 / 1000 * self.H)

    def test_click_with_box_token(self):
        text = "Action: click(start_box='<|box_start|>(250,750)<|box_end|>')"
        r = parse_action_simple(text, self.W, self.H)
        assert r is not None
        assert r["type"] == "click"
        assert r["x"] == round(250 / 1000 * self.W)
        assert r["y"] == round(750 / 1000 * self.H)

    def test_click_with_thought(self):
        text = (
            "Thought: I need to click the submit button.\n"
            "Action: click(start_box='(493,67)')"
        )
        r = parse_action_simple(text, 800, 600)
        assert r is not None
        assert r["type"] == "click"
        assert r["x"] == round(493 / 1000 * 800)
        assert r["y"] == round(67 / 1000 * 600)

    def test_double_click(self):
        text = "Action: left_double(start_box='(100,200)')"
        r = parse_action_simple(text, self.W, self.H)
        assert r is not None
        assert r["type"] == "double_click"

    def test_right_click(self):
        text = "Action: right_single(start_box='(100,200)')"
        r = parse_action_simple(text, self.W, self.H)
        assert r is not None
        assert r["type"] == "right_click"

    def test_type(self):
        text = "Action: type(content='hello world')"
        r = parse_action_simple(text, self.W, self.H)
        assert r == {"type": "type", "content": "hello world"}

    def test_type_chinese(self):
        text = "Action: type(content='你好世界')"
        r = parse_action_simple(text, self.W, self.H)
        assert r == {"type": "type", "content": "你好世界"}

    def test_scroll_down(self):
        text = "Action: scroll(start_box='(500,400)', direction='down')"
        r = parse_action_simple(text, self.W, self.H)
        assert r is not None
        assert r["type"] == "scroll"
        assert r["direction"] == "down"
        assert r["x"] == round(500 / 1000 * self.W)

    def test_hotkey(self):
        text = "Action: hotkey(key='ctrl+c')"
        r = parse_action_simple(text, self.W, self.H)
        assert r == {"type": "hotkey", "key": "ctrl+c"}

    def test_finished(self):
        text = "Action: finished()"
        r = parse_action_simple(text, self.W, self.H)
        assert r is not None
        assert r["type"] == "finished"

    def test_coordinates_normalized_correctly(self):
        # 0-1000 坐标映射到 2560x1440
        text = "Action: click(start_box='(171,68)')"
        r = parse_action_simple(text, 2560, 1440)
        assert r["x"] == round(171 / 1000 * 2560)   # 437
        assert r["y"] == round(68 / 1000 * 1440)     # 97

    def test_unparseable_returns_none(self):
        assert parse_action_simple("I cannot complete this task.", 1280, 720) is None

    def test_coordinates_within_image_bounds(self):
        text = "Action: click(start_box='(999,999)')"
        r = parse_action_simple(text, 1280, 720)
        assert r["x"] <= 1280
        assert r["y"] <= 720


# ── encode_image ───────────────────────────────────────────────────────────────

class TestEncodeImage:
    """encode_image 支持多种输入类型，输出合法 base64。"""

    @pytest.fixture
    def png_1x1(self):
        """最小合法 PNG：2×2 灰色像素（程序生成，兼容新版 Pillow）"""
        return _make_png(2, 2)

    def test_encode_from_bytes(self, png_1x1):
        result = encode_image(png_1x1)
        assert isinstance(result, str)
        # 必须能 base64 解码且不报错
        decoded = base64.b64decode(result)
        assert len(decoded) > 0

    def test_encode_from_bytesio(self, png_1x1):
        buf = BytesIO(png_1x1)
        result = encode_image(buf)
        assert base64.b64decode(result) == png_1x1

    def test_encode_from_pil(self, png_1x1):
        from PIL import Image
        img = Image.open(BytesIO(png_1x1))
        result = encode_image(img)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_encode_from_path(self, png_1x1, tmp_path):
        p = tmp_path / "test.png"
        p.write_bytes(png_1x1)
        result = encode_image(str(p))
        assert base64.b64decode(result) == png_1x1


# ── add_box_token ──────────────────────────────────────────────────────────────

class TestAddBoxToken:
    def test_adds_tokens_to_coordinates(self):
        text = "Thought: click\nAction: click(start_box='(500,300)')"
        result = add_box_token(text)
        assert "<|box_start|>" in result
        assert "<|box_end|>" in result
        assert "(500,300)" in result

    def test_no_action_unchanged(self):
        text = "No action here."
        assert add_box_token(text) == text

    def test_already_tokenized_not_double_wrapped(self):
        text = "Action: click(start_box='<|box_start|>(500,300)<|box_end|>')"
        result = add_box_token(text)
        # 不应出现双重 wrap
        assert result.count("<|box_start|>") == 1
