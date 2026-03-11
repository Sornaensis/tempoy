from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple

import requests

from tempoy_app.logging_utils import debug_log


class TempoClient:
    BASE = "https://api.tempo.io/4"

    def __init__(self, tempo_api_token: str):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {tempo_api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def create_worklog(
        self,
        *,
        issue_key: str,
        issue_id: str,
        account_id: str,
        seconds: int,
        when: Optional[dt.datetime] = None,
        description: str = "",
    ) -> Dict:
        when = when or dt.datetime.now()
        start_date = when.strftime("%Y-%m-%d")
        start_time = when.strftime("%H:%M:%S")
        if not issue_id:
            raise ValueError(f"issueId is required for Tempo API - could not get ID for issue {issue_key}")
        payload = {
            "issueId": int(issue_id),
            "timeSpentSeconds": int(seconds),
            "startDate": start_date,
            "startTime": start_time,
            "authorAccountId": account_id,
            "description": description or "",
        }
        response = self.session.post(f"{self.BASE}/worklogs", json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_user_issue_time(
        self,
        *,
        issue_key: str,
        issue_id: Optional[str] = None,
        account_id: str,
        days_back: int = 365 * 5,
    ) -> Tuple[int, int]:
        today = dt.date.today()
        from_date = today - dt.timedelta(days=days_back)
        params = {
            "worker": account_id,
            "from": from_date.strftime("%Y-%m-%d"),
            "to": today.strftime("%Y-%m-%d"),
            "limit": 100,
        }
        if issue_id:
            params["issueId"] = int(issue_id)
        total = 0
        today_total = 0
        debug_log("Querying Tempo API with params: {}", params)
        offset = 0
        max_pages = 20
        page_count = 0
        while page_count < max_pages:
            current_params = dict(params)
            current_params["offset"] = offset
            debug_log("Page {}, offset {}", page_count + 1, offset)
            try:
                response = self.session.get(f"{self.BASE}/worklogs", params=current_params, timeout=30)
                response.raise_for_status()
                data = response.json() or {}
                batch = data.get("results", [])
                if not batch:
                    debug_log("No more worklogs, ending pagination")
                    break
                debug_log("Got {} worklogs", len(batch))
            except Exception as error:
                debug_log("API request failed: {}", error)
                break
            for worklog in batch:
                if issue_id:
                    worklog_issue = worklog.get("issue", {})
                    worklog_issue_id = worklog_issue.get("id")
                    if str(worklog_issue_id) != str(issue_id):
                        continue
                worklog_author = worklog.get("author", {})
                worklog_account_id = worklog_author.get("accountId")
                if worklog_account_id != account_id:
                    debug_log("Skipping worklog - author {} != {}", worklog_account_id, account_id)
                    continue
                seconds = int(worklog.get("timeSpentSeconds") or 0)
                total += seconds
                start_date = worklog.get("startDate")
                if start_date:
                    try:
                        if dt.datetime.strptime(start_date, "%Y-%m-%d").date() == today:
                            today_total += seconds
                    except Exception:
                        pass
                debug_log("Processed worklog: {}s on {}", seconds, start_date)
            if len(batch) < params["limit"]:
                debug_log("Received {} < {}, ending pagination", len(batch), params["limit"])
                break
            offset += len(batch)
            page_count += 1
        debug_log("Final result for {} (ID: {}): today={}s, total={}s", issue_key, issue_id, today_total, total)
        return today_total, total

    def get_user_daily_total(self, *, account_id: str, days_back: int = 1) -> int:
        today = dt.date.today()
        params = {
            "worker": account_id,
            "from": today.strftime("%Y-%m-%d"),
            "to": today.strftime("%Y-%m-%d"),
            "limit": 200,
        }
        daily_total = 0
        debug_log("Querying daily total with params: {}", params)
        offset = 0
        max_pages = 20
        page_count = 0
        while page_count < max_pages:
            current_params = dict(params)
            current_params["offset"] = offset
            try:
                response = self.session.get(f"{self.BASE}/worklogs", params=current_params, timeout=30)
                response.raise_for_status()
                data = response.json() or {}
                batch = data.get("results", [])
                if not batch:
                    break
                for worklog in batch:
                    worklog_author = worklog.get("author", {})
                    worklog_account_id = worklog_author.get("accountId")
                    if worklog_account_id != account_id:
                        continue
                    start_date = worklog.get("startDate")
                    if not start_date:
                        continue
                    try:
                        if dt.datetime.strptime(start_date, "%Y-%m-%d").date() == today:
                            daily_total += int(worklog.get("timeSpentSeconds") or 0)
                    except Exception:
                        pass
                if len(batch) < params["limit"]:
                    break
                offset += len(batch)
                page_count += 1
            except Exception as error:
                debug_log("Daily total request failed: {}", error)
                break
        debug_log("Daily total: {}s", daily_total)
        return daily_total

    def get_recent_worked_issues(self, *, account_id: str, days_back: int = 7) -> List[Dict]:
        today = dt.date.today()
        from_date = today - dt.timedelta(days=days_back)
        params = {
            "worker": account_id,
            "from": from_date.strftime("%Y-%m-%d"),
            "to": today.strftime("%Y-%m-%d"),
            "limit": 200,
        }
        collected: List[Dict] = []
        debug_log("Fetching recent worklogs for {} from {} to {}", account_id, from_date, today)
        offset = 0
        max_pages = 10
        page_count = 0
        while page_count < max_pages:
            params["offset"] = offset
            page_count += 1
            try:
                response = self.session.get(f"{self.BASE}/worklogs", params=params, timeout=30)
                response.raise_for_status()
                data = response.json() or {}
                results = data.get("results", [])
                if not results:
                    break
                collected.extend(results)
                metadata = data.get("metadata", {})
                total = metadata.get("count", 0)
                if len(collected) >= total:
                    break
                offset += len(results)
            except Exception as error:
                debug_log("Error fetching recent worklogs: {}", error)
                break
        debug_log("Found {} recent worklogs", len(collected))
        return collected

    def get_last_logged_date(
        self,
        *,
        issue_key: str,
        issue_id: Optional[str] = None,
        account_id: str,
        days_back: int = 365,
    ) -> Optional[str]:
        today = dt.date.today()
        from_date = today - dt.timedelta(days=days_back)
        attempts = []
        if issue_id:
            attempts.append(("issueId", {"issueId": int(issue_id)}))
        attempts.append(("manual_filter", {}))
        for attempt_name, extra_params in attempts:
            params = {
                "worker": account_id,
                "from": from_date.strftime("%Y-%m-%d"),
                "to": today.strftime("%Y-%m-%d"),
                "limit": 200,
            }
            params.update(extra_params)
            debug_log("Trying {} for {} with params: {}", attempt_name, issue_key, params)
            try:
                response = self.session.get(f"{self.BASE}/worklogs", params=params, timeout=30)
                response.raise_for_status()
                data = response.json() or {}
                results = data.get("results", [])
                debug_log("{} returned {} worklogs for {}", attempt_name, len(results), issue_key)
                if attempt_name == "manual_filter":
                    filtered_results = []
                    for worklog in results:
                        issue_obj = worklog.get("issue", {})
                        worklog_key = issue_obj.get("key")
                        if worklog_key == issue_key:
                            filtered_results.append(worklog)
                    results = filtered_results
                    debug_log("After filtering by {}: {} worklogs", issue_key, len(results))
                if not results:
                    continue
                most_recent_entry = None
                most_recent_datetime = None
                for worklog in results:
                    start_date = worklog.get("startDate")
                    start_time = worklog.get("startTime")
                    if not start_date:
                        continue
                    try:
                        if start_time:
                            datetime_str = f"{start_date} {start_time}"
                            worklog_datetime = dt.datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
                        else:
                            worklog_datetime = dt.datetime.strptime(start_date, "%Y-%m-%d")
                        if most_recent_datetime is None or worklog_datetime > most_recent_datetime:
                            most_recent_datetime = worklog_datetime
                            most_recent_entry = worklog
                    except Exception as error:
                        debug_log("Error parsing datetime for worklog: {}", error)
                        continue
                if most_recent_entry:
                    result_date = most_recent_entry.get("startDate")
                    debug_log("Found most recent worklog for {} using {}: {}", issue_key, attempt_name, result_date)
                    return result_date
            except Exception as error:
                debug_log("{} failed for {}: {}", attempt_name, issue_key, error)
                continue
        debug_log("No worklogs found for {} after all attempts", issue_key)
        return None
