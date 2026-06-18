import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from device import Device

APPIUM = os.environ.get("APPIUM_URL", "http://127.0.0.1:4723")
PKG = os.environ.get("KUGOU_PKG", "com.kugou.android")


def _appium_up() -> bool:
    import httpx
    try:
        return httpx.get(f"{APPIUM}/status", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _appium_up(), reason="Appium server 未运行/真机未连接")


@pytest.fixture(scope="module")
def dev():
    d = Device(appium_url=APPIUM, pkg=PKG)
    d.start()
    yield d
    d.quit()


def test_screen_size_positive(dev):
    w, h = dev.screen_size()
    assert w > 0 and h > 0

def test_screenshot_created(dev, tmp_path):
    p = dev.screenshot(str(tmp_path / "shot.png"))
    assert Path(p).exists() and Path(p).stat().st_size > 0

def test_activate_kugou_foreground(dev):
    dev.activate_app()
    import time
    time.sleep(2)
    assert PKG in dev.current_package()

def test_screenshot_via_adb_fast(dev, tmp_path):
    """截图走 adb screencap，必须快速(<15s)返回有效 PNG（绕开 UiAutomator2 崩溃）。"""
    import time
    dev.activate_app()
    time.sleep(3)
    t0 = time.time()
    p = dev.screenshot(str(tmp_path / "adb_shot.png"))
    dt = time.time() - t0
    assert dt < 15, f"截图太慢({dt:.1f}s)"
    data = Path(p).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "不是有效 PNG"

def test_page_source_bounded(dev):
    """page_source 仅作兜底，必须有界(不挂死):酷狗重界面会超时返回空串，<8s 内返回。"""
    import time
    dev.activate_app()
    time.sleep(3)
    t0 = time.time()
    _ = dev.page_source()       # 可能为空(超时停用)，但绝不能挂死
    dt = time.time() - t0
    assert dt < 8, f"page_source 未在超时内返回({dt:.1f}s)"

