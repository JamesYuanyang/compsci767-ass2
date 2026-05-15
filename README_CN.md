# 个人任务规划智能体

COMPSCI 767 Assignment 2  
学生：Nanyuanyang Zhang  
学号：961188227

GitHub 仓库：https://github.com/JamesYuanyang/compsci767-ass2

演示视频：https://youtu.be/SqmoX3l20oQ

## 简短说明

Personal Task Planning Agent 是一个本地 Web 应用，可以把学生输入的目标或粘贴的作业说明转换成可执行的任务计划。系统会识别交付物、截止日期、可用工作时间、优先级、反馈和安全风险，并生成带有进度追踪、最近计划记忆和可解释 Agent Trace 的计划。

该应用不依赖付费 API key 即可复现。它可以选择性地使用本地 Ollama 模型进行作业说明分析；如果 Ollama 不可用，系统会自动使用规则式 fallback，仍然可以生成计划。

## 功能

- 解析作业说明，包括 report 要求、GitHub 仓库要求、截图、README、演示视频、commit checkpoints、API 工作、Web UI 工作、memory 和 safety checks。
- 支持非作业类目标的普通目标规划。
- 通过 `/api/feedback` 支持反馈更新，例如减少可用时间、完成 README、未完成 demo video、完成 report 或遇到 blocker。
- 区分不同的安全概念：
  - `recommended_effort_hours`：完整、高质量完成所有任务的理想时间。
  - `available_hours`：用户输入的可用工作时间。
  - `planned_hours`：压缩到用户可用时间内的计划时长。
- Agent Trace 面板，包含 Perception、Decision、Action、Memory 和 Safety Check 部分。
- 基于任务状态进行进度追踪。
- Focus Timer 工作流：当任务状态设置为 `doing` 时，会打开计时器视图，显示当前任务、支持提示、计划时间、优先级以及 Done/Pause 操作。
- Pause / Rest memory：保存当前活跃任务和已累计的专注时间，应用重启后可以恢复计划。
- Resume evaluation：重新载入最近保存的计划，重新计算 deadline pressure，并在时间变紧时建议进行反馈更新或生成新计划。
- Recent Plans memory：显示短标题、日期、任务数量、计划时长以及 generated/updated 标签。
- FastAPI JSON API 加静态浏览器 UI。

## Agent 架构

```text
User Input
  -> Perception Module
  -> Decision / Planning Module
  -> Safety Checker
  -> Action Module
  -> Memory Store
  -> Web UI + API
```

- Perception：识别输入类型、目标、截止日期、可用工作时间、优先级、交付物、约束和作业类需求。
- Decision：选择规划策略，优先处理必需交付物，分配可用时间，并应用反馈规则。
- Action：生成任务，更新任务状态，为反馈更新压缩计划，延后低优先级任务，并返回结构化 JSON。
- Memory：在 `data/memory.json` 中保存最近 session、活跃专注任务、已累计专注时间、暂停状态和恢复元数据。
- Safety：比较推荐工作量、可用工作时间、计划时间、截止日期压力和风险等级。

## 技术栈

- Python 3.12
- FastAPI
- Uvicorn
- Pydantic
- 静态 HTML、CSS 和 JavaScript
- JSON 文件记忆存储
- 可选本地 Ollama 模型：`llama3.2:1b`

## 安装

Windows PowerShell：

```powershell
cd D:\compsci767-ass2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS/Linux：

```bash
cd compsci767-ass2
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 如何运行后端

推荐的 Windows 命令，默认启用 Ollama：

```powershell
cd D:\compsci767-ass2
powershell -ExecutionPolicy Bypass -File .\start-agent.ps1
```

该脚本会在需要时启动 Ollama，检查 `llama3.2:1b`，设置 LLM 环境变量，并启动 FastAPI 应用。

如果 8000 端口被占用：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-agent.ps1 -Port 8001
```

手动启动后端：

```powershell
cd D:\compsci767-ass2
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

后端运行地址：

```text
http://127.0.0.1:8000
```

## 如何运行前端

前端由同一个 FastAPI 应用提供服务。启动 Uvicorn 后，在浏览器打开：

```text
http://127.0.0.1:8000
```

## 可选 Ollama 设置

应用在没有 Ollama 的情况下也可以工作。若要启用可选的本地 LLM 分析：

```powershell
$env:OLLAMA_MODELS="D:\Ollama\Models"
D:\Ollama\App\ollama.exe serve
D:\Ollama\App\ollama.exe pull llama3.2:1b
```

然后使用以下环境变量运行应用：

```powershell
$env:LLM_PROVIDER="ollama"
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
$env:LLM_MODEL="llama3.2:1b"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

如果 Ollama 没有运行，系统会自动使用规则式 planner。

## API 用法

### 生成计划

```bash
curl -X POST http://127.0.0.1:8000/api/plan \
  -H "Content-Type: application/json" \
  -d '{
    "goal_or_brief": "Build an intelligent software agent prototype. Report: 2 pages. Page 1 should include GitHub repo link, system design diagram and explanation. Page 2 should include screenshots and explanations of how the system works. GitHub repo should include README.md with reproduction instructions, a 2-minute demo video link, and commit checkpoints.",
    "deadline": "2026-05-21",
    "available_hours": 8,
    "priority": "High"
  }'
```

也支持旧字段名 `goal`：

```json
{
  "goal": "Complete the assignment report and demo",
  "deadline": "2026-05-21",
  "available_hours": 8,
  "priority": "high"
}
```

### 反馈更新

```bash
curl -X POST http://127.0.0.1:8000/api/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "SESSION_ID_HERE",
    "feedback": "I only have 2 hours today",
    "available_hours": 2
  }'
```

`/api/feedback` 会在原 session 上进行更新。它适合简单的进度、范围、时间预算或 blocker 反馈。如果要使用不同的截止日期，应通过 `/api/plan` 生成新计划。

### 更新任务状态

```bash
curl -X PATCH http://127.0.0.1:8000/api/sessions/SESSION_ID_HERE/tasks/TASK_ID_HERE \
  -H "Content-Type: application/json" \
  -d '{"status": "done"}'
```

有效状态包括 `todo`、`doing`、`done` 和 `blocked`。

当任务被设置为 `doing` 时，Web UI 会进入 Focus Timer 模式。

### Pause / Rest

```bash
curl -X POST http://127.0.0.1:8000/api/sessions/SESSION_ID_HERE/pause
```

该操作会保存活跃任务、暂停状态和已累计专注时间。Web 应用不会强制关闭本地服务器；暂停后用户可以手动停止服务，并在之后重新启动。

### 恢复最近保存的计划

```bash
curl http://127.0.0.1:8000/api/resume
```

该接口会恢复最近保存的 session，重新计算距离截止日期的时间，刷新 safety warnings，并在存在暂停任务时报告上次活跃任务。

### 最近计划

```bash
curl http://127.0.0.1:8000/api/plans
```

保留兼容接口 `/api/memory`。

## 示例输入

```text
Build an intelligent software agent prototype.
Report: 2 pages.
Page 1 should include GitHub repo link, system design diagram and explanation.
Page 2 should include screenshots and explanations of how the system works.
GitHub repo should include README.md with reproduction instructions, a 2-minute demo video link, and commit checkpoints.
```

## 示例输出结构

```json
{
  "session_id": "...",
  "tasks": [
    {
      "title": "Implement core agent loop: perception, decision, action, memory, safety",
      "status": "todo",
      "effort_hours": 1.2
    }
  ],
  "planned_hours": 8,
  "recommended_effort_hours": 13.5,
  "safety_warnings": [
    "Recommended effort exceeds available working hours."
  ],
  "agent_trace": {
    "perception": ["Input type: assignment_brief"],
    "decision": ["Selected planning strategy: assignment_deliverable_extraction"],
    "action": ["Generated plan: 12 tasks, 8h planned."],
    "memory": ["Current session ID: ..."],
    "safety_check": ["Recommended effort: 13.5h"]
  },
  "perception": {
    "deliverables": ["GitHub repository", "README", "report", "screenshots", "demo video"]
  }
}
```

## Commit Checkpoint 建议

- `checkpoint: implement core agent planning loop`
- `checkpoint: add API and web UI workflow`
- `checkpoint: add feedback updates and safety checks`
- `checkpoint: update memory, progress, and trace panels`
- `checkpoint: prepare README, report outline, and demo evidence`

## 已知限制

- 规则式自然语言解析有意保持简单，可能无法识别不常见的表达方式。
- 可选的 Ollama 分析可以改善解析效果，但依赖本地模型可用性。
- Memory 使用本地 JSON 文件，而不是数据库。
- 由于这是本地作业原型，因此没有加入身份验证。
- 截止日期变化应通过 `/api/plan` 生成新计划处理；`/api/feedback` 只更新当前活跃 session。