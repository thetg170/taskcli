from __future__ import annotations

import getpass
import os

from .actions import (
    add_logtime,
    create_child_work,
    get_logtime,
    get_work_detail,
    get_work_in_process,
    inspect_child_work_payload,
    list_project_statuses,
    list_projects,
    list_statuses,
    list_workflows,
    update_progress,
    update_status,
)
from .client import BecaClient
from .config import require_env, write_output


def build_client() -> BecaClient:
    client = BecaClient(cookie=os.getenv("BECA_COOKIE"))
    if client.cookie:
        return client

    username = os.getenv("BECA_USERNAME") or input("Username: ")
    password = os.getenv("BECA_PASSWORD") or getpass.getpass("Password: ")
    client.login(username, password)
    return client


def run_action(client: BecaClient) -> object | None:
    action = os.getenv("ACTION", "list_workflows").lower().replace("-", "_")

    if action == "list_work":
        return get_work_in_process(client)

    if action in {"list_workflows", "list_works", "works"}:
        return list_workflows(client)

    if action in {"list_projects", "projects"}:
        return list_projects(client)

    if action in {"list_statuses", "statuses"}:
        return list_statuses(client)

    if action in {"list_project_statuses", "project_statuses"}:
        return list_project_statuses(client)

    if action == "get_logtime":
        return get_logtime(client, require_env("WORKFLOW_ID"))

    if action == "add_logtime":
        return add_logtime(client)

    if action in {"get_work_detail", "work_detail"}:
        return get_work_detail(client, require_env("WORKFLOW_ID"))

    if action in {"update_progress", "set_progress"}:
        return update_progress(client)

    if action in {"update_status", "set_status"}:
        return update_status(client)

    if action in {"inspect_child_work_payload", "child_work_payload"}:
        return inspect_child_work_payload(client)

    if action in {"create_child_work", "create_child_task", "add_child_work", "add_child_task"}:
        return create_child_work(client)

    raise SystemExit(f"Unsupported ACTION: {action}")


def run() -> None:
    client = build_client()
    data = run_action(client)
    if data is not None:
        write_output(data)
