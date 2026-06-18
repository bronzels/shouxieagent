# -*- coding: utf-8 -*-
"""
Boss直聘自动投递 - 首页职位Tab专项任务

任务：点击首页「职位」按钮进入职位列表页，遍历以下 tab：
  - 机器学习（处理）
  - 算法工程师（处理）
  - 数据架构师（跳过，不投递）

对每个职位使用混合判断（verify_mixed）：
  - 远程岗 → verify_job_is_it_remote
  - 深圳岗 → verify_llm_sz（从 zhipin_llm_sz import）
  - 两者都不是 → 跳过

复用：BossZhipinAutomator（全部基础设施共享）。
通过注入 verify_fn=verify_mixed 实现定制判断。

注意：Boss直聘首页「职位」按钮及其 tab 选择器以下为最佳猜测，
      需要在调试时用真实浏览器页面确认（搜索 TODO-SELECTOR 标记）。
      所有不确定的选择器都已用 _click_smart（UI-TARS视觉兜底）包装，
      确保即使选择器失效也能通过 UI-TARS 视觉定位正常运行。
"""

import asyncio
import os
from pathlib import Path

# 从 .env 文件加载环境变量（与 zhipin_apply.py 保持一致）
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ─── 复用 zhipin_apply 的核心组件 ─────────────────────────────────────────────
from zhipin_apply import (
    BossZhipinAutomator,
    verify_job_is_it_remote,
    CITY_CODES,
    human_delay,
    human_mouse_move_and_click,
    screenshot_page,
    export_applications_csv,
    save_applied_jobs,
    DELAY_MIN,
    DELAY_MAX,
)

# ─── 复用大模型深圳的判断函数 ─────────────────────────────────────────────────
from zhipin_llm_sz import verify_llm_sz

# ─── 配置 ─────────────────────────────────────────────────────────────────────

SHENZHEN_CITY_CODE = CITY_CODES["深圳"]  # "101280600"

# 要处理的 tab 名称（跳过「数据架构师」）
TABS_TO_PROCESS = ["机器学习", "算法工程师"]
# 明确跳过的 tab
TABS_TO_SKIP = ["数据架构师"]

# 首页职位按钮 URL（Boss直聘职位推荐/列表页，不含搜索关键字）
# TODO-SELECTOR: 需真实浏览器确认此 URL 是否是首页点「职位」后的落地页
ZHIPIN_JOBS_HOME = "https://www.zhipin.com/web/geek/jobs"


def _is_remote_job(title: str, desc: str, location: str) -> bool:
    """
    快速判断是否是远程岗（用于 verify_mixed 预筛选）。
    远程岗特征：标题或描述中包含"远程""可远程""WFH""居家办公""在家办公"。
    """
    keywords = ["远程", "可远程", "WFH", "wfh", "居家办公", "在家办公"]
    combined = f"{title} {desc} {location}"
    return any(kw in combined for kw in keywords)


def _is_shenzhen_job(location: str, desc: str) -> bool:
    """
    快速判断是否是深圳岗（用于 verify_mixed 预筛选）。
    深圳岗特征：location 包含"深圳"。
    """
    return "深圳" in (location or "") or "深圳" in (desc[:200] or "")


async def verify_mixed(
    title: str,
    desc: str,
    salary: str = "",
    location: str = "",
) -> tuple[bool, str]:
    """
    混合判断函数：根据职位地点/描述是否为远程或深圳，选择对应的 verify 函数。
    - 远程岗 → verify_job_is_it_remote（title, desc, salary）
    - 深圳岗 → verify_llm_sz（title, desc, salary，需满足30K硬条件）
    - 两者都不是 → 跳过（返回 False）

    注意：一个职位可能同时满足"远程+深圳"（深圳的远程岗），
    此时优先走 verify_job_is_it_remote（能投就投）。
    """
    is_remote = _is_remote_job(title, desc, location)
    is_sz = _is_shenzhen_job(location, desc)

    if is_remote:
        should, reason = await verify_job_is_it_remote(title, desc, salary)
        return should, f"[远程岗路径] {reason}"

    if is_sz:
        should, reason = await verify_llm_sz(title, desc, salary)
        return should, f"[深圳大模型路径] {reason}"

    # 既不是远程也不是深圳
    return False, f"[跳过] 既非远程岗也非深圳岗（location={location!r}）"


# ─── verify_mixed 的包装器：适配 apply_to_job 的 (title, desc, salary) 签名 ──
# apply_to_job 调用 self.verify_fn(title, desc, salary)，不传 location。
# 但 verify_mixed 需要 location 来判断。
# 解决方案：在 PositionTabsAutomator 中重写 apply_to_job，从 job dict 取 location，
# 传给 verify_mixed_with_location（见下方）。
# 这样无需修改 BossZhipinAutomator.apply_to_job 的签名，保持向后兼容。

async def _verify_mixed_no_location(title: str, desc: str, salary: str = "") -> tuple[bool, str]:
    """
    无 location 参数的 verify_mixed 适配器（供 apply_to_job 的 verify_fn 签名使用）。
    在没有 location 信息时，仅依赖标题和描述中的关键字判断是否远程/深圳。
    """
    return await verify_mixed(title, desc, salary, location="")


# ─── 职位 Tab 专项 Automator ──────────────────────────────────────────────────

class PositionTabsAutomator(BossZhipinAutomator):
    """
    首页职位Tab专项投递。
    复用 BossZhipinAutomator 全部基础设施。
    通过注入 verify_fn=_verify_mixed_no_location 实现混合判断。
    覆盖：
      - navigate_to_jobs_home()：导航到职位列表首页
      - click_tab()：点击指定 tab
      - process_tab()：处理单个 tab 的全部职位
      - run()：主流程（遍历 tab，跳过数据架构师）
    """

    def __init__(self, dry_run=False):
        super().__init__(verify_fn=self._verify_mixed_bound, dry_run=dry_run)
        self.task_label = "职位tab"  # CSV/断点任务标识
        # 深圳岗薪资字体反爬：拦截列表 API joblist.json 取明文 salaryDesc（不截图OCR）
        self.salary_map = {}
        self.salary_resolver = self._resolve_salary

    async def start_browser(self, playwright):
        await super().start_browser(playwright)
        self.page.on("response", self._on_joblist_response)

    async def _on_joblist_response(self, resp):
        """捕获 zhipin 列表 API 明文 salaryDesc，按职位名建映射。

        ⚠️ 职位 tab（expect 推荐）列表走的是 wapi/zpgeek/pc/recommend/job/list.json，
        搜索结果走 wapi/zpgeek/search/joblist.json，两者结构相同(zpData.jobList[])。
        过滤需同时覆盖 joblist 和 job/list，否则 tab 模式 salary_map 永远为空、
        薪资字体反爬无法解析、全部职位被误判薪资不达标。
        """
        try:
            url = resp.url
            if not ("zpgeek" in url and ".json" in url
                    and ("joblist" in url or "job/list" in url)):
                return
            data = await resp.json()
            zp = data.get("zpData", data)
            jobs = zp.get("jobList") or zp.get("jobs") if isinstance(zp, dict) else None
            for j in (jobs or []):
                name = (j.get("jobName") or "").strip()
                sal = (j.get("salaryDesc") or "").strip()
                comp = (j.get("brandName") or j.get("companyName") or "").strip()
                if name and sal:
                    self.salary_map[name] = sal
                    self.salary_map[f"{comp}|{name}"] = sal
        except Exception:
            pass

    async def _resolve_salary(self, page) -> str:
        """从拦截到的列表 API 明文薪资映射查当前职位薪资（不截图OCR）。"""
        title = getattr(self, "_current_title", "") or ""
        company = getattr(self, "_current_company", "") or ""
        if not title:
            return ""
        return self.salary_map.get(f"{company}|{title}") or self.salary_map.get(title, "")

    async def _verify_mixed_bound(self, title: str, desc: str, salary: str = "") -> tuple[bool, str]:
        """绑定方法版混合判断：从 apply_to_job 暂存的 self._current_location 取地点，
        传给 verify_mixed 以准确区分远程/深圳。"""
        loc = getattr(self, "_current_location", "") or ""
        return await verify_mixed(title, desc, salary, location=loc)

    async def navigate_to_jobs_home(self) -> bool:
        """
        导航到 Boss直聘「职位」列表首页（不含搜索关键字，显示推荐职位列表）。

        方式一（直接导航URL）：直接访问 ZHIPIN_JOBS_HOME。
        方式二（点击导航栏职位按钮）：如果直接URL失败，回退到首页后点「职位」按钮。

        TODO-SELECTOR: 以下导航栏「职位」按钮选择器为最佳猜测，需真实页面确认。
        候选选择器：
          - ".nav-main a:has-text('职位')"  ← 主导航区包含"职位"的链接
          - "a[href*='/web/geek/jobs']"      ← 指向职位页的链接
          - ".header-nav a:has-text('职位')"
          - "nav a:has-text('职位')"
        """
        print(f"  导航到职位列表首页: {ZHIPIN_JOBS_HOME}")
        try:
            await self.page.goto(ZHIPIN_JOBS_HOME, wait_until="domcontentloaded", timeout=30000)
            human_delay(1.2, 2.0)
            # 检查是否有职位卡或 tab 区域（说明导航成功）
            try:
                await self.page.wait_for_selector(
                    # TODO-SELECTOR: 职位列表页可能有 .job-card-box 或 tab 区域
                    ".job-card-box, [class*='tab'], [class*='category']",
                    timeout=10000
                )
            except Exception:
                pass
            # 尝试截图确认页面状态
            await screenshot_page(self.page, "position_tabs_home.png")
            print("  已导航到职位首页")
            return True
        except Exception as e:
            print(f"  [WARN] 直接导航失败，尝试从首页点击职位按钮: {e}")

        # 回退方式：先回首页，再点「职位」按钮
        try:
            await self.page.goto("https://www.zhipin.com/", wait_until="domcontentloaded", timeout=30000)
            human_delay(1.0, 1.6)
        except Exception:
            return False

        # TODO-SELECTOR: 以下为导航栏「职位」按钮的候选选择器，需真实页面确认
        clicked = await self._click_smart(
            self.page,
            [
                ".nav-main a:has-text('职位')",         # TODO-SELECTOR: 候选1
                "a[href*='/web/geek/jobs']",             # TODO-SELECTOR: 候选2
                ".header-nav a:has-text('职位')",        # TODO-SELECTOR: 候选3
                "nav a:has-text('职位')",                # TODO-SELECTOR: 候选4
            ],
            "找到页面顶部导航栏中的「职位」按钮，点击它进入职位列表页。",
            "nav_jobs_btn.png",
        )
        if not clicked:
            print("  [WARN] 未能找到并点击「职位」导航按钮")
            return False

        human_delay(1.2, 2.0)
        await screenshot_page(self.page, "position_tabs_home_fallback.png")
        return True

    async def click_tab(self, tab_name: str) -> bool:
        """
        点击职位列表页中的指定 tab（如「机器学习」「算法工程师」）。

        Boss直聘职位列表页顶部有分类 tab 栏，
        各 tab 名称为职位类别（如「机器学习」「算法工程师」「数据架构师」等）。

        TODO-SELECTOR: 以下 tab 选择器为最佳猜测，需真实页面确认。
        Boss直聘职位 tab 的可能 HTML 结构（待确认）：
          <ul class="tab-list">
            <li class="tab-item active">机器学习</li>
            <li class="tab-item">算法工程师</li>
            <li class="tab-item">数据架构师</li>
          </ul>
        候选选择器：
          - ".tab-list .tab-item"                    ← tab列表项
          - "[class*='tab'] li"                      ← 泛化tab项
          - ".category-list .category-item"          ← 分类列表
          - "[class*='category'] [class*='item']"    ← 泛化分类项
        """
        print(f"  点击 tab: 【{tab_name}】")

        # 实测：职位列表页顶部的求职期望 tab 是 a.expect-item，内含 span.text-content，
        # 文本形如「机器学习(深圳)」（带地点后缀），故用【子串】匹配 tab_name。
        # ⚠️ tab 是异步渲染的：必须先等 a.expect-item 出现再查，否则会"选择器未命中"
        # 退到不可靠的 UI-TARS 视觉点击（实测整轮 tab 抓 0 的根因就是没等渲染）。
        clicked = False
        try:
            await self.page.wait_for_selector("a.expect-item, .expect-item", timeout=12000)
        except Exception:
            print("  [WARN] 等待 expect-item tab 渲染超时，仍尝试查询")
        try:
            tabs = await self.page.query_selector_all("a.expect-item, .expect-item")
            for t in tabs:
                txt = (await t.text_content() or "").strip()
                if tab_name in txt and await t.is_visible():
                    print(f"    命中 tab 文本: 「{txt}」")
                    bb = await t.bounding_box()
                    if bb:
                        await human_mouse_move_and_click(
                            self.page, int(bb["x"] + bb["width"] / 2), int(bb["y"] + bb["height"] / 2))
                    else:
                        await t.click()
                    clicked = True
                    break
        except Exception as e:
            print(f"  [WARN] expect-item tab 点击异常: {e}")

        # 选择器失败 → UI-TARS 视觉兜底
        if not clicked:
            clicked = await self._click_smart(
                self.page,
                ["a.expect-item", ".expect-item"],
                f"找到职位列表页顶部的求职期望 tab 栏，点击名称包含「{tab_name}」的那个 tab。",
                f"tab_click_{tab_name}.png",
            )
        if not clicked:
            print(f"  [WARN] 未能点击 tab: {tab_name}")
            return False

        # ⚠️ expect-item tab 是带 href 的链接，点击会【触发页面导航】到对应职位列表页。
        # 必须先等导航/网络稳定，否则随后 get_job_listings 在导航过程中查询会报
        # "Execution context was destroyed, most likely because of a navigation"，
        # 上一轮就是这个原因导致每个 tab 都"无职位"。
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        try:
            await self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        human_delay(1.0, 1.8)
        # 等待 tab 内容加载（职位卡出现）
        try:
            await self.page.wait_for_selector(".job-card-box", timeout=10000)
        except Exception:
            pass
        # 再短暂静置，确保 SPA 列表渲染稳定后再交给 get_job_listings 滚动加载
        human_delay(0.8, 1.5)
        await screenshot_page(self.page, f"tab_{tab_name}_loaded.png")
        n = len(await self.page.query_selector_all(".job-card-box"))
        print(f"  tab【{tab_name}】加载完成，当前页 {n} 个职位（滚动加载在 get_job_listings 内进行）")
        return True

    async def scroll_to_load_more(self) -> int:
        """
        在 tab 内滚动到底部以加载更多职位。
        实测 Boss直聘职位列表为【无限滚动懒加载】：goto/切 tab 后只渲染首屏约 15 个，
        需持续下滚才会陆续加载（约 15 次滚动可达 120 个）。早先"只滚 3 次"远不够，
        会漏掉本 tab 大部分职位。现复用父类 _scroll_load_all_cards 滚动到底加载全部。
        """
        return await self._scroll_load_all_cards()

    async def process_tab(self, tab_name: str) -> dict:
        """
        处理单个 tab 内的全部职位：
        1. 点击 tab
        2. 滚动加载更多（如果是无限滚动）
        3. 逐个职位调用 apply_to_job（注入了 verify_mixed，自动判断远程/深圳路径）
        """
        print(f"\n  {'='*50}")
        print(f"  处理 tab：【{tab_name}】")
        print(f"  {'='*50}")

        stat = {"tab": tab_name, "checked": 0, "applied": 0, "reject": 0,
                "dup": 0, "contacted": 0, "fail": 0, "blocked": 0}

        # 点击 tab
        if not await self.click_tab(tab_name):
            print(f"  [WARN] tab【{tab_name}】点击失败，跳过本 tab")
            return stat

        # 获取职位列表（get_job_listings 已内置滚动懒加载到底，加载本 tab 全部职位，
        # 无需再单独调 scroll_to_load_more）
        jobs = await self.get_job_listings()
        if not jobs:
            print(f"  tab【{tab_name}】无职位，跳过")
            return stat

        print(f"  tab【{tab_name}】共 {len(jobs)} 个职位，逐个检查...")
        import zhipin_apply as _za
        verified_count = 0  # 每个 tab 前3个成功投递进聊天界面看一眼
        for job in jobs:
            enter_chat = bool(_za.VERIFY_ALL_IN_MESSAGES or verified_count < 3)
            status = await self.apply_to_job(job, f"tab-{tab_name}", enter_chat=enter_chat)
            stat["checked"] += 1
            if status in stat:
                stat[status] += 1
            if status == "applied" and enter_chat:
                verified_count += 1
            self._mark_processed(job.get("company", ""), job.get("title", ""), f"tab-{tab_name}", status)
            skipped = stat['reject'] + stat['dup'] + stat['contacted'] + stat['blocked']
            print(f"     [tab {tab_name}] 检查 {stat['checked']} | "
                  f"投递 {stat['applied']} | 跳过 {skipped} | 失败 {stat['fail']}")
            if self.stop_requested:
                print("  🛑 当日沟通次数已用完，停止脚本，明天再跑。", flush=True)
                break
            human_delay()

        # tab 阶段总结
        skipped_total = stat['reject'] + stat['dup'] + stat['contacted'] + stat['blocked']
        print(f"\n  tab【{tab_name}】总结：检查 {stat['checked']} | "
              f"投递 {stat['applied']} | 跳过 {skipped_total} | 失败 {stat['fail']}")
        return stat

    async def run(self):
        """职位Tab专项主运行入口"""
        import zhipin_apply as za
        if not za.OPENROUTER_API_KEY:
            raise ValueError(
                "缺少 OPENROUTER_API_KEY！\n"
                "请在 automation/.env 中设置：OPENROUTER_API_KEY=sk-or-v1-xxx"
            )

        print("\n" + "🤖 " * 20)
        print("Boss直聘自动投递 — 首页职位Tab专项 启动")
        print(f"将处理 tab：{TABS_TO_PROCESS}（跳过：{TABS_TO_SKIP}）")
        print("🤖 " * 20 + "\n")

        from rebrowser_playwright.async_api import async_playwright
        async with async_playwright() as playwright:
            await self.start_browser(playwright)

            try:
                await self.navigate_to_zhipin()
                logged_in = await self.check_login_and_wait()
                if not logged_in:
                    print("未能登录，终止运行")
                    return

                # 导航到职位列表首页
                if not await self.navigate_to_jobs_home():
                    print("未能导航到职位列表首页，终止运行")
                    return

                all_stats = []
                for tab_name in TABS_TO_PROCESS:
                    st = await self.process_tab(tab_name)
                    all_stats.append(st)
                    self._flush_checkpoint(f"tab-{tab_name}")  # tab 处理完落盘断点
                    if self.stop_requested:
                        print("\n🛑 当日沟通次数已用完，停止处理剩余 tab，明天再跑。", flush=True)
                        break
                    # tab 间休息
                    import random
                    rest = random.uniform(2.0, 3.5)
                    print(f"\n  tab 间休息 {rest:.1f}s...")
                    await asyncio.sleep(rest)

                # 全部 tab 跑完（未被每日上限中断）→ 清除断点
                if not self.stop_requested:
                    import zhipin_apply as _za
                    _za.clear_checkpoint(self.task_label)

                # 全部 tab 汇总
                print("\n" + "█" * 60)
                print("首页职位Tab专项 — 全部 tab 处理完毕")
                print("█" * 60)
                tot = {"checked": 0, "applied": 0, "reject": 0,
                       "dup": 0, "contacted": 0, "fail": 0, "blocked": 0}
                print(f"  {'tab':<12}{'检查':>6}{'投递':>6}{'不符合':>7}{'已投':>6}{'失败':>6}")
                for st in all_stats:
                    for k in tot:
                        tot[k] += st.get(k, 0)
                    print(f"  {st['tab']:<12}{st['checked']:>6}{st['applied']:>6}"
                          f"{st['reject']:>7}{st['dup']:>6}{st['fail']:>6}")
                print(f"  {'─' * 46}")
                print(f"  {'合计':<12}{tot['checked']:>6}{tot['applied']:>6}"
                      f"{tot['reject']:>7}{tot['dup']:>6}{tot['fail']:>6}")

            except KeyboardInterrupt:
                print("\n用户中断，保存当前进度...")
                save_applied_jobs(self.applied_data)

            finally:
                try:
                    save_applied_jobs(self.applied_data)
                    csv_path = export_applications_csv(
                        self.applied_data, label=self.task_label, since=self._run_started)
                    print(f"最终统计CSV已生成: {csv_path}")
                except Exception as e:
                    print(f"[WARN] 导出CSV失败: {e}")
                print("\n关闭浏览器...")
                try:
                    await self.context.close()
                except Exception:
                    pass


# ─── 入口 ─────────────────────────────────────────────────────────────────────

def _build_arg_parser():
    import argparse
    parser = argparse.ArgumentParser(
        description="Boss直聘自动投递 - 首页职位Tab专项（机器学习/算法工程师；混合判断远程+深圳）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 使用 .env 中的 OpenRouter key
  python automation/zhipin_position_tabs.py

  # 命令行传入 key
  python automation/zhipin_position_tabs.py --openrouter-key sk-or-v1-xxx

  # 指定 UI-TARS 为 remote 方式（UI-TARS兜底点击将走remote endpoint）
  python automation/zhipin_position_tabs.py \\
    --uitars-provider remote \\
    --uitars-endpoint https://xxxx.ngrok.io/v1/chat/completions \\
    --uitars-key super-secret-key

注意：首页「职位」按钮和 tab 选择器为最佳猜测，
      首次运行时请观察浏览器行为，如选择器失效将自动触发 UI-TARS 视觉兜底。
      所有 TODO-SELECTOR 标记处均需在真实页面确认后更新。
        """,
    )
    parser.add_argument("--openrouter-key", default=None,
                        help="OpenRouter API key（优先级高于环境变量/env文件）")
    parser.add_argument("--uitars-provider", choices=["openrouter", "remote", "local"],
                        default="openrouter", help="UI-TARS 提供方式（默认 openrouter）")
    parser.add_argument("--uitars-endpoint", default=None,
                        help="remote 方式下 UI-TARS endpoint URL")
    parser.add_argument("--uitars-key", default=None,
                        help="remote 方式下 UI-TARS x-api-key 鉴权 key")
    parser.add_argument("--uitars-local-url", default=None,
                        help="local 方式下本地/局域网 UI-TARS 推理地址（含 /v1），"
                             "如 http://192.168.3.14:8000/v1")
    parser.add_argument("--dry-run", action="store_true",
                        help="试运行：搜索+判断+打印，但不点立即沟通/不发招呼/不记录。")
    parser.add_argument("--speed", choices=["normal", "fast", "slow"], default="normal",
                        help="操作延迟档位：normal(默认) | fast(快) | slow(慢/反爬)。触发安全验证会自动升 slow。")
    parser.add_argument("--allow-paid-fallback", action="store_true",
                        help="允许免费LLM/本地UI-TARS连续失败后升级到OpenRouter收费LLM/UI-TARS兜底。默认关。")
    parser.add_argument("--proxy", default=None,
                        help="访问 openrouter.ai 的代理(如 http://127.0.0.1:25378)。不传则自动从系统PAC检测。")
    parser.add_argument("--verify-all", action="store_true",
                        help="每个成功打招呼都进消息窗口核验(更稳更拟人,更慢)。默认只核验每tab前3个。")
    return parser


def main():
    import zhipin_apply as za
    parser = _build_arg_parser()
    args = parser.parse_args()

    za.apply_speed_profile(args.speed)
    za.ALLOW_PAID_FALLBACK = args.allow_paid_fallback
    za.VERIFY_ALL_IN_MESSAGES = args.verify_all
    za.setup_openrouter_proxy(args.proxy)
    print(f"⚙️ 操作延迟档位: {args.speed} | 收费兜底: {'开' if args.allow_paid_fallback else '关'}"
          f" | 消息核验: {'全部' if args.verify_all else '前3'}", flush=True)

    if args.openrouter_key:
        za.OPENROUTER_API_KEY = args.openrouter_key
    za.UITARS_PROVIDER = args.uitars_provider
    if args.uitars_key:
        za.UITARS_KEY = args.uitars_key
    if args.uitars_endpoint:
        za.UITARS_ENDPOINT = args.uitars_endpoint
    if args.uitars_local_url:
        za.UITARS_LOCAL_URL = args.uitars_local_url

    if za.UITARS_PROVIDER == "remote" and not za.UITARS_ENDPOINT:
        parser.error("--uitars-provider remote 需要同时指定 --uitars-endpoint")

    print(f"UI-TARS 提供方式: {za.UITARS_PROVIDER}"
          + (f" | endpoint: {za.UITARS_ENDPOINT}" if za.UITARS_PROVIDER == "remote" else "")
          + (f" | local: {za.UITARS_LOCAL_URL}" if za.UITARS_PROVIDER == "local" else ""),
          flush=True)
    if args.dry_run:
        print("🧪 dry-run 试运行：只搜索+判断，不实际投递", flush=True)

    asyncio.run(PositionTabsAutomator(dry_run=args.dry_run).run())


if __name__ == "__main__":
    main()
