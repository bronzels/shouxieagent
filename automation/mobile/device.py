"""设备驱动封装（纯 adb 实现）。

酷狗会把 Appium/UiAutomator2 instrumentation 的 screenshot/tap/getPageSource 拖到 50-88s
并崩溃，故弃用 Appium，全程走 adb 原语（实测 screencap~1.2s、input tap~0.18s 稳定）。
page_source 改用 `adb shell uiautomator dump`，仅作 UI-TARS 视觉的兜底，带短超时防挂死。
"""
import os
import re
import shutil
import subprocess
import threading

# Windows 下隐藏子进程控制台窗口
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Device:
    def __init__(self, serial: str | None = None, pkg: str = "com.kugou.android"):
        self.pkg = pkg
        self._serial = serial
        self._xml_disabled = False  # page_source 一次超时后本会话停用，避免反复阻塞
        self._size = None

    @staticmethod
    def _adb_bin() -> str:
        p = shutil.which("adb")
        if p:
            return p
        cand = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            ".tools", "platform-tools", "adb.exe")
        return cand if os.path.exists(cand) else "adb"

    def _args(self, *a) -> list:
        base = [self._adb_bin()]
        if self._serial:
            base += ["-s", self._serial]
        return base + list(a)

    def _run(self, *a, timeout: float = 30.0, binary: bool = False):
        # adb 输出为 UTF-8；Windows 默认 gbk 解码会在含非 gbk 字节时崩溃，强制 utf-8/replace
        kw = dict(capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
        if not binary:
            kw.update(text=True, encoding="utf-8", errors="replace")
        return subprocess.run(self._args(*a), **kw)

    def _out(self, *a, timeout: float = 30.0) -> str:
        r = self._run(*a, timeout=timeout)
        return (r.stdout or "") if r.returncode == 0 else ""

    # ---- 生命周期 ----
    def start(self) -> None:
        # 选设备：未指定 serial 且有多台时取第一台 device
        if not self._serial:
            out = self._out("devices", timeout=10)
            devs = [ln.split("\t")[0] for ln in out.splitlines()[1:]
                    if ln.strip().endswith("device")]
            if not devs:
                raise RuntimeError("adb 未发现已授权的设备（adb devices 为空）")
            self._serial = devs[0]
        self._size = self.screen_size()

    def quit(self) -> None:
        pass  # 纯 adb，无会话需清理

    # ---- 基础信息 ----
    def screen_size(self) -> tuple[int, int]:
        if self._size:
            return self._size
        out = self._out("shell", "wm", "size", timeout=10)
        m = re.search(r"(\d+)\s*x\s*(\d+)", out)
        if not m:
            raise RuntimeError(f"无法解析屏幕尺寸: {out!r}")
        self._size = (int(m.group(1)), int(m.group(2)))
        return self._size

    def current_package(self) -> str:
        out = self._out("shell", "dumpsys", "activity", "activities", timeout=10)
        m = re.search(r"mResumedActivity.*?\{[^}]*\s(\S+)/", out)
        if m:
            return m.group(1)
        out = self._out("shell", "dumpsys", "window", timeout=10)
        m = re.search(r"mCurrentFocus=.*?\s(\S+)/", out)
        return m.group(1) if m else ""

    # ---- 操作 ----
    def screenshot(self, path: str) -> str:
        r = self._run("exec-out", "screencap", "-p", timeout=30, binary=True)
        if r.returncode == 0 and r.stdout:
            with open(path, "wb") as f:
                f.write(r.stdout)
        return path

    def tap(self, x: int, y: int) -> None:
        self._run("shell", "input", "tap", str(int(x)), str(int(y)), timeout=15)

    def back(self) -> None:
        self._run("shell", "input", "keyevent", "4", timeout=15)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 400) -> None:
        self._run("shell", "input", "swipe", str(int(x1)), str(int(y1)),
                  str(int(x2)), str(int(y2)), str(int(ms)), timeout=15)

    def activate_app(self) -> None:
        self._run("shell", "monkey", "-p", self.pkg,
                  "-c", "android.intent.category.LAUNCHER", "1", timeout=20)

    # ---- 兜底：无障碍树 XML（带超时，一次超时即停用）----
    def page_source(self, timeout: float = 6.0) -> str:
        if self._xml_disabled:
            return ""
        box = {}

        def _get():
            try:
                self._run("shell", "uiautomator", "dump", "/sdcard/u2dump.xml",
                          timeout=timeout)
                box["v"] = self._out("shell", "cat", "/sdcard/u2dump.xml",
                                     timeout=timeout)
            except Exception:  # noqa: BLE001
                box["v"] = ""

        t = threading.Thread(target=_get, daemon=True)
        t.start()
        t.join(timeout + 2.0)
        if "v" not in box:
            self._xml_disabled = True
            return ""
        return box.get("v") or ""
