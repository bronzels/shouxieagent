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
        return self.driver.page_source

    def activate_app(self) -> None:
        self.driver.activate_app(self.pkg)

    def current_package(self) -> str:
        return self.driver.current_package or ""
