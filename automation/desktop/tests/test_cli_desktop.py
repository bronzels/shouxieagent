# -*- coding: utf-8 -*-
"""kugou_vip_ads_desktop CLI 单元测试（mock 掉 ScrcpyDevice 与 agent）。"""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# 辅助：拿到 build_arg_parser 而不触发真实导入
# ---------------------------------------------------------------------------

def _get_parser():
    import automation.desktop.kugou_vip_ads_desktop as cli_mod
    return cli_mod.build_arg_parser


def _cli_mod():
    import automation.desktop.kugou_vip_ads_desktop as m
    return m


# ---------------------------------------------------------------------------
# build_arg_parser 默认值
# ---------------------------------------------------------------------------

def test_parser_default_add_hours():
    parser = _get_parser()()
    args = parser.parse_args([])
    assert args.add_hours == 3.0


def test_parser_default_scrcpy_dir():
    parser = _get_parser()()
    args = parser.parse_args([])
    assert "scrcpy" in args.scrcpy_dir.lower()


def test_parser_default_window_title():
    parser = _get_parser()()
    args = parser.parse_args([])
    assert args.window_title == "scrcpy-kugou"


def test_parser_explicit_add_hours():
    parser = _get_parser()()
    args = parser.parse_args(["--add-hours", "5"])
    assert args.add_hours == 5.0


def test_parser_dry_run_flag():
    parser = _get_parser()()
    args = parser.parse_args(["--dry-run"])
    assert args.dry_run is True


# ---------------------------------------------------------------------------
# main_async — add 语义：target = baseline + add_hours*60
# ---------------------------------------------------------------------------

def _build_args(**kwargs):
    """构造 args namespace，填好所有 main_async 需要的字段。"""
    import types
    defaults = dict(
        add_hours=3.0,
        scrcpy_dir=r"D:\fake-scrcpy",
        window_title="scrcpy-kugou",
        openrouter_key="",
        uitars_local_url="http://127.0.0.1:8000/v1",
        use_local=False,
        max_ads=100,
        serial=None,
        dry_run=False,
    )
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


def _run(coro):
    return asyncio.run(coro)


def test_main_async_target_is_baseline_plus_add_hours():
    """main_async 读出 baseline，以 baseline + add_hours*60 为 target 调 agent.run。"""
    import automation.desktop.kugou_vip_ads_desktop as cli_mod
    import vision as vision_mod

    mock_dev = MagicMock()
    mock_dev.start = MagicMock()
    mock_dev.quit = MagicMock()

    baseline_mins = 20
    mock_agent = MagicMock()
    mock_agent.reset_to_kugou_home = AsyncMock()
    mock_agent.navigate_to_ads_page = AsyncMock()
    mock_agent.read_remaining_minutes = AsyncMock(return_value=baseline_mins)
    # 假设最终达到目标
    target = baseline_mins + int(round(3.0 * 60))
    mock_agent.run = AsyncMock(return_value=target)

    with patch.object(cli_mod, "ScrcpyDevice", return_value=mock_dev), \
         patch.object(cli_mod, "KugouAdsAgent", return_value=mock_agent), \
         patch.object(vision_mod, "configure"):
        args = _build_args(add_hours=3.0)
        rc = _run(cli_mod.main_async(args))

    # 验证 run 被以正确的 target 调用
    mock_agent.run.assert_awaited_once_with(
        target_minutes=target,
        max_ads=100,
    )
    assert rc == 0


def test_main_async_returns_0_when_final_ge_target():
    import automation.desktop.kugou_vip_ads_desktop as cli_mod
    import vision as vision_mod

    mock_dev = MagicMock()
    mock_dev.start = MagicMock()
    mock_dev.quit = MagicMock()

    baseline = 10
    add_hours = 2.0
    target = baseline + int(round(add_hours * 60))

    mock_agent = MagicMock()
    mock_agent.reset_to_kugou_home = AsyncMock()
    mock_agent.navigate_to_ads_page = AsyncMock()
    mock_agent.read_remaining_minutes = AsyncMock(return_value=baseline)
    mock_agent.run = AsyncMock(return_value=target)  # 达到目标

    with patch.object(cli_mod, "ScrcpyDevice", return_value=mock_dev), \
         patch.object(cli_mod, "KugouAdsAgent", return_value=mock_agent), \
         patch.object(vision_mod, "configure"):
        rc = _run(cli_mod.main_async(_build_args(add_hours=add_hours)))

    assert rc == 0


def test_main_async_returns_2_when_final_lt_target():
    import automation.desktop.kugou_vip_ads_desktop as cli_mod
    import vision as vision_mod

    mock_dev = MagicMock()
    mock_dev.start = MagicMock()
    mock_dev.quit = MagicMock()

    baseline = 10
    add_hours = 2.0
    target = baseline + int(round(add_hours * 60))

    mock_agent = MagicMock()
    mock_agent.reset_to_kugou_home = AsyncMock()
    mock_agent.navigate_to_ads_page = AsyncMock()
    mock_agent.read_remaining_minutes = AsyncMock(return_value=baseline)
    mock_agent.run = AsyncMock(return_value=target - 1)  # 未达目标

    with patch.object(cli_mod, "ScrcpyDevice", return_value=mock_dev), \
         patch.object(cli_mod, "KugouAdsAgent", return_value=mock_agent), \
         patch.object(vision_mod, "configure"):
        rc = _run(cli_mod.main_async(_build_args(add_hours=add_hours)))

    assert rc == 2


def test_main_async_dry_run_does_not_call_agent_run():
    import automation.desktop.kugou_vip_ads_desktop as cli_mod
    import vision as vision_mod

    mock_dev = MagicMock()
    mock_dev.start = MagicMock()
    mock_dev.quit = MagicMock()

    mock_agent = MagicMock()
    mock_agent.reset_to_kugou_home = AsyncMock()
    mock_agent.navigate_to_ads_page = AsyncMock()
    mock_agent.read_remaining_minutes = AsyncMock(return_value=30)
    mock_agent.run = AsyncMock()

    with patch.object(cli_mod, "ScrcpyDevice", return_value=mock_dev), \
         patch.object(cli_mod, "KugouAdsAgent", return_value=mock_agent), \
         patch.object(vision_mod, "configure"):
        rc = _run(cli_mod.main_async(_build_args(dry_run=True)))

    mock_agent.run.assert_not_awaited()
    assert rc == 0


def test_main_async_dev_quit_called_even_on_exception():
    """即便 agent 抛异常，dev.quit() 也要在 finally 里被调用。"""
    import automation.desktop.kugou_vip_ads_desktop as cli_mod
    import vision as vision_mod

    mock_dev = MagicMock()
    mock_dev.start = MagicMock()
    mock_dev.quit = MagicMock()

    mock_agent = MagicMock()
    mock_agent.reset_to_kugou_home = AsyncMock(side_effect=RuntimeError("boom"))

    with patch.object(cli_mod, "ScrcpyDevice", return_value=mock_dev), \
         patch.object(cli_mod, "KugouAdsAgent", return_value=mock_agent), \
         patch.object(vision_mod, "configure"):
        with pytest.raises(RuntimeError, match="boom"):
            _run(cli_mod.main_async(_build_args()))

    mock_dev.quit.assert_called_once()
