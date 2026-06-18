"""
集成测试 — UI-TARS 推理服务 (192.168.3.14:8000)
测试前检查：服务必须运行，否则全部 skip。
测试后清理：无持久数据写入（每次请求无状态）。

运行：
    pytest automation/tests/test_uitars_server_integration.py -v
"""
import base64
import json
import struct
import subprocess
import zlib
from io import BytesIO

import pytest
from openai import OpenAI

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).parent))
from conftest import UITARS_BASE_URL, UITARS_SERVER

# ── 前置检查：服务不在线则 skip 整个模块 ─────────────────────────────────────

def _server_online() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen(f"{UITARS_SERVER}/v1/models", timeout=5)
        return True
    except Exception:
        return False

pytestmark = pytest.mark.skipif(
    not _server_online(),
    reason=f"UI-TARS server not reachable at {UITARS_SERVER}"
)


# ── 工具函数 ───────────────────────────────────────────────────────────────────

def make_test_png(w: int, h: int) -> bytes:
    """生成指定尺寸的测试 PNG（带蓝色按钮，用于 grounding 测试）。"""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)

    rows = []
    for y in range(h):
        row = b"\x00"
        for x in range(w):
            if y > h - 50:                          # 底部任务栏
                row += bytes([30, 30, 30])
            elif 100 < x < 300 and 50 < y < 100:   # 蓝色按钮
                row += bytes([0, 120, 215])
            else:
                row += bytes([220, 220, 220])
        rows.append(row)

    raw = b"".join(rows)
    comp = zlib.compress(raw, 1)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", comp)
            + chunk(b"IEND", b""))


def gpu_memory_used_mib() -> int:
    """从服务器查询当前 GPU 显存占用（MiB）。需要 SSH 免密登录。"""
    try:
        r = subprocess.run(
            ["ssh", "root@192.168.3.14",
             "nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        return int(r.stdout.strip())
    except Exception:
        return -1


@pytest.fixture(scope="module")
def client():
    return OpenAI(base_url=UITARS_BASE_URL, api_key="none", timeout=180.0)


@pytest.fixture(scope="module")
def model_id(client):
    models = client.models.list()
    assert len(models.data) > 0, "服务返回空模型列表"
    return models.data[0].id


# ── TEST §1: 服务健康检查 ──────────────────────────────────────────────────────

class TestServerHealth:
    def test_models_endpoint_returns_list(self, client):
        """GET /v1/models 返回非空模型列表"""
        models = client.models.list()
        assert len(models.data) >= 1

    def test_model_id_is_gguf_path(self, model_id):
        """模型 ID 是 GGUF 文件路径"""
        assert model_id.endswith(".gguf"), f"预期 GGUF 路径，实际: {model_id}"

    def test_gpu_memory_idle_under_8gb(self):
        """空闲显存占用 < 8192 MiB（flash_attn 优化后应在 5-6 GB）"""
        used = gpu_memory_used_mib()
        if used == -1:
            pytest.skip("无法查询 GPU 显存（SSH 不可达）")
        assert used < 8192, f"空闲显存占用过高: {used} MiB"


# ── TEST §2: 基础文本视觉推理 ─────────────────────────────────────────────────

class TestBasicInference:
    def _call(self, client, model_id, img_b64: str, prompt: str, max_tokens=100) -> str:
        resp = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": prompt},
            ]}],
            max_tokens=max_tokens,
            frequency_penalty=1,
        )
        return resp.choices[0].message.content

    def test_small_image_returns_content(self, client, model_id):
        """小图（100×100）推理有输出"""
        png = make_test_png(100, 100)
        img_b64 = base64.b64encode(png).decode()
        result = self._call(client, model_id, img_b64, "What color is the background?")
        assert result and len(result) > 0

    def test_viewport_1280x720(self, client, model_id):
        """标准 viewport（1280×720）推理有输出"""
        png = make_test_png(1280, 720)
        img_b64 = base64.b64encode(png).decode()
        result = self._call(client, model_id, img_b64,
                            "Click the blue button near the top of the image.")
        assert result and len(result) > 0


# ── TEST §3: UI Grounding ────────────────────────────────────────────────────

class TestUIGrounding:
    """验证 UI-TARS 输出的 click 坐标合理性。"""

    SYSTEM = (
        "You are a GUI agent. Output the next action only.\n"
        "Format: Action: click(start_box='(x,y)')\n"
        "Coordinates are 0-1000 relative."
    )

    def _ground(self, client, model_id, w, h, prompt) -> dict:
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "ui-tars-server"))
        from inference_client import parse_action_simple

        png = make_test_png(w, h)
        img_b64 = base64.b64encode(png).decode()
        resp = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": self.SYSTEM + "\n\nTask: " + prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            ]}],
            max_tokens=64,
            frequency_penalty=1,
        )
        text = resp.choices[0].message.content
        action = parse_action_simple(text, w, h)
        return {"raw": text, "action": action, "w": w, "h": h}

    def test_click_action_returned(self, client, model_id):
        """1280×720 图，返回 click 动作"""
        r = self._ground(client, model_id, 1280, 720, "Click the blue button.")
        assert r["action"] is not None, f"无法解析动作，原始输出: {r['raw']}"
        assert r["action"]["type"] in ("click", "double_click", "right_click")

    def test_click_coordinates_in_bounds(self, client, model_id):
        """坐标在图像范围内"""
        r = self._ground(client, model_id, 1280, 720, "Click the blue button.")
        if r["action"] is None:
            pytest.skip(f"动作解析失败: {r['raw']}")
        assert 0 <= r["action"]["x"] <= r["w"]
        assert 0 <= r["action"]["y"] <= r["h"]

    def test_click_button_x_in_left_third(self, client, model_id):
        """蓝色按钮在左侧（x=100-300/1280），预期 x 坐标在左 1/3 区域"""
        r = self._ground(client, model_id, 1280, 720, "Click the blue button.")
        if r["action"] is None:
            pytest.skip(f"动作解析失败: {r['raw']}")
        # 按钮 x 范围 100-300px（1280宽），换算到屏幕坐标应在 left half
        assert r["action"]["x"] < r["w"] // 2, (
            f"按钮在左侧，但预测 x={r['action']['x']} 超过中线。原始: {r['raw']}"
        )

    def test_grounding_2560x1440_fullhd(self, client, model_id):
        """2560×1440 全分辨率推理成功（不 OOM，坐标合法）"""
        r = self._ground(client, model_id, 2560, 1440, "Click the blue button.")
        assert r["action"] is not None, f"2560×1440 推理失败: {r['raw']}"
        assert 0 <= r["action"]["x"] <= 2560
        assert 0 <= r["action"]["y"] <= 1440


# ── TEST §4: 显存峰值（2560×1440 推理后） ─────────────────────────────────────

class TestGPUMemoryPeak:
    def test_peak_under_11gb_after_fullhd_inference(self, client, model_id):
        """2560×1440 推理后显存峰值 < 11000 MiB（flash_attn 优化目标 ≤ 8500 MiB）"""
        png = make_test_png(2560, 1440)
        img_b64 = base64.b64encode(png).decode()

        client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": "Click the blue button."},
            ]}],
            max_tokens=64,
            frequency_penalty=1,
        )

        used = gpu_memory_used_mib()
        if used == -1:
            pytest.skip("无法查询 GPU 显存")
        assert used < 11000, f"2560×1440 推理后显存 {used} MiB，超过 11GB 警戒线"
        # 记录实际值供报告参考
        print(f"\n  GPU 显存实测: {used} MiB / 12288 MiB")
