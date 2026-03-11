from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from tempoy_app.models import IssueSnapshot
from tempoy_app.services.issue_catalog import IssueCatalog
from tempoy_app.ui import messages


@dataclass(slots=True)
class IssueBrowserStatus:
    text: str
    tone: str = "neutral"


@dataclass
class IssueBrowserState:
    issue_catalog: IssueCatalog
    known_issues_by_key: Dict[str, Dict] = field(default_factory=dict)
    all_snapshots: List[IssueSnapshot] = field(default_factory=list)
    visible_snapshots: List[IssueSnapshot] = field(default_factory=list)
    filter_text: str = ""

    def cache_known_issues(self, issues: List[Dict]) -> None:
        for issue in issues:
            issue_key = issue.get("key")
            if issue_key:
                self.known_issues_by_key[issue_key] = issue

    def set_snapshots(self, snapshots: List[IssueSnapshot]) -> None:
        self.all_snapshots = list(snapshots)

    def apply_filter(self, filter_text: str) -> List[IssueSnapshot]:
        self.filter_text = (filter_text or "").strip()
        self.visible_snapshots = self.issue_catalog.filter_snapshots(self.all_snapshots, self.filter_text)
        return self.visible_snapshots

    def visible_issue_keys(self) -> List[str]:
        return [snapshot.issue_key for snapshot in self.visible_snapshots]

    def snapshot_for(self, issue_key: str) -> Optional[IssueSnapshot]:
        return next((snapshot for snapshot in self.all_snapshots if snapshot.issue_key == issue_key), None)

    def allocation_issue_context(
        self,
        issue_key: str,
        *,
        raw_issue_by_key: Optional[Dict[str, Dict]] = None,
        cached_total_seconds: Optional[int] = None,
    ) -> Dict[str, object]:
        snapshot = self.snapshot_for(issue_key)
        raw_issue_cache = raw_issue_by_key or {}
        raw_issue = self.known_issues_by_key.get(issue_key) or raw_issue_cache.get(issue_key) or {}
        summary = ""
        parent_key = ""
        parent_summary = ""
        total_logged_seconds = 0
        if snapshot is not None:
            summary = snapshot.summary or ""
            parent_key, parent_summary = self.issue_catalog.split_parent_text(
                snapshot.parent_or_epic,
                snapshot.parent_lookup_key,
            )
            total_logged_seconds = max(0, int(snapshot.total_seconds or 0))
        fields = raw_issue.get("fields", {}) if isinstance(raw_issue, dict) else {}
        if not summary:
            summary = str((fields or {}).get("summary", "") or "")
        if not parent_key:
            raw_parent_text, raw_parent_key = self.issue_catalog.extract_parent_info(fields)
            parent_key, parent_summary = self.issue_catalog.split_parent_text(raw_parent_text, raw_parent_key)
        if cached_total_seconds is not None:
            total_logged_seconds = max(0, int(cached_total_seconds or 0))
        return {
            "issue_key": issue_key,
            "summary": summary,
            "parent_key": parent_key,
            "parent_summary": parent_summary,
            "total_logged_seconds": total_logged_seconds,
            "has_raw_issue": bool(raw_issue),
        }

    def choose_selection(
        self,
        preferred_key: Optional[str],
        current_key: Optional[str],
        *,
        update_selection_context: bool,
    ) -> Optional[str]:
        visible_issue_keys = self.visible_issue_keys()
        if preferred_key and preferred_key in visible_issue_keys:
            return preferred_key
        if current_key and current_key in visible_issue_keys:
            return current_key
        if visible_issue_keys and update_selection_context:
            return visible_issue_keys[0]
        return None

    def status(self) -> IssueBrowserStatus:
        total_count = len(self.all_snapshots)
        visible_count = len(self.visible_snapshots)
        if total_count == 0:
            return IssueBrowserStatus(messages.ISSUE_BROWSER_EMPTY_STATUS, tone="warning")
        if self.filter_text and visible_count == 0:
            return IssueBrowserStatus(messages.issue_browser_no_matches_status(self.filter_text, total_count), tone="warning")
        if self.filter_text:
            return IssueBrowserStatus(messages.issue_browser_filtered_status(visible_count, total_count, self.filter_text), tone="success")
        return IssueBrowserStatus(messages.issue_browser_count_status(visible_count), tone="neutral")
