from __future__ import annotations

import datetime as dt
import unittest

from tempoy_app.formatting import format_relative_time, format_seconds


class FormattingTests(unittest.TestCase):
    def test_format_seconds_matches_existing_window_behavior(self) -> None:
        self.assertEqual(format_seconds(0), "0m")
        self.assertEqual(format_seconds(59), "<1m")
        self.assertEqual(format_seconds(3660), "1h 1m")

    def test_format_relative_time_handles_today_and_historical_values(self) -> None:
        today = dt.date(2026, 3, 10)

        self.assertEqual(format_relative_time("2026-03-10", today=today), "Today")
        self.assertEqual(format_relative_time("2026-03-09", today=today), "Yesterday")
        self.assertEqual(format_relative_time("2026-03-03", today=today), "1 week ago")
        self.assertEqual(format_relative_time("2025-03-10", today=today), "1 year ago")

    def test_format_relative_time_returns_raw_value_for_invalid_input(self) -> None:
        self.assertEqual(format_relative_time("not-a-date"), "not-a-date")


if __name__ == "__main__":
    unittest.main()