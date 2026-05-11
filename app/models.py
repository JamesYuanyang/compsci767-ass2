from typing import Literal

from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    goal: str = Field(min_length=5, max_length=500)
    deadline: str | None = Field(default=None, max_length=80)
    available_hours: float = Field(default=6, ge=0.5, le=80)
    priority: Literal["low", "medium", "high"] = "medium"


class FeedbackRequest(BaseModel):
    session_id: str
    feedback: str = Field(min_length=3, max_length=500)


class StatusRequest(BaseModel):
    status: Literal["todo", "doing", "done", "blocked"]
