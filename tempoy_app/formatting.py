from __future__ import annotations

import datetime as dt


def format_seconds(secs: int) -> str:
    if secs <= 0:
        return "0m"
    hours, rem = divmod(secs, 3600)
    mins = rem // 60
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    if not parts:
        parts.append("<1m")
    return " ".join(parts)


def format_relative_time(date_str: str, *, today: dt.date | None = None) -> str:
    if not date_str:
        return ""

    try:
        logged_date = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
        current_day = today or dt.date.today()
        diff = current_day - logged_date

        if diff.days == 0:
            return "Today"
        if diff.days == 1:
            return "Yesterday"
        if diff.days < 7:
            return f"{diff.days} days ago"
        if diff.days < 30:
            weeks = diff.days // 7
            return f"{weeks} week{'s' if weeks > 1 else ''} ago"
        if diff.days < 365:
            months = diff.days // 30
            return f"{months} month{'s' if months > 1 else ''} ago"
        years = diff.days // 365
        return f"{years} year{'s' if years > 1 else ''} ago"
    except Exception:
        return date_str