from __future__ import annotations

import datetime as dt
import re


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


def format_duration_hms(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}hr {minutes}m {seconds}s"


def parse_duration_hms(text: str) -> int | None:
    normalized = (text or "").strip().casefold()
    if not normalized:
        return None
    matches = re.findall(r"(\d+)\s*(hr|hrs|hour|hours|h|m|min|mins|minute|minutes|s|sec|secs|second|seconds)", normalized)
    if not matches:
        return None
    matched_text = " ".join(f"{value}{unit}" for value, unit in matches)
    compact_normalized = re.sub(r"\s+", "", normalized)
    compact_matched = re.sub(r"\s+", "", matched_text)
    if compact_matched != compact_normalized:
        return None
    total_seconds = 0
    for value_text, unit in matches:
        value = int(value_text)
        if unit.startswith("h"):
            total_seconds += value * 3600
        elif unit.startswith("m"):
            total_seconds += value * 60
        else:
            total_seconds += value
    return total_seconds


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