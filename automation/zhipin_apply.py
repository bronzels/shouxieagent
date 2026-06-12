# -*- coding: utf-8 -*-
"""
Boss直聘自动投递脚本
- 使用 OpenRouter UI-TARS-1.5-7B 理解页面UI并决定操作
- 使用 Playwright 控制浏览器
- 使用 Google Gemini-2.5-Flash 验证职位是否为IT软件类远程/WFH
- 模拟人类鼠标操作，随机延迟防止反爬
- 自动遍历热门城市，搜索"远程"关键字
- 去重记录已投递职位，避免重复投递
"""

import asyncio
import base64
import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path

# 从 .env 文件加载环境变量（如果存在）
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

import httpx
import pyautogui
# 使用 rebrowser-playwright：修补了 CDP Runtime.enable 指纹泄露的 Playwright 分支。
# Boss直聘的反爬 JS 会检测原版 Playwright 的 CDP 痕迹并把页面跳转到 about:blank。
from rebrowser_playwright.async_api import async_playwright, Page, Browser

import zhipin_status  # 对方回应状态过滤（所有 apply 任务共享）

# ─── 配置 ────────────────────────────────────────────────────────────────────

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

UITARS_MODEL = "bytedance/ui-tars-1.5-7b"

# ─── UI-TARS 提供方式（由命令行参数在 main 中赋值，见文件末尾 argparse）──────────
# UI-TARS 模型有 3 种提供方式，仅影响 call_uitars 的调用路径，
# 不影响验证职位的 VERIFY_MODELS_*（那两类始终走 OpenRouter）。
#   - "openrouter"（默认）：UI-TARS 走 OpenRouter，复用 OpenRouter key 与 _post_openrouter
#   - "remote"：UI-TARS 走 Kaggle/Colab 等部署的 OpenAI 兼容 endpoint，
#               key 放在 header 的 x-api-key 字段（不是 Authorization Bearer）
#   - "local"：本地推理（用户搭建中，暂未实现），调用时抛 NotImplementedError 优雅跳过
UITARS_PROVIDER = "openrouter"   # openrouter / remote / local
UITARS_ENDPOINT = ""             # remote 方式的完整 URL（如 https://xxx.ngrok.io/v1/chat/completions）
UITARS_KEY = ""                  # remote 方式的鉴权 key（放 x-api-key header）
# local 方式将来本地推理服务地址（OpenAI 兼容），当前未实现，仅占位
UITARS_LOCAL_URL = "http://127.0.0.1:8000/v1/chat/completions"
# 验证职位用纯文本免费模型 fallback 链：免费模型 provider 容量经常被打满返回 429，
# 依次尝试，哪个不限流用哪个（实时核验均为 :free）。Qwen 中文最强但最易限流，放第一位，
# 后面用同样响应过的 gpt-oss / gemma / llama 兜底。
VERIFY_MODELS_TEXT = [
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "openai/gpt-oss-120b:free",
    "google/gemma-4-31b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
]
# 抓不到正文时用免费多模态模型（带截图判断）
VERIFY_MODELS_MULTIMODAL = [
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
]
# 正文文本判定为"足够"的最小长度；低于此视为反爬导致抓取失败，触发滚动重抓/多模态兜底
MIN_DESC_LEN = 40

APPLIED_JOBS_FILE = Path(__file__).parent / "applied_jobs.json"
SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)
# 最终统计 CSV 单独目录
REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# 搜索关键词（"远程 软件" 用空格分隔，更聚焦 IT 软件类远程岗）
SEARCH_KEYWORD = "远程 软件"

# 热门城市 → Boss直聘城市编码。
# 这 14 个城市与"地图→请选择城市→热门城市"面板里展示的完全一致（实测核对），
# 城市码经地图面板点击验证（例：点'杭州'后 URL city=101210100）。
# 列表搜索结果页 URL：https://www.zhipin.com/web/geek/jobs?query=远程&city=<code>
# 地图版职位页 URL：https://www.zhipin.com/web/geek/map/jobs?query=远程&cityCode=<code>
CITY_CODES = {
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "天津": "101030100",
    "西安": "101110100",
    "苏州": "101190400",
    "武汉": "101200100",
    "厦门": "101230200",
    "长沙": "101250100",
    "成都": "101270100",
    "郑州": "101180100",
    "重庆": "101040100",
}
DEFAULT_HOT_CITIES = list(CITY_CODES.keys())

# 人类操作延迟范围（秒）
# 策略：检查/跳过的职位走快速延迟（读取动作为主，对 zhipin 真实请求少，风险低）；
#       真正投递（立即沟通发招呼）走稳健延迟（发真实消息，且有每日打招呼上限，需谨慎）。
DELAY_MIN = 0.8          # 职位间隔（检查阶段，下调）
DELAY_MAX = 1.8
CARD_DELAY_MIN = 1.2     # 点职位卡→详情面板（检查阶段，下调）
CARD_DELAY_MAX = 2.2
APPLY_DELAY_MIN = 3.0    # 投递动作（立即沟通后）保持稳健
APPLY_DELAY_MAX = 5.0

# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def load_applied_jobs() -> dict:
    """加载已投递职位记录（含已完成城市列表，用于双重去重）"""
    if APPLIED_JOBS_FILE.exists():
        with open(APPLIED_JOBS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("jobs", [])
            data.setdefault("completed_cities", [])
            data.setdefault("last_updated", "")
            return data
    return {"jobs": [], "completed_cities": [], "last_updated": ""}


def save_applied_jobs(data: dict):
    """保存已投递职位记录"""
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(APPLIED_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_already_applied(data: dict, company: str, position: str) -> bool:
    """检查是否已投递过该职位"""
    key = f"{company.strip()}|{position.strip()}"
    return any(
        f"{j['company'].strip()}|{j['position'].strip()}" == key
        for j in data["jobs"]
    )


def record_application(data: dict, company: str, position: str, city: str):
    """记录投递"""
    data["jobs"].append({
        "company": company,
        "position": position,
        "city": city,
        "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    save_applied_jobs(data)
    print(f"  ✅ 已记录投递：{company} | {position} ({city})")


def is_city_completed(data: dict, city: str) -> bool:
    """该城市是否已在之前的运行中处理完成"""
    return city in data.get("completed_cities", [])


def mark_city_completed(data: dict, city: str):
    """标记城市处理完成，下次运行跳过"""
    if city not in data["completed_cities"]:
        data["completed_cities"].append(city)
        save_applied_jobs(data)
        print(f"  🏁 城市 [{city}] 处理完成，已记录（下次运行将跳过）")


def export_applications_csv(data: dict) -> str:
    """
    把投递记录导出为 CSV，放到单独的 reports/ 目录。
    文件名包含【投递时间】+【搜索内容】，例如：
      投递记录_远程软件_20260612_143000.csv
    用 utf-8-sig（带 BOM），Excel 打开中文不乱码。
    返回 CSV 文件路径。
    """
    import csv
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    kw = re.sub(r"\s+", "", SEARCH_KEYWORD)  # "远程 软件" -> "远程软件"
    fname = f"投递记录_{kw}_{ts}.csv"
    path = REPORTS_DIR / fname
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        # 表头：搜索内容 + 生成时间 作为元信息行，再写列名
        w.writerow([f"搜索内容：{SEARCH_KEYWORD}",
                    f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"投递总数：{len(data.get('jobs', []))}",
                    f"完成城市：{'/'.join(data.get('completed_cities', []))}"])
        w.writerow(["序号", "公司", "职位", "城市", "投递时间"])
        for i, j in enumerate(data.get("jobs", []), 1):
            w.writerow([i, j.get("company", ""), j.get("position", ""),
                        j.get("city", ""), j.get("applied_at", "")])
    return str(path)


def human_delay(min_s: float = DELAY_MIN, max_s: float = DELAY_MAX):
    """模拟人类随机延迟"""
    t = random.uniform(min_s, max_s)
    time.sleep(t)


def image_to_base64(image_path: str) -> str:
    """将图片文件转为 base64 字符串"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


async def screenshot_page(page: Page, filename: str) -> str:
    """截图当前页面，返回文件路径"""
    path = str(SCREENSHOTS_DIR / filename)
    await page.screenshot(path=path, full_page=False)
    return path


# ─── OpenRouter API 调用 ──────────────────────────────────────────────────────

async def _post_openrouter(payload: dict, models: list = None, max_rounds: int = 3) -> dict:
    """
    调用 OpenRouter，支持免费模型 fallback 链 + 429/5xx 退避重试。
    - models：要依次尝试的 model id 列表（免费模型 provider 常被打满 429，
      逐个尝试，哪个不限流用哪个）。不传则用 payload["model"] 单模型。
    - 单模型 429 立即换下一个模型；整轮所有模型都 429 才退避等待重试整轮。
    - 尊重 429 响应里的 retry_after_seconds / Retry-After。
    """
    model_list = models or [payload.get("model")]
    delay = 4.0
    last_err = None
    for rnd in range(max_rounds):
        retry_after = 0
        for m in model_list:
            payload["model"] = m
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    resp = await client.post(
                        f"{OPENROUTER_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    if resp.status_code in (429, 500, 502, 503):
                        last_err = f"{m}:{resp.status_code}"
                        try:
                            meta = resp.json().get("error", {}).get("metadata", {})
                            retry_after = max(retry_after, int(float(meta.get("retry_after_seconds", 0))))
                        except Exception:
                            pass
                        continue  # 立即换下一个模型
                    resp.raise_for_status()
                    return resp.json()
            except httpx.HTTPStatusError:
                raise
            except Exception as e:
                last_err = f"{m}:{str(e)[:40]}"
                continue
        # 整轮所有模型都失败 → 退避后重试整轮
        wait = max(delay, retry_after)
        print(f"  ⏳ 免费模型全部限流({last_err})，{wait:.0f}s 后重试整轮 ({rnd+1}/{max_rounds})", flush=True)
        await asyncio.sleep(wait)
        delay = min(delay * 2, 40)
    raise RuntimeError(f"OpenRouter 所有模型多轮重试仍失败: {last_err}")


async def _post_uitars_remote(payload: dict) -> dict:
    """
    调用 remote 方式（Kaggle/Colab 等部署的 OpenAI 兼容 endpoint）的 UI-TARS。
    - URL：UITARS_ENDPOINT（命令行 --uitars-endpoint 传入）
    - 鉴权：key 放在 header 的 x-api-key 字段（不是 Authorization Bearer），
      等价于 requests.post(url, headers={"x-api-key": key}, json=data)
    - body 仍为 OpenAI 兼容 chat/completions 格式（vLLM/类似框架默认暴露此接口）
    """
    headers = {"Content-Type": "application/json"}
    if UITARS_KEY:
        headers["x-api-key"] = UITARS_KEY
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(UITARS_ENDPOINT, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


async def call_uitars(image_path: str, task_prompt: str) -> str:
    """
    调用 UI-TARS 模型（仅在选择器兜底时使用），返回含 Thought/Action 的响应。
    根据 UITARS_PROVIDER 分三种提供方式：
      - openrouter：复用 _post_openrouter，走 OpenRouter（OpenRouter key）
      - remote    ：走 _post_uitars_remote，POST 到 UITARS_ENDPOINT，x-api-key 鉴权
      - local     ：本地推理（用户搭建中），暂未实现 → 抛 NotImplementedError，
                    上层 _click_smart 已 try/except 包裹，会优雅跳过 UI-TARS 兜底不崩溃
    三种方式的 messages/payload 结构一致（OpenAI 兼容），响应均按
    result["choices"][0]["message"]["content"] 解析。
    """
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

    if UITARS_PROVIDER == "remote":
        result = await _post_uitars_remote(payload)
    elif UITARS_PROVIDER == "local":
        # 本地 UI-TARS 推理方式尚未实现，待用户搭建完成后补充 endpoint（UITARS_LOCAL_URL）
        raise NotImplementedError(
            f"本地 UI-TARS 推理方式尚未实现，待用户搭建完成后补充 endpoint（预留地址: {UITARS_LOCAL_URL}）"
        )
    else:  # openrouter（默认）
        result = await _post_openrouter(payload)
    return result["choices"][0]["message"]["content"]


async def verify_job_is_it_remote(job_title: str, job_desc: str, salary: str = "", image_path: str = None) -> tuple[bool, str]:
    """
    判断职位是否为「IT 软件/技术开发类」且「支持远程/WFH」。
    - 默认用免费纯文本模型 VERIFY_MODEL（以标题+正文为依据，中文足够）。
    - 若传入 image_path（说明正文抓取失败、需看图），改用免费多模态模型
      VERIFY_MODEL_MULTIMODAL，把截图一起发出去兜底判断。
    采用严格提示词：只有核心岗位是软件/IT技术开发，且支持远程，才判定投递。
    返回 (should_apply, reason)
    """
    prompt = f"""你是一个严格的招聘职位筛选助手。请判断下面这个职位是否【同时满足】两个条件，只有都满足才建议投递。

【条件1：必须是 IT 软件【开发】类岗位（只投开发岗，不投运维岗）】
✅ 算作（核心工作是写代码/做软件开发）：
   后端/前端/全栈/移动端/客户端开发、软件工程师、程序员、
   数据工程师、算法工程师、机器学习工程师、
   AI 工程师（做模型/系统开发的）、嵌入式开发、测试开发(SDET)
❌ 必须排除（即使提到 AI/互联网/远程也要排除）：
   - 【运维类】运维工程师 / DevOps / SRE / 系统运维 / 网络运维 / 系统管理员（明确不投运维）
   - 【特定技术栈】主要技术栈为 PHP / Django / C#/.NET 的开发岗（这几类不投）
     注意：只排除 Django 这个具体框架；其他 Python Web（如 Flask、FastAPI）以及 Python 后端/数据/算法岗仍然要投
   - 数据标注/AI标注师、内容运营/用户运营/活动运营、产品经理、
     销售/市场/BD、猎头/HR/招聘、文案/写作/编辑/翻译、客服、
     平面/视觉/漫画设计、教师/培训、医学/医疗相关、
     金融分析师、财务、行政、兼职文稿、需要医学/法律/金融等非IT专业背景的岗位

【条件2：必须支持远程办公 / WFH / 居家办公】
   职位标题或描述中明确提到"远程""可远程""居家办公""WFH""在家办公"等。

职位标题：{job_title}

职位描述正文：
{job_desc[:1500]}

请严格按以下格式回答（一定要有"结论"行）：
是否软件开发岗：是/否（说明依据，如具体开发职责/技术栈）
是否运维/DevOps/SRE岗：是/否（若是→必须不投递）
主要技术栈是否为PHP/Django/C#/.NET：是/否（只看是否Django框架，不要把Flask/FastAPI等其他PythonWeb算进来；若是→必须不投递）
是否支持远程：是/否
结论：投递 / 不投递
理由：（一句话，说明关键原因）"""

    content = [{"type": "text", "text": prompt}]
    models = VERIFY_MODELS_TEXT  # 默认纯文本免费模型 fallback 链
    if image_path:
        # 正文抓取失败 → 用免费多模态模型 + 截图兜底
        models = VERIFY_MODELS_MULTIMODAL
        img_b64 = image_to_base64(image_path)
        content.insert(0, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})

    payload = {
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 400,
    }
    result = await _post_openrouter(payload, models=models)
    answer = result["choices"][0]["message"]["content"]

    # 稳健解析：只看"结论"那一行，去掉 markdown 加粗(*)、空格再判断，
    # 避免 (a) 模型用 **结论**：投递 破坏匹配 (b) 推理正文里出现"不投递"误伤。
    concl_line = ""
    for line in answer.splitlines():
        if "结论" in line:
            concl_line = line
            break
    c = concl_line.replace("*", "").replace(" ", "").replace("：", ":")
    if "结论" in c:
        c = c.split("结论", 1)[1]  # 取"结论"之后部分
    should_apply = ("投递" in c) and ("不投递" not in c)
    return should_apply, answer


# ─── UI-TARS 动作解析与执行 ───────────────────────────────────────────────────

def parse_uitars_action(response: str, screen_width: int, screen_height: int) -> dict | None:
    """
    使用 ui-tars 包解析模型响应，返回第一个动作结构。
    返回结构示例：
      {"action_type": "click", "action_inputs": {"start_box": "[0.39, 0.37, 0.39, 0.37]"}}
    start_box 中的坐标是 0-1 归一化值。
    """
    try:
        from ui_tars.action_parser import parse_action_to_structure_output
        parsed = parse_action_to_structure_output(
            response,
            factor=1000,
            origin_resized_height=screen_height,
            origin_resized_width=screen_width,
            model_type="qwen25vl",
        )
        return parsed[0] if parsed else None
    except Exception as e:
        print(f"  [WARN] 动作解析失败: {e}")
        return None


def _box_to_xy(action_inputs: dict, key: str, width: int, height: int) -> tuple[int, int] | None:
    """将归一化 start_box/end_box 字符串转为页面像素坐标（取中心点）"""
    box_str = action_inputs.get(key)
    if not box_str:
        return None
    try:
        box = json.loads(box_str)
        x = (box[0] + box[2]) / 2 * width
        y = (box[1] + box[3]) / 2 * height
        return int(x), int(y)
    except Exception:
        return None


async def execute_action_on_page(page: Page, action: dict):
    """
    在 Playwright 页面上执行 UI-TARS 解析出的动作（带人类化延迟）
    """
    if not action:
        return

    action_type = action.get("action_type", "")
    inputs = action.get("action_inputs", {})
    vw, vh = page.viewport_size["width"], page.viewport_size["height"]

    if action_type in ("click", "left_single"):
        xy = _box_to_xy(inputs, "start_box", vw, vh)
        if xy:
            await human_mouse_move_and_click(page, *xy)

    elif action_type == "left_double":
        xy = _box_to_xy(inputs, "start_box", vw, vh)
        if xy:
            await page.mouse.dblclick(*xy)
            human_delay(0.3, 0.7)

    elif action_type == "right_single":
        xy = _box_to_xy(inputs, "start_box", vw, vh)
        if xy:
            await page.mouse.click(*xy, button="right")
            human_delay(0.3, 0.7)

    elif action_type == "drag":
        start = _box_to_xy(inputs, "start_box", vw, vh)
        end = _box_to_xy(inputs, "end_box", vw, vh)
        if start and end:
            await page.mouse.move(*start)
            await page.mouse.down()
            await page.mouse.move(*end, steps=random.randint(10, 20))
            await page.mouse.up()
            human_delay(0.3, 0.7)

    elif action_type == "type" and inputs.get("content"):
        text = inputs["content"]
        submit = text.endswith("\n")
        await page.keyboard.type(text.rstrip("\n"), delay=random.randint(50, 150))
        if submit:
            human_delay(0.3, 0.6)
            await page.keyboard.press("Enter")
        human_delay(0.3, 0.8)

    elif action_type == "scroll":
        direction = (inputs.get("direction") or "down").lower()
        delta = random.randint(300, 500)
        if "up" in direction:
            await page.mouse.wheel(0, -delta)
        else:
            await page.mouse.wheel(0, delta)
        human_delay(0.5, 1.2)

    elif action_type == "hotkey" and inputs.get("key"):
        # ui-tars 用空格分隔键，如 "ctrl c" → Playwright 格式 "Control+c"
        key_map = {"ctrl": "Control", "shift": "Shift", "alt": "Alt", "enter": "Enter",
                   "esc": "Escape", "tab": "Tab", "space": "Space", "backspace": "Backspace"}
        keys = [key_map.get(k.lower(), k) for k in inputs["key"].split()]
        await page.keyboard.press("+".join(keys))
        human_delay(0.2, 0.5)

    elif action_type in ("finished", "wait"):
        human_delay(0.5, 1.0)


async def human_mouse_move_and_click(page: Page, x: int, y: int):
    """
    模拟人类鼠标移动（分段移动+随机偏移）后点击
    """
    current_pos = await page.evaluate("() => ({x: window.outerWidth/2, y: window.outerHeight/2})")
    start_x = current_pos.get("x", x - 100)
    start_y = current_pos.get("y", y - 100)

    # 分3-5步移动，每步加随机偏移
    steps = random.randint(3, 5)
    for i in range(steps):
        progress = (i + 1) / steps
        mid_x = start_x + (x - start_x) * progress + random.randint(-5, 5)
        mid_y = start_y + (y - start_y) * progress + random.randint(-5, 5)
        await page.mouse.move(mid_x, mid_y)
        await asyncio.sleep(random.uniform(0.05, 0.15))

    await page.mouse.move(x, y)
    await asyncio.sleep(random.uniform(0.1, 0.3))
    await page.mouse.click(x, y)
    human_delay(0.3, 0.8)


# ─── 主要自动化逻辑 ───────────────────────────────────────────────────────────

class BossZhipinAutomator:
    def __init__(self, verify_fn=None):
        """
        verify_fn: 职位判断函数，签名为 async (title, desc, salary="") -> (bool, str)
                   默认为 None，此时 apply_to_job 使用模块级 verify_job_is_it_remote。
                   通过注入不同的 verify_fn，同一个 Automator 可服务：
                     - 远程岗任务（verify_job_is_it_remote）
                     - 大模型深圳任务（verify_damoxing_sz）
                     - 职位 tab 混合任务（verify_mixed）
        """
        self.verify_fn = verify_fn  # 可注入的职位判断函数
        self.applied_data = load_applied_jobs()
        self.status_data = zhipin_status.load_status()  # 对方回应状态（apply前过滤）
        self.page: Page = None
        self.browser: Browser = None
        self.context = None
        self.viewport_width = 1280
        self.viewport_height = 800

    async def start_browser(self, playwright):
        """
        启动浏览器（有头模式）。
        使用本机真实 Chrome + 持久化用户目录：
        - 真实 Chrome 指纹比 Playwright 自带 Chromium（Chrome for Testing）更难被反爬识别
        - 持久化目录保留登录 cookie，重跑无需再扫码
        """
        profile_dir = Path(__file__).parent / "chrome_profile"
        profile_dir.mkdir(exist_ok=True)

        self.context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=False,
            viewport={"width": self.viewport_width, "height": self.viewport_height},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            args=[
                "--disable-blink-features=AutomationControlled",
                f"--window-size={self.viewport_width},{self.viewport_height}",
            ],
            ignore_default_args=["--enable-automation"],
        )
        self.browser = self.context.browser  # persistent context 下可能为 None
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

        # 注入反检测脚本
        await self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

    async def navigate_to_zhipin(self):
        """导航到Boss直聘"""
        print("🌐 正在打开 Boss直聘...")
        await self.page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=30000)
        human_delay(3.0, 5.0)
        title = await self.page.title()
        print(f"  页面标题: {title} | URL: {self.page.url}", flush=True)
        if "验证" in title or "security" in self.page.url.lower():
            print("  ⚠️ 疑似触发安全验证页面，请在浏览器中手动完成验证", flush=True)

    async def _is_logged_in_on_home(self) -> bool:
        """
        在首页判断是否已登录（仅用于首页/非登录页）。
        未登录标志：首页导航栏存在可见的"登录/注册"链接。
        """
        try:
            login_link = await self.page.query_selector("a:has-text('登录/注册')")
            if login_link and await login_link.is_visible():
                return False
            # 进一步确认：存在用户/极客导航区
            return True
        except Exception:
            return False

    async def check_login_and_wait(self) -> bool:
        """
        检测登录状态，未登录则打开登录页（直接显示二维码）并等待用户扫码。

        可靠的登录完成信号：扫码成功后 BOSS直聘 会把页面从 /web/user
        重定向到首页/极客中心。因此轮询条件是"URL 已离开 /web/user"，
        避免在登录页上因二维码刷新/过期导致的误判。
        """
        # 先在首页判断是否已登录（持久化 profile 可能已保存登录态）
        await self.page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=30000)
        human_delay(2.0, 3.0)
        if await self._is_logged_in_on_home():
            print("✅ 已检测到登录状态（chrome_profile 已保存登录），继续执行", flush=True)
            return True

        # 未登录 → 打开登录页（该页默认直接显示二维码）
        print("\n" + "=" * 60)
        print("🔐 检测到未登录！正在打开扫码登录页...")
        try:
            await self.page.goto(
                "https://www.zhipin.com/web/user/?ka=header-login",
                wait_until="domcontentloaded", timeout=30000,
            )
        except Exception:
            pass
        human_delay(2.0, 3.0)
        await screenshot_page(self.page, "login_qr.png")

        print("👉 浏览器已显示二维码，请用 BOSS直聘 APP 扫码登录")
        print("   登录信息会保存到 automation/chrome_profile，下次重跑无需再扫码")
        print("   脚本每 5 秒检测一次，最长等待 10 分钟。二维码过期会自动刷新，请耐心扫码")
        print("=" * 60 + "\n", flush=True)

        for i in range(120):
            await asyncio.sleep(5)
            try:
                url = self.page.url
                # 主信号：已离开登录页
                if "/web/user" not in url:
                    # 再确认首页无"登录/注册"
                    human_delay(1.0, 2.0)
                    if await self._is_logged_in_on_home():
                        print(f"✅ 检测到登录成功（已跳转到 {url[:60]}），继续执行", flush=True)
                        return True
            except Exception:
                pass
            if i % 6 == 5:
                print(f"  ⏳ 仍在等待扫码登录... ({(i + 1) * 5}秒)", flush=True)

        print("⚠️ 等待登录超时（10分钟）", flush=True)
        return False

    def get_hot_cities(self) -> list[str]:
        """返回要遍历的热门城市列表"""
        return DEFAULT_HOT_CITIES

    async def _click_smart(self, page: Page, selectors: list[str], uitars_instruction: str,
                           shot_name: str, require_text: str = None) -> bool:
        """
        混合点击：选择器优先，UI-TARS 兜底。
        1. 依次尝试 Playwright 选择器（精确、可靠），命中可见元素则人类化点击
        2. 全部失败时（页面反爬/动态结构），截图交给 UI-TARS 做 GUI grounding
           定位按钮坐标并点击（这是 UI-TARS 的强项，通用多模态模型坐标不准）
        返回是否点击成功。
        require_text: 若指定，则要求元素文本精确等于它（用于在多个同类元素中选目标）
        """
        # 阶段1：选择器
        for sel in selectors:
            try:
                els = await page.query_selector_all(sel)
                for el in els:
                    if not await el.is_visible():
                        continue
                    if require_text is not None:
                        t = (await el.text_content() or "").strip()
                        if t != require_text:
                            continue
                    bb = await el.bounding_box()
                    if bb:
                        await human_mouse_move_and_click(
                            page,
                            int(bb["x"] + bb["width"] / 2),
                            int(bb["y"] + bb["height"] / 2),
                        )
                    else:
                        await el.click()
                    return True
            except Exception:
                continue

        # 阶段2：UI-TARS 视觉兜底
        print(f"  🔎 选择器未命中，改用 UI-TARS 视觉定位: {shot_name}")
        try:
            shot = await screenshot_page(page, shot_name)
            resp = await call_uitars(shot, uitars_instruction)
            action = parse_uitars_action(resp, page.viewport_size["width"], page.viewport_size["height"])
            if action and action.get("action_type") in ("click", "left_single"):
                await execute_action_on_page(page, action)
                return True
            print(f"  [WARN] UI-TARS 未返回有效点击动作: {resp[:120]}")
        except Exception as e:
            print(f"  [WARN] UI-TARS 兜底失败: {e}")
        return False

    async def _read_current_city(self) -> str:
        """读取当前页面的城市标签（.city-label），用于确认/记录实际搜索城市"""
        try:
            el = await self.page.query_selector(".city-label, [class*='city-label']")
            if el:
                return (await el.text_content() or "").strip()
        except Exception:
            pass
        return ""

    async def switch_city_via_map(self, city: str) -> bool:
        """
        通过"地图→请选择城市→热门城市"面板选择城市（忠于用户要求的地图选城市方式）。
        步骤：打开地图版职位页 → 点城市选择器 → 在热门城市面板点目标城市。
        使用 _click_smart（选择器优先 + UI-TARS 兜底）以应对反爬时按钮定位。
        """
        from urllib.parse import quote
        code = CITY_CODES[city]
        q = quote(SEARCH_KEYWORD)
        map_url = f"https://www.zhipin.com/web/geek/map/jobs?query={q}&cityCode={code}"
        print(f"  🗺️ 打开地图选城市页 ({city})")
        try:
            await self.page.goto(map_url, wait_until="domcontentloaded", timeout=30000)
            human_delay(3.0, 5.0)
            # 等待地图页城市选择器渲染（地图 JS 初始化较慢）
            try:
                await self.page.wait_for_selector(
                    "[class*='city-sel'], .city-label", timeout=12000
                )
            except Exception:
                pass
            human_delay(1.0, 2.0)
        except Exception as e:
            print(f"  [WARN] 打开地图页失败: {e}")
            return False

        # 点城市选择器打开面板
        ok = await self._click_smart(
            self.page,
            ["[class*='city-sel']", ".city-label", "[class*='city-label']"],
            "找到页面上显示当前城市名或'请选择城市'的按钮，点击它打开城市选择面板。",
            "map_city_selector.png",
        )
        if not ok:
            print("  [WARN] 未能打开城市选择面板")
            return False
        human_delay(1.5, 2.5)

        # 在热门城市面板点目标城市
        ok = await self._click_smart(
            self.page,
            ["*"],  # 选择器阶段用文本匹配热门城市链接
            f"城市选择面板已打开，'热门城市'标签下找到'{city}'这个城市并点击它。",
            f"map_hotcity_{city}.png",
            require_text=city,
        )
        if not ok:
            print(f"  [WARN] 未能在面板点选城市: {city}")
            return False
        human_delay(2.0, 3.5)

        confirmed = await self._read_current_city()
        print(f"  ✅ 地图面板已选择城市，页面城市标签确认为: [{confirmed}]")
        return True

    async def goto_list(self, city: str, page_num: int = 1) -> bool:
        """
        导航到列表版搜索结果页（可投递，有立即沟通+详情面板）。
        登录后首次导航可能触发安全校验导致 0 卡，故 0 卡时重试一次。
        导航后读取 .city-label 确认实际城市与预期一致。
        """
        from urllib.parse import quote
        code = CITY_CODES[city]
        q = quote(SEARCH_KEYWORD)
        url = f"https://www.zhipin.com/web/geek/jobs?query={q}&city={code}&page={page_num}"
        print(f"  🔍 列表搜索: {city} 第{page_num}页 (city={code})")

        for attempt in range(2):
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                human_delay(3.0, 5.0)
                try:
                    await self.page.wait_for_selector(".job-card-box", timeout=10000)
                except Exception:
                    pass
                n = len(await self.page.query_selector_all(".job-card-box"))
                if n > 0:
                    confirmed = await self._read_current_city()
                    if confirmed and city not in confirmed and confirmed not in city:
                        print(f"  ⚠️ 城市标签[{confirmed}]与预期[{city}]不一致，仍按预期[{city}]记录")
                    print(f"  ✅ 城市确认: [{confirmed or city}] | 本页 {n} 个职位")
                    return True
                if attempt == 0:
                    print("  ↻ 0 个职位（疑似首次导航安全校验），重试一次...")
                    human_delay(3.0, 5.0)
            except Exception as e:
                print(f"  [WARN] 列表导航失败(尝试{attempt+1}): {e}")
        return False

    async def get_job_listings(self) -> list[dict]:
        """提取当前搜索结果页的职位列表（选择器经实测：.job-card-box）"""
        jobs = []
        try:
            job_cards = await self.page.query_selector_all(".job-card-box")

            for card in job_cards:
                try:
                    job = {}
                    # 实测卡片结构：.job-name(标题) .boss-name(公司) .job-salary(薪资)
                    # .company-location(地点) .tag-list(标签)
                    title_el = await card.query_selector(".job-name")
                    if title_el:
                        job["title"] = (await title_el.text_content() or "").strip()

                    company_el = await card.query_selector(".boss-name, .company-name")
                    if company_el:
                        job["company"] = (await company_el.text_content() or "").strip()

                    salary_el = await card.query_selector(".job-salary")
                    if salary_el:
                        job["salary"] = (await salary_el.text_content() or "").strip()

                    loc_el = await card.query_selector(".company-location")
                    if loc_el:
                        job["location"] = (await loc_el.text_content() or "").strip()

                    tags_el = await card.query_selector_all(".tag-list li")
                    job["tags"] = []
                    for tag in tags_el:
                        t = (await tag.text_content() or "").strip()
                        if t:
                            job["tags"].append(t)

                    if job.get("title") and job.get("company"):
                        job["element"] = card
                        jobs.append(job)
                except Exception:
                    continue
        except Exception as e:
            print(f"  [WARN] 获取职位列表失败: {e}")

        return jobs

    async def _extract_job_description(self) -> str:
        """
        提取右侧详情面板的职位描述正文，并清洗反爬注入的 CSS 噪音。
        """
        desc = ""
        try:
            el = await self.page.query_selector(".job-detail-box, .job-detail")
            if el:
                desc = await el.text_content() or ""
        except Exception:
            pass
        # 去掉反爬注入的 CSS 规则（形如 .xxx{display:none!important;}）
        desc = re.sub(r"\.[a-zA-Z0-9_-]+\{[^}]*\}", "", desc)
        # 取"职位描述"之后的正文（若有）
        if "职位描述" in desc:
            desc = desc.split("职位描述", 1)[1]
        desc = re.sub(r"\s+", " ", desc).strip()
        return desc

    async def _close_greet_dialog(self) -> bool:
        """
        关闭"已向BOSS发送消息"弹窗（greet-boss-dialog）。
        该弹窗的遮罩 .greet-boss-layer 会拦截后续点击，必须先关掉。
        点 X（.icon-close）关闭；失败则按 Escape。
        """
        try:
            x = await self.page.query_selector(".greet-boss-dialog .icon-close, .greet-boss-dialog .close")
            if x and await x.is_visible():
                await x.click()
                human_delay(0.8, 1.5)
                return True
        except Exception:
            pass
        # 兜底：按 Escape
        try:
            await self.page.keyboard.press("Escape")
            human_delay(0.5, 1.0)
        except Exception:
            pass
        return False

    async def apply_to_job(self, job: dict, city: str) -> str:
        """
        对单个职位投递（Boss直聘聊天式）。返回状态码用于统计：
          "applied"   —— 新投递成功
          "dup"       —— 已投递过（去重跳过）
          "reject"    —— 验证不通过（非IT软件/非远程/被排除）
          "contacted" —— 此前已沟通过（记录，不重复发）
          "fail"      —— 投递过程出错
        流程：点卡→抓标题+正文→严格判断→通过则点立即沟通(发招呼=投递)→关弹窗→记录
        """
        company = job.get("company", "")
        title = job.get("title", "")

        if is_already_applied(self.applied_data, company, title):
            print(f"  ⏭️  [跳过-已投递] {company} | {title}")
            return "dup"

        # 对方回应状态过滤：已读不回/拒绝/索要简历/已发简历 → 跳过，不浪费打招呼次数
        # （即使 zhipin 2 个月限制解除仍跳过；状态由 zhipin_messages.py 扫描写入）
        if zhipin_status.is_blocked(self.status_data, company, title):
            st = zhipin_status.get_status(self.status_data, company, title)
            print(f"  ⏭️  [跳过-对方已回应:{st}] {company} | {title}")
            return "blocked"

        print(f"\n  🔎 检查职位: {company} | {title}")
        print(f"     薪资: {job.get('salary', 'N/A')} | 地点: {job.get('location','')} | 标签: {', '.join(job.get('tags', []))}")

        try:
            # 点职位卡 → 详情面板（检查阶段，快速延迟）
            card = job["element"]
            await card.scroll_into_view_if_needed()
            human_delay(0.4, 0.9)
            await card.click()
            human_delay(CARD_DELAY_MIN, CARD_DELAY_MAX)

            # 抓取职位描述正文
            desc = await self._extract_job_description()
            safe = re.sub(r"[^\w一-龥]", "_", f"{company}_{title}")[:60]

            # 正文太短（疑似反爬/懒加载）→ 滚动详情面板再抓一次
            if len(desc) < MIN_DESC_LEN:
                try:
                    await self.page.mouse.wheel(0, 600)
                    human_delay(1.0, 2.0)
                    await self.page.mouse.wheel(0, -300)
                    human_delay(0.8, 1.5)
                except Exception:
                    pass
                desc2 = await self._extract_job_description()
                if len(desc2) > len(desc):
                    desc = desc2

            # 选择职位判断函数：优先用注入的 verify_fn，未注入则用默认的远程判断
            _verify = self.verify_fn or verify_job_is_it_remote
            salary = job.get("salary", "")

            # 判断：正文够长 → 纯文本免费模型；正文仍抓不到 → 截图+免费多模态兜底
            # 注意：verify_job_is_it_remote 支持可选的 image_path 参数（多模态兜底）；
            # 自定义 verify_fn 签名为 (title, desc, salary="")，不接受 image_path，
            # 所以多模态截图兜底仅对默认远程判断函数生效。
            if len(desc) >= MIN_DESC_LEN:
                should_apply, reason = await _verify(title, desc, salary)
                model_used = "纯文本"
            else:
                if _verify is verify_job_is_it_remote:
                    # 默认远程判断函数支持截图兜底
                    shot_path = await screenshot_page(self.page, f"job_{safe}.png")
                    print(f"  ⚠️ 正文抓取不足({len(desc)}字)，降级用免费多模态+截图判断")
                    should_apply, reason = await verify_job_is_it_remote(title, desc, shot_path)
                    model_used = "多模态"
                else:
                    # 自定义 verify_fn：正文不足时仍调用，但不传截图
                    print(f"  ⚠️ 正文抓取不足({len(desc)}字)，使用自定义判断函数（无截图兜底）")
                    should_apply, reason = await _verify(title, desc, salary)
                    model_used = "纯文本(正文不足)"

            verdict = "✅ 投递" if should_apply else "❌ 跳过"
            print(f"  🤖 判断[{verdict}]({model_used}): {reason[:160].replace(chr(10), ' ')}")

            if not should_apply:
                return "reject"

            # 检查按钮：若"继续沟通"说明之前已发过消息 → 记录并跳过，不重复发
            chat_btn = await self.page.query_selector(
                "a:has-text('立即沟通'), .op-btn-chat, a:has-text('继续沟通')"
            )
            if chat_btn:
                btn_text = (await chat_btn.text_content() or "").strip()
                if "继续沟通" in btn_text:
                    print(f"  ℹ️  [跳过-此前已沟通] {company} | {title}（记录，不重复发）")
                    record_application(self.applied_data, company, title, city)
                    return "contacted"

            # 点"立即沟通"（选择器优先，UI-TARS 视觉兜底）→ 自动发打招呼语 = 投递
            clicked = await self._click_smart(
                self.page,
                ["a:has-text('立即沟通')", ".op-btn-chat"],
                "找到右侧职位详情区的'立即沟通'按钮（绿色按钮），点击它开始沟通。",
                f"chat_btn_{safe}.png",
            )
            if not clicked:
                print("  ⚠️  [跳过-未找到立即沟通按钮]")
                return "fail"
            human_delay(APPLY_DELAY_MIN, APPLY_DELAY_MAX)  # 投递动作保持稳健延迟

            # 关闭"已向BOSS发送消息"弹窗（点X），避免遮罩挡住下一个职位的点击
            await screenshot_page(self.page, "greet_dialog.png")
            await self._close_greet_dialog()

            # 记录投递（打招呼语已发送 = 完成投递）
            print(f"  ✅ [投递成功] {company} | {title}")
            record_application(self.applied_data, company, title, city)
            return "applied"

        except Exception as e:
            print(f"  [ERROR] 投递失败: {e}")
            # 出错也尝试关掉可能存在的遮罩，避免影响后续
            await self._close_greet_dialog()
            return "fail"

    async def process_city(self, city: str):
        """
        处理单个城市的全部远程职位：
        1. 通过"地图→热门城市"面板选择城市（忠于用户要求）
        2. 切到列表页逐页投递（地图页不可投递）
        3. 全部完成后标记城市已完成（城市级去重）
        """
        print(f"\n{'='*60}")
        print(f"🏙️ 开始处理城市: {city}")
        print(f"{'='*60}")

        # 城市级去重：已完成的城市跳过
        if is_city_completed(self.applied_data, city):
            print(f"  ⏭️ 城市 [{city}] 之前已处理完成，跳过")
            return {"city": city, "checked": 0, "applied": 0, "reject": 0,
                    "dup": 0, "contacted": 0, "fail": 0, "blocked": 0, "skipped": True}

        # 本城市统计
        stat = {"city": city, "checked": 0, "applied": 0, "reject": 0,
                "dup": 0, "contacted": 0, "fail": 0, "blocked": 0, "skipped": False}

        # 列表页逐页投递（直接用城市码导航列表页，并读 .city-label 确认城市；
        # 地图选城市的 switch_city_via_map 已保留但不在主流程调用——列表页
        # 已能可靠确认城市，无需额外折腾地图页）
        page_num = 1
        any_page_ok = False
        while page_num <= 5:  # 每个城市最多5页
            print(f"\n  📄 {city} 第 {page_num} 页")
            if not await self.goto_list(city, page_num):
                if page_num == 1:
                    print(f"  ❌ 第1页无职位，跳过城市: {city}")
                else:
                    print(f"  📄 已到最后一页")
                break

            any_page_ok = True
            await screenshot_page(self.page, f"results_{city}_p{page_num}.png")

            jobs = await self.get_job_listings()
            if not jobs:
                print(f"  ⚠️ 本页无职位，停止翻页")
                break

            print(f"  📋 本页找到 {len(jobs)} 个职位，逐个检查...")
            for job in jobs:
                status = await self.apply_to_job(job, city)
                stat["checked"] += 1
                if status in stat:
                    stat[status] += 1
                # 实时累计进度提示
                skipped = stat['reject'] + stat['dup'] + stat['contacted'] + stat['blocked']
                print(f"     ▸ [{city}] 进度：检查 {stat['checked']} | "
                      f"投递 {stat['applied']} | 跳过 {skipped} | 失败 {stat['fail']}")
                human_delay(DELAY_MIN, DELAY_MAX)

            page_num += 1

        # 步骤3：标记城市完成（城市级去重）
        if any_page_ok:
            mark_city_completed(self.applied_data, city)

        # 城市阶段总结
        skipped_total = stat["reject"] + stat["dup"] + stat["contacted"] + stat["blocked"]
        print(f"\n  {'─'*54}")
        print(f"  🏁 城市 [{city}] 阶段总结：")
        print(f"     共检查 {stat['checked']} 个职位 → ✅ 投递 {stat['applied']} | "
              f"⏭️ 跳过 {skipped_total}（不符合{stat['reject']}/已投{stat['dup']}/已沟通{stat['contacted']}/对方已回应{stat['blocked']}）| "
              f"⚠️ 失败 {stat['fail']}")
        print(f"  {'─'*54}")
        return stat

    async def run(self):
        """主运行入口"""
        if not OPENROUTER_API_KEY:
            raise ValueError(
                "缺少 OPENROUTER_API_KEY！\n"
                "请在 automation/.env 文件中设置：\n"
                "  OPENROUTER_API_KEY=sk-or-v1-xxx\n"
                "或设置环境变量 OPENROUTER_API_KEY"
            )

        print("\n" + "🤖 " * 20)
        print("Boss直聘自动投递脚本 启动")
        print("🤖 " * 20 + "\n")

        async with async_playwright() as playwright:
            await self.start_browser(playwright)

            try:
                # 导航到Boss直聘
                await self.navigate_to_zhipin()

                # 检查登录状态
                logged_in = await self.check_login_and_wait()
                if not logged_in:
                    print("❌ 未能登录，终止运行")
                    return

                # 获取热门城市列表
                cities = self.get_hot_cities()
                print(f"\n📋 将处理以下城市（共{len(cities)}个）:")
                print("  " + ", ".join(cities))

                # 遍历城市，收集每城统计
                city_stats = []
                for i, city in enumerate(cities):
                    print(f"\n[{i+1}/{len(cities)}] ▶▶▶ 切换到城市: {city}")
                    st = await self.process_city(city)
                    if st:
                        city_stats.append(st)

                    # 城市间休息（防止触发反爬）
                    rest_time = random.uniform(5.0, 10.0)
                    print(f"\n  😴 城市间休息 {rest_time:.1f} 秒...")
                    await asyncio.sleep(rest_time)

                # 全部城市总汇总
                print("\n" + "█"*60)
                print("📊 全部城市处理完毕 —— 总汇总")
                print("█"*60)
                tot = {"checked": 0, "applied": 0, "reject": 0, "dup": 0,
                       "contacted": 0, "fail": 0, "blocked": 0}
                print(f"  {'城市':<6}{'检查':>6}{'投递':>6}{'不符合':>7}{'已投':>6}{'已沟通':>7}{'已回应':>7}{'失败':>6}")
                for st in city_stats:
                    if st.get("skipped"):
                        print(f"  {st['city']:<6}{'(本次跳过-之前已完成)':>30}")
                        continue
                    for k in tot:
                        tot[k] += st.get(k, 0)
                    print(f"  {st['city']:<6}{st['checked']:>6}{st['applied']:>6}"
                          f"{st['reject']:>7}{st['dup']:>6}{st['contacted']:>7}{st['blocked']:>7}{st['fail']:>6}")
                print(f"  {'─'*58}")
                print(f"  {'合计':<6}{tot['checked']:>6}{tot['applied']:>6}"
                      f"{tot['reject']:>7}{tot['dup']:>6}{tot['contacted']:>7}{tot['blocked']:>7}{tot['fail']:>6}")
                print(f"\n  本次共检查 {tot['checked']} 个职位 → 投递 {tot['applied']} | "
                      f"跳过 {tot['reject']+tot['dup']+tot['contacted']+tot['blocked']} | 失败 {tot['fail']}")

                # 汇总报告
                print("\n" + "="*60)
                print("✅ 投递完成！")
                print(f"📊 累计投递 {len(self.applied_data['jobs'])} 个职位")
                print(f"🏙️ 已完成城市: {', '.join(self.applied_data.get('completed_cities', [])) or '无'}")
                print(f"📁 记录已保存至: {APPLIED_JOBS_FILE}")
                print("="*60)

                # 显示投递记录
                if self.applied_data["jobs"]:
                    print("\n📋 已投递职位列表：")
                    for j in self.applied_data["jobs"]:
                        print(f"  • {j['company']} | {j['position']} ({j['city']}) [{j['applied_at']}]")

            except KeyboardInterrupt:
                print("\n⚠️ 用户中断，保存当前进度...")
                save_applied_jobs(self.applied_data)

            finally:
                # 程序结束前（无论正常跑完/中断/报错）都把 json 转成 csv
                try:
                    save_applied_jobs(self.applied_data)
                    csv_path = export_applications_csv(self.applied_data)
                    print(f"📑 最终统计CSV已生成: {csv_path}")
                except Exception as e:
                    print(f"[WARN] 导出CSV失败: {e}")
                print("\n🔚 关闭浏览器...")
                try:
                    await self.context.close()
                except Exception:
                    pass


# ─── 入口 ─────────────────────────────────────────────────────────────────────

def _build_arg_parser():
    """
    构建命令行参数解析器。

    OpenRouter key 优先级：命令行 --openrouter-key > 环境变量 OPENROUTER_API_KEY（含 .env）。
    该 key 用于：验证职位的多模态/文本模型（始终走 OpenRouter），
    以及 UI-TARS 选择 openrouter 提供方式时。

    UI-TARS 提供方式（--uitars-provider）三选一：

      openrouter（默认）：UI-TARS 走 OpenRouter
        python zhipin_apply.py --openrouter-key sk-or-v1-xxx
        # 或不传 key，用 .env / 环境变量里的 OPENROUTER_API_KEY

      remote：UI-TARS 走 Kaggle/Colab 部署的 OpenAI 兼容 endpoint（x-api-key 鉴权）
        python zhipin_apply.py \\
            --openrouter-key sk-or-v1-xxx \\
            --uitars-provider remote \\
            --uitars-endpoint https://xxxx.ngrok.io/v1/chat/completions \\
            --uitars-key super-secret-key
        # 验证职位仍用 OpenRouter key；UI-TARS 走 remote endpoint

      local：本地推理（用户搭建中，暂未实现，调用 UI-TARS 时会优雅跳过）
        python zhipin_apply.py \\
            --openrouter-key sk-or-v1-xxx \\
            --uitars-provider local \\
            --uitars-local-url http://127.0.0.1:8000/v1/chat/completions
    """
    import argparse
    parser = argparse.ArgumentParser(
        description="Boss直聘自动投递脚本（支持 UI-TARS 三种提供方式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--openrouter-key", default=None,
        help="OpenRouter API key（优先级高于环境变量 OPENROUTER_API_KEY / .env）。"
             "用于验证职位的文本/多模态模型，以及 openrouter 方式下的 UI-TARS。",
    )
    parser.add_argument(
        "--uitars-provider", choices=["openrouter", "remote", "local"], default="openrouter",
        help="UI-TARS 模型提供方式：openrouter（默认，走 OpenRouter）/ "
             "remote（Kaggle/Colab 部署的 OpenAI 兼容 endpoint，x-api-key 鉴权）/ "
             "local（本地推理，暂未实现）。",
    )
    parser.add_argument(
        "--uitars-endpoint", default=None,
        help="remote 方式下 UI-TARS 的完整 URL（如 https://xxxx.ngrok.io/v1/chat/completions）。"
             "选 remote 时必填。",
    )
    parser.add_argument(
        "--uitars-key", default=None,
        help="remote 方式下 UI-TARS endpoint 的鉴权 key（放在 header 的 x-api-key 字段）。",
    )
    parser.add_argument(
        "--uitars-local-url", default=UITARS_LOCAL_URL,
        help=f"local 方式下本地 UI-TARS 推理服务地址（OpenAI 兼容），当前未实现，仅占位预留。"
             f"默认 {UITARS_LOCAL_URL}。",
    )
    return parser


def main():
    """解析命令行参数，赋值到模块级全局变量后启动自动投递。"""
    global OPENROUTER_API_KEY, UITARS_PROVIDER, UITARS_ENDPOINT, UITARS_KEY, UITARS_LOCAL_URL

    parser = _build_arg_parser()
    args = parser.parse_args()

    # OpenRouter key：命令行 > 环境变量/.env（保留现有回退方式）
    if args.openrouter_key:
        OPENROUTER_API_KEY = args.openrouter_key

    # UI-TARS 提供方式
    UITARS_PROVIDER = args.uitars_provider
    UITARS_LOCAL_URL = args.uitars_local_url
    if args.uitars_key:
        UITARS_KEY = args.uitars_key
    if args.uitars_endpoint:
        UITARS_ENDPOINT = args.uitars_endpoint

    # remote 方式必须提供 endpoint
    if UITARS_PROVIDER == "remote" and not UITARS_ENDPOINT:
        parser.error("--uitars-provider remote 需要同时指定 --uitars-endpoint")

    # local 方式提示尚未实现
    if UITARS_PROVIDER == "local":
        print("⚠️ 本地 UI-TARS 推理方式尚未实现，待用户搭建完成后补充 endpoint。"
              f"（预留地址: {UITARS_LOCAL_URL}）UI-TARS 视觉兜底将被优雅跳过。", flush=True)

    print(f"⚙️ UI-TARS 提供方式: {UITARS_PROVIDER}"
          + (f" | endpoint: {UITARS_ENDPOINT}" if UITARS_PROVIDER == "remote" else ""), flush=True)

    asyncio.run(BossZhipinAutomator().run())


if __name__ == "__main__":
    main()
