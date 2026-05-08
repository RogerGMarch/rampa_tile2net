"""In-memory pipeline tracker — TaskInfo, PipelineStage, _tasks dict."""
from __future__ import annotations

import enum
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


class PipelineStage(enum.Enum):
    IDLE = "idle"
    GENERATING = "generating"
    INFERRING = "inferring"
    POSTPROCESSING = "postprocessing"


@dataclass
class TaskInfo:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_name: str = ""
    status: str = "queued"
    stage: PipelineStage | None = None
    progress: float = 0.0
    message: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _result: object = field(default=None, repr=False)


_tasks: dict[str, TaskInfo] = {}
_project_task: dict[str, str] = {}


def register_task(project_name: str) -> TaskInfo:
    task = TaskInfo(project_name=project_name)
    _tasks[task.task_id] = task
    _project_task[project_name] = task.task_id
    return task


def get_task(project_name: str) -> TaskInfo | None:
    tid = _project_task.get(project_name)
    if tid is None:
        return None
    return _tasks.get(tid)


def cleanup_old_tasks(max_age_hours: int = 24) -> int:
    now = datetime.now(timezone.utc)
    removed = 0
    for tid in list(_tasks):
        task = _tasks[tid]
        if task.finished_at and (now - task.finished_at).total_seconds() > max_age_hours * 3600:
            _project_task.pop(task.project_name, None)
            _tasks.pop(tid, None)
            removed += 1
    return removed
