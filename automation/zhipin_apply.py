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

# 热门城市 → Boss直聘城市编码（用于直达搜索结果页，比 UI 交互可靠）
# 搜索结果页 URL 格式：
#   https://www.zhipin.com/web/geek/jobs?query=远程&city=<code>
# city=101020100 经实测对应"上海招聘"，编码已验证。
CITY_CODES = {
    "全国": "100010000",
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "成都": "101270100",
    "武汉": "101200100",
    "西安": "101110100",
    "南京": "101190100",
    "苏州": "101190400",
    "天津": "101030100",
    "重庆": "101040100",
    "长沙": "101250100",
    "郑州": "101180100",
    "厦门": "101230200",
    "青岛": "101120200",
    "宁波": "101210400",
    "合肥": "101220100",
    "济南": "101120100",
}
DEFAULT_HOT_CITIES = list(CITY_CODES.keys())

# 人类操作延迟范围（秒）
DELAY_MIN = 1.5
DELAY_MAX = 3.5
APPLY_DELAY_MIN = 3.0
APPLY_DELAY_MAX = 6.0

# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def load_applied_jobs() -> dict:
    """加载已投递职位记录"""
    if APPLIED_JOBS_FILE.exists():
        with open(APPLIED_JOBS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"jobs": [], "last_updated": ""}


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

    async def _is_logged_in(self) -> bool:
        """
        判断当前是否已登录。
        未登录标志：导航栏存在"登录/注册"链接。
        已登录标志：存在用户昵称/头像区，且无"登录/注册"链接。
        """
        try:
            login_link = await self.page.query_selector(
                "a.nav-login, a:has-text('登录/注册'), a:has-text('登录')"
            )
            if login_link and await login_link.is_visible():
                return False
            return True
        except Exception:
            return False

    async def check_login_and_wait(self) -> bool:
        """检测登录状态，未登录则打开登录页并等待用户扫码"""
        await screenshot_page(self.page, "login_check.png")

        if await self._is_logged_in():
            print("✅ 已检测到登录状态（持久化 profile 已保存登录），继续执行", flush=True)
            return True

        # 未登录 → 打开登录页
        print("\n" + "=" * 60)
        print("🔐 检测到未登录！正在打开登录页...")
        try:
            await self.page.goto(
                "https://www.zhipin.com/web/user/?ka=header-login",
                wait_until="domcontentloaded", timeout=30000,
            )
        except Exception:
            pass
        human_delay(2.0, 3.0)
        await screenshot_page(self.page, "login_qr.png")

        print("👉 请在弹出的 Chrome 窗口中用 BOSS直聘 APP 扫描二维码登录")
        print("   登录信息会保存到 automation/chrome_profile，下次无需再扫码")
        print("   脚本每 5 秒自动检测一次登录状态，最长等待 10 分钟...")
        print("=" * 60 + "\n", flush=True)

        for i in range(120):
            await asyncio.sleep(5)
            try:
                if await self._is_logged_in():
                    print("✅ 检测到登录成功，继续执行", flush=True)
                    human_delay(1.0, 2.0)
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

    def _search_url(self, city: str, page_num: int = 1) -> str:
        """构造某城市某页的搜索结果页 URL"""
        from urllib.parse import quote
        code = CITY_CODES.get(city, CITY_CODES["全国"])
        q = quote(SEARCH_KEYWORD)
        return f"https://www.zhipin.com/web/geek/jobs?query={q}&city={code}&page={page_num}"

    async def goto_search(self, city: str, page_num: int = 1) -> bool:
        """直接导航到指定城市+关键字+页码的搜索结果页"""
        url = self._search_url(city, page_num)
        print(f"🔍 导航到搜索结果: {city} 第{page_num}页 (city={CITY_CODES.get(city)})")
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            human_delay(3.0, 5.0)
            # 等待职位卡渲染
            try:
                await self.page.wait_for_selector(".job-card-box", timeout=10000)
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"  [WARN] 导航搜索页失败: {e}")
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

            # 点击"立即沟通"
            chat_btn = await self.page.query_selector(
                "a:has-text('立即沟通'), .op-btn-chat, a:has-text('继续沟通')"
            )
            if not chat_btn:
                print("  ⚠️ 未找到'立即沟通'按钮，跳过")
                return False

            btn_text = (await chat_btn.text_content() or "").strip()
            if "继续沟通" in btn_text:
                # 已经聊过 → 视为已投递，记录并跳过重复打招呼
                print("  ℹ️ 该职位此前已沟通过，记录并跳过")
                record_application(self.applied_data, company, title, city)
                return False

            bb = await chat_btn.bounding_box()
            if bb:
                await human_mouse_move_and_click(
                    self.page,
                    int(bb["x"] + bb["width"] / 2),
                    int(bb["y"] + bb["height"] / 2),
                )
            else:
                await chat_btn.click()
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
        """处理单个城市的全部远程职位（按页直达搜索结果 URL）"""
        print(f"\n{'='*60}")
        print(f"🏙️ 开始处理城市: {city}")
        print(f"{'='*60}")

        page_num = 1
        while page_num <= 5:  # 每个城市最多5页
            print(f"\n  📄 第 {page_num} 页")
            if not await self.goto_search(city, page_num):
                print(f"  ❌ 无法打开搜索页，跳过城市: {city}")
                break

            await screenshot_page(self.page, f"results_{city}_p{page_num}.png")

            jobs = await self.get_job_listings()
            if not jobs:
                print(f"  ⚠️ 未找到职位，停止翻页")
                break

            print(f"  找到 {len(jobs)} 个职位")

            for job in jobs:
                await self.apply_to_job(job, city)
                human_delay(DELAY_MIN, DELAY_MAX)

            page_num += 1

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
                print(f"📊 本次共投递 {len(self.applied_data['jobs'])} 个职位")
                print(f"📁 投递记录已保存至: {APPLIED_JOBS_FILE}")
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
