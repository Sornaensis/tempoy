from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (email, api_token)
        self.session.headers.update({"Accept": "application/json"})
        self._myself = None
        self._active_jql_endpoint: str = "/rest/api/3/search/jql"
        self._issue_id_cache: Dict[str, str] = {}

    def ensure_issue_ids(self, issue_keys: List[str], *, chunk_size: int = 40) -> Dict[str, str]:
        unique_keys: List[str] = []
        seen = set()
        for issue_key in issue_keys:
            if issue_key and issue_key not in seen:
                seen.add(issue_key)
                unique_keys.append(issue_key)

        missing = [issue_key for issue_key in unique_keys if issue_key not in self._issue_id_cache]
        for index in range(0, len(missing), chunk_size):
            chunk = missing[index:index + chunk_size]
            if not chunk:
                continue
            try:
                self.search_by_keys(chunk, fields=["summary"])
            except Exception:
                continue

        return {
            issue_key: self._issue_id_cache[issue_key]
            for issue_key in unique_keys
            if issue_key in self._issue_id_cache
        }

    def get_myself(self) -> Dict:
        if self._myself is None:
            response = self.session.get(f"{self.base_url}/rest/api/3/myself", timeout=20)
            response.raise_for_status()
            self._myself = response.json()
        return self._myself

    def get_issue_id(self, issue_key: str) -> Optional[str]:
        if issue_key in self._issue_id_cache:
            return self._issue_id_cache[issue_key]
        try:
            response = self.session.get(
                f"{self.base_url}/rest/api/3/issue/{issue_key}",
                params={"fields": "id"},
                timeout=20,
            )
            response.raise_for_status()
            issue_data = response.json()
            issue_id = issue_data.get("id")
            if issue_id:
                self._issue_id_cache[issue_key] = issue_id
                return issue_id
        except Exception:
            pass
        return None

    def search_assigned(self, max_results: int = 50) -> List[Dict]:
        jql = 'assignee = currentUser() ORDER BY updated DESC'
        return self._search_jql(
            jql=jql,
            max_results=max_results,
            fields=["summary", "status", "issuetype", "project", "priority", "parent", "customfield_10014"],
        )

    def search(self, query: str, max_results: int = 25) -> List[Dict]:
        query = (query or "").strip()
        if not query:
            return []
        if "-" in query and len(query) <= 30:
            jql = f'key = "{query}"'
        else:
            escaped_query = query.replace('"', '\\"')
            jql = f'summary ~ "{escaped_query}" ORDER BY updated DESC'
        return self._search_jql(
            jql=jql,
            max_results=max_results,
            fields=["summary", "status", "issuetype", "project", "priority", "parent", "customfield_10014"],
        )

    def search_by_keys(self, issue_keys: List[str], fields: List[str], order_by_updated: bool = False) -> List[Dict]:
        keys = [issue_key for issue_key in issue_keys if issue_key]
        if not keys:
            return []
        key_list = '\",\"'.join(keys)
        order_clause = " ORDER BY updated DESC" if order_by_updated else ""
        jql = f'key in ("{key_list}"){order_clause}'
        return self._search_jql(jql=jql, max_results=len(keys), fields=fields)

    def _search_jql(self, *, jql: str, max_results: int, fields: List[str]) -> List[Dict]:
        payload = {
            "jql": jql,
            "maxResults": max_results,
            "fields": fields,
            "fieldsByKeys": False,
        }
        response = self.session.post(f"{self.base_url}{self._active_jql_endpoint}", json=payload, timeout=30)
        response.raise_for_status()
        data = response.json() or {}
        issues = data.get("issues", [])
        for issue in issues:
            issue_key = issue.get("key")
            issue_id = issue.get("id")
            if issue_key and issue_id:
                self._issue_id_cache[issue_key] = issue_id
        return issues

    def get_issue_worklogs(self, issue_key: str, account_id: Optional[str] = None) -> List[Dict]:
        collected: List[Dict] = []
        start_at = 0
        max_results = 100
        while True:
            response = self.session.get(
                f"{self.base_url}/rest/api/3/issue/{issue_key}/worklog",
                params={"startAt": start_at, "maxResults": max_results},
                timeout=30,
            )
            if response.status_code == 404:
                break
            response.raise_for_status()
            data = response.json() or {}
            worklogs = data.get("worklogs", [])
            if account_id:
                worklogs = [worklog for worklog in worklogs if (worklog.get("author") or {}).get("accountId") == account_id]
            collected.extend(worklogs)
            if data.get("isLast") or len(worklogs) == 0:
                break
            start_at += max_results
        return collected

    def sum_worklog_times(self, issue_key: str, account_id: str) -> Tuple[int, int]:
        try:
            worklogs = self.get_issue_worklogs(issue_key, account_id=account_id)
        except Exception:
            return (0, 0)
        total = 0
        today = 0
        local_today = datetime.now().date()
        for worklog in worklogs:
            seconds = int(worklog.get("timeSpentSeconds") or 0)
            total += seconds
            started = worklog.get("started")
            if not started:
                continue
            parsed_datetime = None
            for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
                try:
                    parsed_datetime = datetime.strptime(started, fmt)
                    break
                except Exception:
                    continue
            if parsed_datetime is not None and parsed_datetime.astimezone().date() == local_today:
                today += seconds
        return (today, total)
