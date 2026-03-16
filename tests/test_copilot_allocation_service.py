from __future__ import annotations

import unittest

from tempoy_app.config import AppConfig
from tempoy_app.services.copilot_allocation_service import CopilotAllocationService


class _ConfigStore:
    def __init__(self, config: AppConfig):
        self.config = config

    def load(self) -> AppConfig:
        return self.config

    def save(self, config: AppConfig) -> None:
        self.config = config


class CopilotAllocationServiceTests(unittest.TestCase):
    def test_get_allocation_draft_returns_derived_seconds_and_warnings(self) -> None:
        store = _ConfigStore(
            AppConfig(
                daily_time_seconds=3600,
                allocation_draft={
                    "total_units": 10000,
                    "rows": [
                        {"issue_key": "ABC-1", "summary": "One", "allocation_units": 6000, "locked": False, "description": ""},
                        {"issue_key": "ABC-2", "summary": "Two", "allocation_units": 4000, "locked": True, "description": ""},
                    ],
                },
            )
        )
        service = CopilotAllocationService(config_loader=store.load, daily_total_resolver=lambda config: 3000)

        payload = service.get_allocation_draft()

        self.assertEqual(payload["remaining_seconds"], 600)
        self.assertEqual(payload["allocatable_seconds"], 600)
        self.assertEqual(payload["rows"][0]["allocated_seconds"], 360)
        self.assertEqual(payload["rows"][1]["allocated_seconds"], 240)
        self.assertEqual(payload["warnings"], [])

    def test_get_allocation_draft_warns_when_planned_exceeds_remaining(self) -> None:
        store = _ConfigStore(
            AppConfig(
                daily_time_seconds=3600,
                allocation_draft={
                    "total_units": 10000,
                    "rows": [
                        {"issue_key": "ABC-1", "summary": "One", "allocation_units": 10000, "locked": False, "description": ""},
                    ],
                },
            )
        )
        service = CopilotAllocationService(config_loader=store.load, daily_total_resolver=lambda config: 3600)

        payload = service.get_allocation_draft()

        self.assertEqual(payload["remaining_seconds"], 0)
        self.assertEqual(payload["warnings"], ["Daily limit reached"])

    def test_add_issue_persists_new_row(self) -> None:
        store = _ConfigStore(AppConfig(allocation_draft={"rows": []}))
        service = CopilotAllocationService(
            config_loader=store.load,
            config_saver=store.save,
            issue_summary_resolver=lambda issue_key: "Fetched summary",
        )

        payload = service.add_issue("abc-1")

        self.assertEqual(payload["rows"][0]["issue_key"], "ABC-1")
        self.assertEqual(payload["rows"][0]["summary"], "Fetched summary")
        self.assertEqual(store.config.allocation_draft["rows"][0]["issue_key"], "ABC-1")

    def test_set_row_units_rebalances_remaining_rows(self) -> None:
        store = _ConfigStore(
            AppConfig(
                allocation_draft={
                    "total_units": 10000,
                    "rows": [
                        {"issue_key": "A", "summary": "A", "allocation_units": 5000, "locked": False, "description": ""},
                        {"issue_key": "B", "summary": "B", "allocation_units": 5000, "locked": False, "description": ""},
                    ],
                }
            )
        )
        service = CopilotAllocationService(config_loader=store.load, config_saver=store.save)

        payload = service.set_row_units("A", 2500)

        self.assertEqual([row["allocation_units"] for row in payload["rows"]], [2500, 7500])

    def test_reset_rebalances_rows_using_ui_semantics(self) -> None:
        store = _ConfigStore(
            AppConfig(
                allocation_draft={
                    "total_units": 10000,
                    "rows": [
                        {"issue_key": "A", "summary": "A", "allocation_units": 9000, "locked": True, "description": ""},
                        {"issue_key": "B", "summary": "B", "allocation_units": 1000, "locked": True, "description": ""},
                    ],
                }
            )
        )
        service = CopilotAllocationService(config_loader=store.load, config_saver=store.save)

        payload = service.reset()

        self.assertEqual([row["allocation_units"] for row in payload["rows"]], [5000, 5000])
        self.assertTrue(all(not row["locked"] for row in payload["rows"]))


if __name__ == "__main__":
    unittest.main()