from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agent import TaskPlanningAgent
from app.memory import JsonMemoryStore
from app.models import FeedbackRequest, PlanRequest, StatusRequest

app = FastAPI(title="Personal Task Planning Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = TaskPlanningAgent()
memory = JsonMemoryStore()


@app.post("/api/plan")
def create_plan(request: PlanRequest):
    session = agent.create_plan(request)
    memory.add_session(session)
    return session


@app.post("/api/feedback")
def apply_feedback(request: FeedbackRequest):
    try:
        session = memory.get_session(request.session_id)
        updated = agent.apply_feedback(session, request)
        memory.update_session(request.session_id, updated)
        return updated
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/sessions/{session_id}/tasks/{task_id}")
def update_task_status(session_id: str, task_id: str, request: StatusRequest):
    try:
        session = memory.get_session(session_id)
        updated = agent.update_status(session, task_id, request.status)
        memory.update_session(session_id, updated)
        return updated
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/memory")
def get_memory():
    return memory.all()


app.mount("/", StaticFiles(directory="static", html=True), name="static")
