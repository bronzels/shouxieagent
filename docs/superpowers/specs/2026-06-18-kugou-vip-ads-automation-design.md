# 酷狗音乐「看广告攒 VIP 听歌时长」自动化 — 设计文档

- 日期：2026-06-18
- 目录：`automation/mobile/`
- 目标：在一台 Android 真机上，用 Appium 驱动操作酷狗音乐 app，反复点击「免费看广告增加 VIP 听歌时长」，直到累计 VIP/免费畅听剩余时长 **≥ 14 小时**。最终交付的 Python 命令程序，**无论手机当前处于任何屏幕或 app 状态**，运行都能完成本任务。

---

## 1. 背景与约束

- 手机：Android 真机，已 USB 连接、已开启 USB 调试，adb 可识别。
- 酷狗音乐：已安装、已登录可领 VIP 的账号。包名预期 `com.kugou.android`（运行时以 adb 实测为准）。
- 单次广告时长 **≤ 60 秒**；**无累计上限**，14 小时目标可达。
- GUI 识别（看截图找按钮 / 读屏文字）复用 `automation/web` 已有能力：
  - **默认**：本地 UI-TARS（`http://192.168.3.14:8000/v1`，OpenAI 兼容）做坐标 grounding；
  - **决策/读屏文字**：OpenRouter 免费文本/多模态模型链；
  - **fallback**：本地 UI-TARS 连续失败 → OpenRouter 上的 UI-TARS / 免费多模态模型。
  - 复用函数来自 `automation/web/zhipin_apply.py`：`call_uitars()`、`parse_uitars_action()`（输出 0-1 归一化坐标）、`_post_openrouter()`、模型清单 `VERIFY_MODELS_TEXT/_MULTIMODAL(_PAID)`、`UITARS_LOCAL_URL`。
- 遵守 `AGENTS.md`：隔离环境（测试代码跑在根目录 `.venv`）、TDD 铁律、测试前后清理数据、中文输出、任务完成 git commit/push。

---

## 2. 环境安装 `automation/mobile/setup.sh`

纯命令行优先；每步先 `command -v` 检测，已存在则跳过。某步只能图形下载时，脚本停下并打印明确提示，让用户手工完成后重跑。

| 步骤 | 组件 | 安装方式（CLI 优先） |
|------|------|---------------------|
| 1 | Android platform-tools (adb) | `curl` 下载 `platform-tools-latest-windows.zip` → 解压到 `automation/mobile/.tools/platform-tools/`；脚本导出 `ANDROID_HOME` 与 PATH |
| 2 | JDK 21 (Temurin) | 优先 `winget install EclipseAdoptium.Temurin.21.JDK`；winget 不可用则 `curl` 下载 zip 版 JDK 解压到 `.tools/` |
| 3 | Appium Server + 驱动 | `npm install -g appium` + `appium driver install uiautomator2` |
| 4 | Python 客户端 | 往 `.venv` 装 `Appium-Python-Client`，随后 `pip freeze > requirements-test.txt` 并提交 |
| 5 | 自检 | 跑 `adb devices`、`appium driver list`，打印手机是否识别、驱动是否就绪 |

`.tools/` 加入 `.gitignore`，不入库。

---

## 3. 代码分层（`automation/mobile/`）

- **`device.py`** — Appium(UiAutomator2) 驱动封装：
  - `screenshot(path)`、`tap(x, y)`、`tap_norm(nx, ny)`（0-1 归一化 → 像素）、`swipe(...)`、`back()`
  - `page_source()` 取 XML、`find_by_text(substr)` / `find_by_resource_id(rid)`
  - `activate_app(pkg)`、`current_activity()`、`screen_size()`
- **`vision.py`** — 复用 web 的视觉/LLM 能力（同款模型链 + `192.168.3.14` 本地 UI-TARS）：
  - `locate(screenshot_path, 指令) -> (nx, ny) | None`：本地 UI-TARS 出坐标，失败 fallback；底层调 `call_uitars` + `parse_uitars_action`
  - `read_text(screenshot_path, 问题) -> str`：免费文本/多模态模型读屏（如读 VIP 剩余时长、判断当前在哪个页面、广告是否结束）
  - 复用策略：以 `sys.path` 注入 `automation/web` 后 import，或抽出公共函数到 `vision.py` 直接调用（实现阶段二选一，以不改动 web 现有行为为准）。
- **`agent.py`** — 主循环（鲁棒性核心，见 §4）。
- **`kugou_vip_ads.py`** — CLI 入口。参数：
  - `--target-hours`（默认 14）
  - `--openrouter-key`（默认读环境变量 / `.env`）
  - `--uitars-local-url`（默认 `http://192.168.3.14:8000/v1`）
  - `--max-ads`（安全上限，防失控，默认一个较大值如 100）
  - `--dry-run`（只导航到看广告入口、读当前时长，不真正看广告）

---

## 4. 「任何屏幕/任何 app 状态都能完成」的鲁棒逻辑（`agent.py`）

1. **状态归位**：启动先无条件 `activate_app("com.kugou.android")`，把酷狗强制拉到前台（覆盖「在别的 app / 锁屏后 / 停在酷狗某深层页」各种情况）。必要时多按几次 `back()` 回到主界面再导航。
2. **导航找入口**：截图 → 先用 page source 文本匹配关键字（「看广告」「免费听歌」「VIP」「领时长」「畅听」）命中直接点；未命中用 UI-TARS 视觉兜底定位（**复刻 web 的「选择器优先 + 视觉兜底」**）→ 进入「看广告领 VIP 时长」页。
3. **看广告循环**（单次循环）：
   - 点「看广告」按钮 → 进入广告（≤60 秒）。
   - 轮询截图判断广告进行中/结束；广告结束后定位右上角关闭「×」（视觉定位优先，结合 page source）→ 关闭回到奖励页。
   - 处理「广告加载失败 / 无广告可看 / 弹窗」等异常：重试或返回奖励页。
4. **读时长 & 停止条件**：每轮读页面显示的「VIP / 免费畅听剩余时长」，`read_text` + 解析成分钟。**累计剩余时长 ≥ 14 小时即停**。达到 `--max-ads` 安全上限也停（打印告警，说明被安全上限截断）。
5. **可观测性**：关键节点存截图到 `automation/mobile/reports/screenshots/`；每轮打印当前剩余时长进度。

---

## 5. 测试（TDD，遵守 AGENTS.md）

测试代码跑在根目录 `.venv`，分单元/集成/E2E；单元测试测完不留数据。

- **单元**（纯函数，mock 输入）：
  - VIP 时长字符串解析：「3小时20分」「200分钟」「3.5 小时」「14:00」→ 分钟数
  - 归一化坐标 → 像素换算
  - page source 文本匹配关键字
  - UI-TARS 响应解析复用 web 的 `parse_uitars_action`（已有覆盖，必要时补 mobile 场景）
- **集成**（真机在线）：
  - adb/Appium 连通性、`activate_app` 把酷狗拉前台、读到 current activity、截图成功
- **E2E**（真机）：
  - 完整流程：归位 → 导航到看广告页 → 看 1～N 次广告 → 时长增长可观测；存截图+录屏，关键截图（看广告页 / 时长到账）用多模态模型核验。
  - `--dry-run` 先验证「归位 + 导航 + 读时长」链路，再放开真看广告。

测试用例在测试计划文档中描述并实现为 case 代码，不留孤立工具脚本。

---

## 6. 风险

- 广告内容随机、关闭「×」位置不固定 → 靠视觉定位兜底。
- 单次广告 ≤60 秒、无上限，但 14 小时可能需看几十次广告，整体耗时较长；程序需稳健处理长时间运行（异常重试、进度可恢复）。
- 本地 UI-TARS（192.168.3.14）不可达时依赖 OpenRouter fallback，需保证 key 有效。

---

## 7. 交付物

- `automation/mobile/setup.sh`
- `automation/mobile/device.py` / `vision.py` / `agent.py` / `kugou_vip_ads.py`
- 测试用例代码 + 测试计划文档 + `reports/` 测试报告（含截图/录屏/多模态核验）
- `.gitignore` 增加 `.tools/`；`requirements-test.txt` 更新
