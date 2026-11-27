from __future__ import annotations

import json
import os
import re
import time
from calendar import monthrange
from collections import deque
from datetime import date as date_cls, timedelta
from html import unescape
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from beca_work.actions import (
    MY_WORK_COUNT_BY_PROJECT_URL,
    SAVE_FORM_URL,
    BecaResponseError,
    build_child_work_context,
    check_apply_sla_in_project,
    check_over_logtime,
    create_work_id_temp,
    default_field_value,
    extract_created_work_id,
    find_status,
    get_api_setting,
    get_current_user,
    get_format_workflow,
    get_logtime,
    get_next_statuses,
    get_project_id,
    get_project_works,
    get_task_resources,
    task_resource_request,
    get_statuses_by_project,
    get_department_leave_calendar,
    get_department_timesheet_report,
    get_recent_activity,
    get_timesheet_report,
    get_work_children,
    get_work_detail,
    get_work_history,
    get_work_in_process,
    html_description,
    insert_status_history,
    insert_work,
    normalize_project,
    normalize_work,
    object_to_fields,
    parse_leave_days,
    person_ref,
    require_work_detail,
    update_work_field,
)
from beca_work.client import BecaClient
from taskcli.config import Config
from taskcli.errors import AuthError, NetworkError, ProviderError, RateLimitError
from taskcli.models import TaskCreate, TaskUpdate, WorklogCreate, normalize_progress_value, task_matches_dates
from taskcli.provider import Provider

WORK_SCOPE_TYPES = {
    "active": ("Xử lý",),
    "completed": ("Việc đã xử lý",),
    "all": ("Xử lý", "Việc đã xử lý"),
}


class BecaProvider(Provider):
    name = "beca"

    def __init__(self, config: Config) -> None:
        self.config = config
        self.client: BecaClient | None = None
        self._user: dict[str, Any] | None = None

    def _current_user(self) -> dict[str, Any]:
        if self._user is None:
            self._user = self._read_call(get_current_user, self._client())
        return self._user

    def whoami(self) -> dict[str, Any]:
        user = self._current_user()
        assignee_id = person_ref(user.get("id"))
        return {
            "id": assignee_id,
            "assignee_id": assignee_id,
            "username": user.get("accountName") or user.get("userName") or user.get("user"),
            "full_name": user.get("fullName") or user.get("name"),
            "email": user.get("email"),
        }

    def preview_whoami(self) -> dict[str, Any]:
        return {
            "method": "GET",
            "endpoint": "Work_GetInfLogin?IsMobile=false",
            "uses_credentials_from": [".env", "environment", "config"],
        }

    def create_task(self, request: TaskCreate) -> dict[str, Any]:
        context = self._build_task_create_context(request)
        parent_id = context["parent_id"]
        child_context = context["child_context"]
        sla_result = self._call(
            check_apply_sla_in_project,
            self._client(),
            str(child_context["metadata"]["project_id"]),
            str(child_context["metadata"]["status_id"]),
            str(child_context["metadata"]["priority"]),
            parent_id,
        )
        if response_data(sla_result) == "NotAllow":
            raise ProviderError("Beca SLA rule rejected this task.", {"parent_id": parent_id})

        temp_id = self._call(create_work_id_temp, self._client())
        insert_result = self._call(
            insert_work,
            self._client(),
            child_context["payload"],
            str(child_context["metadata"]["form_id"]),
            str(child_context["metadata"]["step_id"]),
            temp_id,
            parent_id,
        )
        created_id = extract_created_work_id(insert_result)
        children = self._call(get_work_children, self._client(), parent_id)

        return {
            "id": created_id,
            "title": request.title,
            "kind": request.kind,
            "status": child_context["metadata"]["status_name"],
            "project": child_context["metadata"]["project_id"],
            "parent_id": parent_id,
            "assignee": child_context["metadata"]["assignee"],
            "external_id": request.external_id,
            "raw": insert_result,
            "children_after": [normalize_work(child) for child in children],
        }

    def preview_create_task(self, request: TaskCreate) -> dict[str, Any]:
        context = self._build_task_create_context(request)
        child_context = context["child_context"]
        form_id = str(child_context["metadata"]["form_id"])
        step_id = str(child_context["metadata"]["step_id"])
        return {
            "method": "POST",
            "endpoint": "Work_InsertWork",
            "query": {
                "urlStr": f"/api/apikey/userWorkflows/{form_id}/addDynamicUserWorkflow/{step_id}",
                "apiId": form_id,
                "workIdTemp": "<created by Work_CreateWorkIdTemp>",
            },
            "preflight": [
                "Work_DetailInfo",
                "Work_GetWorkByCode",
                "Work_GetApiSetting",
                "Eoffice_GetData?urlStr=getFormatWorkflow",
                "Work_GetWorkChild",
                "Work_CheckApplySLAInProject",
                "Work_CreateWorkIdTemp",
            ],
            "metadata": child_context["metadata"],
            "payload": child_context["payload"],
        }

    def _build_task_create_context(self, request: TaskCreate) -> dict[str, Any]:
        parent_id = request.parent_id or self.config.parent_id
        if not parent_id:
            raise ProviderError("Beca task creation requires a parent work id.", {"field": "parent_id"})

        with patched_env(
            {
                "WORKFLOW_ID": parent_id,
                "LOG_PROJECT_ID": request.project or self.config.project or "",
                "CHILD_TITLE": request.title,
                "CHILD_DESCRIPTION": request.desc,
                "CHILD_STATUS": "Open",
                "CHILD_PRIORITY": "Bình thường",
                "CHILD_ASSIGNEE": request.assignee or self.config.assignee or "",
                "CHILD_START": "",
                "CHILD_END": "",
                "CHILD_PROGRESS": "",
            }
        ):
            child_context = self._call(build_child_work_context, self._client(), parent_id, request.title)
        return {"parent_id": parent_id, "child_context": child_context}

    def list_projects(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        project_type = str(filters.get("type") or "Việc đã xử lý")
        data = self._call(
            self._client().request_json,
            f"{MY_WORK_COUNT_BY_PROJECT_URL}?{urlencode({'type': project_type})}",
            print_body=False,
        )
        projects = data if isinstance(data, list) else []
        rows = [compact_project(normalize_project(project)) for project in projects]
        query = str(filters.get("query") or "").strip().casefold()
        if query:
            rows = [
                row
                for row in rows
                if query in str(row.get("project_id", "")).casefold()
                or query in str(row.get("project_name", "")).casefold()
            ]
        return limit_rows(rows, filters.get("limit"))

    def preview_list_projects(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {
            "method": "GET",
            "endpoint": "Work_MyWorkCountByProject",
            "query": {"type": filters.get("type") or "Việc đã xử lý"},
            "filters": filters,
        }

    def _work_pages(self, work_type: str, row_number: int = 100) -> Iterator[dict[str, Any]]:
        seen: set[str] = set()
        page_number = 1
        while True:
            page = self._read_call(
                get_work_in_process, self._client(), False,
                page_number=page_number, row_number=row_number, work_type=work_type,
            )
            count = 0
            for work in page:
                work_id = str(normalize_work(work)["workflow_id"])
                if work_id and work_id not in seen:
                    seen.add(work_id)
                    count += 1
                    yield work
            if len(page) < row_number:
                break
            if not count:
                raise ProviderError("Beca pagination returned a repeated page.", {"page": page_number, "type": work_type})
            page_number += 1

    def list_stories(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        row_number = int(filters.get("row_number") or 100)
        rows = [normalize_work(work) for work in self._work_pages("Xử lý", row_number)]
        project_id = str(filters.get("project") or self.config.project or "").strip()
        status = str(filters.get("status") or "").strip().casefold()
        query = str(filters.get("query") or "").strip().casefold()
        if project_id:
            rows = [row for row in rows if str(row.get("project_id") or "").strip() == project_id]
        if status:
            rows = [row for row in rows if str(row.get("status") or "").strip().casefold() == status]
        if filters.get("today"):
            today = time.strftime("%Y-%m-%d")
            rows = [row for row in rows if str(row.get("start", "")).startswith(today)]
        if query:
            rows = [
                row
                for row in rows
                if query in str(row.get("workflow_id", "")).casefold()
                or query in str(row.get("title", "")).casefold()
                or query in str(row.get("project_name", "")).casefold()
            ]
        return limit_rows(rows, filters.get("limit"))

    def preview_list_stories(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {
            "method": "GET",
            "endpoint": "Work_GetWorkInProcess",
            "query": {
                "type": "Xử lý",
                "isComplete": 1,
                "layout": 2,
                "pageNumber": 1,
                "rowNumber": filters.get("row_number") or 100,
            },
            "filters": filters,
        }

    def list_tasks(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        limit = filters.get("limit")
        if limit is not None and int(limit) <= 0:
            return []
        filters = self._with_related_user(filters)
        parent_id = str(filters.get("parent_id") or "").strip()
        if filters.get("scope") and not parent_id:
            return self._list_scoped_tasks(filters)
        # Child filters must not be applied to ancestors: a child can start
        # today even when its parent started months ago.
        story_filters = {**filters, "limit": None, "status": None, "query": None,
                         "related": False, "mine": False, "today": False}
        stories = [{"workflow_id": parent_id}] if parent_id else self.list_stories(story_filters)
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        child_filters = {**filters, "limit": None}
        for story in stories:
            story_id = str(story.get("workflow_id") or "").strip()
            if not story_id:
                continue
            children = self._iter_descendants(story_id) if filters.get("recursive") else self._child_rows(story_id)
            for row in children:
                work_id = str(row.get("workflow_id") or "")
                if work_id and work_id not in seen and filter_task_rows([row], child_filters):
                    seen.add(work_id)
                    rows.append(row)
                    if limit is not None and len(rows) >= int(limit):
                        return rows
        return rows

    def _scope_candidates(self, filters: dict[str, Any]) -> Iterator[dict[str, Any]]:
        scope = filters["scope"]
        project = str(filters.get("project") or "").strip()
        if scope == "project":
            if not project:
                raise ProviderError("Project scope requires a project id.")
            for work in self._read_call(get_project_works, self._client(), project):
                yield child_task_row(work, str(work.get("parentId") or ""))
            return
        if scope not in WORK_SCOPE_TYPES:
            raise ProviderError("Unsupported work scope.", {"scope": scope})
        roots: list[str] = []
        seen: set[str] = set()
        for work_type in WORK_SCOPE_TYPES[scope]:
            for work in self._work_pages(work_type):
                row = child_task_row(work, str(work.get("parentId") or ""))
                workflow_id = row["workflow_id"]
                if not workflow_id or workflow_id in seen:
                    continue
                if project and row["project_id"] != project:
                    continue
                seen.add(workflow_id)
                roots.append(workflow_id)
                yield row
        # Current and processed lists can overlap and can already contain
        # descendants. Expand each parent only once across both sources.
        expanded: set[str] = set()
        queue = deque(roots)
        while queue:
            root = queue.popleft()
            if root in expanded:
                continue
            expanded.add(root)
            for row in self._child_rows(root):
                workflow_id = row["workflow_id"]
                if not workflow_id:
                    continue
                if workflow_id not in seen:
                    seen.add(workflow_id)
                    yield row
                if filters.get("recursive") and workflow_id not in expanded:
                    queue.append(workflow_id)

    def _list_scoped_tasks(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        results = []
        seen: set[str] = set()
        basic_filters = {**filters, "mine": False, "related": False, "limit": None}
        full_filters = {**filters, "limit": None}
        for row in self._scope_candidates(filters):
            workflow_id = row["workflow_id"]
            if not workflow_id or workflow_id in seen:
                continue
            seen.add(workflow_id)
            if not filter_task_rows([row], basic_filters):
                continue
            # Flat lists omit userPartner, so never infer assignee from
            # isMyWork, userIds, or related participants.
            if (filters.get("mine") or filters.get("related")) and not (
                row["related_user_ids"] or row["related_user_emails"]
            ):
                detail = self._read_call(get_work_detail, self._client(), workflow_id, False)
                if not isinstance(detail, dict) or not detail.get("userWorkflowId"):
                    raise ProviderError("Beca did not return task detail.", {"task_id": workflow_id})
                row = child_task_row(detail, str(detail.get("parentId") or row.get("parent_id") or ""))
            if filter_task_rows([row], full_filters):
                results.append(row)
                if filters.get("limit") is not None and len(results) >= int(filters["limit"]):
                    break
        return results

    def _child_rows(self, parent_id: str) -> list[dict[str, Any]]:
        return [
            child_task_row(work, parent_id)
            for work in self._read_call(get_work_children, self._client(), parent_id)
        ]

    def preview_list_tasks(self, filters: dict[str, Any]) -> dict[str, Any]:
        if filters.get("parent_id"):
            return {
                "method": "GET",
                "endpoint": "Work_GetWorkChild",
                "query": {"WorkflowCode": filters.get("parent_id"), "newLayout": "true"},
                "filters": filters,
            }
        if filters.get("scope"):
            scope = filters["scope"]
            return {
                "operation": "task.list",
                "endpoint": "Work_GetAllByProject" if scope == "project" else "Work_GetWorkInProcess",
                "types": list(WORK_SCOPE_TYPES.get(scope, ())),
                "detail_for_missing_roles": "Work_DetailInfo",
                "per_parent": None if scope == "project" else "Work_GetWorkChild",
                "filters": filters,
            }
        return {
            "operation": "task.list",
            "preflight": ["Work_GetWorkInProcess"],
            "per_story": ["Work_GetWorkChild"],
            "filters": filters,
        }

    def list_subtasks(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        filters = self._with_related_user(filters)
        parent_id = str(filters.get("parent_id") or "").strip()
        if parent_id:
            if filters.get("recursive"):
                rows = self._list_descendants(parent_id)
            else:
                rows = [
                    child_task_row(work, parent_id)
                    for work in self._call(get_work_children, self._client(), parent_id)
                ]
            return filter_task_rows(rows, filters)

        if filters.get("mine"):
            # An assigned descendant may have a parent assigned to someone else.
            tasks = self.list_tasks({**filters, "limit": None, "status": None, "query": None,
                                     "related": False, "mine": False, "today": False,
                                     "date_from": None, "date_to": None, "recursive": False})
            rows = []
            for task in tasks:
                rows.extend(self._list_descendants(str(task["workflow_id"])))
            return filter_task_rows(rows, filters)

        if filters.get("related"):
            rows: list[dict[str, Any]] = []
            for _task, descendants in self._related_tasks_with_descendants(filters):
                rows.extend(descendants)
            return filter_task_rows(rows, {**filters, "related": False})

        task_filters = {**filters, "limit": None, "status": None, "query": None, "related": False,
                        "today": False, "date_from": None, "date_to": None, "recursive": False}
        tasks = self.list_tasks(task_filters)
        rows = []
        for task in tasks:
            task_id = str(task.get("workflow_id") or "").strip()
            if not task_id:
                continue
            rows.extend(self._list_descendants(task_id) if filters.get("recursive") else self._child_rows(task_id))
        return filter_task_rows(rows, filters)

    def _list_descendants(self, root_id: str) -> list[dict[str, Any]]:
        return list(self._iter_descendants(root_id))

    def _iter_descendants(self, root_id: str) -> Iterator[dict[str, Any]]:
        seen: set[str] = {root_id}
        queue = deque([root_id])
        while queue:
            current_id = queue.popleft()
            for row in self._child_rows(current_id):
                child_id = str(row.get("workflow_id") or "").strip()
                if child_id and child_id not in seen:
                    seen.add(child_id)
                    queue.append(child_id)
                    yield row

    def _related_tasks_with_descendants(
        self, filters: dict[str, Any]
    ) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        """Every task related to the user, paired with its full descendant
        subtask tree (any depth). Descendants are included unconditionally
        once their ancestor task is related — a subtask often doesn't carry
        its own userPartner entry for the assignee even though it belongs to
        a task that does, so re-checking relatedness on each subtask would
        drop real items."""
        related_task_filters = {**filters, "limit": None, "status": None, "query": None, "project": None,
                                "today": False, "date_from": None, "date_to": None, "recursive": False}
        tasks = self.list_tasks(related_task_filters)
        result: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for task in tasks:
            task_id = str(task.get("workflow_id") or "").strip()
            if not task_id:
                continue
            result.append((task, self._list_descendants(task_id)))
        return result

    def _list_loggable_items(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Items that logtime is actually recorded against: every descendant
        subtask (any depth) if a task has subtasks, otherwise the task itself
        (per convention, a bare task with no subtask is logged directly)."""
        # --mine on logtime refers to the author of the logs, not the assignee.
        filters = self._with_related_user({**filters, "mine": False})
        rows: list[dict[str, Any]] = []
        for task, descendants in self._related_tasks_with_descendants(filters):
            rows.extend(descendants if descendants else [task])
        return filter_task_rows(rows, {**filters, "related": False})

    def preview_list_subtasks(self, filters: dict[str, Any]) -> dict[str, Any]:
        if filters.get("parent_id"):
            return {
                "method": "GET",
                "endpoint": "Work_GetWorkChild",
                "query": {"WorkflowCode": filters.get("parent_id"), "newLayout": "true"},
                "filters": filters,
            }
        return {
            "operation": "subtask.list",
            "preflight": ["Work_GetWorkInProcess"],
            "per_story": ["Work_GetWorkChild"],
            "per_task": ["Work_GetWorkChild"],
            "filters": filters,
        }

    def _with_related_user(self, filters: dict[str, Any]) -> dict[str, Any]:
        if not (filters.get("related") or filters.get("mine")):
            return filters
        user = self._current_user()
        return {
            **filters,
            "related_user_id": person_ref(user.get("id")),
            "related_user_email": str(user.get("email") or "").strip().casefold(),
        }

    def logtime_status(self, filters: dict[str, Any]) -> dict[str, Any]:
        tasks = self._list_loggable_items(filters)
        user = self._current_user()
        user_ref = person_ref(user.get("id"))
        user_email = str(user.get("email") or "").strip().casefold()
        date_value = str(filters.get("date") or "")
        rows: list[dict[str, Any]] = []
        for task in tasks:
            workflow_id = str(task.get("workflow_id") or task.get("id") or "").strip()
            if not workflow_id:
                continue
            raw_logs = self._call(get_logtime, self._client(), workflow_id, False)
            logs = raw_logs if isinstance(raw_logs, list) else []
            matched_logs = [
                compact_logtime(log)
                for log in logs
                if log_matches_date(log, date_value) and log_matches_user(log, user_ref, user_email)
            ]
            hours = sum(float(log.get("hours") or 0) for log in matched_logs)
            row = {
                **task,
                "has_logtime": bool(matched_logs),
                "logtime_hours": round(hours, 2),
                "logtimes": matched_logs,
            }
            rows.append(row)

        if filters.get("missing_only"):
            rows = [row for row in rows if not row["has_logtime"]]

        return {
            "date": date_value,
            "total_tasks": len(tasks),
            "returned_tasks": len(rows),
            "logged_tasks": sum(1 for row in rows if row["has_logtime"]),
            "missing_tasks": sum(1 for row in rows if not row["has_logtime"]),
            "tasks": rows,
        }

    def list_logtime(self, task_id: str, filters: dict[str, Any]) -> dict[str, Any]:
        raw_logs = self._call(get_logtime, self._client(), task_id, False)
        logs = raw_logs if isinstance(raw_logs, list) else []
        date_value = str(filters.get("date") or "").strip()
        if filters.get("mine"):
            user = self._current_user()
            user_ref = person_ref(user.get("id"))
            user_email = str(user.get("email") or "").strip().casefold()
            logs = [log for log in logs if log_matches_user(log, user_ref, user_email)]
        compacted = [compact_logtime(log) for log in logs if not date_value or log_matches_date(log, date_value)]
        return {
            "task_id": task_id,
            "date": date_value or None,
            "total_logs": len(compacted),
            "total_hours": round(sum(float(log.get("hours") or 0) for log in compacted), 2),
            "logtimes": limit_rows(compacted, filters.get("limit")),
        }

    def preview_list_logtime(self, task_id: str, filters: dict[str, Any]) -> dict[str, Any]:
        return {
            "method": "GET",
            "endpoint": "Work_GetLogtimeByWorkId",
            "query": {"WorkFlowId": task_id},
            "filters": filters,
        }

    def timesheet(self, filters: dict[str, Any]) -> dict[str, Any]:
        date_value = str(filters.get("date") or "").strip()
        days = max(1, int(filters.get("days") or 1))
        end = date_cls.fromisoformat(date_value)
        # A multi-day window means "N most recent workdays" - weekends never
        # have logtime, so a plain calendar-day window would waste slots on
        # Sat/Sun and under-report actual work coverage. A single-day lookup
        # (the default) still checks exactly the date given, weekend or not.
        start = date_cls.fromisoformat(filters["date_from"]) if filters.get("date_from") else (
            workday_window_start(end, days) if days > 1 else end
        )
        if filters.get("date_from"):
            days = (end - start).days + 1

        user = self._current_user()
        user_id = str(user.get("id") or "").strip()

        raw: list[dict[str, Any]] = []
        month_anchor = start.replace(day=1)
        while month_anchor <= end:
            raw.extend(self._read_call(get_timesheet_report, self._client(), month_anchor.isoformat(), user_id))
            month_anchor = (month_anchor + timedelta(days=32)).replace(day=1)

        all_entries = [entry for entry in (parse_timesheet_row(row) for row in raw) if entry]
        entries = sorted(
            (entry for entry in all_entries if entry["date"] and start.isoformat() <= entry["date"] <= end.isoformat()),
            key=lambda entry: entry["date"],
        )
        return {
            "date": date_value,
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "days": days,
            "total_logs": len(entries),
            "total_hours": round(sum(entry["hours"] for entry in entries), 2),
            "logtimes": entries,
        }

    def preview_timesheet(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {
            "method": "GET",
            "endpoint": "Work_TimeSheetReport",
            "query": {"date": filters.get("date"), "projectName": "-1", "email": "<current user P: id>", "department": ""},
            "filters": filters,
        }

    def list_task_resources(self, kind: str, task_id: str) -> dict[str, Any]:
        return self._read_call(get_task_resources, self._client(), kind, task_id)

    def preview_task_resources(self, kind: str, task_id: str) -> dict[str, Any]:
        endpoint, query = task_resource_request(kind, task_id)
        return {"method": "GET", "endpoint": endpoint, "query": query}

    def timesheet_gaps(self, filters: dict[str, Any]) -> dict[str, Any]:
        month_str, year_str = str(filters.get("month")).split("/")
        month, year = int(month_str), int(year_str)
        today = date_cls.today()
        if (year, month) == (today.year, today.month):
            # Today's log isn't due until end of day, so don't flag it as missing yet.
            up_to = date_cls.fromordinal(today.toordinal() - 1)
        else:
            up_to = date_cls(year, month, monthrange(year, month)[1])
        workdays = workdays_in_month(year, month, up_to)

        excluded = {value.strip().casefold() for value in DEFAULT_TIMESHEET_GAPS_EXCLUDE + list(filters.get("exclude") or [])}

        raw = self._call(get_department_timesheet_report, self._client(), filters.get("month"), str(filters.get("department")))
        people: dict[str, dict[str, Any]] = {}
        for row in raw:
            entry = parse_timesheet_row(row)
            if not entry or not entry["email"]:
                continue
            person = people.setdefault(entry["email"], {"name": entry["user"] or entry["email"], "hours": {}, "ref": ""})
            if entry["date"]:
                try:
                    day = date_cls.fromisoformat(entry["date"][:10])
                except ValueError:
                    day = None
                if day:
                    person["hours"][day] = person["hours"].get(day, 0.0) + entry["hours"]
            if entry["person_ref"] and not person["ref"]:
                person["ref"] = entry["person_ref"]

        leave_days: dict[str, dict[str, float]] = {}
        try:
            if not workdays:
                raise ValueError("no workdays in range")
            leave_raw = self._call(
                get_department_leave_calendar,
                self._client(),
                workdays[0].isoformat(),
                workdays[-1].isoformat(),
                str(filters.get("department")),
            )
            leave_days = parse_leave_days(leave_raw)
        except Exception:
            # Best-effort: gaps report still works without leave info if this
            # (separate-subdomain, separately-authed) call fails.
            pass

        # A full workday is 8h logtime; a half-day leave still expects the
        # other 4h logged, a full-day leave expects nothing.
        FULL_DAY_HOURS = 8.0

        results = []
        for email in sorted(people, key=lambda e: people[e]["name"]):
            person = people[email]
            if person["name"].strip().casefold() in excluded or email.strip().casefold() in excluded:
                continue
            on_leave = leave_days.get(person["ref"], {})
            missing = []
            for d in workdays:
                required = FULL_DAY_HOURS * (1 - on_leave.get(d.isoformat(), 0.0))
                if required <= 0:
                    continue
                logged = person["hours"].get(d, 0.0)
                if logged + 1e-9 < required:
                    missing.append(d)
            if missing:
                results.append({
                    "name": person["name"],
                    "email": email,
                    "missing_count": len(missing),
                    "missing_dates": [d.isoformat() for d in missing],
                })

        return {
            "month": filters.get("month"),
            "department": filters.get("department"),
            "workdays": [d.isoformat() for d in workdays],
            "people": results,
        }

    def preview_timesheet_gaps(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {
            "method": "GET",
            "endpoint": "Work_TimeSheetPersonal",
            "query": {"date": filters.get("month"), "projectName": "-1", "email": "", "department": filters.get("department")},
            "filters": filters,
        }

    def preview_logtime_status(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {
            "operation": "logtime.status",
            "preflight": ["Work_GetWorkInProcess", "Work_GetInfLogin"],
            "per_story": ["Work_GetWorkChild"],
            "per_task": ["Work_GetWorkChild"],
            "per_subtask": ["Work_GetLogtimeByWorkId"],
            "filters": filters,
        }

    def history(self, task_id: str) -> list[dict[str, Any]]:
        raw = self._call(get_work_history, self._client(), task_id)
        return [compact_history(entry) for entry in raw]

    def preview_history(self, task_id: str) -> dict[str, Any]:
        return {
            "method": "GET",
            "endpoint": "Work_GetHistoryChangedStatus",
            "query": {"id": task_id},
        }

    def activity(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        project_id = str(filters.get("project") or "").strip()
        user_id = str(filters.get("user_id") or "").strip()
        if filters.get("mine") and not user_id:
            user = self._call(get_current_user, self._client())
            user_id = str(user.get("id") or "").strip()
        raw = self._call(get_recent_activity, self._client(), project_id, user_id)
        rows = [compact_activity(entry) for entry in raw]
        return limit_rows(rows, filters.get("limit"))

    def preview_activity(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {
            "method": "GET",
            "endpoint": "Work_RecentActivity",
            "query": {
                "projectId": filters.get("project") or "",
                "userId": filters.get("user_id") or "",
            },
            "filters": filters,
        }

    def show_task(self, task_id: str) -> dict[str, Any]:
        detail = self._call(get_work_detail, self._client(), task_id, False)
        if not isinstance(detail, dict):
            raise ProviderError("Beca did not return task detail.", {"task_id": task_id})
        logs = self._call(get_logtime, self._client(), task_id, False)
        return {"task": detail, "worklogs": logs if isinstance(logs, list) else []}

    def update_task(self, task_id: str, request: TaskUpdate) -> dict[str, Any]:
        changes = request.changes()
        if not changes:
            return self.show_task(task_id)

        before = self._call(require_work_detail, self._client(), task_id)
        responses: dict[str, Any] = {}
        field_map = {
            "title": "Tieude",
            "desc": "Noidung",
            "assignee": "Nguoixuly",
            "estimate": "EstimateWorkTime",
            "progress": "Tiendo",
        }
        for key, field_name in field_map.items():
            if key in changes:
                if key == "desc":
                    value = html_description(changes[key])
                elif key == "progress":
                    value = normalize_progress_value(changes[key])
                else:
                    value = str(changes[key])
                responses[key] = self._call(update_work_field, self._client(), task_id, field_name, value)

        if request.status:
            statuses = self._call(get_next_statuses, self._client(), task_id, before)
            selected = find_status(statuses, request.status)
            if not selected:
                selected = find_status(
                    self._call(get_statuses_by_project, self._client(), str(before.get("projectId") or "")),
                    request.status,
                )
            if not selected:
                raise ProviderError("Cannot find Beca status.", {"status": request.status})
            old_status_id = str(before.get("status") or "")
            new_status_id = str(selected.get("userWorkflowId") or "")
            responses["status"] = self._call(
                update_work_field,
                self._client(),
                task_id,
                "TrangThaiCongViec",
                new_status_id,
            )
            responses["status_history"] = self._call(
                insert_status_history,
                self._client(),
                task_id,
                old_status_id,
                new_status_id,
            )

        after = self._call(get_work_detail, self._client(), task_id, False)
        return {"id": task_id, "changes": changes, "responses": responses, "task": after}

    def add_worklog(self, request: WorklogCreate) -> dict[str, Any]:
        context = self._build_worklog_context(request)
        result = self._call(
            self._client().request_json,
            f"{SAVE_FORM_URL}?{urlencode(context['query'])}",
            headers={
                "Content-Type": "application/json; charset=UTF-8",
                "Origin": "https://work.becawork.vn",
                "Referer": f"https://work.becawork.vn/work/mywork?workId={request.task_id}",
            },
            data=json.dumps(context["payload"], ensure_ascii=False).encode("utf-8"),
            method="POST",
            print_body=False,
        )

        return {
            "id": extract_created_work_id(result),
            "task_id": request.task_id,
            "content": request.content,
            "time_spent": request.time_spent,
            "hours": context["hours"],
            "type": request.log_type,
            "date": context["date"],
            "external_id": request.external_id,
            "raw": result,
        }

    def preview_worklog(self, request: WorklogCreate) -> dict[str, Any]:
        context = self._build_worklog_context(request)
        return {
            "method": "POST",
            "endpoint": "Eoffice_ValidateAndInsertData",
            "query": context["query"],
            "preflight": [
                "Work_GetLogtimeByWorkId",
                "Work_CheckOverInLogtime",
                "Work_GetApiSetting",
                "Eoffice_GetData?urlStr=getFormatWorkflow",
                "Work_GetInfLogin",
            ],
            "payload": context["payload"],
            "date": context["date"],
            "hours": context["hours"],
        }

    def _build_worklog_context(self, request: WorklogCreate) -> dict[str, Any]:
        log_date = request.resolved_date()
        hours = hours_from_time(request.time_spent)
        with patched_env({"WORKFLOW_ID": request.task_id, "LOG_PROJECT_ID": self.config.project or ""}):
            project_id = self._call(get_project_id, self._client(), request.task_id)
            over_result = self._call(check_over_logtime, self._client(), log_date, hours)
            if isinstance(over_result, (int, float)) and over_result < 0:
                raise ProviderError("Beca rejected this logtime amount.", {"response": over_result})

            api_setting = self._call(get_api_setting, self._client())
            form_id = str(api_setting["id_getWorkFormLogTime"]["id"])
            step_id = str(api_setting["id_getWorkFormLogTimeStep"]["id"])
            form_format = self._call(get_format_workflow, self._client(), form_id)
            user = self._call(get_current_user, self._client())
            values = {
                "Nguoilap": default_field_value(form_format, "Nguoilap") or user.get("fullName"),
                "Ngaylap": time.strftime("%Y-%m-%d %H:%M:%S"),
                "Email": default_field_value(form_format, "Email") or user.get("email"),
                "Duan": project_id,
                "Congviec": request.task_id,
                "Ngay": f"{log_date} 00:00:00",
                "SoGio": hours,
                "Hanhdong": action_from_log_type(request.log_type),
                "Mota": html_description(request.content),
                "UserId": person_ref(user.get("id")),
            }
            fields = object_to_fields(values, form_format)
            payload = {
                "data": fields,
                "data_json": json.dumps({item["name"]: item["value"] for item in fields}, ensure_ascii=False),
                "isDraft": True,
            }
            query = {
                "urlStr": f"/api/apikey/userWorkflows/{form_id}/addDynamicUserWorkflow/{step_id}",
                "apiId": form_id,
            }
        return {"query": query, "payload": payload, "date": log_date, "hours": hours}

    def _client(self) -> BecaClient:
        if self.client:
            return self.client

        self.client = BecaClient(
            cookie=self.config.beca_cookie,
            timeout=self.config.timeout,
            verbose=self.config.verbose,
        )
        if self.client.cookie:
            return self.client

        username = self.config.beca_username or os.getenv("BECA_USERNAME")
        password = self.config.beca_password or os.getenv("BECA_PASSWORD")
        if not username or not password:
            raise AuthError(
                "Missing Beca credentials. Set TASKCLI_BECA_USERNAME/TASKCLI_BECA_PASSWORD, "
                "BECA_USERNAME/BECA_PASSWORD, or TASKCLI_BECA_COOKIE.",
            )
        self._call(self.client.login, username, password)
        return self.client

    def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except BecaResponseError as exc:
            raise ProviderError(str(exc)) from exc
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise AuthError("Beca authentication failed.", {"status": exc.code}) from exc
            if exc.code == 429:
                raise RateLimitError("Beca rate limit exceeded.", {"status": exc.code}) from exc
            raise NetworkError("Beca HTTP request failed.", {"status": exc.code, "reason": exc.reason}) from exc
        except URLError as exc:
            raise NetworkError("Cannot reach Beca API.", {"reason": str(exc.reason)}) from exc
        except TimeoutError as exc:
            raise NetworkError("Beca API request timed out.") from exc

    def _read_call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Retry a transient read once; never automatically retry writes."""
        try:
            return self._call(fn, *args, **kwargs)
        except NetworkError as exc:
            status = exc.details.get("status")
            if status is not None and not 500 <= status < 600:
                raise
            time.sleep(0.5)
            return self._call(fn, *args, **kwargs)


@contextmanager
def patched_env(values: dict[str, str]) -> Any:
    old_values = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value:
                os.environ[key] = value
        yield
    finally:
        for key, old_value in old_values.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def response_data(data: object | None) -> object | None:
    if isinstance(data, dict) and "data" in data:
        return data.get("data")
    return data


def hours_from_time(value: str | None) -> str:
    if not value:
        return "1"
    text = value.strip().lower()
    if text.endswith("h"):
        return text[:-1]
    if text.endswith("m"):
        minutes = float(text[:-1])
        return str(round(minutes / 60, 2))
    return text


def action_from_log_type(log_type: str) -> str:
    return {
        "progress": "Thực hiện",
        "review": "Xem xét",
        "test": "Kiểm thử",
        "follow": "Theo dõi",
    }.get(log_type, "Thực hiện")


def compact_project(project: dict[str, object]) -> dict[str, object]:
    return {
        "project_id": project.get("project_id") or "",
        "project_name": project.get("project_name") or "",
        "count": project.get("count") if project.get("count") is not None else "",
    }


def limit_rows(rows: list[dict[str, Any]], limit: object | None) -> list[dict[str, Any]]:
    if limit is None or limit == "":
        return rows
    try:
        size = int(limit)
    except (TypeError, ValueError):
        return rows
    if size <= 0:
        return []
    return rows[:size]


def child_task_row(work: dict[str, Any], parent_id: str) -> dict[str, Any]:
    row = normalize_work(work)
    row["parent_id"] = parent_id
    row["is_my_work"] = bool(work.get("isMyWork"))
    row["related_user_ids"] = related_user_ids(work)
    row["related_user_emails"] = related_user_emails(work)
    row["related_user_types"] = related_user_types(work)
    assignees = [user for user in work.get("userPartner") or []
                 if str(user.get("userType") or "").casefold() == "nguoixuly"]
    row["assignee_ids"] = list(dict.fromkeys(person_ref(user.get("id")) for user in assignees if user.get("id")))
    row["assignee_emails"] = list(dict.fromkeys(str(user["email"]) for user in assignees if user.get("email")))
    return row


def filter_task_rows(rows: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    project_id = str(filters.get("project") or "").strip()
    status = str(filters.get("status") or "").strip().casefold()
    query = str(filters.get("query") or "").strip().casefold()
    related_user_id = str(filters.get("related_user_id") or "").strip().casefold()
    related_user_email = str(filters.get("related_user_email") or "").strip().casefold()
    if project_id:
        rows = [row for row in rows if str(row.get("project_id") or "").strip() == project_id]
    if status:
        rows = [row for row in rows if str(row.get("status") or "").strip().casefold() == status]
    if filters.get("related"):
        rows = [
            row
            for row in rows
            if (related_user_id and related_user_id in [str(value).casefold() for value in row.get("related_user_ids") or []])
            or (
                related_user_email
                and related_user_email in [str(value).casefold() for value in row.get("related_user_emails") or []]
            )
        ]
    if filters.get("mine"):
        rows = [
            row for row in rows
            if (related_user_id and related_user_id in [str(value).casefold() for value in row.get("assignee_ids") or []])
            or (related_user_email and related_user_email in [str(value).casefold() for value in row.get("assignee_emails") or []])
        ]
    if query:
        rows = [
            row
            for row in rows
            if query in str(row.get("workflow_id", "")).casefold()
            or query in str(row.get("title", "")).casefold()
            or query in str(row.get("project_name", "")).casefold()
            or query in str(row.get("parent_id", "")).casefold()
        ]
    rows = [
        row for row in rows
        if task_matches_dates(
            row.get("start"),
            row.get("end") or (
                row.get("completed_at")
                if str(row.get("status") or "").casefold() in {"done", "feedback", "reject"} else None
            ),
            filters,
        )
    ]
    return limit_rows(rows, filters.get("limit"))


def related_user_ids(work: dict[str, Any]) -> list[str]:
    values = []
    for user in work.get("userPartner") or []:
        user_id = str(user.get("id") or "").strip()
        if user_id and user_id not in values:
            values.append(user_id)
    return values


def related_user_types(work: dict[str, Any]) -> list[str]:
    values = []
    for user in work.get("userPartner") or []:
        user_type = str(user.get("userType") or "").strip()
        if user_type and user_type not in values:
            values.append(user_type)
    return values


def related_user_emails(work: dict[str, Any]) -> list[str]:
    values = []
    for user in work.get("userPartner") or []:
        email = str(user.get("email") or "").strip()
        if email and email not in values:
            values.append(email)
    return values


def log_matches_date(log: dict[str, Any], date_value: str) -> bool:
    raw_date = log.get("DateLogtime") or log.get("Ngay") or log.get("date")
    return str(raw_date or "").startswith(date_value)


def log_matches_user(log: dict[str, Any], user_ref: str, user_email: str) -> bool:
    log_user = str(log.get("UserId") or "").strip().casefold()
    log_email = str(log.get("Email") or "").strip().casefold()
    if log_user:
        return log_user == user_ref.casefold()
    if log_email:
        return log_email == user_email
    return True


# Always left out of `logtime gaps` (e.g. people on long leave, already
# tracked separately). Add full name or email, either works.
DEFAULT_TIMESHEET_GAPS_EXCLUDE = [
    "NGUYỄN QUANG VINH",
    "NGUYỄN THỊ LOAN",
]


def workdays_in_month(year: int, month: int, up_to: date_cls) -> list[date_cls]:
    last_day = monthrange(year, month)[1]
    days = []
    for day in range(1, last_day + 1):
        d = date_cls(year, month, day)
        if d > up_to:
            break
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
    return days


def workday_window_start(end: date_cls, days: int) -> date_cls:
    """Earliest date such that [result, end] contains exactly `days` weekdays
    (Mon-Fri), walking backward from `end` and skipping Saturday/Sunday."""
    current = end
    remaining = days
    while True:
        if current.weekday() < 5:
            remaining -= 1
            if remaining == 0:
                return current
        current -= timedelta(days=1)


def compact_logtime(log: dict[str, Any]) -> dict[str, Any]:
    description_html = str(log.get("Mota") or "")
    return {
        "id": log.get("Id") or log.get("id"),
        "date": str(log.get("DateLogtime") or log.get("Ngay") or ""),
        "hours": float(log.get("SoGio") or log.get("hours") or 0),
        "action": log.get("Hanhdong") or log.get("action") or "",
        "description": html_to_text(description_html),
        "description_html": description_html,
        "user": log.get("Nguoilap") or log.get("user") or "",
        "email": log.get("Email") or log.get("email") or "",
        "person_ref": log.get("UserId") or "",
    }


def parse_timesheet_row(row: dict[str, Any]) -> dict[str, Any] | None:
    raw_data = row.get("data")
    if not raw_data:
        return None
    try:
        log = json.loads(raw_data)
    except (TypeError, ValueError):
        return None
    return {
        **compact_logtime(log),
        "date": str(row.get("dateLogtime") or "").strip(),
        "workflow_id": str(row.get("workId") or "").strip(),
        "title": row.get("workLogtime") or "",
    }


BLOCK_CLOSE_RE = re.compile(r"</(p|li|div|h[1-6])>|<br\s*/?>", re.IGNORECASE)


def html_to_text(value: str) -> str:
    with_breaks = BLOCK_CLOSE_RE.sub("\n", value)
    text = unescape(re.sub(r"<[^>]+>", " ", with_breaks))
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def compact_history(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry.get("id"),
        "workflow_id": str(entry.get("workid") or "").strip(),
        "date": entry.get("date") or "",
        "field": entry.get("columnName") or "",
        "old_value": entry.get("oldValue"),
        "new_value": entry.get("newValue"),
        "updated_by": entry.get("updateUser") or "",
        "note": entry.get("note") or "",
    }


def compact_activity(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflow_id": str(entry.get("workId") or "").strip(),
        "title": entry.get("workName") or "",
        "field": entry.get("columnName") or "",
        "user": entry.get("fullName") or "",
        "time": entry.get("time") or "",
        "content": html_to_text(str(entry.get("content") or "")),
    }
