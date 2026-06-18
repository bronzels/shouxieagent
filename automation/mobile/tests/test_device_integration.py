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

def test_page_source_fast_on_kugou(dev):
    """酷狗开屏/首页 page_source 必须快速返回、不崩（根因修复:关idle等待+忽略不重要视图）。"""
    import time
    dev.activate_app()
    time.sleep(3)
    t0 = time.time()
    xml = dev.page_source()
    dt = time.time() - t0
    assert dt < 10, f"page_source 太慢({dt:.1f}s)，idle等待修复可能失效"
    assert xml, "page_source 返回空（dump 失败）"

