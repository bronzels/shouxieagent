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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import vision
from agent import KugouAdsAgent
from device import Device


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="酷狗看广告攒 VIP 听歌时长自动化")
    p.add_argument("--target-hours", type=float, default=14, help="目标累计时长(小时)，默认14")
    p.add_argument("--openrouter-key", default=os.environ.get("OPENROUTER_API_KEY", ""),
                   help="OpenRouter API key（默认读环境变量 OPENROUTER_API_KEY）")
    p.add_argument("--uitars-local-url", default="http://192.168.3.14:8000/v1",
                   help="本地 UI-TARS server 地址（/v1 前缀）")
    p.add_argument("--max-ads", type=int, default=100, help="安全上限：最多看多少次广告")
    p.add_argument("--serial", default=None, help="adb 设备序列号（多设备时指定，默认取第一台）")
    p.add_argument("--pkg", default="com.kugou.android", help="酷狗包名")
    p.add_argument("--dry-run", action="store_true",
                   help="只归位+导航+读当前时长，不真正看广告")
    return p


async def main_async(args) -> int:
    vision.configure(args.openrouter_key, args.uitars_local_url)
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
