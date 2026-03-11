from __future__ import annotations

import datetime as dt
from typing import Dict, Iterable, List, Optional

from tempoy_app.models import IssueSnapshot


class IssueCatalog:
    @staticmethod
    def merge_issues(*issue_groups: Iterable[Dict]) -> List[Dict]:
        merged: Dict[str, Dict] = {}
        order: List[str] = []
        for group in issue_groups:
            for issue in group:
                key = issue.get("key")
                if not key:
                    continue
                if key not in merged:
                    merged[key] = issue
                    order.append(key)
                    continue
                existing = merged[key]
                existing_fields = existing.get("fields", {})
                incoming_fields = issue.get("fields", {})
                if not existing_fields and incoming_fields:
                    merged[key] = issue
        return [merged[key] for key in order]

    @staticmethod
    def worked_issue_keys_from_worklogs(worklogs: Iterable[Dict]) -> List[str]:
        seen = set()
        keys: List[str] = []
        for worklog in worklogs:
            issue_obj = worklog.get("issue", {})
            issue_key = issue_obj.get("key")
            if issue_key and issue_key not in seen:
                seen.add(issue_key)
                keys.append(issue_key)
        return keys

    @staticmethod
    def filter_snapshots(snapshots: Iterable[IssueSnapshot], query: str) -> List[IssueSnapshot]:
        normalized_query = (query or "").strip().casefold()
        if not normalized_query:
            return list(snapshots)
        return [
            snapshot
            for snapshot in snapshots
            if normalized_query in snapshot.issue_key.casefold() or normalized_query in snapshot.summary.casefold()
        ]

    @staticmethod
    def extract_parent_info(fields: Dict) -> tuple[str, str]:
        parent_text = ""
        lookup_key = ""
        epic = fields.get("customfield_10014")
        if epic:
            if isinstance(epic, str):
                return epic, epic
            if isinstance(epic, dict):
                epic_key = epic.get("key", "")
                epic_summary = ""
                if epic.get("fields"):
                    epic_summary = epic.get("fields", {}).get("summary", "")
                elif epic.get("summary"):
                    epic_summary = epic.get("summary", "")
                if epic_key:
                    if epic_summary:
                        return f"{epic_key}: {epic_summary}", ""
                    return epic_key, epic_key
        parent = fields.get("parent")
        if isinstance(parent, dict):
            parent_key = parent.get("key", "")
            parent_summary = parent.get("fields", {}).get("summary", "")
            if parent_key:
                if parent_summary:
                    parent_text = f"{parent_key}: {parent_summary}"
                else:
                    parent_text = parent_key
                    lookup_key = parent_key
        return parent_text, lookup_key

    @staticmethod
    def split_parent_text(parent_text: str, lookup_key: str) -> tuple[str, str]:
        if not parent_text:
            return lookup_key or "", ""
        if ":" in parent_text:
            parent_key, parent_summary = parent_text.split(":", 1)
            return (lookup_key or parent_key.strip(), parent_summary.strip())
        return (lookup_key or parent_text.strip(), "")

    @staticmethod
    def _timestamp_or_zero(value: Optional[str]) -> float:
        if not value:
            return 0.0
        try:
            if len(value) == 10 and value.count("-") == 2:
                return dt.datetime.strptime(value, "%Y-%m-%d").timestamp()
            normalized = value.replace("Z", "+00:00")
            return dt.datetime.fromisoformat(normalized).timestamp()
        except Exception:
            try:
                return dt.datetime.strptime(value.split("T", 1)[0], "%Y-%m-%d").timestamp()
            except Exception:
                return 0.0

    def build_snapshots(
        self,
        issues: Iterable[Dict],
        *,
        assigned_keys: Optional[set[str]] = None,
        worked_keys: Optional[set[str]] = None,
        totals_by_key: Optional[Dict[str, tuple[int, int]]] = None,
        last_logged_by_key: Optional[Dict[str, str]] = None,
    ) -> List[IssueSnapshot]:
        assigned = assigned_keys or set()
        worked = worked_keys or set()
        totals = totals_by_key or {}
        last_logged = last_logged_by_key or {}
        snapshots: List[IssueSnapshot] = []
        for issue in issues:
            issue_key = issue.get("key")
            if not issue_key:
                continue
            fields = issue.get("fields", {})
            parent_or_epic, parent_lookup_key = self.extract_parent_info(fields)
            today_seconds, total_seconds = totals.get(issue_key, (0, 0))
            snapshots.append(
                IssueSnapshot(
                    issue_key=issue_key,
                    summary=fields.get("summary", ""),
                    status_name=(fields.get("status") or {}).get("name", "Unknown"),
                    parent_or_epic=parent_or_epic,
                    parent_lookup_key=parent_lookup_key,
                    today_seconds=today_seconds,
                    total_seconds=total_seconds,
                    last_logged_at=last_logged.get(issue_key),
                    is_assigned_to_me=issue_key in assigned,
                    is_recently_worked=issue_key in worked,
                    updated_at=fields.get("updated"),
                )
            )
        return self.sort_snapshots(snapshots)

    def sort_snapshots(self, snapshots: Iterable[IssueSnapshot]) -> List[IssueSnapshot]:
        return sorted(
            snapshots,
            key=lambda snapshot: (
                snapshot.status_name.casefold(),
                -self._timestamp_or_zero(snapshot.last_logged_at),
                -self._timestamp_or_zero(snapshot.updated_at),
                snapshot.issue_key.casefold(),
            ),
        )
