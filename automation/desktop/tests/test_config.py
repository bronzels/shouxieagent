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
