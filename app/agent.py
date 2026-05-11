from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.models import FeedbackRequest, PlanRequest


class TaskPlanningAgent:
    """Rule-based agent with explicit perception, decision, action, memory outputs."""

    def create_plan(self, request: PlanRequest) -> dict[str, Any]:
        perception = self._perceive(request)
        decisions = self._decide(perception)
        actions = self._act(perception, decisions)
        safety = self._safety_check(perception, actions)

        return {
            "session_id": str(uuid.uuid4()),
            "created_at": self._now(),
            "goal": request.goal,
            "deadline": request.deadline or "Not specified",
            "available_hours": request.available_hours,
            "priority": request.priority,
            "perception": perception,
            "decisions": decisions,
            "tasks": actions["tasks"],
            "agent_log": actions["agent_log"] + safety["messages"],
            "safety": safety,
            "feedback_history": [],
        }

    def apply_feedback(self, session: dict[str, Any], request: FeedbackRequest) -> dict[str, Any]:
        feedback = request.feedback.strip()
        tasks = session["tasks"]
        lower = feedback.lower()
        agent_log = [
            f'Perceived feedback: "{feedback}"',
            "Decision: re-evaluate task order, effort, and risk based on the feedback.",
        ]

        if any(term in lower for term in ["less time", "busy", "only", "reduce", "shorter", "too much"]):
            for task in tasks:
                if task["status"] == "todo" and task["effort_hours"] > 0.75:
                    task["effort_hours"] = max(0.5, round(task["effort_hours"] * 0.7, 1))
            agent_log.append("Action: reduced remaining task effort estimates and kept essential tasks first.")

        if any(term in lower for term in ["hard", "confusing", "stuck", "blocked"]):
            for task in tasks:
                if task["status"] == "todo":
                    task["priority_score"] += 1
                    task["support_hint"] = "Break this into a 25-minute focus block and write one question if blocked."
            agent_log.append("Action: added support hints and raised priority for unresolved tasks.")

        if any(term in lower for term in ["tomorrow", "later", "delay", "extend"]):
            for task in tasks:
                if task["status"] == "todo":
                    task["schedule"] = "Later slot"
            agent_log.append("Action: moved remaining todo items into a later planning slot.")

        tasks.sort(key=lambda item: (item["status"] == "done", -item["priority_score"], item["order"]))
        for index, task in enumerate(tasks, start=1):
            task["order"] = index

        session["tasks"] = tasks
        session["feedback_history"].append(
            {"at": self._now(), "feedback": feedback, "agent_response": agent_log}
        )
        session["agent_log"] = agent_log + self._safety_check(session["perception"], {"tasks": tasks})["messages"]
        session["updated_at"] = self._now()
        return session

    def update_status(self, session: dict[str, Any], task_id: str, status: str) -> dict[str, Any]:
        for task in session["tasks"]:
            if task["id"] == task_id:
                task["status"] = status
                session["agent_log"] = [
                    f"Action: updated task '{task['title']}' to {status}.",
                    "Decision: keep the current plan but move completed work lower in the active queue.",
                ]
                session["tasks"].sort(key=lambda item: (item["status"] == "done", item["order"]))
                session["updated_at"] = self._now()
                return session
        raise KeyError(f"Unknown task_id: {task_id}")

    def _perceive(self, request: PlanRequest) -> dict[str, Any]:
        goal = request.goal.strip()
        keywords = [
            word.lower()
            for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", goal)
            if word.lower() not in {"the", "and", "for", "with", "this", "that"}
        ][:8]
        domain = self._classify_domain(goal)
        return {
            "raw_goal": goal,
            "keywords": keywords,
            "domain": domain,
            "deadline_detected": bool(request.deadline),
            "time_budget": request.available_hours,
            "urgency": request.priority,
            "constraints": self._detect_constraints(goal, request),
        }

    def _decide(self, perception: dict[str, Any]) -> dict[str, Any]:
        base_steps = self._steps_for_domain(perception["domain"])
        urgency_weight = {"low": 1, "medium": 2, "high": 3}[perception["urgency"]]
        time_budget = perception["time_budget"]
        effort = max(0.5, round(time_budget / len(base_steps), 1))
        return {
            "strategy": "decompose_goal_prioritize_schedule",
            "selected_template": perception["domain"],
            "urgency_weight": urgency_weight,
            "estimated_hours_per_task": effort,
            "task_count": len(base_steps),
            "reason": "The agent decomposes the goal, prioritizes high-risk work, then schedules review and delivery actions.",
        }

    def _act(self, perception: dict[str, Any], decisions: dict[str, Any]) -> dict[str, Any]:
        tasks = []
        steps = self._steps_for_domain(perception["domain"])
        for index, step in enumerate(steps, start=1):
            risk_boost = 2 if index in {1, len(steps)} else 1
            tasks.append(
                {
                    "id": str(uuid.uuid4()),
                    "order": index,
                    "title": step,
                    "status": "todo",
                    "priority_score": decisions["urgency_weight"] + risk_boost,
                    "effort_hours": decisions["estimated_hours_per_task"],
                    "schedule": self._schedule_label(index, len(steps)),
                    "support_hint": "Complete the smallest useful version first, then improve it if time remains.",
                }
            )

        return {
            "tasks": tasks,
            "agent_log": [
                "Perception: parsed the user goal, time budget, deadline, urgency, and constraints.",
                f"Decision: selected the {decisions['selected_template']} planning template.",
                "Action: generated ordered tasks with priorities, effort estimates, and schedule labels.",
            ],
        }

    def _safety_check(self, perception: dict[str, Any], actions: dict[str, Any]) -> dict[str, Any]:
        total_hours = round(sum(task["effort_hours"] for task in actions["tasks"]), 1)
        messages = []
        warnings = []

        if not perception.get("deadline_detected"):
            warnings.append("No explicit deadline was provided.")
            messages.append("Safety: no deadline detected, so the plan includes review and buffer tasks.")

        if total_hours > perception["time_budget"]:
            warnings.append("Estimated work exceeds available time.")
            messages.append("Safety: estimated effort is above the time budget; reduce scope or increase available hours.")
        else:
            messages.append("Safety: estimated effort fits within the available time budget.")

        if len(actions["tasks"]) > 8:
            warnings.append("Plan has too many tasks for a short prototype workflow.")

        return {"total_estimated_hours": total_hours, "warnings": warnings, "messages": messages}

    def _classify_domain(self, goal: str) -> str:
        lower = goal.lower()
        if any(term in lower for term in ["assignment", "report", "github", "submit", "course"]):
            return "student_assignment"
        if any(term in lower for term in ["exam", "study", "quiz", "test"]):
            return "study_plan"
        if any(term in lower for term in ["project", "build", "prototype", "app"]):
            return "software_project"
        return "general_goal"

    def _steps_for_domain(self, domain: str) -> list[str]:
        templates = {
            "student_assignment": [
                "Clarify marking requirements and deliverables",
                "Break the assignment into implementation, report, and demo tasks",
                "Build the minimum working prototype",
                "Write reproduction instructions and prepare evidence",
                "Review against the rubric and submit final materials",
            ],
            "study_plan": [
                "List topics and rank weak areas",
                "Create focused study blocks",
                "Practice representative questions",
                "Review mistakes and update notes",
                "Run a final timed check",
            ],
            "software_project": [
                "Define the smallest working feature set",
                "Set up the project structure",
                "Implement the core workflow",
                "Test the user path and fix issues",
                "Prepare documentation and demo",
            ],
            "general_goal": [
                "Define the concrete outcome",
                "Identify required resources and blockers",
                "Create the first actionable milestone",
                "Complete and review the core work",
                "Prepare final delivery and next steps",
            ],
        }
        return templates[domain]

    def _detect_constraints(self, goal: str, request: PlanRequest) -> list[str]:
        constraints = []
        if request.available_hours < 3:
            constraints.append("Very limited time budget")
        if not request.deadline:
            constraints.append("Missing explicit deadline")
        if "github" in goal.lower():
            constraints.append("Repository evidence required")
        if "report" in goal.lower():
            constraints.append("Written explanation required")
        return constraints

    def _schedule_label(self, index: int, total: int) -> str:
        if index == 1:
            return "Start now"
        if index == total:
            return "Final review"
        return f"Work block {index}"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
