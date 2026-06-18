import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))

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


class AdAppDevice(FakeDevice):
    """模拟看完广告落在第三方广告 app：前几次 current_package 非酷狗，back 几次后回酷狗。"""
    def __init__(self, backs_to_return=2):
        super().__init__()
        self._left = backs_to_return
        self.backs = 0
    def current_package(self):
        return "com.kugou.android" if self._left <= 0 else "com.thirdparty.ad"
    def back(self):
        self.backs += 1
        self._left -= 1


@pytest.mark.asyncio
async def test_ensure_kugou_foreground_multi_back():
    """看完广告在广告app里，多退几步直到回酷狗（不是退一步就算）。"""
    dev = AdAppDevice(backs_to_return=3)
    agent = KugouAdsAgent(device=dev, vision=FakeVision([0]), sleep=_no_sleep)
    ok = await agent._ensure_kugou_foreground()
    assert ok is True
    assert dev.backs == 3          # 连退 3 次才回到酷狗


@pytest.mark.asyncio
async def test_ensure_kugou_foreground_activate_fallback():
    """多次 back 仍回不去 → activate_app 兜底拉回。"""
    class StuckDevice(FakeDevice):
        def __init__(self):
            super().__init__()
            self._activated_to_kugou = False
        def back(self): pass
        def activate_app(self):
            super().activate_app()
            self._activated_to_kugou = True
        def current_package(self):
            return "com.kugou.android" if self._activated_to_kugou else "com.ad.app"
    dev = StuckDevice()
    agent = KugouAdsAgent(device=dev, vision=FakeVision([0]), sleep=_no_sleep)
    ok = await agent._ensure_kugou_foreground(max_back=3)
    assert ok is True
    assert dev.activated >= 1       # 用了 activate 兜底


@pytest.mark.asyncio
async def test_xml_fallback_when_vision_blank():
    """UI-TARS 视觉全空时，回退到 page_source 关键字点击 + XML 时长解析仍能完成。"""
    dev = XmlDevice()
    agent = KugouAdsAgent(device=dev, vision=BlindVision(), sleep=_no_sleep)
    final = await agent.run(target_minutes=840, max_ads=50)
    assert final >= 840          # 经 XML 兜底读到 900 分钟
    assert dev.taps               # 经 page_source 关键字命中点击过
