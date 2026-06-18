"""主循环：感知(UI-TARS读屏)→决策(规则)→定位(UI-TARS)→执行+读时长，直到 ≥ 目标。

酷狗启动/首页状态多变(开屏广告/内测版/挽留弹窗/夺宝游戏)，故用感知-决策-执行循环：
每步截图让 UI-TARS 描述当前屏 → decide_action 规则判断该干什么 → UI-TARS 定位目标按钮点击。
看广告时先从文案读出要求秒数(如『看15秒』)，定时看够即关闭，不死等浪费时间。
"""
import asyncio
import os

import parsers

ENTRY_KEYWORDS = ["看广告", "免费听歌", "免费畅听", "领时长", "去浏览", "看视频", "免费领"]
WATCH_KEYWORDS = ["看广告", "看视频", "立即领取", "领取", "观看", "去观看", "去浏览"]
CLOSE_KEYWORDS = ["关闭", "跳过", "×", "X", "✕", "领取", "完成"]
REMAIN_QUESTION = (
    "只看这个页面有没有明确写着『VIP剩余』『免费畅听剩余』『可免费听X分钟/小时』这类"
    "听歌时长。有就只回答该时长(如『3小时20分』)；没有明确写听歌时长就回答『无』。"
    "绝对不要把金额(元)、夺宝/宝箱倒计时、歌曲时长、当前时间当作听歌时长。")
DECIDE_QUESTION = (
    "你在操作酷狗音乐app，目标是反复『看广告领免费听歌时长』把时长攒够。请只看这张截图，"
    "用下面固定格式回答一行，不要解释：\n"
    "ACTION=<WATCH|WAIT|CLOSE|BACK|HOME|DONE>; LABEL=<要点击的按钮文字或无>; SECONDS=<要求观看秒数或0>\n"
    "判断规则：\n"
    "- 有『看广告/点击去浏览/看视频』且是领【免费听歌时长/VIP时长】的入口 → WATCH，LABEL填按钮文字，"
    "SECONDS填要求秒数(如看15秒填15)。\n"
    "- 广告正在播放、有倒计时还没到 → WAIT。\n"
    "- 出现『领取/已获得/恭喜』奖励弹窗或广告结束有关闭X → CLOSE，LABEL填关闭或领取。\n"
    "- 是夺宝/宝箱/刮刮乐/红包/内测版邀请/升级等与领听歌时长无关的页 → BACK。\n"
    "- 是酷狗主页/播放器等稳定页、没有可领时长入口 → HOME。\n"
    "- 已经能看到VIP/免费听歌剩余时长且无事可做 → DONE。")
DEFAULT_AD_SECONDS = 16


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

    async def _locate_tap(self, instruction, keywords=()) -> bool:
        """视觉优先定位点击；UI-TARS 未命中再回退 page_source 关键字（兜底）。"""
        shot = self._shot()
        w, h = self.dev.screen_size()
        xy = await self.vis.locate(shot, instruction, w, h)
        if xy:
            self.dev.tap(*xy)
            return True
        if keywords:
            hit = parsers.find_keyword_bounds(self.dev.page_source(), keywords)
            if hit:
                self.dev.tap(*hit)
                return True
        return False

    async def _decide(self) -> dict:
        """感知+决策：UI-TARS 给结构化决策，再用规则(decide_action)交叉校验，
        防止 UI-TARS 把『夺宝/红包/马上去用』等误判为 WATCH（看广告领听歌时长）。"""
        raw = await self.vis.read_text(self._shot(), DECIDE_QUESTION)
        d = parsers.parse_decision(raw)
        if d is None:
            d = parsers.decide_action(raw)
            d.setdefault("seconds", None)
        elif d["action"] == "watch" and parsers.is_distraction_label(d.get("label", "")):
            # 复核 WATCH：LABEL 明显是夺宝/红包/充值等干扰项 → 降级为返回
            d = {"action": "back", "label": "", "seconds": None}
        d["_raw"] = (raw or "")[:80]
        return d

    async def _close_ad(self) -> bool:
        return await self._locate_tap("点击右上角关闭广告的×按钮，或『领取奖励/完成』按钮",
                                      CLOSE_KEYWORDS)

    def _in_kugou(self) -> bool:
        return "kugou" in (self.dev.current_package() or "").lower()

    async def _ensure_kugou_foreground(self, max_back: int = 5) -> bool:
        """确保回到酷狗：看完广告常落地在第三方广告 app/夺宝页，单次 back 回不去。
        连退多步(每步检查当前包)，仍不在酷狗则 activate_app 兜底拉回。"""
        for _ in range(max_back):
            if self._in_kugou():
                return True
            self.dev.back()
            await self.sleep(1.2)
        if not self._in_kugou():
            self.dev.activate_app()   # 多次 back 仍回不去 → 直接拉起酷狗
            await self.sleep(2.0)
        return self._in_kugou()

    # ---- 兼容旧接口（单元测试用）----
    async def reset_to_kugou_home(self) -> None:
        self.dev.activate_app()
        await self.sleep(2.0)
        if "com.kugou" not in self.dev.current_package():
            self.dev.activate_app()
            await self.sleep(2.0)

    async def navigate_to_ads_page(self) -> bool:
        """尽量进入看广告入口：视觉优先点入口，未命中回退关键字。"""
        for _ in range(3):
            if await self._locate_tap("点击进入看广告领VIP听歌时长的入口", ENTRY_KEYWORDS):
                await self.sleep(2.0)
                return True
            self.dev.back()
            await self.sleep(1.0)
        return False

    async def read_remaining_minutes(self) -> int | None:
        # 主路径：UI-TARS OCR 读屏（酷狗自绘文字不进无障碍树）
        txt = await self.vis.read_text(self._shot(), REMAIN_QUESTION)
        mins = parsers.parse_duration_to_minutes(txt)
        if mins is not None:
            return mins
        # 兜底：扫 page_source XML
        return parsers.extract_duration_from_xml(self.dev.page_source())

    async def watch_one_ad(self) -> bool:
        """点看广告入口 → 按要求秒数定时看够 → 关闭。"""
        d = await self._decide()
        if not await self._locate_tap("点击『看广告/点击去浏览/看视频领时长』按钮开始看广告",
                                      WATCH_KEYWORDS):
            return False
        secs = (d.get("seconds") or DEFAULT_AD_SECONDS)
        await self.sleep(secs + 3)        # 定时看够要求秒数(+缓冲)，不死等
        ok = False
        for _ in range(4):                 # 关闭/领取，最多重试几次
            if await self._close_ad():
                ok = True
                await self.sleep(2.0)
                break
            await self.sleep(3.0)
        await self._ensure_kugou_foreground()   # 看完广告强制回酷狗，别留在广告app
        return ok

    # ---- 感知-决策-执行主循环 ----
    async def run(self, target_minutes: int, max_ads: int) -> int:
        await self.reset_to_kugou_home()
        await self.navigate_to_ads_page()
        remaining = await self.read_remaining_minutes() or 0
        print(f"  ▶ 初始剩余时长: {remaining} 分钟", flush=True)
        ads = 0
        steps = 0
        max_steps = max(30, max_ads * 6)
        stale_home = 0   # 连续 home/done 次数，过多则重启换状态
        while remaining < target_minutes and ads < max_ads and steps < max_steps:
            steps += 1
            decision = await self._decide()
            act = decision["action"]
            print(f"  · step{steps}: {act} (label={decision.get('label','')}) | {decision.get('_raw','')}",
                  flush=True)
            if act == "watch":
                secs = (decision.get("seconds") or DEFAULT_AD_SECONDS)
                label = decision.get("label") or "看广告"
                if await self._locate_tap(f"点击『{label}』按钮看广告领免费听歌时长", WATCH_KEYWORDS):
                    await self.sleep(secs + 3)   # 定时看够，不死等
                    await self._close_ad()
                    await self._ensure_kugou_foreground()   # 看完回酷狗
                    ads += 1
                stale_home = 0
            elif act == "wait":
                await self.sleep(5.0)
            elif act == "close":
                await self._close_ad()
                await self._ensure_kugou_foreground()
                stale_home = 0
            elif act == "back":
                await self._ensure_kugou_foreground()   # 多退几步直到回酷狗
                stale_home = 0
            else:  # home / done：稳定页无可领入口 → 重启酷狗重新触发看广告领时长入口
                stale_home += 1
                self.dev.activate_app()
                await self.sleep(2.5)
                if stale_home >= 3:
                    # 多次回到主页仍无入口：尝试导航一次
                    await self.navigate_to_ads_page()
                    stale_home = 0
            new_remaining = await self.read_remaining_minutes()
            if new_remaining is not None:
                remaining = new_remaining
            print(f"  ▶ 已看 {ads} 次广告，当前剩余: {remaining} 分钟 (目标 {target_minutes})",
                  flush=True)
        if remaining >= target_minutes:
            print(f"  ✅ 已达目标，最终剩余 {remaining} 分钟 (≥{target_minutes})", flush=True)
        else:
            print(f"  ⚠️ 停止：剩余 {remaining} 分钟 (看了 {ads} 次广告，{steps} 步)", flush=True)
        return remaining
