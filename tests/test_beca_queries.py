from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from urllib.error import URLError

from beca_work.actions import BecaResponseError, get_task_resources, get_work_children, get_work_in_process
from taskcli.config import Config, load_config
from taskcli.errors import ProviderError
from taskcli.models import task_matches_dates
from taskcli.providers.beca import BecaProvider, child_task_row, filter_task_rows


def work(work_id, *, role="Nguoixuly", user="P:1", start="2026-10-01", end=""):
    return {
        "userWorkflowId": work_id,
        "title": work_id,
        "start": start,
        "end": end,
        "userPartner": [{"id": user, "userType": role}],
    }


class TaskQueryTests(unittest.TestCase):
    def setUp(self):
        self.provider = BecaProvider(Config())
        self.provider.client = Mock()
        self.mine = {"mine": True, "related_user_id": "P:1"}

    def test_assignee_must_match_role_on_same_user(self):
        follower = work("follower", role="Nguoitheodoi")
        follower["userPartner"].append({"id": "P:2", "userType": "Nguoixuly"})
        rows = [child_task_row(item, "story") for item in [
            follower, work("assigned"), work("assigner", role="Nguoigiao"),
        ]]
        self.assertEqual(["assigned"], [r["workflow_id"] for r in filter_task_rows(rows, self.mine)])
        related = {"related": True, "related_user_id": "P:1"}
        self.assertEqual(3, len(filter_task_rows(rows, related)))

    def test_assignee_email_fallback(self):
        item = work("assigned", user="")
        item["userPartner"][0]["email"] = "ME@example.com"
        rows = [child_task_row(item, "story")]
        self.assertEqual(rows, filter_task_rows(rows, {"mine": True, "related_user_email": "me@example.com"}))

    def test_range_overlaps_inclusively(self):
        filters = {"date_from": "2026-11-01", "date_to": "2026-11-27"}
        for start, end, expected in [
            ("2026-10-01 08:00:00", "", True),
            ("2026-10-01", "2026-11-01", True),
            ("2026-11-27", "2026-12-01", True),
            ("2026-10-01", "2026-10-31", False),
            ("2026-11-28", "", False),
            ("", "", False),
            ("2026-11-10", "2026-11-05", False),
        ]:
            with self.subTest(start=start, end=end):
                self.assertEqual(expected, task_matches_dates(start, end, filters))
        self.assertTrue(task_matches_dates("2026-01-01", "", {"date_from": "2026-11-01"}))
        self.assertFalse(task_matches_dates("2026-12-01", "", {"date_to": "2026-11-27"}))

    @patch("taskcli.providers.beca.get_work_in_process")
    def test_pagination_deduplicates_ids(self, get_page):
        get_page.side_effect = [[work("a"), work("b")], [work("b"), work("c")], []]
        rows = self.provider.list_stories({"row_number": 2})
        self.assertEqual(["a", "b", "c"], [row["workflow_id"] for row in rows])
        self.assertEqual([1, 2, 3], [call.kwargs["page_number"] for call in get_page.call_args_list])

    @patch("taskcli.providers.beca.get_work_in_process")
    def test_repeated_full_page_fails_instead_of_looping(self, get_page):
        get_page.return_value = [work("a"), work("b")]
        with self.assertRaises(ProviderError):
            self.provider.list_stories({"row_number": 2})
        self.assertEqual(2, get_page.call_count)

    @patch("taskcli.providers.beca.get_work_children")
    @patch("taskcli.providers.beca.get_work_in_process")
    @patch("taskcli.providers.beca.get_current_user")
    def test_today_does_not_prune_older_parent_and_limit_stops_scan(self, get_user, get_page, get_children):
        get_user.return_value = {"id": "P:1"}
        get_page.return_value = [work("old-parent"), work("next-parent")]
        get_children.return_value = [work("today", start=date.today().isoformat()), work("other")]
        rows = self.provider.list_tasks({"mine": True, "today": True, "limit": 1})
        self.assertEqual(["today"], [row["workflow_id"] for row in rows])
        get_children.assert_called_once_with(self.provider.client, "old-parent")
        self.provider.whoami()
        self.assertEqual(1, get_user.call_count)

    @patch("taskcli.providers.beca.get_work_children")
    @patch("taskcli.providers.beca.get_current_user")
    def test_recursive_finds_assigned_child_under_other_assignee(self, get_user, get_children):
        get_user.return_value = {"id": "P:1"}
        graph = {
            "root": [work("parent", user="P:2")],
            "parent": [work("child"), work("child")],
            "child": [work("root")],
        }
        get_children.side_effect = lambda client, parent: graph[parent]
        rows = self.provider.list_tasks({"parent_id": "root", "mine": True, "recursive": True})
        self.assertEqual(["child"], [row["workflow_id"] for row in rows])
        self.assertEqual(3, get_children.call_count)

    @patch("taskcli.providers.beca.get_work_children")
    def test_recursive_limit_skips_unneeded_descendant_requests(self, get_children):
        get_children.return_value = [work("child")]
        self.assertEqual(1, len(self.provider.list_tasks({"parent_id": "root", "recursive": True, "limit": 1})))
        self.assertEqual(1, get_children.call_count)

    @patch("taskcli.providers.beca.get_current_user")
    @patch("taskcli.providers.beca.get_timesheet_report")
    def test_timesheet_fetches_every_intervening_month(self, report, get_user):
        report.return_value = []
        get_user.return_value = {"id": "P:1"}
        self.provider.timesheet({"date": "2026-04-01", "days": 65})
        months = [call.args[1] for call in report.call_args_list]
        self.assertEqual(["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"], months)

    def test_bad_api_data_not_silently_empty(self):
        client = Mock()
        client.request_json.return_value = None
        with self.assertRaises(BecaResponseError):
            get_work_in_process(client, False)
        with self.assertRaises(BecaResponseError):
            get_work_children(client, "root")
        self.provider.client = client
        with self.assertRaises(ProviderError):
            self.provider.list_tasks({})

    def test_config_defaults_without_config_file(self):
        with TemporaryDirectory() as tmp:
            cfg = load_config(str(Path(tmp) / "missing.toml"), env={"TASKCLI_TIMEOUT": "5"})
            self.assertEqual("beca", cfg.provider)
            self.assertEqual(5, cfg.timeout)

    @patch("taskcli.providers.beca.get_work_detail")
    @patch("taskcli.providers.beca.get_work_children")
    @patch("taskcli.providers.beca.get_work_in_process")
    @patch("taskcli.providers.beca.get_current_user")
    def test_all_scope_includes_roots_deduplicates_and_checks_roles(self, get_user, pages, children, detail):
        get_user.return_value = {"id": "P:1"}
        missing_roles = work("active")
        missing_roles["userPartner"] = []
        pages.side_effect = lambda *args, **kwargs: (
            [missing_roles] if kwargs["work_type"] == "Xử lý" else [missing_roles, work("old"), work("follower", role="Nguoitheodoi")]
        )
        detail.return_value = work("active")
        graph = {"active": [work("child")], "old": [work("child")], "follower": [], "child": []}
        children.side_effect = lambda client, parent: graph[parent]
        rows = self.provider.list_tasks({"scope": "all", "mine": True, "recursive": True})
        self.assertEqual(["active", "old", "child"], [r["workflow_id"] for r in rows])
        self.assertEqual(["Xử lý", "Việc đã xử lý"], [c.kwargs["work_type"] for c in pages.call_args_list])
        self.assertEqual(4, children.call_count)
        detail.assert_called_once_with(self.provider.client, "active", False)

    @patch("taskcli.providers.beca.get_work_detail")
    @patch("taskcli.providers.beca.get_project_works")
    @patch("taskcli.providers.beca.get_current_user")
    def test_project_scope_uses_flat_snapshot_and_hydrates_filtered_rows(self, get_user, get_works, detail):
        get_user.return_value = {"id": "P:1"}
        first = {**work("match"), "userPartner": [], "projectId": "10"}
        second = {**work("old", start="2020-01-01", end="2020-02-01"), "userPartner": [], "projectId": "10"}
        get_works.return_value = [first, second]
        detail.return_value = {**work("match"), "projectId": "10"}
        rows = self.provider.list_tasks({"scope": "project", "project": "10", "mine": True, "date_from": "2026-01-01"})
        self.assertEqual(["match"], [r["workflow_id"] for r in rows])
        get_works.assert_called_once_with(self.provider.client, "10")
        detail.assert_called_once_with(self.provider.client, "match", False)

    def test_completed_task_without_planned_end_uses_completion_date(self):
        old = child_task_row({**work("old"), "statusName": "Done", "dateComplete": "2026-10-31"}, "root")
        feedback = child_task_row({**work("feedback"), "statusName": "Feedback", "dateComplete": "2026-10-31"}, "root")
        open_task = child_task_row({**work("open"), "statusName": "Open", "dateComplete": "2026-10-31"}, "root")
        rows = filter_task_rows([old, feedback, open_task], {"date_from": "2026-11-01"})
        self.assertEqual(["open"], [r["workflow_id"] for r in rows])

    def test_task_resources_api_shapes_and_error(self):
        client = Mock()
        client.request_json.return_value = [{"id": 1}]
        self.assertEqual({"items": [{"id": 1}], "total_items": 1}, get_task_resources(client, "comment", "100"))
        self.assertIn("Work_GetComment?workId=100", client.request_json.call_args.args[0])
        client.request_json.return_value = {"items": [{"name": "x"}], "totalItems": 3}
        self.assertEqual(3, get_task_resources(client, "attachment", "100")["total_items"])
        client.request_json.return_value = None
        with self.assertRaises(BecaResponseError):
            get_task_resources(client, "checklist", "100")

    @patch("taskcli.providers.beca.get_current_user")
    @patch("taskcli.providers.beca.get_timesheet_report")
    def test_explicit_month_includes_first_day_even_on_weekend(self, report, get_user):
        report.return_value = []
        get_user.return_value = {"id": "P:1"}
        result = self.provider.timesheet({"date": "2026-11-30", "date_from": "2026-11-01", "days": 30})
        self.assertEqual("2026-11-01", result["date_from"])
        self.assertEqual("2026-11-30", result["date_to"])
        report.assert_called_once_with(self.provider.client, "2026-11-01", "P:1")

    @patch("taskcli.providers.beca.time.sleep")
    @patch("taskcli.providers.beca.get_work_in_process")
    def test_transient_network_read_retries_once(self, page, sleep):
        page.side_effect = [URLError("temporary outage"), [work("ok")]]
        rows = self.provider.list_stories({})
        self.assertEqual(["ok"], [row["workflow_id"] for row in rows])
        self.assertEqual(2, page.call_count)
        sleep.assert_called_once_with(0.5)


if __name__ == "__main__":
    unittest.main()
