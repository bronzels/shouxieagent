"""纯函数工具：时长解析、归一化坐标换算、UiAutomator2 XML 关键字定位/时长提取。"""
import re
import xml.etree.ElementTree as ET


def parse_duration_to_minutes(text: str) -> int | None:
    """从含时长的文本解析分钟数。支持「X小时Y分」「X分钟」「X.Y小时」「X小时」；
    含「过期/已用完」等视为 0；无任何数字返回 None。"""
    if text is None:
        return None
    if re.search(r"过期|已用完|用完|结束", text):
        return 0
    # X小时Y分
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:小时|时|h)\s*(\d+)\s*(?:分钟|分|m)", text)
    if m:
        return int(round(float(m.group(1)) * 60)) + int(m.group(2))
    # X小时 / X.Y小时
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:小时|时|h)\b", text)
    if m:
        return int(round(float(m.group(1)) * 60))
    # X分钟
    m = re.search(r"(\d+)\s*(?:分钟|分|m)\b", text)
    if m:
        return int(m.group(1))
    # 仅一个数字（兜底，按分钟）
    m = re.search(r"(\d+)", text)
    if m:
        return int(m.group(1))
    return None


def norm_to_pixel(nx: float, ny: float, width: int, height: int) -> tuple[int, int]:
    """0-1 归一化坐标 → 像素整数坐标。"""
    return (int(round(nx * width)), int(round(ny * height)))


def find_keyword_bounds(page_source_xml: str, keywords: list[str]) -> tuple[int, int] | None:
    """在 UiAutomator2 dump 的 XML 中找首个 text/content-desc 命中任一关键字的节点，
    返回 bounds 中心像素坐标 (cx, cy)；无命中返回 None。"""
    try:
        root = ET.fromstring(page_source_xml)
    except ET.ParseError:
        return None
    for node in root.iter():
        label = (node.get("text") or "") + " " + (node.get("content-desc") or "")
        if any(kw in label for kw in keywords):
            b = node.get("bounds") or ""
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
            if m:
                x1, y1, x2, y2 = map(int, m.groups())
                return ((x1 + x2) // 2, (y1 + y2) // 2)
    return None


def parse_required_seconds(text: str) -> int | None:
    """从文案里提取广告要求观看的秒数，如「看15秒可领取」「浏览 15 秒」→ 15；无则 None。"""
    if not text:
        return None
    m = re.search(r"(?:看|浏览|观看|播放)\s*(\d+)\s*秒", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*秒", text)
    return int(m.group(1)) if m else None


def parse_watch_progress(text: str) -> tuple[int, int] | None:
    """解析批量模式的观看进度。支持『已看2/5』『2/5条』『还需观看3条』『观看5条』等。
    返回 (已看, 需看)；只给出目标条数(如『观看5条』)时返回 (0, 5)；解析不出返回 None。"""
    if not text:
        return None
    m = re.search(r"(\d+)\s*/\s*(\d+)\s*条?", text)        # 2/5
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.search(r"已?看\D{0,4}(\d+)\D{0,6}(?:共|/|还需|再看)\D{0,4}(\d+)", text)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.search(r"(?:观看|看|浏览)\s*(\d+)\s*条", text)    # 观看5条 → 目标5
    if m:
        return (0, int(m.group(1)))
    return None


def classify_task_mode(text: str) -> str:
    """识别看广告领时长页是哪种模式：
      'scattered'：看一个广告立即奖励一段时长；
      'batch'    ：要累计观看多条/完成多任务才一次性发奖(有『观看N条』『X/Y』『做任务』等)；
      'both'     ：两种都有；
      'unknown'  ：无法判断。"""
    if not text:
        return "unknown"
    batch = bool(re.search(r"观看\s*\d+\s*条|看\s*\d+\s*条|\d+\s*/\s*\d+|"
                           r"做任务|任务列表|累计|集齐|全部完成|进度|解锁", text))
    scattered = bool(re.search(r"看(?:一个|1个|完)?广告.{0,6}(?:得|领|获得|\+).{0,4}\d+\s*(?:分钟|小时)|"
                               r"看视频得\d+|立即领取\d+\s*(?:分钟|小时)|每看", text))
    if batch and scattered:
        return "both"
    if batch:
        return "batch"
    if scattered:
        return "scattered"
    return "unknown"


_VALID_ACTIONS = {"watch", "wait", "close", "back", "home", "done"}


def parse_decision(text: str) -> dict | None:
    """解析 UI-TARS 的受限结构化决策输出，形如：
        ACTION=WATCH; LABEL=点击去浏览; SECONDS=15
    返回 {"action": <小写动作>, "label": str, "seconds": int|None}；解析不出返回 None。
    动作语义：watch=点看广告入口并定时观看; wait=广告播放中等待; close=关闭/领取奖励弹窗;
    back=干扰页返回; home=回主页(重启); done=已在可读时长的稳定页。"""
    if not text:
        return None
    ma = re.search(r"ACTION\s*[=:：]\s*([A-Za-z]+)", text)
    if not ma:
        return None
    action = ma.group(1).lower()
    if action not in _VALID_ACTIONS:
        return None
    ml = re.search(r"LABEL\s*[=:：]\s*([^\n;；]+)", text)
    label = ml.group(1).strip() if ml else ""
    if label.lower() in ("none", "无", "n/a", ""):
        label = ""
    ms = re.search(r"SECONDS\s*[=:：]\s*(\d+)", text)
    seconds = int(ms.group(1)) if ms else None
    return {"action": action, "label": label, "seconds": seconds}


_DISTRACTION_RE = re.compile(r"夺宝|宝箱|刮刮乐|抽奖|红包|金币|现金|福利|签到|"
                             r"马上去用|立即使用|开通|充值|下载|安装|领金|抽\b")


def is_distraction_label(label: str) -> bool:
    """LABEL/按钮文字是否属于与『看广告领听歌时长』无关的干扰项(夺宝/红包/充值等)。
    用于交叉校验 UI-TARS 把干扰按钮误判成 WATCH 的情况。"""
    return bool(label) and bool(_DISTRACTION_RE.search(label))


def decide_action(description: str) -> dict:
    """兜底：当结构化决策解析失败时，用关键词从散文描述里粗分类下一步动作（纯函数可单测）。
    返回 {"action": watch|wait|close|back|done, "label": 期望点击的按钮文字}。
    顺序：奖励到账→看广告入口→干扰页返回→正在播广告等待→主页→默认返回。
    （注意:干扰页判断放在『N秒等待』之前，避免『浏览5秒夺宝』被误判为正在播广告。）"""
    d = description or ""
    # 1) 领取成功/奖励到账 → 关闭奖励弹窗
    if re.search(r"领取成功|已获得|恭喜|奖励到账|成功领取|获得.*分钟", d):
        return {"action": "close", "label": "关闭"}
    # 2) 有看广告领【听歌时长】的入口 → 点它（须同时含看广告语义+领时长语义，排除夺宝/红包）
    if (re.search(r"看广告|看视频|点击去浏览|去浏览|观看视频", d)
            and re.search(r"听歌|畅听|时长|分钟|VIP|会员时长", d)
            and not re.search(r"夺宝|宝箱|刮刮乐|红包|金币|现金|抽奖", d)):
        for kw in ["点击去浏览", "去浏览", "看广告领", "看广告", "看视频领", "看视频得", "去观看"]:
            if kw in d:
                return {"action": "watch", "label": kw}
        return {"action": "watch", "label": "看广告"}
    # 3) 无关干扰页(内测版/夺宝/刮刮乐/活动/红包/升级) → 返回
    if re.search(r"内测版|夺宝|宝箱|刮刮乐|抽奖|红包|金币|现金|立即升级|邀请您|青少年", d):
        return {"action": "back", "label": ""}
    # 4) 正在播放广告 → 等
    if re.search(r"倒计时|正在播放|广告播放中|稍后可关闭|跳过广告|\d+\s*秒后", d):
        return {"action": "wait", "label": ""}
    # 5) 已在主页/播放器等稳定页 → 完成(由上层读时长/重启再领)
    if re.search(r"主页|推荐|乐库|首页|播放器|我的音乐|底部导航", d):
        return {"action": "done", "label": ""}
    return {"action": "back", "label": ""}


def extract_duration_from_xml(page_source_xml: str) -> int | None:
    """扫描 XML 所有 text/content-desc，返回首个**明确含时长单位**节点的分钟数；无则 None。
    只接受含「小时/时/分钟/分」单位的文本，避免误命中界面里的无关数字。"""
    try:
        root = ET.fromstring(page_source_xml)
    except ET.ParseError:
        return None
    for node in root.iter():
        label = (node.get("text") or "") + " " + (node.get("content-desc") or "")
        if not re.search(r"小时|时|分钟|分|畅听|时长", label):
            continue
        if not re.search(r"(\d+(?:\.\d+)?)\s*(?:小时|时|分钟|分|h|m)", label):
            continue
        mins = parse_duration_to_minutes(label)
        if mins is not None:
            return mins
    return None
