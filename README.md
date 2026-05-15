# Personal Task Planning Agent

COMPSCI 767 Assignment 2  
Student: Nanyuanyang Zhang  
Student ID: 961188227

GitHub repository: https://github.com/JamesYuanyang/compsci767-ass2

Demo video: https://youtu.be/SqmoX3l20oQ

## Short Description

Personal Task Planning Agent is a local web application that turns a student goal or pasted assignment brief into an actionable task plan. It detects deliverables, deadlines, available working hours, priority, feedback, and safety risks, then produces a plan with progress tracking, recent-plan memory, and an explainable Agent Trace.

The app is reproducible without paid API keys. It can optionally use a local Ollama model for brief analysis, but it has a rule-based fallback that still generates plans when Ollama is unavailable.

## Features

- Assignment-brief parsing for report requirements, GitHub repository requirements, screenshots, README, demo video, commit checkpoints, API work, web UI work, memory, and safety checks.
- Goal planning for non-assignment tasks.
- Feedback updates through `/api/feedback`, such as reduced time, finished README, unfinished demo video, completed report, or blocker notes.
- Separate safety concepts:
  - `recommended_effort_hours`: ideal time to finish everything properly.
  - `available_hours`: user-provided working time.
  - `planned_hours`: compressed plan duration allocated inside the available time.
- Agent Trace panel with Perception, Decision, Action, Memory, and Safety Check sections.
- Progress tracking based on task statuses.
- Focus Timer workflow: setting a task to `doing` opens a timer view with the current task, support hint, planned time, priority, and Done/Pause actions.
- Pause / Rest memory: saves the active task and elapsed focus time so the plan can be restored after restarting the service.
- Resume evaluation: reloads the latest saved plan, recalculates deadline pressure, and recommends a feedback update or new plan when time has become tight.
- Recent Plans memory with short titles, dates, task counts, planned hours, and generated/updated labels.
- FastAPI JSON API plus static browser UI.

## Agent Architecture

```text
User Input
  -> Perception Module
  -> Decision / Planning Module
  -> Safety Checker
  -> Action Module
  -> Memory Store
  -> Web UI + API
```

- Perception: identifies input type, goal, deadline, available working hours, priority, deliverables, constraints, and assignment-like requirements.
- Decision: chooses a planning strategy, prioritizes required deliverables, allocates available time, and applies feedback rules.
- Action: generates tasks, updates task statuses, compresses plans for feedback updates, defers lower-priority tasks, and returns structured JSON.
- Memory: stores recent sessions, active focus task, elapsed focus time, pause state, and resume metadata in `data/memory.json`.
- Safety: compares recommended effort, available working hours, planned hours, deadline pressure, and risk level.

## Tech Stack

- Python 3.12
- FastAPI
- Uvicorn
- Pydantic
- Static HTML, CSS, and JavaScript
- JSON file memory store
- Optional local Ollama model: `llama3.2:1b`

## Installation

Windows PowerShell:

```powershell
cd D:\compsci767-ass2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS/Linux:

```bash
cd compsci767-ass2
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## How To Run Backend

Recommended Windows command, with Ollama enabled by default:

```powershell
cd D:\compsci767-ass2
powershell -ExecutionPolicy Bypass -File .\start-agent.ps1
```

This starts Ollama if needed, checks `llama3.2:1b`, sets the LLM environment variables, and starts the FastAPI app.

If port 8000 is occupied:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-agent.ps1 -Port 8001
```

Manual backend command:

```powershell
cd D:\compsci767-ass2
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The backend runs at:

```text
http://127.0.0.1:8000
```

## How To Run Frontend

The frontend is served by the same FastAPI app. After starting Uvicorn, open:

```text
http://127.0.0.1:8000
```

## Optional Ollama Setup

The app works without Ollama. To enable optional local LLM analysis:

```powershell
$env:OLLAMA_MODELS="D:\Ollama\Models"
D:\Ollama\App\ollama.exe serve
D:\Ollama\App\ollama.exe pull llama3.2:1b
```

Then run the app with:

```powershell
$env:LLM_PROVIDER="ollama"
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
$env:LLM_MODEL="llama3.2:1b"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

If Ollama is not running, the rule-based planner is used automatically.

## API Usage

### Generate Plan

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

The older field name `goal` is also supported:

```json
{
  "goal": "Complete the assignment report and demo",
  "deadline": "2026-05-21",
  "available_hours": 8,
  "priority": "high"
}
```

### Feedback Update

```bash
curl -X POST http://127.0.0.1:8000/api/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "SESSION_ID_HERE",
    "feedback": "I only have 2 hours today",
    "available_hours": 2
  }'
```

`/api/feedback` updates the existing session in place. It is useful for simple progress, scope, time-budget, or blocker feedback. To use a different deadline, generate a new plan with `/api/plan`.

### Update Task Status

```bash
curl -X PATCH http://127.0.0.1:8000/api/sessions/SESSION_ID_HERE/tasks/TASK_ID_HERE \
  -H "Content-Type: application/json" \
  -d '{"status": "done"}'
```

Valid statuses are `todo`, `doing`, `done`, and `blocked`.

When a task is set to `doing`, the web UI enters Focus Timer mode.

### Pause / Rest

```bash
curl -X POST http://127.0.0.1:8000/api/sessions/SESSION_ID_HERE/pause
```

This saves the active task, pause state, and elapsed focus time. The web app does not forcibly shut down the local server; after pausing, you can stop the service manually and restart later.

### Resume Latest Saved Plan

```bash
curl http://127.0.0.1:8000/api/resume
```

This restores the latest stored session, recalculates time until the deadline, refreshes safety warnings, and reports the last active task if one was paused.

### Recent Plans

```bash
curl http://127.0.0.1:8000/api/plans
```

The existing `/api/memory` endpoint is also kept.

## Example Input

```text
Build an intelligent software agent prototype.
Report: 2 pages.
Page 1 should include GitHub repo link, system design diagram and explanation.
Page 2 should include screenshots and explanations of how the system works.
GitHub repo should include README.md with reproduction instructions, a 2-minute demo video link, and commit checkpoints.
```

## Example Output Shape

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


## Commit Checkpoint Suggestions

- `checkpoint: implement core agent planning loop`
- `checkpoint: add API and web UI workflow`
- `checkpoint: add feedback updates and safety checks`
- `checkpoint: update memory, progress, and trace panels`
- `checkpoint: prepare README, report outline, and demo evidence`

## Known Limitations

- Rule-based natural language parsing is intentionally simple and may miss unusual wording.
- Optional Ollama analysis improves parsing but depends on local model availability.
- Memory is stored in a local JSON file rather than a database.
- There is no authentication because this is a local assignment prototype.
- Deadline changes are handled by generating a new plan through `/api/plan`; `/api/feedback` only updates the active session in place.
