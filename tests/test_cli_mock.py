from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from taskcli.cli import main


class CliMockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = {
            "TASKCLI_PROVIDER": "mock",
            "TASKCLI_DATA_PATH": str(self.root / "mock_store.json"),
            "TASKCLI_IDEMPOTENCY_PATH": str(self.root / "idempotency.json"),
            "TASKCLI_PROJECT": "project-a",
            "TASKCLI_CURRENT_SPRINT": "sprint-1",
            "TASKCLI_ASSIGNEE": "env-user",
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, argv: list[str], stdin: str | None = None) -> tuple[int, dict]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, self.env, clear=False), redirect_stdout(stdout), redirect_stderr(stderr):
            if stdin is None:
                code = main(argv)
            else:
                with patch("sys.stdin", io.StringIO(stdin)):
                    code = main(argv)
        self.assertEqual("", stderr.getvalue())
        return code, json.loads(stdout.getvalue())

    def test_create_list_and_flag_precedence(self) -> None:
        code, created = self.run_cli(
            [
                "task",
                "create",
                "--json",
                "--title",
                "Build API",
                "--sprint",
                "current",
                "--assignee",
                "flag-user",
            ]
        )
        self.assertEqual(0, code)
        self.assertEqual("Build API", created["record"]["title"])
        self.assertEqual("sprint-1", created["record"]["sprint"])
        self.assertEqual("flag-user", created["record"]["assignee"])

        code, listed = self.run_cli(["task", "list", "--json", "--sprint", "current"])
        self.assertEqual(0, code)
        self.assertEqual(1, len(listed["tasks"]))
        self.assertEqual("Build API", listed["tasks"][0]["title"])

    def test_create_idempotency_by_external_id(self) -> None:
        argv = [
            "task",
            "create",
            "--json",
            "--title",
            "Idempotent task",
            "--external-id",
            "meeting-1-task-1",
        ]
        _, first = self.run_cli(argv)
        _, second = self.run_cli(argv)
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(first["record"]["id"], second["record"]["id"])

    def test_dry_run_does_not_create(self) -> None:
        code, dry = self.run_cli(["task", "create", "--json", "--dry-run", "--title", "No write"])
        self.assertEqual(0, code)
        self.assertTrue(dry["dry_run"])
        self.assertNotIn("provider", dry)

        _, listed = self.run_cli(["task", "list", "--json"])
        self.assertEqual([], listed["tasks"])

    def test_whoami(self) -> None:
        code, current = self.run_cli(["whoami", "--json"])
        self.assertEqual(0, code)
        self.assertEqual("P:mock", current["user"]["assignee_id"])
        self.assertNotIn("provider", current)
        self.assertNotIn("provider", current["user"])

        code, dry = self.run_cli(["whoami", "--json", "--dry-run"])
        self.assertEqual(0, code)
        self.assertTrue(dry["dry_run"])
        self.assertNotIn("provider", dry)

    def test_project_and_story_lookup(self) -> None:
        self.run_cli(["task", "create", "--json", "--title", "Build API", "--project", "project-a"])
        self.run_cli(["task", "create", "--json", "--title", "Write docs", "--project", "project-b"])

        code, projects = self.run_cli(["project", "list", "--json", "--query", "project-b"])
        self.assertEqual(0, code)
        self.assertEqual("project.list", projects["operation"])
        self.assertEqual([{"project_id": "project-b", "project_name": "project-b", "count": 1}], projects["projects"])

        code, stories = self.run_cli(["story", "list", "--json", "--project", "project-a"])
        self.assertEqual(0, code)
        self.assertEqual("story.list", stories["operation"])
        self.assertEqual(1, len(stories["stories"]))
        self.assertEqual("Build API", stories["stories"][0]["title"])
        self.assertEqual("1", stories["stories"][0]["workflow_id"])

        code, dry = self.run_cli(["story", "list", "--json", "--dry-run", "--query", "api"])
        self.assertEqual(0, code)
        self.assertTrue(dry["dry_run"])
        self.assertEqual("story.list", dry["operation"])

    def test_task_list_by_parent(self) -> None:
        self.run_cli(
            [
                "task",
                "create",
                "--json",
                "--title",
                "Child API",
                "--project",
                "project-a",
                "--parent-id",
                "story-1",
            ]
        )
        self.run_cli(
            [
                "task",
                "create",
                "--json",
                "--title",
                "Other child",
                "--project",
                "project-a",
                "--parent-id",
                "story-2",
            ]
        )

        code, tasks = self.run_cli(["task", "list", "--json", "--parent-id", "story-1"])
        self.assertEqual(0, code)
        self.assertEqual("task.list", tasks["operation"])
        self.assertEqual(1, len(tasks["tasks"]))
        self.assertEqual("Child API", tasks["tasks"][0]["title"])

        code, dry = self.run_cli(["task", "list", "--json", "--parent-id", "story-1", "--dry-run"])
        self.assertEqual(0, code)
        self.assertTrue(dry["dry_run"])
        self.assertEqual("task.list", dry["operation"])

    def test_update_progress_for_task_and_subtask(self) -> None:
        _, task = self.run_cli(["task", "create", "--json", "--title", "Task progress"])
        task_id = task["record"]["id"]

        code, updated = self.run_cli(["task", "update", task_id, "--json", "--progress", "50"])
        self.assertEqual(0, code)
        self.assertEqual("task.update", updated["operation"])
        self.assertEqual("50%", updated["task"]["progress"])

        _, subtask = self.run_cli(
            [
                "subtask",
                "create",
                "--json",
                "--title",
                "Subtask progress",
                "--parent-id",
                task_id,
            ]
        )
        subtask_id = subtask["record"]["id"]
        code, dry = self.run_cli(["subtask", "update", subtask_id, "--json", "--progress", "75%", "--dry-run"])
        self.assertEqual(0, code)
        self.assertTrue(dry["dry_run"])
        self.assertEqual("75%", dry["would_send"]["changes"]["progress"])

        code, updated_subtask = self.run_cli(["subtask", "update", subtask_id, "--json", "--progress", "75%"])
        self.assertEqual(0, code)
        self.assertEqual("subtask.update", updated_subtask["operation"])
        self.assertEqual("75%", updated_subtask["subtask"]["progress"])

    def test_log_and_idempotency(self) -> None:
        _, created = self.run_cli(["task", "create", "--json", "--title", "Log target"])
        task_id = created["record"]["id"]
        argv = [
            "log",
            task_id,
            "Implemented the parser",
            "--json",
            "--time",
            "2h",
            "--type",
            "progress",
            "--external-id",
            "daily-log-1",
        ]
        _, first = self.run_cli(argv)
        _, second = self.run_cli(argv)
        self.assertEqual(task_id, first["record"]["task_id"])
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(first["record"]["id"], second["record"]["id"])

    def test_logtime_list(self) -> None:
        _, created = self.run_cli(["task", "create", "--json", "--title", "Log target"])
        task_id = created["record"]["id"]
        self.run_cli(
            [
                "log",
                task_id,
                "Implemented the parser",
                "--json",
                "--time",
                "2h",
                "--date",
                "2026-07-02",
            ]
        )

        code, listed = self.run_cli(["logtime", "list", task_id, "--json", "--date", "2026-07-02"])
        self.assertEqual(0, code)
        self.assertEqual("logtime.list", listed["operation"])
        self.assertEqual(task_id, listed["task_id"])
        self.assertEqual(1, listed["total_logs"])
        self.assertEqual(2.0, listed["total_hours"])
        self.assertEqual("Implemented the parser", listed["logtimes"][0]["description"])

    def test_logtime_status(self) -> None:
        _, first_task = self.run_cli(
            [
                "subtask",
                "create",
                "--json",
                "--title",
                "Logged subtask",
                "--project",
                "project-a",
                "--parent-id",
                "task-1",
            ]
        )
        _, second_task = self.run_cli(
            [
                "subtask",
                "create",
                "--json",
                "--title",
                "Missing subtask",
                "--project",
                "project-a",
                "--parent-id",
                "task-1",
            ]
        )
        self.run_cli(
            [
                "log",
                first_task["record"]["id"],
                "Finished parser",
                "--json",
                "--time",
                "2h",
                "--date",
                "2026-07-02",
                "--external-id",
                "2026-07-02:1:progress",
            ]
        )

        code, status = self.run_cli(["logtime", "status", "--json", "--date", "2026-07-02", "--project", "project-a"])
        self.assertEqual(0, code)
        self.assertEqual("logtime.status", status["operation"])
        self.assertEqual(2, status["total_tasks"])
        self.assertEqual(1, status["logged_tasks"])
        self.assertEqual(1, status["missing_tasks"])
        self.assertEqual(2.0, status["tasks"][0]["logtime_hours"])
        self.assertTrue(status["tasks"][0]["has_logtime"])
        self.assertFalse(status["tasks"][1]["has_logtime"])
        self.assertEqual(second_task["record"]["id"], status["tasks"][1]["workflow_id"])

        code, missing = self.run_cli(
            ["logtime", "status", "--json", "--date", "2026-07-02", "--project", "project-a", "--missing-only"]
        )
        self.assertEqual(0, code)
        self.assertEqual(1, missing["returned_tasks"])
        self.assertEqual("Missing subtask", missing["tasks"][0]["title"])

    def test_subtask_list_by_parent(self) -> None:
        self.run_cli(
            [
                "subtask",
                "create",
                "--json",
                "--title",
                "Child parser",
                "--project",
                "project-a",
                "--parent-id",
                "task-1",
            ]
        )
        self.run_cli(
            [
                "subtask",
                "create",
                "--json",
                "--title",
                "Child docs",
                "--project",
                "project-a",
                "--parent-id",
                "task-2",
            ]
        )

        code, subtasks = self.run_cli(["subtask", "list", "--json", "--parent-id", "task-1"])
        self.assertEqual(0, code)
        self.assertEqual("subtask.list", subtasks["operation"])
        self.assertEqual(1, len(subtasks["subtasks"]))
        self.assertEqual("Child parser", subtasks["subtasks"][0]["title"])

        code, dry = self.run_cli(["subtask", "list", "--json", "--parent-id", "task-1", "--dry-run"])
        self.assertEqual(0, code)
        self.assertTrue(dry["dry_run"])
        self.assertEqual("subtask.list", dry["operation"])

    def test_subtask_list_related(self) -> None:
        self.run_cli(
            [
                "subtask",
                "create",
                "--json",
                "--title",
                "My subtask",
                "--project",
                "project-a",
                "--parent-id",
                "task-1",
            ]
        )
        self.run_cli(
            [
                "subtask",
                "create",
                "--json",
                "--title",
                "Other subtask",
                "--project",
                "project-a",
                "--parent-id",
                "task-1",
                "--assignee",
                "other-user",
            ]
        )

        code, subtasks = self.run_cli(["subtask", "list", "--json", "--parent-id", "task-1", "--related"])
        self.assertEqual(0, code)
        self.assertEqual(1, len(subtasks["subtasks"]))
        self.assertEqual("My subtask", subtasks["subtasks"][0]["title"])

    def test_task_from_file_and_log_from_stdin(self) -> None:
        task_file = self.root / "task.md"
        task_file.write_text("# Parsed title\n\nParsed description", encoding="utf-8")
        _, created = self.run_cli(["task", "create", "--json", "--from-file", str(task_file)])
        self.assertEqual("Parsed title", created["record"]["title"])
        self.assertEqual("Parsed description", created["record"]["desc"])

        task_id = created["record"]["id"]
        _, log = self.run_cli(["log", task_id, "--json", "--from-file", "-"], stdin="stdin worklog")
        self.assertEqual("stdin worklog", log["record"]["content"])

    def test_focused_create_commands(self) -> None:
        _, subtask = self.run_cli(
            [
                "subtask",
                "create",
                "--json",
                "--role",
                "QC",
                "--title",
                "Thiết kế testcase đăng nhập",
                "--parent-id",
                "parent-1",
            ]
        )
        self.assertEqual("subtask", subtask["record"]["kind"])
        self.assertEqual("[QC] Thiết kế testcase đăng nhập", subtask["record"]["title"])

        _, release = self.run_cli(
            [
                "release",
                "create",
                "--json",
                "--version",
                "v2.4.0",
                "--env",
                "Production",
                "--parent-id",
                "parent-1",
            ]
        )
        self.assertEqual("release", release["record"]["kind"])
        self.assertEqual("[RELEASE] Ver 2.4.0 Production", release["record"]["title"])

        _, hotfix = self.run_cli(
            [
                "hotfix",
                "create",
                "--json",
                "--version",
                "v2.4.1",
                "--module",
                "Đăng nhập",
                "--issue",
                "lỗi token",
                "--parent-id",
                "parent-1",
            ]
        )
        self.assertEqual("hotfix", hotfix["record"]["kind"])
        self.assertEqual("[HOTFIX] Ver 2.4.1 Đăng nhập lỗi token", hotfix["record"]["title"])


if __name__ == "__main__":
    unittest.main()
