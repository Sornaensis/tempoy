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


# ---------------------------------------------------------------------------
# Markdown → Atlassian Document Format (ADF)
# ---------------------------------------------------------------------------

_INLINE_PATTERN = re.compile(
    r"(?P<bold_ast>\*\*(?P<bold_ast_text>.+?)\*\*)"
    r"|(?P<bold_usc>__(?P<bold_usc_text>.+?)__)"
    r"|(?P<italic_ast>\*(?P<italic_ast_text>.+?)\*)"
    r"|(?P<italic_usc>_(?P<italic_usc_text>.+?)_)"
    r"|(?P<code>`(?P<code_text>[^`]+)`)"
    r"|(?P<link>\[(?P<link_text>[^\]]+)\]\((?P<link_href>[^)]+)\))"
)


def _parse_inline(text: str) -> list[dict]:
    nodes: list[dict] = []
    last_end = 0
    for m in _INLINE_PATTERN.finditer(text):
        if m.start() > last_end:
            nodes.append({"type": "text", "text": text[last_end:m.start()]})
        if m.group("bold_ast") or m.group("bold_usc"):
            inner = m.group("bold_ast_text") or m.group("bold_usc_text")
            nodes.append({"type": "text", "text": inner, "marks": [{"type": "strong"}]})
        elif m.group("italic_ast") or m.group("italic_usc"):
            inner = m.group("italic_ast_text") or m.group("italic_usc_text")
            nodes.append({"type": "text", "text": inner, "marks": [{"type": "em"}]})
        elif m.group("code"):
            nodes.append({"type": "text", "text": m.group("code_text"), "marks": [{"type": "code"}]})
        elif m.group("link"):
            nodes.append({
                "type": "text",
                "text": m.group("link_text"),
                "marks": [{"type": "link", "attrs": {"href": m.group("link_href")}}],
            })
        last_end = m.end()
    if last_end < len(text):
        nodes.append({"type": "text", "text": text[last_end:]})
    return nodes


def markdown_to_adf(text: str) -> dict:
    """Convert a markdown string to an Atlassian Document Format document.

    Supports: headings, bold, italic, inline code, fenced code blocks,
    unordered lists (``-``, ``*``, ``+``), ordered lists, and links.
    Plain text and unrecognised constructs pass through as paragraphs.
    """
    lines = str(text or "").splitlines()
    content: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # --- fenced code block ---
        fence_match = re.match(r"^(`{3,})(.*)", line)
        if fence_match:
            fence = fence_match.group(1)
            language = fence_match.group(2).strip() or None
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith(fence):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            node: dict = {"type": "codeBlock", "content": [{"type": "text", "text": "\n".join(code_lines)}]}
            if language:
                node["attrs"] = {"language": language}
            content.append(node)
            continue

        stripped = line.strip()

        # --- blank line → skip ---
        if not stripped:
            i += 1
            continue

        # --- heading ---
        heading_match = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            content.append({"type": "heading", "attrs": {"level": level}, "content": _parse_inline(heading_text)})
            i += 1
            continue

        # --- unordered list ---
        ul_match = re.match(r"^[-*+]\s+(.*)", stripped)
        if ul_match:
            items: list[dict] = []
            while i < len(lines) and re.match(r"^\s*[-*+]\s+", lines[i]):
                item_text = re.sub(r"^\s*[-*+]\s+", "", lines[i])
                items.append({"type": "listItem", "content": [{"type": "paragraph", "content": _parse_inline(item_text)}]})
                i += 1
            content.append({"type": "bulletList", "content": items})
            continue

        # --- ordered list ---
        ol_match = re.match(r"^\d+[.)]\s+(.*)", stripped)
        if ol_match:
            items = []
            while i < len(lines) and re.match(r"^\s*\d+[.)]\s+", lines[i]):
                item_text = re.sub(r"^\s*\d+[.)]\s+", "", lines[i])
                items.append({"type": "listItem", "content": [{"type": "paragraph", "content": _parse_inline(item_text)}]})
                i += 1
            content.append({"type": "orderedList", "content": items})
            continue

        # --- paragraph (fallback) ---
        content.append({"type": "paragraph", "content": _parse_inline(stripped)})
        i += 1

    if not content:
        content = [{"type": "paragraph", "content": []}]
    return {"type": "doc", "version": 1, "content": content}