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

# ─── 配置 ────────────────────────────────────────────────────────────────────

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

UITARS_MODEL = "bytedance/ui-tars-1.5-7b"
VERIFY_MODEL = "google/gemini-2.5-flash"

APPLIED_JOBS_FILE = Path(__file__).parent / "applied_jobs.json"
SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# 搜索关键词
SEARCH_KEYWORD = "远程"

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
DELAY_MIN = 1.5
DELAY_MAX = 3.5
APPLY_DELAY_MIN = 3.0
APPLY_DELAY_MAX = 6.0

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

async def call_uitars(image_path: str, task_prompt: str) -> str:
    """
    调用 OpenRouter UI-TARS 模型，给定截图和任务描述，返回模型响应（包含 Thought 和 Action）
    """
    from ui_tars.prompt import COMPUTER_USE_DOUBAO

    img_b64 = image_to_base64(image_path)
    prompt_text = COMPUTER_USE_DOUBAO.format(
        instruction=task_prompt, language="Chinese"
    )

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                },
                {
                    "type": "text",
                    "text": prompt_text,
                },
            ],
        },
    ]

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": UITARS_MODEL,
                "messages": messages,
                "max_tokens": 512,
            },
        )
        resp.raise_for_status()
        result = resp.json()
        return result["choices"][0]["message"]["content"]


async def verify_job_is_it_remote(image_path: str, job_title: str, job_desc: str) -> tuple[bool, str]:
    """
    使用 Gemini 多模态模型验证职位是否为 IT 软件类远程/WFH 工作
    返回 (is_valid, reason)
    """
    img_b64 = image_to_base64(image_path)

    prompt = f"""请分析这个招聘职位，判断它是否满足以下所有条件：
1. 属于IT/互联网/软件/技术类工作（包括：软件开发、产品、设计、测试、运维、数据、AI等）
2. 明确支持远程办公（WFH）或全程在家工作

职位标题：{job_title}
职位描述摘要：{job_desc}

请回答：
- 是否IT软件类：是/否
- 是否支持远程/WFH：是/否
- 综合判断：符合/不符合
- 理由：（一句话）

如果截图中有职位信息，也请参考截图内容判断。"""

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                },
                {"type": "text", "text": prompt},
            ],
        }
    ]

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": VERIFY_MODEL,
                "messages": messages,
                "max_tokens": 256,
            },
        )
        resp.raise_for_status()
        result = resp.json()
        answer = result["choices"][0]["message"]["content"]

    is_valid = "综合判断：符合" in answer or ("符合" in answer and "不符合" not in answer)
    return is_valid, answer


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
    def __init__(self):
        self.applied_data = load_applied_jobs()
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
                    title_el = await card.query_selector(".job-name")
                    if title_el:
                        job["title"] = (await title_el.text_content() or "").strip()

                    company_el = await card.query_selector(".company-name, [class*='company-name']")
                    if company_el:
                        job["company"] = (await company_el.text_content() or "").strip()

                    salary_el = await card.query_selector(".job-salary, .salary, [class*='salary']")
                    if salary_el:
                        job["salary"] = (await salary_el.text_content() or "").strip()

                    tags_el = await card.query_selector_all(".tag-list li, .tag-item, [class*='tag']")
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

    async def apply_to_job(self, job: dict, city: str) -> bool:
        """
        对单个职位进行投递（Boss直聘是聊天式投递）：
        1. 点击职位卡 → 右侧详情面板更新（同一页面，非新标签页）
        2. 截图详情面板 → Gemini 验证是否 IT 软件类远程职位
        3. 点击"立即沟通"开启与招聘者的对话
        4. 在对话中发送打招呼语，并通过 UI-TARS 发送"刘先生"中文简历
        5. 记录投递，关闭对话回到列表
        """
        company = job.get("company", "")
        title = job.get("title", "")

        if is_already_applied(self.applied_data, company, title):
            print(f"  ⏭️ 跳过（已投递）: {company} | {title}")
            return False

        print(f"\n  📋 处理职位: {company} | {title}")
        print(f"     薪资: {job.get('salary', 'N/A')} | 标签: {', '.join(job.get('tags', []))}")

        try:
            # 点击职位卡 → 右侧详情面板更新（同页）
            card = job["element"]
            await card.scroll_into_view_if_needed()
            human_delay(0.5, 1.2)
            await card.click()
            human_delay(2.0, 3.5)

            # 获取详情面板的职位描述文本
            desc = ""
            try:
                desc_el = await self.page.query_selector(
                    ".job-detail-box, .job-detail, [class*='job-detail']"
                )
                if desc_el:
                    desc = (await desc_el.text_content() or "")[:600]
            except Exception:
                pass

            # 截图详情面板用于验证
            safe = re.sub(r"[^\w一-龥]", "_", f"{company}_{title}")[:60]
            shot_path = await screenshot_page(self.page, f"job_{safe}.png")

            # Gemini 验证是否 IT 软件类远程
            is_valid, reason = await verify_job_is_it_remote(shot_path, title, desc)
            print(f"  🤖 Gemini验证: {'✅ 符合' if is_valid else '❌ 不符合'} | {reason[:120]}")

            if not is_valid:
                return False

            # 先检查按钮文本：若是"继续沟通"说明之前已沟通过 → 记录并跳过
            chat_btn = await self.page.query_selector(
                "a:has-text('立即沟通'), .op-btn-chat, a:has-text('继续沟通')"
            )
            if chat_btn:
                btn_text = (await chat_btn.text_content() or "").strip()
                if "继续沟通" in btn_text:
                    print("  ℹ️ 该职位此前已沟通过，记录并跳过")
                    record_application(self.applied_data, company, title, city)
                    return False

            # 点击"立即沟通"（选择器优先，UI-TARS 视觉兜底）
            clicked = await self._click_smart(
                self.page,
                ["a:has-text('立即沟通')", ".op-btn-chat"],
                "找到右侧职位详情区的'立即沟通'按钮（绿色按钮），点击它开始沟通。",
                f"chat_btn_{safe}.png",
            )
            if not clicked:
                print("  ⚠️ 未能点击'立即沟通'按钮，跳过")
                return False
            human_delay(APPLY_DELAY_MIN, APPLY_DELAY_MAX)

            # 处理对话框 + 发送简历
            await self._send_greeting_and_resume(company, title)

            # 记录投递
            record_application(self.applied_data, company, title, city)
            return True

        except Exception as e:
            print(f"  [ERROR] 投递失败: {e}")
            return False

    async def _send_greeting_and_resume(self, company: str, title: str):
        """
        点击立即沟通后处理对话窗口：
        - Boss直聘点击立即沟通后通常会跳转到聊天页/弹出聊天框，并自动发送打招呼语
        - 在聊天工具栏找到"发送简历"，弹出简历选择时用 UI-TARS 选"刘先生"中文简历
        """
        human_delay(2.0, 3.5)

        # 可能打开了新标签页（聊天页），切到最新页
        pages = self.context.pages
        chat_page = pages[-1] if pages else self.page
        try:
            await chat_page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        human_delay(1.5, 2.5)

        await screenshot_page(chat_page, "chat_opened.png")

        # 找"发送简历"入口（聊天工具栏按钮或快捷气泡）
        try:
            resume_entry = await chat_page.query_selector(
                "*:has-text('发送简历'), *:has-text('发送附件简历'), [class*='resume']"
            )
        except Exception:
            resume_entry = None

        if resume_entry:
            try:
                await resume_entry.click()
                human_delay(1.5, 2.5)
            except Exception:
                pass

        # 用 UI-TARS 在弹窗中选"刘先生"中文简历并确认发送
        shot1 = await screenshot_page(chat_page, "resume_dialog.png")
        resp1 = await call_uitars(
            shot1,
            "如果出现简历选择弹窗，找到名字以'刘先生'开头的中文版简历并点击选中它；"
            "如果没有弹窗但有'发送简历'按钮，则点击该按钮。",
        )
        act1 = parse_uitars_action(resp1, chat_page.viewport_size["width"], chat_page.viewport_size["height"])
        if act1:
            await execute_action_on_page(chat_page, act1)
            human_delay(1.5, 2.5)

            shot2 = await screenshot_page(chat_page, "resume_confirm.png")
            resp2 = await call_uitars(
                shot2,
                "找到确认发送简历的按钮（如'发送'/'确定'/'确认发送'）并点击，完成简历投递。",
            )
            act2 = parse_uitars_action(resp2, chat_page.viewport_size["width"], chat_page.viewport_size["height"])
            if act2:
                await execute_action_on_page(chat_page, act2)
                human_delay(1.5, 2.5)

        await screenshot_page(chat_page, "after_send_resume.png")

        # 若聊天是新标签页，发送完关闭它回到列表页
        if chat_page is not self.page:
            try:
                await chat_page.close()
                human_delay(1.0, 2.0)
            except Exception:
                pass

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
            return

        # 步骤1：地图面板选城市（忠于用户要求；失败不致命，列表页用城市码兜底）
        await self.switch_city_via_map(city)

        # 步骤2：列表页逐页投递
        page_num = 1
        any_page_ok = False
        while page_num <= 5:  # 每个城市最多5页
            print(f"\n  📄 第 {page_num} 页")
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

            print(f"  找到 {len(jobs)} 个职位")
            for job in jobs:
                await self.apply_to_job(job, city)
                human_delay(DELAY_MIN, DELAY_MAX)

            page_num += 1

        # 步骤3：标记城市完成（城市级去重）
        if any_page_ok:
            mark_city_completed(self.applied_data, city)

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

                # 遍历城市
                for i, city in enumerate(cities):
                    print(f"\n[{i+1}/{len(cities)}] 处理城市: {city}")
                    await self.process_city(city)

                    # 城市间休息（防止触发反爬）
                    rest_time = random.uniform(5.0, 10.0)
                    print(f"\n  😴 城市间休息 {rest_time:.1f} 秒...")
                    await asyncio.sleep(rest_time)

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
                print("\n🔚 关闭浏览器...")
                await self.context.close()


# ─── 入口 ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(BossZhipinAutomator().run())
