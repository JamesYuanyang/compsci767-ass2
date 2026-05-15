from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonMemoryStore:
    def __init__(self, path: str = "data/memory.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"sessions": []})

    def all(self) -> dict[str, Any]:
        data = self._read()
        return {**data, "summary": self._summary_from_data(data)}

    def add_session(self, session: dict[str, Any]) -> None:
        data = self._read()
        data["sessions"].insert(0, session)
        data["sessions"] = data["sessions"][:20]
        self._write(data)

    def update_session(self, session_id: str, updated: dict[str, Any]) -> None:
        data = self._read()
        for index, session in enumerate(data["sessions"]):
            if session["session_id"] == session_id:
                data["sessions"][index] = updated
                self._write(data)
                return
        raise KeyError(f"Unknown session_id: {session_id}")

    def get_session(self, session_id: str) -> dict[str, Any]:
        for session in self._read()["sessions"]:
            if session["session_id"] == session_id:
                return session
        raise KeyError(f"Unknown session_id: {session_id}")

    def latest_session(self) -> dict[str, Any]:
        sessions = self._read().get("sessions", [])
        if not sessions:
            raise KeyError("No stored sessions")
        return sessions[0]

    def summary(self, current_session_id: str | None = None) -> dict[str, Any]:
        data = self._read()
        summary = self._summary_from_data(data)
        summary["current_session"] = current_session_id
        return summary

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _summary_from_data(self, data: dict[str, Any]) -> dict[str, Any]:
        sessions = data.get("sessions", [])
        last = sessions[0].get("updated_at") or sessions[0].get("created_at") if sessions else None
        return {
            "stored_plans": len(sessions),
            "current_session": None,
            "last_saved": last,
        }
