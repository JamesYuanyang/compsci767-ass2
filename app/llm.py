from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


class OllamaBriefAnalyzer:
    """Optional local LLM analyzer. Returns None when Ollama is unavailable."""

    def __init__(self) -> None:
        self.provider = os.getenv("LLM_PROVIDER", "ollama").lower()
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        self.model = os.getenv("LLM_MODEL", "llama3.2:1b")
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "45"))
        self.health_timeout = float(os.getenv("LLM_HEALTH_TIMEOUT_SECONDS", "1.5"))

    def analyze(self, brief: str) -> dict[str, Any] | None:
        if self.provider in {"none", "off", "false", "0"}:
            return None
        if self.provider != "ollama":
            return None
        if not self._is_available():
            return None

        prompt = self._build_prompt(brief)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 1200},
        }
        try:
            response = self._post_json("/api/generate", payload, self.timeout)
            raw = response.get("response", "")
            parsed = self._extract_json(raw)
            if not parsed:
                return None
            normalized = self._normalize(parsed)
            normalized["source"] = f"ollama:{self.model}"
            return normalized
        except (OSError, TimeoutError, ValueError, urllib.error.URLError):
            return None

    def _is_available(self) -> bool:
        try:
            self._get_json("/api/tags", self.health_timeout)
            return True
        except (OSError, TimeoutError, urllib.error.URLError):
            return False

    def _build_prompt(self, brief: str) -> str:
        clipped = brief.strip()[:7000]
        return f"""
Analyze this student assignment brief or goal. Return JSON only, with no markdown.

Schema:
{{
  "domain": "student_assignment | data_analysis_assignment | software_project | study_plan | research_project | writing_project | career_goal | habit_goal | event_plan | creative_project | general_goal",
  "input_type": "assignment_brief | goal_description",
  "deliverables": ["short noun phrase"],
  "methods": ["specific required method or technique"],
  "sections": ["named part or requirement"],
  "tasks": [
    {{"title": "specific task", "hint": "concrete implementation hint", "weight": 1, "risk": 1}}
  ],
  "recommended_hours": 1,
  "risks": ["specific risk or ambiguity"]
}}

Rules:
- If the brief asks for statistics, regression, testing, metrics, datasets, or quantitative interpretation, use domain "data_analysis_assignment".
- Extract concrete methods such as descriptive statistics, linear regression, R2, MAE, RMSE, normality check, t-test, ANOVA, Kruskal-Wallis, conceptual model, external data collection.
- Do not include README, GitHub, or demo tasks unless the brief explicitly asks for them.
- Produce 5 to 8 tasks. Each task title must mention the actual assignment content.
- Weight and risk must be integers from 1 to 5.
- recommended_hours should be realistic for a student completing the whole assignment.

Brief:
{clipped}
""".strip()

    def _get_json(self, path: str, timeout: float) -> dict[str, Any]:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _extract_json(self, text: str) -> dict[str, Any] | None:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        return json.loads(cleaned[start : end + 1])

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        allowed_domains = {
            "student_assignment",
            "data_analysis_assignment",
            "software_project",
            "study_plan",
            "research_project",
            "writing_project",
            "career_goal",
            "habit_goal",
            "event_plan",
            "creative_project",
            "general_goal",
        }
        domain = str(data.get("domain", "general_goal"))
        if domain not in allowed_domains:
            domain = "general_goal"

        tasks = []
        for item in data.get("tasks", [])[:8]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            hint = str(item.get("hint", "")).strip()
            if not title:
                continue
            tasks.append(
                {
                    "title": title[:140],
                    "hint": (hint or "Complete the smallest useful version first.")[:180],
                    "weight": self._clamp_int(item.get("weight", 2), 1, 5),
                    "risk": self._clamp_int(item.get("risk", 3), 1, 5),
                }
            )

        return {
            "domain": domain,
            "input_type": str(data.get("input_type", "assignment_brief")),
            "deliverables": self._string_list(data.get("deliverables", []), 8),
            "methods": self._string_list(data.get("methods", []), 12),
            "sections": self._string_list(data.get("sections", []), 10),
            "tasks": tasks,
            "recommended_hours": self._clamp_float(data.get("recommended_hours", 0), 0, 80),
            "risks": self._string_list(data.get("risks", []), 10),
        }

    def _string_list(self, value: Any, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        result = []
        for item in value:
            text = str(item).strip()
            if text and text not in result:
                result.append(text[:120])
        return result[:limit]

    def _clamp_int(self, value: Any, lower: int, upper: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = lower
        return max(lower, min(upper, number))

    def _clamp_float(self, value: Any, lower: float, upper: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = lower
        return max(lower, min(upper, number))
