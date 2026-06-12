"""
UI-TARS 推理客户端 — 可直接 import 使用

支持三种 provider：
  - "local"  : 本地/局域网 llama-cpp-python server（OpenAI 兼容），默认 http://127.0.0.1:8000
  - "remote" : Kaggle/Colab 等部署的 OpenAI 兼容 endpoint（x-api-key 鉴权）
  - "openrouter": OpenRouter（bytedance/ui-tars-1.5-7b）

快速使用：
    from inference_client import UITarsClient
    client = UITarsClient("http://192.168.3.14:8000")   # local/remote 同样用法
    action = client.ground(screenshot_path, "点击「投递」按钮")
    # → {"type": "click", "x": 493, "y": 67}
"""

import base64
import re
from io import BytesIO
from pathlib import Path
from typing import Optional

from openai import OpenAI

# ── 官方 System Prompts ────────────────────────────────────────────────────────

DESKTOP_SYSTEM_PROMPT = """You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## Output Format
```
Thought: ...
Action: ...
```

## Action Space

click(start_box='<|box_start|>(x1,y1)<|box_end|>')
left_double(start_box='<|box_start|>(x1,y1)<|box_end|>')
right_single(start_box='<|box_start|>(x1,y1)<|box_end|>')
drag(start_box='<|box_start|>(x1,y1)<|box_end|>', end_box='<|box_start|>(x3,y3)<|box_end|>')
hotkey(key='')
type(content='')
scroll(start_box='<|box_start|>(x1,y1)<|box_end|>', direction='down or up or right or left')
wait()
finished()
call_user()

## Note
- Use English in `Thought` part.
- Write a small plan and finally summarize your next action (with its target element) in one sentence in `Thought` part.

## User Instruction
"""

MOBILE_SYSTEM_PROMPT = """You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## Output Format
```
Thought: ...
Action: ...
```

## Action Space

click(start_box='<|box_start|>(x1,y1)<|box_end|>')
long_press(start_box='<|box_start|>(x1,y1)<|box_end|>', time='')
type(content='')
scroll(start_box='<|box_start|>(x1,y1)<|box_end|>', end_box='<|box_start|>(x3,y3)<|box_end|>')
press_home()
press_back()
finished(content='')

## Note
- Use English in `Thought` part.
- Write a small plan and finally summarize your next action (with its target element) in one sentence in `Thought` part.

## User Instruction
"""

# ── 工具函数 ───────────────────────────────────────────────────────────────────

def encode_image(source) -> str:
    """
    将图片编码为 base64 字符串。
    source 可以是：文件路径(str/Path)、PIL Image、bytes、BytesIO
    """
    if isinstance(source, (str, Path)):
        with open(source, "rb") as f:
            return base64.b64encode(f.read()).decode()
    if isinstance(source, bytes):
        return base64.b64encode(source).decode()
    if isinstance(source, BytesIO):
        return base64.b64encode(source.getvalue()).decode()
    # PIL Image — force pixel load before saving (avoids lazy-load FP teardown)
    buf = BytesIO()
    source.load()
    source.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def get_image_size(source) -> tuple[int, int]:
    """返回 (width, height)，用于坐标归一化。"""
    if isinstance(source, (str, Path)):
        from PIL import Image
        with Image.open(source) as img:
            return img.size
    if hasattr(source, "size"):   # PIL Image
        return source.size
    return (1920, 1080)           # 无法获取时的默认值


def add_box_token(text: str) -> str:
    """为坐标添加 box token（官方要求，用于多轮对话 history 里的 assistant 消息）"""
    if "Action: " not in text or "start_box=" not in text:
        return text
    prefix = text.split("Action: ")[0] + "Action: "
    actions = text.split("Action: ")[1:]
    processed = []
    for action in actions:
        action = action.strip()
        coords = re.findall(r"(start_box|end_box)='\((\d+),\s*(\d+)\)'", action)
        for coord_type, x, y in coords:
            action = action.replace(
                f"{coord_type}='({x},{y})'",
                f"{coord_type}='<|box_start|>({x},{y})<|box_end|>'"
            )
        processed.append(action)
    return prefix + "\n\n".join(processed)


def parse_action_simple(text: str, img_width: int, img_height: int) -> Optional[dict]:
    """
    不依赖 ui_tars 包的轻量 action 解析器。
    UI-TARS 输出的坐标是 0-1000 的相对坐标，需乘以实际分辨率归一化。

    返回形如：
      {"type": "click", "x": 493, "y": 67}
      {"type": "type", "content": "hello"}
      {"type": "scroll", "x": 500, "y": 300, "direction": "down"}
      {"type": "hotkey", "key": "ctrl+c"}
      {"type": "finished"}
      None  ← 解析失败
    """
    # 提取 Action: 之后的内容
    action_line = text
    if "Action:" in text:
        action_line = text.split("Action:")[-1].strip().split("\n")[0].strip()

    # click / left_double / right_single
    m = re.search(r"(click|left_double|right_single)\(start_box='[<|box_start|>]*\((\d+),\s*(\d+)\)", action_line)
    if m:
        action_type = {"click": "click", "left_double": "double_click", "right_single": "right_click"}[m.group(1)]
        x = round(int(m.group(2)) / 1000 * img_width)
        y = round(int(m.group(3)) / 1000 * img_height)
        return {"type": action_type, "x": x, "y": y}

    # type
    m = re.search(r"type\(content='([^']*)'\)", action_line)
    if m:
        return {"type": "type", "content": m.group(1)}

    # scroll
    m = re.search(r"scroll\(start_box='[<|box_start|>]*\((\d+),\s*(\d+)\).*?direction='(\w+)'", action_line)
    if m:
        return {"type": "scroll",
                "x": round(int(m.group(1)) / 1000 * img_width),
                "y": round(int(m.group(2)) / 1000 * img_height),
                "direction": m.group(3)}

    # drag
    m = re.search(
        r"drag\(start_box='[<|box_start|>]*\((\d+),\s*(\d+)\).*?end_box='[<|box_start|>]*\((\d+),\s*(\d+)\)",
        action_line)
    if m:
        return {"type": "drag",
                "x": round(int(m.group(1)) / 1000 * img_width),
                "y": round(int(m.group(2)) / 1000 * img_height),
                "end_x": round(int(m.group(3)) / 1000 * img_width),
                "end_y": round(int(m.group(4)) / 1000 * img_height)}

    # hotkey
    m = re.search(r"hotkey\(key='([^']*)'\)", action_line)
    if m:
        return {"type": "hotkey", "key": m.group(1)}

    # finished / wait / call_user
    for kw in ("finished", "wait", "call_user", "press_home", "press_back"):
        if kw in action_line:
            return {"type": kw}

    return None


# ── 主类 ───────────────────────────────────────────────────────────────────────

class UITarsClient:
    """
    UI-TARS 推理客户端，封装 OpenAI SDK。

    Args:
        base_url: OpenAI 兼容 API 地址
                  - local/remote: "http://192.168.3.14:8000/v1"
                  - openrouter:   "https://openrouter.ai/api/v1"
        api_key:  local 填任意值；openrouter 填 sk-or-v1-xxx
        model:    local 填 GGUF 路径或 None（自动从 /v1/models 取第一个）
                  openrouter 填 "bytedance/ui-tars-1.5-7b"
        timeout:  请求超时秒数（local 推理较慢，建议 120）
    """

    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL = "bytedance/ui-tars-1.5-7b"
    LOCAL_DEFAULT_URL = "http://127.0.0.1:8000/v1"

    def __init__(
        self,
        base_url: str = LOCAL_DEFAULT_URL,
        api_key: str = "none",
        model: Optional[str] = None,
        timeout: float = 120.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._client = OpenAI(base_url=self._base_url, api_key=api_key, timeout=timeout)
        self._model = model  # None → 延迟查询

    @classmethod
    def local(cls, url: str = LOCAL_DEFAULT_URL, **kwargs) -> "UITarsClient":
        """工厂方法：连接本地/局域网 llama-cpp-python server"""
        return cls(base_url=url, api_key="none", **kwargs)

    @classmethod
    def openrouter(cls, api_key: str, **kwargs) -> "UITarsClient":
        """工厂方法：连接 OpenRouter"""
        return cls(
            base_url=cls.OPENROUTER_BASE_URL,
            api_key=api_key,
            model=cls.OPENROUTER_MODEL,
            **kwargs,
        )

    @property
    def model(self) -> str:
        if self._model:
            return self._model
        # 从 /v1/models 取第一个（适用于 llama-cpp-python server）
        models = self._client.models.list()
        self._model = models.data[0].id
        return self._model

    def predict(
        self,
        instruction: str,
        screenshot,
        history: list = None,
        platform: str = "desktop",
        max_tokens: int = 256,
    ) -> str:
        """
        单步推理：返回原始 Thought + Action 字符串。

        Args:
            instruction:  任务描述，如 "点击「立即投递」按钮"
            screenshot:   截图，支持文件路径/PIL Image/bytes/BytesIO
            history:      多轮对话历史（上一轮 predict 返回后用 append_history 添加）
            platform:     "desktop" 或 "mobile"
            max_tokens:   最大输出 token 数
        """
        system_prompt = DESKTOP_SYSTEM_PROMPT if platform == "desktop" else MOBILE_SYSTEM_PROMPT
        img_b64 = encode_image(screenshot)

        if not history:
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": system_prompt + instruction},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                ],
            }]
        else:
            messages = list(history)
            messages.append({
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                ],
            })

        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            frequency_penalty=1,   # 官方要求，防止输出重复
            max_tokens=max_tokens,
            temperature=0.0,
        )
        return resp.choices[0].message.content

    def ground(
        self,
        screenshot,
        instruction: str,
        platform: str = "desktop",
        max_tokens: int = 128,
    ) -> Optional[dict]:
        """
        UI Grounding：截图 + 自然语言指令 → 结构化动作字典。
        适合投简历脚本直接调用。

        返回示例：
          {"type": "click", "x": 493, "y": 67}
          {"type": "type", "content": "你好"}
          {"type": "scroll", "x": 500, "y": 300, "direction": "down"}
          None  ← 模型无法完成或解析失败
        """
        w, h = get_image_size(screenshot)
        raw = self.predict(instruction, screenshot, platform=platform, max_tokens=max_tokens)
        return parse_action_simple(raw, w, h)

    def append_history(self, history: list, response: str, screenshot) -> list:
        """
        将本轮的 assistant 回复和截图追加到 history，用于多轮对话。
        注意：assistant 消息里的坐标需要加 box token（官方要求）。
        """
        history = list(history)
        history.append({"role": "assistant", "content": add_box_token(response)})
        img_b64 = encode_image(screenshot)
        history.append({
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            ],
        })
        return history


# ── 命令行快速测试 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, sys

    parser = argparse.ArgumentParser(description="UI-TARS 推理客户端测试")
    parser.add_argument("screenshot", help="截图文件路径")
    parser.add_argument("instruction", help="自然语言指令，如 '点击搜索按钮'")
    parser.add_argument("--url", default=UITarsClient.LOCAL_DEFAULT_URL,
                        help=f"推理服务地址，默认 {UITarsClient.LOCAL_DEFAULT_URL}")
    parser.add_argument("--openrouter-key", default=None, help="OpenRouter API key（使用 OpenRouter 时填）")
    args = parser.parse_args()

    if args.openrouter_key:
        client = UITarsClient.openrouter(api_key=args.openrouter_key)
    else:
        client = UITarsClient.local(url=args.url)

    print(f"Model: {client.model}")
    result = client.ground(args.screenshot, args.instruction)
    print(f"Action: {result}")

    raw = client.predict(args.instruction, args.screenshot)
    print(f"\nRaw output:\n{raw}")
