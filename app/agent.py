from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.models import FeedbackRequest, PlanRequest


class TaskPlanningAgent:
    """Rule-based planning agent with perception, decision, action, memory, and safety outputs."""

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
        updated_budget = self._extract_time_budget(lower)
        agent_log = [
            f'Perceived feedback: "{feedback}"',
            "Decision: re-evaluate task order, scope, effort, and risk from the feedback.",
        ]

        if updated_budget is not None:
            session["available_hours"] = updated_budget
            session["perception"]["time_budget"] = updated_budget
            constraints = session["perception"].setdefault("constraints", [])
            if updated_budget < 3 and "Very limited time budget" not in constraints:
                constraints.append("Very limited time budget")
            agent_log.append(f"Perception: detected a revised time budget of {updated_budget:g} hours.")

        if any(term in lower for term in ["less time", "busy", "only", "reduce", "shorter", "too much", "太多", "没时间", "少一点"]):
            self._fit_remaining_effort(tasks, session["perception"]["time_budget"])
            agent_log.append("Action: compressed remaining tasks to fit the revised time budget.")

        if any(term in lower for term in ["hard", "confusing", "stuck", "blocked", "unclear", "卡住", "不会", "不清楚"]):
            for task in tasks:
                if task["status"] == "todo":
                    task["priority_score"] += 1
                    task["support_hint"] = "Turn this into one 25-minute attempt, then write the exact question or blocker."
            agent_log.append("Action: raised unresolved task priority and added blocker-focused hints.")

        if any(term in lower for term in ["specific", "detail", "too generic", "具体", "细化", "详细"]):
            for task in tasks:
                if task["status"] == "todo":
                    task["support_hint"] = "Define one visible output for this task before starting, then stop when that output exists."
            agent_log.append("Action: made the remaining task hints more concrete.")

        if any(term in lower for term in ["tomorrow", "later", "delay", "extend", "明天", "延后", "推迟"]):
            for task in tasks:
                if task["status"] == "todo":
                    task["schedule"] = "Later slot"
            agent_log.append("Action: moved remaining todo items into a later planning slot.")

        addition = self._extract_requested_addition(feedback)
        if addition:
            tasks.append(self._make_feedback_task(addition, session["perception"], len(tasks) + 1))
            self._fit_remaining_effort(tasks, session["perception"]["time_budget"])
            agent_log.append(f'Action: added a requested task for "{addition}".')

        tasks.sort(key=lambda item: (item["status"] == "done", -item["priority_score"], item["order"]))
        for index, task in enumerate(tasks, start=1):
            task["order"] = index

        session["tasks"] = tasks
        session["feedback_history"].append(
            {"at": self._now(), "feedback": feedback, "agent_response": agent_log}
        )
        safety = self._safety_check(session["perception"], {"tasks": tasks})
        session["safety"] = safety
        session["agent_log"] = agent_log + safety["messages"]
        session["updated_at"] = self._now()
        return session

    def update_status(self, session: dict[str, Any], task_id: str, status: str) -> dict[str, Any]:
        for task in session["tasks"]:
            if task["id"] == task_id:
                task["status"] = status
                session["agent_log"] = [
                    f"Action: updated task '{task['title']}' to {status}.",
                    "Decision: keep the plan but move completed work lower in the active queue.",
                ]
                session["tasks"].sort(key=lambda item: (item["status"] == "done", item["order"]))
                session["updated_at"] = self._now()
                return session
        raise KeyError(f"Unknown task_id: {task_id}")

    def _perceive(self, request: PlanRequest) -> dict[str, Any]:
        goal = request.goal.strip()
        domain = self._classify_domain(goal)
        deliverables = self._extract_deliverables(goal, domain)
        return {
            "raw_goal": goal,
            "keywords": self._extract_keywords(goal),
            "domain": domain,
            "deliverables": deliverables,
            "deadline_detected": bool(request.deadline),
            "deadline_pressure": self._deadline_pressure(request.deadline, request.priority),
            "time_budget": request.available_hours,
            "urgency": request.priority,
            "complexity": self._estimate_complexity(goal, request.available_hours, deliverables),
            "constraints": self._detect_constraints(goal, request, deliverables),
        }

    def _decide(self, perception: dict[str, Any]) -> dict[str, Any]:
        steps = self._build_steps(perception)
        efforts = self._allocate_effort(perception["time_budget"], [step["weight"] for step in steps])
        urgency_weight = {"low": 1, "medium": 2, "high": 3}[perception["urgency"]]
        return {
            "strategy": "goal_aware_decomposition",
            "selected_template": perception["domain"],
            "urgency_weight": urgency_weight,
            "task_count": len(steps),
            "steps": steps,
            "effort_plan": efforts,
            "reason": "The agent infers the goal type, deliverables, constraints, and time pressure before building the task sequence.",
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
                }
            )

        return {
            "tasks": tasks,
            "agent_log": [
                "Perception: parsed the goal, domain, deliverables, deadline pressure, time budget, and constraints.",
                f"Decision: selected a {decisions['selected_template']} workflow with {decisions['task_count']} tasks.",
                "Action: generated a prioritized plan with effort estimates and concrete support hints.",
            ],
        }

    def _safety_check(self, perception: dict[str, Any], actions: dict[str, Any]) -> dict[str, Any]:
        total_hours = round(sum(task["effort_hours"] for task in actions["tasks"]), 1)
        messages = []
        warnings = []

        if not perception.get("deadline_detected"):
            warnings.append("No explicit deadline was provided.")
            messages.append("Safety: no deadline detected, so the plan includes a final review task.")

        if perception.get("deadline_pressure") == "urgent" and total_hours > 4:
            warnings.append("Urgent deadline with a large workload.")
            messages.append("Safety: urgent deadline detected; keep only the highest-value output if time slips.")

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
        if self._has_any(lower, ["assignment", "coursework", "course", "homework", "rubric", "submit", "compsci", "ass2", "作业", "课程", "提交"]):
            return "student_assignment"
        if self._has_any(lower, ["app", "website", "api", "code", "debug", "prototype", "software", "网站", "应用", "程序", "编程", "调试"]):
            return "software_project"
        if self._has_any(lower, ["research", "literature", "dataset", "experiment", "survey", "reading report", "研究", "文献", "数据", "实验", "阅读报告"]):
            return "research_project"
        if self._has_any(lower, ["essay", "paper", "article", "proposal", "write", "report", "论文", "写作", "文章", "提案", "报告"]):
            return "writing_project"
        if self._has_any(lower, ["exam", "quiz", "study", "revise", "revision", "test", "考试", "复习", "学习", "测验"]):
            return "study_plan"
        if self._has_any(lower, ["resume", "cv", "interview", "job", "internship", "portfolio", "简历", "面试", "求职", "实习"]):
            return "career_goal"
        if self._has_any(lower, ["workout", "fitness", "diet", "habit", "sleep", "健身", "运动", "减肥", "习惯", "睡眠"]):
            return "habit_goal"
        if self._has_any(lower, ["event", "trip", "travel", "meeting", "presentation", "活动", "旅行", "会议", "演讲"]):
            return "event_plan"
        if self._has_any(lower, ["video", "design", "podcast", "art", "demo", "视频", "设计", "作品", "演示"]):
            return "creative_project"
        return "general_goal"

    def _build_steps(self, perception: dict[str, Any]) -> list[dict[str, Any]]:
        focus = self._goal_focus(perception["raw_goal"])
        deliverables = perception["deliverables"]
        final_output = ", ".join(deliverables) if deliverables else "the final output"

        if perception["time_budget"] <= 2:
            return [
                self._step(f"Define the minimum acceptable result for: {focus}", "Write the exact finish line in one sentence.", 1, 3),
                self._step("Complete the highest-impact work item", "Choose the one action that makes the goal visibly closer to done.", 3, 4),
                self._step(f"Check and package {final_output}", "Review only the essentials: correctness, completeness, and delivery format.", 1, 4),
            ]

        middle_steps = {
            "student_assignment": [
                self._step("Map requirements to required evidence", "List each rubric or submission requirement and the file or screenshot that proves it.", 2, 4),
                self._step("Build the core submission artifact", "Finish the smallest version that demonstrates the required agent behaviour.", 4, 5),
                self._step("Prepare report, README, and demo evidence", "Make reproduction steps and screenshots/video easy for a marker to verify.", 3, 4),
            ],
            "software_project": [
                self._step("Define the smallest working user path", "Name the one workflow that must work end to end before adding extras.", 2, 4),
                self._step("Implement the core workflow", "Build the critical path first and leave optional polish until it works.", 4, 5),
                self._step("Test the main path and fix failures", "Run the app like a user and repair the first blocking issue.", 3, 5),
            ],
            "study_plan": [
                self._step("Rank weak topics by marks and confidence", "Put the most valuable or uncertain topics first.", 2, 4),
                self._step("Run focused practice blocks", "Use active recall or representative questions instead of passive reading.", 4, 4),
                self._step("Review mistakes and update notes", "Turn each error into a short rule, example, or flashcard.", 2, 4),
            ],
            "research_project": [
                self._step("Narrow the research question and scope", "State what will be answered and what will not be covered.", 2, 4),
                self._step("Collect and compare credible sources or data", "Capture source, method, key finding, and limitation for each item.", 4, 5),
                self._step("Synthesize findings into an argument", "Group evidence by claim instead of summarising sources one by one.", 3, 5),
            ],
            "writing_project": [
                self._step("Define the audience, claim, and structure", "Write the thesis or core message before drafting paragraphs.", 2, 4),
                self._step("Draft the main sections quickly", "Get a complete rough version before editing sentences.", 4, 4),
                self._step("Revise for evidence, flow, and clarity", "Check whether each section supports the main claim.", 3, 5),
            ],
            "career_goal": [
                self._step("Select the target role or opportunity", "Tune the plan to one realistic role, company type, or application.", 2, 4),
                self._step("Prepare tailored evidence", "Connect resume, portfolio, examples, or interview stories to that target.", 4, 5),
                self._step("Submit or rehearse with feedback", "Do one real application or one timed practice round.", 3, 4),
            ],
            "habit_goal": [
                self._step("Set a measurable baseline and trigger", "Choose when, where, and how the habit starts.", 2, 3),
                self._step("Create the smallest repeatable routine", "Make the routine easy enough to do on a bad day.", 3, 4),
                self._step("Track progress and adjust friction", "Record completion and remove one obstacle each cycle.", 2, 4),
            ],
            "event_plan": [
                self._step("Confirm purpose, date, people, and constraints", "Lock the facts that affect every later decision.", 2, 4),
                self._step("Arrange logistics and materials", "Handle booking, agenda, transport, equipment, or invitations.", 4, 5),
                self._step("Prepare contingency and final checklist", "Identify what could fail and the fallback action.", 2, 5),
            ],
            "creative_project": [
                self._step("Define the concept and reference standard", "Pick a concrete style, audience, and finished format.", 2, 4),
                self._step("Produce a rough complete version", "Finish the full shape before polishing details.", 4, 4),
                self._step("Edit against the intended effect", "Remove anything that weakens the message or experience.", 3, 5),
            ],
            "general_goal": [
                self._step("Identify resources, blockers, and the first milestone", "Turn the goal into a visible next result.", 2, 4),
                self._step("Complete the smallest useful version", "Do the version that creates evidence of progress fastest.", 4, 4),
                self._step("Review results and decide the next action", "Compare the result with the finish line and choose the next move.", 2, 4),
            ],
        }

        steps = [
            self._step(f"Define success criteria for: {focus}", "Write what done means, what can be skipped, and how quality will be judged.", 1, 4),
            *middle_steps[perception["domain"]],
            self._step(f"Review and package {final_output}", "Check the deliverable, remove avoidable errors, and prepare the handoff.", 2, 5),
        ]

        max_steps = 4 if perception["time_budget"] <= 4 else 5 if perception["time_budget"] <= 8 else 6
        if len(steps) > max_steps:
            steps = steps[: max_steps - 1] + [steps[-1]]
        return steps

    def _detect_constraints(self, goal: str, request: PlanRequest, deliverables: list[str]) -> list[str]:
        lower = goal.lower()
        constraints = []
        if request.available_hours < 3:
            constraints.append("Very limited time budget")
        if not request.deadline:
            constraints.append("Missing explicit deadline")
        if self._has_any(lower, ["github", "repository", "repo"]):
            constraints.append("Repository evidence required")
        if any(item in deliverables for item in ["report", "paper", "essay", "proposal"]):
            constraints.append("Written explanation required")
        if any(item in deliverables for item in ["demo video", "presentation", "slides"]):
            constraints.append("Presentation or demo evidence required")
        if self._has_any(lower, ["hard", "confusing", "stuck", "blocked", "unclear", "不会", "卡住"]):
            constraints.append("Blocker or uncertainty mentioned")
        return constraints

    def _extract_keywords(self, goal: str) -> list[str]:
        stop_words = {
            "the", "and", "for", "with", "this", "that", "into", "from", "have",
            "need", "want", "make", "complete", "finish", "using", "about",
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
        return keywords[:10]

    def _extract_deliverables(self, goal: str, domain: str) -> list[str]:
        lower = goal.lower()
        markers = [
            ("readme", "README"),
            ("github", "GitHub repository"),
            ("repository", "repository"),
            ("repo", "repository"),
            ("report", "report"),
            ("paper", "paper"),
            ("essay", "essay"),
            ("proposal", "proposal"),
            ("slides", "slides"),
            ("presentation", "presentation"),
            ("demo video", "demo video"),
            ("video", "video"),
            ("prototype", "prototype"),
            ("app", "app"),
            ("website", "website"),
            ("resume", "resume"),
            ("portfolio", "portfolio"),
            ("报告", "report"),
            ("论文", "paper"),
            ("演示", "demo"),
            ("视频", "video"),
            ("简历", "resume"),
            ("作品集", "portfolio"),
        ]
        deliverables = []
        for marker, name in markers:
            if self._contains_marker(lower, marker) and name not in deliverables:
                deliverables.append(name)
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
        return deliverables[:4]

    def _estimate_complexity(self, goal: str, available_hours: float, deliverables: list[str]) -> str:
        signals = len(deliverables) + len(re.findall(r"\b(and|with|plus|including)\b", goal.lower()))
        if available_hours < 3:
            return "compressed"
        if signals >= 4 or len(goal) > 160:
            return "high"
        if signals >= 2:
            return "medium"
        return "low"

    def _deadline_pressure(self, deadline: str | None, priority: str) -> str:
        if not deadline:
            return "unknown"
        lower = deadline.lower()
        if self._has_any(lower, ["today", "tonight", "asap", "urgent", "今天", "今晚", "马上"]):
            return "urgent"
        if self._has_any(lower, ["tomorrow", "this week", "week 11", "明天", "本周"]):
            return "soon"
        if priority == "high":
            return "soon"
        return "normal"

    def _allocate_effort(self, time_budget: float, weights: list[int]) -> list[float]:
        total_tenths = max(5, int(round(time_budget * 10)))
        total_weight = sum(weights)
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
            r"(?:only|have|budget|available|left)\D{0,20}(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)",
            r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\D{0,20}(?:left|available|today)",
            r"(?:只有|剩下|还有)\D{0,8}(\d+(?:\.\d+)?)\s*(?:小时|个小时)",
        ]
        for pattern in patterns:
            match = re.search(pattern, feedback)
            if match:
                return max(0.5, min(80.0, float(match.group(1))))
        return None

    def _extract_requested_addition(self, feedback: str) -> str | None:
        match = re.search(r"(?:add|include|also need|also add)\s+(.{4,80})", feedback, re.IGNORECASE)
        if not match:
            match = re.search(r"(?:加入|添加|还需要)(.{2,40})", feedback)
        if not match:
            return None
        addition = match.group(1).strip(" .。")
        if not addition:
            return None
        return addition[:80]

    def _fit_remaining_effort(self, tasks: list[dict[str, Any]], time_budget: float) -> None:
        completed_hours = sum(task["effort_hours"] for task in tasks if task["status"] == "done")
        remaining_tasks = [task for task in tasks if task["status"] != "done"]
        if not remaining_tasks:
            return

        remaining_budget = max(0.1, time_budget - completed_hours)
        budget_tenths = max(1, int(round(remaining_budget * 10)))
        if len(remaining_tasks) > budget_tenths:
            for index, task in enumerate(remaining_tasks):
                task["effort_hours"] = 0.1 if index < budget_tenths else 0.0
                if index >= budget_tenths:
                    task["schedule"] = "Backlog"
            return

        base_tenths = max(1, budget_tenths // len(remaining_tasks))
        extra_tenths = max(0, budget_tenths - base_tenths * len(remaining_tasks))

        for index, task in enumerate(remaining_tasks):
            task["effort_hours"] = round((base_tenths + (1 if index < extra_tenths else 0)) / 10, 1)

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
        }

    def _step(self, title: str, hint: str, weight: int, risk: int) -> dict[str, Any]:
        return {"title": title, "hint": hint, "weight": weight, "risk": risk}

    def _goal_focus(self, goal: str) -> str:
        cleaned = re.sub(r"\s+", " ", goal).strip()
        return cleaned if len(cleaned) <= 90 else f"{cleaned[:87]}..."

    def _schedule_label(self, index: int, total: int) -> str:
        if index == 1:
            return "Start"
        if index == total:
            return "Final check"
        return f"Block {index}"

    def _has_any(self, text: str, terms: list[str]) -> bool:
        return any(term in text for term in terms)

    def _contains_marker(self, text: str, marker: str) -> bool:
        if re.fullmatch(r"[a-z0-9 ]+", marker):
            return re.search(rf"\b{re.escape(marker)}\b", text) is not None
        return marker in text

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
