from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests


DEFAULT_SEARCH_FIELDS = [
    "summary",
    "description",
    "status",
    "issuetype",
    "project",
    "priority",
    "labels",
    "parent",
    "customfield_10014",
    "issuelinks",
    "assignee",
]


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

    def get_projects(self, *, max_results: int = 100) -> List[Dict]:
        response = self.session.get(
            f"{self.base_url}/rest/api/3/project/search",
            params={"startAt": 0, "maxResults": max(1, min(int(max_results), 1000))},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json() or {}
        values = data.get("values")
        if isinstance(values, list):
            return values
        if isinstance(data, list):
            return data
        return []

    def get_project_issue_types(self, project_key: str) -> List[Dict]:
        normalized_project_key = str(project_key or "").strip().upper()
        if not normalized_project_key:
            raise ValueError("Project key is required")
        response = self.session.get(
            f"{self.base_url}/rest/api/3/project/{normalized_project_key}",
            params={"expand": "issueTypes"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json() or {}
        issue_types = data.get("issueTypes")
        return issue_types if isinstance(issue_types, list) else []

    def get_create_schema(self, project_key: str, *, issue_type_ids: Optional[List[str]] = None) -> List[Dict]:
        normalized_project_key = str(project_key or "").strip().upper()
        if not normalized_project_key:
            raise ValueError("Project key is required")
        issue_types = self.get_project_issue_types(normalized_project_key)
        id_to_name = {str(item.get("id") or "").strip(): str(item.get("name") or "").strip() for item in issue_types}
        raw_issue_type_ids = issue_type_ids
        if raw_issue_type_ids is None:
            raw_issue_type_ids = list(id_to_name.keys())
        collected: List[Dict] = []
        seen = set()
        for issue_type_id in raw_issue_type_ids:
            normalized_issue_type_id = str(issue_type_id or "").strip()
            if not normalized_issue_type_id or normalized_issue_type_id in seen:
                continue
            seen.add(normalized_issue_type_id)
            all_fields: List[Dict] = []
            start_at = 0
            while True:
                response = self.session.get(
                    f"{self.base_url}/rest/api/3/issue/createmeta/{normalized_project_key}/issuetypes/{normalized_issue_type_id}",
                    params={"startAt": start_at, "maxResults": 50},
                    timeout=30,
                )
                response.raise_for_status()
                payload = response.json() or {}
                if not isinstance(payload, dict):
                    break
                # New paginated format: {"startAt", "maxResults", "total", "fields": [...]}
                fields_value = payload.get("fields")
                if isinstance(fields_value, list):
                    all_fields.extend(fields_value)
                    total = int(payload.get("total") or 0)
                    start_at += len(fields_value)
                    if start_at >= total or not fields_value:
                        break
                elif isinstance(fields_value, dict):
                    # Legacy format: {"issueTypeId", "name", "fields": {...}}
                    collected.append(payload)
                    break
                else:
                    break
            if all_fields:
                fields_dict = {}
                for field_entry in all_fields:
                    if isinstance(field_entry, dict):
                        fid = str(field_entry.get("fieldId") or field_entry.get("key") or "").strip()
                        if fid:
                            fields_dict[fid] = field_entry
                collected.append({
                    "issueTypeId": normalized_issue_type_id,
                    "name": id_to_name.get(normalized_issue_type_id, ""),
                    "fields": fields_dict,
                })
        return collected

    def get_edit_schema(self, issue_key: str) -> Dict:
        normalized_issue_key = str(issue_key or "").strip().upper()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        response = self.session.get(
            f"{self.base_url}/rest/api/3/issue/{normalized_issue_key}/editmeta",
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json() or {}
        return payload if isinstance(payload, dict) else {}

    def create_issue(self, fields: Dict[str, object]) -> Dict:
        if not isinstance(fields, dict) or not fields:
            raise ValueError("Issue fields are required")
        response = self.session.post(
            f"{self.base_url}/rest/api/3/issue",
            json={"fields": fields},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json() or {}
        issue_key = str(payload.get("key") or "").strip()
        issue_id = str(payload.get("id") or "").strip()
        if issue_key and issue_id:
            self._issue_id_cache[issue_key] = issue_id
        return payload

    def update_issue(self, issue_key: str, fields: Dict[str, object]) -> Dict:
        normalized_issue_key = str(issue_key or "").strip().upper()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        if not isinstance(fields, dict) or not fields:
            raise ValueError("Issue fields are required")
        response = self.session.put(
            f"{self.base_url}/rest/api/3/issue/{normalized_issue_key}",
            json={"fields": fields},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json() if getattr(response, "status_code", 204) != 204 else {}
        return payload if isinstance(payload, dict) else {}

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

    def get_issue(self, issue_key: str, *, fields: Optional[List[str]] = None) -> Dict:
        normalized_issue_key = str(issue_key or "").strip()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        response = self.session.get(
            f"{self.base_url}/rest/api/3/issue/{normalized_issue_key}",
            params={"fields": ",".join(fields or DEFAULT_SEARCH_FIELDS)},
            timeout=30,
        )
        response.raise_for_status()
        issue = response.json() or {}
        issue_id = issue.get("id")
        if issue_id:
            self._issue_id_cache[normalized_issue_key] = issue_id
        return issue

    def search_issues(
        self,
        *,
        query: str = "",
        project_key: Optional[str] = None,
        issue_types: Optional[List[str]] = None,
        status_filters: Optional[List[str]] = None,
        max_results: int = 25,
        fields: Optional[List[str]] = None,
    ) -> List[Dict]:
        normalized_query = str(query or "").strip()
        normalized_project_key = str(project_key or "").strip().upper()
        normalized_issue_types = [str(item or "").strip() for item in (issue_types or []) if str(item or "").strip()]
        normalized_status_filters = [str(item or "").strip() for item in (status_filters or []) if str(item or "").strip()]

        clauses: List[str] = []
        if normalized_project_key:
            clauses.append(f'project = "{self._escape_jql_value(normalized_project_key)}"')

        if normalized_query:
            if self._looks_like_issue_key(normalized_query):
                escaped_query = self._escape_jql_value(normalized_query.upper())
                clauses.append(f'key = "{escaped_query}"')
            else:
                escaped_query = self._escape_jql_value(normalized_query)
                clauses.append(f'summary ~ "{escaped_query}"')

        if normalized_issue_types:
            issue_type_values = ", ".join(f'"{self._escape_jql_value(value)}"' for value in normalized_issue_types)
            clauses.append(f"issuetype in ({issue_type_values})")

        if normalized_status_filters:
            status_values = ", ".join(f'"{self._escape_jql_value(value)}"' for value in normalized_status_filters)
            clauses.append(f"status in ({status_values})")

        jql = " AND ".join(clauses) if clauses else "ORDER BY updated DESC"
        if clauses:
            jql = f"{jql} ORDER BY updated DESC"
        return self._search_jql(jql=jql, max_results=max(1, min(int(max_results), 100)), fields=fields or DEFAULT_SEARCH_FIELDS)

    def search_by_keys(self, issue_keys: List[str], fields: List[str], order_by_updated: bool = False) -> List[Dict]:
        keys = [issue_key for issue_key in issue_keys if issue_key]
        if not keys:
            return []
        key_list = '\",\"'.join(keys)
        order_clause = " ORDER BY updated DESC" if order_by_updated else ""
        jql = f'key in ("{key_list}"){order_clause}'
        return self._search_jql(jql=jql, max_results=len(keys), fields=fields)

    def get_issues_by_keys(self, issue_keys: List[str], *, fields: Optional[List[str]] = None, order_by_updated: bool = False) -> List[Dict]:
        return self.search_by_keys(issue_keys, fields=fields or DEFAULT_SEARCH_FIELDS, order_by_updated=order_by_updated)

    def search_children(self, parent_keys: List[str], *, fields: Optional[List[str]] = None, max_results: int = 50) -> List[Dict]:
        keys = [k for k in parent_keys if k]
        if not keys:
            return []
        key_list = ", ".join(f'"{self._escape_jql_value(k)}"' for k in keys)
        jql = f"parent in ({key_list}) ORDER BY issuetype ASC, key ASC"
        return self._search_jql(jql=jql, max_results=max(1, min(int(max_results), 100)), fields=fields or DEFAULT_SEARCH_FIELDS)

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

    @staticmethod
    def _escape_jql_value(value: str) -> str:
        return str(value or "").replace('\\', '\\\\').replace('"', '\\"')

    @staticmethod
    def _looks_like_issue_key(value: str) -> bool:
        normalized = str(value or "").strip().upper()
        if "-" not in normalized:
            return False
        prefix, _, number = normalized.partition("-")
        return bool(prefix and number.isdigit())

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
