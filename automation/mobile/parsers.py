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
