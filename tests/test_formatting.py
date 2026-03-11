from __future__ import annotations

import datetime as dt
import unittest

from tempoy_app.formatting import format_duration_hms, format_relative_time, format_seconds, parse_duration_hms


class FormattingTests(unittest.TestCase):
    def test_format_seconds_matches_existing_window_behavior(self) -> None:
        self.assertEqual(format_seconds(0), "0m")
        self.assertEqual(format_seconds(59), "<1m")
        self.assertEqual(format_seconds(3660), "1h 1m")

    def test_format_duration_hms_renders_full_triplet(self) -> None:
        self.assertEqual(format_duration_hms(3665), "1hr 1m 5s")

    def test_parse_duration_hms_accepts_hr_min_sec_text(self) -> None:
        self.assertEqual(parse_duration_hms("1hr 30m 15s"), 5415)
        self.assertEqual(parse_duration_hms("45m"), 2700)
        self.assertIsNone(parse_duration_hms("nonsense"))

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