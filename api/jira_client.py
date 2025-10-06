"""Jira API client for Tempoy application."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests


class JiraClient:
    """Client for interacting with Jira REST API."""
    
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({"Accept": "application/json"})
        self._myself = None
        # Post‑May 2025 only the new dedicated JQL search endpoint is supported.
        # Legacy /rest/api/3/search has been intentionally removed from this client.
        self._active_jql_endpoint: str = "/rest/api/3/search/jql"
        # Cache issue key -> issue ID mapping for Tempo API calls
        self._issue_id_cache: Dict[str, str] = {}

    def get_myself(self) -> Dict:
        """Get information about the current authenticated user."""
        if self._myself is None:
            r = self.session.get(f"{self.base_url}/rest/api/3/myself", timeout=20)
            r.raise_for_status()
            self._myself = r.json()
        return self._myself

    def get_issue_id(self, issue_key: str) -> Optional[str]:
        """Get the numeric issue ID for a given issue key. Uses cache for performance."""
        if issue_key in self._issue_id_cache:
            return self._issue_id_cache[issue_key]
        
        try:
            r = self.session.get(f"{self.base_url}/rest/api/3/issue/{issue_key}", 
                                params={"fields": "id"}, timeout=20)
            r.raise_for_status()
            issue_data = r.json()
            issue_id = issue_data.get("id")
            if issue_id:
                self._issue_id_cache[issue_key] = issue_id
                return issue_id
        except Exception:
            pass
        return None

    def search_assigned(self, max_results: int = 50) -> List[Dict]:
        """Search for issues assigned to the current user."""
        jql = 'assignee = currentUser() ORDER BY updated DESC'
        return self._search_jql(jql=jql, max_results=max_results,
                                 fields=["summary", "status", "issuetype", "project", "priority", "parent", "customfield_10014"])

    def search(self, query: str, max_results: int = 25) -> List[Dict]:
        """Search for issues by key or text query."""
        # support key or text
        query = (query or "").strip()
        if not query:
            return []
        if "-" in query and len(query) <= 30:
            jql = f'key = "{query}"'
        else:
            # Search by summary contains
            # NOTE: ~ operator requires text index; escape quotes
            q = query.replace('"', '\\"')
            jql = f'summary ~ "{q}" ORDER BY updated DESC'
        return self._search_jql(jql=jql, max_results=max_results,
                                 fields=["summary", "status", "issuetype", "project", "priority", "parent", "customfield_10014"])

    # ---------- Internal helpers ----------
    def _search_jql(self, *, jql: str, max_results: int, fields: List[str]) -> List[Dict]:
        """Execute a JQL search using the enhanced search endpoint (/rest/api/3/search/jql).

        The enhanced endpoint replaces the deprecated /rest/api/3/search usage. It does NOT
        accept 'startAt'; pagination uses 'nextPageToken'. For our UI we only need the first
        page, so we omit pagination tokens. If future pagination is needed, capture the
        returned 'nextPageToken' when 'isLast' is False and loop.

        Request body fields used here (per spec):
          jql:       JQL string
          maxResults: desired maximum issues (bounded by server limits)
          fields:    list of field ids/names to return
          fieldsByKeys: False (we reference fields by name)

        Returns list of issue objects (may be empty). Raises HTTPError on failure.
        """
        payload = {
            "jql": jql,
            "maxResults": max_results,
            "fields": fields,
            "fieldsByKeys": False
        }
        url = f"{self.base_url}{self._active_jql_endpoint}"
        r = self.session.post(url, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json() or {}
        issues = data.get("issues", [])
        
        # Cache issue ID mappings from search results
        for issue in issues:
            issue_key = issue.get("key")
            issue_id = issue.get("id")
            if issue_key and issue_id:
                self._issue_id_cache[issue_key] = issue_id
        
        # 'isLast' boolean may be present; we ignore unless future pagination needed.
        return issues

    # ---------- Worklogs ----------
    def get_issue_worklogs(self, issue_key: str, account_id: Optional[str]=None) -> List[Dict]:
        """Retrieve all worklogs for an issue (paginates) and optionally filter by author accountId."""
        collected: List[Dict] = []
        start_at = 0
        max_results = 100
        while True:
            r = self.session.get(
                f"{self.base_url}/rest/api/3/issue/{issue_key}/worklog",
                params={"startAt": start_at, "maxResults": max_results},
                timeout=30
            )
            if r.status_code == 404:
                break
            r.raise_for_status()
            data = r.json() or {}
            worklogs = data.get("worklogs", [])
            if account_id:
                worklogs = [w for w in worklogs if (w.get("author") or {}).get("accountId") == account_id]
            collected.extend(worklogs)
            if data.get("isLast") or len(worklogs) == 0:
                break
            start_at += max_results
        return collected

    def sum_worklog_times(self, issue_key: str, account_id: str) -> Tuple[int, int]:
        """Return (today_seconds, total_seconds) for the given issue and user."""
        try:
            wls = self.get_issue_worklogs(issue_key, account_id=account_id)
        except Exception:
            return (0, 0)
        total = 0
        today = 0
        local_today = datetime.now().date()
        for w in wls:
            secs = int(w.get("timeSpentSeconds") or 0)
            total += secs
            started = w.get("started")
            if started:
                # format example: 2021-01-17T12:34:00.000+0000
                dt_obj = None
                for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
                    try:
                        dt_obj = datetime.strptime(started, fmt)
                        break
                    except Exception:
                        continue
                if dt_obj is not None:
                    if dt_obj.astimezone().date() == local_today:
                        today += secs
        return (today, total)
