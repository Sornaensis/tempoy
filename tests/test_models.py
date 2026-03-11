from __future__ import annotations

import unittest

from tempoy_app.models import AllocationRow, AllocationState, CacheEntry, IssueSnapshot


class ModelsTests(unittest.TestCase):
    def test_cache_entry_validity_uses_ttl(self) -> None:
        entry = CacheEntry(value={"ok": True}, fetched_at=100.0, ttl_seconds=30)

        self.assertTrue(entry.is_valid(120.0))
        self.assertFalse(entry.is_valid(131.0))

    def test_allocation_state_tracks_allocated_and_unlocked_rows(self) -> None:
        state = AllocationState(
            total_units=10_000,
            rows=[
                AllocationRow(issue_key="ABC-1", allocation_units=4000, locked=False),
                AllocationRow(issue_key="ABC-2", allocation_units=6000, locked=True),
            ],
        )

        self.assertEqual(state.allocated_units(), 10_000)
        self.assertEqual([row.issue_key for row in state.unlocked_rows()], ["ABC-1"])

    def test_issue_snapshot_defaults_match_grouped_grid_needs(self) -> None:
        snapshot = IssueSnapshot(issue_key="ABC-123")

        self.assertEqual(snapshot.status_name, "Unknown")
        self.assertFalse(snapshot.is_assigned_to_me)
        self.assertFalse(snapshot.is_recently_worked)


if __name__ == "__main__":
    unittest.main()
