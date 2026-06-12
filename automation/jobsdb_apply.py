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

# 持久化 profile 目录（独立于 zhipin，避免互相污染）
JOBSDB_PROFILE_DIR = Path(__file__).parent / "jobsdb_profile"

APPLIED_JOBS_FILE = Path(__file__).parent / "jobsdb_applied.json"
SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)
REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# 正文太短时视为抓取失败的阈值（英文 JD 字符更少，适当降低）
MIN_DESC_LEN = 60

# 人类操作延迟
DELAY_MIN = 0.8
DELAY_MAX = 1.8
CARD_DELAY_MIN = 1.2
CARD_DELAY_MAX = 2.2
APPLY_DELAY_MIN = 3.0
APPLY_DELAY_MAX = 5.0


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
{desc[:2000]}

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
    def __init__(self):
        self.applied_data = load_applied_jobs()
        self.page: Page = None
        self.context = None
        self.viewport_width = 1280
        self.viewport_height = 900

    # ── 浏览器启动 ────────────────────────────────────────────────────────────────

    async def start_browser(self, playwright):
        """
        启动真实 Chrome + 独立 jobsdb_profile 持久化目录。
        用 rebrowser_playwright 避免反爬指纹检测。
        """
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
        await self.context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

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
        print("🌐 正在打开 JobsDB...", flush=True)
        await self.page.goto("https://hk.jobsdb.com/", wait_until="domcontentloaded", timeout=30000)
        human_delay(3.0, 5.0)

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
            print("  ⚠️ 未找到 Sign in 按钮，请手动检查页面", flush=True)
            # 不直接 return False，允许用户手动操作后继续
            input("  请手动点击登录按钮后按 Enter 继续...")

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
            print("  ⚠️ 未找到邮箱输入框，请手动填入邮箱", flush=True)
            input(f"  请手动填入邮箱 {LOGIN_EMAIL} 后按 Enter 继续...")

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

        # 步骤5：暂停，等用户输入验证码
        print("\n" + "=" * 60)
        print("📧 验证码已发送到邮箱:", LOGIN_EMAIL)
        print("   请查收邮件，找到 JobsDB 发来的验证码（一次性密码 OTP）")
        print("=" * 60, flush=True)
        otp_code = input("  请在此处输入验证码（直接粘贴后回车）: ").strip()

        # 步骤6：填入验证码
        # TODO: 调试时确认 OTP 输入框选择器（可能是多个单字符输入框）
        otp_field = await self.page.query_selector(
            "input[name='otp'], input[type='text'][maxlength='6'], "
            "input[type='number'][maxlength='6'], "
            "[data-automation='otp-input'], "
            "input[autocomplete='one-time-code']"
        )
        if otp_field:
            await otp_field.click()
            human_delay(0.3, 0.7)
            await otp_field.fill(otp_code)
            human_delay(0.5, 1.0)
        else:
            # 可能是多个单字符输入框
            # TODO: 调试时如果是多框，需特殊处理（逐字符填入）
            print("  ⚠️ 未找到单一 OTP 输入框，尝试逐字符输入模式...", flush=True)
            otp_fields = await self.page.query_selector_all(
                "input[maxlength='1'], input[type='tel'][maxlength='1']"
            )
            if otp_fields and len(otp_fields) >= len(otp_code):
                for i, char in enumerate(otp_code):
                    await otp_fields[i].fill(char)
                    human_delay(0.1, 0.3)
            else:
                print("  ⚠️ 无法自动填入验证码，请手动填入", flush=True)
                input("  请手动填入验证码后按 Enter 继续...")

        # 步骤7：提交验证码
        await self._click_smart(
            self.page,
            [
                "button[type='submit']",
                "button:has-text('Verify')",
                "button:has-text('Continue')",
                "button:has-text('Sign in')",
            ],
            "找到提交验证码的按钮（Verify / Continue），点击它完成验证。",
            "jobsdb_verify_btn.png",
        )

        # 步骤8：等待登录完成
        print("  ⏳ 等待登录完成...", flush=True)
        for i in range(24):  # 最多等 2 分钟
            await asyncio.sleep(5)
            if await self._is_logged_in():
                print("✅ 登录成功！", flush=True)
                await screenshot_page(self.page, "jobsdb_logged_in.png")
                return True
            if i % 4 == 3:
                print(f"  ⏳ 仍在等待登录... ({(i+1)*5}秒)", flush=True)

        print("⚠️ 等待登录超时（2分钟）", flush=True)
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

        await self.page.goto("https://hk.jobsdb.com/", wait_until="domcontentloaded", timeout=30000)
        human_delay(3.0, 5.0)
        await screenshot_page(self.page, "jobsdb_recommended_page.png")

        # 滚动触发懒加载
        for _ in range(3):
            await self.page.mouse.wheel(0, 600)
            human_delay(1.0, 2.0)

        jobs = await self._extract_job_cards_from_page("Recommended")
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

        # TODO: 调试时确认实际 URL；先尝试两个候选
        saved_url = None
        for candidate in [
            "https://hk.jobsdb.com/saved-searches",
            "https://hk.jobsdb.com/profile/saved-searches",
            "https://hk.jobsdb.com/my-activity/saved-searches",
        ]:
            try:
                await self.page.goto(candidate, wait_until="domcontentloaded", timeout=15000)
                human_delay(2.0, 3.0)
                # 简单判断是否正确跳转（非 404 / 非重定向回首页）
                if "saved" in self.page.url.lower() or "search" in self.page.url.lower():
                    saved_url = candidate
                    break
                # 也检查页面内容是否包含 saved search 相关关键词
                content = await self.page.content()
                if "saved search" in content.lower() or "saved-search" in content.lower():
                    saved_url = candidate
                    break
            except Exception:
                continue

        if not saved_url:
            # 降级：通过首页导航菜单找 saved searches 入口
            print("  ⚠️ 直接 URL 导航失败，尝试通过导航菜单进入 Saved searches...", flush=True)
            await self.page.goto("https://hk.jobsdb.com/", wait_until="domcontentloaded", timeout=30000)
            human_delay(2.0, 3.0)
            clicked = await self._click_smart(
                self.page,
                [
                    "a:has-text('Saved searches')",
                    "[data-automation='saved-searches-link']",
                    "a[href*='saved-search']",
                ],
                "找到导航菜单中的 'Saved searches' 链接，点击它。",
                "jobsdb_nav_saved.png",
            )
            if not clicked:
                print("  ❌ 无法进入 Saved searches，跳过此来源", flush=True)
                return []
            human_delay(2.0, 3.5)

        await screenshot_page(self.page, "jobsdb_saved_searches_page.png")

        # 可能有多个保存的搜索，逐个抓取
        all_jobs = []

        # TODO: 调试时确认各个保存搜索的展开方式
        # 方案A：每个保存搜索是一个可点击项，点击后展示结果列表
        # 方案B：页面直接列出所有匹配职位
        # 当前先尝试直接从页面提取职位卡片
        jobs = await self._extract_job_cards_from_page("Saved searches")
        all_jobs.extend(jobs)

        # 如果页面是保存搜索的"管理"页而非结果页，需要逐个点击搜索项
        if not all_jobs:
            print("  ℹ️  当前页可能是搜索管理页，尝试点击各保存搜索项...", flush=True)
            search_items = await self.page.query_selector_all(
                "[data-automation='saved-search-item'], "
                ".saved-search-item, "
                "li[class*='saved'], "
                "a[href*='saved-search']"
            )
            for item in search_items[:5]:  # 最多处理5个保存搜索
                try:
                    name = (await item.text_content() or "搜索项").strip()[:30]
                    print(f"  🔍 展开保存搜索: {name}", flush=True)
                    await item.click()
                    human_delay(2.0, 3.0)
                    batch = await self._extract_job_cards_from_page(f"Saved:{name}")
                    all_jobs.extend(batch)
                    await self.page.go_back()
                    human_delay(1.5, 2.5)
                except Exception as e:
                    print(f"  [WARN] 展开保存搜索失败: {e}", flush=True)

        print(f"  ✅ 保存搜索共抓取 {len(all_jobs)} 个职位", flush=True)
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
            await self.page.goto(detail_url, wait_until="domcontentloaded", timeout=20000)
            human_delay(2.0, 3.5)
            for sel in [
                "[data-automation='jobDescription']",
                "[data-automation='job-description']",
                ".job-description",
                "[class*='JobDescription']",
                "[class*='job-detail']",
                "section[class*='description']",
                "div[id*='description']",
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
        填写申请表单。JobsDB apply 流程通常分多步：
          Step 1: 简历选择（已有上传的简历，直接 Continue）
          Step 2: Cover Letter 选择 → 选"不附/No cover letter"
          Step 3: 薪资要求 → 填写计算好的金额
          Step 4: 其他问题（可能有额外问卷）→ 尽力填写，不确定时暂停
          Step 5: 最终提交

        因为没有真实运行浏览器，以下选择器均为最佳猜测 + TODO 标注。

        TODO 清单（调试时逐一核实）：
          1. Apply 按钮弹出的是新页面/新 tab 还是模态框（modal）？
          2. 简历步骤：是否需要手动选择简历？选择器？
          3. Cover letter 选项：
             - "No cover letter" / "Don't include a cover letter"
             - 可能是 radio button 或 dropdown
          4. 薪资输入框：
             - 是 input[type='number'] 还是 input[type='text']？
             - 是否有"per month"/"per annum"单位选择？
             - TODO: 确认单位（月薪/年薪）
          5. 其他问题：因职位而异，无法预先列举全部选择器
          6. 最终"Submit"/"Send Application"按钮选择器
        """
        salary_to_fill = parse_salary_fill(job.get("salary", ""))
        print(f"  💰 薪资填写: {salary_to_fill} HKD/月（来源: {job.get('salary', '无范围→默认40K')}）",
              flush=True)

        # ── Step 1: 等待申请表单弹出 ──────────────────────────────────────────────
        # TODO: 确认 apply 后是模态框还是跳转新页面
        human_delay(2.0, 3.5)
        await screenshot_page(self.page, f"jobsdb_apply_form_start_{self._safe_name(job)}.png")

        # ── Step 2: 简历步骤 ───────────────────────────────────────────────────────
        # TODO: 选择已上传的简历（通常列表中已有，直接 Continue）
        resume_continue = await self._click_smart(
            self.page,
            [
                "button:has-text('Continue')",
                "button:has-text('Next')",
                "[data-automation='continue-button']",
            ],
            "找到申请表单第一步的 Continue 或 Next 按钮，点击它继续。",
            f"jobsdb_resume_step_{self._safe_name(job)}.png",
        )
        if resume_continue:
            human_delay(1.5, 2.5)

        # ── Step 3: Cover Letter 选"无/不附" ─────────────────────────────────────
        # TODO: 调试时确认 "No cover letter" 选项的实际选择器和文本
        cover_letter_no = await self._click_smart(
            self.page,
            [
                # radio / button 类型
                "input[type='radio'][value*='no' i]",
                "label:has-text('No cover letter')",
                "label:has-text('Don\\'t include')",
                "label:has-text('No, thanks')",
                "button:has-text('No cover letter')",
                "span:has-text('No cover letter')",
                # 下拉框中的选项
                "option:has-text('No cover letter')",
                "option[value*='none' i]",
                "[data-automation='no-cover-letter']",
            ],
            "在 Cover Letter 选择区域，找到并点击 'No cover letter' 或 '不附申请书' 选项。",
            f"jobsdb_cover_letter_{self._safe_name(job)}.png",
        )
        if not cover_letter_no:
            # 如果界面复杂，暂停请用户确认
            # TODO: 调试阶段这里可能需要频繁手动介入
            print("  ⚠️ [TODO] 未能自动选择 No cover letter，"
                  "请手动选择后按 Enter 继续...", flush=True)
            await screenshot_page(self.page, f"jobsdb_cover_letter_manual_{self._safe_name(job)}.png")
            user_action = input("  已手动处理 cover letter？输入 'ok' 继续 / 'skip' 跳过此职位: ").strip().lower()
            if user_action != "ok":
                return False
        else:
            human_delay(1.0, 2.0)

        await self._click_smart(
            self.page,
            ["button:has-text('Continue')", "button:has-text('Next')",
             "[data-automation='continue-button']"],
            "找到 Continue 或 Next 按钮，进入下一步。",
            f"jobsdb_after_cover_{self._safe_name(job)}.png",
        )
        human_delay(1.5, 2.5)

        # ── Step 4: 薪资填写 ────────────────────────────────────────────────────────
        # TODO: 调试时确认薪资输入框的实际选择器和单位
        salary_input = await self.page.query_selector(
            "input[data-automation='salary-input'], "
            "input[name*='salary' i], "
            "input[placeholder*='salary' i], "
            "input[type='number'][name*='expect' i], "
            "input[aria-label*='salary' i]"
        )
        if salary_input and await salary_input.is_visible():
            await salary_input.click()
            human_delay(0.3, 0.7)
            await salary_input.triple_click()  # 清除原有内容
            await salary_input.type(str(salary_to_fill), delay=random.randint(50, 120))
            human_delay(0.5, 1.0)
            print(f"  ✅ 已填入薪资: {salary_to_fill}", flush=True)
        else:
            # TODO: 薪资字段可能出现在不同步骤，或有单位下拉框
            print(f"  ⚠️ [TODO] 未找到薪资输入框，请手动填入 {salary_to_fill} 后按 Enter 继续...",
                  flush=True)
            await screenshot_page(self.page, f"jobsdb_salary_manual_{self._safe_name(job)}.png")
            input("  已手动填入薪资？按 Enter 继续... ")

        # ── Step 5: 其他问题（因职位而异）────────────────────────────────────────────
        # TODO: 可能有 "Are you eligible to work in HK?" 等问题
        # 当前策略：截图后暂停让用户处理，或自动回答常见题
        # 常见问题自动处理：
        await self._handle_additional_questions(job)

        await self._click_smart(
            self.page,
            ["button:has-text('Continue')", "button:has-text('Next')",
             "[data-automation='continue-button']"],
            "找到 Continue 或 Next 按钮，进入薪资后的下一步。",
            f"jobsdb_after_salary_{self._safe_name(job)}.png",
        )
        human_delay(1.5, 2.5)

        # ── Step 6: 最终提交 ────────────────────────────────────────────────────────
        await screenshot_page(self.page, f"jobsdb_before_submit_{self._safe_name(job)}.png")
        submitted = await self._click_smart(
            self.page,
            [
                "button:has-text('Submit application')",
                "button:has-text('Send application')",
                "button:has-text('Submit')",
                "button:has-text('Apply')",
                "[data-automation='submit-button']",
                "[data-automation='send-application']",
            ],
            "找到最终提交申请的按钮（Submit application / Send application），点击它完成申请。",
            f"jobsdb_submit_{self._safe_name(job)}.png",
        )
        if not submitted:
            print("  ⚠️ [TODO] 未找到提交按钮，请手动提交后按 Enter 继续...", flush=True)
            input("  已手动提交？按 Enter 继续... ")
        human_delay(APPLY_DELAY_MIN, APPLY_DELAY_MAX)
        await screenshot_page(self.page, f"jobsdb_after_submit_{self._safe_name(job)}.png")

        # 确认是否提交成功（页面出现 "Application submitted" 字样）
        try:
            content = await self.page.content()
            if any(kw in content.lower() for kw in
                   ["application submitted", "successfully applied", "your application"]):
                print("  ✅ 页面确认申请提交成功", flush=True)
                return True
        except Exception:
            pass

        return submitted

    async def _handle_additional_questions(self, job: dict):
        """
        处理申请表单中的额外问题（因职位不同而异）。
        当前策略：
          - 尝试自动回答已知常见题
          - 遇到不确定的题目，截图 + input() 暂停让用户处理

        TODO: 调试时补充常见问题的自动处理逻辑，例如：
          - "Are you eligible to work in Hong Kong?" → Yes
          - "How many years of experience do you have?" → 需配置
          - "Expected start date" → 近期日期
        """
        # 通用"Yes/是"类问题自动回答
        for label_text in ["Yes", "I am eligible", "Currently residing"]:
            try:
                el = await self.page.query_selector(f"label:has-text('{label_text}')")
                if el and await el.is_visible():
                    await el.click()
                    human_delay(0.3, 0.7)
            except Exception:
                pass

        # 截图记录当前表单状态（调试时有用）
        await screenshot_page(self.page, f"jobsdb_extra_questions_{self._safe_name(job)}.png")

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

        # 若正文仍不足，用截图兜底
        use_image = len(desc) < MIN_DESC_LEN
        shot_path = None
        if use_image:
            print(f"  ⚠️ 正文抓取不足({len(desc)}字)，降级用多模态+截图判断", flush=True)
            shot_path = await screenshot_page(self.page, f"job_{safe}.png")

        # LLM 验证
        try:
            should_apply, reason = await verify_jobsdb(title, desc, shot_path)
        except Exception as e:
            print(f"  [ERROR] LLM 验证失败: {e}", flush=True)
            stat["fail"] += 1
            self._print_progress(stat)
            return "fail"

        verdict = "✅ 投递" if should_apply else "❌ 跳过"
        print(f"  🤖 判断[{verdict}]: {reason[:200].replace(chr(10), ' ')}", flush=True)

        if not should_apply:
            record_job(self.applied_data, company, title, "skipped_reject", source, salary_text)
            stat["reject"] += 1
            self._print_progress(stat)
            return "reject"

        # 检查 Apply 按钮（若无，跳过）
        # 回到职位卡片所在页面（若刚刚打开了详情页）
        # TODO: 调试时确认：打开详情页后是否需要 go_back() 才能点卡片上的 Apply
        apply_btn = None
        for sel in [
            "button:has-text('Apply now')",
            "button:has-text('Quick apply')",
            "button:has-text('Apply')",
            "[data-automation='apply-button']",
            "a:has-text('Apply now')",
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
        help=f"local 方式本地推理地址（暂未实现，占位预留）。默认: {UITARS_LOCAL_URL}",
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

    if UITARS_PROVIDER == "remote" and not UITARS_ENDPOINT:
        parser.error("--uitars-provider remote 需要同时指定 --uitars-endpoint")

    if UITARS_PROVIDER == "local":
        print(f"⚠️ 本地 UI-TARS 推理方式尚未实现，UI-TARS 视觉兜底将被优雅跳过。"
              f"（预留地址: {args.uitars_local_url}）", flush=True)

    print(f"⚙️ UI-TARS 提供方式: {UITARS_PROVIDER}"
          + (f" | endpoint: {UITARS_ENDPOINT}" if UITARS_PROVIDER == "remote" else ""),
          flush=True)

    asyncio.run(JobsDBAutomator().run())


if __name__ == "__main__":
    main()
