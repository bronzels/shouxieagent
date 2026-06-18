# -*- coding: utf-8 -*-
"""酷狗刷 VIP 任务状态机。纯编排，外部副作用经注入依赖。"""
import hashlib

INSTRUCTIONS = {
    "START": "如果当前不在酷狗音乐app内，找到并打开酷狗音乐app；如果已在酷狗内，进入下一步。",
    "LOCATE_ENTRY": (
        "在酷狗音乐里找到『免费看广告领VIP』或『看视频得会员』『免费领会员时长』的入口并点击；"
        "若当前页没有，去『我的』或『VIP中心』页面下滑查找。"
    ),
    "WATCH_AD": (
        "如果有『看视频』『立即领取』按钮就点击开始看广告；"
        "如果广告正在播放就等待；广告播完后点击右上角『关闭/×/跳过』和『领取奖励』。"
    ),
    "CHECK_PROGRESS": (
        "查看已新增的VIP累计时长是否已达到目标新增量；"
        "如果已达到就结束；否则返回继续看广告。"
    ),
}


class KugouTask:
    def __init__(self, window, agent, inp, add_hours=14, max_rounds=200,
                 stale_limit=4, max_grounding_retries=3):
        self.window = window
        self.agent = agent
        self.inp = inp
        self.add_hours = add_hours
        self.max_rounds = max_rounds
        self.stale_limit = stale_limit
        self.max_grounding_retries = max_grounding_retries
        self.INSTRUCTIONS = INSTRUCTIONS

    @staticmethod
    def _screen_hash(img):
        small = img.resize((16, 16)).convert("L")
        return hashlib.md5(small.tobytes()).hexdigest()

    def run(self):
        rounds = 0
        fail_streak = 0
        stale_streak = 0
        last_hash = None
        instruction = self._compose()

        while rounds < self.max_rounds:
            rounds += 1
            self.window.activate()
            img, win_rect = self.window.grab()

            h = self._screen_hash(img)
            stale_streak = stale_streak + 1 if h == last_hash else 0
            last_hash = h

            action = self.agent.step(instruction, img)

            if action is None:
                fail_streak += 1
                if fail_streak >= self.max_grounding_retries:
                    return {"status": "failed", "rounds": rounds}
                continue
            fail_streak = 0

            if action.get("type") == "finished":
                return {"status": "done", "rounds": rounds}

            # 卡死：连续 stale_limit 步画面不变 → 注入返回键跳出
            if stale_streak >= self.stale_limit:
                self.inp.do({"type": "press_back"}, self.window, win_rect, img.size)
                stale_streak = 0
                continue

            self.inp.do(action, self.window, win_rect, img.size)

        return {"status": "max_rounds", "rounds": rounds}

    def _compose(self):
        # 单条综合指令，让 UI-TARS 自主决策完整任务路径
        return (
            f"任务：在酷狗音乐app里通过反复点击『免费看广告』新增{self.add_hours}小时的免费VIP听歌时长，"
            f"达到后输出 finished()。"
            f"{self.INSTRUCTIONS['START']} {self.INSTRUCTIONS['LOCATE_ENTRY']} "
            f"{self.INSTRUCTIONS['WATCH_AD']} {self.INSTRUCTIONS['CHECK_PROGRESS']} "
            f"全部完成后输出 finished()。"
        )
