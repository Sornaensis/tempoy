from __future__ import annotations

import unittest

from tempoy_app.models import IssueSnapshot
from tempoy_app.services.issue_catalog import IssueCatalog
from tempoy_app.ui.issue_browser_state import IssueBrowserState


class IssueBrowserStateTests(unittest.TestCase):
    def test_allocation_issue_context_prefers_snapshot_values_and_cached_total(self) -> None:
        state = IssueBrowserState(IssueCatalog())
        state.set_snapshots(
            [
                IssueSnapshot(
                    issue_key="ABC-1",
                    summary="Snapshot summary",
                    parent_or_epic="PARENT-1: Parent summary",
                    parent_lookup_key="PARENT-1",
                    total_seconds=1800,
                )
            ]
        )

        context = state.allocation_issue_context("ABC-1", cached_total_seconds=7200)

        self.assertEqual(context["summary"], "Snapshot summary")
        self.assertEqual(context["parent_key"], "PARENT-1")
        self.assertEqual(context["parent_summary"], "Parent summary")
        self.assertEqual(context["total_logged_seconds"], 7200)
        self.assertFalse(context["has_raw_issue"])

    def test_allocation_issue_context_falls_back_to_raw_issue_metadata(self) -> None:
        state = IssueBrowserState(IssueCatalog())
        state.cache_known_issues(
            [
                {
                    "key": "ABC-2",
                    "fields": {
                        "summary": "Raw issue summary",
                        "parent": {"key": "PARENT-2", "fields": {}},
                    },
                }
            ]
        )

        context = state.allocation_issue_context("ABC-2")

        self.assertEqual(context["summary"], "Raw issue summary")
        self.assertEqual(context["parent_key"], "PARENT-2")
        self.assertEqual(context["parent_summary"], "")
        self.assertEqual(context["total_logged_seconds"], 0)
        self.assertTrue(context["has_raw_issue"])


if __name__ == "__main__":
    unittest.main()