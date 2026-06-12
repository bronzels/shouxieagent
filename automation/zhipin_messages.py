# -*- coding: utf-8 -*-
"""
Boss直聘「消息状态扫描 + 按需发简历」脚本
================================================================================
功能概述
--------
打开 Boss直聘 极客端「消息」聊天页，遍历「全部」会话，识别每个会话里对方
(BOSS/招聘者) 对我的招呼的处理状态，按【公司+职位】记录到 message_status.json：

  1. 未读   (对方还没看我的招呼)                 → upsert_status(..., "unread")
  2. 已读不回 (对方看了但没回复)                  → upsert_status(..., "read_noreply")
  3. 回复拒绝 (对方回复了拒绝类话术)              → upsert_status(..., "rejected")
  4. 回复索要简历 (对方回复要简历)               → upsert_status(..., "asked_resume")
       然后【发送简历】：
       - 默认发中文在线简历（账号已上传的"刘先生"开头中文版）
       - 若对方明确要英文简历(English/英文简历) → 发英文在线简历
       - 发送成功后 upsert_status(..., "resume_sent", note="已发中文/英文简历")

复用策略（不复制现有代码，直接 import zhipin_apply 的模块级函数 / 工具）：
  - call_uitars / parse_uitars_action / execute_action_on_page  —— UI-TARS 视觉兜底
  - _post_openrouter                                            —— 纯文本免费模型判定回复意图
  - image_to_base64 / screenshot_page / human_delay            —— 截图 / 人类化延迟
  - human_mouse_move_and_click                                 —— 人类化鼠标点击
  - VERIFY_MODELS_TEXT / OPENROUTER 配置                       —— 免费模型 fallback 链
  - 浏览器启动做法（rebrowser-playwright + 持久化 chrome_profile）—— 本文件复用同样的
    launch_persistent_context 参数，复用同一个已登录 chrome_profile，无需重新扫码。
  - zhipin_status：load_status / upsert_status / save_status   —— 写入对方回应状态

⚠️ 开发说明：本脚本涉及发送真实消息（发简历），开发阶段只做编译验证，不实际运行浏览器、
            不真发消息。调试由主人稍后逐个进行。代码中所有"待调试确认"的选择器 / URL /
            判断逻辑均以最佳猜测实现并以  # TODO[调试确认]  标注。
"""

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# ─── 从 .env 文件加载环境变量（如果存在），与主脚本一致 ────────────────────────
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# 使用 rebrowser-playwright（与主脚本一致）：修补了 CDP Runtime.enable 指纹泄露的
# Playwright 分支。原版 Playwright 会被 Boss直聘反爬 JS 检测并跳转 about:blank。
from rebrowser_playwright.async_api import async_playwright, Page  # noqa: E402

# 复用同目录的现有模块（直接 import，避免复制代码）。
# zhipin_apply.py / zhipin_status.py 与本文件同级，确保能 import。
sys.path.insert(0, str(Path(__file__).parent))
import zhipin_apply as za       # noqa: E402  浏览器/UI-TARS/OpenRouter 工具复用
import zhipin_status            # noqa: E402  对方回应状态记录契约


# ─── 配置 ─────────────────────────────────────────────────────────────────────

# 极客端聊天页 URL。
# TODO[调试确认]：以下为最佳猜测，实际以浏览器跳转后的真实地址为准。
#   常见两种：
#     https://www.zhipin.com/web/geek/chat   （较新版极客端聊天）
#     https://www.zhipin.com/web/chat         （旧版/通用聊天）
CHAT_URL_CANDIDATES = [
    "https://www.zhipin.com/web/geek/chat",   # TODO[调试确认] 首选
    "https://www.zhipin.com/web/chat",        # TODO[调试确认] 备选
]

# 本任务来源标识（写入 message_status.json 的 task_source 字段，便于溯源）
TASK_SOURCE = "zhipin_messages"

# 简历版本标识
RESUME_CN = "cn"   # 中文在线简历（"刘先生"开头中文版，默认）
RESUME_EN = "en"   # 英文在线简历

# 单次扫描最多处理的会话数（防止一次跑太久，可按需调大）
MAX_CONVERSATIONS = 200


# ─── 选择器集中区（全部为最佳猜测，待调试确认）──────────────────────────────────
# 把"待调试确认"的选择器集中在此，方便主人调试时统一修改。
# TODO[调试确认]：以下选择器均为根据 Boss直聘极客端历史 DOM 结构的最佳猜测，
#                 实际运行时需用浏览器 DevTools 核对并修正。
SEL = {
    # 「全部」会话标签（消息列表顶部的过滤标签：全部/沟通中/新招呼...）
    "tab_all": [
        "[class*='chat-label'] >> text=全部",
        "li:has-text('全部')",
        "[class*='label-item']:has-text('全部')",
    ],
    # 会话列表项（左侧每一条会话）
    "conv_items": [
        ".user-list li",
        "[class*='conversation'] li",
        ".chat-user-list li",
        "[role='listitem']",
    ],
    # 会话项内：公司名
    "conv_company": [
        ".name-box .name-text",   # 有时显示对方姓名@公司
        "[class*='company']",
        ".company",
    ],
    # 会话项内：职位名
    "conv_position": [
        "[class*='source-job']",
        "[class*='job-name']",
        ".position",
    ],
    # 会话项内：最后一条消息预览
    "conv_preview": [
        "[class*='last-msg']",
        ".gray .push-text",
        ".message-text",
    ],
    # 会话项内：未读红点 / 未读数徽标
    "conv_badge": [
        "[class*='badge-count']",
        ".badge",
        "[class*='unread']",
    ],
    # 进入会话后右侧聊天窗口的标题区（含对方公司+职位）
    "chat_title_company": [
        "[class*='figure'] [class*='name']",
        ".chat-title .name",
    ],
    "chat_title_position": [
        "[class*='chat-title'] [class*='job']",
        ".chat-title .job-name",
    ],
    # 聊天消息气泡：对方(BOSS)发的消息（用于判断是否已回复 + 取最后一条文本）
    # Boss直聘消息气泡一般用 .item-friend(对方) / .item-myself(我) 区分。
    "msg_from_other": [
        ".item-friend .text",
        "[class*='message'][class*='friend'] .text",
        ".chat-message .friend",
    ],
    # 聊天消息气泡：我发的消息
    "msg_from_me": [
        ".item-myself .text",
        "[class*='message'][class*='myself'] .text",
    ],
    # 「发送简历」入口按钮（聊天窗口工具栏 / 快捷操作里）
    "send_resume_btn": [
        "[class*='toolbar'] >> text=发送简历",
        "span:has-text('发送简历')",
        "button:has-text('发送简历')",
        "[class*='resume']:has-text('简历')",
    ],
    # 简历选择弹窗里：中文简历选项
    "resume_option_cn": [
        "[class*='resume-item']:has-text('刘先生')",
        "[class*='resume-list'] li:has-text('中文')",
    ],
    # 简历选择弹窗里：英文简历选项
    "resume_option_en": [
        "[class*='resume-item']:has-text('English')",
        "[class*='resume-list'] li:has-text('英文')",
    ],
    # 简历选择弹窗里：确认发送按钮
    "resume_confirm": [
        "[class*='dialog'] button:has-text('发送')",
        "button:has-text('确定')",
        "[class*='resume'] .btn-confirm",
    ],
}


# ─── 回复意图分类（纯文本免费模型，复用 _post_openrouter）─────────────────────────

CLASSIFY_PROMPT = """你是招聘聊天意图分类助手。下面是招聘方(BOSS)在Boss直聘上回复求职者的最后一条/最近几条消息。
请判断招聘方的意图，只能从以下三类里选一个：

- rejected     ：明确拒绝/婉拒，例如"不合适""已招到""暂不考虑""不太匹配""谢谢您的关注但..."等
- asked_resume ：希望求职者发简历，例如"方便发份简历吗""发个简历看看""把简历发我看下""投个简历"等
- other        ：其他（普通寒暄、约时间面试、问问题、要联系方式等，既非拒绝也非索要简历）

招聘方消息内容：
\"\"\"
{text}
\"\"\"

只输出一个词（rejected / asked_resume / other），不要任何解释。"""


async def classify_reply(text: str) -> str:
    """
    用纯文本免费模型判断招聘方回复意图，返回 'rejected' / 'asked_resume' / 'other'。
    复用 zhipin_apply._post_openrouter + VERIFY_MODELS_TEXT 免费模型 fallback 链。
    解析失败/异常时保守返回 'other'（不误判为拒绝，也不误发简历）。
    """
    text = (text or "").strip()
    if not text:
        return "other"
    payload = {
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": CLASSIFY_PROMPT.format(text=text[:1200])},
        ]}],
        "max_tokens": 16,
    }
    try:
        result = await za._post_openrouter(payload, models=za.VERIFY_MODELS_TEXT)
        ans = (result["choices"][0]["message"]["content"] or "").lower()
    except Exception as e:
        print(f"  [WARN] 回复意图分类失败，按 other 处理: {e}", flush=True)
        return "other"
    # 稳健解析：命中关键词即归类，优先级 asked_resume > rejected > other
    if "asked_resume" in ans or "简历" in ans:
        return "asked_resume"
    if "rejected" in ans or "拒绝" in ans:
        return "rejected"
    return "other"


def wants_english_resume(text: str) -> bool:
    """
    根据对方消息文本判断是否明确要英文简历。
    命中 English / 英文简历 / 英文版 等关键词 → True，否则 False（默认发中文）。
    """
    t = (text or "").lower()
    if "english" in t:
        return True
    raw = text or ""
    for kw in ("英文简历", "英文版", "英文的简历", "英文 cv", "english cv", "英文cv"):
        if kw.lower() in t or kw in raw:
            return True
    return False


# ─── 主扫描器 ─────────────────────────────────────────────────────────────────

class ZhipinMessageScanner:
    """
    Boss直聘消息状态扫描器。
    复用 zhipin_apply 的浏览器启动做法（持久化 chrome_profile，复用已登录态）。
    """

    def __init__(self, export_csv: bool = False):
        self.status_data = zhipin_status.load_status()
        self.page: Page = None
        self.context = None
        self.viewport_width = 1280
        self.viewport_height = 800
        self.export_csv = export_csv
        # 本次扫描每条会话的结果（用于可选 CSV 导出）
        self.scan_rows: list[dict] = []

    # ── 浏览器：复用主脚本同样的持久化 chrome_profile 做法 ──────────────────────
    async def start_browser(self, playwright):
        """
        启动浏览器（有头模式），复用与 zhipin_apply.BossZhipinAutomator.start_browser
        完全一致的 launch_persistent_context 参数：复用同一个已登录的 chrome_profile，
        无需重新扫码。
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
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self.context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

    async def _is_logged_in(self) -> bool:
        """
        判断是否已登录：聊天页若未登录会被重定向到登录页(/web/user)或首页出现"登录/注册"。
        """
        try:
            if "/web/user" in self.page.url:
                return False
            login_link = await self.page.query_selector("a:has-text('登录/注册')")
            if login_link and await login_link.is_visible():
                return False
            return True
        except Exception:
            return False

    # ── 鲁棒点击：复用主脚本的 _click_smart 思路（选择器优先 + UI-TARS 兜底）─────
    async def click_smart(self, selectors: list[str], uitars_instruction: str,
                          shot_name: str, require_text: str = None) -> bool:
        """
        混合点击：先依次尝试选择器命中可见元素并人类化点击（复用 za.human_mouse_move_and_click），
        全部失败则截图交给 UI-TARS 视觉定位（复用 za.call_uitars / parse_uitars_action /
        execute_action_on_page）。与 zhipin_apply.BossZhipinAutomator._click_smart 等价，
        因该方法是实例方法不便直接 import，这里复用其底层模块级函数实现等价逻辑。
        """
        # 阶段1：选择器
        for sel in selectors:
            try:
                els = await self.page.query_selector_all(sel)
                for el in els:
                    if not await el.is_visible():
                        continue
                    if require_text is not None:
                        t = (await el.text_content() or "").strip()
                        if t != require_text:
                            continue
                    bb = await el.bounding_box()
                    if bb:
                        await za.human_mouse_move_and_click(
                            self.page,
                            int(bb["x"] + bb["width"] / 2),
                            int(bb["y"] + bb["height"] / 2),
                        )
                    else:
                        await el.click()
                    return True
            except Exception:
                continue

        # 阶段2：UI-TARS 视觉兜底
        print(f"  🔎 选择器未命中，改用 UI-TARS 视觉定位: {shot_name}", flush=True)
        try:
            shot = await za.screenshot_page(self.page, shot_name)
            resp = await za.call_uitars(shot, uitars_instruction)
            action = za.parse_uitars_action(
                resp, self.page.viewport_size["width"], self.page.viewport_size["height"]
            )
            if action and action.get("action_type") in ("click", "left_single"):
                await za.execute_action_on_page(self.page, action)
                return True
            print(f"  [WARN] UI-TARS 未返回有效点击动作: {resp[:120]}", flush=True)
        except Exception as e:
            print(f"  [WARN] UI-TARS 兜底失败: {e}", flush=True)
        return False

    async def _first_text(self, root, selectors: list[str]) -> str:
        """在 root(ElementHandle) 范围内依次尝试选择器，返回第一个命中元素的文本。"""
        for sel in selectors:
            try:
                el = await root.query_selector(sel)
                if el:
                    t = (await el.text_content() or "").strip()
                    if t:
                        return t
            except Exception:
                continue
        return ""

    # ── 打开聊天页 ──────────────────────────────────────────────────────────────
    async def open_chat_page(self) -> bool:
        """
        打开极客端聊天页（消息列表）。依次尝试候选 URL，命中会话列表即成功。
        TODO[调试确认]：CHAT_URL_CANDIDATES 与会话列表选择器 SEL['conv_items'] 待核对。
        """
        for url in CHAT_URL_CANDIDATES:
            print(f"💬 打开聊天页: {url}", flush=True)
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                za.human_delay(3.0, 5.0)
            except Exception as e:
                print(f"  [WARN] 打开 {url} 失败: {e}", flush=True)
                continue

            if not await self._is_logged_in():
                print("  ⚠️ 未检测到登录态。请先用 zhipin_apply.py 扫码登录"
                      "（登录态保存在 automation/chrome_profile）。", flush=True)
                return False

            # 等待会话列表渲染
            for sel in SEL["conv_items"]:
                try:
                    await self.page.wait_for_selector(sel, timeout=6000)
                    n = len(await self.page.query_selector_all(sel))
                    if n > 0:
                        print(f"  ✅ 聊天页就绪，发现 {n} 条会话项 (selector={sel})", flush=True)
                        return True
                except Exception:
                    continue
            print(f"  [WARN] {url} 未发现会话列表，尝试下一个候选 URL", flush=True)
        print("  ❌ 所有候选聊天页 URL 都未能加载出会话列表（待调试确认 URL/选择器）", flush=True)
        return False

    async def click_tab_all(self):
        """
        点「全部」标签，确保遍历所有会话。
        TODO[调试确认]：SEL['tab_all'] 选择器与是否需要点（默认可能已是全部）待核对。
        """
        ok = await self.click_smart(
            SEL["tab_all"],
            "在消息列表顶部的过滤标签栏里，找到并点击'全部'这个标签。",
            "msg_tab_all.png",
            require_text=None,
        )
        if ok:
            print("  ✅ 已切换到'全部'会话标签", flush=True)
        else:
            print("  ℹ️ 未显式点到'全部'标签（可能默认就是全部），继续遍历", flush=True)
        za.human_delay(1.0, 2.0)

    # ── 单条会话状态识别 ────────────────────────────────────────────────────────
    async def _get_conversation_handles(self) -> list:
        """获取当前会话列表项的 ElementHandle 列表（用首个命中的选择器）。"""
        for sel in SEL["conv_items"]:
            try:
                els = await self.page.query_selector_all(sel)
                if els:
                    return els
            except Exception:
                continue
        return []

    async def _has_unread_badge(self, item) -> bool:
        """会话项是否有未读红点/未读数。命中可见徽标 → True。"""
        for sel in SEL["conv_badge"]:
            try:
                el = await item.query_selector(sel)
                if el and await el.is_visible():
                    return True
            except Exception:
                continue
        return False

    async def _extract_other_last_messages(self) -> tuple[bool, str]:
        """
        进入会话后，提取对方(BOSS)发的消息。
        返回 (对方是否有回复, 对方最后消息文本拼接)。
        - 若找不到任何对方气泡 → (False, "")，即"只有我发的招呼" → read_noreply。
        TODO[调试确认]：msg_from_other 选择器（区分对方/我）待核对。
        """
        texts: list[str] = []
        for sel in SEL["msg_from_other"]:
            try:
                els = await self.page.query_selector_all(sel)
                for el in els:
                    t = (await el.text_content() or "").strip()
                    if t:
                        texts.append(t)
                if texts:
                    break
            except Exception:
                continue
        if not texts:
            return False, ""
        # 取最后若干条对方消息（最多 3 条）拼接，供意图分类
        tail = texts[-3:]
        return True, " ".join(tail)

    async def _read_chat_company_position(self, fallback_company: str,
                                           fallback_position: str) -> tuple[str, str]:
        """
        进入会话后从聊天窗口标题区读取公司名/职位名；读不到则用会话列表项的兜底值。
        TODO[调试确认]：chat_title_company / chat_title_position 选择器待核对。
        """
        company, position = fallback_company, fallback_position
        # _first_text 接受 ElementHandle 或 page 均可 query_selector
        try:
            c = await self._first_text(self.page, SEL["chat_title_company"])
            p = await self._first_text(self.page, SEL["chat_title_position"])
            if c:
                company = c
            if p:
                position = p
        except Exception:
            pass
        return company or fallback_company, position or fallback_position

    # ── 发送简历 ────────────────────────────────────────────────────────────────
    async def send_resume(self, version: str) -> bool:
        """
        在当前已打开的会话窗口里发送在线简历。
        version: RESUME_CN(中文,默认) / RESUME_EN(英文)。
        流程：点"发送简历"入口 → 简历选择弹窗里选对应版本 → 确认发送。
        用 click_smart（选择器优先 + UI-TARS 视觉兜底）定位各按钮。

        ⚠️ 这是发送真实消息的动作。开发阶段绝不调用运行；调试由主人逐个进行。
        TODO[调试确认]：send_resume_btn / resume_option_* / resume_confirm 选择器，
                        以及"发送简历"是否会先弹简历选择、是否需要二次确认，均待核对。
        """
        ver_name = "英文" if version == RESUME_EN else "中文"
        print(f"  📄 准备发送【{ver_name}】在线简历...", flush=True)

        # 1) 点"发送简历"入口
        ok = await self.click_smart(
            SEL["send_resume_btn"],
            "在聊天输入框上方/旁边的工具栏里，找到并点击'发送简历'按钮。",
            "send_resume_entry.png",
        )
        if not ok:
            print("  [WARN] 未找到'发送简历'入口按钮（待调试确认选择器）", flush=True)
            return False
        za.human_delay(1.5, 2.5)

        # 2) 简历选择弹窗里选对应版本
        option_selectors = SEL["resume_option_en"] if version == RESUME_EN else SEL["resume_option_cn"]
        instruction = (
            "在弹出的简历选择列表里，找到并点击英文版简历(English/英文)。"
            if version == RESUME_EN else
            "在弹出的简历选择列表里，找到并点击中文版简历（'刘先生'开头的中文简历）。"
        )
        ok = await self.click_smart(option_selectors, instruction, f"resume_pick_{version}.png")
        if not ok:
            # 有些版本可能直接发默认简历、无选择弹窗；记录后仍尝试确认
            print("  [WARN] 未找到简历版本选项（可能无选择弹窗或选择器待确认）", flush=True)
        za.human_delay(1.0, 2.0)

        # 3) 确认发送（若弹窗有确认按钮）
        ok_confirm = await self.click_smart(
            SEL["resume_confirm"],
            "点击简历发送弹窗里的'发送'或'确定'按钮，确认把简历发给对方。",
            f"resume_confirm_{version}.png",
        )
        if not ok_confirm:
            print("  ℹ️ 未点到独立的确认按钮（可能选中即发送），请调试时确认是否已发出", flush=True)
        za.human_delay(1.5, 2.5)
        print(f"  ✅ 已执行发送【{ver_name}】简历动作（实际是否送达需调试时人工确认）", flush=True)
        return True

    # ── 处理单条会话 ────────────────────────────────────────────────────────────
    async def process_conversation(self, index: int) -> dict:
        """
        处理列表中第 index 条会话：
          1) 取公司/职位/预览/未读徽标
          2) 有未读徽标 → unread
          3) 无徽标 → 进入会话，看对方是否有回复：
               - 无对方消息（只有我的招呼）→ read_noreply
               - 有对方消息 → classify_reply 分类：
                   rejected     → rejected
                   asked_resume → asked_resume，然后判断中/英文发简历 → resume_sent
                   other        → 不改变拦截语义；记录为 unread（视为未决，留待人工/重投）
        返回该会话的 scan row（含 company/position/status/note）。
        """
        items = await self._get_conversation_handles()
        if index >= len(items):
            return {}
        item = items[index]

        company = await self._first_text(item, SEL["conv_company"])
        position = await self._first_text(item, SEL["conv_position"])
        preview = await self._first_text(item, SEL["conv_preview"])
        has_badge = await self._has_unread_badge(item)

        label = f"{company or '?'} | {position or '?'}"
        print(f"\n  [{index + 1}] 会话: {label}  预览='{preview[:30]}'  未读={has_badge}", flush=True)

        # 公司/职位缺失时无法可靠 upsert（key 依赖二者），记录后跳过写入
        if not company and not position:
            print("  [WARN] 该会话未能提取公司/职位（待调试确认选择器），跳过状态写入", flush=True)
            return {"company": company, "position": position, "status": "skip",
                    "note": "公司/职位提取失败"}

        # 情况1：未读红点 → unread（对方还没看我的招呼）
        if has_badge:
            zhipin_status.upsert_status(
                self.status_data, company, position, "unread",
                task_source=TASK_SOURCE, note="会话列表有未读红点(对方未看?)",
            )
            print("  → 状态: unread (未读红点)", flush=True)
            return {"company": company, "position": position, "status": "unread", "note": "未读红点"}

        # 情况2/3/4：无红点，需进入会话看对方是否回复
        # 点开会话（用列表项本身点击）
        try:
            await item.scroll_into_view_if_needed()
            za.human_delay(0.4, 0.9)
            await item.click()
            za.human_delay(1.5, 2.8)
        except Exception as e:
            print(f"  [WARN] 打开会话失败: {e}", flush=True)
            return {"company": company, "position": position, "status": "skip",
                    "note": f"打开会话失败:{e}"}

        # 进入会话后尽量用聊天窗标题校正公司/职位（更准确）
        company, position = await self._read_chat_company_position(company, position)

        has_other, other_text = await self._extract_other_last_messages()

        # 情况2：只有我发的招呼、对方无回复 → read_noreply
        if not has_other:
            zhipin_status.upsert_status(
                self.status_data, company, position, "read_noreply",
                task_source=TASK_SOURCE, note="无对方回复(已读不回/未读但无红点)",
            )
            print("  → 状态: read_noreply (对方无回复)", flush=True)
            return {"company": company, "position": position,
                    "status": "read_noreply", "note": "对方无回复"}

        # 对方有回复 → 用纯文本免费模型分类意图
        intent = await classify_reply(other_text)
        print(f"  🤖 对方最后消息='{other_text[:40]}' → 意图={intent}", flush=True)

        # 情况3：拒绝
        if intent == "rejected":
            zhipin_status.upsert_status(
                self.status_data, company, position, "rejected",
                task_source=TASK_SOURCE, note=f"对方拒绝: {other_text[:60]}",
            )
            print("  → 状态: rejected (对方拒绝)", flush=True)
            return {"company": company, "position": position,
                    "status": "rejected", "note": other_text[:60]}

        # 情况4：索要简历 → 先标 asked_resume，再发简历，发后改 resume_sent
        if intent == "asked_resume":
            zhipin_status.upsert_status(
                self.status_data, company, position, "asked_resume",
                task_source=TASK_SOURCE, note=f"对方索要简历: {other_text[:60]}",
            )
            print("  → 状态: asked_resume (对方索要简历)", flush=True)

            # 判断发中文还是英文简历
            want_en = wants_english_resume(other_text)
            version = RESUME_EN if want_en else RESUME_CN
            ver_name = "英文" if want_en else "中文"

            sent = await self.send_resume(version)
            if sent:
                zhipin_status.upsert_status(
                    self.status_data, company, position, "resume_sent",
                    task_source=TASK_SOURCE, note=f"已发{ver_name}简历",
                )
                print(f"  → 状态: resume_sent (已发{ver_name}简历)", flush=True)
                return {"company": company, "position": position,
                        "status": "resume_sent", "note": f"已发{ver_name}简历"}
            else:
                # 发送失败：保留 asked_resume，待下次/人工重试
                print("  [WARN] 发简历未成功，保留 asked_resume 状态待重试", flush=True)
                return {"company": company, "position": position,
                        "status": "asked_resume", "note": "发简历未成功，待重试"}

        # 情况 other：对方回复了但既非拒绝也非索要简历（约面试/寒暄/问问题等）
        # 记为 unread（不进入拦截集合，留待人工处理或后续重投），并在 note 说明。
        zhipin_status.upsert_status(
            self.status_data, company, position, "unread",
            task_source=TASK_SOURCE, note=f"对方有回复但非拒绝/索简历(other): {other_text[:60]}",
        )
        print("  → 状态: unread (对方回复=other，留待人工)", flush=True)
        return {"company": company, "position": position,
                "status": "unread", "note": f"other: {other_text[:60]}"}

    # ── CSV 导出（可选）─────────────────────────────────────────────────────────
    def export_scan_csv(self) -> str:
        """
        把本次扫描的每条会话状态导出为 CSV 到 automation/reports/，文件名含时间。
        复用主脚本 reports 目录与 utf-8-sig（Excel 中文不乱码）的思路。
        """
        import csv
        reports_dir = Path(__file__).parent / "reports"
        reports_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = reports_dir / f"消息状态扫描_{ts}.csv"
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow([f"扫描时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                        f"会话数：{len(self.scan_rows)}"])
            w.writerow(["序号", "公司", "职位", "状态", "备注"])
            for i, r in enumerate(self.scan_rows, 1):
                w.writerow([i, r.get("company", ""), r.get("position", ""),
                            r.get("status", ""), r.get("note", "")])
        return str(path)

    # ── 主流程 ──────────────────────────────────────────────────────────────────
    async def run(self):
        if not za.OPENROUTER_API_KEY:
            raise ValueError(
                "缺少 OPENROUTER_API_KEY！\n"
                "请在 automation/.env 文件中设置 OPENROUTER_API_KEY=sk-or-v1-xxx，"
                "或用 --openrouter-key 传入，或设置环境变量 OPENROUTER_API_KEY。"
            )

        print("\n" + "💬 " * 20)
        print("Boss直聘 消息状态扫描 + 按需发简历 启动")
        print("💬 " * 20 + "\n", flush=True)

        async with async_playwright() as playwright:
            await self.start_browser(playwright)
            try:
                if not await self.open_chat_page():
                    print("❌ 未能打开聊天页/会话列表，终止。", flush=True)
                    return

                await self.click_tab_all()

                # 统计每种状态的数量
                stat = {"unread": 0, "read_noreply": 0, "rejected": 0,
                        "asked_resume": 0, "resume_sent": 0, "skip": 0}

                # 遍历会话。每处理一条后会话列表可能因切换而刷新，故每次重新取 handle。
                total = len(await self._get_conversation_handles())
                total = min(total, MAX_CONVERSATIONS)
                print(f"\n📋 将遍历 {total} 条会话（上限 {MAX_CONVERSATIONS}）", flush=True)

                for idx in range(total):
                    row = await self.process_conversation(idx)
                    if row:
                        self.scan_rows.append(row)
                        st = row.get("status", "skip")
                        if st in stat:
                            stat[st] += 1
                    za.human_delay(0.8, 1.6)

                # 汇总
                print("\n" + "=" * 60)
                print("📊 扫描完成 —— 状态汇总")
                print("=" * 60)
                print(f"  未读 unread        : {stat['unread']}")
                print(f"  已读不回 read_noreply: {stat['read_noreply']}")
                print(f"  拒绝 rejected      : {stat['rejected']}")
                print(f"  索要简历 asked_resume: {stat['asked_resume']}")
                print(f"  已发简历 resume_sent : {stat['resume_sent']}")
                print(f"  跳过 skip          : {stat['skip']}")
                print(f"  📁 状态已写入: {zhipin_status.MESSAGE_STATUS_FILE}", flush=True)

                if self.export_csv:
                    try:
                        csv_path = self.export_scan_csv()
                        print(f"  📑 扫描结果CSV: {csv_path}", flush=True)
                    except Exception as e:
                        print(f"  [WARN] 导出CSV失败: {e}", flush=True)

            except KeyboardInterrupt:
                print("\n⚠️ 用户中断，已写入的状态已保存。", flush=True)
            finally:
                # 状态在每次 upsert 时已即时 save_status，这里再保险保存一次
                try:
                    zhipin_status.save_status(self.status_data)
                except Exception:
                    pass
                print("\n🔚 关闭浏览器...", flush=True)
                try:
                    await self.context.close()
                except Exception:
                    pass


# ─── 入口 ─────────────────────────────────────────────────────────────────────

def _build_arg_parser():
    """
    命令行参数（风格同 zhipin_apply.py）：
      --openrouter-key  OpenRouter API key，优先级高于环境变量/.env。
                        用于回复意图分类的纯文本免费模型，以及 UI-TARS(openrouter方式)。
      --export-csv      额外把本次扫描每条会话状态导出 CSV 到 automation/reports/。
    UI-TARS 提供方式参数与主脚本保持一致（openrouter/remote/local）。
    """
    parser = argparse.ArgumentParser(
        description="Boss直聘 消息状态扫描 + 按需发简历（复用 zhipin_apply 浏览器/UI-TARS 能力）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--openrouter-key", default=None,
        help="OpenRouter API key（优先级高于环境变量 OPENROUTER_API_KEY / .env）。",
    )
    parser.add_argument(
        "--export-csv", action="store_true",
        help="把本次扫描每条会话状态导出为 CSV 到 automation/reports/。",
    )
    # UI-TARS 提供方式（与 zhipin_apply 一致，影响视觉兜底定位按钮的调用路径）
    parser.add_argument(
        "--uitars-provider", choices=["openrouter", "remote", "local"], default="openrouter",
        help="UI-TARS 模型提供方式：openrouter（默认）/ remote（x-api-key 鉴权的兼容 endpoint）/ "
             "local（本地推理，暂未实现）。",
    )
    parser.add_argument(
        "--uitars-endpoint", default=None,
        help="remote 方式下 UI-TARS 的完整 URL。选 remote 时必填。",
    )
    parser.add_argument(
        "--uitars-key", default=None,
        help="remote 方式下 UI-TARS endpoint 的鉴权 key（放 header 的 x-api-key 字段）。",
    )
    parser.add_argument(
        "--uitars-local-url", default=za.UITARS_LOCAL_URL,
        help="local 方式下本地 UI-TARS 推理服务地址（OpenAI 兼容），当前未实现，仅占位。",
    )
    return parser


def main():
    """解析命令行参数，赋值到 zhipin_apply 的模块级全局变量后启动扫描。"""
    parser = _build_arg_parser()
    args = parser.parse_args()

    # OpenRouter key：命令行 > 环境变量/.env（复用 za 模块的全局变量，
    # 这样 _post_openrouter / call_uitars 都会用到最新 key）
    if args.openrouter_key:
        za.OPENROUTER_API_KEY = args.openrouter_key

    # UI-TARS 提供方式：直接写入 za 的全局，复用其 call_uitars 分发逻辑
    za.UITARS_PROVIDER = args.uitars_provider
    za.UITARS_LOCAL_URL = args.uitars_local_url
    if args.uitars_key:
        za.UITARS_KEY = args.uitars_key
    if args.uitars_endpoint:
        za.UITARS_ENDPOINT = args.uitars_endpoint

    if za.UITARS_PROVIDER == "remote" and not za.UITARS_ENDPOINT:
        parser.error("--uitars-provider remote 需要同时指定 --uitars-endpoint")
    if za.UITARS_PROVIDER == "local":
        print("⚠️ 本地 UI-TARS 推理方式尚未实现，视觉兜底将被优雅跳过。", flush=True)

    print(f"⚙️ UI-TARS 提供方式: {za.UITARS_PROVIDER}"
          + (f" | endpoint: {za.UITARS_ENDPOINT}" if za.UITARS_PROVIDER == "remote" else ""),
          flush=True)

    asyncio.run(ZhipinMessageScanner(export_csv=args.export_csv).run())


if __name__ == "__main__":
    main()
