# -*- coding: utf-8 -*-
"""薄封装 UITarsClient：本地优先，OpenRouter 兜底，保留多轮 history。"""
import sys
from pathlib import Path

# 复用 automation/ui-tars-server/inference_client.py（不重写）
_UITARS_DIR = Path(__file__).resolve().parents[1] / "ui-tars-server"
if str(_UITARS_DIR) not in sys.path:
    sys.path.insert(0, str(_UITARS_DIR))
from inference_client import (  # noqa: E402
    UITarsClient, parse_action_simple, MOBILE_SYSTEM_PROMPT,
    encode_image, add_box_token,
)


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
            self._record_turn(instruction, raw, screenshot)
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

    def _record_turn(self, instruction, raw, screenshot):
        """把本轮发送的 user 消息 + assistant 回复追加到 history，
        使 history 与 predict() 实际发送的 messages 序列一致。"""
        img_b64 = encode_image(screenshot)
        image_part = {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        }
        if not self.history:
            user_msg = {"role": "user", "content": [
                {"type": "text", "text": MOBILE_SYSTEM_PROMPT + instruction},
                image_part,
            ]}
        else:
            user_msg = {"role": "user", "content": [image_part]}
        self.history.append(user_msg)
        self.history.append({"role": "assistant", "content": add_box_token(raw)})
