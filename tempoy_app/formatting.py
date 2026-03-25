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

_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:]*-{3,}[\s:]*(\|[\s:]*-{3,}[\s:]*)*\|?\s*$")


def _split_table_row(line: str) -> list[str]:
    """Split a pipe-delimited table row into cell texts."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _parse_table(table_lines: list[str]) -> dict | None:
    """Parse markdown table lines into an ADF table node.

    Expects at least a header row and a separator row.
    Returns ``None`` if the lines don't form a valid table.
    """
    if len(table_lines) < 2:
        return None

    # Identify the separator line (must be present)
    sep_idx: int | None = None
    for idx, tl in enumerate(table_lines):
        if _SEPARATOR_RE.match(tl):
            sep_idx = idx
            break
    if sep_idx is None:
        return None

    header_lines = table_lines[:sep_idx]
    body_lines = table_lines[sep_idx + 1:]

    if not header_lines:
        return None

    def _make_row(cells: list[str], cell_type: str = "tableCell") -> dict:
        return {
            "type": "tableRow",
            "content": [
                {"type": cell_type, "content": [{"type": "paragraph", "content": _parse_inline(c)}]}
                for c in cells
            ],
        }

    rows: list[dict] = []
    for hl in header_lines:
        rows.append(_make_row(_split_table_row(hl), "tableHeader"))
    for bl in body_lines:
        if not bl.strip():
            continue
        rows.append(_make_row(_split_table_row(bl)))

    if not rows:
        return None
    return {"type": "table", "content": rows}


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

        # --- table ---
        if "|" in stripped:
            table_lines: list[str] = []
            while i < len(lines) and "|" in lines[i]:
                table_lines.append(lines[i])
                i += 1
            table_node = _parse_table(table_lines)
            if table_node is not None:
                content.append(table_node)
                continue
            # Not a valid table — fall through and treat first line as paragraph
            for tl in table_lines[1:]:
                lines.insert(i, tl)
            stripped = table_lines[0].strip()

        # --- paragraph (fallback) ---
        content.append({"type": "paragraph", "content": _parse_inline(stripped)})
        i += 1

    if not content:
        content = [{"type": "paragraph", "content": []}]
    return {"type": "doc", "version": 1, "content": content}