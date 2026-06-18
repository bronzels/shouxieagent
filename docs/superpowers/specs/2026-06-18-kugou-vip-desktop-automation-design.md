# 酷狗音乐刷 VIP 时长 — Windows Desktop 自动化 设计文档

- 日期：2026-06-18
- 位置：`automation/desktop/`
- 性质：全新子项目

## 1. 目标

开发一个 Python 命令行程序，运行在 Windows 上，**通过桌面（desktop）自动化**操作经
scrcpy 投屏到 PC 的安卓手机，打开酷狗音乐 app，反复点击"免费看广告增加 VIP 听歌时长"，
累计达到 **14 小时** 后停止。要求：**无论手机当前处于任何屏幕或 app 状态**，运行该程序都能完成任务。

**本项目的核心验证目的：Windows desktop 自动化能力**（不是 ADB 控制）。因此操作与截图都
走桌面层（鼠标/键盘模拟 + 桌面窗口截图），ADB 仅用于连接手机、启动 scrcpy。

## 2. 连接与前置假设

- 手机经 USB 连接，已开启 USB 调试，`adb devices` 可识别。
- scrcpy 已安装，运行后能把手机屏幕投影为一个 PC 桌面窗口。
- 程序运行时 scrcpy 窗口需可见（可被程序前置）。

## 3. 模型方案（单模型）

- **唯一模型：UI-TARS**（GUI agent，输出 `Thought + Action`，自己完成 think→ground→act）。
  - 既做 **grounding（定位，给坐标）**，也做任务里**极少量**的简单视觉问答（读"当前 VIP 累计时长"、
    "今日已领完"、广告倒计时等短文本/数字）。
  - **不引入任何文字大模型**——本任务是导航任务，不需要理解大段文字
    （这点与 `automation/web` 招聘投递任务不同，后者需读职位描述做决策）。
- **Fallback：OpenRouter 托管的 UI-TARS**（`bytedance/ui-tars-1.5-7b`）。仅当本地服务不可用、
  或本地返回低置信/解析失败时切换。同一模型家族，行为一致。
- 备注：`automation/web` 里"运行时禁用截图 OCR、走 DOM 解码"的规则是 **web 场景专属**
  （浏览器有 DOM）。scrcpy 投出的手机画面**没有 DOM，只有像素**，本任务只能让 UI-TARS 从画面读取，
  不违背"不做大段文字 OCR 理解"的本意。

## 4. 架构与目录

```
automation/desktop/
├── kugou_vip.py          # 主程序入口（命令行）
├── scrcpy_window.py      # 【桌面自动化核心】找窗口/前置/截图/坐标映射
├── desktop_input.py      # 【桌面自动化核心】UI-TARS 动作 → pyautogui→scrcpy 手势翻译
├── task_kugou.py         # 酷狗任务状态机
├── config.py             # 配置（窗口标题、模型地址、key、目标小时数等）
├── tests/                # 单元/集成/E2E 测试（基于根目录 .venv）
└── runs/<时间戳>/         # 每次运行留档（每步截图）
```

**复用 `automation/web` 既有资产（不重写）：**

- `automation/web/ui-tars-server/inference_client.py` 的 `UITarsClient`：
  - `local()` / `openrouter()` 工厂方法（本地优先 + OpenRouter 兜底）
  - `predict()` / `ground()` / `append_history()`（多轮对话历史，agent 循环必备）
  - 内置 `MOBILE_SYSTEM_PROMPT`（含 `press_home`/`press_back`/`long_press`/`scroll`）
  - `parse_action_simple()`（0–1000 相对坐标 → 像素归一化）
  - 官方参数 `frequency_penalty=1, temperature=0`
- `automation/web/inference.py`：需在本地起 UI-TARS OpenAI 兼容服务时使用。
- OpenRouter 走代理的 env 模式。

`uitars_agent` 逻辑以薄封装方式复用 `UITarsClient`，不重写。

**不借鉴：** `automation/web` 的文字大模型/文本理解管线。

## 5. 数据流（单循环）

1. `scrcpy_window` 截取 scrcpy 窗口**内容区**（排除标题栏）→ 一张手机画面图。
2. `uitars_agent` 把图 + 当前指令 + 多轮 history 发给 UI-TARS → 返回 `Thought + Action(坐标)`。
3. `scrcpy_window` 把"图片坐标系"坐标换算成"PC 屏幕绝对坐标"。
4. `desktop_input` 用 pyautogui 在该屏幕坐标执行（点击/滑动/长按/back/home/输入）。
5. `task_kugou` 状态机据画面判断进度，更新 history，决定下一步指令；直到累计 14 小时或停止。

## 6. 桌面自动化核心（验证重点）

scrcpy 窗口里是**手机画面**，但全部用**桌面手段**操作。UI-TARS 的 mobile 动作 → scrcpy 可接收的
PC 鼠标键盘操作翻译表：

| UI-TARS 输出（mobile 动作） | desktop_input 用 pyautogui 执行 | 依据 |
|---|---|---|
| `click(x,y)` | 左键点击映射后屏幕坐标 | scrcpy 转发触摸 |
| `scroll` / swipe | 鼠标按下 → 拖动 → 松开（drag） | 模拟滑动 |
| `long_press` | 鼠标按下 → hold → 松开 | 模拟长按 |
| `press_back` | **右键点击**（scrcpy 默认右键 = BACK） | scrcpy 快捷键 |
| `press_home` | **中键点击**（scrcpy 默认中键 = HOME） | scrcpy 快捷键 |
| `type(content)` | `pyautogui.typewrite`（scrcpy 转发键盘） | 输入文字 |

> 注：scrcpy 不同版本默认快捷键可能不同，实测时以实际版本为准；将映射做成 config 可调。

**坐标映射算法：**

1. `pygetwindow`/`win32gui` 按标题找 scrcpy 窗口，记录屏幕位置 `(left, top)` 与内容区大小 `(W_win, H_win)`。
2. 截图只截内容区，得到图片尺寸 `(W_img, H_img)`。
3. UI-TARS 在图片坐标系返回 `(x_img, y_img)`。
4. 屏幕绝对坐标：`x_screen = left + x_img * (W_win / W_img)`，`y_screen = top + y_img * (H_win / H_img)`。
5. pyautogui 点 `(x_screen, y_screen)`。

每个循环都重新定位窗口（可能被移动/缩放）并 `activate()` 前置，保证操作落在 scrcpy 上。

## 7. 任务状态机（酷狗）

不写死点击序列，状态机 + UI-TARS 每步看图决策：

```
START
 └─ press_home（中键）回桌面，建立确定起点
 └─ 找到并点击酷狗图标进入；若已在酷狗内，UI-TARS 识别后跳过

LOCATE_ENTRY（探索找广告入口）
 └─ 指令："找到'免费看广告领VIP'/'看视频得会员'入口并点击"
 └─ 找不到 → 去"我的"/"VIP中心"翻找（scroll）
 └─ 最多 N 步未找到 → 报告并停

WATCH_AD（看广告子循环）
 └─ 点"看视频" → 等待广告播放（wait + 倒计时观察）
 └─ 广告结束 → 找"关闭/×/领取"点掉
 └─ 处理弹窗（领取成功、继续观看等）

CHECK_PROGRESS
 └─ 读当前累计 VIP 时长（UI-TARS 视觉问答）
 └─ ≥ 14 小时 → DONE
 └─ "今日已领完/暂无机会" → STOP_LIMIT（报告今日上限 + 下次重试时间）
 └─ 否则 → 回 WATCH_AD
```

状态：用 `UITarsClient.append_history` 保留多轮上下文；本地维护 `rounds` 计数与"上次画面 hash"
防死循环。

## 8. 健壮性 / 任意状态可启动

| 风险 | 处理 |
|---|---|
| 起点未知 | 每次启动先 `press_home` 回桌面建立确定起点，再找酷狗图标 |
| scrcpy 窗口被遮挡/移动/缩放 | 每循环重定位 + `activate()` 前置；坐标按当前窗口大小重算 |
| UI-TARS 解析失败/低置信 | 本地失败 → OpenRouter 兜底；连续失败 N 次 → 截图存档并报告退出 |
| 卡同一画面死循环 | 记录画面 hash + 步数；连续 K 步无变化 → `press_back` 跳出或报告 |
| 误触发付费/订阅页 | 识别"支付/开通确认"页 → `press_back` 退出，不点确认 |
| 广告需等待 | `wait()` + 轮询截图，检测到"关闭/×"再继续 |
| 今日达上限 | 识别"已领完"文案 → 正常停止，报告今日上限 + 下次重试时间 |
| 全程留痕 | 每步截图存 `automation/desktop/runs/<时间戳>/` 便于复盘 |

**命令行参数（仿 web 程序风格）：**
`--target-hours 14`、`--max-rounds`、`--openrouter-key`、`--local-url`、`--scrcpy-title`、
`--dry-run`（只看不点，验证 grounding）。

## 9. 测试计划（TDD，分层；连手机的需用户显式授权后才执行）

按 AGENTS.md 单元/集成/E2E 分层，代码放 `automation/desktop/tests/`，基于根目录 `.venv`：

- **单元（不连手机）**：
  - 坐标映射函数（图坐标 ↔ 屏幕坐标，纯数学，可断言）
  - 手势翻译表（mobile 动作 → pyautogui 调用，mock pyautogui）
  - action 解析（复用并验证 `parse_action_simple`）
- **集成（连手机/scrcpy，需授权）**：
  - 窗口定位 + 截图真实跑通
  - `--dry-run` 验证 UI-TARS 在真实酷狗截图上正确给坐标
- **E2E（连手机，需授权）**：
  - 完整跑一次刷 VIP 到 14 小时；每步截图留档，关键节点用截图（多模态/人工）确认

> 测试只在用户明确说"开始测试"后进行；当前手机被其他程序占用，先只做设计与编码。

## 10. 单元边界小结

- `scrcpy_window`：输入窗口标题，输出截图 + 坐标映射；不关心点什么。
- `desktop_input`：输入"动作字典 + 屏幕坐标"，输出 pyautogui 调用；不关心任务语义。
- `uitars_agent`：输入图 + 指令 + history，输出动作字典；不关心窗口与桌面。
- `task_kugou`：编排上述三者跑状态机；不直接碰 pyautogui/win32。
- 每个单元可独立理解与测试。
