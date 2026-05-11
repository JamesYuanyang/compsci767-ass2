# COMPSCI 767 Assignment 2 Report Draft

Student: Nanyuanyang Zhang  
Student ID: 961188227

## Page 1

### GitHub Repository

https://github.com/JamesYuanyang/compsci767-ass2

### System Design Diagram

```text
User Goal / Feedback
        |
        v
Web Dashboard
        |
        v
FastAPI Agent API
        |
        v
TaskPlanningAgent
  |-- Perception: parses goal, deadline, hours, priority, keywords, constraints
  |-- Decision: selects planning template, estimates effort, ranks tasks
  |-- Action: creates plan, updates status, replans from feedback
  |-- Safety: checks missing deadline, unrealistic time budget, excessive tasks
        |
        v
JSON Memory Store
  |-- sessions
  |-- tasks
  |-- feedback history
  |-- agent reasoning log
```

### Design Explanation

The prototype is a personal task planning agent for student work. The user enters a goal, deadline, available hours, and priority. The perception module extracts structured information from this input, including keywords, domain type, time budget, and constraints. The decision module selects a planning template, estimates the effort per task, and assigns priorities. The action module generates ordered tasks and later updates the plan when the user changes task status or gives feedback. The memory module stores each session in a local JSON file so previous plans can be revisited. The safety module warns when the plan has missing deadlines, too much estimated work, or excessive task count.

The system uses APIs through FastAPI, code execution through the Python planning engine, tool-style internal modules for perception/decision/action, persistent memory through `data/memory.json`, and safety checks. It does not require an LLM, which makes the prototype reproducible without external API keys. An LLM could be added later to improve natural language parsing and richer task decomposition.

## Page 2

### Screenshots

Screenshots to add:

1. Initial dashboard with the goal input panel.
2. Generated plan showing ordered tasks, effort estimates, priorities, and schedule labels.
3. Feedback-based replanning after entering a message such as "I only have 2 hours today".
4. Memory panel showing previous sessions.

### System Workflow Explanation

The agent workflow starts when the user submits a goal. The backend receives the request through `POST /api/plan`, then the agent perceives the goal and creates a structured internal representation. It decides which planning template fits the goal, calculates priorities and estimated effort, and acts by returning a task plan to the dashboard. The user can then mark tasks as todo, doing, done, or blocked. These actions are sent to the backend through `PATCH /api/sessions/{session_id}/tasks/{task_id}` and saved in memory.

The system also supports feedback-driven replanning. For example, if the user writes "I only have 2 hours today", the agent detects a reduced time constraint, lowers remaining effort estimates, keeps essential tasks first, and logs the reasoning. This demonstrates an agent loop: perceive new input, decide how the plan should change, act by updating the task list, and remember the result for future inspection.
