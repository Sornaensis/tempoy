from __future__ import annotations

import datetime as dt
import unittest

from tempoy_app.services.reminder_service import ReminderService


class ReminderServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ReminderService()

    def test_next_reminder_datetime_uses_same_day_when_time_is_ahead(self) -> None:
        now = dt.datetime(2026, 3, 11, 14, 30, 0)

        target = self.service.next_reminder_datetime(reminder_enabled=True, reminder_value="1500", now=now)

        self.assertEqual(target, dt.datetime(2026, 3, 11, 15, 0, 0))

    def test_next_reminder_datetime_rolls_to_next_day_when_time_has_passed(self) -> None:
        now = dt.datetime(2026, 3, 11, 15, 1, 0)

        target = self.service.next_reminder_datetime(reminder_enabled=True, reminder_value="1500", now=now)

        self.assertEqual(target, dt.datetime(2026, 3, 12, 15, 0, 0))

    def test_next_reminder_datetime_returns_none_when_disabled(self) -> None:
        target = self.service.next_reminder_datetime(reminder_enabled=False, reminder_value="1500")

        self.assertIsNone(target)


if __name__ == "__main__":
    unittest.main()