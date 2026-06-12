# AGENTS.md — ragateway 项目规则

---

## 目录结构

##开发基本原则# 

开发的根目录在automation

1. agent对用户的所有回复都要用中文，用中文输出中间思路和最后总结，不要用其他语言。
2. 所有开发和测试必须按照文档来进行。
3. 小的修改直接在git的origin/main上进行，任务完成以后，要自动执行git commit/push。大的需要多个阶段/步骤的修改，请求用户批准后，在分支上进行，按阶段 git commit/push到分支，所有phase/step任务全部完成后要把分支代码merge会origin/main。
4. 所有agent发现的bug，为了保证任务完成，可以临时patch修复，但是不能只有patch修复，同时从设计架构角度修改代码固化fix，确保以后正常使用系统时你的fix也被包括，系统能正常工作。
5. 修改完代码做测试时，如果是容器化环境，要先构建image，重启容器再开始测试。
6. 如果发现文档有错误或者遗漏，需要背离文档做开发，必须先和用户确认，获得批准后，先修改文档，再做开发。
7. 除了不能确定的设计方向，和碰到困难多次尝试你无法解决，不要不停让用户确认细节的执行命令
8. 强制TDD，开发计划/测试计划必须同步，开发完一个组件，完成测试任务才算完成
9. 测试代码基于根目录.venv下的虚拟环境，不要基于本机的裸python，如果不存在用conda创建
10. 不应该有很多孤立的py/js工具用于测试，应该分单元（子组件接口），集成（项目接口），E2E（项目ui接口，使用playwright）case，在测试计划/设计文档中描述，实现成测试case代码。所有的py/js工具都是完成某个测试目的，应该把孤立py/js工具的功能，转换成这些case的代码，如果实现某个测试目的时，应该执行某一个case，或者某几个case，或者某一个test suite来完成。
11. 测试计划/设计文档需要这样设计，测试case代码需要这样实现：原则上所有的case执行前，开始前要检查是否有本测试不需要的数据，如果有要清空，结束时要把自己写入的数据清空。如果是一个test suit每次都必须以suite为单位执行，那可以以suite为单位来做开始和结束的数据清理。特别是单元测试case直接测试子组件接口，或者更细粒度的模块/函数，不能保留数据，必须在测试后删除恢复系统远洋。只有集成/接口（开发目标的整个系统接口）测试和E2E测试case，才支持在用户显式要求下保留测试结果。
12. 长程开发可能碰到上下文长度超出不得不 reset session。每次开发/测试推进到新的步骤时，把当前处于开发计划/测试计划的哪一步、以及当前步骤足够的上下文，记录到 `context.md` 中。每次新 session 开始开发前，先读 `context.md` 找到进度和上下文，再开始开发。
13. 按照计划逐步做开发和测试时，每一步完成、做下一步之前，先把这一步修改的文件 git commit/push。
14. 测试计划应该通过依赖关系仔细计划组件开发顺序，避免引入mock/stub，必须引入的要明确得到许可。项目开发/测试顺序
  先无开发/定制少的组件，再开发复杂的组件
  先无依赖/依赖少的组件，再依赖多的组件
15. 对于E2E测试，有webUI的组件，要用playwright捕捉测试case执行中的屏幕，生成和测试case同名的截图（成功get并且confirm到case对应的webUI的状态后）和录屏mp4（整个测试过程），并每个case用多模态大模型分析截图
16. 对于设计被更改了的模组，要重新做开发和测试。对这个模组更改的地方有依赖、可能产生连锁反应的其他模组，也要评估是否需要修改和重新做开发和测试。
17. **隔离环境原则（强制）：开始任何代码开发（含测试代码）之前，必须先建立不污染宿主机（host）的隔离环境：**
   - **所有服务组件**（API 服务、数据库、消息队列等）**必须运行在 Docker 容器中**，不得直接安装到宿主机。容器定义统一放在 `docker-compose.yml`（含 profiles 分阶段启用）。
   - **测试代码（Python）必须运行在统一的 Python 虚拟环境中**，路径为项目根目录下的 `.venv/`。开发前先激活：
     ```bash
     # Windows PowerShell
     .\.venv\Scripts\Activate.ps1
     # Linux / macOS / WSL
     source .venv/bin/activate
     ```
     创建命令（首次，仅需一次）：
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\pip install -r requirements-test.txt
     ```
   - `.venv/` 已加入 `.gitignore`，不提交到仓库。
   - **每次向 `.venv` 安装新包后，必须立即 freeze 并提交**：
     ```bash
     .venv/Scripts/pip freeze > requirements-test.txt
     git add requirements-test.txt && git commit -m "chore: update requirements-test.txt"
     ```
   - **禁止**：直接用宿主机全局 `pip install`；跳过 venv 直接运行测试；将依赖安装到容器外的全局环境。

## WSL 执行规范

从 Windows 侧（Claude Code / PowerShell）调用 WSL 命令时，使用 `-lc` 参数确保加载登录 shell 环境（含 `~/.bash_profile` / `~/.bashrc` 中的环境变量）：

```bash
wsl -e bash -lc 'cd /mnt/d/ragateway && your_command'
```

- 用单引号包裹命令，让变量（如 `$GH_TOKEN`）在 WSL 内展开而非 Windows 侧展开
- 环境变量（如 `GH_TOKEN`）应写在 `~/.bashrc` 的 early-return 判断**之前**，或存放于 `~/.gh_token` 文件并在 bashrc 开头 source

---

- `rag-design.md` — 主设计文档（Markdown）
- `rag-design.html` — 设计文档 HTML 渲染版（从 .md 自动生成）
- `ARCH.md` — 项目文件架构说明
- `tools/` — 工具脚本（import_to_neo4j.py / md_ref_graph.py / render_schema_html.py）
- `medical-device-reg/` — 知识图谱数据（sources / wiki / schema）
- `test-data/` — 测试用源文档（含3个ZIP包 + Test Case 16_A/B docx + EN/JA译文）
- `docker-compose.yml` — Neo4j 服务
- `reports/` — 测试报告（每个 Step 完成后生成，含截图/录像引用）



## 运行环境

### Shell 环境检测（必须在运行任何命令前执行）

每次对话开始时，**先检测当前 shell 环境并缓存结果**，缓存有效期 4 小时。

**检测脚本（优先用 bash 执行，PowerShell 不可用时跳过）：**

```bash
# 缓存文件路径
CACHE_FILE="${TMPDIR:-/tmp}/.ragateway_shell_env"

# 检查缓存是否在 4 小时内
if [ -f "$CACHE_FILE" ]; then
  cache_age=$(( $(date +%s) - $(date -r "$CACHE_FILE" +%s 2>/dev/null || stat -c %Y "$CACHE_FILE") ))
  [ "$cache_age" -lt 14400 ] && SHELL_ENV=$(cat "$CACHE_FILE")
fi

if [ -z "$SHELL_ENV" ]; then
  if grep -qi microsoft /proc/version 2>/dev/null; then
    SHELL_ENV="wsl"
  elif [ "$(uname -s)" = "Linux" ]; then
    SHELL_ENV="linux"
  elif echo "$MSYSTEM" | grep -q "MINGW\|MSYS"; then
    SHELL_ENV="gitbash"
  else
    SHELL_ENV="unknown"
  fi
  echo "$SHELL_ENV" > "$CACHE_FILE"
fi

echo "Shell env: $SHELL_ENV"
```

PowerShell 下的备用检测（bash 不可用时）：

```powershell
$cacheFile = "$env:TEMP\.ragateway_shell_env"
$shellEnv = $null
if (Test-Path $cacheFile) {
  $age = (Get-Date) - (Get-Item $cacheFile).LastWriteTime
  if ($age.TotalHours -lt 4) { $shellEnv = Get-Content $cacheFile }
}
if (-not $shellEnv) {
  $shellEnv = "powershell"
  Set-Content $cacheFile $shellEnv
}
Write-Host "Shell env: $shellEnv"
```

**根据检测结果选择命令执行策略：**

| 环境 | 策略 |
|------|------|
| `powershell` | 只使用 PowerShell 命令 |
| `gitbash` | 优先 bash 命令；遇到问题无法解决时切换 PowerShell |
| `wsl` | 只使用 bash 命令（不使用 PowerShell） |
| `linux` | 只使用 bash 命令（不使用 PowerShell） |

## Git 操作

**所有 git 命令必须使用专用 SSH key：**

```bash
GIT_SSH_COMMAND="ssh -i ~/.ssh/alexliu_ragateway_key" git push origin main
GIT_SSH_COMMAND="ssh -i ~/.ssh/alexliu_ragateway_key" git pull origin main
GIT_SSH_COMMAND="ssh -i ~/.ssh/alexliu_ragateway_key" git fetch origin
```

- **Key 路径：** `~/.ssh/alexliu_ragateway_key`
- **Remote：** `git@github.com:bronzels/ragateway.git`
- **分支：** `main`

**每次任务完成后（无论修改多少文件），必须立即 commit + push，不允许只 commit 不 push。**

**Commit message 规范：** message 必须说明"为什么改、改了什么"，以便日后 rollback 时快速理解上下文。LLM 在 commit 时有完整对话上下文，应充分利用，写清楚本次任务的背景和变更摘要。格式：

```
<type>: <一句话摘要>

<背景/原因>
<主要变更列表>
```

示例：
```
chore: 删除AI审查临时文件，去掉所有文件名中的版本号

背景：review-part*.md 是 2026-05-18 AI审查产生的临时文档，已无保留价值；
文件名版本号（v27/v1/v2）由 git 历史管理，无需体现在文件名中。
变更：删除 review-part1/2/3.md；重命名 rag-design-v27→rag-design、
ragateway-plan-v1→ragateway-plan、ragateway-test-v1→ragateway-test、
import_to_neo4j_v2→import_to_neo4j；同步更新所有引用文件。
```

```bash
cd /d/ragateway
git add -A
git commit -m "..."

# push 前检测运行环境：WSL 或原生 Linux 需显式指定 SSH key，Windows 原生不需要
if [ "$(uname -s)" = "Linux" ] || grep -qi microsoft /proc/version 2>/dev/null; then
  GIT_SSH_COMMAND="ssh -i ~/.ssh/alexliu_ragateway_key" git push origin main
else
  git push origin main
fi
```

## 开发规范（强制，所有开发任务必须遵守）

### 1. 先 Infra 后开发，难度低先做

- Phase 1（基础设施 + 框架骨架）必须全部完成、测试通过，才能开始 Phase 2
- 同一 Phase 内：纯配置/脚手架类 Step 先做，定制逻辑复杂的后做
- 单纯连接层（Redis/PG schema）难度低，先做；LLM 编译类（llm-wiki-graph）难度高，后做

### 2. TDD 铁律 — 先测试后提交

**每个 Step 的完成标准（DoD）必须严格按以下顺序执行，缺一不可：**

```
1. 实现代码
2. 运行该 Step 对应的测试用例（见 ragateway-test.md 对应章节）
3. 所有 case 全部 PASS
4. 将测试结果写入 reports/ 目录的测试报告 MD 文件
5. git commit + push
6. 才能开始下一个 Step
```

⛔ **禁止行为：** 代码写完但测试没全过就 commit；跳过测试直接进入下一步；"应该可以"替代实际运行验证。

### 3. 测试报告格式（每个 Step 完成后必须生成）

测试报告文件路径：`reports/step-{STEP_ID}-{YYYY-MM-DD}.md`  
例：`reports/step-2.2-2026-05-21.md`

**必须包含：**

```markdown
# Step {ID} 测试报告

## 测试环境
- 日期：YYYY-MM-DD
- 版本：git commit SHA

## 单元测试结果
| Case ID | 描述 | 结果 | 耗时 |
|---------|------|------|------|
| TEST §X.Y-01 | ... | ✅ PASS | 0.1s |

## pytest 输出摘要
\`\`\`
pytest tests/... -v
X passed, 0 failed in Xs
\`\`\`

## 已知问题
（无 / 或描述）
```

### 4. 网页端到端测试 — Playwright + 多模态大模型录制

**针对所有涉及 Web UI 的 Step（Step 3.4 / Step 3.5 / TEST §5 E2E）：**

#### 4.0 ⚠️ Claude 必须亲自验证截图（强制，不可跳过）

**每个 UI E2E case 完成后，Claude 必须：**

1. **用 `Read` tool 读取截图文件**（PNG 图片），亲自看图判断：
   - 页面是否正确加载（有实际内容，不是空白或 loading 状态）
   - 功能是否符合设计文档要求（正确的组件/数据/状态）
   - **特别检查：UI 是否显示了真实数据**（表格有数据行，不是"0 items"的空表）

2. **在对话中明确陈述每张截图的验证结论**，格式：
   ```
   截图验证 [case_id]:
   ✅/❌ [观察到的内容描述]
   ✅/❌ 数据非空：[具体数据内容]
   ✅/❌ 符合设计要求：[依据]
   结论：PASS / FAIL / 需要修复
   ```

3. **发现问题必须修复**：若截图显示空数据、错误状态、或与设计文档不符，必须：
   - 停止测试
   - 修复后端连接/数据/配置
   - 重新运行测试并重新验证截图
   - **不允许**：接受空表格/空数据，然后仅依赖 LLM 的宽松判断

4. **录像验证**：检查 `tests/e2e/reports/videos/` 下是否有对应 case 的录像文件（非空），若无则修复录像保存逻辑

**这是强制要求，仅凭脚本通过和 LLM 返回 True 不等于验证完成。**

#### 4.1 Playwright 数据验证

```python
# tests/e2e/test_ui_*.py
from playwright.async_api import async_playwright

async def test_ui_case(case_id: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        # 操作 UI ...
        # 断言数据正确性
        assert await page.locator(...).text_content() == expected
```

#### 4.2 屏幕录制（每个 UI 测试 case 必须）

```python
# 每个 UI case 启动录制
await page.video.path()   # Playwright 内置录制

# 截图时机：
# 1. 操作前（初始状态）
# 2. 关键交互后（结果展示）
# 3. 断言时（最终状态）
await page.screenshot(path=f"tests/e2e/reports/screenshots/{case_id}-final.png")
# 注意：截图必须保存在 tests/e2e/reports/screenshots/ 下，不是 reports/screenshots/
```

#### 4.3 多模态大模型质量检查（所有 UI E2E case 必须）

```python
# tests/e2e/multimodal_checker.py
import base64, httpx

async def check_screenshot_with_llm(
    screenshot_path: str,
    case_id: str,
    expected_description: str,
) -> dict:
    """
    用多模态 LLM（GPT-4o Vision 或 Gemini）验证截图内容。
    问题："图中是否显示了 {expected_description}？如有异常请描述。"
    """
    with open(screenshot_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    # 调用 OpenRouter GPT-4o Vision ...
    return {"case_id": case_id, "passed": True/False, "llm_comment": "..."}
```

#### 4.4 测试报告记录格式（UI case 专用）

测试报告中 UI case 必须包含：

```markdown
## UI 测试 Case: {case_id}

**截图：**
![{case_id} 初始状态](screenshots/{case_id}-before.png)
![{case_id} 最终状态](screenshots/{case_id}-final.png)

**录像：** [视频文件](videos/{case_id}.webm)

**多模态检查结果：**
- LLM 判断：✅ 符合预期 / ❌ 异常
- LLM 描述：{llm_comment}

**Playwright 断言：** ✅ PASS / ❌ FAIL
```

**文件命名约定（case_id 与文件名严格对应）：**

```
reports/
├── screenshots/
│   ├── A01-before.png
│   ├── A01-final.png
│   ├── E01-naive_only-before.png
│   └── E01-naive_only-final.png
├── videos/
│   ├── A01.webm
│   └── E01-naive_only.webm
└── step-{ID}-{date}.md   ← 汇总报告，内嵌 ![img](...) 引用
```

### 5. 并行开发规则

同一 Phase 内无依赖关系的 Step **必须并行开发**：

| 可并行组 | Steps |
|---------|-------|
| Phase 1 并行组A | Step 1.0 ‖ Step 1.1（均无依赖） |
| Phase 1 并行组B | Step 1.2 ‖ Step 1.3（均依赖 1.1，互不依赖） |
| Phase 1 并行组C | Step 1.5 ‖ Step 1.6（均依赖 1.4，互不依赖） |
| Phase 2 并行组A | Step 2.1 ‖ Step 2.3 ‖ Step 2.4（均依赖 1.x，互不依赖） |
| Phase 3 并行组A | Step 3.4 ‖ Step 3.5 ‖ Step 3.6 ‖ Step 3.7（均依赖 2.x，互不依赖） |
| Phase 4 并行组A | Step 4.1 ‖ Step 4.3（互不依赖） |

#### 5.1 并行任务必须用独立 Subagent 执行

**凡是上表中标注为可并行的 Step 组，主 Agent 必须通过 `Agent` tool 派发独立 subagent 并行执行，不得串行完成。**

**操作规范：**

1. **同一消息内派发所有并行 subagent**（一条消息中多个 `Agent` tool call），让它们真正并发运行。
2. **每个 subagent 的 prompt 必须自包含**：包括任务目标、负责的文件列表（`FILES_OWNED`）、依赖的接口约定、环境变量、测试运行命令。不得依赖另一个 subagent session 的上下文。
3. **文件边界不得重叠**：并行 subagent 各自负责的文件不得有交集，在派发前在 prompt 中明确声明。
4. **等所有 subagent 完成后**，由主 Agent 汇总结果、运行集成测试、写测试报告、git commit + push。

**派发示例（Step 1.2 ‖ Step 1.3）：**

```
# 主 Agent 一条消息内同时发出两个 Agent tool call：
Agent(prompt="实现 Step 1.2 PostgreSQL schema 验证 ...", subagent_type="claude")
Agent(prompt="实现 Step 1.3 Redis 连接层 ...", subagent_type="claude")
# → 两个 subagent 并发运行
```

**不适合 subagent 的情况：**
- 单一文件的小修改（直接在主 Agent 做）
- 需要交互确认的决策（先向用户确认，再派发）
- 集成测试和 git commit（统一由主 Agent 完成）

### 6. 设计文档一致性

**开始任何 Step 前，必须先读 rag-design.md 对应章节，以文档为准，不得凭记忆行事。**  
如实现需要背离文档 → 停止 → 报告分歧 → 先改文档再改代码（见 AGENTS.md 中的 doc-code consistency 规则）。

### 7. 测试真实性原则（强制）

**所有测试必须是真实测试，禁止在未经测试计划明确授权的情况下引入 stub/mock。**

#### 7.1 允许使用 mock 的场景（仅限测试计划中明确出现的以下模式）

| 类型 | 允许原因 | 示例 |
|------|---------|------|
| **外部 HTTP API mock（respx）** | 第三方服务（OpenAI、Anthropic、MinerU、RAGFlow）在 CI 环境不可用，且测试目标是本地代码逻辑，非网络层 | `@respx.mock` 拦截 OpenAI、RAGFlow HTTP 调用 |
| **subprocess mock** | 依赖本地二进制（SwarmVault CLI）不在 CI 环境，测试目标是调用参数和返回值处理逻辑 | `patch("subprocess.run")` for SwarmVault |
| **plugin_manager patch（§2.5）** | 摄入流水线单元测试，目标是流水线编排逻辑，非插件实现本身 | `patch("ragateway.core.ingest.plugin_manager")` |

#### 7.2 禁止行为

⛔ **禁止在测试计划未明确要求的地方：**
- 用 `AsyncMock` / `MagicMock` 替换本项目自己的数据库层（PostgreSQL、Redis、Elasticsearch）
- 用 in-memory dict / stub 替换需要真实 DB 读写的 API 端点
- 为了让测试通过而修改生产代码，加入仅用于测试的分支、标志位或假实现
- 将集成测试降级为单元测试（把真实服务连接替换成 mock）

#### 7.3 缺乏测试数据时的处理规则

如果真实测试需要测试数据（文件、数据库记录、外部服务响应）而数据不存在：

1. **停下来**，不要自行创建 stub/mock 绕过
2. **向用户明确说明**：缺少什么数据、路径/格式要求是什么
3. **等用户确认**提供数据或批准替代方案后再继续

---

## 🔴 受保护页面（绝对不能删除或破坏）

以下两个网页及其对应的程序文件**绝对不能被删除、覆盖或以任何方式导致其不可访问**：

| 页面 | 本地文件路径 | 说明 |
|------|------------|------|
| https://design.bot.regdesk.ai/medical-kg/ | `/home/ubuntu/designs/medical-kg/index.html` | 医疗法规知识图谱可视化（D3.js 交互图） |
| https://design.bot.regdesk.ai/medical-kg/schema.html | `/home/ubuntu/designs/medical-kg/schema.html` | 医疗器械 Schema 可视化页面 |

**强制规则：**
- ❌ 任何 `rm`、`mv`、`cp --overwrite`、`file_server` 重配置操作，如果影响 `/home/ubuntu/designs/medical-kg/` 目录内的文件，必须先确认上述两个文件不受影响
- ❌ 不得修改 Caddyfile 中 `/medical-kg/*` 的路由配置，也不得删除该段 `handle` 规则
- ✅ 在该目录新增文件可以，但不能覆盖现有 `index.html` 和 `schema.html`
- ✅ 如有疑虑，操作前先 `ls /home/ubuntu/designs/medical-kg/` 确认文件存在

## 使用 Superpowers Sub-skills

Superpowers 是一套可组合的 agentic 开发 sub-skills，不需要全量引入，按需在特定场景加载对应 sub-skill。**加载方式：在 Claude Code 中用 `Skill` tool 调用，或直接 `read` 对应 SKILL.md 文件。**

> **优先级：** AGENTS.md 中的规则 > Superpowers sub-skills > 默认行为。如有冲突，以 AGENTS.md 为准。

### 何时加载哪个 Sub-skill

| 场景 | Sub-skill | 加载路径 |
|------|-----------|---------|
| 遇到 bug、测试失败、行为异常，**开始 fix 之前** | `systematic-debugging` | `~/.openclaw/skills/superpowers/skills/systematic-debugging/SKILL.md` |
| 两个 Claude Code **并行**开发，派发独立任务前 | `dispatching-parallel-agents` | `~/.openclaw/skills/superpowers/skills/dispatching-parallel-agents/SKILL.md` |
| 当前 session 内执行有多个独立任务的实现计划时 | `subagent-driven-development` | `~/.openclaw/skills/superpowers/skills/subagent-driven-development/SKILL.md` |
| 完成一个 Step 或 feature，**合并前请求 review** | `requesting-code-review` | `~/.openclaw/skills/superpowers/skills/requesting-code-review/SKILL.md` |
| 收到 review 意见，准备处理反馈 | `receiving-code-review` | `~/.openclaw/skills/superpowers/skills/receiving-code-review/SKILL.md` |
| 一个开发分支完成、测试全过，准备合并/PR | `finishing-a-development-branch` | `~/.openclaw/skills/superpowers/skills/finishing-a-development-branch/SKILL.md` |

### 两个 Claude Code 并行开发的协作规范

本项目用两个 Claude Code 实例并行开发（对应 ragateway-plan.md 中的 🔀 并行 Step 组）。除了 AGENTS.md 中的规则外，还需：

1. **加载 `dispatching-parallel-agents`**：派发并行任务前必须读取，确保：
   - 每个实例的任务 brief 是精确构造的，不继承另一个 session 的上下文
   - 明确声明 `FILES_OWNED`（各自负责的文件列表不得有交集）
   - 任务 brief 中明确依赖关系和接口约定

2. **文件边界强制**：并行开发时，两个实例的修改文件不得重叠。开始前在 `PROJECT-STATUS.md` 里写清楚各自的文件边界。

3. **集成点约定**：两个实例完成各自的独立模块后，由 **一个** 实例负责集成（另一个不参与），集成前做 `git diff` 检查。

4. **Review 轮换**：每个 Step 完成后，由另一个实例（或新 subagent）做 `requesting-code-review`，而不是自己 review 自己的代码。

### 不需要加载的 Sub-skills（AGENTS.md 已覆盖）

| Sub-skill | 原因 |
|-----------|------|
| `brainstorming` | 设计已定，不需要再 brainstorm |
| `writing-plans` | ragateway-plan.md 已完备，比这个更具体 |
| `test-driven-development` | AGENTS.md §2（TDD 铁律）已覆盖 |
| `verification-before-completion` | AGENTS.md §2（DoD）已覆盖 |
| `using-git-worktrees` | 统一用 main branch + feature flag，不用 worktree |

---

## 文档 HTML 生成

设计文档修改后，同步重新生成 HTML：

```bash
cd /home/ubuntu/workspace/ragateway
python3 - << 'EOF'
import markdown
from pathlib import Path

src = Path("rag-design.md").read_text(encoding="utf-8")
md = markdown.Markdown(extensions=["fenced_code", "tables", "toc", "nl2br", "attr_list"])
body_html = md.convert(src)
toc_html  = md.toc
# ... (完整脚本见 tools/gen_doc_html.py)
EOF
```

或直接运行：
```bash
python3 tools/gen_doc_html.py
```
