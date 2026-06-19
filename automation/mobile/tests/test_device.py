"""Device.screenshot 健壮性单元测试（mock adb subprocess，AGENTS.md §7.1 允许）。

背景：实测这台机 adb `screencap` 偶发抽风——有时返回空输出/非零码、有时只回 1 字节，
旧实现「写文件只在成功时、但无论如何都 return path」会让下游 image_to_base64 去 open
一个不存在/损坏的文件，FileNotFoundError 直接打挂整个 3 小时任务（实测 step17 崩溃）。
修复：screenshot 应重试 + 校验 PNG 魔数，确保返回的永远是有效截图；彻底失败才显式报错。
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from device import Device

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# 构造一张「足够大」的假 PNG（魔数 + 填充），仅供校验逻辑识别为有效
_VALID_PNG = _PNG_MAGIC + b"\x00" * 200


def _fake_result(returncode, stdout):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=b"")


def _make_device_with_runs(results):
    """返回一个 Device，其 _run 依次吐出 results 里的结果（耗尽后重复最后一个）。"""
    dev = Device(serial="TESTDEV")
    seq = list(results)

    def fake_run(*a, **kw):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    dev._run = fake_run  # type: ignore[assignment]
    return dev


def test_screenshot_retries_when_first_capture_empty(tmp_path):
    # 第一次空输出(flaky)，第二次正常 PNG → 应重试并最终写出有效 PNG
    dev = _make_device_with_runs([
        _fake_result(0, b""),       # flaky：空
        _fake_result(0, _VALID_PNG),
    ])
    p = dev.screenshot(str(tmp_path / "shot.png"))
    assert Path(p).exists(), "重试成功后截图文件必须存在"
    assert Path(p).read_bytes()[:8] == _PNG_MAGIC


def test_screenshot_rejects_truncated_one_byte(tmp_path):
    # 复现实测的 1 字节坏图：第一次只回 1 字节，第二次正常 → 不能把 1 字节当成功
    dev = _make_device_with_runs([
        _fake_result(0, b"x"),      # 1 字节坏图
        _fake_result(0, _VALID_PNG),
    ])
    p = dev.screenshot(str(tmp_path / "shot.png"))
    data = Path(p).read_bytes()
    assert data[:8] == _PNG_MAGIC, "1 字节坏图必须被拒绝并重试到有效 PNG"
    assert len(data) > 8


def test_screenshot_raises_after_all_retries_fail(tmp_path):
    # 始终失败 → 必须显式抛错，绝不能静默返回一个不存在/损坏文件的路径让下游崩溃
    dev = _make_device_with_runs([_fake_result(1, b"")])
    with pytest.raises(Exception):
        dev.screenshot(str(tmp_path / "shot.png"))
