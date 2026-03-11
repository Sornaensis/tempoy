from __future__ import annotations

import datetime as dt


class ReminderService:
    def configured_reminder_time(self, reminder_value: str) -> dt.time:
        raw_value = str(reminder_value or "1500")
        try:
            hour = int(raw_value[:2])
            minute = int(raw_value[2:4])
            return dt.time(hour=hour, minute=minute)
        except (TypeError, ValueError):
            return dt.time(hour=15, minute=0)

    def next_reminder_datetime(
        self,
        *,
        reminder_enabled: bool,
        reminder_value: str,
        now: dt.datetime | None = None,
    ) -> dt.datetime | None:
        if not reminder_enabled:
            return None
        reference = now or dt.datetime.now()
        reminder_time = self.configured_reminder_time(reminder_value)
        target = reference.replace(
            hour=reminder_time.hour,
            minute=reminder_time.minute,
            second=0,
            microsecond=0,
        )
        if target <= reference:
            target += dt.timedelta(days=1)
        return target

    def format_local_time(self, reminder_timestamp: float | None) -> str:
        if not reminder_timestamp:
            return ""
        return dt.datetime.fromtimestamp(reminder_timestamp, tz=dt.timezone.utc).astimezone().strftime("%H:%M")