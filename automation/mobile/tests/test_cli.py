import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kugou_vip_ads import build_arg_parser


def test_default_target_hours():
    args = build_arg_parser().parse_args([])
    assert args.target_hours == 14
    assert args.uitars_local_url == "http://192.168.3.14:8000/v1"

def test_override_args():
    args = build_arg_parser().parse_args(
        ["--target-hours", "2", "--max-ads", "5", "--dry-run"])
    assert args.target_hours == 2
    assert args.max_ads == 5
    assert args.dry_run is True
