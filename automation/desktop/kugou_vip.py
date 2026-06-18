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
        add_hours=args.add_hours,
        max_rounds=args.max_rounds,
        stale_limit=args.stale_limit,
        max_grounding_retries=args.max_grounding_retries,
    )


def main(argv=None):
    args = parse_args(argv)
    task = build_task(args)
    result = task.run()
    status = result["status"]
    msgs = {
        "done": f"✅ 完成：已新增 {args.add_hours} 小时免费VIP时长（{result['rounds']} 轮）",
        "failed": f"❌ 失败：连续 grounding 解析失败（{result['rounds']} 轮）",
        "max_rounds": f"⚠ 达到最大轮数 {args.max_rounds} 仍未完成",
    }
    print(msgs.get(status, f"结束：{result}"))
    return 0 if status == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
