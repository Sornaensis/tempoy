from __future__ import annotations

import unittest

from tempoy_app.models import AllocationRow, AllocationState
from tempoy_app.services.allocation_service import AllocationService


class AllocationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AllocationService()

    def test_equalize_unlocked_preserves_locked_rows(self) -> None:
        state = AllocationState(
            total_units=10_000,
            rows=[
                AllocationRow(issue_key="A", allocation_units=4000, locked=True),
                AllocationRow(issue_key="B", allocation_units=1000, locked=False),
                AllocationRow(issue_key="C", allocation_units=5000, locked=False),
            ],
        )

        updated = self.service.equalize_unlocked(state)

        self.assertEqual([row.allocation_units for row in updated.rows], [4000, 3000, 3000])
        self.assertTrue(self.service.validate(updated))

    def test_set_row_units_redistributes_other_unlocked_rows(self) -> None:
        state = AllocationState(
            total_units=10_000,
            rows=[
                AllocationRow(issue_key="A", allocation_units=3000, locked=False),
                AllocationRow(issue_key="B", allocation_units=3000, locked=False),
                AllocationRow(issue_key="C", allocation_units=4000, locked=False),
            ],
        )

        updated = self.service.set_row_units(state, "A", 5000)

        self.assertEqual(updated.rows[0].allocation_units, 5000)
        self.assertEqual(sum(row.allocation_units for row in updated.rows), 10_000)
        self.assertTrue(self.service.validate(updated))

    def test_set_row_units_clamps_when_other_rows_are_locked(self) -> None:
        state = AllocationState(
            total_units=10_000,
            rows=[
                AllocationRow(issue_key="A", allocation_units=2000, locked=False),
                AllocationRow(issue_key="B", allocation_units=4000, locked=True),
                AllocationRow(issue_key="C", allocation_units=4000, locked=True),
            ],
        )

        updated = self.service.set_row_units(state, "A", 9000)

        self.assertEqual([row.allocation_units for row in updated.rows], [2000, 4000, 4000])
        self.assertTrue(self.service.validate(updated))

    def test_remove_row_redistributes_deleted_units_without_equalizing(self) -> None:
        state = AllocationState(
            total_units=10_000,
            rows=[
                AllocationRow(issue_key="A", allocation_units=2000, locked=False),
                AllocationRow(issue_key="B", allocation_units=3000, locked=False),
                AllocationRow(issue_key="C", allocation_units=5000, locked=False),
            ],
        )

        updated = self.service.remove_row(state, "A")

        self.assertEqual([row.issue_key for row in updated.rows], ["B", "C"])
        self.assertEqual([row.allocation_units for row in updated.rows], [3750, 6250])
        self.assertTrue(self.service.validate(updated))

    def test_allocations_to_seconds_assigns_exact_total(self) -> None:
        state = AllocationState(
            total_units=10_000,
            rows=[
                AllocationRow(issue_key="A", allocation_units=3333),
                AllocationRow(issue_key="B", allocation_units=3333),
                AllocationRow(issue_key="C", allocation_units=3334),
            ],
        )

        allocations = self.service.allocations_to_seconds(state, daily_time_minutes=60)

        self.assertEqual(sum(allocations.values()), 3600)
        self.assertEqual(allocations, {"A": 1200, "B": 1200, "C": 1200})

    def test_validate_rejects_inexact_total(self) -> None:
        state = AllocationState(
            total_units=10_000,
            rows=[
                AllocationRow(issue_key="A", allocation_units=5000),
                AllocationRow(issue_key="B", allocation_units=4000),
            ],
        )

        self.assertFalse(self.service.validate(state))

    def test_allocations_to_seconds_handles_empty_rows(self) -> None:
        state = AllocationState(total_units=10_000, rows=[])

        allocations = self.service.allocations_to_seconds(state, daily_time_minutes=480)

        self.assertEqual(allocations, {})

    def test_allocations_to_total_seconds_uses_remaining_time_budget(self) -> None:
        state = AllocationState(
            total_units=10_000,
            rows=[
                AllocationRow(issue_key="A", allocation_units=2500),
                AllocationRow(issue_key="B", allocation_units=7500),
            ],
        )

        allocations = self.service.allocations_to_total_seconds(state, total_seconds=7200)

        self.assertEqual(allocations, {"A": 1800, "B": 5400})
        self.assertEqual(sum(allocations.values()), 7200)


if __name__ == "__main__":
    unittest.main()
