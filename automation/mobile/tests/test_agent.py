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
        if "主页" in question:          # _on_kugou_home 校验 → 视为已在主页
            return "是"
        if "任务中心" in question:      # _on_ads_center 校验 → 视为已在中心
            return "是"
        if "放弃" in question:          # giveup 挽留弹窗检测 → 无弹窗
            return "无"
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


class GiveupVision:
    """模拟出现/未出现『要放弃免费听歌』挽留弹窗。"""
    def __init__(self, present):
        self._ans = "有" if present else "无"
    async def locate(self, image_path, instruction, w, h): return (60, 70)
    async def read_text(self, image_path, question): return self._ans


@pytest.mark.asyncio
async def test_handle_giveup_popup_clicks_continue():
    """出现『要放弃免费听歌』挽留弹窗时，点『继续浏览』保住奖励(不放弃)。"""
    dev = FakeDevice()
    agent = KugouAdsAgent(device=dev, vision=GiveupVision(present=True), sleep=_no_sleep)
    handled = await agent._handle_giveup_popup(browse_secs=10)
    assert handled is True
    assert dev.taps == [(60, 70)]      # 点了『继续浏览』


@pytest.mark.asyncio
async def test_handle_giveup_popup_absent_no_action():
    """没有挽留弹窗时不做任何点击。"""
    dev = FakeDevice()
    agent = KugouAdsAgent(device=dev, vision=GiveupVision(present=False), sleep=_no_sleep)
    handled = await agent._handle_giveup_popup(browse_secs=10)
    assert handled is False
    assert dev.taps == []


@pytest.mark.asyncio
async def test_close_ad_landing_taps_corner_X_not_back():
    """看完广告用广告自带的关闭X(左上角坐标)领奖、回到中心，绝不用返回键。"""
    dev = FakeDevice()                       # screen 1000x2000
    agent = KugouAdsAgent(device=dev, vision=FakeVision([0]), sleep=_no_sleep)
    reached = await agent._close_ad_landing()
    assert reached is True
    # 只点了左上角X坐标(0.15*1000, 0.075*2000)，没有走 back 兜底
    assert dev.taps == [(150, 150)]


class StuckLandingVision:
    """中心校验一直为否(关不掉)，用于验证最终走 back 兜底逃出。"""
    async def locate(self, image_path, instruction, w, h): return None
    async def read_text(self, image_path, question): return "否"


@pytest.mark.asyncio
async def test_close_ad_landing_falls_back_to_back_when_stuck():
    """所有关闭X都没回到中心时，最后用返回键兜底逃出避免卡死。"""
    class CountBackDevice(FakeDevice):
        def __init__(self):
            super().__init__()
            self.backs = 0
        def back(self): self.backs += 1
        def current_package(self): return "com.kugou.android"
    dev = CountBackDevice()
    agent = KugouAdsAgent(device=dev, vision=StuckLandingVision(), sleep=_no_sleep)
    reached = await agent._close_ad_landing()
    assert dev.backs >= 1        # 兜底用了返回键逃出
    assert reached is False       # 仍未确认回到中心


class WrongThenCenterVision:
    """前 wrong_times 次中心校验返回『否』(进错页)，之后返回『是』(进对)。"""
    def __init__(self, wrong_times):
        self.wrong_times = wrong_times
        self.checks = 0
    async def locate(self, image_path, instruction, w, h): return (50, 50)
    async def read_text(self, image_path, question):
        if "任务中心" in question:
            self.checks += 1
            return "否" if self.checks <= self.wrong_times else "是"
        return "无"


class StuckThenCenterVision:
    """前 wrong_times 次中心校验为否(卡在子页)，之后为是(回到中心)；主页校验恒否。"""
    def __init__(self, wrong_times):
        self.wrong = wrong_times
        self.checks = 0
    async def locate(self, image_path, instruction, w, h): return (50, 50)
    async def read_text(self, image_path, question):
        if "任务中心" in question:
            self.checks += 1
            return "否" if self.checks <= self.wrong else "是"
        if "主页" in question:
            return "否"
        return "无"


@pytest.mark.asyncio
async def test_recover_to_center_backs_until_center():
    """卡在非中心页时，反复『<』返回(back)直到回到免费听歌中心。"""
    class BackCountDevice(FakeDevice):
        def __init__(self):
            super().__init__()
            self.backs = 0
        def back(self): self.backs += 1
    dev = BackCountDevice()
    vis = StuckThenCenterVision(wrong_times=2)   # 前2次还在子页，第3次回到中心
    agent = KugouAdsAgent(device=dev, vision=vis, sleep=_no_sleep)
    ok = await agent._recover_to_center()
    assert ok is True
    assert dev.backs >= 2          # 反复返回退出子页


@pytest.mark.asyncio
async def test_recover_relaunches_kugou_when_in_third_party_app():
    """跳进真正的第三方App(如淘宝App,无『<』和『X』)时，重开酷狗(activate_app)
    而不是只按返回键——对应『上滑回桌面/最近任务再打开酷狗』。"""
    class ThirdPartyThenKugouDevice(FakeDevice):
        def __init__(self):
            super().__init__()
            self.activated = 0
            self._launched = False
        def current_package(self):
            return "com.kugou.android" if self._launched else "com.taobao.taobao"
        def activate_app(self):
            self.activated += 1
            self._launched = True

    class CenterAfterRelaunchVision:
        def __init__(self): self.center_checks = 0
        async def locate(self, image_path, instruction, w, h): return (50, 50)
        async def read_text(self, image_path, question):
            if "任务中心" in question:
                self.center_checks += 1
                return "是" if self.center_checks >= 2 else "否"
            if "主页" in question: return "是"
            return "无"

    dev = ThirdPartyThenKugouDevice()
    agent = KugouAdsAgent(device=dev, vision=CenterAfterRelaunchVision(), sleep=_no_sleep)
    ok = await agent._recover_to_center()
    assert ok is True
    assert dev.activated >= 1        # 重开了酷狗(没只靠返回键)


@pytest.mark.asyncio
async def test_navigate_retries_when_not_on_center():
    """鲁棒性：进错页面(中心校验为否)时 back 退回重试，最终进入中心，而非卡死。"""
    dev = FakeDevice()
    vis = WrongThenCenterVision(wrong_times=2)   # 前2次进错，第3次进对
    agent = KugouAdsAgent(device=dev, vision=vis, sleep=_no_sleep)
    ok = await agent.navigate_to_ads_page()
    assert ok is True
    assert vis.checks == 3            # 校验3次(2次失败重试+1次成功)
    assert len(dev.taps) >= 3         # 至少点了3次入口坐标
