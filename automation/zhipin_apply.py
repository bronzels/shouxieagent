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
from playwright.async_api import async_playwright, Page, Browser

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

# 热门城市列表（Boss直聘主要热门城市，脚本运行时会从页面动态提取覆盖此列表）
DEFAULT_HOT_CITIES = [
    "全国", "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉",
    "西安", "南京", "苏州", "天津", "重庆", "长沙", "郑州", "厦门",
    "青岛", "宁波", "合肥", "济南",
]

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
    from ui_tars.prompt import COMPUTER_USE

    img_b64 = image_to_base64(image_path)

    messages = [
        {
            "role": "system",
            "content": COMPUTER_USE,
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                },
                {
                    "type": "text",
                    "text": task_prompt,
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
    使用 ui-tars 包解析模型响应，返回动作结构
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
        return parsed
    except Exception as e:
        print(f"  [WARN] 动作解析失败: {e}")
        return None


async def execute_action_on_page(page: Page, action: dict):
    """
    在 Playwright 页面上执行 UI-TARS 解析出的动作（带人类化延迟）
    """
    if not action:
        return

    action_type = action.get("action_type", "")
    coordinates = action.get("coordinate", [])

    if action_type in ("click", "left_click") and coordinates:
        x, y = int(coordinates[0]), int(coordinates[1])
        await human_mouse_move_and_click(page, x, y)

    elif action_type == "double_click" and coordinates:
        x, y = int(coordinates[0]), int(coordinates[1])
        await page.mouse.dblclick(x, y)
        human_delay(0.3, 0.7)

    elif action_type == "right_click" and coordinates:
        x, y = int(coordinates[0]), int(coordinates[1])
        await page.mouse.click(x, y, button="right")
        human_delay(0.3, 0.7)

    elif action_type == "type" and action.get("text"):
        text = action["text"]
        await page.keyboard.type(text, delay=random.randint(50, 150))
        human_delay(0.3, 0.8)

    elif action_type == "scroll" and coordinates:
        x, y = int(coordinates[0]), int(coordinates[1])
        direction = action.get("direction", "down")
        delta = random.randint(300, 500)
        if direction == "down":
            await page.mouse.wheel(0, delta)
        else:
            await page.mouse.wheel(0, -delta)
        human_delay(0.5, 1.2)

    elif action_type == "key" and action.get("key"):
        await page.keyboard.press(action["key"])
        human_delay(0.2, 0.5)


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
        self.viewport_width = 1280
        self.viewport_height = 800

    async def start_browser(self, playwright):
        """启动浏览器（有头模式）"""
        self.browser = await playwright.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                f"--window-size={self.viewport_width},{self.viewport_height}",
            ],
        )
        context = await self.browser.new_context(
            viewport={"width": self.viewport_width, "height": self.viewport_height},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        self.page = await context.new_page()

        # 注入反检测脚本
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = {runtime: {}};
        """)

    async def navigate_to_zhipin(self):
        """导航到Boss直聘"""
        print("🌐 正在打开 Boss直聘...")
        await self.page.goto("https://www.zhipin.com/", wait_until="networkidle", timeout=30000)
        human_delay(2.0, 3.0)

    async def check_login_and_wait(self) -> bool:
        """检测是否需要登录，若需要则暂停等待用户扫码"""
        # 截图检测登录状态
        shot_path = await screenshot_page(self.page, "login_check.png")

        # 判断是否显示登录界面（通过页面内容检测）
        page_content = await self.page.content()
        login_indicators = ["扫码登录", "密码登录", "login", "二维码"]
        need_login = any(ind in page_content for ind in login_indicators)

        # 也检查是否有用户头像（已登录状态）
        try:
            avatar = await self.page.wait_for_selector(".user-nav", timeout=3000)
            if avatar:
                print("✅ 已检测到登录状态，继续执行")
                return True
        except Exception:
            pass

        if need_login:
            print("\n" + "="*60)
            print("🔐 检测到需要登录！")
            print("请在打开的浏览器窗口中扫描二维码完成登录")
            print(f"截图已保存至: {shot_path}")
            print("登录完成后，请按回车键继续...")
            print("="*60 + "\n")
            input("▶ 按回车键继续（确认已登录）: ")
            human_delay(1.0, 2.0)

        return True

    async def get_hot_cities(self) -> list[str]:
        """从Boss直聘获取热门城市列表"""
        print("🏙️ 获取热门城市列表...")

        # 尝试点击城市选择器
        try:
            # Boss直聘城市切换通常在导航栏
            city_selector = await self.page.query_selector(".city-label, .nav-city, [class*='city']")
            if city_selector:
                await city_selector.click()
                human_delay(1.0, 2.0)

                # 截图让UI-TARS识别热门城市
                shot_path = await screenshot_page(self.page, "city_selector.png")
                response = await call_uitars(
                    shot_path,
                    "请列出页面上显示的所有热门城市名称，只返回城市名称，用逗号分隔。"
                )
                print(f"  UI-TARS城市识别结果: {response[:200]}")

                # 提取城市名
                cities = re.findall(r'[一-龥]{2,4}', response)
                if len(cities) > 5:
                    await self.page.keyboard.press("Escape")
                    return cities[:20]
        except Exception as e:
            print(f"  [WARN] 动态获取城市失败: {e}，使用默认列表")

        return DEFAULT_HOT_CITIES

    async def switch_city(self, city: str) -> bool:
        """切换到指定城市"""
        print(f"\n🏙️ 切换城市: {city}")

        try:
            # 方法1：直接点击城市链接
            city_link = await self.page.query_selector(f"a:text('{city}'), [data-city-name='{city}']")
            if city_link:
                await city_link.click()
                human_delay(1.5, 2.5)
                return True

            # 方法2：通过URL切换（Boss直聘城市URL格式）
            city_urls = {
                "全国": "https://www.zhipin.com/",
                "北京": "https://www.zhipin.com/beijing/",
                "上海": "https://www.zhipin.com/shanghai/",
                "广州": "https://www.zhipin.com/guangzhou/",
                "深圳": "https://www.zhipin.com/shenzhen/",
                "杭州": "https://www.zhipin.com/hangzhou/",
                "成都": "https://www.zhipin.com/chengdu/",
                "武汉": "https://www.zhipin.com/wuhan/",
                "西安": "https://www.zhipin.com/xian/",
                "南京": "https://www.zhipin.com/nanjing/",
                "苏州": "https://www.zhipin.com/suzhou/",
                "天津": "https://www.zhipin.com/tianjin/",
                "重庆": "https://www.zhipin.com/chongqing/",
                "长沙": "https://www.zhipin.com/changsha/",
                "郑州": "https://www.zhipin.com/zhengzhou/",
                "厦门": "https://www.zhipin.com/xiamen/",
                "青岛": "https://www.zhipin.com/qingdao/",
                "宁波": "https://www.zhipin.com/ningbo/",
                "合肥": "https://www.zhipin.com/hefei/",
                "济南": "https://www.zhipin.com/jinan/",
            }

            if city in city_urls:
                await self.page.goto(city_urls[city], wait_until="networkidle", timeout=20000)
                human_delay(1.5, 2.5)
                return True

            # 方法3：使用UI-TARS识别城市切换按钮
            shot_path = await screenshot_page(self.page, f"before_city_{city}.png")
            response = await call_uitars(
                shot_path,
                f"找到城市切换或地区选择的按钮/链接，点击它以切换到'{city}'城市。"
            )
            action = parse_uitars_action(response, self.viewport_width, self.viewport_height)
            if action:
                await execute_action_on_page(self.page, action)
                human_delay(1.0, 2.0)
                return True

        except Exception as e:
            print(f"  [WARN] 切换城市'{city}'失败: {e}")

        return False

    async def search_remote_jobs(self) -> bool:
        """搜索'远程'关键字"""
        print(f"🔍 搜索关键字: {SEARCH_KEYWORD}")

        try:
            # 查找搜索框
            search_box = await self.page.query_selector(
                "input[placeholder*='搜索'], input[name='query'], .search-input input, #search-input"
            )
            if search_box:
                await search_box.triple_click()
                human_delay(0.3, 0.6)
                await search_box.type(SEARCH_KEYWORD, delay=random.randint(80, 150))
                human_delay(0.5, 1.0)
                await self.page.keyboard.press("Enter")
                await self.page.wait_for_load_state("networkidle", timeout=15000)
                human_delay(1.5, 2.5)
                return True

            # 备用：使用UI-TARS找搜索框
            shot_path = await screenshot_page(self.page, "search_page.png")
            response = await call_uitars(
                shot_path,
                f"找到搜索输入框，清空内容后输入'{SEARCH_KEYWORD}'，然后按回车键或点击搜索按钮。"
            )
            action = parse_uitars_action(response, self.viewport_width, self.viewport_height)
            if action:
                await execute_action_on_page(self.page, action)
                await self.page.wait_for_load_state("networkidle", timeout=15000)
                human_delay(1.5, 2.5)
                return True

        except Exception as e:
            print(f"  [WARN] 搜索失败: {e}")

        return False

    async def get_job_listings(self) -> list[dict]:
        """提取当前页面的职位列表"""
        jobs = []
        try:
            # Boss直聘职位卡片选择器
            job_cards = await self.page.query_selector_all(
                ".job-card-wrapper, .job-list-item, [class*='job-card']"
            )

            for card in job_cards[:10]:  # 每页最多处理10个
                try:
                    job = {}

                    # 提取职位名称
                    title_el = await card.query_selector(".job-name, .position-name, [class*='job-name']")
                    if title_el:
                        job["title"] = (await title_el.text_content() or "").strip()

                    # 提取公司名称
                    company_el = await card.query_selector(".company-name, [class*='company-name']")
                    if company_el:
                        job["company"] = (await company_el.text_content() or "").strip()

                    # 提取薪资
                    salary_el = await card.query_selector(".salary, [class*='salary']")
                    if salary_el:
                        job["salary"] = (await salary_el.text_content() or "").strip()

                    # 提取职位描述标签
                    tags_el = await card.query_selector_all(".tag-item, [class*='tag']")
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
        对单个职位进行投递
        1. 点击职位卡片
        2. 在新页面/弹窗中验证是否IT远程职位
        3. 找到"立即沟通"/"投递简历"按钮并点击
        4. 选择中文简历（刘先生版本）
        5. 确认投递
        """
        company = job.get("company", "")
        title = job.get("title", "")

        # 检查是否已投递
        if is_already_applied(self.applied_data, company, title):
            print(f"  ⏭️ 跳过（已投递）: {company} | {title}")
            return False

        print(f"\n  📋 处理职位: {company} | {title}")
        print(f"     薪资: {job.get('salary', 'N/A')} | 标签: {', '.join(job.get('tags', []))}")

        try:
            # 点击职位卡片（在新标签页打开）
            card = job["element"]
            job_link = await card.query_selector("a")

            if job_link:
                # 用Ctrl+Click在新标签页打开
                context = self.page.context
                async with context.expect_page() as new_page_info:
                    await job_link.click(modifiers=["Control"])
                job_page = await new_page_info.value
                await job_page.wait_for_load_state("networkidle", timeout=15000)
            else:
                await card.click()
                await self.page.wait_for_load_state("networkidle", timeout=10000)
                job_page = self.page

            human_delay(2.0, 3.0)

            # 截图用于验证
            shot_path = await screenshot_page(job_page, f"job_{company}_{title}.png".replace("/", "_")[:80])

            # 获取职位详细描述
            desc = ""
            try:
                desc_el = await job_page.query_selector(".job-detail-section, .job-sec-text, [class*='job-detail']")
                if desc_el:
                    desc = (await desc_el.text_content() or "")[:500]
            except Exception:
                pass

            # 使用Gemini验证职位是否为IT远程
            is_valid, reason = await verify_job_is_it_remote(shot_path, title, desc)
            print(f"  🤖 Gemini验证: {'✅ 符合' if is_valid else '❌ 不符合'} | {reason[:100]}")

            if not is_valid:
                if job_page != self.page:
                    await job_page.close()
                return False

            # 寻找并点击"立即沟通"或"投递简历"按钮
            apply_btn = await job_page.query_selector(
                "a:text('立即沟通'), button:text('立即沟通'), "
                "a:text('投递简历'), button:text('投递简历'), "
                ".btn-startchat, [class*='apply-btn']"
            )

            if not apply_btn:
                # 用UI-TARS找投递按钮
                shot_path2 = await screenshot_page(job_page, f"apply_btn_{title}.png".replace("/", "_")[:80])
                response = await call_uitars(
                    shot_path2,
                    "找到'立即沟通'或'投递简历'或'发送简历'按钮，点击它。"
                )
                action = parse_uitars_action(response, self.viewport_width, self.viewport_height)
                if action:
                    await execute_action_on_page(job_page, action)
                    human_delay(APPLY_DELAY_MIN, APPLY_DELAY_MAX)
            else:
                bb = await apply_btn.bounding_box()
                if bb:
                    cx = int(bb["x"] + bb["width"] / 2)
                    cy = int(bb["y"] + bb["height"] / 2)
                    await human_mouse_move_and_click(job_page, cx, cy)
                human_delay(APPLY_DELAY_MIN, APPLY_DELAY_MAX)

            # 处理可能出现的简历选择弹窗
            await self._handle_resume_selection(job_page)

            # 记录投递
            record_application(self.applied_data, company, title, city)

            if job_page != self.page:
                await asyncio.sleep(1.0)
                await job_page.close()

            return True

        except Exception as e:
            print(f"  [ERROR] 投递失败: {e}")
            try:
                if job_page != self.page:
                    await job_page.close()
            except Exception:
                pass
            return False

    async def _handle_resume_selection(self, page: Page):
        """处理简历选择弹窗，选择中文版简历（刘先生）"""
        human_delay(1.0, 2.0)

        try:
            # 检查是否有简历选择弹窗
            resume_modal = await page.query_selector(
                ".resume-modal, [class*='resume-select'], [class*='cv-select']"
            )
            if not resume_modal:
                return

            # 截图用UI-TARS识别中文简历（刘先生开头）
            shot_path = await screenshot_page(page, "resume_select.png")
            response = await call_uitars(
                shot_path,
                "页面显示了简历选择弹窗，请找到名字以'刘先生'开头的中文版简历，点击选择它，然后点击确认/提交/发送按钮。"
            )
            action = parse_uitars_action(response, self.viewport_width, self.viewport_height)
            if action:
                await execute_action_on_page(page, action)
                human_delay(1.0, 2.0)

                # 再次截图确认选择后点击确认
                shot_path2 = await screenshot_page(page, "resume_confirm.png")
                response2 = await call_uitars(
                    shot_path2,
                    "找到确认/发送/提交简历的按钮，点击它完成投递。"
                )
                action2 = parse_uitars_action(response2, self.viewport_width, self.viewport_height)
                if action2:
                    await execute_action_on_page(page, action2)
                    human_delay(1.5, 2.5)

        except Exception as e:
            print(f"  [WARN] 处理简历选择时出错: {e}")

    async def process_city(self, city: str):
        """处理单个城市的全部远程职位"""
        print(f"\n{'='*60}")
        print(f"🏙️ 开始处理城市: {city}")
        print(f"{'='*60}")

        # 切换城市
        if not await self.switch_city(city):
            print(f"  ❌ 无法切换到城市: {city}，跳过")
            return

        # 搜索远程职位
        if not await self.search_remote_jobs():
            print(f"  ❌ 搜索失败，跳过城市: {city}")
            return

        # 处理分页
        page_num = 1
        while page_num <= 5:  # 每个城市最多5页
            print(f"\n  📄 第 {page_num} 页")
            shot_path = await screenshot_page(self.page, f"results_{city}_p{page_num}.png")

            jobs = await self.get_job_listings()
            if not jobs:
                print(f"  ⚠️ 未找到职位，停止翻页")
                break

            print(f"  找到 {len(jobs)} 个职位")
            applied_count = 0

            for job in jobs:
                await self.apply_to_job(job, city)
                human_delay(DELAY_MIN, DELAY_MAX)
                applied_count += 1

            # 翻页
            try:
                next_btn = await self.page.query_selector(
                    ".next-btn, [class*='next'], button:text('下一页'), a:text('下一页')"
                )
                if next_btn and await next_btn.is_enabled():
                    await next_btn.click()
                    await self.page.wait_for_load_state("networkidle", timeout=15000)
                    human_delay(2.0, 3.5)
                    page_num += 1
                else:
                    print(f"  📄 已到最后一页")
                    break
            except Exception:
                break

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
                await self.check_login_and_wait()

                # 获取热门城市列表
                cities = await self.get_hot_cities()
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
                await self.browser.close()


# ─── 入口 ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(BossZhipinAutomator().run())
