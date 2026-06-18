# -*- coding: utf-8 -*-
"""薄封装 UITarsClient：本地优先，OpenRouter 兜底，保留多轮 history。"""
import sys
from pathlib import Path

# 复用 automation/ui-tars-server/inference_client.py（不重写）
_UITARS_DIR = Path(__file__).resolve().parents[1] / "ui-tars-server"
if str(_UITARS_DIR) not in sys.path:
    sys.path.insert(0, str(_UITARS_DIR))
from inference_client import UITarsClient, parse_action_simple  # noqa: E402


class UITarsAgent:
    def __init__(self, local_url, openrouter_key=None):
        self._local = UITarsClient.local(url=local_url)
        self._remote = (
            UITarsClient.openrouter(api_key=openrouter_key) if openrouter_key else None
        )
        self.history = []

    def step(self, instruction, screenshot):
        """单步：返回动作字典或 None。screenshot 为 PIL.Image。"""
        w, h = screenshot.size
        raw = self._predict_with_fallback(instruction, screenshot)
        if raw is None:
            return None
        # 维护 history（供下一轮上下文）
        try:
            client = self._last_client
            self.history = client.append_history(self.history, raw, screenshot) \
                if self.history else self._init_history(instruction, raw, screenshot, client)
        except Exception:
            pass
        return parse_action_simple(raw, w, h)

    def _predict_with_fallback(self, instruction, screenshot):
        try:
            self._last_client = self._local
            return self._local.predict(
                instruction, screenshot, history=self.history, platform="mobile"
            )
        except Exception:
            if self._remote is None:
                return None
            try:
                self._last_client = self._remote
                return self._remote.predict(
                    instruction, screenshot, history=self.history, platform="mobile"
                )
            except Exception:
                return None

    @staticmethod
    def _init_history(instruction, raw, screenshot, client):
        # 首轮：构造一个最小 history 起点
        return client.append_history([], raw, screenshot)
