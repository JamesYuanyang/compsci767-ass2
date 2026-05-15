# 2-Page Report Outline

## Page 1

### GitHub Repository

GitHub repo link: [add repository link here]

### System Design Diagram

```text
User Input
  -> Perception Module
  -> Decision / Planning Module
  -> Safety Checker
  -> Action Module
  -> Focus Timer / Pause State
  -> Memory Store
  -> Web UI + API
```

### System Design Explanation

The user enters an assignment brief or goal, deadline, available working hours, priority, and optional feedback. The Perception Module detects whether the input is an assignment brief or normal goal, then extracts deliverables, constraints, deadline pressure, and available working time.

The Decision / Planning Module chooses a strategy. For assignment briefs it prioritizes report requirements, GitHub repository evidence, README, screenshots, demo video, API work, web interface work, memory, safety checks, and commit checkpoints. It separates recommended effort from the compressed planned time.

The Safety Checker compares recommended effort, available hours, planned hours, and time until the deadline. It warns when the recommended workload is larger than the user's available working time and avoids contradictory messages.

The Action Module creates tasks, updates task status, and applies in-place feedback updates through `/api/feedback`. When a task is set to Doing, the Focus Timer view starts and shows the exact current task plus its support hint and planned time. Pause / Rest saves the active task and elapsed focus time instead of forcibly shutting down the server. The Memory Store saves recent sessions in `data/memory.json`. The Web UI and API expose the workflow through a browser interface and FastAPI endpoints.

## Page 2

### Screenshot 1: Initial Plan Generation

Add a screenshot showing the assignment brief in the input area and the generated assignment-specific task list.

### Screenshot 2: Feedback Update

Add a screenshot showing feedback such as "I only have 2 hours today" and the resulting compressed plan with updated safety messages.

### Screenshot 3: Agent Trace / Memory / Safety

Add a screenshot showing:

- Agent Trace sections: Perception, Decision, Action, Memory, Safety Check.
- Recent Plans panel with short titles and planned hours.
- Safety messages showing recommended effort, available time, and planned time.
- Progress indicator showing completed tasks and remaining planned time.

### Screenshot 4: Focus Timer / Pause-Resume

Add a screenshot showing a task set to Doing, the Focus Timer view, and the current task instructions. Add another screenshot after Pause / Rest or after restarting the app showing that the latest plan and last active task were restored.

### How The System Works

1. The user submits a goal or assignment brief through the web UI.
2. `POST /api/plan` sends the input to the FastAPI backend.
3. The agent perceives deliverables, constraints, deadline, and available working hours.
4. The decision logic selects a planning strategy and ranks required tasks.
5. The action logic generates a task list with statuses, priorities, effort estimates, and support hints.
6. The safety checker compares recommended effort with available and planned time.
7. The session is stored in memory and appears in Recent Plans.
8. When the user submits `POST /api/feedback`, the agent updates the active session from the feedback, refreshes trace, safety, memory, and progress.
9. When a task is changed to Doing, the UI enters Focus Timer mode and records elapsed focus time.
10. When the user clicks Pause / Rest, `POST /api/sessions/{session_id}/pause` saves the active task and pause state.
11. On restart, `GET /api/resume` restores the latest saved plan, recalculates deadline pressure, and recommends a feedback update or new plan if the remaining time is risky.
