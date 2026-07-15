from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any


@dataclass
class TaskCreate:
    title: str
    kind: str = "task"
    desc: str = ""
    sprint: str | None = None
    labels: list[str] = field(default_factory=list)
    estimate: str | None = None
    assignee: str | None = None
    project: str | None = None
    parent_id: str | None = None
    external_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "kind": self.kind,
            "desc": self.desc,
            "sprint": self.sprint,
            "labels": self.labels,
            "estimate": self.estimate,
            "assignee": self.assignee,
            "project": self.project,
            "parent_id": self.parent_id,
            "external_id": self.external_id,
        }


@dataclass
class TaskUpdate:
    status: str | None = None
    title: str | None = None
    desc: str | None = None
    sprint: str | None = None
    labels: list[str] | None = None
    estimate: str | None = None
    assignee: str | None = None
    progress: str | None = None

    def changes(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "status": self.status,
                "title": self.title,
                "desc": self.desc,
                "sprint": self.sprint,
                "labels": self.labels,
                "estimate": self.estimate,
                "assignee": self.assignee,
                "progress": self.progress,
            }.items()
            if value is not None
        }


@dataclass
class WorklogCreate:
    task_id: str
    content: str
    time_spent: str | None = None
    log_type: str = "progress"
    log_date: str = "today"
    external_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "content": self.content,
            "time_spent": self.time_spent,
            "type": self.log_type,
            "date": self.resolved_date(),
            "external_id": self.external_id,
        }

    def resolved_date(self) -> str:
        return resolve_date_token(self.log_date)


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def resolve_date_token(value: str | None) -> str:
    if not value or value == "today":
        return date.today().isoformat()
    if value == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    return value


def normalize_progress_value(value: object) -> str:
    raw_value = str(value).strip().removesuffix("%").strip()
    progress = int(raw_value)
    if progress < 0 or progress > 100:
        raise ValueError("progress must be from 0 to 100")
    return f"{progress}%"
