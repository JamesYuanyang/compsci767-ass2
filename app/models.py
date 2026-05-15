from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PlanRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    goal: str = Field(min_length=5, max_length=12000)
    deadline: str | None = Field(default=None, max_length=80)
    available_hours: float = Field(default=6, ge=0.5, le=80)
    priority: Literal["low", "medium", "high"] = "medium"

    @model_validator(mode="before")
    @classmethod
    def support_goal_or_brief(cls, data: Any) -> Any:
        if isinstance(data, dict) and "goal" not in data and "goal_or_brief" in data:
            data = {**data, "goal": data["goal_or_brief"]}
        return data

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, value: Any) -> str:
        priority = str(value or "medium").strip().lower()
        if priority not in {"low", "medium", "high"}:
            return "medium"
        return priority


class FeedbackRequest(BaseModel):
    session_id: str
    feedback: str = Field(min_length=3, max_length=1000)
    available_hours: float | None = Field(default=None, ge=0.5, le=80)


class StatusRequest(BaseModel):
    status: Literal["todo", "doing", "done", "blocked"]
