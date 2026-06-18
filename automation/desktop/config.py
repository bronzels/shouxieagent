# -*- coding: utf-8 -*-
"""配置常量与命令行参数解析。"""
import argparse

DEFAULTS = {
    "target_hours": 14,
    "max_rounds": 200,
    "scrcpy_title": "scrcpy",
    "local_url": "http://127.0.0.1:8000/v1",
    "openrouter_key": None,
    "dry_run": False,
    "stale_limit": 4,            # 连续 N 步画面无变化判定卡死
    "max_grounding_retries": 3,  # 单步 grounding 失败重试上限
}

# UI-TARS mobile 动作 → scrcpy 接收的鼠标键（scrcpy 默认：右键=BACK，中键=HOME）
SCRCPY_GESTURE = {
    "press_back": "right",
    "press_home": "middle",
}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="酷狗刷 VIP 桌面自动化")
    p.add_argument("--target-hours", type=float, default=DEFAULTS["target_hours"])
    p.add_argument("--max-rounds", type=int, default=DEFAULTS["max_rounds"])
    p.add_argument("--scrcpy-title", default=DEFAULTS["scrcpy_title"])
    p.add_argument("--local-url", default=DEFAULTS["local_url"])
    p.add_argument("--openrouter-key", default=DEFAULTS["openrouter_key"])
    p.add_argument("--dry-run", action="store_true", default=DEFAULTS["dry_run"])
    p.add_argument("--stale-limit", type=int, default=DEFAULTS["stale_limit"])
    p.add_argument("--max-grounding-retries", type=int, default=DEFAULTS["max_grounding_retries"])
    return p.parse_args(argv)
