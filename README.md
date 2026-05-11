# COMPSCI 767 Assignment 2: Personal Task Planning Agent

Student: Nanyuanyang Zhang  
Student ID: 961188227

GitHub repository: https://github.com/JamesYuanyang/compsci767-ass2

This repository contains a prototype intelligent software agent that helps a student turn a goal into an actionable task plan. The agent perceives the user's goal, deadline, time budget, and feedback; decides how to decompose and prioritize the work; acts by creating or updating a plan; stores sessions in memory; and applies safety checks to warn about missing deadlines or unrealistic time budgets.

## Project Status

Working prototype.

## Agent Capabilities

- Perception: parses the user's goal, deadline, available hours, urgency, keywords, and constraints.
- English interface: keeps the main workflow readable and consistent.
- Assignment brief input: users can paste teacher-provided requirements or type their own goal description.
- Date deadline picker: accepts a calendar date and uses it to estimate deadline pressure.
- Optional local LLM analysis: can use Ollama with `llama3.2:1b` to extract tasks, key requirements, sections, and risks from pasted briefs without relying on subject-specific templates.
- Rule-based fallback: if Ollama is unavailable, the app still runs and uses deterministic planning rules.
- Decision-making: selects a planning template and assigns task order, priority, effort estimates, and schedule labels.
- Actions: creates a plan, updates task status, and replans from user feedback.
- Memory: stores previous planning sessions and feedback in `data/memory.json`.
- Safety mechanisms: warns when deadlines are missing, the recommended workload exceeds available hours, or today's deadline leaves too little calendar time.
- APIs: exposes the agent through FastAPI endpoints.
- Code execution: runs the agent logic locally as Python code.
- LLM support: optional. The submitted prototype is rule-based so it can be reproduced without paid API keys.

## Reproduction Instructions

### 1. Clone the repository

```bash
git clone https://github.com/JamesYuanyang/compsci767-ass2.git
cd compsci767-ass2
```

### 2. Create and activate a Python virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the application

```bash
uvicorn app.main:app --reload
```

Open the app in a browser:

```text
http://127.0.0.1:8000
```

### Optional: enable local Ollama analysis

The repository does not include model files. To reproduce the local LLM setup:

```powershell
# Example Windows layout used during development
$env:OLLAMA_MODELS="D:\Ollama\Models"
D:\Ollama\App\ollama.exe serve
D:\Ollama\App\ollama.exe pull llama3.2:1b
```

Then run the app with:

```text
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
LLM_MODEL=llama3.2:1b
```

If Ollama is not running, the application automatically falls back to its rule-based planner.

### 5. Try the agent

1. Paste assignment requirements or enter a personal/study goal.
2. Choose a deadline date, available hours, and priority.
3. Click `Generate Plan`.
4. Change task statuses using `Todo`, `Doing`, `Done`, or `Blocked`.
5. Add feedback such as `I only have 2 hours today` and click `Re-plan`.
6. Check the `Memory` panel to reload previous sessions.

## API Endpoints

- `POST /api/plan`: creates a new plan.
- `POST /api/feedback`: updates a plan from user feedback.
- `PATCH /api/sessions/{session_id}/tasks/{task_id}`: updates a task status.
- `GET /api/memory`: returns stored planning sessions.

## System Design

```text
User Interface
   |
   v
FastAPI Routes
   |
   v
TaskPlanningAgent
   |-- Perception Module
   |-- Decision Module
   |-- Action Module
   |-- Safety Check Module
   |
   v
JSON Memory Store
```

## Demo Video

The 2-minute demo video will be uploaded to this GitHub repository before submission.
