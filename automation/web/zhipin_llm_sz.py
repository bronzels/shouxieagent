# -*- coding: utf-8 -*-
"""
Boss直聘自动投递 - 大模型·深圳专项任务

任务：深圳(city=101280600)，搜索关键字「大模型」，自动遍历列表页投递。
判断标准：
  1. 与大模型相关（LLM/大模型/AIGC/生成式AI/RAG/Agent/微调/推理/预训练等）
  2. 软件开发岗 或 管理岗（管理岗允许，如算法负责人/AI技术经理）
  3. 薪资区间必须包含30K（薪资下限≤30000≤上限），解析失败则视为不满足硬条件

复用：BossZhipinAutomator（start_browser / check_login_and_wait / apply_to_job /
      get_job_listings / _click_smart / _close_greet_dialog 等全部复用）。
      通过注入 verify_fn=verify_llm_sz 实现定制判断，无需复制任何投递逻辑。
"""

import asyncio
import os
import re
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
    _post_openrouter,
    VERIFY_MODELS_TEXT,
    CITY_CODES,
    human_delay,
    screenshot_page,
    is_city_completed,
    mark_city_completed,
    export_applications_csv,
    save_applied_jobs,
    APPLY_DELAY_MIN,
    APPLY_DELAY_MAX,
    DELAY_MIN,
    DELAY_MAX,
    CARD_DELAY_MIN,
    CARD_DELAY_MAX,
)

# ─── 配置 ─────────────────────────────────────────────────────────────────────

LLM_SEARCH_KEYWORD = "大模型"
LLM_CITY = "深圳"
LLM_CITY_CODE = CITY_CODES["深圳"]  # "101280600"

# 大模型岗位薪资硬条件：30K/月
SALARY_THRESHOLD = 30_000  # 单位：元/月


# ─── 薪资解析 ─────────────────────────────────────────────────────────────────

def salary_covers_30k(salary_text: str) -> bool:
    """
    判断薪资【上限是否 ≥ 30K(30000元/月)】——即该岗位能给到 30K 或更高就算满足。
    （用户口径："上限高于30k；下限也高于30k当然可以"。只排除封顶<30K 的低薪岗。）
    支持格式：
      - "25-50K"  → 上限50K ≥ 30K → True
      - "35-60K"  → 上限60K ≥ 30K → True（下限也>30K）
      - "100-200K"→ 上限200K → True
      - "20-35K"  → 上限35K → True
      - "10-15K"  → 上限15K < 30K → False
      - "3-5万"   → 上限50000 → True
      - "30K以上"/"5万以上" → 上限开放 → True
      - "8千-1.2万"→ 上限12000 < 30K → False
    解析失败时保守返回 False（宁可漏掉也不错投）。
    """
    if not salary_text:
        return False

    text = salary_text.strip()
    # 日薪/时薪不是月薪，直接排除（如 "100-150元/天"、实习日结、"200元/小时"）
    if re.search(r"/?\s*[天日]|/\s*小?时|元/天|元/日|元/时", text):
        return False
    # 归一化：去掉多薪/年薪等说明（·14薪、/年 等），只看月薪主体
    text = re.sub(r"[··×x]\d+薪.*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"/年.*", "", text)

    # 格式1：XX-YY万（如 3-5万）→ 看上限
    m = re.match(r"(\d+(?:\.\d+)?)\s*[-~–]\s*(\d+(?:\.\d+)?)\s*万", text)
    if m:
        hi = float(m.group(2)) * 10_000
        return hi >= SALARY_THRESHOLD

    # 格式2：XX-YYK（如 25-50K）→ 看上限
    m = re.match(r"(\d+(?:\.\d+)?)\s*[-~–]\s*(\d+(?:\.\d+)?)\s*[Kk]", text)
    if m:
        hi = float(m.group(2)) * 1_000
        return hi >= SALARY_THRESHOLD

    # 格式3：XX万以上 / XX万+ → 上限开放，视为满足
    if re.match(r"(\d+(?:\.\d+)?)\s*万\s*(?:以上|\+)", text):
        return True

    # 格式4：XXK以上 / XXK+ → 上限开放，视为满足
    if re.match(r"(\d+(?:\.\d+)?)\s*[Kk]\s*(?:以上|\+)", text):
        return True

    # 格式5：纯数字范围（如 30000-50000 元/月）→ 看上限
    m = re.match(r"(\d+)\s*[-~–]\s*(\d+)", text)
    if m:
        hi = float(m.group(2))
        if hi < 500:   # 较小数字按"千"→K 处理（如 25-50 即 25K-50K）
            hi *= 1_000
        return hi >= SALARY_THRESHOLD

    # 解析失败 → 保守返回 False
    return False


# ─── 大模型深圳职位判断函数 ───────────────────────────────────────────────────

async def verify_llm_sz(job_title: str, job_desc: str, salary: str = "") -> tuple[bool, str]:
    """
    判断职位是否满足「大模型·深圳」投递条件：
      1. 与大模型相关（LLM/大模型/AIGC/生成式AI/RAG/Agent/微调/推理/预训练等）
      2. 软件开发岗 OR 管理岗（管理岗允许，如算法负责人/AI技术经理）
      3. 薪资区间必须包含 30K（代码层面硬判断，模型仅辅助复核）

    薪资硬条件在代码层面 and 起来：salary_covers_30k 返回 False 则直接不投递。
    返回 (should_apply, reason)
    """
    # 薪资硬条件（代码层面）：解析失败保守返回 False
    salary_ok = salary_covers_30k(salary)
    if not salary_ok:
        return False, f"薪资硬条件不满足（{salary!r} 不包含30K/月，或无法解析）"

    prompt = f"""你是一个严格的招聘职位筛选助手，专门筛选「大模型·深圳」岗位。
请判断下面这个职位是否【同时满足】以下两个条件，只有都满足才建议投递。

【条件1：必须与大模型/AI相关】
✅ 算作相关（职位核心工作与以下任一方向相关）：
   LLM / 大语言模型 / 大模型 / AIGC / 生成式AI / RAG / Agent / 智能体 /
   模型微调(Fine-tuning) / 模型推理 / 模型预训练 / 向量数据库 / Embedding /
   Prompt Engineering / AI应用开发 / 多模态模型 / 扩散模型 / 强化学习(RLHF)
❌ 排除（即使公司做大模型，岗位本身与大模型无关的也排除）：
   数据标注师 / 客服 / 销售 / 市场 / BD / 内容运营 / 行政 / 财务 / 法务

【条件2：必须是软件开发岗 或 技术管理岗】
✅ 算作（开发岗或管理岗均可）：
   算法工程师 / 模型工程师 / AI工程师 / 后端工程师 / 全栈工程师 / 平台工程师 /
   算法负责人 / AI技术经理 / 技术总监（技术背景）/ 研究员 / 架构师
   注意：管理岗允许（与远程任务不同，这里管理岗可以投递）
   运维开发说明：以【开发为主】的运维开发/平台开发/工具链开发/DevOps平台研发可以投；
   但【纯运维】、SRE值守、7×24随时待命/oncall为主、保障稳定性而非写代码的岗位 → 不投。
❌ 排除（不是开发/技术管理的岗位）：
   产品经理 / 项目经理 / 运营 / 销售 / 市场 / 招聘 / HR / 行政 /
   纯运维 / SRE值守 / 7×24待命运维 / 系统管理员（以保障/值守为主、非以写代码开发为主）

【备注：薪资方面】
薪资信息（{salary}）已在代码层面做了硬判断（是否≥30K/月）。
请你也在推理中复核薪资是否合理，但最终结论只需基于条件1和条件2。

职位标题：{job_title}

职位描述正文：
{job_desc[:1500]}

请严格按以下格式回答（一定要有"结论"行）：
是否与大模型/AI相关：是/否（说明依据，如核心技术方向/关键词）
是否开发岗或技术管理岗：是/否（说明岗位性质）
薪资复核（{salary}）：符合/不符合/无法判断（仅供参考，代码已做硬判断）
结论：投递 / 不投递
理由：（一句话，说明关键原因）"""

    payload = {
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        "max_tokens": 400,
    }
    result = await _post_openrouter(payload, models=VERIFY_MODELS_TEXT)
    answer = result["choices"][0]["message"]["content"]

    # 稳健解析"结论"行
    concl_line = ""
    for line in answer.splitlines():
        if "结论" in line:
            concl_line = line
            break
    c = concl_line.replace("*", "").replace(" ", "").replace("：", ":")
    if "结论" in c:
        c = c.split("结论", 1)[1]
    should_apply = ("投递" in c) and ("不投递" not in c)
    return should_apply, answer


# ─── 大模型深圳专项 Automator ─────────────────────────────────────────────────

class LlmSzAutomator(BossZhipinAutomator):
    """
    大模型·深圳专项投递。
    复用 BossZhipinAutomator 全部基础设施（浏览器/登录/投递/去重/状态过滤/CSV）。
    通过构造时注入 verify_fn=verify_llm_sz 实现定制判断。
    仅覆盖：列表页 URL 生成（固定深圳+大模型关键字）、run() 主流程。
    """

    def __init__(self, dry_run=False):
        super().__init__(verify_fn=verify_llm_sz, dry_run=dry_run)
        self.search_keyword = LLM_SEARCH_KEYWORD
        self.city = LLM_CITY
        self.city_code = LLM_CITY_CODE
        self.task_label = "大模型深圳"  # CSV/断点任务标识
        # 薪资字体反爬解决方案：拦截列表 API joblist.json（返回明文 salaryDesc），
        # 建 {职位名→明文薪资} 映射，投递判断时按职位名查映射。【不用截图OCR】。
        self.salary_map = {}
        self.salary_resolver = self._resolve_salary

    async def start_browser(self, playwright):
        # 复用父类启动，再挂上 API 响应监听以捕获明文薪资
        await super().start_browser(playwright)
        self.page.on("response", self._on_joblist_response)

    async def _on_joblist_response(self, resp):
        """捕获 zhipin 列表 API 明文 salaryDesc，按职位名建映射。

        覆盖 search/joblist.json（搜索）与 pc/recommend/job/list.json（推荐/tab），
        两者结构相同(zpData.jobList[])，过滤需同时匹配 joblist 和 job/list。
        """
        try:
            url = resp.url
            if not ("zpgeek" in url and ".json" in url
                    and ("joblist" in url or "job/list" in url)):
                return
            data = await resp.json()
            zp = data.get("zpData", data)
            jobs = None
            if isinstance(zp, dict):
                jobs = zp.get("jobList") or zp.get("jobs")
            for j in (jobs or []):
                name = (j.get("jobName") or "").strip()
                sal = (j.get("salaryDesc") or "").strip()
                comp = (j.get("brandName") or j.get("companyName") or "").strip()
                if name and sal:
                    self.salary_map[name] = sal
                    self.salary_map[f"{comp}|{name}"] = sal  # 公司+职位做更精确的键
        except Exception:
            pass

    async def _resolve_salary(self, page) -> str:
        """从拦截到的列表 API 明文薪资映射里，按当前职位名/公司查真实薪资（不截图OCR）。"""
        title = getattr(self, "_current_title", "") or ""
        company = getattr(self, "_current_company", "") or ""
        if not title:
            return ""
        # 优先 公司+职位 精确键，再退回仅职位名
        return self.salary_map.get(f"{company}|{title}") or self.salary_map.get(title, "")

    async def goto_list_llm(self, page_num: int = 1) -> bool:
        """
        导航到大模型·深圳列表搜索结果页。
        URL 格式与远程任务一致，只是关键字换成「大模型」、城市固定深圳。
        """
        from urllib.parse import quote
        q = quote(self.search_keyword)
        url = (f"https://www.zhipin.com/web/geek/jobs"
               f"?query={q}&city={self.city_code}&page={page_num}")
        print(f"  搜索大模型岗位: {self.city} 第{page_num}页 (city={self.city_code})")

        for attempt in range(2):
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                human_delay(1.2, 2.0)
                try:
                    await self.page.wait_for_selector(".job-card-box", timeout=10000)
                except Exception:
                    pass
                n = len(await self.page.query_selector_all(".job-card-box"))
                if n > 0:
                    print(f"  本页找到 {n} 个职位")
                    return True
                if attempt == 0:
                    print("  0个职位（疑似首次导航安全校验），重试一次...")
                    human_delay(1.2, 2.0)
            except Exception as e:
                print(f"  [WARN] 列表导航失败(尝试{attempt+1}): {e}")
        return False

    async def run(self):
        """大模型·深圳专项主运行入口"""
        import zhipin_apply as za
        if not za.OPENROUTER_API_KEY:
            raise ValueError(
                "缺少 OPENROUTER_API_KEY！\n"
                "请在 automation/.env 中设置：OPENROUTER_API_KEY=sk-or-v1-xxx"
            )

        print("\n" + "🤖 " * 20)
        print("Boss直聘自动投递 — 大模型·深圳专项 启动")
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

                print(f"\n搜索关键字: {self.search_keyword} | 城市: {self.city}")

                # 城市级去重
                if is_city_completed(self.applied_data, f"{self.city}-大模型"):
                    print(f"深圳大模型任务今天已完成，跳过（隔天会自动重跑）")
                    return

                stat = {"checked": 0, "applied": 0, "reject": 0,
                        "dup": 0, "contacted": 0, "fail": 0, "blocked": 0,
                        "would_apply": 0}

                # ⚠️ Boss直聘新版列表页【无限滚动懒加载，URL &page=N 实测无效】，
                # 早先"翻 10 页"实际每页拿同一批首屏职位，去重后只处理首屏、漏 80%+。
                # 现改为：goto 第 1 页 → get_job_listings 内部滚动到底加载全部 → 一次性处理。
                any_page_ok = False
                if not await self.goto_list_llm(1):
                    print("  列表无职位，退出")
                else:
                    any_page_ok = True
                    await screenshot_page(self.page, "llm_sz.png")

                    jobs = await self.get_job_listings()  # 已内置滚动懒加载到底
                    if not jobs:
                        print("  滚动加载后仍无职位")
                    else:
                        print(f"  共 {len(jobs)} 个职位（已滚动加载全部），逐个检查...")
                        verified_count = 0  # 前3个成功投递进聊天界面看一眼
                        for job in jobs:
                            enter_chat = bool(za.VERIFY_ALL_IN_MESSAGES or verified_count < 3)
                            status = await self.apply_to_job(job, self.city, enter_chat=enter_chat)
                            stat["checked"] += 1
                            if status in stat:
                                stat[status] += 1
                            if status == "applied" and enter_chat:
                                verified_count += 1
                            self._mark_processed(job.get("company", ""), job.get("title", ""), self.city, status)
                            skipped = stat['reject'] + stat['dup'] + stat['contacted'] + stat['blocked']
                            print(f"     [进度] 检查 {stat['checked']}/{len(jobs)} | "
                                  f"投递 {stat['applied']} | 跳过 {skipped} | 失败 {stat['fail']}")
                            if self.stop_requested:
                                print("  🛑 当日沟通次数已用完，停止脚本，明天再跑。", flush=True)
                                break
                            human_delay()

                # dry-run 不标记城市完成（未真正投递）
                if any_page_ok and not self.dry_run:
                    mark_city_completed(self.applied_data, f"{self.city}-大模型")
                # 断点：任务完整跑完（未被每日上限中断）→ 清除；否则保留供重启续跑
                self._flush_checkpoint(self.city)
                if any_page_ok and not self.stop_requested:
                    import zhipin_apply as _za
                    _za.clear_checkpoint(self.task_label)

                # 总结
                skipped_total = stat['reject'] + stat['dup'] + stat['contacted'] + stat['blocked']
                would = stat.get('would_apply', 0)
                print(f"\n  大模型·深圳 总结{'（dry-run 试运行）' if self.dry_run else ''}：")
                print(f"  共检查 {stat['checked']} 个职位 → "
                      + (f"本应投递 {would} | " if self.dry_run else f"投递 {stat['applied']} | ")
                      + f"跳过 {skipped_total}（不符合{stat['reject']}/已投{stat['dup']}"
                      f"/已沟通{stat['contacted']}/对方已回应{stat['blocked']}）| "
                      f"失败 {stat['fail']}")

            except KeyboardInterrupt:
                print("\n用户中断，保存当前进度...")
                save_applied_jobs(self.applied_data)

            finally:
                if not self.dry_run:
                    try:
                        save_applied_jobs(self.applied_data)
                        csv_path = export_applications_csv(
                            self.applied_data, label=self.task_label, since=self._run_started)
                        print(f"最终统计CSV已生成: {csv_path}")
                    except Exception as e:
                        print(f"[WARN] 导出CSV失败: {e}")
                else:
                    print("（dry-run：未记录、未导出 CSV）")
                print("\n关闭浏览器...")
                try:
                    await self.context.close()
                except Exception:
                    pass


# ─── 入口 ─────────────────────────────────────────────────────────────────────

def _build_arg_parser():
    import argparse
    parser = argparse.ArgumentParser(
        description="Boss直聘自动投递 - 大模型·深圳专项（复用BossZhipinAutomator，注入verify_llm_sz）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 试运行（只搜索+判断，不投递）
  python automation/zhipin_llm_sz.py --dry-run

  # 使用 .env 中的 OpenRouter key 正式跑
  python automation/zhipin_llm_sz.py

  # 本地 UI-TARS 推理（局域网服务器 192.168.3.14），验证职位仍走 OpenRouter
  python automation/zhipin_llm_sz.py --uitars-provider local \\
    --uitars-local-url http://192.168.3.14:8000/v1 \\
    --openrouter-key sk-or-v1-xxx

  # remote 方式（Kaggle/Colab 的 x-api-key endpoint）
  python automation/zhipin_llm_sz.py \\
    --uitars-provider remote \\
    --uitars-endpoint https://xxxx.ngrok.io/v1/chat/completions \\
    --uitars-key super-secret-key
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
                        help="local 方式下本地/局域网 UI-TARS 推理服务地址（OpenAI 兼容，含 /v1），"
                             "如 http://192.168.3.14:8000/v1")
    parser.add_argument("--dry-run", action="store_true",
                        help="试运行：搜索+判断+打印结论，但不点立即沟通/不发招呼/不记录，用于安全验证筛选。")
    parser.add_argument("--speed", choices=["normal", "fast", "slow"], default="normal",
                        help="操作延迟档位：normal(默认) | fast(快) | slow(慢/反爬)。触发安全验证会自动升 slow。")
    parser.add_argument("--allow-paid-fallback", action="store_true",
                        help="允许免费LLM/本地UI-TARS连续失败后升级到OpenRouter收费LLM/UI-TARS兜底。默认关。")
    parser.add_argument("--proxy", default=None,
                        help="访问 openrouter.ai 的代理(如 http://127.0.0.1:25378)。不传则自动从系统PAC检测。")
    parser.add_argument("--verify-all", action="store_true",
                        help="每个成功打招呼都进消息窗口核验(更稳更拟人,更慢)。默认只核验前3个。")
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
    asyncio.run(LlmSzAutomator(dry_run=args.dry_run).run())


if __name__ == "__main__":
    main()
