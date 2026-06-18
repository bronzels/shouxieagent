# -*- coding: utf-8 -*-
from automation.desktop import config


def test_defaults_target_hours():
    assert config.DEFAULTS["target_hours"] == 14


def test_gesture_map_back_and_home():
    assert config.SCRCPY_GESTURE["press_back"] == "right"
    assert config.SCRCPY_GESTURE["press_home"] == "middle"


def test_parse_args_overrides_target_hours():
    ns = config.parse_args(["--target-hours", "8", "--openrouter-key", "sk-or-x"])
    assert ns.target_hours == 8
    assert ns.openrouter_key == "sk-or-x"
    assert ns.dry_run is False


def test_parse_args_dry_run_flag():
    ns = config.parse_args(["--dry-run"])
    assert ns.dry_run is True


# ── M3 配置接线测试 ───────────────────────────────────────────────────────────

def test_defaults_stale_limit_and_max_grounding_retries():
    assert config.DEFAULTS["stale_limit"] == 4
    assert config.DEFAULTS["max_grounding_retries"] == 3


def test_parse_args_stale_limit_default():
    ns = config.parse_args([])
    assert ns.stale_limit == 4


def test_parse_args_max_grounding_retries_default():
    ns = config.parse_args([])
    assert ns.max_grounding_retries == 3


def test_parse_args_stale_limit_override():
    ns = config.parse_args(["--stale-limit", "6"])
    assert ns.stale_limit == 6


def test_parse_args_max_grounding_retries_override():
    ns = config.parse_args(["--max-grounding-retries", "5"])
    assert ns.max_grounding_retries == 5
