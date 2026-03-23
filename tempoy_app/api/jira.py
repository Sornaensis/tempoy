from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


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

    def get_all_fields(self) -> List[Dict]:
        response = self.session.get(
            f"{self.base_url}/rest/api/3/field",
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []

    def search_fields(self, query: str = "", field_type: str = "custom") -> List[Dict]:
        collected: List[Dict] = []
        start_at = 0
        page_size = 50
        while True:
            params: Dict[str, object] = {"startAt": start_at, "maxResults": page_size}
            if query:
                params["query"] = query
            if field_type:
                params["type"] = field_type
            response = self.session.get(
                f"{self.base_url}/rest/api/3/field/search",
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json() or {}
            values = data.get("values")
            if not isinstance(values, list) or not values:
                break
            collected.extend(values)
            total = int(data.get("total", 0))
            start_at += len(values)
            if start_at >= total:
                break
        return collected

    def get_field_options(self, field_id: str, *, max_options: int = 200) -> List[str]:
        """Fetch the allowed option values for a custom select field.

        Tries three approaches:
        1. Create metadata for a project (works for standard select fields)
        2. Edit metadata for a recent issue (works for fields that expose
           allowedValues only in edit context)
        3. Scan existing issues to collect distinct values that have been
           set for the field (works for team fields and any other type
           where Jira doesn't expose allowedValues in metadata)

        Returns a list of option value strings, or an empty list if the
        field has no discoverable options.
        """
        normalized = str(field_id or "").strip()
        if not normalized:
            return []

        # Get a project to pull metadata from
        try:
            projects = self.get_projects(max_results=1)
        except Exception as exc:
            logger.warning("get_field_options(%s): failed to fetch projects: %s", normalized, exc)
            return []
        if not projects:
            logger.info("get_field_options(%s): no projects found", normalized)
            return []

        project_key = str(projects[0].get("key") or "").strip()
        if not project_key:
            return []

        # Approach 1: create metadata
        logger.info("get_field_options(%s): trying create schema for project %s", normalized, project_key)
        options = self._options_from_create_schema(normalized, project_key)
        if options:
            return options[:max_options]

        # Approach 2: edit metadata from a recent issue
        logger.info("get_field_options(%s): trying edit metadata fallback", normalized)
        options = self._options_from_edit_meta(normalized, project_key)
        if options:
            return options[:max_options]

        # Approach 3: scan existing issue values
        logger.info("get_field_options(%s): trying issue scan fallback", normalized)
        options = self._options_from_issue_scan(normalized)
        if options:
            return options[:max_options]

        logger.info("get_field_options(%s): no allowed values found via any method", normalized)
        return []

    def _options_from_create_schema(self, field_id: str, project_key: str) -> List[str]:
        try:
            schemas = self.get_create_schema(project_key)
        except Exception as exc:
            logger.warning("get_field_options(%s): failed to fetch create schema: %s", field_id, exc)
            return []

        logger.info("get_field_options(%s): got %d issue type schemas", field_id, len(schemas))

        for schema in schemas:
            fields = schema.get("fields")
            if not isinstance(fields, dict):
                continue
            field_meta = fields.get(field_id)
            if not field_meta:
                continue
            options = self._extract_allowed_values(field_meta)
            if options:
                logger.info(
                    "get_field_options(%s): found %d allowed values in create schema (issue type %s)",
                    field_id, len(options), schema.get("name", "?"),
                )
                return options
            else:
                logger.info(
                    "get_field_options(%s): field found in issue type %s but no usable allowedValues",
                    field_id, schema.get("name", "?"),
                )
        return []

    def _options_from_edit_meta(self, field_id: str, project_key: str) -> List[str]:
        # Find a recent issue in the project
        try:
            issues = self._search_jql(
                jql=f'project = "{project_key}" ORDER BY updated DESC',
                max_results=1,
                fields=["summary"],
            )
        except Exception as exc:
            logger.warning("get_field_options(%s): failed to search for issue: %s", field_id, exc)
            return []

        if not issues:
            logger.info("get_field_options(%s): no issues found in project %s", field_id, project_key)
            return []

        issue_key = str(issues[0].get("key") or "").strip()
        if not issue_key:
            return []

        logger.info("get_field_options(%s): fetching edit metadata for %s", field_id, issue_key)

        try:
            edit_meta = self.get_edit_schema(issue_key)
        except Exception as exc:
            logger.warning("get_field_options(%s): failed to fetch edit metadata: %s", field_id, exc)
            return []

        fields = edit_meta.get("fields")
        if not isinstance(fields, dict):
            return []

        field_meta = fields.get(field_id)
        if not field_meta:
            logger.info("get_field_options(%s): field not in edit metadata for %s", field_id, issue_key)
            return []

        options = self._extract_allowed_values(field_meta)
        if options:
            logger.info(
                "get_field_options(%s): found %d allowed values via edit metadata for %s",
                field_id, len(options), issue_key,
            )
        else:
            logger.info(
                "get_field_options(%s): field in edit metadata for %s but no usable allowedValues (keys: %s)",
                field_id, issue_key, list(field_meta.keys()),
            )
        return options

    @staticmethod
    def _extract_allowed_values(field_meta: Dict) -> List[str]:
        allowed = field_meta.get("allowedValues")
        if not isinstance(allowed, list):
            return []
        options: List[str] = []
        for opt in allowed:
            if isinstance(opt, dict):
                val = str(opt.get("value") or opt.get("name") or opt.get("title") or "").strip()
            elif isinstance(opt, str):
                val = opt.strip()
            else:
                continue
            if val:
                options.append(val)
        return options

    def _options_from_issue_scan(self, field_id: str, *, scan_limit: int = 100) -> List[str]:
        """Collect distinct values for a field by scanning recent issues."""
        try:
            issues = self._search_jql(
                jql=f'"{field_id}" is not EMPTY ORDER BY updated DESC',
                max_results=scan_limit,
                fields=[field_id],
            )
        except Exception as exc:
            logger.warning("get_field_options(%s): issue scan query failed: %s", field_id, exc)
            return []

        logger.info("get_field_options(%s): issue scan returned %d issues", field_id, len(issues))

        seen: set = set()
        options: List[str] = []
        for issue in issues:
            fields_data = issue.get("fields") or {}
            raw_value = fields_data.get(field_id)
            for val in self._extract_field_display_values(raw_value):
                if val not in seen:
                    seen.add(val)
                    options.append(val)

        if options:
            logger.info(
                "get_field_options(%s): found %d distinct values from issue scan",
                field_id, len(options),
            )
        return options

    @staticmethod
    def _extract_field_display_values(raw_value: object) -> List[str]:
        """Extract display-friendly string value(s) from a Jira field value."""
        if raw_value is None:
            return []
        if isinstance(raw_value, str):
            val = raw_value.strip()
            return [val] if val else []
        if isinstance(raw_value, (int, float)):
            return [str(raw_value)]
        if isinstance(raw_value, dict):
            # Team, user, option, priority etc. — try common display keys
            val = str(
                raw_value.get("value")
                or raw_value.get("name")
                or raw_value.get("title")
                or raw_value.get("displayName")
                or ""
            ).strip()
            return [val] if val else []
        if isinstance(raw_value, list):
            results: List[str] = []
            for item in raw_value:
                results.extend(JiraClient._extract_field_display_values(item))
            return results
        return []

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
        assignee: Optional[str] = None,
        labels: Optional[List[str]] = None,
        labels_match: Optional[str] = None,
        priority: Optional[str] = None,
        updated_after: Optional[str] = None,
        created_after: Optional[str] = None,
        parent_key: Optional[str] = None,
        order_by: Optional[str] = None,
        custom_field_filters: Optional[List[Dict]] = None,
        max_results: int = 25,
        fields: Optional[List[str]] = None,
    ) -> List[Dict]:
        normalized_query = str(query or "").strip()
        normalized_project_key = str(project_key or "").strip().upper()
        normalized_issue_types = [str(item or "").strip() for item in (issue_types or []) if str(item or "").strip()]
        normalized_status_filters = [str(item or "").strip() for item in (status_filters or []) if str(item or "").strip()]
        normalized_assignee = str(assignee or "").strip()
        normalized_labels = [str(item or "").strip() for item in (labels or []) if str(item or "").strip()]
        normalized_priority = str(priority or "").strip()
        normalized_updated_after = str(updated_after or "").strip()
        normalized_created_after = str(created_after or "").strip()
        normalized_parent_key = str(parent_key or "").strip().upper()
        normalized_order_by = str(order_by or "").strip().lower()

        clauses: List[str] = []
        if normalized_project_key:
            clauses.append(f'project = "{self._escape_jql_value(normalized_project_key)}"')

        if normalized_query:
            if self._looks_like_issue_key(normalized_query):
                escaped_query = self._escape_jql_value(normalized_query.upper())
                clauses.append(f'key = "{escaped_query}"')
            else:
                escaped_query = self._escape_jql_value(normalized_query)
                clauses.append(f'text ~ "{escaped_query}"')

        if normalized_issue_types:
            issue_type_values = ", ".join(f'"{self._escape_jql_value(value)}"' for value in normalized_issue_types)
            clauses.append(f"issuetype in ({issue_type_values})")

        if normalized_status_filters:
            status_values = ", ".join(f'"{self._escape_jql_value(value)}"' for value in normalized_status_filters)
            clauses.append(f"status in ({status_values})")

        if normalized_assignee:
            lower = normalized_assignee.lower()
            if lower == "currentuser":
                clauses.append("assignee = currentUser()")
            elif lower == "unassigned":
                clauses.append("assignee is EMPTY")
            else:
                clauses.append(f'assignee = "{self._escape_jql_value(normalized_assignee)}"')

        if normalized_labels:
            match_mode = str(labels_match or "").strip().lower()
            if match_mode == "any":
                label_values = ", ".join(f'"{self._escape_jql_value(label)}"' for label in normalized_labels)
                clauses.append(f"labels in ({label_values})")
            else:
                for label in normalized_labels:
                    clauses.append(f'labels = "{self._escape_jql_value(label)}"')

        if normalized_priority:
            clauses.append(f'priority = "{self._escape_jql_value(normalized_priority)}"')

        if normalized_updated_after:
            clauses.append(f'updated >= "{self._escape_jql_value(normalized_updated_after)}"')

        if normalized_created_after:
            clauses.append(f'created >= "{self._escape_jql_value(normalized_created_after)}"')

        if normalized_parent_key:
            clauses.append(f'parent = "{self._escape_jql_value(normalized_parent_key)}"')

        for cf in (custom_field_filters or []):
            cf_id = str(cf.get("field_id") or "").strip()
            cf_type = str(cf.get("type") or "").strip().lower()
            cf_value = cf.get("value")
            if not cf_id or cf_value is None:
                continue
            jql_field = f'cf[{cf_id.replace("customfield_", "")}]' if cf_id.startswith("customfield_") else f'"{self._escape_jql_value(cf_id)}"'
            if cf_type == "string":
                clauses.append(f'{jql_field} ~ "{self._escape_jql_value(str(cf_value))}"')
            elif cf_type == "number":
                clauses.append(f'{jql_field} = {float(cf_value)}')
            elif cf_type == "option":
                clauses.append(f'{jql_field} = "{self._escape_jql_value(str(cf_value))}"')
            elif cf_type == "multi_option":
                if isinstance(cf_value, list):
                    vals = ", ".join(f'"{self._escape_jql_value(str(v))}"' for v in cf_value)
                    clauses.append(f'{jql_field} in ({vals})')
                else:
                    clauses.append(f'{jql_field} = "{self._escape_jql_value(str(cf_value))}"')

        allowed_order = {"updated": "updated DESC", "created": "created DESC", "priority": "priority ASC"}
        order_clause = allowed_order.get(normalized_order_by, "updated DESC")

        jql = " AND ".join(clauses) if clauses else f"ORDER BY {order_clause}"
        if clauses:
            jql = f"{jql} ORDER BY {order_clause}"
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

    def get_transitions(self, issue_key: str) -> List[Dict]:
        normalized_issue_key = str(issue_key or "").strip().upper()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        response = self.session.get(
            f"{self.base_url}/rest/api/3/issue/{normalized_issue_key}/transitions",
            timeout=30,
        )
        response.raise_for_status()
        data = response.json() or {}
        return data.get("transitions", []) if isinstance(data.get("transitions"), list) else []

    def get_dev_info(self, issue_id: str) -> Dict:
        """Fetch development information (branches, commits, PRs) for an issue by its numeric ID."""
        normalized_id = str(issue_id or "").strip()
        if not normalized_id:
            raise ValueError("Issue ID is required")
        result: Dict = {"branches": [], "commits": [], "pullRequests": []}
        for data_type in ("repository",):
            response = self.session.get(
                f"{self.base_url}/rest/dev-status/latest/issue/detail",
                params={"issueId": normalized_id, "applicationType": "", "dataType": data_type},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json() or {}
            for detail in data.get("detail", []):
                if not isinstance(detail, dict):
                    continue
                for branch in detail.get("branches", []):
                    if isinstance(branch, dict):
                        result["branches"].append(branch)
                for commit in detail.get("commits", []):
                    if isinstance(commit, dict):
                        result["commits"].append(commit)
                for pr in detail.get("pullRequests", []):
                    if isinstance(pr, dict):
                        result["pullRequests"].append(pr)
        return result

    def transition_issue(self, issue_key: str, transition_id: str) -> None:
        normalized_issue_key = str(issue_key or "").strip().upper()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        normalized_transition_id = str(transition_id or "").strip()
        if not normalized_transition_id:
            raise ValueError("Transition ID is required")
        response = self.session.post(
            f"{self.base_url}/rest/api/3/issue/{normalized_issue_key}/transitions",
            json={"transition": {"id": normalized_transition_id}},
            timeout=30,
        )
        response.raise_for_status()

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

    def search_users(self, query: str, max_results: int = 10) -> List[Dict]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return []
        response = self.session.get(
            f"{self.base_url}/rest/api/3/user/search",
            params={"query": normalized_query, "maxResults": max(1, min(int(max_results), 50))},
            timeout=20,
        )
        response.raise_for_status()
        users = response.json() or []
        return [
            {
                "accountId": str(user.get("accountId") or ""),
                "displayName": str(user.get("displayName") or ""),
                "emailAddress": str(user.get("emailAddress") or ""),
                "active": bool(user.get("active", True)),
            }
            for user in users
            if isinstance(user, dict) and user.get("accountId")
        ]
