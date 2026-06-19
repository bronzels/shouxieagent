"""CLI 入口：酷狗看广告攒 VIP 时长。任意手机状态下运行均可完成。

用法示例：
  python kugou_vip_ads.py --target-hours 14 --openrouter-key sk-or-...
  python kugou_vip_ads.py --dry-run            # 只归位+导航+读当前时长
"""
import argparse
import asyncio
import os
import sys

# Windows 控制台默认 gbk，打印 ▶/✅ 等字符会崩；统一 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "common"))

import vision
from agent import KugouAdsAgent
from device import Device


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="酷狗看广告攒 VIP 听歌时长自动化")
    p.add_argument("--target-hours", type=float, default=14,
                   help="目标累计时长(小时)，默认14（未指定 --add-hours 时用）")
    p.add_argument("--add-hours", type=float, default=None,
                   help="要新增的免费时长(小时)，如3=在当前基础上新增3小时；优先于 --target-hours")
    p.add_argument("--openrouter-key", default=os.environ.get("OPENROUTER_API_KEY", ""),
                   help="OpenRouter API key（默认读环境变量 OPENROUTER_API_KEY）")
    p.add_argument("--uitars-local-url", default="http://192.168.3.14:8000/v1",
                   help="本地 UI-TARS server 地址（/v1 前缀，仅 --use-local 时生效）")
    p.add_argument("--use-local", action="store_true",
                   help="也用本地 UI-TARS（默认关闭，只用 OpenRouter）")
    p.add_argument("--max-ads", type=int, default=100, help="安全上限：最多看多少次广告")
    p.add_argument("--serial", default=None, help="adb 设备序列号（多设备时指定，默认取第一台）")
    p.add_argument("--pkg", default="com.kugou.android", help="酷狗包名")
    p.add_argument("--dry-run", action="store_true",
                   help="只归位+导航+读当前时长，不真正看广告")
    return p


async def main_async(args) -> int:
    # 默认只用 OpenRouter（不连本地 UI-TARS）；--use-local 才本地优先+OpenRouter兜底
    if args.use_local:
        vision.configure(args.openrouter_key, args.uitars_local_url, use_local=True)
    else:
        vision.configure(args.openrouter_key, use_local=False)
    print(f"  ▶ 视觉后端: {'本地优先+OpenRouter兜底' if args.use_local else '仅 OpenRouter'}", flush=True)
    dev = Device(serial=args.serial, pkg=args.pkg)
    dev.start()
    try:
        agent = KugouAdsAgent(device=dev, vision=vision)
        if args.dry_run:
            await agent.reset_to_kugou_home()
            await agent.navigate_to_ads_page()
            mins = await agent.read_remaining_minutes()
            print(f"✅ dry-run：当前剩余时长 {mins} 分钟", flush=True)
            return 0
        if args.add_hours is not None:
            # 新增语义：读基线 + 新增小时数
            await agent.reset_to_kugou_home()
            await agent.navigate_to_ads_page()
            baseline = await agent.read_remaining_minutes() or 0
            target_minutes = baseline + int(round(args.add_hours * 60))
            print(f"  ▶ 当前基线: {baseline} 分钟，目标新增 {int(round(args.add_hours*60))} 分钟"
                  f" → 目标: {target_minutes} 分钟", flush=True)
        else:
            target_minutes = int(round(args.target_hours * 60))
        final = await agent.run(target_minutes=target_minutes, max_ads=args.max_ads)
        return 0 if final >= target_minutes else 2
    finally:
        dev.quit()


def main() -> None:
    args = build_arg_parser().parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
