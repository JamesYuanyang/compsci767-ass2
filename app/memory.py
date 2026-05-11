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
        return self._read()

    def add_session(self, session: dict[str, Any]) -> None:
        data = self._read()
        data["sessions"].insert(0, session)
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

    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")
