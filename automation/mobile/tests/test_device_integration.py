import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from device import Device

PKG = os.environ.get("KUGOU_PKG", "com.kugou.android")


def _device_online() -> bool:
    try:
        import subprocess
        out = subprocess.run([Device._adb_bin(), "devices"],
                             capture_output=True, text=True, timeout=10).stdout
        return any(ln.strip().endswith("device") for ln in out.splitlines()[1:])
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _device_online(), reason="adb 未发现已授权设备")


@pytest.fixture(scope="module")
def dev():
    d = Device(pkg=PKG)
    d.start()
    yield d
    d.quit()


def test_screen_size_positive(dev):
    w, h = dev.screen_size()
    assert w > 0 and h > 0

def test_screenshot_via_adb_fast(dev, tmp_path):
    """截图走 adb screencap，必须快速(<15s)返回有效 PNG。"""
    import time
    dev.activate_app()
    time.sleep(3)
    t0 = time.time()
    p = dev.screenshot(str(tmp_path / "adb_shot.png"))
    dt = time.time() - t0
    assert dt < 15, f"截图太慢({dt:.1f}s)"
    data = Path(p).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "不是有效 PNG"

def test_activate_kugou_foreground(dev):
    import time
    dev.activate_app()
    time.sleep(3)
    assert "kugou" in dev.current_package().lower()

def test_page_source_bounded(dev):
    """page_source 仅作兜底，必须有界(不挂死):酷狗重界面会超时返回空串。"""
    import time
    dev.activate_app()
    time.sleep(3)
    t0 = time.time()
    _ = dev.page_source()       # 可能为空，但绝不能挂死
    dt = time.time() - t0
    assert dt < 12, f"page_source 未在超时内返回({dt:.1f}s)"
