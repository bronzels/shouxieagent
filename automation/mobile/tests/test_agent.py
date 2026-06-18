import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from agent import KugouAdsAgent


async def _no_sleep(_seconds):
    return None


class FakeDevice:
    def __init__(self):
        self.activated = 0
        self.taps = []
    def screen_size(self): return (1000, 2000)
    def screenshot(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"x"); return path
    def tap(self, x, y): self.taps.append((x, y))
    def back(self): pass
    def page_source(self): return '<hierarchy><node text="看广告领时长" bounds="[0,0][100,100]"/></hierarchy>'
    def activate_app(self): self.activated += 1
    def current_package(self): return "com.kugou.android"


class FakeVision:
    def __init__(self, minutes_seq):
        self.minutes_seq = list(minutes_seq)
        self.read_calls = 0
    async def locate(self, image_path, instruction, w, h): return (50, 50)
    async def read_text(self, image_path, question):
        i = min(self.read_calls, len(self.minutes_seq) - 1)
        self.read_calls += 1
        return f"剩余{self.minutes_seq[i]}分钟"


@pytest.mark.asyncio
async def test_run_stops_when_target_reached():
    dev = FakeDevice()
    vis = FakeVision(minutes_seq=[60, 600, 900])  # 第三次读到 900>=840 停止
    agent = KugouAdsAgent(device=dev, vision=vis, sleep=_no_sleep)
    final = await agent.run(target_minutes=840, max_ads=50)
    assert final >= 840
    assert dev.activated >= 1  # 启动时归位过


@pytest.mark.asyncio
async def test_run_stops_at_max_ads():
    dev = FakeDevice()
    vis = FakeVision(minutes_seq=[10, 20, 30])  # 永远到不了 840
    agent = KugouAdsAgent(device=dev, vision=vis, sleep=_no_sleep)
    final = await agent.run(target_minutes=840, max_ads=2)
    assert final < 840  # 被 max_ads 截断


class BlindVision:
    """视觉全失败：locate 返回 None、read_text 返回空 → 逼出 XML 兜底路径。"""
    async def locate(self, image_path, instruction, w, h): return None
    async def read_text(self, image_path, question): return ""


class XmlDevice(FakeDevice):
    def page_source(self):
        return ('<hierarchy>'
                '<node text="看广告" bounds="[0,0][100,100]"/>'
                '<node text="剩余900分钟" bounds="[0,100][100,200]"/>'
                '</hierarchy>')


@pytest.mark.asyncio
async def test_xml_fallback_when_vision_blank():
    """UI-TARS 视觉全空时，回退到 page_source 关键字点击 + XML 时长解析仍能完成。"""
    dev = XmlDevice()
    agent = KugouAdsAgent(device=dev, vision=BlindVision(), sleep=_no_sleep)
    final = await agent.run(target_minutes=840, max_ads=50)
    assert final >= 840          # 经 XML 兜底读到 900 分钟
    assert dev.taps               # 经 page_source 关键字命中点击过
