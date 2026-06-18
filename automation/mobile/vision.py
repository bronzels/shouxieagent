"""视觉/LLM 层：只用 UI-TARS 这一类 GUI grounding 模型（本地优先 + OpenRouter 同款 fallback）。
自包含借鉴自 automation/web/zhipin_apply.py（去除 pyautogui/playwright 依赖与文字模型链）。"""
import asyncio
import base64
import json
import re

import httpx

OPENROUTER_API_KEY = ""
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
UITARS_LOCAL_URL = "http://192.168.3.14:8000/v1"
UITARS_MODEL = "bytedance/ui-tars-1.5-7b"

# 本任务只用 UI-TARS 这一类 GUI grounding 模型，不引入独立文字/多模态模型链。
# OpenRouter 仅作本地 UI-TARS 不可达时的同款模型 fallback（models=[UITARS_MODEL]）。


def configure(openrouter_key: str, uitars_local_url: str) -> None:
    global OPENROUTER_API_KEY, UITARS_LOCAL_URL
    if openrouter_key:
        OPENROUTER_API_KEY = openrouter_key
    if uitars_local_url:
        UITARS_LOCAL_URL = uitars_local_url


def image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


async def _post_openrouter(payload: dict, models: list = None, paid_models: list = None) -> dict:
    """OpenRouter 模型 fallback 链：逐个 model 试，全失败退避重试整轮（最多3轮）。
    本任务仅以 models=[UITARS_MODEL] 调用（本地 UI-TARS 不可达时的同款 fallback）。"""
    model_list = models or [payload.get("model")]
    delay = 4.0
    last_err = "unknown"
    async with httpx.AsyncClient(timeout=120.0) as client:
        for rnd in range(3):
            for model in model_list:
                body = dict(payload)
                body["model"] = model
                try:
                    r = await client.post(
                        f"{OPENROUTER_BASE_URL}/chat/completions",
                        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                        json=body,
                    )
                    if r.status_code == 200:
                        return r.json()
                    last_err = f"{model} HTTP {r.status_code}"
                except Exception as e:  # noqa: BLE001
                    last_err = f"{model} {str(e)[:60]}"
            if rnd < 2:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 40)
    raise RuntimeError(f"OpenRouter 模型多轮失败: {last_err}")


def _post_uitars_local_sync(payload: dict) -> dict:
    """连本地 llama-cpp-python server（OpenAI 兼容），同步调用。"""
    from openai import OpenAI
    client = OpenAI(base_url=UITARS_LOCAL_URL, api_key="none", timeout=120.0)
    model = client.models.list().data[0].id
    resp = client.chat.completions.create(
        model=model,
        messages=payload["messages"],
        max_tokens=payload.get("max_tokens", 512),
        frequency_penalty=1,
    )
    return {"choices": [{"message": {"content": resp.choices[0].message.content}}]}


async def call_uitars(image_path: str, task_prompt: str) -> str:
    """UI-TARS grounding：本地优先，连续失败 fallback 到 OpenRouter 同款 ui-tars。返回含 Action 的文本。"""
    from ui_tars.prompt import COMPUTER_USE_DOUBAO
    img_b64 = image_to_base64(image_path)
    prompt_text = COMPUTER_USE_DOUBAO.format(instruction=task_prompt, language="Chinese")
    payload = {
        "model": UITARS_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": prompt_text},
            ],
        }],
        "max_tokens": 512,
    }
    # 本地优先，3 次重试
    for attempt in range(3):
        try:
            result = await asyncio.to_thread(_post_uitars_local_sync, payload)
            content = result["choices"][0]["message"]["content"]
            if content and content.strip():
                return content
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print(f"  ⚠️ 本地 UI-TARS 连续失败({str(e)[:60]})，fallback OpenRouter", flush=True)
            await asyncio.sleep(2.0 * (attempt + 1))
    # fallback：OpenRouter 同款 ui-tars
    result = await _post_openrouter(payload, models=[UITARS_MODEL])
    return result["choices"][0]["message"]["content"]


def _parse_point(response: str) -> tuple[float, float] | None:
    """解析 UI-TARS 响应中的坐标，返回 0-1 归一化 (nx, ny)。
    优先用 ui_tars 包，失败则正则兜底（坐标系 0-1000）。"""
    try:
        from ui_tars.action_parser import parse_action_to_structure_output
        parsed = parse_action_to_structure_output(
            response, factor=1000, origin_resized_height=1000,
            origin_resized_width=1000, model_type="qwen25vl")
        if parsed:
            box = json.loads(parsed[0]["action_inputs"]["start_box"])
            return (box[0], box[1])
    except Exception:  # noqa: BLE001
        pass
    m = (re.search(r"<point>\s*(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)\s*</point>", response)
         or re.search(r"\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\)", response)
         or re.search(r"\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)", response))
    if m:
        return (float(m.group(1)) / 1000.0, float(m.group(2)) / 1000.0)
    return None


async def locate(image_path: str, instruction: str, width: int, height: int) -> tuple[int, int] | None:
    """返回点击像素坐标 (px, py)；定位失败返回 None。"""
    resp = await call_uitars(image_path, instruction)
    norm = _parse_point(resp)
    if norm is None:
        return None
    return (int(round(norm[0] * width)), int(round(norm[1] * height)))


async def read_text(image_path: str, question: str) -> str:
    """UI-TARS OCR 兜底：用同一 UI-TARS 模型读屏回答（普通问题，非动作 prompt），
    不使用独立文字/多模态模型。本地优先，失败 fallback OpenRouter 同款 ui-tars。"""
    img_b64 = image_to_base64(image_path)
    payload = {
        "model": UITARS_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": question},
            ],
        }],
        "max_tokens": 256,
    }
    try:
        result = await asyncio.to_thread(_post_uitars_local_sync, payload)
        content = result["choices"][0]["message"]["content"]
        if content and content.strip():
            return content
    except Exception:  # noqa: BLE001
        pass
    result = await _post_openrouter(payload, models=[UITARS_MODEL])
    return result["choices"][0]["message"]["content"] or ""
