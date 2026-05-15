from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timezone
from typing import Any

from app.llm import OllamaBriefAnalyzer
from app.models import FeedbackRequest, PlanRequest


class TaskPlanningAgent:
    """Rule-based planning agent with perception, decision, action, memory, safety, and feedback outputs."""

    def __init__(self, analyzer: OllamaBriefAnalyzer | None = None) -> None:
        self.analyzer = analyzer or OllamaBriefAnalyzer()

    def create_plan(self, request: PlanRequest) -> dict[str, Any]:
        llm_analysis = self.analyzer.analyze(request.goal)
        perception = self._perceive(request, llm_analysis)
        decisions = self._decide(perception, llm_analysis)
        actions = self._act(perception, decisions)
        safety = self._safety_check(perception, actions["tasks"])
        session_id = str(uuid.uuid4())

        session = {
            "session_id": session_id,
            "created_at": self._now(),
            "updated_at": self._now(),
            "goal": request.goal,
            "deadline": request.deadline or "Not specified",
            "available_hours": request.available_hours,
            "priority": request.priority,
            "perception": perception,
            "decisions": decisions,
            "tasks": actions["tasks"],
            "safety": safety,
            "llm_analysis": llm_analysis,
            "feedback_history": [],
            "event_type": "generated",
            "focus_state": self._empty_focus_state(),
        }
        self._refresh_session_outputs(
            session,
            action_lines=[
                f"Generated plan with {len(actions['tasks'])} tasks.",
                "Stored plan in memory after API response.",
            ],
        )
        return session

    def apply_feedback(self, session: dict[str, Any], request: FeedbackRequest) -> dict[str, Any]:
        feedback = request.feedback.strip()
        lower = feedback.lower()
        perception = session["perception"]
        tasks = session["tasks"]

        trace_notes = [f'Feedback received: "{feedback}"']
        decision_notes = ["Re-evaluate task order, effort, status, and scope from feedback."]
        action_notes: list[str] = []

        revised_budget = self._extract_time_budget(lower)
        if revised_budget is None and request.available_hours is not None:
            current_budget = float(perception.get("time_budget", session.get("available_hours", 0)))
            if abs(request.available_hours - current_budget) > 0.05:
                revised_budget = request.available_hours

        completed_tags = self._feedback_completion_tags(lower)
        not_done_tags = self._feedback_not_done_tags(lower)
        addition = self._extract_requested_addition(feedback)

        if revised_budget is not None:
            session["available_hours"] = revised_budget
            perception["time_budget"] = revised_budget
            perception["available_working_hours"] = revised_budget
            constraints = perception.setdefault("constraints", [])
            if revised_budget < 3 and "Very limited time budget" not in constraints:
                constraints.append("Very limited time budget")
            trace_notes.append("Feedback detected: reduced available time.")
            decision_notes.append("Compress plan and defer lower-priority tasks.")

        if completed_tags:
            changed = self._mark_tasks_done(tasks, completed_tags)
            if changed:
                trace_notes.append(f"Feedback detected: completed work for {', '.join(completed_tags)}.")
                action_notes.append(f"Marked {changed} matching task(s) as done.")
                decision_notes.append("Re-prioritize remaining unfinished work.")

        if not_done_tags:
            changed = self._prioritize_tasks(tasks, not_done_tags)
            if changed:
                trace_notes.append(f"Feedback detected: unfinished work for {', '.join(not_done_tags)}.")
                action_notes.append(f"Moved {changed} matching task(s) earlier in the plan.")
                decision_notes.append("Raise priority of unfinished explicit deliverables.")

        if addition:
            tasks.append(self._make_feedback_task(addition, perception, len(tasks) + 1))
            trace_notes.append(f'Feedback detected: added requested scope "{addition}".')
            action_notes.append("Added a new task from feedback.")

        if any(term in lower for term in ["hard", "confusing", "stuck", "blocked", "unclear"]):
            for task in tasks:
                if task["status"] != "done" and not task.get("deferred"):
                    task["priority_score"] = min(10, task["priority_score"] + 1)
                    task["support_hint"] = "Make one short attempt, then write the exact blocker or question."
            trace_notes.append("Feedback detected: blocker or uncertainty.")
            action_notes.append("Raised unresolved task priority and added blocker-focused hints.")

        if revised_budget is not None:
            self._compress_and_defer(tasks, revised_budget)
            action_notes.append(f"Action: generated a {self._format_hours(revised_budget).replace('h', '-hour')} plan.")
        elif completed_tags or not_done_tags or addition:
            self._fit_remaining_effort(tasks, float(perception["time_budget"]))
            action_notes.append("Updated the task list and remaining time allocation.")

        self._sort_tasks(tasks)
        session["tasks"] = tasks
        session["event_type"] = "updated"
        session["updated_at"] = self._now()
        session.setdefault("feedback_history", []).append(
            {
                "at": session["updated_at"],
                "feedback": feedback,
                "detected": trace_notes,
                "actions": action_notes,
            }
        )
        self._refresh_session_outputs(
            session,
            input_type="feedback",
            perception_lines=trace_notes,
            decision_lines=[*decision_notes, "Feedback update rules were applied."],
            action_lines=action_notes or ["Updated plan from feedback."],
        )
        return session

    def update_status(self, session: dict[str, Any], task_id: str, status: str) -> dict[str, Any]:
        self._accumulate_running_focus(session)
        for task in session["tasks"]:
            if task["id"] == task_id:
                action_lines = [f"Updated task status to {status}."]
                task["status"] = status
                task["deferred"] = False if status in {"todo", "doing", "done", "blocked"} else task.get("deferred", False)
                if status == "doing":
                    self._start_focus(session, task)
                    action_lines.append("Entered focus timer view for the selected task.")
                elif status == "done":
                    self._clear_focus_if_active(session, task_id)
                    action_lines.append("Completed the active task and returned to the planning view.")
                elif status in {"todo", "blocked"}:
                    self._clear_focus_if_active(session, task_id)
                session["updated_at"] = self._now()
                self._sort_tasks(session["tasks"])
                self._refresh_session_outputs(
                    session,
                    input_type="status update",
                    perception_lines=[f"Status update received for task: {task['title']}."],
                    decision_lines=["Keep the plan structure and update progress from task statuses."],
                    action_lines=action_lines,
                )
                return session
        raise KeyError(f"Unknown task_id: {task_id}")

    def pause_session(self, session: dict[str, Any]) -> dict[str, Any]:
        self._accumulate_running_focus(session)
        focus = session.setdefault("focus_state", self._empty_focus_state())
        focus["status"] = "paused"
        focus["active_started_at"] = None
        focus["paused_at"] = self._now()
        session["updated_at"] = focus["paused_at"]
        self._refresh_session_outputs(
            session,
            input_type="pause/rest",
            perception_lines=["Pause requested: current progress and focus timer were saved to memory."],
            decision_lines=["Resume later by loading the latest saved session and recalculating deadline pressure."],
            action_lines=["Saved session pause state. The local web service can be stopped manually if needed."],
        )
        return session

    def resume_focus(self, session: dict[str, Any]) -> dict[str, Any]:
        focus = session.setdefault("focus_state", self._empty_focus_state())
        task = self._find_task(session, focus.get("active_task_id"))
        if not task:
            raise KeyError("No paused focus task to resume")
        if task.get("status") == "done":
            raise KeyError("Cannot resume a task that is already done")
        for item in session.get("tasks", []):
            if item["id"] != task["id"] and item.get("status") == "doing":
                item["status"] = "todo"
        task["status"] = "doing"
        focus["status"] = "running"
        focus["active_started_at"] = self._now()
        focus["paused_at"] = None
        session["updated_at"] = focus["active_started_at"]
        self._refresh_session_outputs(
            session,
            input_type="focus resume",
            perception_lines=[f"Resume requested for task: {task['title']}."],
            decision_lines=["Continue the saved active task instead of starting a new planning session."],
            action_lines=["Restarted the focus timer from the saved elapsed time."],
        )
        return session

    def resume_session(self, session: dict[str, Any]) -> dict[str, Any]:
        previous_pressure = session.get("perception", {}).get("deadline_pressure")
        self._reevaluate_deadline(session)
        current_pressure = session.get("perception", {}).get("deadline_pressure")
        progress = self._progress(session.get("tasks", []))
        focus = session.setdefault("focus_state", self._empty_focus_state())
        resume_lines = [
            "Loaded the latest saved plan from memory.",
            f"Unfinished tasks: {progress['total_tasks'] - progress['completed_tasks']}",
            f"Remaining planned time: {self._format_hours(progress['remaining_planned_hours'])}",
        ]
        if focus.get("active_task_id"):
            task = self._find_task(session, focus["active_task_id"])
            if task:
                resume_lines.append(f"Last active task: {task['title']}")
        if focus.get("status") == "running":
            focus["status"] = "paused"
            focus["active_started_at"] = None
            focus["paused_at"] = self._now()
            resume_lines.append("A previously running timer was restored as paused so time away is not counted as work.")
        if previous_pressure != current_pressure:
            resume_lines.append(f"Deadline pressure changed from {previous_pressure or 'unknown'} to {current_pressure or 'unknown'}.")
        if current_pressure in {"urgent", "soon"} and progress["remaining_planned_hours"] > 0:
            resume_lines.append("Recommendation: use feedback or generate a new plan because the deadline is closer than before.")
        session["updated_at"] = self._now()
        self._refresh_session_outputs(
            session,
            input_type="resume",
            perception_lines=resume_lines,
            decision_lines=["Recalculate safety using the current date and the remaining unfinished tasks."],
            action_lines=["Restored previous progress and refreshed safety warnings."],
        )
        return session

    def attach_memory_summary(
        self,
        session: dict[str, Any],
        summary: dict[str, Any],
        previous_loaded: bool = False,
    ) -> dict[str, Any]:
        session["memory_summary"] = summary
        trace = session.setdefault("agent_trace", {})
        trace["memory"] = [
            f"Current session ID: {session['session_id']}",
            f"Number of stored recent plans: {summary.get('stored_plans', 0)}",
            f"Previous plan loaded or reused: {'yes' if previous_loaded else 'no'}",
            f"Last saved: {summary.get('last_saved') or 'not saved yet'}",
        ]
        session["agent_log"] = self._flatten_trace(trace)
        return session

    def _empty_focus_state(self) -> dict[str, Any]:
        return {
            "status": "idle",
            "active_task_id": None,
            "active_started_at": None,
            "elapsed_seconds": 0,
            "paused_at": None,
        }

    def _start_focus(self, session: dict[str, Any], task: dict[str, Any]) -> None:
        for item in session.get("tasks", []):
            if item["id"] != task["id"] and item.get("status") == "doing":
                item["status"] = "todo"
        now = self._now()
        elapsed = int(task.get("elapsed_seconds") or 0)
        session["focus_state"] = {
            "status": "running",
            "active_task_id": task["id"],
            "active_started_at": now,
            "elapsed_seconds": elapsed,
            "paused_at": None,
        }

    def _clear_focus_if_active(self, session: dict[str, Any], task_id: str) -> None:
        focus = session.setdefault("focus_state", self._empty_focus_state())
        if focus.get("active_task_id") == task_id:
            focus["status"] = "idle"
            focus["active_task_id"] = None
            focus["active_started_at"] = None
            focus["paused_at"] = None

    def _accumulate_running_focus(self, session: dict[str, Any]) -> None:
        focus = session.setdefault("focus_state", self._empty_focus_state())
        if focus.get("status") != "running" or not focus.get("active_task_id") or not focus.get("active_started_at"):
            return
        started_at = self._parse_datetime(str(focus["active_started_at"]))
        if not started_at:
            return
        now = datetime.now(timezone.utc)
        elapsed = max(0, int((now - started_at).total_seconds()))
        if elapsed <= 0:
            return
        focus["elapsed_seconds"] = int(focus.get("elapsed_seconds") or 0) + elapsed
        focus["active_started_at"] = self._now()
        task = self._find_task(session, focus["active_task_id"])
        if task:
            task["elapsed_seconds"] = int(task.get("elapsed_seconds") or 0) + elapsed

    def _find_task(self, session: dict[str, Any], task_id: str | None) -> dict[str, Any] | None:
        if not task_id:
            return None
        for task in session.get("tasks", []):
            if task.get("id") == task_id:
                return task
        return None

    def _reevaluate_deadline(self, session: dict[str, Any]) -> None:
        deadline = session.get("deadline")
        if not deadline or deadline == "Not specified":
            return
        details = self._deadline_details(str(deadline), session.get("priority", "medium"))
        perception = session.setdefault("perception", {})
        perception["deadline_pressure"] = details["pressure"]
        perception["deadline_date"] = details["date"]
        perception["deadline_days_left"] = details["days_left"]
        perception["deadline_hours_remaining"] = details["hours_remaining"]
        perception["time_until_deadline_hours"] = details["hours_remaining"]

    def _parse_datetime(self, value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _perceive(self, request: PlanRequest, llm_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
        goal = request.goal.strip()
        rule_domain = self._classify_domain(goal)
        llm_domain = llm_analysis.get("domain") if llm_analysis else None
        domain = llm_domain or rule_domain
        if rule_domain == "student_assignment" and domain == "general_goal":
            domain = rule_domain

        deliverables = self._merge_lists(
            self._extract_deliverables(goal, domain),
            llm_analysis.get("deliverables", []) if llm_analysis else [],
        )
        methods = self._merge_lists(
            self._extract_methods(goal),
            llm_analysis.get("methods", []) if llm_analysis else [],
        )
        sections = self._merge_lists(
            self._extract_sections(goal),
            llm_analysis.get("sections", []) if llm_analysis else [],
        )
        input_type = self._detect_input_type(goal)
        if llm_analysis and llm_analysis.get("input_type") == "assignment_brief":
            input_type = "assignment_brief"

        deadline = self._deadline_details(request.deadline, request.priority)
        rule_recommended_hours = self._estimate_recommended_hours(
            goal=goal,
            domain=domain,
            deliverables=deliverables,
            methods=methods,
            input_type=input_type,
            priority=request.priority,
            available_hours=request.available_hours,
        )
        llm_recommended_hours = float((llm_analysis or {}).get("recommended_hours") or 0)
        recommended_hours = max(llm_recommended_hours, rule_recommended_hours)

        return {
            "raw_goal": goal,
            "keywords": self._extract_keywords(goal),
            "domain": domain,
            "input_type": input_type,
            "analysis_source": (llm_analysis or {}).get("source", "rules"),
            "deliverables": deliverables,
            "methods": methods,
            "sections": sections,
            "deadline_detected": bool(request.deadline),
            "deadline_pressure": deadline["pressure"],
            "deadline_date": deadline["date"],
            "deadline_days_left": deadline["days_left"],
            "deadline_hours_remaining": deadline["hours_remaining"],
            "time_until_deadline_hours": deadline["hours_remaining"],
            "time_budget": request.available_hours,
            "available_working_hours": request.available_hours,
            "recommended_hours": recommended_hours,
            "recommended_effort_hours": recommended_hours,
            "urgency": request.priority,
            "complexity": self._estimate_complexity(goal, request.available_hours, deliverables),
            "constraints": self._detect_constraints(goal, request, deliverables),
        }

    def _decide(self, perception: dict[str, Any], llm_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
        steps = self._build_steps(perception, llm_analysis)
        efforts = self._allocate_effort(float(perception["time_budget"]), [step["weight"] for step in steps])
        urgency_weight = {"low": 1, "medium": 2, "high": 3}[perception["urgency"]]
        strategy = "assignment_deliverable_extraction" if perception["input_type"] == "assignment_brief" else "goal_aware_decomposition"
        return {
            "strategy": strategy,
            "selected_template": perception["domain"],
            "urgency_weight": urgency_weight,
            "task_count": len(steps),
            "steps": steps,
            "effort_plan": efforts,
            "prioritisation_rule": "Required deliverables and explicit unfinished feedback come before polish.",
            "time_allocation_rule": "Allocate available hours across required tasks; defer lower-priority polish when compressed.",
            "reason": "The agent extracts deliverables, constraints, and time pressure before ranking tasks.",
        }

    def _act(self, perception: dict[str, Any], decisions: dict[str, Any]) -> dict[str, Any]:
        tasks = []
        pressure_boost = 1 if perception["deadline_pressure"] in {"urgent", "soon"} else 0
        for index, step in enumerate(decisions["steps"], start=1):
            priority_score = min(10, decisions["urgency_weight"] + step["risk"] + pressure_boost)
            tasks.append(
                {
                    "id": str(uuid.uuid4()),
                    "order": index,
                    "title": step["title"],
                    "status": "todo",
                    "priority_score": priority_score,
                    "effort_hours": decisions["effort_plan"][index - 1],
                    "schedule": self._schedule_label(index, len(decisions["steps"])),
                    "support_hint": step["hint"],
                    "tags": step.get("tags") or self._tags_for_text(step["title"]),
                    "deferred": False,
                    "elapsed_seconds": 0,
                }
            )
        return {"tasks": tasks}

    def _safety_check(self, perception: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any]:
        planned_hours = round(sum(float(task.get("effort_hours", 0)) for task in tasks), 1)
        remaining_planned_hours = round(sum(float(task.get("effort_hours", 0)) for task in tasks if task.get("status") != "done"), 1)
        recommended_hours = round(float(perception.get("recommended_effort_hours") or perception.get("recommended_hours") or planned_hours), 1)
        available_hours = round(float(perception.get("time_budget", planned_hours)), 1)
        hours_remaining = perception.get("time_until_deadline_hours", perception.get("deadline_hours_remaining"))
        messages: list[str] = []
        warnings: list[str] = []

        if not perception.get("deadline_detected"):
            warnings.append("No explicit deadline was provided.")
            messages.append("No deadline detected; keep a final review task in the plan.")

        if hours_remaining is not None:
            if hours_remaining <= 0:
                warnings.append("The selected deadline has already passed or has no remaining time today.")
                messages.append("Choose a later deadline or switch to an emergency minimum-scope submission.")
            elif available_hours > hours_remaining + 0.25:
                warnings.append("Available working hours exceed calendar time until the deadline.")
                messages.append(
                    f"Only about {self._format_hours(hours_remaining)} remain until the deadline, less than the available working time entered."
                )
            if recommended_hours > hours_remaining + 0.25:
                warnings.append("Recommended effort does not fit before the selected deadline.")
                messages.append(
                    f"Recommended effort is around {self._format_hours(recommended_hours)}, but only {self._format_hours(hours_remaining)} remain until the deadline."
                )
            if remaining_planned_hours > hours_remaining + 0.25:
                warnings.append("Remaining planned work does not fit before the selected deadline.")
                messages.append(
                    f"Remaining planned work is {self._format_hours(remaining_planned_hours)}, but only {self._format_hours(hours_remaining)} remain until the deadline."
                )

        if perception.get("deadline_pressure") == "urgent" and recommended_hours > 4:
            warnings.append("Urgent deadline with a large recommended workload.")
            messages.append("Urgent deadline detected; keep only the highest-value deliverables if time slips.")

        if recommended_hours > available_hours + 0.25:
            warnings.append("Recommended effort exceeds available working hours.")
            messages.append(
                f"Recommended effort is around {self._format_hours(recommended_hours)}, which exceeds the available {self._format_hours(available_hours)}."
            )
            if planned_hours <= available_hours + 0.25:
                messages.append(
                    f"A compressed {self._format_hours(planned_hours)} plan was generated by reducing optional polishing time."
                )
            messages.append("Consider increasing available hours, extending the deadline, or reducing scope.")
        elif planned_hours <= available_hours + 0.25:
            messages.append("Estimated effort fits within the available time budget.")

        if planned_hours > available_hours + 0.25:
            warnings.append("Planned hours exceed available working hours.")
            messages.append("Planned work exceeds the time budget; reduce scope or increase available hours.")

        risk_level = self._risk_level(warnings, perception, recommended_hours, available_hours)
        return {
            "planned_hours": planned_hours,
            "total_estimated_hours": planned_hours,
            "remaining_planned_hours": remaining_planned_hours,
            "recommended_effort_hours": recommended_hours,
            "recommended_hours": recommended_hours,
            "available_hours": available_hours,
            "hours_remaining_before_deadline": hours_remaining,
            "time_until_deadline_hours": hours_remaining,
            "risk_level": risk_level,
            "warnings": warnings,
            "messages": messages,
        }

    def _refresh_session_outputs(
        self,
        session: dict[str, Any],
        input_type: str | None = None,
        perception_lines: list[str] | None = None,
        decision_lines: list[str] | None = None,
        action_lines: list[str] | None = None,
    ) -> None:
        session.setdefault("focus_state", self._empty_focus_state())
        safety = self._safety_check(session["perception"], session["tasks"])
        progress = self._progress(session["tasks"])
        session["safety"] = safety
        session["progress"] = progress
        session["planned_hours"] = safety["planned_hours"]
        session["recommended_effort_hours"] = safety["recommended_effort_hours"]
        session["safety_warnings"] = safety["warnings"]
        session["short_title"] = self._short_title(session)
        session["plan_title"] = session["short_title"]
        trace = self._agent_trace(
            session=session,
            safety=safety,
            input_type=input_type,
            perception_lines=perception_lines or [],
            decision_lines=decision_lines or [],
            action_lines=action_lines or [],
        )
        session["agent_trace"] = trace
        session["agent_log"] = self._flatten_trace(trace)

    def _agent_trace(
        self,
        session: dict[str, Any],
        safety: dict[str, Any],
        input_type: str | None,
        perception_lines: list[str],
        decision_lines: list[str],
        action_lines: list[str],
    ) -> dict[str, list[str]]:
        perception = session["perception"]
        decisions = session["decisions"]
        progress = session.get("progress", {})
        detected_input_type = input_type or perception.get("input_type", "goal_description")
        perception_items = [
            f"Input type: {detected_input_type}",
            f"Goal detected: {self._goal_focus(session['goal'])}",
            f"Deadline detected: {'yes' if perception.get('deadline_detected') else 'no'}",
            f"Time until deadline: {self._format_optional_hours(perception.get('time_until_deadline_hours'))}",
            f"Available hours: {self._format_hours(perception.get('time_budget', 0))}",
            f"Priority: {session.get('priority', perception.get('urgency', 'medium'))}",
            f"Deliverables detected: {', '.join(perception.get('deliverables', [])) or 'none'}",
            f"Constraints detected: {', '.join(perception.get('constraints', [])) or 'none'}",
            *perception_lines,
        ]
        decision_items = [
            f"Selected planning strategy: {decisions.get('strategy')}",
            f"Prioritisation rule: {decisions.get('prioritisation_rule')}",
            f"Time allocation rule: {decisions.get('time_allocation_rule')}",
        ]
        decision_items.extend(decision_lines)

        action_items = [
            f"Generated plan: {len(session['tasks'])} tasks, {self._format_hours(safety['planned_hours'])} planned.",
            f"Updated task list: {progress.get('completed_tasks', 0)} of {progress.get('total_tasks', len(session['tasks']))} complete.",
            "Stored plan in memory.",
        ]
        focus = session.get("focus_state") or {}
        if focus.get("active_task_id"):
            active_task = self._find_task(session, focus.get("active_task_id"))
            active_title = active_task["title"] if active_task else "unknown task"
            action_items.append(
                f"Focus timer: {focus.get('status', 'idle')} on {active_title}, tracked {self._format_duration(focus.get('elapsed_seconds', 0))}."
            )
        elif focus.get("status") == "paused":
            action_items.append("Focus timer: paused with no active task.")
        action_items.extend(action_lines)

        memory_items = [
            f"Current session ID: {session['session_id']}",
            "Number of stored recent plans: pending memory save",
            "Previous plan loaded or reused: no",
        ]
        safety_items = [
            f"Recommended effort: {self._format_hours(safety['recommended_effort_hours'])}",
            f"Available time: {self._format_hours(safety['available_hours'])}",
            f"Planned time: {self._format_hours(safety['planned_hours'])}",
            f"Risk level: {safety['risk_level']}",
            f"Warning or recommendation: {'; '.join(safety['messages']) or 'No safety notes.'}",
        ]
        return {
            "perception": perception_items,
            "decision": decision_items,
            "action": action_items,
            "memory": memory_items,
            "safety_check": safety_items,
        }

    def _flatten_trace(self, trace: dict[str, list[str]]) -> list[str]:
        labels = {
            "perception": "Perception",
            "decision": "Decision",
            "action": "Action",
            "memory": "Memory",
            "safety_check": "Safety Check",
        }
        flattened: list[str] = []
        for key in ["perception", "decision", "action", "memory", "safety_check"]:
            for item in trace.get(key, []):
                flattened.append(f"{labels[key]}: {item}")
        return flattened

    def _classify_domain(self, goal: str) -> str:
        lower = goal.lower()
        if self._looks_like_assignment_brief(lower) or self._has_any(
            lower,
            ["assignment", "coursework", "course", "homework", "rubric", "submit", "submission", "criteria", "marks", "compsci", "ass2"],
        ):
            return "student_assignment"
        if self._has_any(lower, ["app", "website", "api", "code", "debug", "prototype", "software"]):
            return "software_project"
        if self._has_any(lower, ["research", "literature", "dataset", "experiment", "survey", "reading report"]):
            return "research_project"
        if self._has_any(lower, ["essay", "paper", "article", "proposal", "write", "report"]):
            return "writing_project"
        if self._has_any(lower, ["exam", "quiz", "study", "revise", "revision", "test"]):
            return "study_plan"
        if self._has_any(lower, ["resume", "cv", "interview", "job", "internship", "portfolio"]):
            return "career_goal"
        if self._has_any(lower, ["workout", "fitness", "diet", "habit", "sleep"]):
            return "habit_goal"
        if self._has_any(lower, ["event", "trip", "travel", "meeting", "presentation"]):
            return "event_plan"
        if self._has_any(lower, ["video", "design", "podcast", "art", "demo"]):
            return "creative_project"
        return "general_goal"

    def _build_steps(self, perception: dict[str, Any], llm_analysis: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if perception.get("input_type") == "assignment_brief":
            return self._assignment_brief_steps(perception, llm_analysis)

        llm_steps = self._llm_steps(llm_analysis, perception["raw_goal"])
        if llm_steps:
            return llm_steps

        focus = self._goal_focus(perception["raw_goal"])
        deliverables = perception["deliverables"]
        final_output = ", ".join(deliverables) if deliverables else "the final output"

        if perception["time_budget"] <= 2:
            return [
                self._step(f"Define the minimum acceptable result for: {focus}", "Write the exact finish line in one sentence.", 1, 3, ["scope"]),
                self._step("Complete the highest-impact work item", "Choose the one action that makes the goal visibly closer to done.", 3, 4, ["core"]),
                self._step(f"Check and package {final_output}", "Review only the essentials: correctness, completeness, and delivery format.", 1, 4, ["review"]),
            ]

        middle_steps = {
            "student_assignment": self._assignment_middle_steps(perception),
            "software_project": [
                self._step("Define the smallest working user path", "Name the one workflow that must work end to end before adding extras.", 2, 4, ["scope", "web"]),
                self._step("Implement the core workflow", "Build the critical path first and leave optional polish until it works.", 4, 5, ["core"]),
                self._step("Test the main path and fix failures", "Run the app like a user and repair the first blocking issue.", 3, 5, ["testing"]),
            ],
            "study_plan": [
                self._step("Rank weak topics by marks and confidence", "Put the most valuable or uncertain topics first.", 2, 4, ["scope"]),
                self._step("Run focused practice blocks", "Use active recall or representative questions instead of passive reading.", 4, 4, ["practice"]),
                self._step("Review mistakes and update notes", "Turn each error into a short rule, example, or flashcard.", 2, 4, ["review"]),
            ],
            "research_project": [
                self._step("Narrow the research question and scope", "State what will be answered and what will not be covered.", 2, 4, ["scope"]),
                self._step("Collect and compare credible sources or data", "Capture source, method, key finding, and limitation for each item.", 4, 5, ["research"]),
                self._step("Synthesize findings into an argument", "Group evidence by claim instead of summarising sources one by one.", 3, 5, ["writing"]),
            ],
            "writing_project": [
                self._step("Define the audience, claim, and structure", "Write the thesis or core message before drafting paragraphs.", 2, 4, ["scope"]),
                self._step("Draft the main sections quickly", "Get a complete rough version before editing sentences.", 4, 4, ["writing"]),
                self._step("Revise for evidence, flow, and clarity", "Check whether each section supports the main claim.", 3, 5, ["review"]),
            ],
            "career_goal": [
                self._step("Select the target role or opportunity", "Tune the plan to one realistic role, company type, or application.", 2, 4, ["scope"]),
                self._step("Prepare tailored evidence", "Connect resume, portfolio, examples, or interview stories to that target.", 4, 5, ["writing"]),
                self._step("Submit or rehearse with review notes", "Do one real application or one timed practice round.", 3, 4, ["review"]),
            ],
            "habit_goal": [
                self._step("Set a measurable baseline and trigger", "Choose when, where, and how the habit starts.", 2, 3, ["scope"]),
                self._step("Create the smallest repeatable routine", "Make the routine easy enough to do on a bad day.", 3, 4, ["core"]),
                self._step("Track progress and adjust friction", "Record completion and remove one obstacle each cycle.", 2, 4, ["memory"]),
            ],
            "event_plan": [
                self._step("Confirm purpose, date, people, and constraints", "Lock the facts that affect every later decision.", 2, 4, ["scope"]),
                self._step("Arrange logistics and materials", "Handle booking, agenda, transport, equipment, or invitations.", 4, 5, ["core"]),
                self._step("Prepare contingency and final checklist", "Identify what could fail and the fallback action.", 2, 5, ["safety"]),
            ],
            "creative_project": [
                self._step("Define the concept and reference standard", "Pick a concrete style, audience, and finished format.", 2, 4, ["scope"]),
                self._step("Produce a rough complete version", "Finish the full shape before polishing details.", 4, 4, ["core"]),
                self._step("Edit against the intended effect", "Remove anything that weakens the message or experience.", 3, 5, ["review"]),
            ],
            "general_goal": [
                self._step("Identify resources, blockers, and the first milestone", "Turn the goal into a visible next result.", 2, 4, ["scope"]),
                self._step("Complete the smallest useful version", "Do the version that creates evidence of progress fastest.", 4, 4, ["core"]),
                self._step("Review results and decide the next action", "Compare the result with the finish line and choose the next move.", 2, 4, ["review"]),
            ],
        }

        steps = [
            self._step(f"Define success criteria for: {focus}", "Write what done means, what can be skipped, and how quality will be judged.", 1, 4, ["scope"]),
            *middle_steps[perception["domain"]],
            self._step(f"Review and package {final_output}", "Check the deliverable, remove avoidable errors, and prepare the handoff.", 2, 5, ["review"]),
        ]
        max_steps = 4 if perception["time_budget"] <= 4 else 5 if perception["time_budget"] <= 8 else 6
        return steps[: max_steps - 1] + [steps[-1]] if len(steps) > max_steps else steps

    def _assignment_brief_steps(
        self, perception: dict[str, Any], llm_analysis: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        lower = perception["raw_goal"].lower()
        steps: list[dict[str, Any]] = []

        self._append_unique_step(
            steps,
            self._step(
                "Extract assignment deliverables and marking requirements",
                "Turn the brief into a checklist covering required outputs, report pages, repo evidence, video, screenshots, and submission rules.",
                2,
                4,
                ["assignment", "requirements"],
            ),
        )

        if self._has_any(lower, ["agent", "prototype", "software"]):
            self._append_unique_step(
                steps,
                self._step(
                    "Implement core agent loop: perception, decision, action, memory, safety",
                    "Verify each agent module exists and contributes visible information to the generated plan.",
                    5,
                    5,
                    ["core", "agent", "memory", "safety"],
                ),
            )

        if self._has_any(lower, ["api", "endpoint", "agent", "prototype", "software"]):
            self._append_unique_step(
                steps,
                self._step(
                    "Build or verify API endpoints such as /api/plan and /api/feedback",
                    "Check request/response JSON, session IDs, feedback updates, and error handling.",
                    4,
                    5,
                    ["api", "testing"],
                ),
            )

        if self._has_any(lower, ["web", "interface", "goal", "deadline", "available", "priority", "feedback", "agent"]):
            self._append_unique_step(
                steps,
                self._step(
                    "Build web interface for goal, deadline, available hours, priority, feedback, task status, and trace",
                    "Make the main workflow usable from the first screen: generate plan, apply feedback, update status, and inspect trace.",
                    4,
                    4,
                    ["web", "feedback"],
                ),
            )

        if self._has_any(lower, ["memory", "recent", "session", "reload", "agent"]):
            self._append_unique_step(
                steps,
                self._step(
                    "Add memory for recent plans and session reload",
                    "Store plans, feedback history, progress, focus state, and enough metadata for clear recent-plan cards.",
                    3,
                    4,
                    ["memory"],
                ),
            )

        if self._has_any(lower, ["safety", "deadline", "workload", "risk", "available hours", "agent"]):
            self._append_unique_step(
                steps,
                self._step(
                    "Add safety checks for workload, deadline pressure, and scope risk",
                    "Separate recommended effort from compressed planned hours so warnings are not contradictory.",
                    3,
                    5,
                    ["safety"],
                ),
            )

        if self._has_any(lower, ["page 1", "system design", "diagram", "report"]):
            self._append_unique_step(
                steps,
                self._step(
                    "Prepare system design diagram and design explanation for report page 1",
                    "Include the GitHub repo link, module diagram, and a concise explanation of perception, decision, action, memory, and safety.",
                    3,
                    4,
                    ["report", "page1", "diagram", "github"],
                ),
            )

        if self._has_any(lower, ["page 2", "screenshot", "screenshots", "system works", "report"]):
            self._append_unique_step(
                steps,
                self._step(
                    "Capture screenshots and explain system workflow for report page 2",
                    "Show initial plan generation, feedback updates, and the trace/memory/safety panels.",
                    3,
                    4,
                    ["report", "page2", "screenshots"],
                ),
            )

        if self._has_any(lower, ["readme", "reproduction", "installation", "api usage", "github", "repo"]):
            self._append_unique_step(
                steps,
                self._step(
                    "Update README with installation, reproduction, API usage, screenshots, and demo link",
                    "Make the repository reproducible with commands, curl examples, feature list, limitations, and placeholders for screenshots/video.",
                    3,
                    4,
                    ["readme", "github"],
                ),
            )

        if self._has_any(lower, ["demo video", "2-minute", "2 minute", "video", "demo"]):
            self._append_unique_step(
                steps,
                self._step(
                    "Record 2-minute demo video and add link to GitHub",
                    "Demonstrate plan generation, feedback updates, status updates, trace, safety, and memory.",
                    2,
                    4,
                    ["demo", "video", "github"],
                ),
            )

        if self._has_any(lower, ["commit", "checkpoint", "github", "repo"]):
            self._append_unique_step(
                steps,
                self._step(
                    "Make meaningful commit checkpoints",
                    "Create commits around core agent logic, UI/API integration, documentation, and final demo/report evidence.",
                    2,
                    3,
                    ["git", "github"],
                ),
            )

        for section in perception.get("sections", [])[:4]:
            if self._has_any(section.lower(), ["page 1", "page 2"]):
                continue
            self._append_unique_step(
                steps,
                self._step(
                    f"Complete brief section: {section}",
                    "Answer every sub-requirement in this section and keep evidence for the final report or repository.",
                    3,
                    4,
                    self._tags_for_text(section),
                ),
            )

        if len(steps) < 5:
            for step in self._llm_steps(llm_analysis, perception["raw_goal"]):
                self._append_unique_step(steps, step)

        if len(steps) < 5:
            for step in self._assignment_middle_steps(perception):
                self._append_unique_step(steps, step)

        self._append_unique_step(
            steps,
            self._step(
                "Run final acceptance check against the brief",
                "Verify the app runs, required endpoints return JSON, feedback updates change the plan, and repo/report/video evidence is ready.",
                1,
                3,
                ["testing", "requirements"],
            ),
        )
        return steps[:12]

    def _assignment_middle_steps(self, perception: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._step(
                "Complete the main assignment implementation",
                "Produce the working artefact requested by the brief before polishing documentation.",
                4,
                5,
                ["core"],
            ),
            self._step(
                "Prepare required report and repository evidence",
                "Convert implementation results into screenshots, design notes, README instructions, and final submission evidence.",
                3,
                4,
                ["report", "github"],
            ),
            self._step(
                "Check against the marking criteria",
                "Compare the final work with the rubric or marks allocation and fix the highest-value missing items first.",
                2,
                5,
                ["requirements", "testing"],
            ),
        ]

    def _llm_steps(self, llm_analysis: dict[str, Any] | None, brief: str = "") -> list[dict[str, Any]]:
        if not llm_analysis:
            return []
        steps = []
        brief_words = set(re.findall(r"[a-zA-Z][a-zA-Z0-9-]{3,}", brief.lower()))
        for item in llm_analysis.get("tasks", []):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            hint = str(item.get("hint", "")).strip()
            if not title:
                continue
            if brief_words and not self._task_overlaps_brief(title, brief_words):
                continue
            steps.append(
                self._step(
                    title,
                    hint or "Complete the smallest useful version first.",
                    self._safe_int(item.get("weight", 2), 1, 5),
                    self._safe_int(item.get("risk", 3), 1, 5),
                    self._tags_for_text(title),
                )
            )
        return steps if len(steps) >= 3 else []

    def _detect_constraints(self, goal: str, request: PlanRequest, deliverables: list[str]) -> list[str]:
        lower = goal.lower()
        constraints = []
        if request.available_hours < 3:
            constraints.append("Very limited time budget")
        if not request.deadline:
            constraints.append("Missing explicit deadline")
        if self._detect_input_type(goal) == "assignment_brief":
            constraints.append("Copied assignment brief detected")
        if self._has_any(lower, ["github", "repository", "repo", "commit"]):
            constraints.append("Repository evidence required")
        if any(item.lower().startswith("report") or item in {"report", "paper", "essay", "proposal"} for item in deliverables):
            constraints.append("Written explanation required")
        if any(item in deliverables for item in ["demo video", "presentation", "slides"]):
            constraints.append("Presentation or demo evidence required")
        if "screenshots" in deliverables:
            constraints.append("Screenshot evidence required")
        if self._has_any(lower, ["hard", "confusing", "stuck", "blocked", "unclear"]):
            constraints.append("Blocker or uncertainty mentioned")
        return constraints

    def _extract_keywords(self, goal: str) -> list[str]:
        stop_words = {
            "the", "and", "for", "with", "this", "that", "into", "from", "have",
            "need", "want", "make", "complete", "finish", "using", "about",
            "should", "include",
        }
        english = [
            word.lower()
            for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", goal)
            if word.lower() not in stop_words
        ]
        chinese = re.findall(r"[\u4e00-\u9fff]{2,}", goal)
        keywords = []
        for word in english + chinese:
            if word not in keywords:
                keywords.append(word)
        return keywords[:12]

    def _extract_deliverables(self, goal: str, domain: str) -> list[str]:
        lower = goal.lower()
        markers = [
            ("system design diagram", "system design diagram"),
            ("design explanation", "design explanation"),
            ("page 1", "report page 1"),
            ("page 2", "report page 2"),
            ("readme", "README"),
            ("github", "GitHub repository"),
            ("repository", "repository"),
            ("repo", "repository"),
            ("commit", "commit checkpoints"),
            ("api", "API endpoints"),
            ("endpoint", "API endpoints"),
            ("web interface", "web interface"),
            ("interface", "web interface"),
            ("memory", "memory store"),
            ("safety", "safety checks"),
            ("source code", "source code"),
            ("report", "report"),
            ("paper", "paper"),
            ("essay", "essay"),
            ("proposal", "proposal"),
            ("slides", "slides"),
            ("presentation", "presentation"),
            ("screenshots", "screenshots"),
            ("screenshot", "screenshots"),
            ("demo video", "demo video"),
            ("video", "demo video"),
            ("prototype", "prototype"),
            ("app", "app"),
            ("website", "website"),
            ("resume", "resume"),
            ("portfolio", "portfolio"),
            (".py", "Python file"),
            (".ipynb", "notebook"),
            (".pdf", "PDF"),
            (".zip", "ZIP submission"),
        ]
        deliverables = []
        for marker, name in markers:
            if self._contains_marker(lower, marker) and name not in deliverables:
                deliverables.append(name)
        if "GitHub repository" in deliverables and "repository" in deliverables:
            deliverables.remove("repository")
        if not deliverables:
            defaults = {
                "software_project": ["working prototype"],
                "study_plan": ["practice results"],
                "research_project": ["research summary"],
                "writing_project": ["draft"],
                "career_goal": ["tailored application material"],
                "habit_goal": ["tracked routine"],
                "event_plan": ["event checklist"],
                "creative_project": ["finished creative piece"],
                "student_assignment": ["submission package"],
                "general_goal": ["visible outcome"],
            }
            deliverables = defaults[domain]
        return deliverables[:12]

    def _estimate_complexity(self, goal: str, available_hours: float, deliverables: list[str]) -> str:
        signals = len(deliverables) + len(re.findall(r"\b(and|with|plus|including|should include)\b", goal.lower()))
        if available_hours < 3:
            return "compressed"
        if signals >= 7 or len(goal) > 450:
            return "high"
        if signals >= 3 or len(goal) > 160:
            return "medium"
        return "low"

    def _deadline_pressure(self, deadline: str | None, priority: str) -> str:
        if not deadline:
            return "unknown"
        lower = deadline.lower()
        parsed_date = self._parse_date(deadline)
        if parsed_date:
            days_left = (parsed_date - date.today()).days
            if days_left <= 1:
                return "urgent"
            if days_left <= 7:
                return "soon"
            return "normal"
        if self._has_any(lower, ["today", "tonight", "asap", "urgent"]):
            return "urgent"
        if self._has_any(lower, ["tomorrow", "this week", "week 11"]):
            return "soon"
        if priority == "high":
            return "soon"
        return "normal"

    def _detect_input_type(self, goal: str) -> str:
        lower = goal.lower()
        if len(goal) > 700 or self._looks_like_assignment_brief(lower):
            return "assignment_brief"
        return "goal_description"

    def _looks_like_assignment_brief(self, lower_goal: str) -> bool:
        if len(lower_goal) > 700:
            return True
        if re.search(r"\bpart\s+[a-z]\s*:", lower_goal):
            return True
        if re.search(r"\bpage\s*[12]\b", lower_goal) and self._has_any(lower_goal, ["report", "github", "readme", "screenshots", "demo"]):
            return True
        if "should include" in lower_goal and sum(1 for signal in ["github", "readme", "report", "screenshots", "demo", "commit"] if signal in lower_goal) >= 2:
            return True
        if self._has_any(lower_goal, ["rubric", "marking", "criteria", "marks", "submission", "deliverables"]):
            return True
        signals = [
            "assignment", "coursework", "submit", "grade", "deadline", "late penalty",
            "requirements", "learning outcome", "teacher-provided", "brief",
        ]
        return sum(1 for signal in signals if signal in lower_goal) >= 2

    def _extract_methods(self, goal: str) -> list[str]:
        lower = goal.lower()
        markers = [
            ("perception", "perception module required"),
            ("decision", "decision module required"),
            ("action", "action module required"),
            ("memory", "memory required"),
            ("safety", "safety checks required"),
            ("api", "API required"),
            ("screenshot", "screenshot evidence required"),
            ("demo", "demo evidence required"),
            ("readme", "README documentation required"),
            ("calculate", "calculation required"),
            ("determine", "determination required"),
            ("compare", "comparison required"),
            ("discuss", "discussion required"),
            ("interpret", "interpretation required"),
            ("identify", "identification required"),
            ("hypothesize", "hypothesis required"),
            ("draw", "diagram or model required"),
            ("include", "included item required"),
            ("specify", "specification required"),
            ("collect", "collection plan required"),
            ("submit", "submission requirement"),
            ("report", "reporting requirement"),
            ("max.", "word limit or response limit"),
            ("marks", "mark allocation"),
        ]
        methods = []
        for marker, label in markers:
            if marker in lower and label not in methods:
                methods.append(label)
        return methods[:12]

    def _extract_sections(self, goal: str) -> list[str]:
        sections = []
        for match in re.finditer(r"\b(part\s+[a-z])\s*:\s*([^.\n]{0,110})", goal, flags=re.IGNORECASE):
            heading = f"{match.group(1).title()}: {match.group(2).strip()}".strip(" .")
            if heading not in sections:
                sections.append(heading)
        for match in re.finditer(r"\b(page\s*[12])\s*(?:should include|include|:)?\s*([^.\n]{0,120})", goal, flags=re.IGNORECASE):
            heading = f"{match.group(1).title()}: {match.group(2).strip()}".strip(" .")
            if heading not in sections:
                sections.append(heading)
        for match in re.finditer(r"(\([a-z]\))\s*([^.\n]{0,110})", goal, flags=re.IGNORECASE):
            heading = f"{match.group(1)} {match.group(2).strip()}".strip(" .")
            if heading not in sections:
                sections.append(heading)
        for line in goal.splitlines():
            cleaned = line.strip(" .")
            if len(cleaned) > 140 or len(re.findall(r"\bpart\s+[a-z]\s*:", cleaned, flags=re.IGNORECASE)) > 1:
                continue
            if re.match(r"^part\s+[a-z]\b", cleaned, flags=re.IGNORECASE):
                if cleaned[:120] not in sections:
                    sections.append(cleaned[:120])
            elif re.match(r"^\(?[a-c]\)", cleaned, flags=re.IGNORECASE):
                if cleaned[:120] not in sections:
                    sections.append(cleaned[:120])
        return sections[:10]

    def _parse_date(self, value: str) -> date | None:
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None

    def _deadline_details(self, deadline: str | None, priority: str) -> dict[str, Any]:
        if not deadline:
            return {"pressure": "unknown", "date": None, "days_left": None, "hours_remaining": None}

        parsed_date = self._parse_date(deadline)
        if parsed_date:
            now = datetime.now().astimezone()
            end_of_deadline = datetime.combine(parsed_date, time.max).replace(tzinfo=now.tzinfo)
            hours_remaining = max(0.0, round((end_of_deadline - now).total_seconds() / 3600, 1))
            days_left = (parsed_date - now.date()).days
            if hours_remaining <= 24:
                pressure = "urgent"
            elif hours_remaining <= 168:
                pressure = "soon"
            else:
                pressure = "normal"
            return {
                "pressure": pressure,
                "date": parsed_date.isoformat(),
                "days_left": days_left,
                "hours_remaining": hours_remaining,
            }

        return {
            "pressure": self._deadline_pressure(deadline, priority),
            "date": None,
            "days_left": None,
            "hours_remaining": None,
        }

    def _estimate_recommended_hours(
        self,
        goal: str,
        domain: str,
        deliverables: list[str],
        methods: list[str],
        input_type: str,
        priority: str,
        available_hours: float,
    ) -> float:
        base_hours = {
            "student_assignment": 5.5,
            "software_project": 6.0,
            "study_plan": 5.0,
            "research_project": 6.0,
            "writing_project": 5.5,
            "career_goal": 4.0,
            "habit_goal": 3.5,
            "event_plan": 4.5,
            "creative_project": 5.0,
            "general_goal": 4.0,
        }[domain]
        base_hours += min(4.0, len(deliverables) * 0.4)
        base_hours += min(2.0, len(methods) * 0.3)
        if input_type == "assignment_brief":
            base_hours += 1.0
        if self._has_any(goal.lower(), ["agent", "prototype", "api", "web interface"]):
            base_hours += 1.0
        if len(goal) > 1500:
            base_hours += 1.5
        elif len(goal) > 700:
            base_hours += 0.8
        if priority == "high":
            base_hours += 0.5
        if available_hours <= 2:
            base_hours = max(base_hours, 4.0)
        return round(base_hours * 2) / 2

    def _allocate_effort(self, time_budget: float, weights: list[int]) -> list[float]:
        if not weights:
            return []
        total_tenths = max(len(weights), int(round(time_budget * 10)))
        total_weight = max(1, sum(weights))
        allocations = [max(1, int(round(total_tenths * weight / total_weight))) for weight in weights]

        while sum(allocations) > total_tenths:
            index = max(range(len(allocations)), key=lambda item: allocations[item])
            if allocations[index] == 1:
                break
            allocations[index] -= 1

        while sum(allocations) < total_tenths:
            index = max(range(len(weights)), key=lambda item: (weights[item], -allocations[item]))
            allocations[index] += 1

        return [round(value / 10, 1) for value in allocations]

    def _extract_time_budget(self, feedback: str) -> float | None:
        patterns = [
            r"(?:only|have|budget|available|left|just)\D{0,24}(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)",
            r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\D{0,24}(?:left|available|today|now)",
        ]
        for pattern in patterns:
            match = re.search(pattern, feedback)
            if match:
                return max(0.5, min(80.0, float(match.group(1))))
        return None

    def _feedback_completion_tags(self, feedback: str) -> list[str]:
        not_done = self._has_any(feedback, ["not done", "not finished", "isn't done", "is not done", "still need", "unfinished", "haven't finished"])
        completed = self._has_any(feedback, ["finished", "done", "complete", "completed", "already finished", "already done"])
        return [] if not_done or not completed else self._feedback_tags(feedback)

    def _feedback_not_done_tags(self, feedback: str) -> list[str]:
        not_done = self._has_any(feedback, ["not done", "not finished", "isn't done", "is not done", "still need", "unfinished", "haven't finished"])
        return self._feedback_tags(feedback) if not_done else []

    def _feedback_tags(self, feedback: str) -> list[str]:
        tags: list[str] = []
        tag_terms = {
            "readme": ["readme"],
            "report": ["report", "page 1", "page 2", "write-up", "writeup"],
            "demo": ["demo", "video", "2-minute", "2 minute"],
            "github": ["github", "repo", "repository", "commit"],
            "screenshots": ["screenshot", "screenshots"],
            "api": ["api", "endpoint", "/api/plan", "/api/feedback"],
            "web": ["web", "interface", "ui"],
            "memory": ["memory", "recent plan", "session"],
            "safety": ["safety", "warning", "deadline", "workload"],
        }
        for tag, terms in tag_terms.items():
            if self._has_any(feedback, terms):
                tags.append(tag)
        return tags

    def _extract_requested_addition(self, feedback: str) -> str | None:
        match = re.search(r"(?:add|include|also need|also add)\s+(.{4,80})", feedback, re.IGNORECASE)
        if not match:
            return None
        addition = match.group(1).strip(" .")
        if not addition:
            return None
        return addition[:80]

    def _mark_tasks_done(self, tasks: list[dict[str, Any]], tags: list[str]) -> int:
        changed = 0
        for task in tasks:
            if self._task_matches_tags(task, tags) and task["status"] != "done":
                task["status"] = "done"
                task["deferred"] = False
                task["schedule"] = "Completed from feedback"
                changed += 1
        return changed

    def _prioritize_tasks(self, tasks: list[dict[str, Any]], tags: list[str]) -> int:
        changed = 0
        for task in tasks:
            if self._task_matches_tags(task, tags) and task["status"] != "done":
                task["status"] = "todo"
                task["deferred"] = False
                task["priority_score"] = min(10, task["priority_score"] + 3)
                task["schedule"] = "Next"
                task["support_hint"] = "Feedback says this is unfinished; complete the smallest visible version before other polish."
                changed += 1
        return changed

    def _compress_and_defer(self, tasks: list[dict[str, Any]], time_budget: float) -> None:
        completed_hours = sum(float(task.get("effort_hours", 0)) for task in tasks if task["status"] == "done")
        remaining_budget = max(0.0, time_budget - completed_hours)
        active_tasks = [task for task in tasks if task["status"] != "done"]
        active_tasks.sort(key=lambda task: (-task.get("priority_score", 0), task.get("order", 0)))
        if not active_tasks:
            return

        max_active = max(2, min(len(active_tasks), int(max(2, round(remaining_budget * 2)))))
        selected = active_tasks[:max_active]
        deferred = active_tasks[max_active:]

        allocations = self._allocate_effort(max(0.5, remaining_budget), [max(1, task.get("priority_score", 1)) for task in selected])
        for index, task in enumerate(selected):
            task["effort_hours"] = allocations[index]
            task["deferred"] = False
            task["schedule"] = "Emergency plan" if time_budget <= 2.5 else self._schedule_label(index + 1, len(selected))

        for task in deferred:
            task["effort_hours"] = 0.0
            task["deferred"] = True
            task["schedule"] = "Deferred"
            task["support_hint"] = "Deferred until more time is available; keep only if required by the marker."

    def _fit_remaining_effort(self, tasks: list[dict[str, Any]], time_budget: float) -> None:
        completed_hours = sum(float(task.get("effort_hours", 0)) for task in tasks if task["status"] == "done")
        remaining_tasks = [task for task in tasks if task["status"] != "done" and not task.get("deferred")]
        if not remaining_tasks:
            return
        remaining_budget = max(0.1, time_budget - completed_hours)
        allocations = self._allocate_effort(remaining_budget, [max(1, task.get("priority_score", 1)) for task in remaining_tasks])
        for index, task in enumerate(remaining_tasks):
            task["effort_hours"] = allocations[index]

    def _make_feedback_task(self, addition: str, perception: dict[str, Any], order: int) -> dict[str, Any]:
        urgency_weight = {"low": 1, "medium": 2, "high": 3}[perception["urgency"]]
        return {
            "id": str(uuid.uuid4()),
            "order": order,
            "title": f"Address requested addition: {addition}",
            "status": "todo",
            "priority_score": min(10, urgency_weight + 3),
            "effort_hours": 0.5,
            "schedule": "Added from feedback",
            "support_hint": "Define the smallest acceptable version of this addition before expanding scope.",
            "tags": self._tags_for_text(addition),
            "deferred": False,
        }

    def _progress(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(tasks)
        completed = [task for task in tasks if task.get("status") == "done"]
        completed_hours = round(sum(float(task.get("effort_hours", 0)) for task in completed), 1)
        remaining_hours = round(sum(float(task.get("effort_hours", 0)) for task in tasks if task.get("status") != "done"), 1)
        tracked_seconds = sum(int(task.get("elapsed_seconds") or 0) for task in tasks)
        percent = round((len(completed) / total) * 100) if total else 0
        return {
            "completed_tasks": len(completed),
            "total_tasks": total,
            "completed_hours": completed_hours,
            "remaining_planned_hours": remaining_hours,
            "percent_complete": percent,
            "tracked_focus_seconds": tracked_seconds,
        }

    def _risk_level(
        self,
        warnings: list[str],
        perception: dict[str, Any],
        recommended_hours: float,
        available_hours: float,
    ) -> str:
        if len(warnings) >= 2 or recommended_hours > available_hours * 1.5:
            return "high"
        if warnings or perception.get("deadline_pressure") in {"urgent", "soon"}:
            return "medium"
        return "low"

    def _short_title(self, session: dict[str, Any]) -> str:
        perception = session.get("perception", {})
        goal = session.get("goal", "")
        lower = goal.lower()
        event = "Updated Plan" if session.get("event_type") == "updated" else "Plan"
        hours = self._format_hours(session.get("planned_hours", session.get("available_hours", 0)))
        if "ollama" in lower:
            return f"Ollama Integration Test {event} - {len(session.get('tasks', []))} tasks"
        if "demo" in lower and perception.get("input_type") != "assignment_brief":
            return f"Demo Preparation {event} - {len(session.get('tasks', []))} tasks"
        if perception.get("input_type") == "assignment_brief" or self._has_any(lower, ["assignment 2", "ass2", "compsci 767"]):
            return f"Assignment 2 {event} - {hours}"
        return f"{self._title_from_goal(goal)} {event} - {len(session.get('tasks', []))} tasks"

    def _title_from_goal(self, goal: str) -> str:
        words = [
            word.capitalize()
            for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", goal)
            if word.lower() not in {"the", "and", "for", "with", "this", "that", "should", "include"}
        ]
        return " ".join(words[:4]) or "Task Planning"

    def _step(self, title: str, hint: str, weight: int, risk: int, tags: list[str] | None = None) -> dict[str, Any]:
        return {"title": title, "hint": hint, "weight": weight, "risk": risk, "tags": tags or self._tags_for_text(title)}

    def _append_unique_step(self, steps: list[dict[str, Any]], step: dict[str, Any]) -> None:
        title = step["title"].lower()
        if not any(existing["title"].lower() == title for existing in steps):
            steps.append(step)

    def _goal_focus(self, goal: str) -> str:
        cleaned = re.sub(r"\s+", " ", goal).strip()
        return cleaned if len(cleaned) <= 90 else f"{cleaned[:87]}..."

    def _schedule_label(self, index: int, total: int) -> str:
        if index == 1:
            return "Start"
        if index == total:
            return "Final check"
        return f"Block {index}"

    def _sort_tasks(self, tasks: list[dict[str, Any]]) -> None:
        tasks.sort(
            key=lambda task: (
                task.get("status") == "done",
                task.get("deferred", False),
                -task.get("priority_score", 0),
                task.get("order", 0),
            )
        )
        for index, task in enumerate(tasks, start=1):
            task["order"] = index

    def _task_matches_tags(self, task: dict[str, Any], tags: list[str]) -> bool:
        task_tags = set(task.get("tags") or self._tags_for_text(task.get("title", "")))
        title = task.get("title", "").lower()
        return any(tag in task_tags for tag in tags) or (
            not task.get("tags") and any(tag in title for tag in tags)
        )

    def _tags_for_text(self, text: str) -> list[str]:
        lower = text.lower()
        tags = []
        tag_terms = {
            "readme": ["readme", "reproduction", "installation"],
            "report": ["report", "write-up", "writeup"],
            "page1": ["page 1", "system design", "diagram", "design explanation"],
            "page2": ["page 2", "screenshot", "screenshots", "workflow"],
            "screenshots": ["screenshot", "screenshots"],
            "demo": ["demo", "video"],
            "video": ["video"],
            "github": ["github", "repository", "repo"],
            "git": ["commit", "checkpoint"],
            "api": ["api", "endpoint", "/api/plan", "patch"],
            "web": ["web", "interface", "ui", "goal", "deadline", "priority"],
            "memory": ["memory", "session", "recent"],
            "safety": ["safety", "deadline", "workload", "risk"],
            "agent": ["agent", "perception", "decision", "action"],
            "testing": ["test", "verify", "acceptance"],
            "requirements": ["requirement", "deliverable", "marking", "brief"],
            "core": ["core", "implement", "prototype"],
        }
        for tag, terms in tag_terms.items():
            if self._has_any(lower, terms):
                tags.append(tag)
        return tags or ["general"]

    def _has_any(self, text: str, terms: list[str]) -> bool:
        return any(term in text for term in terms)

    def _merge_lists(self, first: list[Any], second: list[Any]) -> list[str]:
        merged = []
        for item in [*first, *second]:
            text = str(item).strip()
            if text and text not in merged:
                merged.append(text)
        return merged[:14]

    def _safe_int(self, value: Any, lower: int, upper: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = lower
        return max(lower, min(upper, number))

    def _task_overlaps_brief(self, title: str, brief_words: set[str]) -> bool:
        generic_words = {
            "assignment", "brief", "requirement", "requirements", "complete", "prepare",
            "review", "draft", "final", "submit", "submission", "part", "question",
            "deliverable", "deliverables", "report", "analysis", "model", "data",
            "github", "readme", "demo", "video", "screenshot", "agent", "api",
        }
        title_words = set(re.findall(r"[a-zA-Z][a-zA-Z0-9-]{3,}", title.lower()))
        return bool((title_words & brief_words) or (title_words & generic_words))

    def _contains_marker(self, text: str, marker: str) -> bool:
        if re.fullmatch(r"[a-z0-9 /.-]+", marker):
            return re.search(rf"\b{re.escape(marker)}\b", text) is not None
        return marker in text

    def _format_optional_hours(self, value: Any) -> str:
        return "unknown" if value is None else self._format_hours(float(value))

    def _format_hours(self, value: Any) -> str:
        number = float(value or 0)
        formatted = f"{number:.1f}".rstrip("0").rstrip(".")
        return f"{formatted}h"

    def _format_duration(self, seconds: Any) -> str:
        total = max(0, int(seconds or 0))
        minutes, second = divmod(total, 60)
        hours, minute = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minute}m"
        if minute:
            return f"{minute}m {second}s"
        return f"{second}s"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
