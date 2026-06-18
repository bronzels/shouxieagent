"""主循环：状态归位 → 导航到看广告页 → 看广告 → 读时长直到 ≥ 目标。"""
import asyncio
import os

import parsers

ENTRY_KEYWORDS = ["看广告", "免费听歌", "免费畅听", "领时长", "广告得", "看视频", "免费领"]
WATCH_KEYWORDS = ["看广告", "看视频", "立即领取", "领取", "观看", "去观看"]
CLOSE_KEYWORDS = ["关闭", "跳过", "×", "X", "✕", "关闭广告"]
REMAIN_QUESTION = "这个页面显示的VIP或免费畅听剩余时长是多少？只回答时长，如『3小时20分』。"


class KugouAdsAgent:
    def __init__(self, device, vision, sleep=asyncio.sleep):
        self.dev = device
        self.vis = vision
        self.sleep = sleep
        self._shot_i = 0

    def _shot(self) -> str:
        self._shot_i += 1
        path = f"automation/mobile/reports/screenshots/run-{self._shot_i:04d}.png"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return self.dev.screenshot(path)

    async def _tap_vision_or_keyword(self, instruction, keywords) -> bool:
        """视觉优先：UI-TARS 定位直接点；UI-TARS 未命中才回退 page_source 关键字（兜底）。
        （酷狗自绘文字不进无障碍树，故视觉为主、XML 为兜底。）"""
        shot = self._shot()
        w, h = self.dev.screen_size()
        xy = await self.vis.locate(shot, instruction, w, h)
        if xy:
            self.dev.tap(*xy)
            return True
        hit = parsers.find_keyword_bounds(self.dev.page_source(), keywords)
        if hit:
            self.dev.tap(*hit)
            return True
        return False

    async def reset_to_kugou_home(self) -> None:
        self.dev.activate_app()
        await self.sleep(2.0)
        if "com.kugou" not in self.dev.current_package():
            self.dev.activate_app()
            await self.sleep(2.0)

    async def navigate_to_ads_page(self) -> bool:
        for _ in range(5):
            if await self._tap_vision_or_keyword("点击进入看广告领VIP听歌时长的入口", ENTRY_KEYWORDS):
                await self.sleep(2.0)
                return True
            self.dev.back()
            await self.sleep(1.0)
        return False

    async def read_remaining_minutes(self) -> int | None:
        # 主路径：UI-TARS OCR 读屏（酷狗自绘文字不进无障碍树）
        shot = self._shot()
        txt = await self.vis.read_text(shot, REMAIN_QUESTION)
        mins = parsers.parse_duration_to_minutes(txt)
        if mins is not None:
            return mins
        # 兜底：扫 page_source XML
        return parsers.extract_duration_from_xml(self.dev.page_source())

    async def watch_one_ad(self) -> bool:
        if not await self._tap_vision_or_keyword("点击『看广告』按钮开始看广告", WATCH_KEYWORDS):
            return False
        await self.sleep(35.0)   # 广告 ≤60s，先等一段
        # 轮询找关闭按钮，最多再等 40s（视觉优先，XML 兜底）
        for _ in range(8):
            shot = self._shot()
            w, h = self.dev.screen_size()
            hit = await self.vis.locate(shot, "点击右上角关闭广告的×按钮", w, h)
            if not hit:
                hit = parsers.find_keyword_bounds(self.dev.page_source(), CLOSE_KEYWORDS)
            if hit:
                self.dev.tap(*hit)
                await self.sleep(2.0)
                return True
            await self.sleep(5.0)
        return False

    async def run(self, target_minutes: int, max_ads: int) -> int:
        await self.reset_to_kugou_home()
        await self.navigate_to_ads_page()
        remaining = await self.read_remaining_minutes() or 0
        print(f"  ▶ 初始剩余时长: {remaining} 分钟", flush=True)
        ads = 0
        while remaining < target_minutes and ads < max_ads:
            ok = await self.watch_one_ad()
            ads += 1
            await self.sleep(2.0)
            new_remaining = await self.read_remaining_minutes()
            if new_remaining is not None:
                remaining = new_remaining
            print(f"  ▶ 已看 {ads} 次广告，当前剩余: {remaining} 分钟 "
                  f"(目标 {target_minutes})", flush=True)
            if not ok:
                await self.navigate_to_ads_page()
        if remaining < target_minutes:
            print(f"  ⚠️ 达到 max_ads={max_ads} 仍未到目标，最终 {remaining} 分钟", flush=True)
        else:
            print(f"  ✅ 已达目标，最终剩余 {remaining} 分钟 (≥{target_minutes})", flush=True)
        return remaining
