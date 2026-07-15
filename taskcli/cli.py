from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .config import Config, load_config
from .errors import CliError, ConfigError, ValidationError
from .idempotency import IdempotencyStore, content_hash
from .models import TaskCreate, TaskUpdate, WorklogCreate, normalize_progress_value, resolve_date_token
from .provider import Provider
from .providers import BecaProvider, MockProvider


ROLE_PREFIXES = {"PM", "PO", "BA", "UIUX", "FE", "BE", "MOBILE", "DEVOPS", "QC", "DE", "AI"}

STATUS_SHORTCUTS = {
    "done": "Done",
    "reject": "Reject",
    "feedback": "Feedback",
    "pending": "Pending",
    "need-to-test": "Need to Test",
}


class JsonAwareParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        if "--json" in sys.argv:
            error = ValidationError(message)
            print(json.dumps(error.to_dict(), ensure_ascii=False), file=sys.stdout)
            raise SystemExit(error.exit_code)
        super().error(message)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        result = run(args)
        emit_success(result, args.json)
        return 0
    except CliError as exc:
        emit_error(exc, wants_json(argv))
        return exc.exit_code
    except KeyboardInterrupt:
        exc = CliError("interrupted", "Interrupted by user.", 130)
        emit_error(exc, wants_json(argv))
        return exc.exit_code
    except Exception as exc:  # pragma: no cover - guardrail for agent callers.
        wrapped = CliError("unexpected_error", str(exc), 1)
        emit_error(wrapped, wants_json(argv))
        return wrapped.exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = JsonAwareParser(prog="taskcli", description="Agent-friendly task/worklog CLI.")
    parser.add_argument("--config", help="Config path. Defaults to ~/.config/taskcli/config.toml.")
    parser.add_argument("--project", dest="global_project", help="Default project override.")
    parser.add_argument("--assignee", dest="global_assignee", help="Default assignee override.")
    parser.add_argument("--parent-id", dest="global_parent_id", help="Default parent task/work id override.")
    parser.add_argument("--timeout", dest="global_timeout", type=float, help="HTTP timeout in seconds.")
    parser.add_argument("--verbose", dest="global_verbose", action="store_true", help="Write debug logs to stderr.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    project_parser = subparsers.add_parser("project", help="Project lookup commands.")
    project_sub = project_parser.add_subparsers(dest="project_command", required=True)
    project_list = project_sub.add_parser("list", help="List projects available to current user.")
    add_common_flags(project_list)
    project_list.add_argument("--type", default="Việc đã xử lý", help="BecaWork project list type.")
    project_list.add_argument("-q", "--query", help="Filter by project id/name.")
    project_list.add_argument("--limit", type=int, help="Maximum rows to return.")

    story_parser = subparsers.add_parser("story", aliases=["work"], help="Story/work lookup commands.")
    story_sub = story_parser.add_subparsers(dest="story_command", required=True)
    story_list = story_sub.add_parser("list", help="List current stories/works for use as --parent-id.")
    add_common_flags(story_list)
    story_list.add_argument("--project", help="Filter by project id.")
    story_list.add_argument("--status", help="Filter by status.")
    story_list.add_argument("-q", "--query", help="Filter by workflow id/title/project name.")
    story_list.add_argument("--mine", action="store_true", help="Only current user's work when supported.")
    story_list.add_argument("--related", action="store_true", help="Only items related to current user.")
    story_list.add_argument("--today", action="store_true", help="Only stories started today.")
    story_list.add_argument("--limit", type=int, help="Maximum rows to return.")

    logtime_parser = subparsers.add_parser("logtime", aliases=["worklog"], help="Logtime lookup commands.")
    logtime_sub = logtime_parser.add_subparsers(dest="logtime_command", required=True)
    logtime_status = logtime_sub.add_parser("status", aliases=["check"], help="Check task logtime by date.")
    add_common_flags(logtime_status)
    logtime_status.add_argument("--date", default="today", help="Date to check: today, yesterday, or YYYY-MM-DD.")
    logtime_status.add_argument("--project", help="Filter by project id.")
    logtime_status.add_argument("--status", help="Filter by task status.")
    logtime_status.add_argument("-q", "--query", help="Filter by workflow id/title/project name.")
    logtime_status.add_argument("--mine", action="store_true", help="Only current user's work when supported.")
    logtime_status.add_argument("--related", action="store_true", help="Only items related to current user.")
    logtime_status.add_argument("--today", action="store_true", help="Only tasks started today.")
    logtime_status.add_argument("--missing-only", action="store_true", help="Return only tasks without logtime.")
    logtime_status.add_argument("--limit", type=int, help="Maximum tasks to check.")
    logtime_list = logtime_sub.add_parser("list", help="List logtime entries for a workflow id, or across related tasks.")
    add_common_flags(logtime_list)
    logtime_list.add_argument("task_id", nargs="?", help="Workflow id. Omit to list across related tasks.")
    logtime_list.add_argument("--date", help="Filter by date: today, yesterday, or YYYY-MM-DD.")
    logtime_list.add_argument("--mine", action="store_true", help="Only current user's logtime entries.")
    logtime_list.add_argument("--related", action="store_true", help="Only tasks related to current user (used when task_id is omitted).")
    logtime_list.add_argument("--project", help="Filter by project id (used when task_id is omitted).")
    logtime_list.add_argument("-q", "--query", help="Filter by workflow id/title/project name (used when task_id is omitted).")
    logtime_list.add_argument("--limit", type=int, help="Maximum rows to return.")
    logtime_timesheet = logtime_sub.add_parser(
        "timesheet",
        help=(
            "Check logtime for a date using BecaWork's own TimeSheet report. "
            "Covers ALL projects (unlike `status`/`list`, which only scan tasks related via `task list --related`)."
        ),
    )
    add_common_flags(logtime_timesheet)
    logtime_timesheet.add_argument("--date", default="today", help="Date to check: today, yesterday, or YYYY-MM-DD.")

    task_parser = subparsers.add_parser("task", help="Task commands.")
    task_sub = task_parser.add_subparsers(dest="task_command", required=True)

    create = task_sub.add_parser("create", help="Create a task.")
    add_create_flags(create)
    create.add_argument("--role", choices=sorted(ROLE_PREFIXES), help="Prefix title with role, e.g. BE.")
    create.set_defaults(issue_kind="task")

    list_cmd = task_sub.add_parser("list", help="List tasks.")
    add_common_flags(list_cmd)
    list_cmd.add_argument("--parent-id", help="List child tasks under this parent WORKFLOW_ID.")
    list_cmd.add_argument("--project", help="Filter by project id.")
    list_cmd.add_argument("--sprint", default=None, help="Sprint name or 'current'.")
    list_cmd.add_argument("--status", help="Filter by status.")
    list_cmd.add_argument("-q", "--query", help="Filter by workflow id/title/project name.")
    list_cmd.add_argument("--mine", action="store_true", help="Only tasks assigned to default assignee.")
    list_cmd.add_argument("--related", action="store_true", help="Only tasks related to current user.")
    list_cmd.add_argument("--today", action="store_true", help="Only tasks created/started today.")
    list_cmd.add_argument("--limit", type=int, help="Maximum rows to return.")

    show = task_sub.add_parser("show", help="Show a task.")
    add_common_flags(show)
    show.add_argument("id")

    update = task_sub.add_parser("update", help="Update a task.")
    add_common_flags(update)
    update.add_argument("id")
    update.add_argument("--status")
    update.add_argument("--title")
    update.add_argument("--desc")
    update.add_argument("--desc-file", help="Read description from file or '-' for stdin.")
    update.add_argument("--sprint")
    update.add_argument("--label", action="append")
    update.add_argument("--estimate")
    update.add_argument("--assignee")
    update.add_argument("--progress", help="Progress percent, 0..100. Example: --progress 50")

    for shortcut, status_name in STATUS_SHORTCUTS.items():
        shortcut_cmd = task_sub.add_parser(shortcut, help=f"Move a task to status: {status_name}.")
        add_common_flags(shortcut_cmd)
        shortcut_cmd.add_argument("id")

    log_cmd = subparsers.add_parser("log", help="Append worklog.")
    add_common_flags(log_cmd)
    log_cmd.add_argument("task_id")
    log_cmd.add_argument("content", nargs="?")
    log_cmd.add_argument("--from-file", help="Read content from file or '-' for stdin.")
    log_cmd.add_argument("--time", dest="time_spent", default="1h", help="Time spent, e.g. 2h or 30m.")
    log_cmd.add_argument(
        "--type",
        choices=["progress", "review", "test", "follow"],
        default="progress",
        help="BecaWork action. Dev work should use the default: progress.",
    )
    log_cmd.add_argument("--date", default="today", help="Log date: today, yesterday, or YYYY-MM-DD.")
    log_cmd.add_argument("--external-id", help="Caller-provided idempotency key.")

    whoami = subparsers.add_parser("whoami", help="Show current BecaWork user and default assignee id.")
    add_common_flags(whoami)

    history_parser = subparsers.add_parser(
        "history", help="Show who changed what and when (status, parent, etc.) on a task or subtask."
    )
    add_common_flags(history_parser)
    history_parser.add_argument("id", help="Task or sub-task WORKFLOW_ID.")
    history_parser.add_argument("--limit", type=int, help="Maximum history entries to return (most recent first).")

    activity_parser = subparsers.add_parser(
        "activity", help="Show a recent-activity feed: who touched which task, and when."
    )
    add_common_flags(activity_parser)
    activity_parser.add_argument("--project", help="Only activity within this project id.")
    activity_parser.add_argument("--mine", action="store_true", help="Only activity by the current user.")
    activity_parser.add_argument("--user-id", help="Only activity by this BecaWork user id, e.g. P:10881 (see `whoami`).")
    activity_parser.add_argument("--limit", type=int, help="Maximum activity entries to return.")

    subtask_parser = subparsers.add_parser("subtask", aliases=["sub-task"], help="Sub-task commands.")
    subtask_sub = subtask_parser.add_subparsers(dest="issue_command", required=True)
    subtask_list = subtask_sub.add_parser("list", help="List subtasks.")
    add_common_flags(subtask_list)
    subtask_list.add_argument("--parent-id", help="List subtasks under this task WORKFLOW_ID.")
    subtask_list.add_argument("--project", help="Filter by project id.")
    subtask_list.add_argument("--status", help="Filter by status.")
    subtask_list.add_argument("-q", "--query", help="Filter by workflow id/title/project name.")
    subtask_list.add_argument("--related", action="store_true", help="Only subtasks related to current user.")
    subtask_list.add_argument("--today", action="store_true", help="Only subtasks created/started today.")
    subtask_list.add_argument("--limit", type=int, help="Maximum rows to return.")
    subtask_list.add_argument(
        "--recursive",
        action="store_true",
        help="With --parent-id, also include subtasks of subtasks (all descendant levels).",
    )
    subtask_show = subtask_sub.add_parser("show", help="Show a sub-task.")
    add_common_flags(subtask_show)
    subtask_show.add_argument("id")
    subtask_create = subtask_sub.add_parser("create", help="Create a sub-task.")
    add_create_flags(subtask_create)
    subtask_create.add_argument("--role", choices=sorted(ROLE_PREFIXES), help="Prefix title with role, e.g. QC.")
    subtask_create.set_defaults(issue_kind="subtask")
    subtask_update = subtask_sub.add_parser("update", help="Update a sub-task.")
    add_update_flags(subtask_update)
    for shortcut, status_name in STATUS_SHORTCUTS.items():
        subtask_shortcut_cmd = subtask_sub.add_parser(shortcut, help=f"Move a sub-task to status: {status_name}.")
        add_common_flags(subtask_shortcut_cmd)
        subtask_shortcut_cmd.add_argument("id")

    release_parser = subparsers.add_parser("release", help="Release-ticket commands.")
    release_sub = release_parser.add_subparsers(dest="issue_command", required=True)
    release_create = release_sub.add_parser("create", help="Create a release ticket.")
    add_create_flags(release_create)
    release_create.add_argument("--version", help="Release version, e.g. v2.4.0.")
    release_create.add_argument("--env", default="Production", help="Release environment.")
    release_create.set_defaults(issue_kind="release")

    hotfix_parser = subparsers.add_parser("hotfix", help="Hotfix-ticket commands.")
    hotfix_sub = hotfix_parser.add_subparsers(dest="issue_command", required=True)
    hotfix_create = hotfix_sub.add_parser("create", help="Create a hotfix ticket.")
    add_create_flags(hotfix_create)
    hotfix_create.add_argument("--version", help="Hotfix version, e.g. v2.4.1.")
    hotfix_create.add_argument("--module", help="Affected module.")
    hotfix_create.add_argument("--issue", help="Observed issue.")
    hotfix_create.set_defaults(issue_kind="hotfix")

    return parser


def add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Show request without writing.")


def add_create_flags(parser: argparse.ArgumentParser) -> None:
    add_common_flags(parser)
    parser.add_argument("--title", help="Task title. If --role is supplied, the role prefix is added when missing.")
    parser.add_argument("--desc", default="", help="Task description.")
    parser.add_argument("--desc-file", help="Read description from file or '-' for stdin.")
    parser.add_argument("--from-file", help="Read task JSON/Markdown from file or '-' for stdin.")
    parser.add_argument("--sprint", default=None, help="Sprint name or 'current'.")
    parser.add_argument("--label", action="append", default=[], help="Repeatable label.")
    parser.add_argument("--estimate", help="Estimate, e.g. 2h.")
    parser.add_argument("--assignee", help="Assignee override.")
    parser.add_argument("--project", help="Project id/code.")
    parser.add_argument("--parent-id", help="Parent BecaWork WORKFLOW_ID.")
    parser.add_argument("--external-id", help="Caller-provided idempotency key.")


def add_update_flags(parser: argparse.ArgumentParser) -> None:
    add_common_flags(parser)
    parser.add_argument("id")
    parser.add_argument("--status")
    parser.add_argument("--title")
    parser.add_argument("--desc")
    parser.add_argument("--desc-file", help="Read description from file or '-' for stdin.")
    parser.add_argument("--sprint")
    parser.add_argument("--label", action="append")
    parser.add_argument("--estimate")
    parser.add_argument("--assignee")
    parser.add_argument("--progress", help="Progress percent, 0..100. Example: --progress 50")


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(
        config_path=args.config,
        overrides={
            "project": args.global_project,
            "assignee": args.global_assignee,
            "parent_id": args.global_parent_id,
            "timeout": args.global_timeout,
            "verbose": args.global_verbose if args.global_verbose else None,
        },
    )
    provider = build_provider(config)
    store = IdempotencyStore(config.idempotency_path)

    if args.command == "task":
        return run_task(args, config, provider, store)
    if args.command == "project":
        return run_project(args, provider)
    if args.command in {"story", "work"}:
        return run_story(args, config, provider)
    if args.command in {"logtime", "worklog"}:
        return run_logtime(args, config, provider)
    if args.command in {"subtask", "sub-task"} and args.issue_command == "list":
        return run_subtask(args, config, provider)
    if args.command in {"subtask", "sub-task"} and args.issue_command == "show":
        return {"ok": True, "operation": "subtask.show", "subtask": provider.show_task(args.id)}
    if args.command in {"subtask", "sub-task"} and (
        args.issue_command == "update" or args.issue_command in STATUS_SHORTCUTS
    ):
        return run_task_update_command(args.issue_command, args, config, provider)
    if args.command in {"subtask", "sub-task", "release", "hotfix"}:
        return run_issue_create(args, config, provider, store)
    if args.command == "log":
        return run_log(args, config, provider, store)
    if args.command == "whoami":
        return run_whoami(args, provider)
    if args.command == "history":
        return run_history(args, provider)
    if args.command == "activity":
        return run_activity(args, provider)
    raise ValidationError("Unsupported command.", {"command": args.command})


def run_project(args: argparse.Namespace, provider: Provider) -> dict[str, Any]:
    if args.project_command != "list":
        raise ValidationError("Unsupported project command.", {"project_command": args.project_command})
    filters = {"type": args.type, "query": args.query, "limit": args.limit}
    if args.dry_run:
        return dry_run_response("project.list", provider.preview_list_projects(filters))
    return {"ok": True, "operation": "project.list", "projects": provider.list_projects(filters)}


def run_story(args: argparse.Namespace, config: Config, provider: Provider) -> dict[str, Any]:
    if args.story_command != "list":
        raise ValidationError("Unsupported story command.", {"story_command": args.story_command})
    filters = {
        "project": args.project or config.project,
        "status": args.status,
        "query": args.query,
        "mine": args.mine,
        "related": args.related,
        "assignee": config.assignee,
        "today": args.today,
        "limit": args.limit,
    }
    if args.dry_run:
        return dry_run_response("story.list", provider.preview_list_stories(filters))
    return {"ok": True, "operation": "story.list", "stories": provider.list_stories(filters)}


def run_logtime(args: argparse.Namespace, config: Config, provider: Provider) -> dict[str, Any]:
    if args.logtime_command == "list":
        if args.task_id:
            filters = {
                "date": resolve_date_token(args.date) if args.date else None,
                "mine": args.mine,
                "limit": args.limit,
            }
            if args.dry_run:
                return dry_run_response("logtime.list", provider.preview_list_logtime(args.task_id, filters))
            result = provider.list_logtime(args.task_id, filters)
            return {"ok": True, "operation": "logtime.list", **result}
        status_filters = {
            "date": resolve_date_token(args.date) if args.date else None,
            "project": args.project or config.project,
            "status": None,
            "query": args.query,
            "mine": args.mine,
            "related": args.related,
            "assignee": config.assignee,
            "today": False,
            "missing_only": False,
            "limit": None,
        }
        if args.dry_run:
            return dry_run_response("logtime.list", provider.preview_logtime_status(status_filters))
        status_result = provider.logtime_status(status_filters)
        return {"ok": True, "operation": "logtime.list", **flatten_logtime_status(status_result, args.limit)}
    if args.logtime_command == "timesheet":
        filters = {"date": resolve_date_token(args.date)}
        if args.dry_run:
            return dry_run_response("logtime.timesheet", provider.preview_timesheet(filters))
        result = provider.timesheet(filters)
        return {"ok": True, "operation": "logtime.timesheet", **result}
    if args.logtime_command not in {"status", "check"}:
        raise ValidationError("Unsupported logtime command.", {"logtime_command": args.logtime_command})
    filters = {
        "date": resolve_date_token(args.date),
        "project": args.project or config.project,
        "status": args.status,
        "query": args.query,
        "mine": args.mine,
        "related": args.related,
        "assignee": config.assignee,
        "today": args.today,
        "missing_only": args.missing_only,
        "limit": args.limit,
    }
    if args.dry_run:
        return dry_run_response("logtime.status", provider.preview_logtime_status(filters))
    result = provider.logtime_status(filters)
    return {"ok": True, "operation": "logtime.status", **result}


def flatten_logtime_status(status_result: dict[str, Any], limit: int | None) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for task in status_result.get("tasks") or []:
        for log in task.get("logtimes") or []:
            entries.append(
                {
                    **log,
                    "workflow_id": task.get("workflow_id"),
                    "title": task.get("title"),
                    "project_id": task.get("project_id"),
                }
            )
    if limit:
        entries = entries[:limit]
    return {
        "date": status_result.get("date"),
        "total_tasks": status_result.get("total_tasks"),
        "total_logs": len(entries),
        "total_hours": round(sum(float(entry.get("hours") or 0) for entry in entries), 2),
        "logtimes": entries,
    }


def run_subtask(args: argparse.Namespace, config: Config, provider: Provider) -> dict[str, Any]:
    filters = {
        "parent_id": args.parent_id or config.parent_id,
        "project": args.project or config.project,
        "status": args.status,
        "query": args.query,
        "related": args.related,
        "assignee": config.assignee,
        "today": args.today,
        "limit": args.limit,
        "recursive": args.recursive,
    }
    if args.dry_run:
        return dry_run_response("subtask.list", provider.preview_list_subtasks(filters))
    return {"ok": True, "operation": "subtask.list", "subtasks": provider.list_subtasks(filters)}


def run_task(
    args: argparse.Namespace,
    config: Config,
    provider: Provider,
    store: IdempotencyStore,
) -> dict[str, Any]:
    command = args.task_command
    if command == "create":
        return create_issue(args, config, provider, store, "task.create")
    if command == "list":
        filters = {
            "parent_id": args.parent_id or config.parent_id,
            "project": args.project or config.project,
            "sprint": resolve_sprint(args.sprint, config),
            "status": args.status,
            "query": args.query,
            "mine": args.mine,
            "related": args.related,
            "today": args.today,
            "assignee": config.assignee,
            "limit": args.limit,
        }
        if args.dry_run:
            return dry_run_response("task.list", provider.preview_list_tasks(filters))
        return {"ok": True, "operation": "task.list", "tasks": provider.list_tasks(filters)}
    if command == "show":
        return {"ok": True, "operation": "task.show", "task": provider.show_task(args.id)}
    if command == "update":
        return run_task_update_command("update", args, config, provider, "task.update")
    if command in STATUS_SHORTCUTS:
        return run_task_update_command(command, args, config, provider, f"task.{command}")
    raise ValidationError("Unsupported task command.", {"task_command": command})


def run_task_update_command(
    command: str,
    args: argparse.Namespace,
    config: Config,
    provider: Provider,
    operation: str | None = None,
) -> dict[str, Any]:
    issue_name = "subtask" if getattr(args, "command", "") in {"subtask", "sub-task"} else "task"
    operation = operation or f"{issue_name}.{command}"
    if command in STATUS_SHORTCUTS:
        status_name = STATUS_SHORTCUTS[command]
        request = TaskUpdate(status=status_name)
        if args.dry_run:
            return dry_run_response(operation, provider.preview_update_task(args.id, request))
        return {
            "ok": True,
            "operation": operation,
            issue_name: provider.update_task(args.id, request),
        }

    request = build_task_update(args, config)
    if args.dry_run:
        return dry_run_response(operation, provider.preview_update_task(args.id, request))
    return {
        "ok": True,
        "operation": operation,
        issue_name: provider.update_task(args.id, request),
    }


def build_task_update(args: argparse.Namespace, config: Config) -> TaskUpdate:
    progress = None
    if args.progress is not None:
        try:
            progress = normalize_progress_value(args.progress)
        except ValueError as exc:
            raise ValidationError("Progress must be a number from 0 to 100.", {"progress": args.progress}) from exc
    return TaskUpdate(
        status=args.status,
        title=args.title,
        desc=read_file(args.desc_file) if args.desc_file else args.desc,
        sprint=resolve_sprint(args.sprint, config) if args.sprint else None,
        labels=args.label,
        estimate=args.estimate,
        assignee=args.assignee,
        progress=progress,
    )


def run_issue_create(
    args: argparse.Namespace,
    config: Config,
    provider: Provider,
    store: IdempotencyStore,
) -> dict[str, Any]:
    if args.issue_command != "create":
        raise ValidationError("Unsupported issue command.", {"issue_command": args.issue_command})
    return create_issue(args, config, provider, store, f"{args.issue_kind}.create")


def create_issue(
    args: argparse.Namespace,
    config: Config,
    provider: Provider,
    store: IdempotencyStore,
    operation: str,
) -> dict[str, Any]:
    request = build_task_create(args, config)
    return mutate_with_idempotency(
        provider=provider,
        store=store,
        operation=operation,
        external_id=request.external_id,
        request=request.to_dict(),
        dry_run=args.dry_run,
        preview=lambda: provider.preview_create_task(request),
        call=lambda: provider.create_task(request),
    )


def run_log(
    args: argparse.Namespace,
    config: Config,
    provider: Provider,
    store: IdempotencyStore,
) -> dict[str, Any]:
    content = read_file(args.from_file) if args.from_file else args.content
    if not content:
        raise ValidationError("Log content is required. Pass content or --from-file.")
    request = WorklogCreate(
        task_id=args.task_id,
        content=content,
        time_spent=args.time_spent,
        log_type=args.type,
        log_date=args.date,
        external_id=args.external_id,
    )
    return mutate_with_idempotency(
        provider=provider,
        store=store,
        operation="worklog.create",
        external_id=request.external_id,
        request=request.to_dict(),
        dry_run=args.dry_run,
        preview=lambda: provider.preview_worklog(request),
        call=lambda: provider.add_worklog(request),
    )


def run_whoami(args: argparse.Namespace, provider: Provider) -> dict[str, Any]:
    if args.dry_run:
        return dry_run_response("whoami", provider.preview_whoami())
    return {
        "ok": True,
        "operation": "whoami",
        "user": provider.whoami(),
    }


def run_history(args: argparse.Namespace, provider: Provider) -> dict[str, Any]:
    if args.dry_run:
        return dry_run_response("history.list", provider.preview_history(args.id))
    entries = provider.history(args.id)
    entries = limit_rows_cli(entries, args.limit)
    return {"ok": True, "operation": "history.list", "task_id": args.id, "history": entries}


def run_activity(args: argparse.Namespace, provider: Provider) -> dict[str, Any]:
    filters = {
        "project": args.project,
        "mine": args.mine,
        "user_id": args.user_id,
        "limit": args.limit,
    }
    if args.dry_run:
        return dry_run_response("activity.list", provider.preview_activity(filters))
    entries = provider.activity(filters)
    return {"ok": True, "operation": "activity.list", "activity": entries}


def limit_rows_cli(rows: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if not limit:
        return rows
    return rows[:limit]


def build_task_create(args: argparse.Namespace, config: Config) -> TaskCreate:
    file_values = read_task_file(args.from_file) if args.from_file else {}
    kind = getattr(args, "issue_kind", None) or file_values.get("kind") or "task"
    title = build_issue_title(kind, args, file_values)
    if not title:
        raise ValidationError("Task title is required. Pass --title or --from-file.")
    desc = args.desc
    if args.desc_file:
        desc = read_file(args.desc_file)
    elif file_values.get("desc") and not desc:
        desc = str(file_values["desc"])
    return TaskCreate(
        title=str(title),
        kind=str(kind),
        desc=desc,
        sprint=resolve_sprint(args.sprint or file_values.get("sprint"), config),
        labels=args.label or list(file_values.get("labels") or []),
        estimate=args.estimate or file_values.get("estimate"),
        assignee=args.assignee or file_values.get("assignee") or config.assignee,
        project=args.project or file_values.get("project") or config.project,
        parent_id=args.parent_id or file_values.get("parent_id") or config.parent_id,
        external_id=args.external_id or file_values.get("external_id"),
    )


def build_issue_title(kind: str, args: argparse.Namespace, file_values: dict[str, Any]) -> str:
    raw_title = args.title or file_values.get("title")
    if kind in {"task", "subtask"}:
        if not raw_title:
            return ""
        role = getattr(args, "role", None) or file_values.get("role")
        return with_role_prefix(str(raw_title), role)
    if kind == "release":
        if raw_title:
            return with_fixed_prefix(str(raw_title), "RELEASE")
        version = getattr(args, "version", None) or file_values.get("version")
        env = getattr(args, "env", None) or file_values.get("env") or "Production"
        if not version:
            raise ValidationError("Release requires --version or --title.")
        return f"[RELEASE] Ver {normalize_version(version)} {env}"
    if kind == "hotfix":
        if raw_title:
            return with_fixed_prefix(str(raw_title), "HOTFIX")
        version = getattr(args, "version", None) or file_values.get("version")
        module = getattr(args, "module", None) or file_values.get("module")
        issue = getattr(args, "issue", None) or file_values.get("issue")
        missing = [name for name, value in {"version": version, "module": module, "issue": issue}.items() if not value]
        if missing:
            raise ValidationError("Hotfix requires --version, --module and --issue, or --title.", {"missing": missing})
        return f"[HOTFIX] Ver {normalize_version(version)} {module} {issue}"
    raise ValidationError("Unsupported issue kind.", {"kind": kind})


def with_role_prefix(title: str, role: object | None) -> str:
    if not role:
        return title
    role_text = str(role).strip().upper()
    if title.lstrip().startswith("["):
        return title
    return f"[{role_text}] {title}"


def with_fixed_prefix(title: str, prefix: str) -> str:
    if title.lstrip().upper().startswith(f"[{prefix}]"):
        return title
    return f"[{prefix}] {title}"


def normalize_version(version: object) -> str:
    text = str(version).strip()
    return text[1:] if text.lower().startswith("v") else text


def mutate_with_idempotency(
    provider: Provider,
    store: IdempotencyStore,
    operation: str,
    external_id: str | None,
    request: dict[str, Any],
    dry_run: bool,
    preview: Any,
    call: Any,
) -> dict[str, Any]:
    key = external_id or f"hash:{content_hash(request)}"
    existing = store.get(provider.name, operation, key)
    if dry_run:
        return {
            "ok": True,
            "operation": operation,
            "dry_run": True,
            "idempotency_key": key,
            "would_send": preview(),
            "existing": existing,
        }
    if existing:
        return {
            "ok": True,
            "operation": operation,
            "idempotent": True,
            "idempotency_key": key,
            "record": existing["result"],
        }
    result = call()
    record = {
        "operation": operation,
        "request": request,
        "result": result,
    }
    store.put(provider.name, operation, key, record)
    return {
        "ok": True,
        "operation": operation,
        "idempotent": False,
        "idempotency_key": key,
        "record": result,
    }


def build_provider(config: Config) -> Provider:
    if config.provider == "mock":
        if config.data_path is None:
            raise ConfigError("Missing mock data path.")
        return MockProvider(config.data_path)
    if config.provider == "beca":
        return BecaProvider(config)
    raise ConfigError("Unsupported provider.", {"provider": config.provider})


def read_task_file(path: str) -> dict[str, Any]:
    text = read_file(path)
    stripped = text.strip()
    if not stripped:
        return {}
    if stripped.startswith("{"):
        data = json.loads(stripped)
        if not isinstance(data, dict):
            raise ValidationError("--from-file JSON must be an object.")
        return data
    lines = [line.rstrip() for line in text.splitlines()]
    title = next((line.strip("# ").strip() for line in lines if line.strip()), "")
    desc_lines = lines[1:] if lines and title else []
    return {"title": title, "desc": "\n".join(desc_lines).strip()}


def read_file(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def resolve_sprint(value: Any, config: Config) -> str | None:
    if value == "current":
        return config.current_sprint
    return str(value) if value else None


def dry_run_response(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "operation": operation,
        "dry_run": True,
        "would_send": payload,
    }


def emit_success(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    operation = result.get("operation", "ok")
    if result.get("dry_run"):
        print(f"{operation}: dry run")
        return
    if operation == "project.list":
        print_project_rows(result.get("projects") or [])
        return
    if operation == "story.list":
        print_story_rows(result.get("stories") or [])
        return
    if operation == "task.list":
        print_task_rows(result.get("tasks") or [])
        return
    if operation == "subtask.list":
        print_task_rows(result.get("subtasks") or [])
        return
    if operation == "logtime.status":
        print_logtime_status(result)
        return
    if operation == "logtime.list":
        print_logtime_rows(result)
        return
    if result.get("idempotent"):
        print(f"{operation}: existing record")
    else:
        print(f"{operation}: ok")


def emit_error(error: CliError, as_json: bool) -> None:
    if as_json:
        print(json.dumps(error.to_dict(), ensure_ascii=False), file=sys.stdout)
    else:
        print(f"{error.code}: {error.message}", file=sys.stderr)


def wants_json(argv: Sequence[str]) -> bool:
    return "--json" in argv


def print_project_rows(projects: list[dict[str, Any]]) -> None:
    if not projects:
        print("No projects found.")
        return
    print(f"{'#':>2}  {'PROJECT_ID':<12}  {'COUNT':<8}  PROJECT_NAME")
    for index, project in enumerate(projects, start=1):
        name = single_line(project.get("project_name"))
        print(f"{index:>2}  {str(project.get('project_id') or ''):<12}  {str(project.get('count') or ''):<8}  {name}")


def print_story_rows(stories: list[dict[str, Any]]) -> None:
    if not stories:
        print("No stories found.")
        return
    print(f"{'#':>2}  {'WORKFLOW_ID':<12}  {'PROJECT_ID':<12}  {'STATUS':<12}  TITLE")
    for index, story in enumerate(stories, start=1):
        workflow_id = story.get("workflow_id") or story.get("id") or ""
        project_id = story.get("project_id") or story.get("project") or ""
        status = story.get("status") or ""
        title = single_line(story.get("title"))
        print(f"{index:>2}  {str(workflow_id):<12}  {str(project_id):<12}  {str(status):<12}  {title}")


def print_task_rows(tasks: list[dict[str, Any]]) -> None:
    if not tasks:
        print("No tasks found.")
        return
    print(f"{'#':>2}  {'WORKFLOW_ID':<12}  {'PROJECT_ID':<12}  {'STATUS':<12}  TITLE")
    for index, task in enumerate(tasks, start=1):
        workflow_id = task.get("workflow_id") or task.get("id") or task.get("workId") or ""
        project_id = task.get("project_id") or task.get("project") or ""
        status = task.get("status") or ""
        title = single_line(task.get("title"))
        print(f"{index:>2}  {str(workflow_id):<12}  {str(project_id):<12}  {str(status):<12}  {title}")


def print_logtime_status(result: dict[str, Any]) -> None:
    tasks = result.get("tasks") or []
    print(
        f"Date: {result.get('date')} | "
        f"logged: {result.get('logged_tasks', 0)} | "
        f"missing: {result.get('missing_tasks', 0)} | "
        f"tasks: {result.get('returned_tasks', len(tasks))}"
    )
    if not tasks:
        return
    print(f"{'#':>2}  {'WORKFLOW_ID':<12}  {'STATUS':<12}  {'HOURS':>6}  {'LOGGED':<6}  TITLE")
    for index, task in enumerate(tasks, start=1):
        workflow_id = task.get("workflow_id") or task.get("id") or ""
        status = task.get("status") or ""
        hours = task.get("logtime_hours") or 0
        logged = "yes" if task.get("has_logtime") else "no"
        title = single_line(task.get("title"))
        print(f"{index:>2}  {str(workflow_id):<12}  {str(status):<12}  {float(hours):>6.2f}  {logged:<6}  {title}")


def print_logtime_rows(result: dict[str, Any]) -> None:
    logs = result.get("logtimes") or []
    if result.get("task_id"):
        header_scope = f"Task: {result['task_id']}"
    else:
        header_scope = f"Date: {result['date']}" if result.get("date") else "Date: all"
    print(
        f"{header_scope} | "
        f"logs: {result.get('total_logs', len(logs))} | "
        f"hours: {float(result.get('total_hours') or 0):.2f}"
    )
    if not logs:
        return
    per_task = "task_id" not in result
    if per_task:
        print(f"{'#':>2}  {'WORKFLOW_ID':<12}  {'DATE':<10}  {'HOURS':>6}  {'ACTION':<12}  DESCRIPTION")
    else:
        print(f"{'#':>2}  {'DATE':<10}  {'HOURS':>6}  {'ACTION':<12}  DESCRIPTION")
    for index, log in enumerate(logs, start=1):
        date_text = str(log.get("date") or "")[:10]
        hours = float(log.get("hours") or 0)
        action = single_line(log.get("action"), 12)
        description = single_line(log.get("description"), 96)
        if per_task:
            workflow_id = str(log.get("workflow_id") or "")
            print(f"{index:>2}  {workflow_id:<12}  {date_text:<10}  {hours:>6.2f}  {action:<12}  {description}")
        else:
            print(f"{index:>2}  {date_text:<10}  {hours:>6.2f}  {action:<12}  {description}")


def single_line(value: object, max_length: int = 96) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


if __name__ == "__main__":
    raise SystemExit(main())
