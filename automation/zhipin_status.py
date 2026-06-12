# -*- coding: utf-8 -*-
"""
对方回应状态记录（所有 apply/打招呼任务共享的过滤契约）

由「消息状态扫描任务」(zhipin_messages.py) 写入，被所有 apply/打招呼任务
（远程 / 大模型深圳 / 职位tab）在投递前读取，用于跳过"已经收到对方非未读回应"
的职位，节省每日打招呼次数。

设计动机：
- zhipin 系统本身对同一职位的重复打招呼有约 2 个月的限制；2 个月后系统状态
  失效、又能重新打招呼。但对于「已读不回 / 拒绝 / 索要简历(已处理)」的职位，
  我们不想浪费宝贵的每日打招呼次数去重复投递。
- 因此把对方回应状态长期记录在 message_status.json，apply 时只要发现该职位
  状态≠未读，就永久跳过（即使 applied_jobs.json 被清空或系统 2 个月限制解除）。

状态取值：
  unread       —— 未读（对方还没看，未来可考虑重投，本过滤不拦截）
  read_noreply —— 已读不回（拦截）
  rejected     —— 回复拒绝（拦截）
  asked_resume —— 回复索要简历（拦截）
  resume_sent  —— 已按对方要求发送简历（拦截）
"""

import json
from datetime import datetime
from pathlib import Path

MESSAGE_STATUS_FILE = Path(__file__).parent / "message_status.json"

# 这些状态在 apply 前应当跳过（对方已看到/已回应，重复打招呼无意义且浪费次数）
BLOCKING_STATUSES = {"read_noreply", "rejected", "asked_resume", "resume_sent"}
ALL_STATUSES = {"unread"} | BLOCKING_STATUSES


def _key(company: str, position: str) -> str:
    return f"{company.strip()}|{position.strip()}"


def load_status() -> dict:
    """加载对方回应状态记录"""
    if MESSAGE_STATUS_FILE.exists():
        with open(MESSAGE_STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("records", [])
            data.setdefault("last_updated", "")
            return data
    return {"records": [], "last_updated": ""}


def save_status(data: dict):
    """保存对方回应状态记录"""
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(MESSAGE_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_status(data: dict, company: str, position: str) -> str | None:
    """查某职位的对方回应状态，没有记录返回 None"""
    k = _key(company, position)
    for r in data.get("records", []):
        if _key(r.get("company", ""), r.get("position", "")) == k:
            return r.get("status")
    return None


def is_blocked(data: dict, company: str, position: str) -> bool:
    """
    apply 前过滤：该职位是否应跳过（对方已有非未读回应）。
    True 表示应跳过，不要再打招呼。
    """
    return get_status(data, company, position) in BLOCKING_STATUSES


def upsert_status(data: dict, company: str, position: str, status: str,
                  task_source: str = "", note: str = ""):
    """
    新增或更新某职位的对方回应状态（消息扫描任务调用）。
    status 必须是 ALL_STATUSES 之一。
    """
    if status not in ALL_STATUSES:
        raise ValueError(f"非法状态: {status}，应为 {ALL_STATUSES} 之一")
    k = _key(company, position)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in data.get("records", []):
        if _key(r.get("company", ""), r.get("position", "")) == k:
            r["status"] = status
            r["updated_at"] = now
            if task_source:
                r["task_source"] = task_source
            if note:
                r["note"] = note
            save_status(data)
            return
    rec = {"company": company, "position": position, "status": status,
           "updated_at": now}
    if task_source:
        rec["task_source"] = task_source
    if note:
        rec["note"] = note
    data["records"].append(rec)
    save_status(data)
