# JobsDB 自动投递脚本（jobsdb_apply.py）使用说明

针对 **hk.jobsdb.com** 的远程软件岗自动申请脚本。

> ⚠️ **关键点：JobsDB 有 Cloudflare Turnstile 人机验证**，对 CDP 自动化浏览器检测极强，
> rebrowser + 隐身参数也**无法稳定自动通过**（手动点验证勾选框会一直循环）。
> 因此**必须用「连接真实 Chrome」(CDP) 模式**：你在自己手动启动的真实 Chrome 里以正常用户
> 身份通过验证并登录，脚本只通过 CDP 接管驱动浏览器。这样 Cloudflare 看到的是真人会话。

---

## 一、前置条件

- 已安装 Google Chrome（路径示例：`C:\Program Files\Google\Chrome\Application\chrome.exe`）
- 项目根目录 `.venv` 已装好依赖（rebrowser-playwright / httpx 等）
- `automation/.env` 里有 `OPENROUTER_API_KEY=sk-or-v1-xxx`（验证职位用，始终走 OpenRouter）
- （可选）本地 UI-TARS 推理服务已启动，如 `http://192.168.3.14:8000/v1`
  - UI-TARS 仅在选择器找不到按钮时做视觉兜底，调用频率低

---

## 二、运行步骤（CDP 连接真实 Chrome，推荐）

### 步骤 1：完全退出 Chrome
关闭所有 Chrome 窗口，确保 Chrome 进程全部退出（否则下一步的调试端口不会生效）。

### 步骤 2：用调试端口启动 Chrome（独立 profile）
> Chrome 136+ 出于安全**禁止在默认 profile 上开调试端口**，必须用独立 `--user-data-dir`。

PowerShell：
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="D:\chrome-debug-jobsdb"
```

### 步骤 3：在这个新 Chrome 里手动通过验证 + 登录
1. 打开 https://hk.jobsdb.com/
2. 以**正常用户身份**通过 Cloudflare 人机验证（真人真浏览器，一般一次过）
3. 用邮箱 `bronzels@hotmail.com` 登录 → 输入邮件收到的验证码（OTP）完成登录

### 步骤 4：运行脚本连接该 Chrome
先 dry-run（只遍历+筛选+判断，不实际申请）验证无误：
```
.venv\Scripts\python.exe -u automation\jobsdb_apply.py --cdp-url http://127.0.0.1:9222 --dry-run --uitars-provider local --uitars-local-url http://192.168.3.14:8000/v1
```
确认筛选/列表抓取正常后，去掉 `--dry-run` 正式申请：
```
.venv\Scripts\python.exe -u automation\jobsdb_apply.py --cdp-url http://127.0.0.1:9222 --uitars-provider local --uitars-local-url http://192.168.3.14:8000/v1
```

> CDP 模式下脚本退出时**不会关闭你的 Chrome**（仅断开连接）。

---

## 三、命令行参数

| 参数 | 说明 |
|------|------|
| `--cdp-url`            | 连接已运行的真实 Chrome（如 `http://127.0.0.1:9222`）。**推荐，绕过 Cloudflare** |
| `--dry-run`            | 试运行：登录+遍历+筛选+判断+打印，但**不点 Apply / 不填表单 / 不记录** |
| `--openrouter-key`     | OpenRouter API key（优先级高于环境变量 / .env）。验证职位始终走 OpenRouter |
| `--uitars-provider`    | UI-TARS 提供方式：`openrouter`（默认）/ `remote` / `local` |
| `--uitars-local-url`   | local 方式本地/局域网推理地址（含 `/v1`），如 `http://192.168.3.14:8000/v1` |
| `--uitars-endpoint`    | remote 方式 endpoint URL（选 remote 时必填） |
| `--uitars-key`         | remote 方式鉴权 key（放 `x-api-key` header） |

---

## 四、筛选规则

职位需**同时满足**（由 OpenRouter 免费模型判断 `verify_jobsdb`，英文 JD）：
1. **软件开发岗**（排除运维/PHP/Django/C#-.NET 等，同 zhipin 远程标准）
2. **支持远程（remote）**
3. **不要求粤语（Cantonese）**——要求粤语则跳过

遍历来源：**Recommended（推荐）** + **Saved searches（保存的搜索）**。

---

## 五、申请表单处理

点 Apply 后 JobsDB 会问多个问题：
- **申请书（cover letter）**：每次都选「不附申请书」(No cover letter)
- **薪资要求**：职位有薪资范围 → 填范围上限或稍低于上限；无范围 → 统一填**月薪 40000 港币**
- 表单较复杂，遇到理解不了的界面会截图 + 暂停提示（调试阶段）

---

## 六、去重与报告

- 边遍历边写 `automation/jobsdb_applied.json`（已申请/已跳过的公司+职位+状态+时间）
- 已申请的职位（页面显示 **Applied**）或已在记录文件里的 → 跳过，不重复申请，加快速度
- 结束（含中断/报错）自动导出 CSV 到 `automation/reports/`（文件名含时间，utf-8-sig）

---

## 七、常见问题

**Q：一直卡在 "Just a moment..." / "Performing security verification"？**
A：这是 Cloudflare 验证。**不要用脚本自启动浏览器模式**，按本文「二、CDP 连接真实 Chrome」操作——在你手动启动的真实 Chrome 里通过验证。

**Q：脚本报 CDP 连不上 / 9222 端口未开？**
A：确认步骤 1 已**完全退出 Chrome**，步骤 2 用了 `--remote-debugging-port=9222` **和独立** `--user-data-dir`。
验证端口：浏览器访问 `http://127.0.0.1:9222/json/version` 应返回 JSON。

**Q：脚本提示未检测到登录态？**
A：在你的 Chrome 里确认已完成 JobsDB 邮箱登录；脚本会每 3 秒轮询检测，最长等 2 分钟。
