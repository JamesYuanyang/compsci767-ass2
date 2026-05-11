from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timezone
from typing import Any

from app.llm import OllamaBriefAnalyzer
from app.models import FeedbackRequest, PlanRequest


class TaskPlanningAgent:
    """Rule-based planning agent with perception, decision, action, memory, and safety outputs."""

    def __init__(self, analyzer: OllamaBriefAnalyzer | None = None) -> None:
        self.analyzer = analyzer or OllamaBriefAnalyzer()

    def create_plan(self, request: PlanRequest) -> dict[str, Any]:
        llm_analysis = self.analyzer.analyze(request.goal)
        perception = self._perceive(request, llm_analysis)
        decisions = self._decide(perception, llm_analysis)
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
            "llm_analysis": llm_analysis,
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

        if any(term in lower for term in ["less time", "busy", "only", "reduce", "shorter", "too much"]):
            self._fit_remaining_effort(tasks, session["perception"]["time_budget"])
            agent_log.append("Action: compressed remaining tasks to fit the revised time budget.")

        if any(term in lower for term in ["hard", "confusing", "stuck", "blocked", "unclear"]):
            for task in tasks:
                if task["status"] == "todo":
                    task["priority_score"] += 1
                    task["support_hint"] = "Turn this into one 25-minute attempt, then write the exact question or blocker."
            agent_log.append("Action: raised unresolved task priority and added blocker-focused hints.")

        if any(term in lower for term in ["specific", "detail", "too generic"]):
            for task in tasks:
                if task["status"] == "todo":
                    task["support_hint"] = "Define one visible output for this task before starting, then stop when that output exists."
            agent_log.append("Action: made the remaining task hints more concrete.")

        if any(term in lower for term in ["tomorrow", "later", "delay", "extend"]):
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

    def _perceive(self, request: PlanRequest, llm_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
        goal = request.goal.strip()
        rule_domain = self._classify_domain(goal)
        llm_domain = llm_analysis.get("domain") if llm_analysis else None
        domain = llm_domain or rule_domain
        if rule_domain == "student_assignment" and domain == "general_goal":
            domain = rule_domain
        deliverables = self._merge_lists(
            llm_analysis.get("deliverables", []) if llm_analysis else [],
            self._extract_deliverables(goal, domain),
        )
        methods = self._merge_lists(
            llm_analysis.get("methods", []) if llm_analysis else [],
            self._extract_methods(goal),
        )
        sections = self._merge_lists(
            self._extract_sections(goal),
            llm_analysis.get("sections", []) if llm_analysis else [],
        )
        input_type = (llm_analysis or {}).get("input_type") or self._detect_input_type(goal)
        deadline = self._deadline_details(request.deadline, request.priority)
        llm_recommended_hours = (llm_analysis or {}).get("recommended_hours") or 0
        recommended_hours = max(
            float(llm_recommended_hours),
            self._estimate_recommended_hours(
            goal=goal,
            domain=domain,
            deliverables=deliverables,
            methods=methods,
            input_type=input_type,
            priority=request.priority,
            available_hours=request.available_hours,
            )
        )
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
            "time_budget": request.available_hours,
            "recommended_hours": recommended_hours,
            "urgency": request.priority,
            "complexity": self._estimate_complexity(goal, request.available_hours, deliverables),
            "constraints": self._detect_constraints(goal, request, deliverables),
        }

    def _decide(self, perception: dict[str, Any], llm_analysis: dict[str, Any] | None = None) -> dict[str, Any]:
        steps = self._build_steps(perception, llm_analysis)
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
        recommended_hours = perception.get("recommended_hours", total_hours)
        hours_remaining = perception.get("deadline_hours_remaining")
        messages = []
        warnings = []

        if not perception.get("deadline_detected"):
            warnings.append("No explicit deadline was provided.")
            messages.append("Safety: no deadline detected, so the plan includes a final review task.")

        if perception.get("deadline_pressure") == "urgent" and total_hours > 4:
            warnings.append("Urgent deadline with a large workload.")
            messages.append("Safety: urgent deadline detected; keep only the highest-value output if time slips.")

        if recommended_hours > perception["time_budget"] + 0.25:
            warnings.append("Available hours are lower than the recommended workload.")
            messages.append(
                f"Safety: this looks closer to {recommended_hours:g} hours of work; increase available hours, extend the deadline, or reduce scope."
            )

        if hours_remaining is not None:
            if hours_remaining <= 0:
                warnings.append("The selected deadline has already passed or has no remaining time today.")
                messages.append("Safety: choose a later deadline or switch to an emergency minimum-scope submission.")
            elif perception["time_budget"] > hours_remaining + 0.25:
                warnings.append("Available hours exceed the calendar time remaining before the deadline.")
                messages.append(
                    f"Safety: only about {hours_remaining:g} hours remain before the selected deadline; lower available hours or extend the deadline."
                )
            if recommended_hours > hours_remaining + 0.25:
                warnings.append("Recommended workload does not fit before the selected deadline.")
                messages.append(
                    f"Safety: recommended work is about {recommended_hours:g} hours but only {hours_remaining:g} hours remain before the deadline."
                )

        if total_hours > perception["time_budget"]:
            warnings.append("Estimated work exceeds available time.")
            messages.append("Safety: estimated effort is above the time budget; reduce scope or increase available hours.")
        else:
            messages.append("Safety: estimated effort fits within the available time budget.")

        if len(actions["tasks"]) > 8:
            warnings.append("Plan has too many tasks for a short prototype workflow.")

        return {
            "total_estimated_hours": total_hours,
            "recommended_hours": recommended_hours,
            "hours_remaining_before_deadline": hours_remaining,
            "warnings": warnings,
            "messages": messages,
        }

    def _classify_domain(self, goal: str) -> str:
        lower = goal.lower()
        if self._looks_like_assignment_brief(lower) or self._has_any(lower, ["assignment", "coursework", "course", "homework", "rubric", "submit", "submission", "criteria", "marks", "compsci", "ass2"]):
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
        focus = self._goal_focus(perception["raw_goal"])
        deliverables = perception["deliverables"]
        final_output = ", ".join(deliverables) if deliverables else "the final output"
        if perception.get("input_type") == "assignment_brief":
            focus = "copied assignment requirements"

        if perception.get("input_type") == "assignment_brief":
            return self._assignment_brief_steps(perception, llm_analysis)

        llm_steps = self._llm_steps(llm_analysis, perception["raw_goal"])
        if llm_steps:
            return llm_steps

        if perception["time_budget"] <= 2:
            return [
                self._step(f"Define the minimum acceptable result for: {focus}", "Write the exact finish line in one sentence.", 1, 3),
                self._step("Complete the highest-impact work item", "Choose the one action that makes the goal visibly closer to done.", 3, 4),
                self._step(f"Check and package {final_output}", "Review only the essentials: correctness, completeness, and delivery format.", 1, 4),
            ]

        middle_steps = {
            "student_assignment": self._assignment_middle_steps(perception),
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

    def _assignment_brief_steps(
        self, perception: dict[str, Any], llm_analysis: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        sections = perception.get("sections", [])
        deliverables = perception.get("deliverables", [])
        final_output = ", ".join(deliverables) if deliverables else "submission package"
        steps = [
            self._step(
                "Convert the brief into a checklist",
                "List each required part, question, deliverable, word limit, mark value, and submission rule before starting.",
                2,
                4,
            )
        ]

        for section in sections[:5]:
            steps.append(
                self._step(
                    f"Complete {section}",
                    "Answer every sub-requirement in this section and keep notes on assumptions, evidence, and unfinished details.",
                    3,
                    4,
                )
            )

        if len(steps) == 1:
            llm_steps = self._llm_steps(llm_analysis, perception["raw_goal"])
            if llm_steps:
                steps.extend(llm_steps[:5])
            else:
                steps.extend(self._assignment_middle_steps(perception))

        steps.extend(
            [
                self._step(
                    "Draft the final responses in submission order",
                    "Put answers under the same headings as the brief so every requirement is easy to mark.",
                    3,
                    4,
                ),
                self._step(
                    f"Review and package {final_output}",
                    "Check every checklist item, fix gaps, confirm formatting, and prepare the final upload.",
                    2,
                    5,
                ),
            ]
        )
        return steps[:8]

    def _assignment_middle_steps(self, perception: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._step(
                "Complete the main assignment work",
                "Work through the brief section by section, producing the required answers, analysis, artefacts, or evidence.",
                4,
                5,
            ),
            self._step(
                "Prepare supporting evidence and final write-up",
                "Convert working notes into clear final responses and attach any required files, tables, figures, or appendices.",
                3,
                4,
            ),
            self._step(
                "Check against the marking criteria",
                "Compare the final work with the rubric or marks allocation and fix the highest-value missing items first.",
                2,
                5,
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
        if self._has_any(lower, ["github", "repository", "repo"]):
            constraints.append("Repository evidence required")
        if any(item in deliverables for item in ["report", "paper", "essay", "proposal"]):
            constraints.append("Written explanation required")
        if any(item in deliverables for item in ["demo video", "presentation", "slides"]):
            constraints.append("Presentation or demo evidence required")
        if self._has_any(lower, ["hard", "confusing", "stuck", "blocked", "unclear"]):
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
            ("source code", "source code"),
            ("code", "code"),
            ("report", "report"),
            ("paper", "paper"),
            ("essay", "essay"),
            ("proposal", "proposal"),
            ("slides", "slides"),
            ("presentation", "presentation"),
            ("screenshot", "screenshots"),
            ("screenshots", "screenshots"),
            ("demo video", "demo video"),
            ("video", "video"),
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
        return deliverables[:6]

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
        signals = [
            "assignment", "coursework", "rubric", "submission", "submit", "deliverable",
            "marking", "criteria", "marks", "grade", "deadline", "late penalty",
            "requirements", "learning outcome",
        ]
        return sum(1 for signal in signals if signal in lower_goal) >= 2

    def _extract_methods(self, goal: str) -> list[str]:
        lower = goal.lower()
        markers = [
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
        return methods

    def _extract_sections(self, goal: str) -> list[str]:
        sections = []
        for match in re.finditer(r"\b(part\s+[a-z])\s*:\s*([^.\n]{0,110})", goal, flags=re.IGNORECASE):
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
            "student_assignment": 7.0,
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
        base_hours += min(3.0, len(deliverables) * 0.5)
        base_hours += min(4.0, len(methods) * 0.4)
        if input_type == "assignment_brief":
            base_hours += 1.5
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
        ]
        for pattern in patterns:
            match = re.search(pattern, feedback)
            if match:
                return max(0.5, min(80.0, float(match.group(1))))
        return None

    def _extract_requested_addition(self, feedback: str) -> str | None:
        match = re.search(r"(?:add|include|also need|also add)\s+(.{4,80})", feedback, re.IGNORECASE)
        if not match:
            return None
        addition = match.group(1).strip(" .")
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

    def _merge_lists(self, first: list[Any], second: list[Any]) -> list[str]:
        merged = []
        for item in [*first, *second]:
            text = str(item).strip()
            if text and text not in merged:
                merged.append(text)
        return merged[:12]

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
        }
        title_words = set(re.findall(r"[a-zA-Z][a-zA-Z0-9-]{3,}", title.lower()))
        return bool((title_words & brief_words) or (title_words & generic_words))

    def _contains_marker(self, text: str, marker: str) -> bool:
        if re.fullmatch(r"[a-z0-9 ]+", marker):
            return re.search(rf"\b{re.escape(marker)}\b", text) is not None
        return marker in text

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
