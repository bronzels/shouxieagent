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
#   - "local"：本地/局域网 llama-cpp-python server（OpenAI 兼容），走 UITARS_LOCAL_URL
UITARS_PROVIDER = "openrouter"   # openrouter / remote / local
UITARS_ENDPOINT = ""             # remote 方式的完整 URL（如 https://xxx.ngrok.io/v1/chat/completions）
UITARS_KEY = ""                  # remote 方式的鉴权 key（放 x-api-key header）
# local 方式：llama-cpp-python server 地址（/v1 前缀，不含 /chat/completions）
# 例：本机 http://127.0.0.1:8000/v1，局域网服务器 http://192.168.3.14:8000/v1
UITARS_LOCAL_URL = "http://127.0.0.1:8000/v1"
UITARS_LOCAL_MODEL = None  # None → 自动从 /v1/models 取第一个
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
# 收费模型兜底链：免费模型全部多轮失败（429限流/402余额/内容异常）后升级到收费模型，
# 保证任务能继续。选便宜且强的：Gemini Flash / GPT-4o-mini（都支持多模态）。
VERIFY_MODELS_TEXT_PAID = [
    "google/gemini-2.0-flash-001",
    "openai/gpt-4o-mini",
]
VERIFY_MODELS_MULTIMODAL_PAID = [
    "google/gemini-2.0-flash-001",
    "openai/gpt-4o-mini",
]
# 正文文本判定为"足够"的最小长度；低于此视为反爬导致抓取失败，触发滚动重抓/多模态兜底
MIN_DESC_LEN = 40

APPLIED_JOBS_FILE = Path(__file__).parent / "applied_jobs.json"
# 断点续跑文件：按任务记录已处理职位 + 当前城市，重启后从断点继续，不必从头
CHECKPOINT_FILE = Path(__file__).parent / "zhipin_checkpoint.json"
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

# 人类操作延迟范围（秒）——三档可调，命令行 --speed normal|fast|slow 切换。
#   normal：旧的稳健值（默认）   fast：快档（少等待，量大时用）   slow：慢档（触发反爬时用）
# 含义：DELAY=职位间隔；CARD=点卡→详情；APPLY=投递(发招呼)后；
#       SCROLL=滚动懒加载每次等待；CITY_REST=城市间休息。
SPEED_PROFILES = {
    "normal": {  # 旧的正常值（之前调快前的稳健档）
        "DELAY": (0.8, 1.8), "CARD": (1.2, 2.2), "APPLY": (3.0, 5.0),
        "SCROLL": (0.9, 1.6), "CITY_REST": (5.0, 10.0),
    },
    "fast": {    # 当前快档
        "DELAY": (0.3, 0.7), "CARD": (0.4, 0.9), "APPLY": (1.5, 2.5),
        "SCROLL": (0.4, 0.8), "CITY_REST": (2.0, 4.0),
    },
    "slow": {    # 慢档（触发反爬/安全验证后自动切到此档，或手动指定）
        "DELAY": (2.0, 4.0), "CARD": (3.0, 5.0), "APPLY": (6.0, 10.0),
        "SCROLL": (1.6, 2.8), "CITY_REST": (12.0, 22.0),
    },
}
SPEED_TIER = "normal"  # 当前档位（main 里按 --speed 设置，反爬触发时升级到 slow）

# 以下模块级延迟变量由 apply_speed_profile() 按档位填充；默认用 normal。
DELAY_MIN, DELAY_MAX = SPEED_PROFILES["normal"]["DELAY"]
CARD_DELAY_MIN, CARD_DELAY_MAX = SPEED_PROFILES["normal"]["CARD"]
APPLY_DELAY_MIN, APPLY_DELAY_MAX = SPEED_PROFILES["normal"]["APPLY"]
SCROLL_WAIT_MIN, SCROLL_WAIT_MAX = SPEED_PROFILES["normal"]["SCROLL"]
CITY_REST_MIN, CITY_REST_MAX = SPEED_PROFILES["normal"]["CITY_REST"]


def apply_speed_profile(tier: str):
    """按档位设置所有延迟全局变量。tier ∈ {normal, fast, slow}。"""
    global SPEED_TIER, DELAY_MIN, DELAY_MAX, CARD_DELAY_MIN, CARD_DELAY_MAX
    global APPLY_DELAY_MIN, APPLY_DELAY_MAX, SCROLL_WAIT_MIN, SCROLL_WAIT_MAX
    global CITY_REST_MIN, CITY_REST_MAX
    p = SPEED_PROFILES.get(tier, SPEED_PROFILES["normal"])
    SPEED_TIER = tier if tier in SPEED_PROFILES else "normal"
    DELAY_MIN, DELAY_MAX = p["DELAY"]
    CARD_DELAY_MIN, CARD_DELAY_MAX = p["CARD"]
    APPLY_DELAY_MIN, APPLY_DELAY_MAX = p["APPLY"]
    SCROLL_WAIT_MIN, SCROLL_WAIT_MAX = p["SCROLL"]
    CITY_REST_MIN, CITY_REST_MAX = p["CITY_REST"]


# 收费/OpenRouter 兜底总开关（命令行 --allow-paid-fallback 打开；默认关）。
# 打开后：免费 LLM 连续失败→升级收费 LLM；本地 UI-TARS 连续失败→切 OpenRouter UI-TARS。
ALLOW_PAID_FALLBACK = False

# 城市完成标记按【日历日期】判断：同一天重跑跳过，不同日期（隔天）则重新处理

# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def load_applied_jobs() -> dict:
    """加载已投递职位记录（含已完成城市记录，用于双重去重）

    completed_cities 现为 dict：{城市名: "YYYY-MM-DD HH:MM:SS"}，记录完成日期时间，
    按日历日期判断：同一天重跑跳过，隔天（不同日期）则重新处理。兼容旧版 list[str]
    格式（自动转换，无时间戳的旧城市视为可重跑）。
    """
    if APPLIED_JOBS_FILE.exists():
        with open(APPLIED_JOBS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("jobs", [])
            data.setdefault("completed_cities", {})
            data.setdefault("last_updated", "")
            # 兼容旧版 list 格式 → 转 dict（无时间戳=空串，视为过期可重跑）
            if isinstance(data["completed_cities"], list):
                data["completed_cities"] = {c: "" for c in data["completed_cities"]}
            return data
    return {"jobs": [], "completed_cities": {}, "last_updated": ""}


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
    """该城市是否【在今天】已处理完成（同一天→跳过；不同日期→可重跑）

    按日历日期判断，不看间隔小时数：同一天重复运行会跳过（避免当天重复打招呼），
    只要不是今天完成的（哪怕只跨过一次午夜）就重新处理。
    """
    cities = data.get("completed_cities", {})
    if isinstance(cities, list):  # 兼容旧格式
        cities = {c: "" for c in cities}
    ts = cities.get(city)
    if not ts:  # 未记录或无时间戳（旧数据）→ 不跳过，可重跑
        return False
    done_date = ts.split(" ")[0]  # 取 "YYYY-MM-DD" 部分
    today = datetime.now().strftime("%Y-%m-%d")
    if done_date == today:
        print(f"  ⏭️ 城市 [{city}] 今天（{done_date}）已处理完成，跳过")
        return True
    print(f"  🔄 城市 [{city}] 上次完成于 {done_date}（非今天 {today}），重新处理")
    return False


def mark_city_completed(data: dict, city: str):
    """标记城市处理完成（记录当前日期时间），当天重跑会跳过，隔天则重新处理"""
    cities = data.get("completed_cities", {})
    if isinstance(cities, list):  # 兼容旧格式
        cities = {c: "" for c in cities}
        data["completed_cities"] = cities
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cities[city] = now
    save_applied_jobs(data)
    print(f"  🏁 城市 [{city}] 处理完成，已记录 {now}（当天重跑将跳过，隔天可重跑）")


# ─── 断点续跑（checkpoint）────────────────────────────────────────────────────────
# 记录每个任务【今天】已处理过的职位 key（公司|职位）和当前城市，程序崩溃/重启后
# 跳过已处理的记录，从断点继续，不必从头。按日历日期作用域：隔天自动重新开始。

def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_checkpoint(label: str) -> dict:
    """读取某任务今天的断点。返回 {'processed': set(), 'current_city': str}。隔天/无则空。"""
    try:
        if CHECKPOINT_FILE.exists():
            allcp = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
            cp = allcp.get(label)
            if cp and cp.get("date") == _today_str():
                return {"processed": set(cp.get("processed", [])),
                        "current_city": cp.get("current_city", "")}
    except Exception:
        pass
    return {"processed": set(), "current_city": ""}


def _save_checkpoint(label: str, processed: set, current_city: str):
    try:
        allcp = {}
        if CHECKPOINT_FILE.exists():
            try:
                allcp = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
            except Exception:
                allcp = {}
        allcp[label] = {"date": _today_str(), "current_city": current_city,
                        "processed": sorted(processed)}
        CHECKPOINT_FILE.write_text(json.dumps(allcp, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    except Exception as e:
        print(f"  [WARN] 保存断点失败: {e}", flush=True)


def clear_checkpoint(label: str):
    """任务完整跑完后清除该任务断点（下次从头）。"""
    try:
        if CHECKPOINT_FILE.exists():
            allcp = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
            if label in allcp:
                allcp.pop(label, None)
                CHECKPOINT_FILE.write_text(json.dumps(allcp, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
                print(f"  🧹 任务[{label}]完整跑完，已清除断点", flush=True)
    except Exception:
        pass


def export_applications_csv(data: dict, label: str = None, since: str = None) -> str:
    """
    把投递记录导出为 CSV，放到单独的 reports/ 目录。
    - label：任务标识，决定文件名和表头（区分不同任务的 CSV）。
      不传则用全局 SEARCH_KEYWORD（远程软件任务）。例：远程软件 / 大模型深圳 / 职位tab。
    - since：只导出 applied_at >= since 的记录（本次运行起始时间戳），
      避免把 applied_jobs.json 里历史累计的所有任务记录混进同一个 CSV。不传则导全部。
    文件名例：投递记录_大模型深圳_20260613_213000.csv
    用 utf-8-sig（带 BOM），Excel 打开中文不乱码。返回 CSV 路径。
    """
    import csv
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    kw = re.sub(r"\s+", "", label or SEARCH_KEYWORD)
    fname = f"投递记录_{kw}_{ts}.csv"
    path = REPORTS_DIR / fname
    jobs = data.get("jobs", [])
    if since:
        jobs = [j for j in jobs if (j.get("applied_at", "") or "") >= since]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"任务：{label or SEARCH_KEYWORD}",
                    f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    f"本次投递数：{len(jobs)}",
                    (f"统计区间：{since} 起" if since else "统计区间：全部历史")])
        w.writerow(["序号", "公司", "职位", "城市/来源", "投递时间"])
        for i, j in enumerate(jobs, 1):
            w.writerow([i, j.get("company", ""), j.get("position", ""),
                        j.get("city", ""), j.get("applied_at", "")])
    return str(path)


def human_delay(min_s: float = None, max_s: float = None):
    """模拟人类随机延迟。默认用当前档位的 DELAY_MIN/MAX（运行时由 --speed 决定）。"""
    lo = DELAY_MIN if min_s is None else min_s
    hi = DELAY_MAX if max_s is None else max_s
    time.sleep(random.uniform(lo, hi))


def _prompt_once(msg: str = ""):
    """阻塞式等待用户回车（放在 executor 里调用，避免阻塞事件循环）。EOF/无终端时静候。"""
    try:
        return input(msg)
    except (EOFError, OSError):
        time.sleep(5)
        return ""


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

def _is_multimodal_payload(payload: dict) -> bool:
    """payload 是否含图片（用于免费模型耗尽后选对应的收费多模态兜底链）。"""
    try:
        for msg in payload.get("messages", []):
            c = msg.get("content")
            if isinstance(c, list) and any(
                    isinstance(p, dict) and p.get("type") == "image_url" for p in c):
                return True
    except Exception:
        pass
    return False


async def _try_models_once(payload: dict, model_list: list) -> tuple:
    """对给定模型列表各试一次。返回 (成功结果 or None, 是否需退避重试, retry_after秒, 末次错误)。

    - 2xx 成功 → 返回结果
    - 429/5xx → 该模型限流/服务端错误，换下个；整轮都这样则上层退避重试
    - 402/401/403 → 余额/鉴权问题，换下个模型（免费链遇 402 极少；收费链遇 402=没钱）
    """
    retry_after = 0
    last_err = None
    transient = False
    for m in model_list:
        if not m:
            continue
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
                if resp.status_code in (429, 500, 502, 503, 408, 409):
                    transient = True
                    last_err = f"{m}:{resp.status_code}"
                    try:
                        meta = resp.json().get("error", {}).get("metadata", {})
                        retry_after = max(retry_after, int(float(meta.get("retry_after_seconds", 0))))
                    except Exception:
                        pass
                    continue
                if resp.status_code in (401, 402, 403):
                    # 余额/权限问题：换下个模型（可能升级到收费链时才有意义）
                    last_err = f"{m}:{resp.status_code}"
                    continue
                resp.raise_for_status()
                return resp.json(), False, 0, None
        except Exception as e:
            transient = True
            last_err = f"{m}:{str(e)[:40]}"
            continue
    return None, transient, retry_after, last_err


async def _post_openrouter(payload: dict, models: list = None, max_rounds: int = 3,
                           paid_models: list = None) -> dict:
    """
    调用 OpenRouter，三级容错：免费模型 fallback 链 → 多轮退避重试 → 升级收费模型。
    - models：依次尝试的免费 model id 列表（provider 常被打满 429，逐个试）。
    - 单模型失败立即换下一个；整轮全失败则退避等待重试整轮（最多 max_rounds 轮）。
    - 免费链多轮仍失败 → 自动升级到收费模型兜底链（paid_models，不传则按是否多模态
      自动选 VERIFY_MODELS_TEXT_PAID / VERIFY_MODELS_MULTIMODAL_PAID），保证任务不中断。
    - 尊重 429 响应里的 retry_after_seconds。
    """
    model_list = models or [payload.get("model")]
    delay = 4.0
    last_err = None
    for rnd in range(max_rounds):
        result, transient, retry_after, err = await _try_models_once(payload, model_list)
        if result is not None:
            return result
        last_err = err or last_err
        if rnd < max_rounds - 1:
            wait = max(delay, retry_after)
            print(f"  ⏳ 免费模型全部失败({last_err})，{wait:.0f}s 后重试整轮 ({rnd+1}/{max_rounds})", flush=True)
            await asyncio.sleep(wait)
            delay = min(delay * 2, 40)

    # 免费链多轮仍失败 → 升级收费模型兜底（仅当 --allow-paid-fallback 打开）
    if not ALLOW_PAID_FALLBACK:
        raise RuntimeError(
            f"OpenRouter 免费模型多轮重试仍失败: {last_err}"
            f"（未开启 --allow-paid-fallback，不升级收费模型）")
    if paid_models is None:
        paid_models = (VERIFY_MODELS_MULTIMODAL_PAID if _is_multimodal_payload(payload)
                       else VERIFY_MODELS_TEXT_PAID)
    if paid_models:
        print(f"  💳 免费模型多轮失败({last_err})，升级到收费模型兜底: {paid_models}", flush=True)
        for rnd in range(2):
            result, transient, retry_after, err = await _try_models_once(payload, paid_models)
            if result is not None:
                print(f"  ✅ 收费模型成功: {payload.get('model')}", flush=True)
                return result
            last_err = err or last_err
            if rnd < 1:
                await asyncio.sleep(max(4.0, retry_after))
    raise RuntimeError(f"OpenRouter 免费+收费模型多轮重试仍失败: {last_err}")


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


async def _post_uitars_local(payload: dict) -> dict:
    """
    调用本地/局域网 llama-cpp-python server，复用 inference_client.UITarsClient。
    - UITARS_LOCAL_URL：/v1 前缀，如 http://192.168.3.14:8000/v1
    - frequency_penalty=1 由 UITarsClient 内部强制设置
    - model 字段：UITARS_LOCAL_MODEL 或自动从 /v1/models 取第一个
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent / "ui-tars-server"))
    from inference_client import UITarsClient as _UITarsClient
    from openai import OpenAI as _OpenAI

    model = UITARS_LOCAL_MODEL
    if not model:
        _c = _OpenAI(base_url=UITARS_LOCAL_URL, api_key="none", timeout=10.0)
        model = _c.models.list().data[0].id

    # 直接调用 OpenAI SDK（与 openrouter/_post_openrouter 结构完全对称）
    _client = _OpenAI(base_url=UITARS_LOCAL_URL, api_key="none", timeout=120.0)
    msgs = payload["messages"]
    resp = _client.chat.completions.create(
        model=model,
        messages=msgs,
        max_tokens=payload.get("max_tokens", 512),
        frequency_penalty=1,   # 官方要求，强制覆盖
    )
    return {"choices": [{"message": {"content": resp.choices[0].message.content}}]}


async def call_uitars(image_path: str, task_prompt: str) -> str:
    """
    调用 UI-TARS 模型（仅在选择器兜底时使用），返回含 Thought/Action 的响应。
    根据 UITARS_PROVIDER 分三种提供方式：
      - openrouter：走 OpenRouter（OpenRouter key）
      - remote    ：走 _post_uitars_remote，POST 到 UITARS_ENDPOINT，x-api-key 鉴权
      - local     ：走 _post_uitars_local，连接 UITARS_LOCAL_URL 的 llama-cpp-python server
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

    async def _call_provider(provider: str) -> str:
        """按 provider 发一次请求并取 content；失败抛异常、空响应返回空串。"""
        if provider == "remote":
            result = await _post_uitars_remote(payload)
        elif provider == "local":
            result = await _post_uitars_local(payload)
        else:  # openrouter
            # openrouter UI-TARS 走 bytedance/ui-tars 模型（收费）；单模型，不走免费 verify 链
            payload["model"] = UITARS_MODEL
            result = await _post_openrouter(payload, models=[UITARS_MODEL], paid_models=[])
        content = result["choices"][0]["message"]["content"]
        return content if (content and content.strip()) else ""

    # 容错重试：当前 provider 重试 3 次（指数退避）。本地/remote 连续失败后，
    # 若开启 --allow-paid-fallback，则切换到 OpenRouter UI-TARS 再试（用户要求）。
    last_err = None
    for attempt in range(3):
        try:
            content = await _call_provider(UITARS_PROVIDER)
            if content:
                return content
            last_err = "空响应"
        except Exception as e:
            last_err = str(e)[:80]
        if attempt < 2:
            print(f"  ⏳ UI-TARS({UITARS_PROVIDER}) 调用失败({last_err})，重试 ({attempt+1}/3)", flush=True)
            await asyncio.sleep(2.0 * (attempt + 1))

    # 本地/remote 连续失败 → 切 OpenRouter UI-TARS 兜底（需 --allow-paid-fallback）
    if UITARS_PROVIDER in ("local", "remote") and ALLOW_PAID_FALLBACK:
        print(f"  💳 本地 UI-TARS 连续失败({last_err})，切换到 OpenRouter UI-TARS 兜底", flush=True)
        for attempt in range(2):
            try:
                content = await _call_provider("openrouter")
                if content:
                    print("  ✅ OpenRouter UI-TARS 兜底成功", flush=True)
                    return content
            except Exception as e:
                last_err = str(e)[:80]
            await asyncio.sleep(2.0)
    print(f"  [WARN] UI-TARS 重试仍失败: {last_err}", flush=True)
    return ""


def _is_salary_obfuscated(salary_text: str) -> bool:
    """薪资文本是否被字体反爬混淆（含私有区字符 U+E000–U+F8FF）。"""
    return any("" <= ch <= "" for ch in (salary_text or ""))


# 注：原 read_salary_via_multimodal（截图+多模态OCR读薪资）已删除。
# 运行时禁止用多模态 OCR 抓文字（太慢太贵）。Boss直聘薪资字体反爬改为
# 拦截列表 API joblist.json 取明文 salaryDesc（见 zhipin_llm_sz / zhipin_position_tabs）。


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
        if parsed:
            return parsed[0]
    except Exception as e:
        # 本地 UI-TARS-1.5 常返回 <point>X Y</point> 坐标格式，ui_tars 包解析器
        # （qwen25vl）不认会抛 "could not convert string to float: '<point>703'"。
        # 退化用正则自行解析 action + 坐标。
        fb = _fallback_parse_uitars(response)
        if fb:
            return fb
        print(f"  [WARN] 动作解析失败: {e}")
        return None
    # 标准解析返回空 → 也尝试 fallback
    return _fallback_parse_uitars(response)


def _fallback_parse_uitars(response: str) -> dict | None:
    """正则兜底解析 UI-TARS 响应（支持 <point>X Y</point> / (X,Y) / [x1,y1,x2,y2]）。

    坐标统一按 0-1000 归一化到 0-1 的 start_box 字符串 "[x,y,x,y]"，与标准路径一致。
    """
    if not response:
        return None
    text = response
    # 动作类型
    m_act = re.search(r"\b(left_double|left_single|right_single|click|type|scroll|"
                      r"drag|hotkey|wait|finished)\b", text, re.I)
    action_type = (m_act.group(1).lower() if m_act else "click")
    if action_type == "click":
        action_type = "click"
    # 坐标：优先 <point>X Y</point>，再 (X,Y)，再 [x1,y1,x2,y2]
    nums = None
    m = re.search(r"<point>\s*(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)\s*</point>", text)
    if m:
        nums = [float(m.group(1)), float(m.group(2))]
    if nums is None:
        m = re.search(r"\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\)", text)
        if m:
            nums = [float(m.group(1)), float(m.group(2))]
    if nums is None:
        m = re.search(r"\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)", text)
        if m:
            nums = [float(m.group(1)), float(m.group(2))]
    inputs = {}
    if nums:
        # 0-1000 → 0-1 归一化；start_box 用 [x,y,x,y] 点框
        x = nums[0] / 1000.0
        y = nums[1] / 1000.0
        inputs["start_box"] = json.dumps([x, y, x, y])
    # type 动作的文本内容
    m_txt = re.search(r"(?:content|text)\s*=\s*['\"](.+?)['\"]", text, re.S)
    if m_txt:
        inputs["content"] = m_txt.group(1)
    if not inputs:
        return None
    return {"action_type": action_type, "action_inputs": inputs}


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
    def __init__(self, verify_fn=None, dry_run=False):
        """
        verify_fn: 职位判断函数，签名为 async (title, desc, salary="") -> (bool, str)
                   默认为 None，此时 apply_to_job 使用模块级 verify_job_is_it_remote。
                   通过注入不同的 verify_fn，同一个 Automator 可服务：
                     - 远程岗任务（verify_job_is_it_remote）
                     - 大模型深圳任务（verify_llm_sz）
                     - 职位 tab 混合任务（verify_mixed）
        dry_run:   调试模式。为 True 时，apply_to_job 完成检查+判断+打印结论，但
                   【不点立即沟通、不发招呼、不记录投递】，用于安全验证筛选逻辑。
        """
        self.verify_fn = verify_fn  # 可注入的职位判断函数
        self.dry_run = dry_run
        self.stop_requested = False  # 当日沟通次数用完时置 True，各处理循环检测后停止
        # 本次运行起始时间戳：用于 CSV 只导出本轮投递（避免混入历史累计记录）
        self._run_started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # CSV/断点任务标识（子类覆盖：远程软件 / 大模型深圳 / 职位tab）
        self.task_label = re.sub(r"\s+", "", SEARCH_KEYWORD)
        # 可注入的薪资解析器：async (page) -> 真实薪资字符串。
        # 用于应对字体反爬（薪资文本被混淆），由需要薪资过滤的任务（如大模型深圳）设置为
        # 截图+多模态读取。默认 None，apply_to_job 直接用职位卡的 salary 文本。
        self.salary_resolver = None
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
        human_delay(1.2, 2.0)
        title = await self.page.title()
        print(f"  页面标题: {title} | URL: {self.page.url}", flush=True)
        await self._check_anti_scrape()

    async def _detect_verify(self) -> bool:
        """仅检测当前页是否为安全验证页（不处理）。基于实地观察的 BOSS直聘 Geetest 验证：
          - URL 落到 /web/passport/zp/verify.html
          - 标题"安全验证 - BOSS直聘"
          - DOM 出现 .verify-container / .geetest_holder / .geetest_radar_btn 等
        点击"点击按钮进行验证"会升级到【图标点选】图片题（需人工解），故只检测、不自动点。
        """
        try:
            url = (self.page.url or "").lower()
            if "passport/zp/verify" in url or "verify.html" in url:
                return True
            title = (await self.page.title()) or ""
            if "安全验证" in title:
                return True
            for sel in [".verify-container", ".page-verify", ".geetest_holder",
                        ".geetest_radar_btn", "#verifyMsg"]:
                try:
                    el = await self.page.query_selector(sel)
                    if el and await el.is_visible():
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    async def _check_anti_scrape(self) -> bool:
        """每次关键操作前调用：检测安全验证；命中则①升级 slow 延迟档②停下提示用户手动处理。

        返回 True 表示检测到验证并已暂停处理。实地验证确认：点击验证按钮会进入图标点选
        图片题，无法可靠自动解（且运行时禁用多模态OCR）——所以一律交给用户手动完成。
        """
        if not await self._detect_verify():
            return False
        # ① 操作太频繁触发反爬 → 自动升级到 slow 延迟档（若还不是）
        if SPEED_TIER != "slow":
            print(f"  🐢 检测到安全验证(反爬)，操作过频 → 延迟档 {SPEED_TIER} 升级到 slow", flush=True)
            apply_speed_profile("slow")
        # ② 截图 + 暂停等用户在浏览器手动完成验证
        print("\n  🛑 检测到【安全验证】页面（触发反爬）。请在浏览器中手动完成验证（点击按钮→"
              "完成图标点选）。", flush=True)
        try:
            await screenshot_page(self.page, "anti_scrape_verify.png")
        except Exception:
            pass
        # 轮询等待用户解除验证（页面离开 verify 页即视为完成）；最长等 10 分钟
        for i in range(120):
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, _prompt_once, "  完成验证后按 Enter 继续（或等待自动检测）... ")
            except Exception:
                await asyncio.sleep(5)
            if not await self._detect_verify():
                print("  ✅ 安全验证已解除，继续运行", flush=True)
                return True
            print("  ⏳ 仍在验证页，请完成验证...", flush=True)
        print("  ⚠️ 等待验证超时（10分钟），继续尝试", flush=True)
        return True

    async def _guard(self) -> bool:
        """操作前守卫：检测到验证返回 True（调用方应跳过本次操作/重试）。供各操作循环调用。"""
        return await self._check_anti_scrape()

    def _mark_processed(self, company: str, title: str, city: str = "", status: str = ""):
        """断点续跑：标记一个职位已处理（判断完），并周期性落盘断点文件。

        status=="fail"（点击/LLM/网络等出错）的职位【不标记】，以便网络/服务恢复后
        重启能重新处理它，避免把临时失败的职位永久跳过。
        """
        if status == "fail":
            return
        if not hasattr(self, "_ckpt_processed"):
            self._ckpt_processed = load_checkpoint(getattr(self, "task_label", ""))["processed"]
        key = f"{(company or '').strip()}|{(title or '').strip()}"
        self._ckpt_processed.add(key)
        # 每处理 5 个落盘一次（降低 IO，崩溃最多丢几条）
        self._ckpt_dirty = getattr(self, "_ckpt_dirty", 0) + 1
        if self._ckpt_dirty >= 5:
            _save_checkpoint(getattr(self, "task_label", ""), self._ckpt_processed, city)
            self._ckpt_dirty = 0

    def _flush_checkpoint(self, city: str = ""):
        """强制落盘当前断点（城市切换/结束时调用）。"""
        if hasattr(self, "_ckpt_processed"):
            _save_checkpoint(getattr(self, "task_label", ""), self._ckpt_processed, city)
            self._ckpt_dirty = 0

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
            human_delay(1.2, 2.0)
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
        human_delay(1.0, 1.8)

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
                human_delay(1.2, 2.0)
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
                    human_delay(1.2, 2.0)
            except Exception as e:
                print(f"  [WARN] 列表导航失败(尝试{attempt+1}): {e}")
        return False

    async def _settle_after_navigation(self, attempts: int = 6):
        """等待 in-flight 导航完成、职位列表稳定，再返回。

        点击 tab / 切换城市等会触发【异步导航】，导航期间任何 query 都会抛
        "Execution context was destroyed, most likely because of a navigation"。
        本方法反复尝试：等 load 状态 → 查询卡片数；遇到导航异常就等待后重试，
        直到能稳定查到卡片（或用尽次数）。
        """
        for i in range(attempts):
            try:
                try:
                    await self.page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                try:
                    await self.page.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    pass
                # 试查一次卡片——若正在导航这里会抛异常
                await self.page.wait_for_selector(".job-card-box", timeout=8000)
                _ = await self.page.query_selector_all(".job-card-box")
                human_delay(0.5, 1.0)
                return
            except Exception as e:
                msg = str(e)
                if "context was destroyed" in msg or "navigation" in msg.lower():
                    # 导航仍在进行，稍等再试
                    human_delay(0.8, 1.5)
                    continue
                # 其它异常（如选择器超时）：再给一次机会
                human_delay(0.5, 1.0)
        # 用尽次数也返回，后续查询自行兜底

    async def _scroll_load_all_cards(self, max_scrolls: int = 40,
                                     stable_rounds: int = 3) -> int:
        """
        Boss直聘新版搜索/列表页是【无限滚动懒加载】，URL 的 &page=N 参数实测无效
        （page=1/2/3 返回同一批职位）。goto 后页面只渲染首屏约 15 个 .job-card-box，
        必须持续向下滚动，新职位卡才会被陆续插入 DOM。

        本方法滚动到底：每次下滚一屏并等待，直到连续 stable_rounds 次卡片数不再增长
        （判定已加载完本次搜索的全部职位），或达到 max_scrolls 上限。
        返回滚动后页面上的 .job-card-box 总数。

        实测（query=远程 软件, city=深圳）：首屏 15 → 滚到底约 120，漏抓时丢失约 87%。
        """
        async def _count():
            try:
                return len(await self.page.query_selector_all(".job-card-box"))
            except Exception:
                # 导航中途查询失败 → 等稳定后再数
                await self._settle_after_navigation(attempts=3)
                try:
                    return len(await self.page.query_selector_all(".job-card-box"))
                except Exception:
                    return 0

        last = await _count()
        stable = 0
        for _ in range(max_scrolls):
            try:
                await self.page.mouse.wheel(0, 1400)
            except Exception:
                pass
            human_delay(SCROLL_WAIT_MIN, SCROLL_WAIT_MAX)
            n = await _count()
            if n <= last:
                stable += 1
                if stable >= stable_rounds:
                    break
            else:
                stable = 0
            last = n
        # 回到列表顶部，保证后续逐卡 click/scroll_into_view 从头开始、坐标稳定
        try:
            await self.page.mouse.wheel(0, -100000)
            human_delay(0.5, 1.0)
        except Exception:
            pass
        print(f"  📜 滚动懒加载完成：本页共 {last} 个职位卡（首屏仅约15，滚动后加载全部）")
        return last

    async def get_job_listings(self) -> list[dict]:
        """提取当前搜索结果页的职位列表（选择器经实测：.job-card-box）。

        ⚠️ 必须先滚动懒加载到底再抓取——新版列表页 goto 后只渲染首屏~15 个卡片，
        不滚动会漏掉本次搜索 80%+ 的职位（用户反馈"符合条件的职位没投递"的根因）。
        """
        jobs = []
        try:
            # 关键：抓取前先等导航/列表稳定。点 tab 等操作会触发异步导航，
            # 若在导航过程中查询会报 "Execution context was destroyed"。
            await self._settle_after_navigation()
            # 关键修复：先滚动到底把全部懒加载职位卡加载进 DOM，再统一抓取
            await self._scroll_load_all_cards()
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

    async def _click_card_by_text(self, title: str, company: str) -> bool:
        """用 Playwright Locator 按 title(+company) 定位并点击职位卡。

        关键：Locator 是惰性的，点击/滚动时才解析 DOM 并自动重试，因此对 Boss直聘
        SPA 列表的重渲染（句柄 detach）免疫——这是替代 stale ElementHandle 的正确做法。
        返回是否成功点击。
        """
        title = (title or "").strip()
        company = (company or "").strip()
        if not title:
            return False

        # 优先 title+company 双重过滤（避免同名标题歧义），失败再退化为仅 title
        candidates = []
        loc_tc = self.page.locator(".job-card-box").filter(
            has=self.page.locator(".job-name", has_text=title))
        if company:
            loc_tc = loc_tc.filter(has=self.page.locator(".boss-name, .company-name",
                                                         has_text=company))
        candidates.append(loc_tc.first)
        candidates.append(
            self.page.locator(".job-card-box").filter(
                has=self.page.locator(".job-name", has_text=title)).first)

        for loc in candidates:
            try:
                # 目标卡可能在懒加载下方未渲染：先确认存在，必要时滚动加载
                if await loc.count() == 0:
                    for _ in range(20):
                        try:
                            await self.page.mouse.wheel(0, 1400)
                        except Exception:
                            break
                        human_delay(0.25, 0.5)
                        if await loc.count() > 0:
                            break
                if await loc.count() == 0:
                    continue
                await loc.scroll_into_view_if_needed(timeout=5000)
                human_delay(0.3, 0.7)
                bb = await loc.bounding_box()
                if bb:
                    await human_mouse_move_and_click(
                        self.page, int(bb["x"] + bb["width"] / 2),
                        int(bb["y"] + bb["height"] / 2))
                else:
                    await loc.click(timeout=5000)
                return True
            except Exception:
                continue
        return False

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

    async def _confirm_greet_sent(self) -> bool:
        """确认点'立即沟通'后招呼【真的发出去了】。成功信号（任一）：
          - 出现"已向BOSS发送消息"弹窗 .greet-boss-dialog
          - 按钮变成"继续沟通"（说明已建立会话）
          - 页面跳到聊天页 /chat
        轮询 ~3 秒。没有任一信号 → 视为未发送（可能触发反爬/点空）。
        """
        for _ in range(6):
            try:
                d = await self.page.query_selector(".greet-boss-dialog")
                if d and await d.is_visible():
                    return True
                if "/chat" in (self.page.url or "").lower():
                    return True
                cont = await self.page.query_selector("a:has-text('继续沟通')")
                if cont and await cont.is_visible():
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False

    async def _verify_greet_in_messages(self, company: str, title: str) -> bool:
        """去【消息】页核验确实给该 boss 发了招呼（每城前3个用，最终事实校验）。

        独立开一个新标签页访问消息页，找最近会话核对公司名+是否有已发消息，
        截图留证。不干扰主列表页。校验失败只告警+截图，不影响投递记录。
        返回 True=核验到已发送，False=未核验到，None=核验过程异常。
        """
        vp = None
        try:
            vp = await self.context.new_page()
            await vp.goto("https://www.zhipin.com/web/geek/chat", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2.5)
            info = await vp.evaluate(r"""(company) => {
                const items=[...document.querySelectorAll('.user-list li, [class*="chat-list"] li, [role="listitem"]')];
                const out={count:items.length, top:'', matched:false, hasMsg:false};
                for(let i=0;i<Math.min(items.length,5);i++){
                    const t=(items[i].textContent||'').trim();
                    if(i===0) out.top=t.slice(0,60);
                    if(company && t.includes(company.slice(0,4))){ out.matched=true; }
                }
                // 是否有"已发送/打招呼"等痕迹
                out.hasMsg=/已发送|你好|您好|打招呼|请问|发简历|简历/.test(document.body.textContent||'');
                return out;
            }""", company)
            safe = re.sub(r"[^\w一-龥]", "_", f"{company}_{title}")[:40]
            await vp.screenshot(path=str(SCREENSHOTS_DIR / f"verify_msg_{safe}.png"))
            ok = info.get("matched") or (info.get("count", 0) > 0 and info.get("hasMsg"))
            mark = "✅ 已核验" if ok else "⚠️ 未核验到"
            print(f"     🔍 [消息页核验] {mark}：会话数={info.get('count')} 顶部会话='{info.get('top')}' "
                  f"匹配公司={info.get('matched')}（截图 verify_msg_{safe}.png）", flush=True)
            return ok
        except Exception as e:
            print(f"     [WARN] 消息页核验异常: {str(e)[:60]}", flush=True)
            return None
        finally:
            try:
                if vp:
                    await vp.close()
            except Exception:
                pass

    async def _handle_limit_popup(self) -> str:
        """
        处理 zhipin 每日沟通次数限制弹窗（"温馨提示"）：
          - 若提示"还剩 X 次"等（未用完）→ 点"好/我知道了/确定"关闭，返回 "dismissed"
          - 若提示"当日/今日沟通次数已用完/已达上限"→ 设置停止标志，返回 "exhausted"
          - 没有此弹窗 → 返回 ""
        该弹窗会遮挡后续点击，必须先 dismiss。
        """
        try:
            # 弹窗文本：实测每日限制弹窗类名为 .chat-block-dialog（遮罩 .chat-block-layer）。
            # 也兼容其他含"温馨提示/沟通次数"的对话框。
            body = ""
            for sel in [".chat-block-dialog", "[class*='chat-block']",
                        "[class*='dialog']", "[class*='modal']", "[class*='popup']"]:
                els = await self.page.query_selector_all(sel)
                for el in els:
                    if not await el.is_visible():
                        continue
                    t = (await el.text_content() or "")
                    # 仅匹配真正的次数限制弹窗，避免误匹配"已向BOSS发送消息(含'打招呼'字样)"的招呼确认弹窗
                    if "温馨提示" in t or "沟通次数" in t or "沟通机会" in t:
                        body = t
                        break
                if body:
                    break
            if not body:
                return ""

            # 判断是否次数用完
            exhausted_kw = ["已用完", "用完了", "已达上限", "达到上限", "次数已用尽",
                            "今日沟通次数已用完", "当日沟通次数已用完", "明天再来", "已用尽"]
            if any(k in body for k in exhausted_kw):
                print(f"  🛑 检测到【当日沟通次数已用完】弹窗，停止脚本（明天再跑）。提示原文片段: {body[:60]}", flush=True)
                self.stop_requested = True
                return "exhausted"

            # 否则是"还剩X次"的温馨提示 → 点"好"关闭
            print(f"  ℹ️ 温馨提示弹窗（剩余次数提醒），点击'好'关闭。原文片段: {body[:50]}", flush=True)
            for btn_sel in [".chat-block-dialog button:has-text('好')",
                            ".chat-block-dialog .btn:has-text('好')",
                            ".chat-block-dialog a:has-text('好')",
                            "button:has-text('好')", "button:has-text('我知道了')",
                            "button:has-text('知道了')", "button:has-text('确定')",
                            "[class*='dialog'] [class*='btn']:has-text('好')",
                            "a:has-text('好')", ".btn:has-text('好')"]:
                try:
                    b = await self.page.query_selector(btn_sel)
                    if b and await b.is_visible():
                        await b.click()
                        human_delay(0.6, 1.2)
                        return "dismissed"
                except Exception:
                    continue
            # 兜底 Escape
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass
            return "dismissed"
        except Exception as e:
            print(f"  [WARN] 处理温馨提示弹窗出错: {e}", flush=True)
            return ""

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

        # 断点续跑：本次/今天已处理过(判断过)的职位直接跳过，不重复点击/LLM判断
        if not hasattr(self, "_ckpt_processed"):
            self._ckpt_processed = load_checkpoint(getattr(self, "task_label", ""))["processed"]
        _ckey = f"{company.strip()}|{title.strip()}"
        if _ckey in self._ckpt_processed:
            print(f"  ⏭️  [断点跳过-已处理] {company} | {title}")
            return "dup"

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

        # 暂存当前职位地点，供需要 location 的 verify_fn（如职位tab混合判断）读取
        self._current_location = job.get("location", "")
        # 暂存当前职位标题/公司，供需要的子类（如大模型深圳从API映射查明文薪资）使用
        self._current_title = job.get("title", "")
        self._current_company = job.get("company", "")

        try:
            # 操作前守卫：检测到安全验证则暂停等用户处理（每个职位点击前都检测，避免空跑卡住）
            await self._check_anti_scrape()
            # 点职位卡 → 详情面板（检查阶段，快速延迟）
            # ⚠️ 不能用 get_job_listings 时存下的 ElementHandle：Boss直聘 SPA 列表会持续
            # 重渲染（点开详情/轮询刷新），存的句柄会 detach（"Element is not attached"）。
            # 用 Playwright Locator（点击时才解析、自动重试/滚动），对重渲染免疫。
            clicked = await self._click_card_by_text(title, company)
            if not clicked:
                # 可能是验证页挡住了列表：再检测一次，若是验证则等用户处理后让上层重试
                if await self._check_anti_scrape():
                    return "fail"
                print(f"  [WARN] 未能定位/点击职位卡，跳过: {company} | {title}")
                return "fail"
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
            # 薪资若被字体反爬混淆，且设置了薪资解析器 → 截图+多模态读真实薪资
            if self.salary_resolver and _is_salary_obfuscated(salary):
                real = await self.salary_resolver(self.page)
                if real:
                    print(f"  💰 薪资字体反爬，多模态读出: {real}（原始混淆文本已替换）")
                    salary = real

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

            # dry-run 调试模式：判断通过即停，不点立即沟通/不发招呼/不记录
            if self.dry_run:
                print(f"  🧪 [dry-run] 本应投递（未实际发招呼/未记录）: {company} | {title}")
                return "would_apply"

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

            # 处理每日沟通次数限制"温馨提示"弹窗（可能挡住后续操作）
            limit = await self._handle_limit_popup()
            if limit == "exhausted":
                # 当日次数用完：本职位未成功投递，标志已置位，调用方循环会停止
                return "limit_exhausted"

            # ⚠️ 关键：必须【确认招呼真的发出去了】才算投递成功。
            # 之前只要点了按钮+关弹窗就记 applied，但若点击时触发反爬/验证、或按钮点空，
            # 招呼根本没发，却被记成假投递（用户在 app 端看不到任何投递）。
            sent = await self._confirm_greet_sent()
            if not sent:
                await screenshot_page(self.page, f"greet_fail_{safe}.png")
                # 可能是触发了安全验证 → 检测+暂停等用户处理
                if await self._check_anti_scrape():
                    print(f"  ⚠️ [未投递-触发安全验证] {company} | {title}（已暂停处理，未记录）")
                    return "fail"
                print(f"  ⚠️ [未投递-未确认招呼发送] {company} | {title}（未出现'已发送'确认，不记录）")
                await self._close_greet_dialog()
                return "fail"

            # 确认已发送 → 关闭"已向BOSS发送消息"弹窗（避免遮罩挡住下个职位）
            await self._close_greet_dialog()
            # 关闭后可能再弹温馨提示，再处理一次
            limit = await self._handle_limit_popup()
            if limit == "exhausted":
                return "limit_exhausted"

            # 记录投递（已确认打招呼语发送成功 = 完成投递）
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

        # 导航到列表页 + 滚动懒加载抓取全部职位后逐个投递。
        # ⚠️ 重要：Boss直聘新版列表页【无限滚动懒加载，URL &page=N 实测无效】
        # （page=1/2/3 返回同一批职位）。早先"靠 &page 翻 5 页"的写法实际每页都拿
        # 同一批首屏 15 个，去重后等于只处理首屏，漏掉本次搜索 80%+ 的职位。
        # 现改为：goto 第 1 页 → get_job_listings 内部滚动到底加载全部 → 一次性处理。
        any_page_ok = False
        # 切城市/进列表后先检测安全验证（导航是最易触发反爬的时机）
        await self._check_anti_scrape()
        if not await self.goto_list(city, 1):
            print(f"  ❌ 列表无职位，跳过城市: {city}")
        else:
            any_page_ok = True
            await screenshot_page(self.page, f"results_{city}.png")

            # get_job_listings 已内置滚动懒加载到底，返回本次搜索全部职位
            jobs = await self.get_job_listings()
            if not jobs:
                print(f"  ⚠️ 滚动加载后仍无职位")
            else:
                print(f"  📋 共找到 {len(jobs)} 个职位（已滚动加载全部），逐个检查...")
                verified_count = 0  # 本城已去消息页核验的成功投递数（前3个核验）
                for job in jobs:
                    status = await self.apply_to_job(job, city)
                    stat["checked"] += 1
                    if status in stat:
                        stat[status] += 1
                    # 断点续跑：记录此职位已处理（含判断完跳过的），落盘
                    self._mark_processed(job.get("company", ""), job.get("title", ""), city, status)
                    # 每个城市前 3 个【投递成功】的，去消息页核验确实发了招呼（用户要求）
                    if status == "applied" and verified_count < 3:
                        verified_count += 1
                        print(f"     🔍 第 {verified_count}/3 个成功投递，去消息页核验...", flush=True)
                        await self._verify_greet_in_messages(job.get("company", ""), job.get("title", ""))
                        # 核验开了新标签页/可能切走焦点，回到列表页确保后续点击正常
                        try:
                            await self.page.bring_to_front()
                        except Exception:
                            pass
                    # 实时累计进度提示
                    skipped = stat['reject'] + stat['dup'] + stat['contacted'] + stat['blocked']
                    print(f"     ▸ [{city}] 进度：检查 {stat['checked']}/{len(jobs)} | "
                          f"投递 {stat['applied']} | 跳过 {skipped} | 失败 {stat['fail']}")
                    if self.stop_requested:
                        print("  🛑 当日沟通次数已用完，停止本城市处理。", flush=True)
                        return stat
                    human_delay(DELAY_MIN, DELAY_MAX)

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
                    self._flush_checkpoint(city)  # 城市处理完落盘断点

                    if self.stop_requested:
                        print("\n🛑 当日沟通次数已用完，停止所有城市处理，明天再跑。", flush=True)
                        break

                    # 城市间休息（防止触发反爬，按速度档位）
                    rest_time = random.uniform(CITY_REST_MIN, CITY_REST_MAX)
                    print(f"\n  😴 城市间休息 {rest_time:.1f} 秒...")
                    await asyncio.sleep(rest_time)

                # 全部城市处理完（未被每日上限中断）→ 任务完整完成，清除断点
                if not self.stop_requested:
                    clear_checkpoint(self.task_label)

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
                print(f"🏙️ 已完成城市: {', '.join(self.applied_data.get('completed_cities', {})) or '无'}")
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
                    csv_path = export_applications_csv(
                        self.applied_data, label=self.task_label, since=self._run_started)
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
        help="UI-TARS 模型提供方式：openrouter（默认）/ remote（Kaggle/Colab x-api-key 鉴权）/ local（本地 llama-cpp-python server）。",
    )
    parser.add_argument(
        "--uitars-endpoint", default=None,
        help="remote 方式下 UI-TARS 的完整 URL（如 https://xxxx.ngrok.io/v1/chat/completions）。选 remote 时必填。",
    )
    parser.add_argument(
        "--uitars-key", default=None,
        help="remote 方式下 UI-TARS endpoint 的鉴权 key（放在 header 的 x-api-key 字段）。",
    )
    parser.add_argument(
        "--uitars-local-url", default=UITARS_LOCAL_URL,
        help=f"local 方式下 llama-cpp-python server 地址（/v1 前缀）。默认 {UITARS_LOCAL_URL}。示例：http://192.168.3.14:8000/v1",
    )
    parser.add_argument(
        "--uitars-local-model", default=None,
        help="local 方式下模型名称（通常是 GGUF 文件路径）。默认 None → 自动从 /v1/models 取第一个。",
    )
    parser.add_argument(
        "--speed", choices=["normal", "fast", "slow"], default="normal",
        help="操作延迟档位：normal(默认,稳健) | fast(快,量大时用) | slow(慢,触发反爬时用)。"
             "触发安全验证时会自动升级到 slow。",
    )
    parser.add_argument(
        "--allow-paid-fallback", action="store_true",
        help="允许在免费 LLM / 本地 UI-TARS 连续失败后，升级到 OpenRouter 收费 LLM / "
             "OpenRouter UI-TARS 兜底。默认关闭（只用免费/本地）。",
    )
    return parser


def main():
    """解析命令行参数，赋值到模块级全局变量后启动自动投递。"""
    global OPENROUTER_API_KEY, UITARS_PROVIDER, UITARS_ENDPOINT, UITARS_KEY, UITARS_LOCAL_URL, UITARS_LOCAL_MODEL
    global ALLOW_PAID_FALLBACK

    parser = _build_arg_parser()
    args = parser.parse_args()

    # 延迟档位 + 收费兜底开关
    apply_speed_profile(args.speed)
    ALLOW_PAID_FALLBACK = args.allow_paid_fallback
    print(f"⚙️ 操作延迟档位: {args.speed} | 收费兜底: {'开' if ALLOW_PAID_FALLBACK else '关'}", flush=True)

    # OpenRouter key：命令行 > 环境变量/.env（保留现有回退方式）
    if args.openrouter_key:
        OPENROUTER_API_KEY = args.openrouter_key

    # UI-TARS 提供方式
    UITARS_PROVIDER = args.uitars_provider
    UITARS_LOCAL_URL = args.uitars_local_url
    UITARS_LOCAL_MODEL = args.uitars_local_model
    if args.uitars_key:
        UITARS_KEY = args.uitars_key
    if args.uitars_endpoint:
        UITARS_ENDPOINT = args.uitars_endpoint

    # remote 方式必须提供 endpoint
    if UITARS_PROVIDER == "remote" and not UITARS_ENDPOINT:
        parser.error("--uitars-provider remote 需要同时指定 --uitars-endpoint")

    if UITARS_PROVIDER == "local":
        print(f"⚙️ UI-TARS 提供方式: local | server: {UITARS_LOCAL_URL}", flush=True)
    elif UITARS_PROVIDER == "remote":
        print(f"⚙️ UI-TARS 提供方式: remote | endpoint: {UITARS_ENDPOINT}", flush=True)
    else:
        print(f"⚙️ UI-TARS 提供方式: openrouter", flush=True)

    asyncio.run(BossZhipinAutomator().run())


if __name__ == "__main__":
    main()
