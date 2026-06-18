"""Appium(UiAutomator2) 驱动封装。"""
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.extensions.android.nativekey import AndroidKey


class Device:
    def __init__(self, appium_url: str = "http://127.0.0.1:4723",
                 pkg: str = "com.kugou.android"):
        self.appium_url = appium_url
        self.pkg = pkg
        self.driver = None

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
        self.driver = webdriver.Remote(self.appium_url, options=opts)
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
        self.driver.get_screenshot_as_file(path)
        return path

    def tap(self, x: int, y: int) -> None:
        self.driver.tap([(x, y)])

    def back(self) -> None:
        self.driver.press_keycode(AndroidKey.BACK)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 400) -> None:
        self.driver.swipe(x1, y1, x2, y2, ms)

    def page_source(self) -> str:
        """取无障碍树 XML。万一底层 dump 失败（重界面偶发），返回空串，
        让上层自动 fallback 到 UI-TARS 视觉定位（防御纵深）。"""
        try:
            return self.driver.page_source
        except Exception:  # noqa: BLE001
            return ""

    def activate_app(self) -> None:
        self.driver.activate_app(self.pkg)

    def current_package(self) -> str:
        return self.driver.current_package or ""
