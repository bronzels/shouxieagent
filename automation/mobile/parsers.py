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


def decide_action(description: str) -> dict:
    """把 UI-TARS 对当前屏幕的文字描述分类成下一步动作（感知→决策，纯函数可单测）。
    返回 {"action": tap|wait|close|back|done, "label": 期望点击的按钮文字(tap/close时)}。
    酷狗启动/首页状态多变(开屏广告/内测版/挽留弹窗/夺宝游戏)，据描述里的关键词决策。"""
    d = description or ""
    # 1) 正在播放广告 → 等
    if re.search(r"倒计时|正在播放|广告播放|秒后|加载广告|skip|稍后可关闭|\d+\s*秒", d):
        return {"action": "wait", "label": ""}
    # 2) 领取成功/奖励到账 → 关闭奖励弹窗
    if re.search(r"领取成功|已获得|恭喜|奖励到账|成功领取|获得.*分钟", d):
        return {"action": "close", "label": "关闭"}
    # 3) 有看广告领时长的入口按钮 → 点它
    for kw in ["点击去浏览", "去浏览", "看广告领", "看广告", "看视频领", "看视频得",
               "免费领取", "领取时长", "点击领取", "去观看", "免费听歌"]:
        if kw in d:
            return {"action": "tap", "label": kw}
    # 4) 无关干扰页(内测版邀请/夺宝/刮刮乐/活动/红包/升级) → 返回
    if re.search(r"内测版|夺宝|刮刮乐|抽奖|红包|活动|立即升级|邀请您|青少年", d):
        return {"action": "back", "label": ""}
    # 5) 已在可看到时长的主页/无可操作 → 完成探索(由上层读时长)
    if re.search(r"主页|推荐|乐库|首页|播放器|我的音乐", d):
        return {"action": "done", "label": ""}
    # 默认：退一步回到可识别状态
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
