"""Appium(UiAutomator2) 驱动封装。

注：酷狗会把 UiAutomator2 instrumentation 的 screenshot/getPageSource 拖到 50-88s 并崩溃，
因此**截图改走 `adb screencap`**（稳定 1s 级，绕开崩溃），其余控制(tap/activate/back/
screen_size)仍走 Appium。page_source 带短超时仅作兜底。"""
import os
import shutil
import subprocess
import threading

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.extensions.android.nativekey import AndroidKey


class Device:
    def __init__(self, appium_url: str = "http://127.0.0.1:4723",
                 pkg: str = "com.kugou.android"):
        self.appium_url = appium_url
        self.pkg = pkg
        self.driver = None
        self._xml_disabled = False  # page_source 一次超时后本会话停用，避免反复阻塞
        self._serial = None         # adb 设备序列号(截图用)

    @staticmethod
    def _adb_path() -> str:
        p = shutil.which("adb")
        if p:
            return p
        cand = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            ".tools", "platform-tools", "adb.exe")
        return cand if os.path.exists(cand) else "adb"

    def start(self) -> None:
        opts = UiAutomator2Options()
        opts.platform_name = "Android"
        opts.automation_name = "UiAutomator2"
        # 不指定 appPackage/appActivity，连当前会话；用 activate_app 控制前台
        opts.no_reset = True
        opts.new_command_timeout = 600
        # vivo/Funtouch 等 ROM 偶发安装辅助 APK 慢，放宽超时
        opts.set_capability("uiautomator2ServerInstallTimeout", 120000)
        opts.set_capability("adbExecTimeout", 120000)
        # vivo 等无「USB安装」开关的 ROM：辅助 APK 已由 setup.sh 预装(adb install)，
        # 这里跳过 Appium 的服务安装与设备初始化(否则因缺 aapt2 读不到版本而每次重装、
        # 反复弹安装授权)。前提:setup.sh 已成功预装 io.appium.settings + uiautomator2 server。
        opts.set_capability("skipServerInstallation", True)
        opts.set_capability("skipDeviceInitialization", True)
        self.driver = webdriver.Remote(self.appium_url, options=opts)
        try:
            self._serial = self.driver.capabilities.get("deviceUDID")
        except Exception:  # noqa: BLE001
            self._serial = None
        # 关键：酷狗开屏广告等带连续动画+超大视图树的页面，UiAutomator2 默认会
        # 等界面 idle 再全量序列化，导致 getPageSource 卡 45s 并把 instrumentation 拖崩。
        # 关掉 idle 等待 + 只 dump 重要视图，page_source 即可秒回不崩。
        try:
            self.driver.update_settings({
                "waitForIdleTimeout": 0,
                "ignoreUnimportantViews": True,
            })
        except Exception:  # noqa: BLE001
            pass

    def quit(self) -> None:
        if self.driver:
            self.driver.quit()
            self.driver = None

    def screen_size(self) -> tuple[int, int]:
        s = self.driver.get_window_size()
        return (s["width"], s["height"])

    def screenshot(self, path: str) -> str:
        """用 adb screencap 截图(绕开 UiAutomator2 在酷狗上崩溃的 screenshot)。
        失败时退回 Appium 截图。"""
        try:
            args = [self._adb_path()]
            if self._serial:
                args += ["-s", self._serial]
            args += ["exec-out", "screencap", "-p"]
            with open(path, "wb") as f:
                subprocess.run(args, stdout=f, timeout=30, check=True)
            if os.path.getsize(path) > 0:
                return path
        except Exception:  # noqa: BLE001
            pass
        self.driver.get_screenshot_as_file(path)
        return path

    def tap(self, x: int, y: int) -> None:
        self.driver.tap([(x, y)])

    def back(self) -> None:
        self.driver.press_keycode(AndroidKey.BACK)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 400) -> None:
        self.driver.swipe(x1, y1, x2, y2, ms)

    def page_source(self, timeout: float = 6.0) -> str:
        """取无障碍树 XML（仅作 UI-TARS 视觉的兜底）。带短超时：酷狗重界面上全树
        dump 可能卡 88s 并拖垮会话；一旦超时即本会话停用 XML（返回空串），让上层
        全程走视觉，避免反复阻塞。"""
        if self._xml_disabled or self.driver is None:
            return ""
        box = {}

        def _get():
            try:
                box["v"] = self.driver.page_source
            except Exception:  # noqa: BLE001
                box["v"] = ""

        t = threading.Thread(target=_get, daemon=True)
        t.start()
        t.join(timeout)
        if "v" not in box:
            # 超时：底层请求仍在后台跑，本会话不再尝试 XML
            self._xml_disabled = True
            return ""
        return box["v"]

    def activate_app(self) -> None:
        self.driver.activate_app(self.pkg)

    def current_package(self) -> str:
        return self.driver.current_package or ""
