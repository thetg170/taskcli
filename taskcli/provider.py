from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import TaskCreate, TaskUpdate, WorklogCreate


class Provider(ABC):
    name: str

    @abstractmethod
    def create_task(self, request: TaskCreate) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_tasks(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def show_task(self, task_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def update_task(self, task_id: str, request: TaskUpdate) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def add_worklog(self, request: WorklogCreate) -> dict[str, Any]:
        raise NotImplementedError

    def whoami(self) -> dict[str, Any]:
        return {}

    def list_projects(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def list_stories(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return self.list_tasks(filters)

    def list_subtasks(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        return self.list_tasks(filters)

    def logtime_status(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {"date": filters.get("date"), "tasks": []}

    def list_logtime(self, task_id: str, filters: dict[str, Any]) -> dict[str, Any]:
        return {"task_id": task_id, "logtimes": []}

    def preview_list_projects(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {"operation": "project.list", "filters": filters}

    def preview_list_stories(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {"operation": "story.list", "filters": filters}

    def preview_list_tasks(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {"operation": "task.list", "filters": filters}

    def preview_list_subtasks(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {"operation": "subtask.list", "filters": filters}

    def preview_logtime_status(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {"operation": "logtime.status", "filters": filters}

    def preview_list_logtime(self, task_id: str, filters: dict[str, Any]) -> dict[str, Any]:
        return {"operation": "logtime.list", "task_id": task_id, "filters": filters}

    def preview_whoami(self) -> dict[str, Any]:
        return {"operation": "whoami"}

    def preview_create_task(self, request: TaskCreate) -> dict[str, Any]:
        return request.to_dict()

    def preview_update_task(self, task_id: str, request: TaskUpdate) -> dict[str, Any]:
        return {"id": task_id, "changes": request.changes()}

    def preview_worklog(self, request: WorklogCreate) -> dict[str, Any]:
        return request.to_dict()
