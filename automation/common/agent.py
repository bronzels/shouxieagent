"""主循环：感知(UI-TARS读屏)→决策(规则)→定位(UI-TARS)→执行+读时长，直到 ≥ 目标。

酷狗启动/首页状态多变(开屏广告/内测版/挽留弹窗/夺宝游戏)，故用感知-决策-执行循环：
每步截图让 UI-TARS 描述当前屏 → decide_action 规则判断该干什么 → UI-TARS 定位目标按钮点击。
看广告时先从文案读出要求秒数(如『看15秒』)，定时看够即关闭，不死等浪费时间。
"""
import asyncio
import os

import parsers

ENTRY_KEYWORDS = ["免费听歌模式", "免费听歌", "免费畅听", "看广告", "领时长", "去浏览", "看视频", "免费领", "免"]
# 酷狗主页进入「免费听歌模式」任务中心的入口：搜索框右边那个蓝色圆角方框里的「免」字图标
ENTRY_INSTRUCTION = (
    "点击屏幕顶部搜索框右边那个蓝色圆角方框里的『免』字图标（免费听歌模式入口，"
    "在扫一扫图标右边）。注意：不要点搜索框本身，要点它右边的蓝色『免』图标。")
WATCH_KEYWORDS = ["点击浏览", "送惊喜奖励", "看广告", "看视频", "立即领取", "领取", "观看", "去观看", "去浏览"]
CLOSE_KEYWORDS = ["关闭", "跳过", "×", "X", "✕", "领取", "完成"]
# 提前想退出广告时酷狗的挽留弹窗(『要放弃免费听歌吗/确定放弃奖励』)：必须点『继续浏览』保住奖励，
# 绝不能点『坚持退出/放弃/开通会员』，否则白看广告、时长不增加。
CONTINUE_KEYWORDS = ["点击继续浏览", "继续浏览", "继续观看", "再看一会", "继续领取", "继续"]
GIVEUP_QUESTION = (
    "屏幕上有没有『要放弃免费听歌吗』『确定放弃奖励』『再浏览X秒可获得奖励』『坚持退出』"
    "这类挽留弹窗(提示再看/再浏览一会就能领到免费听歌时长奖励)？只回答『有』或『无』。")
# 校验是否到了「免费听歌模式」任务中心(用于导航后确认没进错页面)
CENTER_QUESTION = (
    "这个页面是不是酷狗的『免费听歌模式』任务中心(顶部有『免费畅听剩余时长』，下方有"
    "『去浏览/去观看』之类看广告领免费听歌时长的任务列表)？只回答『是』或『否』。")
# 校验是否在酷狗主页(顶部有搜索框和右边的『免』图标入口，不是排行榜/搜索/详情等子页)
HOME_QUESTION = (
    "这个页面是不是酷狗音乐的主页(顶部有搜索框、右边有蓝色『免』图标，底部导航『首页』高亮)？"
    "如果是排行榜/搜索/歌单/详情等带左上角『<』返回箭头的子页面就回答『否』。只回答『是』或『否』。")
REMAIN_QUESTION = (
    "这个页面顶部『免费畅听剩余时长』显示的数字是多少？它的格式是 分:秒"
    "（例如 533:23 表示还剩 533 分钟 23 秒）。请把这个数字原样回答，如『533:23』，"
    "千万不要把它当成小时:分钟、也不要换算成小时。如果页面没有明确的免费听歌剩余时长，"
    "就回答『无』。绝对不要把金额(元)、夺宝/宝箱倒计时、歌曲时长、当前时间当作听歌时长。")
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
    def __init__(self, device, vision, sleep=asyncio.sleep,
                 shots_dir="automation/mobile/reports/screenshots"):
        self.dev = device
        self.vis = vision
        self.sleep = sleep
        self._shots_dir = shots_dir
        self._shot_i = 0

    def _shot(self) -> str:
        self._shot_i += 1
        path = os.path.join(self._shots_dir, f"run-{self._shot_i:04d}.png")
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

    # 广告落地页的关闭X位置(占屏比例)：浏览落地页(淘宝/美团)在左上、连续广告流在右上
    LANDING_CLOSE_FRACTIONS = ((0.15, 0.075), (0.945, 0.106))
    # 中心底部的奖励弹窗CTA「点击浏览5秒，送惊喜奖励」位置(占屏比例)——实测最快领奖路径(链式领下一个)
    REWARD_CTA_FRACTION = (0.5, 0.88)

    async def _start_browse_task(self, label: str) -> bool:
        """开始一个看广告/浏览领时长任务。优先视觉点任务按钮；未命中则点中心底部
        『点击浏览5秒，送惊喜奖励』奖励弹窗CTA(坐标，实测最快链式领奖路径)。返回是否已开始。"""
        if await self._locate_tap(
                f"点击『{label}/点击浏览5秒/送惊喜奖励/去浏览/去观看』按钮看广告领免费听歌时长",
                WATCH_KEYWORDS):
            return True
        # 视觉没命中 → 点底部奖励弹窗CTA坐标兜底
        w, h = self.dev.screen_size()
        fx, fy = self.REWARD_CTA_FRACTION
        self.dev.tap(int(w * fx), int(h * fy))
        await self.sleep(2.0)
        return True

    async def _close_ad_landing(self) -> bool:
        """看完广告/浏览后【点广告自带的关闭X来领取奖励】，绝不能用返回键。
        实测铁律：用系统返回键(back)关广告=放弃奖励、白看；只有点广告X才真正计入并加时长。
        X 位置因落地页而异，依次尝试：左上角坐标→视觉定位→右上角坐标，每次用是否回到中心校验。
        返回 True 表示已回到免费听歌中心(领奖成功)。"""
        w, h = self.dev.screen_size()
        fx, fy = self.LANDING_CLOSE_FRACTIONS[0]      # 左上角(浏览落地页, 实测可靠)
        self.dev.tap(int(w * fx), int(h * fy))
        await self.sleep(2.0)
        if await self._on_ads_center():
            return True
        # 视觉兜底找关闭X(明确不是左上角返回箭头‹)
        if await self._locate_tap(
                "点击关闭这个广告/浏览页面的『X』或『×』关闭按钮以领取免费听歌奖励"
                "(是关闭按钮，不是左上角的返回箭头‹)", []):
            await self.sleep(2.0)
            if await self._on_ads_center():
                return True
        fx2, fy2 = self.LANDING_CLOSE_FRACTIONS[1]    # 右上角(连续广告流)
        self.dev.tap(int(w * fx2), int(h * fy2))
        await self.sleep(2.0)
        if await self._on_ads_center():
            return True
        # 兜底：所有关闭X都没回到中心 → 直接按返回键逃出避免卡死(本次可能未领到奖励)
        # (落地页是酷狗内webview, current_package仍是酷狗, 不能靠_in_kugou判断, 直接back)
        for _ in range(2):
            self.dev.back()
            await self.sleep(1.2)
            if await self._on_ads_center():
                return True
        return False

    async def _handle_giveup_popup(self, browse_secs: int) -> bool:
        """检测『要放弃免费听歌吗/放弃奖励』挽留弹窗：有就点『继续浏览』保住奖励、再浏览够时间，
        绝不点『坚持退出/放弃』。返回 True 表示处理过弹窗(继续浏览了)。
        这是时长不增加的主因：浏览没够就退出会触发该弹窗、放弃则白看广告。"""
        ans = await self.vis.read_text(self._shot(), GIVEUP_QUESTION)
        if "有" in ans and "无" not in ans:
            await self._locate_tap(
                "点击『继续浏览/点击继续浏览/继续观看』按钮（绝对不要点坚持退出/放弃/开通会员）",
                CONTINUE_KEYWORDS)
            await self.sleep(browse_secs + 4)   # 点继续后把要求的浏览时间看够
            return True
        return False

    def _in_kugou(self) -> bool:
        return "kugou" in (self.dev.current_package() or "").lower()

    async def _on_ads_center(self) -> bool:
        """是否在『免费听歌模式』任务中心(导航后校验，避免误进搜索/其他页却以为成功)。"""
        ans = await self.vis.read_text(self._shot(), CENTER_QUESTION)
        return ("是" in ans) and ("否" not in ans) and ("不是" not in ans)

    async def _on_kugou_home(self) -> bool:
        """是否在酷狗主页(顶部有搜索框+『免』图标，非排行榜/搜索等子页)。"""
        ans = await self.vis.read_text(self._shot(), HOME_QUESTION)
        return ("是" in ans) and ("否" not in ans) and ("不是" not in ans)

    async def _try_claim_reward(self) -> bool:
        """批量模式累计够条数后，页面会出现『领取/领取奖励/领时长』按钮 → 点它领奖。
        没有可领的就什么都不做（返回 False）。仅当 UI-TARS 明确看到领取按钮才点。"""
        q = ("这个酷狗页面上有没有【已点亮/可领取】的『领取/领取奖励/领时长/立即领取』按钮"
             "(不是『去完成/去观看』)？只回答『有:按钮文字』或『无』。")
        ans = await self.vis.read_text(self._shot(), q)
        if "无" in ans and "有" not in ans:
            return False
        if "领取" in ans or "领时长" in ans or "立即领" in ans:
            return await self._locate_tap("点击可领取的『领取奖励/领时长』按钮（不是去完成）",
                                          ["领取", "领时长", "立即领取"])
        return False

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
        """归位到酷狗【主页】。activate_app 常恢复到上次的子页(如排行榜/搜索)，
        此时『免』图标坐标会点空，故连按返回(=点左上角『<』)退出子页直到检测确认回到主页。
        检测到主页就停，避免在主页多按返回触发退出酷狗。"""
        self.dev.activate_app()
        await self.sleep(2.0)
        if "com.kugou" not in self.dev.current_package():
            self.dev.activate_app()
            await self.sleep(2.0)
        # 退出任何子页回主页(最多5步)：到主页即停
        for _ in range(5):
            if await self._on_kugou_home():
                return
            self.dev.back()      # 等同点左上角『<』返回上一页
            await self.sleep(1.5)

    # 「免」图标在主页搜索框右边、屏幕右上角，按屏幕比例定位
    # （UI-TARS 对这个紧贴搜索框的小图标视觉定位不可靠，实测常误点成搜索框→进搜索页，故用坐标）
    ENTRY_FRACTION_XY = (0.827, 0.133)

    async def navigate_to_ads_page(self) -> bool:
        """进入「免费听歌模式」任务中心：坐标点主页搜索框右边的蓝色「免」图标。
        鲁棒性：点完校验是否真到了中心；没到(误进搜索/其他页)就 back 退回再试，绝不卡在错误页。"""
        w, h = self.dev.screen_size()
        ex = int(w * self.ENTRY_FRACTION_XY[0])
        ey = int(h * self.ENTRY_FRACTION_XY[1])
        for _ in range(4):
            self.dev.tap(ex, ey)            # 坐标点『免』图标(不靠视觉)
            await self.sleep(2.0)
            if await self._on_ads_center():
                return True
            # 没进对(可能误触到别的) → 退回去重试，不卡死
            self.dev.back()
            await self.sleep(1.2)
        # 坐标多次未成功，最后用视觉精确指令兜底一次
        if await self._locate_tap(ENTRY_INSTRUCTION, ENTRY_KEYWORDS):
            await self.sleep(2.0)
            return await self._on_ads_center()
        return False

    # 免费听歌剩余时长的合理上限(分钟)：超过视为误读(如把 533:23 分:秒误当 533小时23分=32003)
    MAX_PLAUSIBLE_MINUTES = 6000  # 100 小时

    def _sane(self, mins: int | None) -> int | None:
        """过滤误读：负数或大于合理上限的一律视为无效(None)。"""
        if mins is None or mins < 0 or mins > self.MAX_PLAUSIBLE_MINUTES:
            return None
        return mins

    async def read_remaining_minutes(self) -> int | None:
        # 主路径：UI-TARS OCR 读屏（酷狗自绘文字不进无障碍树）
        txt = await self.vis.read_text(self._shot(), REMAIN_QUESTION)
        mins = self._sane(parsers.parse_duration_to_minutes(txt))
        if mins is not None:
            return mins
        # 兜底：扫 page_source XML
        return self._sane(parsers.extract_duration_from_xml(self.dev.page_source()))

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
                if await self._start_browse_task(label):
                    await self.sleep(secs + 5)   # 先浏览够要求秒数(+缓冲)，浏览不够会触发放弃挽留弹窗
                    # 浏览没够想退出会弹『要放弃免费听歌吗』→ 点继续浏览看够再领，最多两轮，绝不放弃奖励
                    for _ in range(2):
                        if not await self._handle_giveup_popup(secs):
                            break
                    # 【铁律】点广告自带的关闭X领奖，绝不用返回键(返回=放弃奖励、白看广告)
                    on_center = await self._close_ad_landing()
                    await self._handle_giveup_popup(secs)   # 关闭时若再弹挽留，再继续浏览一次
                    if not on_center and not await self._on_ads_center():
                        await self.navigate_to_ads_page()   # 没回到中心就重新导航回去
                    ads += 1
                    # 累计够任务数后会出现领取按钮 → 领奖（中途时长不涨是正常的）
                    if await self._try_claim_reward():
                        print("    🎁 领取了已解锁的奖励", flush=True)
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
            # 单调性护栏：免费时长不可能一步骤降(看完广告常落在非中心页、读到乱数)。
            # 只接受小幅下降(自然消耗)或上涨(领到奖励)；骤降视为误读丢弃。
            if new_remaining is not None and new_remaining >= remaining - 30:
                remaining = new_remaining
            elif new_remaining is not None:
                print(f"    (忽略疑似误读 {new_remaining} 分钟，保持 {remaining})", flush=True)
            print(f"  ▶ 已看 {ads} 次广告，当前剩余: {remaining} 分钟 (目标 {target_minutes})",
                  flush=True)
        if remaining >= target_minutes:
            print(f"  ✅ 已达目标，最终剩余 {remaining} 分钟 (≥{target_minutes})", flush=True)
        else:
            print(f"  ⚠️ 停止：剩余 {remaining} 分钟 (看了 {ads} 次广告，{steps} 步)", flush=True)
        return remaining
