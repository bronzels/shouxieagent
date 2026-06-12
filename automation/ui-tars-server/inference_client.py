"""
UI-TARS 推理客户端
封装 OpenAI SDK，提供桌面端/移动端 GUI agent 推理接口
"""

import base64
import re
from pathlib import Path
from openai import OpenAI

# 桌面端 action space prompt（官方）
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

# 移动端 action space prompt（官方）
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


def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def add_box_token(text: str) -> str:
    """为坐标添加 box token（官方后处理，用于多轮对话 history）"""
    if "Action: " not in text or "start_box=" not in text:
        return text
    suffix = text.split("Action: ")[0] + "Action: "
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
    return suffix + "\n\n".join(processed)


class UITarsClient:
    def __init__(self, base_url="http://127.0.0.1:8000/v1", api_key="empty"):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = "ui-tars"

    def predict(
        self,
        instruction: str,
        screenshot_path: str,
        history: list = None,
        platform: str = "desktop",  # "desktop" or "mobile"
        max_tokens: int = 256,
    ) -> str:
        """
        单步推理：给定截图和任务指令，返回下一步 action

        Args:
            instruction: 任务描述，如 "open browser and search for weather"
            screenshot_path: 当前屏幕截图路径
            history: 历史对话消息列表（多轮对话时传入）
            platform: "desktop" 或 "mobile"
            max_tokens: 最大输出 token 数

        Returns:
            模型输出的 Thought + Action 字符串
        """
        system_prompt = DESKTOP_SYSTEM_PROMPT if platform == "desktop" else MOBILE_SYSTEM_PROMPT
        encoded = encode_image(screenshot_path)

        messages = history or []

        # 第一轮：将 instruction 拼入 system prompt
        if not messages:
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": system_prompt + instruction},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                ]
            }]
        else:
            # 多轮：追加新截图
            messages.append({
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                ]
            })

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            frequency_penalty=1,  # 官方推荐，防止重复
            max_tokens=max_tokens,
            temperature=0.0,
        )
        return response.choices[0].message.content

    def parse_action(self, response: str, image_width: int, image_height: int) -> dict:
        """解析 action 为结构化输出（需安装 ui-tars 包）"""
        try:
            from ui_tars.action_parser import parse_action_to_structure_output
            return parse_action_to_structure_output(
                response,
                factor=1000,
                origin_resized_height=image_height,
                origin_resized_width=image_width,
                model_type="qwen25vl",
            )
        except ImportError:
            raise ImportError("请安装官方包: pip install ui-tars")


# 使用示例
if __name__ == "__main__":
    client = UITarsClient()

    # 单步推理示例
    result = client.predict(
        instruction="open the browser",
        screenshot_path="screenshot.png",
        platform="desktop",
    )
    print(result)
