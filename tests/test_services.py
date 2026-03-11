from __future__ import annotations

import unittest

from tempoy_app.services.cache_service import CacheService
from tempoy_app.services.issue_catalog import IssueCatalog
from tempoy_app.services.worklog_service import WorklogService


class _FakeJiraClient:
    def __init__(self, issue_id: str = "101", fallback=(0, 0), bulk_issue_ids=None):
        self.issue_id = issue_id
        self.fallback = fallback
        self.bulk_issue_ids = bulk_issue_ids or {}
        self.issue_id_requests = []
        self.ensure_issue_id_requests = []

    def ensure_issue_ids(self, issue_keys):
        self.ensure_issue_id_requests.append(list(issue_keys))
        if self.bulk_issue_ids:
            return {issue_key: self.bulk_issue_ids[issue_key] for issue_key in issue_keys if issue_key in self.bulk_issue_ids}
        return {issue_key: self.issue_id for issue_key in issue_keys if issue_key}

    def get_issue_id(self, issue_key: str):
        self.issue_id_requests.append(issue_key)
        return self.issue_id

    def sum_worklog_times(self, issue_key: str, account_id: str):
        return self.fallback


class _FakeTempoClient:
    def __init__(self, *, issue_time=(0, 0), daily_total=0, last_logged="2026-03-10", worked_issues=None, raise_issue_time=False):
        self.issue_time = issue_time
        self.daily_total = daily_total
        self.last_logged = last_logged
        self.worked_issues = worked_issues or []
        self.raise_issue_time = raise_issue_time

    def get_recent_worked_issues(self, *, account_id: str, days_back: int):
        return self.worked_issues

    def get_user_issue_time(self, *, issue_key: str, issue_id: str, account_id: str):
        if self.raise_issue_time:
            raise RuntimeError("tempo failure")
        return self.issue_time

    def get_last_logged_date(self, *, issue_key: str, issue_id: str, account_id: str):
        return self.last_logged

    def get_user_daily_total(self, *, account_id: str):
        return self.daily_total


class ServicesTests(unittest.TestCase):
    def test_cache_service_gets_and_invalidates_entries(self) -> None:
        cache = CacheService()
        cache.set("issue:ABC-1", {"ok": True}, ttl_seconds=60, now=100.0)

        self.assertEqual(cache.get("issue:ABC-1", now=120.0), {"ok": True})
        self.assertIsNone(cache.get("issue:ABC-1", now=170.0))

        cache.set("issue:ABC-1", {"ok": True}, ttl_seconds=60, now=100.0)
        cache.invalidate("issue:ABC-1", reason="refresh")
        self.assertIsNone(cache.get("issue:ABC-1", now=120.0))

    def test_issue_catalog_merges_without_duplicate_keys(self) -> None:
        assigned = [{"key": "ABC-1", "fields": {"summary": "Assigned"}}]
        worked = [
            {"key": "ABC-1", "fields": {"summary": "Worked duplicate"}},
            {"key": "ABC-2", "fields": {"summary": "Worked only"}},
        ]

        merged = IssueCatalog.merge_issues(assigned, worked)

        self.assertEqual([issue["key"] for issue in merged], ["ABC-1", "ABC-2"])
        self.assertEqual(merged[0]["fields"]["summary"], "Assigned")

    def test_issue_catalog_builds_and_sorts_snapshots_by_status_then_last_logged(self) -> None:
        catalog = IssueCatalog()
        issues = [
            {
                "key": "ABC-2",
                "fields": {
                    "summary": "Later done",
                    "status": {"name": "Done"},
                    "updated": "2026-03-08T10:00:00+00:00",
                    "parent": {"key": "PARENT-1", "fields": {"summary": "Parent"}},
                },
            },
            {
                "key": "ABC-1",
                "fields": {
                    "summary": "Earlier done",
                    "status": {"name": "Done"},
                    "updated": "2026-03-07T10:00:00+00:00",
                },
            },
            {
                "key": "ABC-3",
                "fields": {
                    "summary": "In progress",
                    "status": {"name": "In Progress"},
                    "updated": "2026-03-09T10:00:00+00:00",
                },
            },
        ]

        snapshots = catalog.build_snapshots(
            issues,
            assigned_keys={"ABC-1", "ABC-2"},
            worked_keys={"ABC-2", "ABC-3"},
            totals_by_key={"ABC-2": (600, 3600)},
            last_logged_by_key={"ABC-2": "2026-03-09", "ABC-1": "2026-03-01"},
        )

        self.assertEqual([snapshot.issue_key for snapshot in snapshots], ["ABC-2", "ABC-1", "ABC-3"])
        self.assertEqual(snapshots[0].parent_or_epic, "PARENT-1: Parent")
        self.assertTrue(snapshots[0].is_recently_worked)
        self.assertEqual((snapshots[0].today_seconds, snapshots[0].total_seconds), (600, 3600))

    def test_issue_catalog_filters_snapshots_by_key_and_summary_without_reordering(self) -> None:
        catalog = IssueCatalog()
        snapshots = catalog.build_snapshots(
            [
                {"key": "ABC-2", "fields": {"summary": "Billing endpoint", "status": {"name": "Done"}, "updated": "2026-03-08T10:00:00+00:00"}},
                {"key": "ABC-1", "fields": {"summary": "Login page polish", "status": {"name": "Done"}, "updated": "2026-03-07T10:00:00+00:00"}},
                {"key": "XYZ-3", "fields": {"summary": "Search dialog", "status": {"name": "In Progress"}, "updated": "2026-03-09T10:00:00+00:00"}},
            ],
            last_logged_by_key={"ABC-2": "2026-03-09", "ABC-1": "2026-03-01"},
        )

        filtered_by_key = catalog.filter_snapshots(snapshots, "ABC")
        filtered_by_summary = catalog.filter_snapshots(snapshots, "search")

        self.assertEqual([snapshot.issue_key for snapshot in filtered_by_key], ["ABC-2", "ABC-1"])
        self.assertEqual([snapshot.issue_key for snapshot in filtered_by_summary], ["XYZ-3"])

    def test_worklog_service_returns_unique_recent_worked_issue_keys(self) -> None:
        jira = _FakeJiraClient()
        tempo = _FakeTempoClient(
            worked_issues=[
                {"issue": {"key": "ABC-1"}},
                {"issue": {"key": "ABC-1"}},
                {"issue": {"key": "ABC-2"}},
            ]
        )
        service = WorklogService(jira, tempo)

        self.assertEqual(service.get_recent_worked_issue_keys(account_id="acc-1", days_back=60), ["ABC-1", "ABC-2"])

    def test_worklog_service_resolves_issue_ids_in_bulk(self) -> None:
        jira = _FakeJiraClient(bulk_issue_ids={"ABC-1": "101", "ABC-2": "202"})
        tempo = _FakeTempoClient()
        service = WorklogService(jira, tempo)

        resolved = service.resolve_issue_ids(["ABC-1", "ABC-2", "ABC-1", "ABC-3"])

        self.assertEqual(resolved, {"ABC-1": "101", "ABC-2": "202"})
        self.assertEqual(jira.ensure_issue_id_requests, [["ABC-1", "ABC-2", "ABC-1", "ABC-3"]])
        self.assertEqual(jira.issue_id_requests, [])

    def test_worklog_service_falls_back_to_jira_when_tempo_returns_zero(self) -> None:
        jira = _FakeJiraClient(fallback=(600, 3600))
        tempo = _FakeTempoClient(issue_time=(0, 0))
        service = WorklogService(jira, tempo)

        self.assertEqual(service.get_user_issue_time(issue_key="ABC-1", account_id="acc-1"), (600, 3600))

    def test_worklog_service_exposes_daily_total_and_last_logged(self) -> None:
        jira = _FakeJiraClient(issue_id="999")
        tempo = _FakeTempoClient(daily_total=7200, last_logged="2026-03-09")
        service = WorklogService(jira, tempo)

        self.assertEqual(service.get_daily_total(account_id="acc-1"), 7200)
        self.assertEqual(service.get_last_logged_date(issue_key="ABC-1", account_id="acc-1"), "2026-03-09")


if __name__ == "__main__":
    unittest.main()
