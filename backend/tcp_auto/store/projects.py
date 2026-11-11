"""File-based project store (JSON per project). Swap for PostgreSQL when hosting at scale."""

from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..models import Project, new_id

_lock = threading.Lock()


class ProjectStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get("TCP_DATA_DIR") or Path(__file__).resolve().parents[2] / "data")
        (self.root / "projects").mkdir(parents=True, exist_ok=True)
        (self.root / "drawings").mkdir(parents=True, exist_ok=True)

    def _path(self, pid: str) -> Path:
        if not pid.isalnum():
            raise KeyError(pid)
        return self.root / "projects" / f"{pid}.json"

    def drawing_path(self, pid: str) -> Path:
        if not pid.isalnum():
            raise KeyError(pid)
        return self.root / "drawings" / f"{pid}.pdf"

    def get(self, pid: str) -> Project:
        p = self._path(pid)
        if not p.exists():
            raise KeyError(pid)
        return Project.model_validate_json(p.read_text(encoding="utf-8"))

    def save(self, project: Project, change: str | None = None, user: str = "") -> Project:
        project.updated_at = datetime.now(timezone.utc)
        if change:
            project.history.append({"at": project.updated_at.isoformat(timespec="seconds"), "change": change, "user": user})
            project.history = project.history[-200:]
        with _lock:
            tmp = self._path(project.id).with_suffix(".tmp")
            tmp.write_text(project.model_dump_json(), encoding="utf-8")
            tmp.replace(self._path(project.id))
        return project

    def list(self) -> list[dict]:
        out = []
        for f in (self.root / "projects").glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            d = data.get("details", {})
            out.append({
                "id": data["id"], "project_name": d.get("project_name", ""), "address": d.get("address", ""),
                "city": d.get("city", ""), "job_number": d.get("job_number", ""), "updated_at": data.get("updated_at"),
                "has_plan": bool(data.get("plan")),
            })
        return sorted(out, key=lambda r: r["updated_at"] or "", reverse=True)

    def duplicate(self, pid: str) -> Project:
        src = self.get(pid)
        copy = src.model_copy(deep=True)
        copy.id = new_id()
        copy.details.project_name = (src.details.project_name or "Project") + " (copy)"
        copy.history = []
        if self.drawing_path(pid).exists():
            shutil.copy(self.drawing_path(pid), self.drawing_path(copy.id))
        return self.save(copy, "duplicated from " + pid)

    def delete(self, pid: str) -> None:
        self._path(pid).unlink(missing_ok=True)
        self.drawing_path(pid).unlink(missing_ok=True)
