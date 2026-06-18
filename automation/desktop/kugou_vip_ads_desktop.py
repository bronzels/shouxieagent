"""CLI 入口：酷狗看广告攒 VIP 时长（桌面 scrcpy 版）。

用法示例：
  python kugou_vip_ads_desktop.py --add-hours 3 --openrouter-key sk-or-...
  python kugou_vip_ads_desktop.py --dry-run   # 只归位+导航+读当前时长
"""
import argparse
import asyncio
import os
import sys

# Windows 控制台默认 gbk，打印特殊字符会崩；统一 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_AUTOMATION_DIR = os.path.dirname(_HERE)
_COMMON_DIR = os.path.join(_AUTOMATION_DIR, "common")
# 把 automation/ 父目录加入 sys.path，让 automation.desktop 包相对导入正常工作
_ROOT_DIR = os.path.dirname(_AUTOMATION_DIR)
for _d in [_COMMON_DIR, _ROOT_DIR]:
    if _d not in sys.path:
        sys.path.insert(0, _d)

import vision
from agent import KugouAdsAgent
from automation.desktop.scrcpy_device import ScrcpyDevice


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="酷狗看广告攒 VIP 听歌时长（桌面 scrcpy 版）")
    p.add_argument("--add-hours", type=float, default=3.0,
                   help="通过看广告要新增的免费VIP时长(小时)，默认3")
    p.add_argument("--scrcpy-dir", default=r"D:\scrcpy-win64-v4.0",
                   help="scrcpy 安装目录（含 scrcpy.exe）")
    p.add_argument("--window-title", default="scrcpy-kugou",
                   help="scrcpy 窗口标题，默认 scrcpy-kugou")
    p.add_argument("--openrouter-key",
                   default=os.environ.get("OPENROUTER_API_KEY", ""),
                   help="OpenRouter API key（默认读环境变量 OPENROUTER_API_KEY）")
    p.add_argument("--uitars-local-url", default="http://192.168.3.14:8000/v1",
                   help="本地 UI-TARS server 地址（/v1 前缀，仅 --use-local 时生效）")
    p.add_argument("--use-local", action="store_true",
                   help="也用本地 UI-TARS（默认关闭，只用 OpenRouter）")
    p.add_argument("--max-ads", type=int, default=100,
                   help="安全上限：最多看多少次广告，默认100")
    p.add_argument("--serial", default=None,
                   help="scrcpy -s 参数：多设备时指定目标设备，默认取第一台")
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
    dev = ScrcpyDevice(args.scrcpy_dir, args.window_title, args.serial)
    dev.start()
    try:
        agent = KugouAdsAgent(
            device=dev,
            vision=vision,
            shots_dir="automation/desktop/runs/screenshots",
        )
        if args.dry_run:
            await agent.reset_to_kugou_home()
            await agent.navigate_to_ads_page()
            mins = await agent.read_remaining_minutes()
            print(f"✅ dry-run：当前剩余时长 {mins} 分钟", flush=True)
            return 0

        # 读基线，计算目标
        await agent.reset_to_kugou_home()
        await agent.navigate_to_ads_page()
        baseline = await agent.read_remaining_minutes() or 0
        target = baseline + int(round(args.add_hours * 60))
        print(f"  ▶ 当前基线: {baseline} 分钟，目标新增 {int(round(args.add_hours*60))} 分钟"
              f" → 目标: {target} 分钟", flush=True)

        final = await agent.run(target_minutes=target, max_ads=args.max_ads)
        return 0 if final >= target else 2
    finally:
        dev.quit()


def main() -> None:
    args = build_arg_parser().parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
