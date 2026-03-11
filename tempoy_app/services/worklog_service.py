from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional, Tuple

if TYPE_CHECKING:
    from tempoy_app.api.jira import JiraClient
    from tempoy_app.api.tempo import TempoClient


class WorklogService:
    def __init__(self, jira_client: JiraClient, tempo_client: TempoClient):
        self.jira = jira_client
        self.tempo = tempo_client

    def resolve_issue_ids(self, issue_keys: list[str]) -> Dict[str, str]:
        resolver = getattr(self.jira, "ensure_issue_ids", None)
        if callable(resolver):
            return resolver(issue_keys)

        resolved: Dict[str, str] = {}
        for issue_key in issue_keys:
            if not issue_key or issue_key in resolved:
                continue
            issue_id = self.jira.get_issue_id(issue_key)
            if issue_id:
                resolved[issue_key] = issue_id
        return resolved

    def get_recent_worked_issue_keys(self, *, account_id: str, days_back: int) -> list[str]:
        worklogs = self.tempo.get_recent_worked_issues(account_id=account_id, days_back=days_back)
        keys: list[str] = []
        seen = set()
        for worklog in worklogs:
            issue_obj = worklog.get("issue", {})
            issue_key = issue_obj.get("key")
            if issue_key and issue_key not in seen:
                seen.add(issue_key)
                keys.append(issue_key)
        return keys

    def get_user_issue_time(self, *, issue_key: str, account_id: str) -> Tuple[int, int]:
        issue_id = self.jira.get_issue_id(issue_key)
        today_seconds = total_seconds = 0
        try:
            today_seconds, total_seconds = self.tempo.get_user_issue_time(
                issue_key=issue_key,
                issue_id=issue_id,
                account_id=account_id,
            )
        except Exception:
            today_seconds = total_seconds = 0
        if total_seconds == 0:
            try:
                fallback_today, fallback_total = self.jira.sum_worklog_times(issue_key, account_id)
                if fallback_total > 0:
                    return fallback_today, fallback_total
            except Exception:
                pass
        return today_seconds, total_seconds

    def get_last_logged_date(self, *, issue_key: str, account_id: str) -> Optional[str]:
        issue_id = self.jira.get_issue_id(issue_key)
        return self.tempo.get_last_logged_date(issue_key=issue_key, issue_id=issue_id, account_id=account_id)

    def get_daily_total(self, *, account_id: str) -> int:
        return self.tempo.get_user_daily_total(account_id=account_id)
