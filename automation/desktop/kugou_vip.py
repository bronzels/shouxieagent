# -*- coding: utf-8 -*-
"""酷狗刷 VIP 桌面自动化 — 命令行入口。"""
import sys

from .config import parse_args
from .scrcpy_window import ScrcpyWindow
from .desktop_input import DesktopInput
from .uitars_agent import UITarsAgent
from .task_kugou import KugouTask


def build_task(args):
    window = ScrcpyWindow(title=args.scrcpy_title)
    agent = UITarsAgent(local_url=args.local_url, openrouter_key=args.openrouter_key)
    inp = DesktopInput(dry_run=args.dry_run)
    return KugouTask(
        window, agent, inp,
        target_hours=args.target_hours,
        max_rounds=args.max_rounds,
    )


def main(argv=None):
    args = parse_args(argv)
    task = build_task(args)
    result = task.run()
    status = result["status"]
    msgs = {
        "done": f"✅ 完成：已累计到 {args.target_hours} 小时（{result['rounds']} 轮）",
        "limit": f"⏸ 今日已达上限，请明日再运行（{result['rounds']} 轮）",
        "failed": f"❌ 失败：连续 grounding 解析失败（{result['rounds']} 轮）",
        "max_rounds": f"⚠ 达到最大轮数 {args.max_rounds} 仍未完成",
    }
    print(msgs.get(status, f"结束：{result}"))
    return 0 if status in ("done", "limit") else 1


if __name__ == "__main__":
    sys.exit(main())
