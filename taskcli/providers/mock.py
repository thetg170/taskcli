from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from taskcli.errors import ProviderError
from taskcli.models import TaskCreate, TaskUpdate, WorklogCreate, now_iso
from taskcli.provider import Provider


class MockProvider(Provider):
    name = "mock"

    def __init__(self, data_path: Path) -> None:
        self.data_path = data_path

    def create_task(self, request: TaskCreate) -> dict[str, Any]:
        data = self._read()
        if request.external_id:
            existing = self._find_by_external_id(data["tasks"], request.external_id)
            if existing:
                return {**existing, "idempotent": True}

        task_id = str(data["next_task_id"])
        data["next_task_id"] += 1
        task = {
            "id": task_id,
            "title": request.title,
            "kind": request.kind,
            "desc": request.desc,
            "sprint": request.sprint,
            "labels": request.labels,
            "estimate": request.estimate,
            "assignee": request.assignee,
            "project": request.project,
            "parent_id": request.parent_id,
            "status": "Open",
            "external_id": request.external_id,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        data["tasks"].append(task)
        self._write(data)
        return task

    def whoami(self) -> dict[str, Any]:
        return {
            "id": "P:mock",
            "assignee_id": "P:mock",
            "username": "mock",
            "full_name": "Mock User",
            "email": "mock@example.com",
        }

    def preview_whoami(self) -> dict[str, Any]:
        return {"operation": "whoami", "store": str(self.data_path)}

    def list_projects(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        projects: dict[str, dict[str, Any]] = {}
        for task in self._read()["tasks"]:
            project_id = str(task.get("project") or "")
            if not project_id:
                continue
            row = projects.setdefault(
                project_id,
                {"project_id": project_id, "project_name": project_id, "count": 0},
            )
            row["count"] += 1
        rows = list(projects.values())
        query = str(filters.get("query") or "").casefold()
        if query:
            rows = [
                row
                for row in rows
                if query in str(row.get("project_id", "")).casefold()
                or query in str(row.get("project_name", "")).casefold()
            ]
        return self._limit(rows, filters.get("limit"))

    def preview_list_projects(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {"operation": "project.list", "filters": filters, "store": str(self.data_path)}

    def list_stories(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        rows = list(self._read()["tasks"])
        project_id = filters.get("project")
        status = filters.get("status")
        query = str(filters.get("query") or "").casefold()
        if project_id:
            rows = [row for row in rows if str(row.get("project") or "") == str(project_id)]
        if status:
            rows = [row for row in rows if str(row.get("status", "")).casefold() == str(status).casefold()]
        if filters.get("today"):
            today_prefix = now_iso()[:10]
            rows = [row for row in rows if str(row.get("created_at", "")).startswith(today_prefix)]
        if query:
            rows = [
                row
                for row in rows
                if query in str(row.get("id", "")).casefold()
                or query in str(row.get("title", "")).casefold()
                or query in str(row.get("project", "")).casefold()
            ]
        return [self._story_row(row) for row in self._limit(rows, filters.get("limit"))]

    def preview_list_stories(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {"operation": "story.list", "filters": filters, "store": str(self.data_path)}

    def logtime_status(self, filters: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        date_value = str(filters.get("date") or "")
        stories = self.list_subtasks(filters)
        rows: list[dict[str, Any]] = []
        for story in stories:
            task_id = str(story.get("workflow_id") or story.get("id") or "")
            logs = [
                {
                    "id": log.get("id"),
                    "date": log.get("date"),
                    "hours": self._hours(log.get("time_spent")),
                    "action": log.get("type"),
                    "description": log.get("content"),
                    "description_html": log.get("content"),
                    "user": "Mock User",
                    "email": "mock@example.com",
                }
                for log in data["worklogs"]
                if str(log.get("task_id")) == task_id and str(log.get("date")) == date_value
            ]
            hours = sum(float(log.get("hours") or 0) for log in logs)
            workflow_id = story.get("workflow_id") or story.get("id")
            rows.append(
                {
                    **story,
                    "workflow_id": workflow_id,
                    "project_id": story.get("project_id") or story.get("project"),
                    "has_logtime": bool(logs),
                    "logtime_hours": round(hours, 2),
                    "logtimes": logs,
                }
            )

        if filters.get("missing_only"):
            rows = [row for row in rows if not row["has_logtime"]]

        return {
            "date": date_value,
            "total_tasks": len(stories),
            "returned_tasks": len(rows),
            "logged_tasks": sum(1 for row in rows if row["has_logtime"]),
            "missing_tasks": sum(1 for row in rows if not row["has_logtime"]),
            "tasks": rows,
        }

    def preview_logtime_status(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {"operation": "logtime.status", "filters": filters, "store": str(self.data_path)}

    def list_logtime(self, task_id: str, filters: dict[str, Any]) -> dict[str, Any]:
        date_value = str(filters.get("date") or "")
        logs = []
        for log in self._read()["worklogs"]:
            if str(log.get("task_id")) != str(task_id):
                continue
            if date_value and str(log.get("date")) != date_value:
                continue
            logs.append(
                {
                    "id": log.get("id"),
                    "date": log.get("date"),
                    "hours": self._hours(log.get("time_spent")),
                    "action": log.get("type"),
                    "description": log.get("content"),
                    "description_html": log.get("content"),
                    "user": "Mock User",
                    "email": "mock@example.com",
                }
            )
        logs = self._limit(logs, filters.get("limit"))
        return {
            "task_id": task_id,
            "date": date_value or None,
            "total_logs": len(logs),
            "total_hours": round(sum(float(log.get("hours") or 0) for log in logs), 2),
            "logtimes": logs,
        }

    def preview_list_logtime(self, task_id: str, filters: dict[str, Any]) -> dict[str, Any]:
        return {"operation": "logtime.list", "task_id": task_id, "filters": filters, "store": str(self.data_path)}

    def list_tasks(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        tasks = list(self._read()["tasks"])
        parent_id = filters.get("parent_id")
        project_id = filters.get("project")
        sprint = filters.get("sprint")
        status = filters.get("status")
        query = str(filters.get("query") or "").casefold()
        mine = filters.get("mine")
        related = filters.get("related")
        assignee = filters.get("assignee")
        today = filters.get("today")
        if parent_id:
            tasks = [task for task in tasks if str(task.get("parent_id") or "") == str(parent_id)]
        if project_id:
            tasks = [task for task in tasks if str(task.get("project") or "") == str(project_id)]
        if sprint:
            tasks = [task for task in tasks if task.get("sprint") == sprint]
        if status:
            tasks = [task for task in tasks if str(task.get("status", "")).casefold() == str(status).casefold()]
        if query:
            tasks = [
                task
                for task in tasks
                if query in str(task.get("id", "")).casefold()
                or query in str(task.get("title", "")).casefold()
                or query in str(task.get("project", "")).casefold()
            ]
        if (mine or related) and assignee:
            tasks = [task for task in tasks if task.get("assignee") == assignee]
        if today:
            today_prefix = now_iso()[:10]
            tasks = [task for task in tasks if str(task.get("created_at", "")).startswith(today_prefix)]
        return self._limit(tasks, filters.get("limit"))

    def preview_list_tasks(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {"operation": "task.list", "filters": filters, "store": str(self.data_path)}

    def list_subtasks(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        subtasks = [task for task in self.list_tasks(filters) if task.get("kind") == "subtask"]
        return self._limit(subtasks, filters.get("limit"))

    def preview_list_subtasks(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {"operation": "subtask.list", "filters": filters, "store": str(self.data_path)}

    def show_task(self, task_id: str) -> dict[str, Any]:
        data = self._read()
        task = self._find_task(data, task_id)
        logs = [log for log in data["worklogs"] if log["task_id"] == task_id]
        return {**task, "worklogs": logs}

    def update_task(self, task_id: str, request: TaskUpdate) -> dict[str, Any]:
        data = self._read()
        task = self._find_task(data, task_id)
        task.update(request.changes())
        task["updated_at"] = now_iso()
        self._write(data)
        return task

    def add_worklog(self, request: WorklogCreate) -> dict[str, Any]:
        data = self._read()
        self._find_task(data, request.task_id)
        if request.external_id:
            existing = self._find_by_external_id(data["worklogs"], request.external_id)
            if existing:
                return {**existing, "idempotent": True}

        log_id = str(data["next_worklog_id"])
        data["next_worklog_id"] += 1
        worklog = {
            "id": log_id,
            "task_id": request.task_id,
            "content": request.content,
            "time_spent": request.time_spent,
            "type": request.log_type,
            "date": request.resolved_date(),
            "external_id": request.external_id,
            "created_at": now_iso(),
        }
        data["worklogs"].append(worklog)
        self._write(data)
        return worklog

    def _read(self) -> dict[str, Any]:
        if not self.data_path.exists():
            return {"next_task_id": 1, "next_worklog_id": 1, "tasks": [], "worklogs": []}
        return json.loads(self.data_path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _find_task(self, data: dict[str, Any], task_id: str) -> dict[str, Any]:
        for task in data["tasks"]:
            if task["id"] == task_id:
                return task
        raise ProviderError("Task not found.", {"task_id": task_id})

    def _find_by_external_id(self, rows: list[dict[str, Any]], external_id: str) -> dict[str, Any] | None:
        for row in rows:
            if row.get("external_id") == external_id:
                return row
        return None

    def _story_row(self, task: dict[str, Any]) -> dict[str, Any]:
        return {
            "workflow_id": task.get("id"),
            "title": task.get("title"),
            "project_id": task.get("project"),
            "project_name": task.get("project"),
            "status": task.get("status"),
            "start": task.get("created_at"),
            "end": None,
        }

    def _limit(self, rows: list[dict[str, Any]], limit: object | None) -> list[dict[str, Any]]:
        if limit is None or limit == "":
            return rows
        size = int(limit)
        if size <= 0:
            return []
        return rows[:size]

    def _hours(self, value: object | None) -> float:
        if not value:
            return 0
        text = str(value).strip().lower()
        if text.endswith("h"):
            return float(text[:-1])
        if text.endswith("m"):
            return round(float(text[:-1]) / 60, 2)
        return float(text)
