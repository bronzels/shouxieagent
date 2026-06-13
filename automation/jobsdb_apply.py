# -*- coding: utf-8 -*-
"""
JobsDB (hk.jobsdb.com) 自动投递脚本
- 登录：邮箱 + 终端输入验证码（暂停等用户输入）
- 遍历 Recommended（推荐）和 Saved searches（保存搜索）
- 严格筛选：远程 + 软件开发 + 无粤语(Cantonese)要求
- 直接点 Apply 申请（无打招呼流程）
- Cover letter 选"不附"，薪资填范围上限或默认 40K HKD/月
- 复用 zhipin_apply.py 的 _post_openrouter / VERIFY_MODELS_TEXT /
  call_uitars / parse_uitars_action / execute_action_on_page / human_delay /
  screenshot_page / image_to_base64 等基础设施
"""

import asyncio
import base64
import csv
import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path

# ─── 从 .env 加载环境变量 ────────────────────────────────────────────────────────
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# rebrowser-playwright 隐身配置（必须在导入/启动前设置）：
# 缓解 Cloudflare 对 CDP 自动化的检测。addBinding 模式修补 Runtime.enable 泄露最隐蔽。
os.environ.setdefault("REBROWSER_PATCHES_RUNTIME_FIX_MODE", "addBinding")
os.environ.setdefault("REBROWSER_PATCHES_SOURCE_URL", "jquery.min.js")
os.environ.setdefault("REBROWSER_PATCHES_UTILITY_WORLD_NAME", "util")

import httpx
from rebrowser_playwright.async_api import async_playwright, Page

# ─── 复用 zhipin_apply 基础设施 ──────────────────────────────────────────────────
# 只 import 稳定的纯函数/常量，不 import 有耦合的 class/全局状态
from zhipin_apply import (
    _post_openrouter,
    _post_uitars_remote,
    VERIFY_MODELS_TEXT,
    VERIFY_MODELS_MULTIMODAL,
    call_uitars,
    parse_uitars_action,
    execute_action_on_page,
    human_mouse_move_and_click,
    image_to_base64,
    UITARS_MODEL,
    UITARS_LOCAL_URL,
    UITARS_LOCAL_MODEL,
)

# ─── 配置 ────────────────────────────────────────────────────────────────────────

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# UI-TARS 提供方式（由 main() 赋值）
UITARS_PROVIDER = "openrouter"
UITARS_ENDPOINT = ""
UITARS_KEY = ""

# 登录邮箱
LOGIN_EMAIL = "bronzels@hotmail.com"

# 默认薪资（职位无薪资范围时填写）：月薪 40000 港币（已与主人确认为月薪）
DEFAULT_SALARY_HKD = 40000

# ─── 申请表单"雇主问题"答题配置 ───────────────────────────────────────────────────
# JobsDB apply 第2步是动态雇主问题（每职位不同）。以下为通用答题规则配置。
#
# HK 工作权利问题答案（radio，单选）。主人指示选 TTPS：
# 对应选项 "I have a temporary visa (eg. QMAS, TTPS, IANG)"。匹配用子串 "TTPS"。
RIGHT_TO_WORK_HK = "TTPS"
# 候选人掌握的编程语言（编程语言勾选题：与选项文本【精确匹配】才勾选，避免 c 命中 CSS/Scala）
CANDIDATE_LANGUAGES = ["python", "java", "c++", "c#", "javascript", "c", "sql"]
# 经验类下拉永远选"经验最多"的最优项（主人指示）
EXPERIENCE_PICK_MAX = True

# 持久化 profile 目录（独立于 zhipin，避免互相污染）
JOBSDB_PROFILE_DIR = Path(__file__).parent / "jobsdb_profile"

APPLIED_JOBS_FILE = Path(__file__).parent / "jobsdb_applied.json"
# 雇主问题 catalog：持久化所有遇到过的动态问题（题型/选项/答题情况），不删旧题
QUESTIONS_CATALOG_FILE = Path(__file__).parent / "jobsdb_questions.json"
SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)
REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# 正文太短时视为抓取失败的阈值（英文 JD 字符更少，适当降低）
MIN_DESC_LEN = 60

# 人类操作延迟（已调低加速：只读遍历/判断，用真实Chrome已过Cloudflare，风险低）
DELAY_MIN = 0.3
DELAY_MAX = 0.7
CARD_DELAY_MIN = 0.5
CARD_DELAY_MAX = 1.0
APPLY_DELAY_MIN = 2.5   # 真实申请动作保持稍稳
APPLY_DELAY_MAX = 4.0


# ─── 工具函数 ─────────────────────────────────────────────────────────────────────

def human_delay(min_s: float = DELAY_MIN, max_s: float = DELAY_MAX):
    """模拟人类随机延迟"""
    t = random.uniform(min_s, max_s)
    time.sleep(t)


async def screenshot_page(page: Page, filename: str) -> str:
    """截图当前页面，返回文件路径"""
    path = str(SCREENSHOTS_DIR / filename)
    await page.screenshot(path=path, full_page=False)
    return path


def load_applied_jobs() -> dict:
    """加载已申请/已跳过职位记录"""
    if APPLIED_JOBS_FILE.exists():
        with open(APPLIED_JOBS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("jobs", [])
            data.setdefault("last_updated", "")
            return data
    return {"jobs": [], "last_updated": ""}


def save_applied_jobs(data: dict):
    """保存职位记录"""
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(APPLIED_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_already_recorded(data: dict, company: str, position: str) -> bool:
    """检查是否已记录（已申请 or 已跳过）"""
    key = f"{company.strip()}|{position.strip()}"
    return any(
        f"{j['company'].strip()}|{j['position'].strip()}" == key
        for j in data["jobs"]
    )


def record_job(data: dict, company: str, position: str, status: str,
               source: str = "", salary: str = ""):
    """记录职位（status: applied / skipped / failed）"""
    data["jobs"].append({
        "company": company,
        "position": position,
        "status": status,
        "source": source,
        "salary": salary,
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    save_applied_jobs(data)


def export_applications_csv(data: dict) -> str:
    """
    导出 CSV 到 reports/ 目录。
    文件名：jobsdb_申请记录_<时间>.csv
    编码：utf-8-sig（Excel 中文不乱码）
    返回文件路径。
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"jobsdb_申请记录_{ts}.csv"
    path = REPORTS_DIR / fname
    jobs = data.get("jobs", [])
    applied = [j for j in jobs if j.get("status") == "applied"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            f"来源：hk.jobsdb.com",
            f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"申请总数：{len(applied)}",
            f"记录总数：{len(jobs)}",
        ])
        w.writerow(["序号", "公司", "职位", "状态", "来源", "薪资", "记录时间"])
        for i, j in enumerate(jobs, 1):
            w.writerow([
                i,
                j.get("company", ""),
                j.get("position", ""),
                j.get("status", ""),
                j.get("source", ""),
                j.get("salary", ""),
                j.get("recorded_at", ""),
            ])
    return str(path)


# ─── 职位筛选 ─────────────────────────────────────────────────────────────────────

async def verify_jobsdb(title: str, desc: str, image_path: str = None) -> tuple[bool, str]:
    """
    判断 JobsDB 职位是否满足投递条件（英文 JD）：
    1. 必须是软件开发岗（同 zhipin 标准，排除运维/PHP/Django/C#/.NET）
    2. 必须支持远程(remote/WFH/work from home)
    3. 不能要求粤语(Cantonese)——这是 JobsDB 特有检查项

    返回 (should_apply, reason_text)
    """
    prompt = f"""You are a strict job filter assistant. Evaluate whether this job meets ALL THREE criteria.
Only recommend applying if ALL conditions are met.

[Condition 1: Must be a software/IT DEVELOPMENT role]
✅ Accept (core work is writing code / software development):
   Backend / Frontend / Full-stack / Mobile / Client-side developer,
   Software Engineer, Programmer, Data Engineer, Algorithm Engineer,
   Machine Learning Engineer, AI Engineer (building models/systems),
   Embedded Developer, SDET (Test Dev)
❌ Reject (even if the posting mentions AI/internet/remote):
   - Operations/DevOps/SRE/SysAdmin/Network Admin (明确不投运维)
   - Roles where PRIMARY stack is PHP / Django / C#/.NET
     (Note: reject only Django framework specifically; other Python web like Flask/FastAPI are OK)
   - Data Annotation, Content/User Operations, Product Manager,
     Sales/Marketing/BD, HR/Recruiter, Copywriter/Editor/Translator,
     Customer Service, Graphic/Visual Designer, Teacher/Trainer,
     Medical/Legal/Finance specialist roles

[Condition 2: Must support remote work / WFH / Work From Home]
   Job title or description explicitly mentions "remote", "work from home",
   "WFH", "fully remote", "remote-first", or equivalent.

[Condition 3: Must NOT require Cantonese]
   If the job description requires Cantonese (粤语) as a mandatory language
   skill, this condition FAILS and the job must be skipped.
   (English and/or Mandarin requirements are acceptable.)

Job Title: {title}

Job Description:
{desc}

Reply STRICTLY in this format (the "Conclusion" line is mandatory):
Is software dev role: Yes/No (explain: specific dev responsibilities or tech stack)
Is ops/DevOps/SRE: Yes/No (if Yes → must not apply)
Primary stack is PHP/Django/C#/.NET: Yes/No (Django only; Flask/FastAPI = No; if Yes → must not apply)
Supports remote: Yes/No
Requires Cantonese: Yes/No (if Yes → must not apply)
Conclusion: Apply / Do not apply
Reason: (one sentence, key reason)"""

    content = [{"type": "text", "text": prompt}]
    models = VERIFY_MODELS_TEXT
    if image_path:
        models = VERIFY_MODELS_MULTIMODAL
        img_b64 = image_to_base64(image_path)
        content.insert(0, {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        })

    payload = {
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 400,
    }
    result = await _post_openrouter(payload, models=models)
    answer = result["choices"][0]["message"]["content"]

    # 解析"Conclusion"行
    concl_line = ""
    for line in answer.splitlines():
        if "Conclusion" in line or "conclusion" in line:
            concl_line = line
            break
    c = concl_line.replace("*", "").replace(" ", "")
    if "Conclusion" in c or "conclusion" in c:
        c = re.split(r"[Cc]onclusion", c, 1)[1]
    # "Apply" 出现且不是 "Do not apply" → 投递
    should_apply = bool(re.search(r"(?i)\bApply\b", c)) and not bool(re.search(r"(?i)(Do\s*not|Donot)\s*apply", c))
    return should_apply, answer


# ─── 薪资解析 ─────────────────────────────────────────────────────────────────────

def parse_salary_fill(salary_text: str) -> int:
    """
    从职位薪资字符串解析出要填写的薪资（整数，港币/月）。
    逻辑：
      - 有范围（如 "$30K – $50K / month"）→ 取上限
      - 只有一个数字 → 用该数字
      - 解析失败 → 返回 DEFAULT_SALARY_HKD
    TODO: 若薪资单位是年薪(annual/year)而非月薪(monthly/month)，
          需要主人确认如何换算；当前暂按月薪处理。
    """
    if not salary_text:
        return DEFAULT_SALARY_HKD
    # 提取所有数字（支持 30K/30,000/30000）
    nums = re.findall(r"[\d,]+(?:\.?\d+)?[Kk]?", salary_text)
    parsed = []
    for n in nums:
        n_clean = n.replace(",", "")
        if n_clean.upper().endswith("K"):
            try:
                parsed.append(int(float(n_clean[:-1]) * 1000))
            except ValueError:
                pass
        else:
            try:
                v = int(float(n_clean))
                if v > 100:  # 过滤掉年份等噪声数字
                    parsed.append(v)
            except ValueError:
                pass
    if not parsed:
        return DEFAULT_SALARY_HKD
    # 取最大值（范围上限）
    return max(parsed)


# ─── 主 Automator 类 ───────────────────────────────────────────────────────────────

class JobsDBAutomator:
    def __init__(self, dry_run=False):
        self.applied_data = load_applied_jobs()
        self.dry_run = dry_run  # 试运行：登录+遍历+筛选+判断，但不点Apply/不填表单/不记录
        self.cdp_url = None     # 若设置，则连接已运行的真实 Chrome（绕过 Cloudflare）
        self.connected_cdp = False
        self.page: Page = None
        self.context = None
        self.viewport_width = 1280
        self.viewport_height = 900

    # ── 浏览器启动 ────────────────────────────────────────────────────────────────

    async def start_browser(self, playwright):
        """
        两种模式：
        1) CDP 连接模式（self.cdp_url 已设）：连接用户【自己打开的真实 Chrome】。
           用户在真实浏览器里以正常用户身份通过 Cloudflare 验证并登录，脚本只接管驱动。
           这是绕过 Cloudflare Turnstile（对 CDP 自动化检测极强）的可靠方式。
        2) 自启动模式：rebrowser 启动真实 Chrome + 独立 jobsdb_profile（zhipin 同款，
           但 JobsDB 的 Cloudflare 难以自动通过，推荐用模式1）。
        """
        if self.cdp_url:
            print(f"🔌 连接已运行的 Chrome (CDP): {self.cdp_url}", flush=True)
            browser = await playwright.chromium.connect_over_cdp(self.cdp_url)
            # 用已有的 context（用户登录态所在），没有则新建
            self.context = browser.contexts[0] if browser.contexts else await browser.new_context()
            pages = self.context.pages
            # 优先选已在 jobsdb 的标签页
            self.page = None
            for pg in pages:
                if "jobsdb" in (pg.url or ""):
                    self.page = pg
                    break
            self.page = self.page or (pages[0] if pages else await self.context.new_page())
            self.connected_cdp = True
            return

        JOBSDB_PROFILE_DIR.mkdir(exist_ok=True)
        self.context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(JOBSDB_PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": self.viewport_width, "height": self.viewport_height},
            locale="en-HK",
            timezone_id="Asia/Hong_Kong",
            args=[
                "--disable-blink-features=AutomationControlled",
                f"--window-size={self.viewport_width},{self.viewport_height}",
            ],
            ignore_default_args=["--enable-automation"],
        )
        self.page = (
            self.context.pages[0]
            if self.context.pages
            else await self.context.new_page()
        )
        # 不再手动 add_init_script 改写 navigator.webdriver：
        # rebrowser-playwright 已内置处理；重复改写反而制造 Cloudflare 可检测的痕迹。

    # ── 登录 ──────────────────────────────────────────────────────────────────────

    async def _is_logged_in(self) -> bool:
        """
        判断是否已登录：登录后通常有用户头像/菜单元素，
        未登录时顶部有 'Sign in' / 'Log in' 链接。
        TODO: 调试时确认实际选择器（页面结构可能更新）
        """
        try:
            # 先检查已登录标志（用户头像按钮）
            avatar = await self.page.query_selector(
                "[data-automation='nav-user-menu'], "
                "[data-automation='logged-in-user'], "
                ".user-menu, "
                "button[aria-label*='account' i], "
                "button[aria-label*='profile' i]"
            )
            if avatar and await avatar.is_visible():
                return True
            # 再检查未登录标志
            sign_in = await self.page.query_selector(
                "a:has-text('Sign in'), a:has-text('Log in'), "
                "[data-automation='sign-in-link']"
            )
            if sign_in and await sign_in.is_visible():
                return False
            return True  # 无明显未登录标志，保守认为已登录
        except Exception:
            return False

    async def _wait_cloudflare_cleared(self, timeout_s: int = 300) -> bool:
        """
        等待 Cloudflare 人机验证通过。JobsDB 用 Cloudflare 防护，未通过时页面标题为
        "Just a moment..." / "Performing security verification"，且需要【人工点击】
        Turnstile 勾选框("Verify you are human")才能通过——无法自动绕过。
        因此这里长时间轮询（默认 5 分钟），提示用户在浏览器完成验证，期间不关闭浏览器。
        通过判定：标题不再是 just a moment 且页面出现真实内容。
        """
        def _is_challenge(title: str) -> bool:
            t = (title or "").lower()
            return ("just a moment" in t or "moment" in t
                    or "security verification" in t or "verifying" in t
                    or "attention required" in t or title.strip() == "")

        title = await self.page.title()
        if not _is_challenge(title):
            return True

        print("\n" + "=" * 60)
        print("🛡️ 检测到 Cloudflare 人机验证页（Just a moment...）")
        print("   👉 请在打开的浏览器里点击 'Verify you are human' 勾选框完成验证")
        print("   脚本每 3 秒检测一次，最长等待 5 分钟，期间不会关闭浏览器")
        print("=" * 60, flush=True)

        loops = max(1, timeout_s // 3)
        for i in range(loops):
            await asyncio.sleep(3)
            try:
                title = await self.page.title()
                if not _is_challenge(title):
                    print(f"✅ Cloudflare 验证已通过（标题: {title[:40]}）", flush=True)
                    human_delay(2.0, 3.0)
                    return True
            except Exception:
                pass
            if i % 5 == 4:
                print(f"  ⏳ 仍在等待人机验证通过... ({(i+1)*3}秒)", flush=True)
        print("⚠️ 等待 Cloudflare 验证超时（5分钟）", flush=True)
        return False

    async def login(self) -> bool:
        """
        登录流程：
        1. 打开首页，若已登录直接返回 True
        2. 点 'Sign in with email'
        3. 填入邮箱，提交
        4. 暂停脚本，提示用户在终端输入邮箱验证码
        5. 填入验证码，等待跳转确认登录成功
        登录态保存在 jobsdb_profile（下次运行无需重新登录）。

        TODO: 调试时核实以下选择器（JobsDB 页面结构可能变动）：
          - 邮箱输入框: input[type='email'], [data-automation='email-input']
          - 提交按钮: button[type='submit'], button:has-text('Continue')
          - 验证码输入框: input[name='otp'], input[type='text'][maxlength]
          - 验证码提交: button:has-text('Verify'), button[type='submit']
        """
        # CDP 连接模式：用户已在真实 Chrome 里通过 Cloudflare + 登录，脚本只校验登录态
        if self.connected_cdp:
            print("🔌 CDP 模式：使用你真实 Chrome 的会话（已绕过 Cloudflare）", flush=True)
            try:
                if "jobsdb" not in (self.page.url or ""):
                    await self.page.goto("https://hk.jobsdb.com/", wait_until="domcontentloaded", timeout=40000)
                    human_delay(2.0, 3.0)
            except Exception:
                pass
            for i in range(40):  # 最多等 2 分钟你在真实 Chrome 完成登录
                if await self._is_logged_in():
                    print("✅ 已检测到登录状态（真实 Chrome 会话），继续执行", flush=True)
                    return True
                if i == 0:
                    print("  ⏳ 未检测到登录态。请在你的 Chrome 里完成 JobsDB 登录，脚本每3秒检测...", flush=True)
                await asyncio.sleep(3)
            print("⚠️ 未检测到登录态（请确认已在真实 Chrome 登录 JobsDB）", flush=True)
            return False

        print("🌐 正在打开 JobsDB...", flush=True)
        await self.page.goto("https://hk.jobsdb.com/", wait_until="domcontentloaded", timeout=40000)
        human_delay(3.0, 5.0)

        # 先等 Cloudflare 人机验证通过（JobsDB 用 Cloudflare 防护，"Just a moment..."）
        if not await self._wait_cloudflare_cleared():
            print("⚠️ Cloudflare 人机验证未通过，无法继续。", flush=True)
            return False

        if await self._is_logged_in():
            print("✅ 已检测到登录状态（jobsdb_profile 已保存登录态），继续执行", flush=True)
            return True

        print("\n" + "=" * 60)
        print("🔐 未登录，开始邮箱登录流程...")
        print(f"   邮箱: {LOGIN_EMAIL}")
        print("=" * 60, flush=True)

        await screenshot_page(self.page, "jobsdb_before_login.png")

        # 步骤1：点 "Sign in" / "Continue with email"
        # TODO: 调试时确认实际按钮文本和选择器
        clicked = await self._click_smart(
            self.page,
            [
                "a:has-text('Sign in')",
                "button:has-text('Sign in')",
                "[data-automation='sign-in-link']",
                "a:has-text('Log in')",
            ],
            "页面顶部找到 'Sign in' 或 'Log in' 按钮，点击它。",
            "jobsdb_signin_btn.png",
        )
        if not clicked:
            print("  ⚠️ 未找到 Sign in 按钮，可在浏览器手动点登录入口（脚本后续会轮询等登录）", flush=True)

        human_delay(2.0, 3.0)
        await screenshot_page(self.page, "jobsdb_login_page.png")

        # 步骤2：选 "Continue with email"（有些站点有多种登录方式）
        # TODO: 确认是否有 Google/Facebook 等选项，若有则需先点 email 选项
        email_option = await self._click_smart(
            self.page,
            [
                "button:has-text('Continue with email')",
                "button:has-text('Email')",
                "[data-automation='email-login-button']",
            ],
            "找到 'Continue with email' 或 'Email' 按钮，点击它选择邮箱登录方式。",
            "jobsdb_email_option.png",
        )
        if email_option:
            human_delay(1.5, 2.5)
            await screenshot_page(self.page, "jobsdb_email_form.png")

        # 步骤3：填入邮箱
        email_field = await self.page.query_selector(
            "input[type='email'], input[name='email'], "
            "[data-automation='email-input'], input[placeholder*='email' i]"
        )
        if email_field:
            await email_field.click()
            human_delay(0.3, 0.7)
            await email_field.fill(LOGIN_EMAIL)
            human_delay(0.5, 1.0)
        else:
            # 未找到邮箱框 → UI-TARS 视觉兜底定位后填入；仍不行则提示在浏览器手动填
            print("  ⚠️ 选择器未找到邮箱输入框，尝试 UI-TARS 兜底...", flush=True)
            await self._click_smart(
                self.page,
                ["input[type='email']", "input[name='email']", "input[placeholder*='email' i]"],
                "找到邮箱输入框并点击它（准备输入邮箱地址）。",
                "jobsdb_email_field.png",
            )
            try:
                await self.page.keyboard.type(LOGIN_EMAIL, delay=60)
            except Exception:
                print(f"  ⚠️ 请在浏览器页面手动填入邮箱 {LOGIN_EMAIL} 并提交（脚本会轮询等登录）", flush=True)

        # 步骤4：点 Continue/Submit
        await self._click_smart(
            self.page,
            [
                "button[type='submit']",
                "button:has-text('Continue')",
                "button:has-text('Send')",
                "button:has-text('Next')",
            ],
            "找到提交邮箱的按钮（Continue / Submit / Send / Next），点击它。",
            "jobsdb_submit_email.png",
        )
        human_delay(3.0, 5.0)
        await screenshot_page(self.page, "jobsdb_otp_page.png")

        # 步骤5-8：等用户【在浏览器页面】输入验证码并提交，脚本轮询等登录成功。
        # （改为轮询式，不用终端 input()，这样后台运行也可用，且 OTP 直接在网页输入更可靠）
        print("\n" + "=" * 60)
        print(f"📧 验证码已发送到邮箱: {LOGIN_EMAIL}")
        print("   👉 请在【打开的浏览器页面】里输入邮件收到的验证码(OTP)并提交")
        print("   脚本每 5 秒自动检测一次登录状态，最长等待 10 分钟...")
        print("=" * 60, flush=True)

        for i in range(120):  # 最多等 10 分钟
            await asyncio.sleep(5)
            try:
                if await self._is_logged_in():
                    print("✅ 登录成功！", flush=True)
                    await screenshot_page(self.page, "jobsdb_logged_in.png")
                    return True
            except Exception:
                pass
            if i % 6 == 5:
                print(f"  ⏳ 仍在等待你输入验证码登录... ({(i+1)*5}秒)", flush=True)

        print("⚠️ 等待登录超时（10分钟）", flush=True)
        return False

    # ── 通用辅助 ──────────────────────────────────────────────────────────────────

    async def _click_smart(self, page: Page, selectors: list, uitars_instruction: str,
                           shot_name: str, require_text: str = None) -> bool:
        """
        混合点击：选择器优先 + UI-TARS 视觉兜底。
        （逻辑同 zhipin_apply.BossZhipinAutomator._click_smart，在本类中复制以避免耦合）
        """
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

        # UI-TARS 视觉兜底
        print(f"  🔎 选择器未命中，改用 UI-TARS 视觉定位: {shot_name}", flush=True)
        try:
            shot = await screenshot_page(page, shot_name)
            resp = await call_uitars(shot, uitars_instruction)
            action = parse_uitars_action(
                resp, page.viewport_size["width"], page.viewport_size["height"]
            )
            if action and action.get("action_type") in ("click", "left_single"):
                await execute_action_on_page(page, action)
                return True
            print(f"  [WARN] UI-TARS 未返回有效点击动作: {resp[:120]}", flush=True)
        except NotImplementedError:
            print("  [WARN] UI-TARS local 方式未实现，跳过视觉兜底", flush=True)
        except Exception as e:
            print(f"  [WARN] UI-TARS 兜底失败: {e}", flush=True)
        return False

    # ── 职位列表抓取 ──────────────────────────────────────────────────────────────

    async def get_recommended_jobs(self) -> list[dict]:
        """
        抓取"Recommended"（推荐列表）职位。
        导航到 https://hk.jobsdb.com/ 的推荐区或专门的 recommended 页面。

        TODO: 调试时确认以下内容：
          - 推荐职位区域的实际选择器（如 [data-automation='recommended-jobs']）
          - 职位卡片选择器（如 article[data-automation='job-card']）
          - 公司名/职位标题/薪资/是否已申请的子元素选择器
          - 是否需要滚动加载更多（lazy load / infinite scroll）
        """
        print("\n" + "=" * 60)
        print("📋 来源：Recommended（推荐职位）")
        print("=" * 60, flush=True)

        # 推荐列表只在首页根地址，总是先回首页（无论当前在哪个 jobsdb 页面）
        await self.page.goto("https://hk.jobsdb.com/", wait_until="domcontentloaded", timeout=40000)
        human_delay(3.0, 5.0)
        await screenshot_page(self.page, "jobsdb_recommended_page.png")

        # 滚动触发渲染（首页推荐封顶 100 个，实测无翻页/懒加载增量）
        for _ in range(3):
            await self.page.mouse.wheel(0, 800)
            human_delay(1.0, 2.0)

        # 推荐卡实测结构：a[data-automation^='recommendedJobLink'] 覆盖整卡，
        # 卡内 [data-automation='jobTitle'] / [data-automation='jobAdvertiser']。
        # href 是 DOM 真实链接（/job/<id>），非拼接。
        raw = await self.page.evaluate(r"""() => {
            const out=[];
            for(const a of document.querySelectorAll("a[data-automation^='recommendedJobLink']")){
                let card=a; for(let i=0;i<5;i++){ if(card.querySelector("[data-automation='jobTitle']"))break; card=card.parentElement; if(!card)break; }
                if(!card) continue;
                const tt=card.querySelector("[data-automation='jobTitle']");
                const co=card.querySelector("[data-automation='jobAdvertiser']");
                const applied=/applied/i.test(card.textContent||'');
                out.push({title: tt?tt.textContent.trim():'', company: co?co.textContent.trim():'Unknown',
                          href: a.getAttribute('href')||'', already_applied: applied});
            }
            return out;
        }""")
        jobs, seen = [], set()
        for r in raw:
            if not r.get("title") or not r.get("href") or r["href"] in seen:
                continue
            seen.add(r["href"])
            jobs.append({"source": "Recommended", "title": r["title"], "company": r["company"],
                         "salary": "", "already_applied": r["already_applied"],
                         "detail_url": "https://hk.jobsdb.com" + r["href"]})
        print(f"  ✅ 推荐列表共抓取 {len(jobs)} 个职位", flush=True)
        return jobs

    async def get_saved_search_jobs(self) -> list[dict]:
        """
        抓取"Saved searches"（保存的搜索）中的职位。

        TODO: 调试时确认以下内容：
          - Saved searches 入口 URL 或导航路径
          - 可能有多个保存搜索，需逐个展开或翻页
          - 职位卡片选择器是否与推荐列表相同
          - 典型 URL 候选：
            https://hk.jobsdb.com/saved-searches
            https://hk.jobsdb.com/profile/saved-searches
        """
        print("\n" + "=" * 60)
        print("🔖 来源：Saved searches（保存的搜索）")
        print("=" * 60, flush=True)

        # 回到首页（根地址），点 Saved searches 区块里名为 "ai" 的保存搜索。
        # 实测：a[data-automation^='savedSearchLink_']，href 含 /ai-jobs/。
        if "hk.jobsdb.com" not in (self.page.url or "") or "/ai-jobs" not in (self.page.url or ""):
            await self.page.goto("https://hk.jobsdb.com/", wait_until="domcontentloaded", timeout=40000)
            human_delay(3.0, 5.0)

        ai_link = None
        for sel in ["a[data-automation^='savedSearchLink_'][href*='/ai-jobs/']",
                    "a[href*='/ai-jobs/']"]:
            try:
                el = await self.page.query_selector(sel)
                if el:
                    ai_link = el
                    break
            except Exception:
                continue
        if not ai_link:
            print("  ❌ 首页未找到 'ai' 保存搜索链接，跳过此来源", flush=True)
            return []

        ai_href = await ai_link.get_attribute("href") or ""
        print(f"  🔖 进入 'ai' 保存搜索结果页: {ai_href[:70]}", flush=True)
        await ai_link.click()
        human_delay(3.0, 5.0)
        await screenshot_page(self.page, "jobsdb_ai_results.png")

        # 逐页抓取 normalJob 卡，翻页到尾。上限设大以覆盖全部（约1510个/30每页≈51页），
        # 防失控保留一个上限。
        MAX_PAGES = 60
        all_jobs = []
        seen = set()
        for pno in range(1, MAX_PAGES + 1):
            human_delay(1.5, 2.5)
            raw = await self.page.evaluate(r"""() => {
                const out=[];
                for(const c of document.querySelectorAll("article[data-automation='normalJob']")){
                    const tt=c.querySelector("[data-automation='jobTitle']");
                    const co=c.querySelector("[data-automation='jobCompany'],[data-automation='jobAdvertiser']");
                    const lk=c.querySelector("a[href*='/job/']");
                    const applied=/applied/i.test(c.textContent||'');
                    if(tt&&lk) out.push({title:tt.textContent.trim(),
                        company:co?co.textContent.trim():'Unknown',
                        href:lk.getAttribute('href')||'', already_applied:applied});
                }
                return out;
            }""")
            newn = 0
            for r in raw:
                if not r.get("href") or r["href"] in seen:
                    continue
                seen.add(r["href"])
                all_jobs.append({"source": "SavedSearch:ai", "title": r["title"],
                                 "company": r["company"], "salary": "",
                                 "already_applied": r["already_applied"],
                                 "detail_url": "https://hk.jobsdb.com" + r["href"]})
                newn += 1
            print(f"    第 {pno} 页: +{newn} 个（累计 {len(all_jobs)}）", flush=True)

            # 翻下一页：JobsDB 分页是数字页码 a[data-automation='page-N']（实测 page-2/3…），
            # 优先点下一页码，其次尝试 page-next/Next 箭头。
            nxt = None
            for sel in [f"a[data-automation='page-{pno+1}']",
                        "[data-automation='page-next']",
                        "a[aria-label='Next']", "a[rel='next']"]:
                try:
                    el = await self.page.query_selector(sel)
                    if el and await el.is_visible():
                        nxt = el
                        break
                except Exception:
                    continue
            if not nxt:
                print("    已到最后一页（无下一页链接）", flush=True)
                break
            try:
                await nxt.click()
                await self.page.wait_for_load_state("domcontentloaded", timeout=20000)
                human_delay(1.5, 2.5)
            except Exception:
                break
        else:
            print(f"  ⚠️ 达到页数上限 {MAX_PAGES}，停止翻页（其余下次运行处理，去重不重复）", flush=True)

        print(f"  ✅ 'ai' 保存搜索共抓取 {len(all_jobs)} 个职位", flush=True)
        return all_jobs

    async def _extract_job_cards_from_page(self, source: str) -> list[dict]:
        """
        从当前页面提取职位卡片信息。
        尽量从列表项读取 公司名 + 职位名 + 薪资 + 是否已申请，
        避免逐个打开详情页（加速策略）。

        TODO: 调试时核实以下选择器（JobsDB 2024/2025 页面结构）：
          - 职位卡片容器: article[data-automation='job-card']
                          div[data-automation='job-card']
                          [data-testid='job-card']
          - 职位标题: [data-automation='job-title'] h1 h2 h3
          - 公司名: [data-automation='company-name']
          - 薪资: [data-automation='job-salary']
          - 已申请标记: 'Applied' 文字 or [data-automation='applied-badge']
          - Apply 按钮: button:has-text('Apply'), [data-automation='apply-button']
        """
        jobs = []
        # 尝试多种卡片容器选择器
        card_selectors = [
            "article[data-automation='job-card']",
            "div[data-automation='job-card']",
            "[data-testid='job-card']",
            "article[class*='job-card']",
            "div[class*='JobCard']",
            # TODO: 调试时若以上都无效，用截图+UI-TARS 分析页面结构
        ]
        cards = []
        for sel in card_selectors:
            try:
                found = await self.page.query_selector_all(sel)
                if found:
                    cards = found
                    break
            except Exception:
                continue

        if not cards:
            print(f"  ⚠️ [{source}] 未找到职位卡片，选择器可能需要调试", flush=True)
            await screenshot_page(self.page, f"jobsdb_no_cards_{source[:20]}.png")
            return []

        for card in cards:
            try:
                job: dict = {"source": source, "element": card}

                # 职位标题
                for sel in ["[data-automation='job-title']", "h1", "h2", "h3",
                             "[class*='title' i]", "a[href*='/job/']"]:
                    el = await card.query_selector(sel)
                    if el:
                        t = (await el.text_content() or "").strip()
                        if t:
                            job["title"] = t
                            break
                if not job.get("title"):
                    continue

                # 公司名
                for sel in ["[data-automation='company-name']", "[data-automation='advertiser-name']",
                             "[class*='company' i]", "[class*='employer' i]"]:
                    el = await card.query_selector(sel)
                    if el:
                        t = (await el.text_content() or "").strip()
                        if t:
                            job["company"] = t
                            break
                if not job.get("company"):
                    job["company"] = "Unknown"

                # 薪资（可选）
                for sel in ["[data-automation='job-salary']", "[class*='salary' i]",
                             "[data-automation='salary-range']"]:
                    el = await card.query_selector(sel)
                    if el:
                        t = (await el.text_content() or "").strip()
                        if t:
                            job["salary"] = t
                            break
                job.setdefault("salary", "")

                # 是否已申请（Applied badge）
                job["already_applied"] = False
                for sel in ["[data-automation='applied-badge']", "span:has-text('Applied')",
                             "div:has-text('Applied')", "[class*='applied' i]"]:
                    el = await card.query_selector(sel)
                    if el and await el.is_visible():
                        t = (await el.text_content() or "").lower()
                        if "applied" in t:
                            job["already_applied"] = True
                            break

                # Apply 按钮（列表项直接有的话记录）
                job["has_apply_btn"] = False
                for sel in ["button:has-text('Apply now')", "button:has-text('Apply')",
                             "a:has-text('Apply now')", "[data-automation='apply-button']"]:
                    el = await card.query_selector(sel)
                    if el and await el.is_visible():
                        job["has_apply_btn"] = True
                        break

                # 职位详情页 URL（用于需要打开详情时）
                job["detail_url"] = ""
                link_el = await card.query_selector("a[href*='/job/'], a[href*='/jobad/']")
                if link_el:
                    href = await link_el.get_attribute("href") or ""
                    if href.startswith("/"):
                        href = "https://hk.jobsdb.com" + href
                    job["detail_url"] = href

                jobs.append(job)
            except Exception as e:
                print(f"  [WARN] 解析卡片失败: {e}", flush=True)
                continue

        return jobs

    # ── 职位描述抓取 ──────────────────────────────────────────────────────────────

    async def get_job_description(self, job: dict) -> str:
        """
        获取职位描述正文。
        优先从当前卡片/展开区域读取，若不够长则打开详情页。

        TODO: 调试时确认：
          - 列表项是否有 snippet/description 摘要（可能足够判断）
          - 详情页的正文选择器
        """
        # 先尝试从卡片读取摘要/片段
        desc = ""
        card = job.get("element")
        if card:
            for sel in ["[data-automation='job-description']", "[class*='description' i]",
                        "[class*='snippet' i]", "p"]:
                try:
                    el = await card.query_selector(sel)
                    if el:
                        t = (await el.text_content() or "").strip()
                        if len(t) >= MIN_DESC_LEN:
                            desc = t
                            break
                except Exception:
                    continue

        if len(desc) >= MIN_DESC_LEN:
            return desc

        # 摘要不足 → 打开详情页
        detail_url = job.get("detail_url", "")
        if not detail_url:
            return desc

        # TODO: 调试时确认详情页 JD 正文选择器
        try:
            await self.page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
            # 详情页 SPA：等 JD 容器出现即读（缩短超时与固定延迟，加速）
            try:
                await self.page.wait_for_selector("[data-automation='jobAdDetails']", timeout=8000)
            except Exception:
                pass
            human_delay(0.4, 0.9)
            for sel in [
                "[data-automation='jobAdDetails']",   # 实测确认的 JD 正文容器
                "[data-automation='jobDescription']",
                "[class*='JobDescription']",
            ]:
                el = await self.page.query_selector(sel)
                if el:
                    t = (await el.text_content() or "").strip()
                    if len(t) >= MIN_DESC_LEN:
                        desc = t
                        break
        except Exception as e:
            print(f"  [WARN] 打开详情页失败: {e}", flush=True)

        return desc

    # ── Apply 表单填写 ────────────────────────────────────────────────────────────

    async def fill_apply_form(self, job: dict) -> bool:
        """
        填写 JobsDB 原生 Quick apply 表单（已实测 DOM 结构，2026-06-13）。

        流程为独立页 /job/<id>/apply 的多步骤，每步点 Continue 推进：
          Step 1  Choose documents (/apply)
                  - Resume:  input[name='resume-method'][value='change'] (用已上传简历)
                  - Cover letter: input[name='coverLetter-method'][value='none'] (不附)
                  - Continue
          Step 2  Answer employer questions (/apply/role-requirements)
                  - 动态 questionnaire.* 题（经验/薪资/HK工作权利/语言/技能…）
                  - 见 _answer_employer_questions（规则化答题）
                  - Continue
          Step 3  Update Jobsdb Profile  → Continue（跳过，不改资料）
          Step 4  Review and submit      → Submit application
        """
        salary_to_fill = parse_salary_fill(job.get("salary", ""))
        print(f"  \U0001f4b0 期望月薪: {salary_to_fill} HKD（来源: {job.get('salary', '无范围→默认40K')}）",
              flush=True)

        # 等申请页加载（点 Apply 后是整页导航到 /apply）
        try:
            await self.page.wait_for_url("**/apply**", timeout=15000)
        except Exception:
            pass
        human_delay(1.2, 2.0)
        cur_url = self.page.url
        # 第三方/外部跳转：不在 hk.jobsdb.com 的 /apply 流程 → 跳过（主人指示）
        if "jobsdb.com" not in cur_url or "/apply" not in cur_url:
            print(f"  ⏭️  [跳过-第三方投递] 申请跳转到外部页面: {cur_url[:80]}", flush=True)
            return False
        await screenshot_page(self.page, f"jobsdb_apply_step1_{self._safe_name(job)}.png")

        # ── Step 1: Choose documents ──────────────────────────────────────────────
        # 简历：选"Select a resumé"（用已上传简历）。选 change 后会出现一个简历下拉，
        # 必须再从下拉里选中具体简历文件，否则校验拦截 "Please make a selection"。
        try:
            r = await self.page.query_selector("input[name='resume-method'][value='change']")
            if r:
                await r.check()
                human_delay(0.5, 0.9)
                # 选 change 后出现简历下拉：用 Playwright select_option（触发真实事件，React 才更新）
                picked_resume = None
                for sel_el in await self.page.query_selector_all("select"):
                    try:
                        opt_texts = await sel_el.eval_on_selector_all(
                            "option", "els => els.map(e => e.textContent.trim())")
                        # 命中简历下拉：含 placeholder 'please select a resum' 或 .pdf/.doc 选项
                        if any(re.search(r"please select a resum|\.pdf|\.doc", t, re.I)
                               for t in opt_texts):
                            # 选第一个非 placeholder 的真实简历
                            for t in opt_texts:
                                if not re.search(r"please select", t, re.I) and t.strip():
                                    await sel_el.select_option(label=t)
                                    picked_resume = t
                                    break
                            break
                    except Exception:
                        continue
                if picked_resume:
                    print(f"  ✅ 简历: {picked_resume}", flush=True)
                else:
                    print("  ✅ 简历: 使用已上传简历(默认)", flush=True)
                human_delay(0.3, 0.6)
        except Exception as e:
            print(f"  [WARN] 选简历失败: {e}", flush=True)
        # Cover letter：选"Don't include a cover letter"
        try:
            c = await self.page.query_selector("input[name='coverLetter-method'][value='none']")
            if c:
                await c.check()
                human_delay(0.4, 0.8)
                print("  ✅ Cover letter: 不附", flush=True)
        except Exception as e:
            print(f"  [WARN] 选 cover letter 失败: {e}", flush=True)

        if not await self._click_continue("step1-documents", job):
            print("  ⚠️ Step1 未能点 Continue", flush=True)
            return False
        human_delay(1.2, 2.0)

        # ── Step 2: Answer employer questions（动态题）──────────────────────────────
        # 只有当本步确实是问卷页时才答题（部分职位无此步，会直接到 review）
        if "role-requirements" in self.page.url:
            await self._answer_employer_questions(job, salary_to_fill)
            if not await self._click_continue("step2-questions", job):
                print("  ⚠️ Step2 未能点 Continue（可能有必答题未填）", flush=True)
                await screenshot_page(self.page, f"jobsdb_step2_stuck_{self._safe_name(job)}.png")
                return False
            human_delay(1.2, 2.0)

        # ── Step 3: Update Jobsdb Profile → 直接 Continue 跳过 ─────────────────────
        for _ in range(2):
            low = (await self.page.title() or "").lower()
            if "review" in low or "submit" in self.page.url.lower():
                break
            if "profile" in self.page.url.lower() or "profile" in low:
                if not await self._click_continue("step3-profile", job):
                    break
                human_delay(1.0, 1.8)
            else:
                break

        # ── Step 4: Review and submit ─────────────────────────────────────────────
        human_delay(1.0, 1.8)
        await screenshot_page(self.page, f"jobsdb_before_submit_{self._safe_name(job)}.png")
        submitted = False
        for sel in [
            "button:has-text('Submit application')",
            "[data-automation='review-submit-application']",
            "button:has-text('Submit')",
        ]:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    submitted = True
                    print("  \U0001f4e8 已点击 Submit application", flush=True)
                    break
            except Exception:
                continue
        if not submitted:
            print("  ⚠️ 未找到 Submit application 按钮", flush=True)
            await screenshot_page(self.page, f"jobsdb_no_submit_{self._safe_name(job)}.png")
            return False

        human_delay(APPLY_DELAY_MIN, APPLY_DELAY_MAX)
        await screenshot_page(self.page, f"jobsdb_after_submit_{self._safe_name(job)}.png")

        # 确认提交成功
        try:
            content = (await self.page.content()).lower()
            if any(kw in content for kw in
                   ["application submitted", "successfully applied", "your application has been",
                    "application sent", "you've applied"]):
                print("  ✅ 页面确认申请提交成功", flush=True)
                return True
            if "/apply/success" in self.page.url.lower() or "submitted" in self.page.url.lower():
                print("  ✅ URL 确认申请提交成功", flush=True)
                return True
        except Exception:
            pass
        # 未明确确认，但已点提交：视为成功（截图留证）
        return True

    async def _click_continue(self, tag: str, job: dict) -> bool:
        """点击当前步骤的 Continue 按钮（JobsDB 申请流程每步推进按钮）。"""
        for sel in [
            "button:has-text('Continue')",
            "[data-automation='continue-button']",
            "button:has-text('Next')",
        ]:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible() and await el.is_enabled():
                    await el.click()
                    human_delay(0.8, 1.4)
                    return True
            except Exception:
                continue
        return False

    async def _answer_employer_questions(self, job: dict, salary_to_fill: int):
        """
        规则化回答 JobsDB apply 第2步的动态雇主问题。

        ⚠️ 雇主问题不固定：发布人从一个很长的固定问题库里勾选，不同职位是不同子集，
        每次都可能遇到新问题。因此本方法：
          1. 用"题型规则"识别（而非写死题名），能泛化到没见过的新题
          2. 把每个遇到过的问题持久化到 jobsdb_questions.json（catalog），不删旧题
          3. 规则无法自信回答的题，标记 answered=False 入 catalog，待补规则

        题型与策略：
          - 经验类下拉（含 'More than 5 years'）→ 选最大（EXPERIENCE_PICK_MAX）
          - 期望薪资下拉（$5K..$120K）→ 选 >= 期望月薪的最接近档
          - 其他下拉 → 选最后一个非空选项
          - HK 工作权利 radio → 匹配 RIGHT_TO_WORK_HK（TTPS）
          - Yes/No radio → 正向问题选 Yes
          - 编程语言 checkbox → 勾选 CANDIDATE_LANGUAGES 命中项
          - 语言熟练度 checkbox（Writes/Speaks/Limited）→ 勾 Writes+Speaks proficiently
          - 其他 checkbox → 勾第一个非"None"项
        """
        controls = await self.page.evaluate(r"""() => {
            function qtext(inp){
                let fs=inp.closest('fieldset'); if(fs){const lg=fs.querySelector('legend'); if(lg)return lg.textContent.trim();}
                let cur=inp.parentElement;
                for(let i=0;i<6&&cur;i++){
                    const strong=cur.querySelector(':scope > strong, :scope > label, :scope > div > strong');
                    if(strong&&strong.textContent.trim().length>5)return strong.textContent.trim().slice(0,160);
                    cur=cur.parentElement;
                }
                return '';
            }
            function labelFor(inp){
                if(inp.id){const l=document.querySelector(`label[for="${CSS.escape(inp.id)}"]`); if(l)return l.textContent.trim();}
                const l2=inp.closest('label'); if(l2)return l2.textContent.trim();
                return inp.getAttribute('aria-label')||'';
            }
            const seen=new Set(), out=[];
            for(const el of document.querySelectorAll("select, input[type=radio], input[type=checkbox]")){
                if(el.tagName==='SELECT'){
                    out.push({name:el.name,kind:'select',q:qtext(el),
                        options:[...el.options].map(o=>({v:o.value,t:o.textContent.trim()}))});
                } else {
                    if(seen.has(el.name))continue; seen.add(el.name);
                    const group=[...document.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`)];
                    out.push({name:el.name,kind:el.type,q:qtext(el),
                        options:group.map((g,i)=>({i:i,label:labelFor(g)}))});
                }
            }
            return out;
        }""")

        def opt_texts(opts):
            return [o.get("t") or o.get("label") or "" for o in opts]

        for ctl in controls:
            name = ctl["name"]
            kind = ctl["kind"]
            opts = ctl["options"]
            q = (ctl.get("q") or "").strip()
            texts = opt_texts(opts)
            joined = " | ".join(texts).lower()
            answered = False
            chosen_desc = ""
            try:
                if kind == "select":
                    real = [o for o in opts if (o.get("v") or "").strip() and (o.get("t") or "").strip()]
                    if not real:
                        self._record_question(name, kind, q, texts, False, "无可选项")
                        continue
                    is_exp = any("more than 5 years" in (o.get("t") or "").lower() for o in opts)
                    is_salary = any(re.match(r"\$\d", (o.get("t") or "").strip()) for o in opts)
                    if is_exp and EXPERIENCE_PICK_MAX:
                        target = real[-1]
                        label = "经验→最大"
                    elif is_salary:
                        target = self._pick_salary_option(real, salary_to_fill)
                        label = "薪资档"
                    else:
                        target = real[-1]
                        label = "默认末项"
                    await self.page.select_option(f"select[name='{name}']", value=target["v"])
                    chosen_desc = target.get("t")
                    answered = True
                    print(f"  ✅ [{label}] {q[:40] or name[-12:]} → {chosen_desc}", flush=True)
                    human_delay(0.3, 0.6)

                elif kind == "radio":
                    pick_idx = None
                    rule = "兜底首项"
                    if "right to work" in q.lower() or "right to work" in joined:
                        for o in opts:
                            if RIGHT_TO_WORK_HK.lower() in (o.get("label") or "").lower():
                                pick_idx = o["i"]; rule = "HK工作权利"; break
                    if pick_idx is None and ("yes" in joined and "no" in joined):
                        for o in opts:
                            if (o.get("label") or "").strip().lower() == "yes":
                                pick_idx = o["i"]; rule = "Yes/No→Yes"; break
                    if pick_idx is None:
                        pick_idx = opts[0]["i"]
                    radios = await self.page.query_selector_all(f"input[name='{name}']")
                    if pick_idx < len(radios):
                        await radios[pick_idx].check()
                        chosen_desc = next((o.get("label") for o in opts if o["i"] == pick_idx), "?")
                        answered = (rule != "兜底首项")
                        print(f"  ✅ [单选/{rule}] {q[:40] or name[-12:]} → {chosen_desc}", flush=True)
                        human_delay(0.3, 0.6)

                elif kind == "checkbox":
                    boxes = await self.page.query_selector_all(f"input[name='{name}']")
                    picked = []
                    is_lang_prof = "proficien" in joined
                    is_prog = any(t.lower() in ("python", "java", "javascript", "c++", "c#")
                                  for t in texts)
                    for o in opts:
                        lab = (o.get("label") or "").lower()
                        want = False
                        if is_lang_prof:
                            want = "proficiently" in lab
                        elif is_prog:
                            # 精确匹配选项文本，避免 "c" 命中 CSS/Scala/Objective-C
                            want = lab.strip() in [cl.strip() for cl in CANDIDATE_LANGUAGES]
                        if want and o["i"] < len(boxes):
                            await boxes[o["i"]].check()
                            picked.append(o.get("label"))
                            human_delay(0.2, 0.4)
                    if not picked and boxes:
                        for o in opts:
                            if "none" not in (o.get("label") or "").lower() and o["i"] < len(boxes):
                                await boxes[o["i"]].check()
                                picked.append(o.get("label")); break
                    answered = bool(picked) and (is_lang_prof or is_prog)
                    chosen_desc = ", ".join(picked)
                    if picked:
                        print(f"  ✅ [多选] {q[:40] or name[-12:]} → {chosen_desc}", flush=True)
                self._record_question(name, kind, q, texts, answered, chosen_desc)
            except Exception as e:
                print(f"  [WARN] 答题失败 {name}: {e}", flush=True)
                self._record_question(name, kind, q, texts, False, f"异常:{e}")

        await screenshot_page(self.page, f"jobsdb_questions_{self._safe_name(job)}.png")

    def _record_question(self, name, kind, q, options, answered, chosen):
        """持久化遇到过的雇主问题到 catalog（不删旧题；标记未自信回答的待补规则）。"""
        try:
            cat = {}
            if QUESTIONS_CATALOG_FILE.exists():
                cat = json.loads(QUESTIONS_CATALOG_FILE.read_text(encoding="utf-8"))
            entry = cat.get(name, {})
            entry["kind"] = kind
            if q:
                entry["question"] = q
            # 合并选项（保留历史出现过的所有选项）
            old_opts = set(entry.get("options", []))
            entry["options"] = sorted(old_opts | set([o for o in options if o]))
            entry["seen_count"] = entry.get("seen_count", 0) + 1
            entry["last_answered"] = answered
            entry["last_chosen"] = chosen
            if not answered:
                entry["needs_rule"] = True  # 标记：规则未自信回答，待补
            cat[name] = entry
            QUESTIONS_CATALOG_FILE.write_text(
                json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"  [WARN] 记录问题 catalog 失败: {e}", flush=True)

    def _pick_salary_option(self, real_opts: list, salary_to_fill: int) -> dict:
        """从薪资下拉（$5K..$120K or more）中选 >= 期望月薪的最接近档；无则选最高。"""
        want_k = max(1, round(salary_to_fill / 1000))
        best = None
        best_k = None
        for o in real_opts:
            m = re.search(r"\$(\d+)", o.get("t") or "")
            if not m:
                continue
            k = int(m.group(1))
            if k >= want_k and (best_k is None or k < best_k):
                best, best_k = o, k
        return best or real_opts[-1]
    def _safe_name(self, job: dict) -> str:
        """生成文件名安全的职位标识符"""
        company = job.get("company", "unknown")
        title = job.get("title", "unknown")
        raw = f"{company}_{title}"
        return re.sub(r"[^\w]", "_", raw)[:40]

    # ── 单职位处理 ────────────────────────────────────────────────────────────────

    async def process_job(self, job: dict, stat: dict) -> str:
        """
        处理单个职位：
        1. 去重检查（已记录 → 跳过）
        2. 已申请标记检查（页面显示 Applied → 跳过）
        3. 抓取 JD 正文
        4. verify_jobsdb 筛选（远程 + 软件开发 + 无 Cantonese）
        5. 点 Apply → 填表单 → 记录

        返回状态字符串: applied / dup / no_apply_btn / reject / fail
        """
        company = job.get("company", "")
        title = job.get("title", "")
        source = job.get("source", "")
        salary_text = job.get("salary", "")

        stat["checked"] += 1

        # 去重
        if is_already_recorded(self.applied_data, company, title):
            print(f"  ⏭️  [跳过-已记录] {company} | {title}", flush=True)
            stat["dup"] += 1
            self._print_progress(stat)
            return "dup"

        # 页面级 Applied 标记
        if job.get("already_applied"):
            print(f"  ⏭️  [跳过-已申请(Applied标记)] {company} | {title}", flush=True)
            record_job(self.applied_data, company, title, "skipped_applied", source, salary_text)
            stat["dup"] += 1
            self._print_progress(stat)
            return "dup"

        print(f"\n  🔎 检查职位: {company} | {title}", flush=True)
        print(f"     薪资: {salary_text or 'N/A'} | 来源: {source}", flush=True)

        # 抓取 JD
        # 优化：先用列表卡片的标题判断（快速过滤明显不符合的），
        # 再需要时才打开详情页拿完整 JD
        # TODO: 可根据调试结果调整是否优先用标题做初步过滤
        desc = await self.get_job_description(job)
        safe = self._safe_name(job)

        # 正文不足时仅打印警告，仍用文本判断（不截图 OCR——运行时禁用多模态读文字）。
        if len(desc) < MIN_DESC_LEN:
            print(f"  ⚠️ 正文抓取不足({len(desc)}字)，仍按文本(标题+少量正文)判断，不截图OCR", flush=True)

        # LLM 验证（纯文本，绝不传截图）
        try:
            should_apply, reason = await verify_jobsdb(title, desc, None)
        except Exception as e:
            print(f"  [ERROR] LLM 验证失败: {e}", flush=True)
            stat["fail"] += 1
            self._print_progress(stat)
            return "fail"

        verdict = "✅ 投递" if should_apply else "❌ 跳过"
        print(f"  🤖 判断[{verdict}]: {reason[:400].replace(chr(10), ' ')}", flush=True)

        if not should_apply:
            record_job(self.applied_data, company, title, "skipped_reject", source, salary_text)
            stat["reject"] += 1
            self._print_progress(stat)
            return "reject"

        # dry-run 调试模式：判断通过即停，不点 Apply / 不填表单 / 不记录
        if getattr(self, "dry_run", False):
            print(f"  🧪 [dry-run] 本应申请（未实际点Apply/未填表单/未记录）: {company} | {title}", flush=True)
            stat["would_apply"] = stat.get("would_apply", 0) + 1
            self._print_progress(stat)
            return "would_apply"

        # 检查 Apply 按钮（此时已在详情页——get_job_description 已导航到 detail_url）
        # 实测确认：详情页申请按钮为 a[data-automation='job-detail-apply']
        #   - 文字 "Quick apply" → JobsDB 原生表单（可自动投递）
        #   - 文字 "Apply"       → 跳第三方网站投递（主人指示：跳过）
        apply_btn = None
        for sel in [
            "a[data-automation='job-detail-apply']",
            "[data-automation='job-detail-apply']",
            "button:has-text('Quick apply')",
            "a:has-text('Quick apply')",
        ]:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    apply_btn = el
                    break
            except Exception:
                continue

        if not apply_btn:
            print(f"  ⏭️  [跳过-无Apply按钮] {company} | {title}", flush=True)
            stat["no_apply_btn"] = stat.get("no_apply_btn", 0) + 1
            self._print_progress(stat)
            return "no_apply_btn"

        # 第三方投递识别：按钮文字非 "Quick apply"（如 "Apply"）→ 跳第三方，跳过
        try:
            btn_text = ((await apply_btn.text_content()) or "").strip().lower()
        except Exception:
            btn_text = ""
        if btn_text and "quick apply" not in btn_text:
            print(f"  ⏭️  [跳过-第三方投递] 申请按钮为 '{btn_text}'（非 Quick apply）", flush=True)
            record_job(self.applied_data, company, title, "skipped_external", source, salary_text)
            stat["reject"] += 1
            self._print_progress(stat)
            return "external"

        # 点 Apply
        try:
            bb = await apply_btn.bounding_box()
            if bb:
                await human_mouse_move_and_click(
                    self.page,
                    int(bb["x"] + bb["width"] / 2),
                    int(bb["y"] + bb["height"] / 2),
                )
            else:
                await apply_btn.click()
            human_delay(2.0, 3.0)
        except Exception as e:
            print(f"  [ERROR] 点 Apply 按钮失败: {e}", flush=True)
            stat["fail"] += 1
            self._print_progress(stat)
            return "fail"

        # 填写申请表单
        try:
            success = await self.fill_apply_form(job)
        except Exception as e:
            print(f"  [ERROR] 填写表单失败: {e}", flush=True)
            success = False

        if success:
            print(f"  ✅ [申请成功] {company} | {title}", flush=True)
            record_job(self.applied_data, company, title, "applied", source, salary_text)
            stat["applied"] += 1
        else:
            print(f"  ⚠️ [申请失败] {company} | {title}", flush=True)
            record_job(self.applied_data, company, title, "failed", source, salary_text)
            stat["fail"] += 1

        self._print_progress(stat)
        human_delay(DELAY_MIN, DELAY_MAX)
        return "applied" if success else "fail"

    def _print_progress(self, stat: dict):
        """输出实时进度"""
        skipped = stat.get("reject", 0) + stat.get("dup", 0) + stat.get("no_apply_btn", 0)
        print(
            f"     ▸ 进度：检查 {stat['checked']} | "
            f"申请 {stat['applied']} | "
            f"跳过 {skipped} | "
            f"失败 {stat['fail']}",
            flush=True,
        )

    # ── 主运行入口 ────────────────────────────────────────────────────────────────

    async def run(self):
        """主运行入口：登录 → Recommended → Saved searches → 汇总"""
        if not OPENROUTER_API_KEY:
            raise ValueError(
                "缺少 OPENROUTER_API_KEY！\n"
                "请在 automation/.env 中设置：OPENROUTER_API_KEY=sk-or-v1-xxx\n"
                "或设置环境变量 OPENROUTER_API_KEY"
            )

        print("\n" + "🤖 " * 20)
        print("JobsDB (hk.jobsdb.com) 自动投递脚本 启动")
        print("🤖 " * 20 + "\n", flush=True)

        # 初始化统计
        stat = {
            "checked": 0,
            "applied": 0,
            "reject": 0,
            "dup": 0,
            "no_apply_btn": 0,
            "fail": 0,
        }

        async with async_playwright() as playwright:
            await self.start_browser(playwright)
            try:
                # 登录
                logged_in = await self.login()
                if not logged_in:
                    print("❌ 未能登录，终止运行", flush=True)
                    return

                # ── 来源1：Recommended ────────────────────────────────────────────
                rec_jobs = await self.get_recommended_jobs()
                if rec_jobs:
                    print(f"\n  📋 Recommended 共 {len(rec_jobs)} 个职位，开始逐个处理...", flush=True)
                    for job in rec_jobs:
                        await self.process_job(job, stat)
                        human_delay(DELAY_MIN, DELAY_MAX)
                else:
                    print("  ℹ️  Recommended 列表为空或无法抓取", flush=True)

                # 来源切换提示
                print("\n" + "★" * 60)
                print("★  切换来源：Saved searches（保存的搜索）")
                print("★" * 60, flush=True)

                # ── 来源2：Saved searches ──────────────────────────────────────────
                saved_jobs = await self.get_saved_search_jobs()
                if saved_jobs:
                    print(f"\n  📋 Saved searches 共 {len(saved_jobs)} 个职位，开始逐个处理...", flush=True)
                    for job in saved_jobs:
                        await self.process_job(job, stat)
                        human_delay(DELAY_MIN, DELAY_MAX)
                else:
                    print("  ℹ️  Saved searches 列表为空或无法抓取", flush=True)

                # ── 总汇总 ──────────────────────────────────────────────────────────
                skipped_total = stat["reject"] + stat["dup"] + stat.get("no_apply_btn", 0)
                print("\n" + "█" * 60)
                print("📊 全部来源处理完毕 —— 总汇总")
                print("█" * 60)
                print(f"  共检查:  {stat['checked']} 个职位")
                print(f"  ✅ 申请:  {stat['applied']} 个")
                print(f"  ⏭️  跳过:  {skipped_total} 个"
                      f"（不符合:{stat['reject']} / 已记录:{stat['dup']} / 无按钮:{stat.get('no_apply_btn',0)}）")
                print(f"  ⚠️  失败:  {stat['fail']} 个")
                print(f"\n  📁 记录文件: {APPLIED_JOBS_FILE}", flush=True)

                # 已申请列表
                applied_list = [j for j in self.applied_data["jobs"] if j.get("status") == "applied"]
                if applied_list:
                    print(f"\n  📋 已申请职位列表（共 {len(applied_list)} 个）：")
                    for j in applied_list:
                        print(f"  • {j['company']} | {j['position']} [{j.get('source','')}] ({j['recorded_at']})")

            except KeyboardInterrupt:
                print("\n⚠️ 用户中断，保存当前进度...", flush=True)
                save_applied_jobs(self.applied_data)

            finally:
                # 无论如何都导出 CSV
                try:
                    save_applied_jobs(self.applied_data)
                    csv_path = export_applications_csv(self.applied_data)
                    print(f"\n📑 最终统计 CSV 已生成: {csv_path}", flush=True)
                except Exception as e:
                    print(f"[WARN] 导出 CSV 失败: {e}", flush=True)
                if self.connected_cdp:
                    print("\n🔚 CDP 模式：保留你的 Chrome 不动（脚本退出即自动断开连接）", flush=True)
                else:
                    print("\n🔚 关闭浏览器...", flush=True)
                    try:
                        await self.context.close()
                    except Exception:
                        pass


# ─── 命令行入口 ────────────────────────────────────────────────────────────────────

def _build_arg_parser():
    """
    构建命令行参数解析器。

    OpenRouter key 优先级：--openrouter-key > 环境变量 OPENROUTER_API_KEY（含 .env）。
    用于验证职位的文本/多模态模型，以及 openrouter 方式下的 UI-TARS。

    UI-TARS 提供方式（--uitars-provider）：
      openrouter（默认）：UI-TARS 走 OpenRouter
      remote            ：走 Kaggle/Colab 等 OpenAI 兼容 endpoint（x-api-key 鉴权）
      local             ：本地推理（暂未实现，优雅跳过）

    用法示例：
      python jobsdb_apply.py
      python jobsdb_apply.py --openrouter-key sk-or-v1-xxx
      python jobsdb_apply.py --uitars-provider remote \\
          --uitars-endpoint https://xxxx.ngrok.io/v1/chat/completions \\
          --uitars-key my-key
    """
    import argparse
    parser = argparse.ArgumentParser(
        description="JobsDB (hk.jobsdb.com) 自动投递脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--openrouter-key", default=None,
        help="OpenRouter API key（优先级高于环境变量 / .env）。",
    )
    parser.add_argument(
        "--uitars-provider", choices=["openrouter", "remote", "local"], default="openrouter",
        help="UI-TARS 模型提供方式（默认: openrouter）。",
    )
    parser.add_argument(
        "--uitars-endpoint", default=None,
        help="remote 方式下 UI-TARS 的完整 URL。选 remote 时必填。",
    )
    parser.add_argument(
        "--uitars-key", default=None,
        help="remote 方式下 UI-TARS endpoint 的鉴权 key（x-api-key header）。",
    )
    parser.add_argument(
        "--uitars-local-url", default=UITARS_LOCAL_URL,
        help=f"local 方式 llama-cpp-python server 地址（/v1 前缀）。默认: {UITARS_LOCAL_URL}。示例：http://192.168.3.14:8000/v1",
    )
    parser.add_argument(
        "--uitars-local-model", default=None,
        help="local 方式模型名称（GGUF 路径）。默认 None → 自动从 /v1/models 取第一个。",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="试运行：登录+遍历+筛选+判断+打印，但不点Apply/不填表单/不记录，安全验证筛选逻辑。",
    )
    parser.add_argument(
        "--cdp-url", default=None,
        help="连接已运行的真实 Chrome（CDP），绕过 Cloudflare。需先用 "
             "--remote-debugging-port=9222 启动 Chrome 并手动通过验证+登录。如 http://127.0.0.1:9222",
    )
    return parser


def main():
    """解析命令行参数，启动自动投递。"""
    global OPENROUTER_API_KEY, UITARS_PROVIDER, UITARS_ENDPOINT, UITARS_KEY

    # 需要同步到被 import 的 zhipin_apply 模块的全局变量
    import zhipin_apply as _za

    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.openrouter_key:
        OPENROUTER_API_KEY = args.openrouter_key
        _za.OPENROUTER_API_KEY = args.openrouter_key  # 同步给被复用的函数

    UITARS_PROVIDER = args.uitars_provider
    _za.UITARS_PROVIDER = args.uitars_provider

    if args.uitars_key:
        UITARS_KEY = args.uitars_key
        _za.UITARS_KEY = args.uitars_key

    if args.uitars_endpoint:
        UITARS_ENDPOINT = args.uitars_endpoint
        _za.UITARS_ENDPOINT = args.uitars_endpoint

    if args.uitars_local_url:
        _za.UITARS_LOCAL_URL = args.uitars_local_url
    if args.uitars_local_model:
        _za.UITARS_LOCAL_MODEL = args.uitars_local_model

    if UITARS_PROVIDER == "remote" and not UITARS_ENDPOINT:
        parser.error("--uitars-provider remote 需要同时指定 --uitars-endpoint")

    if UITARS_PROVIDER == "local":
        print(f"⚙️ UI-TARS 提供方式: local | server: {args.uitars_local_url}", flush=True)
    elif UITARS_PROVIDER == "remote":
        print(f"⚙️ UI-TARS 提供方式: remote | endpoint: {UITARS_ENDPOINT}", flush=True)
    else:
        print(f"⚙️ UI-TARS 提供方式: openrouter", flush=True)

    if args.dry_run:
        print("🧪 dry-run 试运行：登录+遍历+筛选+判断，不实际申请", flush=True)

    automator = JobsDBAutomator(dry_run=args.dry_run)
    if args.cdp_url:
        automator.cdp_url = args.cdp_url
    asyncio.run(automator.run())


if __name__ == "__main__":
    main()
