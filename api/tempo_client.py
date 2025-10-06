"""Tempo API client for Tempoy application."""
from __future__ import annotations

import datetime as dt
import os
from typing import Dict, List, Optional, Tuple

import requests


class TempoClient:
    """Client for interacting with Tempo REST API."""
    
    BASE = "https://api.tempo.io/4"

    def __init__(self, tempo_api_token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {tempo_api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

    def create_worklog(self, *, issue_key: str, issue_id: str, account_id: str, seconds: int,
                        when: Optional[dt.datetime] = None, description: str = "") -> Dict:
        """Create a worklog via Tempo Cloud API v4.
        Requires issueId (numeric) - issue_key is only used for error messages.
        """
        when = when or dt.datetime.now()
        # Tempo expects separate date and time strings (local time)
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
            "description": description or ""
        }
        
        r = self.session.post(f"{self.BASE}/worklogs", json=payload, timeout=30)
        # If your Tempo is configured for site-scoped endpoint on your JIRA URL,
        # you can switch to:
        # r = requests.post(f"{jira_base_url}/rest/tempo-timesheets/4/worklogs", headers=..., json=payload)
        r.raise_for_status()
        return r.json()

    # -------- Worklog queries (Tempo API) --------
    def iter_issue_worklogs(self, *, issue_key: str, issue_id: Optional[str] = None, worker: Optional[str] = None,
                             page_limit: int = 100) -> List[Dict]:
        """Fetch all Tempo worklogs for an issue using Tempo API v4.
        
        Uses issueId (numeric) if available, with optional worker filter.
        """
        # Build query parameters for Tempo API v4
        params = {"limit": page_limit}
        
        if issue_id:
            params["issueId"] = int(issue_id)
        if worker:
            params["worker"] = worker

        
        collected: List[Dict] = []
        debug = os.environ.get("TEMPOY_DEBUG")
        
        if debug:
            print(f"[TEMPOY DEBUG] iter_issue_worklogs for issue {issue_key} (ID: {issue_id}) with params: {params}")
        
        # Paginate through results
        offset = 0
        max_pages = 10  # Limit pagination
        page_count = 0
        
        while page_count < max_pages:
            current_params = dict(params)
            current_params["offset"] = offset
            
            try:
                r = self.session.get(f"{self.BASE}/worklogs", params=current_params, timeout=30)
                r.raise_for_status()
                
                data = r.json() or {}
                batch = data.get("results", [])
                
                if not batch:
                    if debug:
                        print(f"[TEMPOY DEBUG] No more worklogs, ending pagination")
                    break
                    
                collected.extend(batch)
                
                if debug:
                    print(f"[TEMPOY DEBUG] Page {page_count+1}: got {len(batch)} worklogs")
                
                if len(batch) < page_limit:
                    break
                    
                offset += len(batch)
                page_count += 1
                
            except Exception as e:
                if debug:
                    print(f"[TEMPOY DEBUG] Request failed: {e}")
                break
                
        if debug:
            print(f"[TEMPOY DEBUG] Total collected: {len(collected)} worklogs")
            
        return collected

    def sum_issue_times(self, *, issue_key: str, account_id: str, alt_workers: Optional[List[str]] = None) -> Tuple[int, int]:
        """Return (today_seconds, total_seconds) for the user using Tempo worklogs.

        alt_workers: optional fallback identifiers (e.g., email) to help locate user logs.
        We fetch all logs (best-effort) once (could be optimized later with date ranges or caching).
        """
        today_date = dt.date.today()
        worker_ids = [account_id]
        if alt_workers:
            for w in alt_workers:
                if w and w not in worker_ids:
                    worker_ids.append(w)
        logs = []
        # try each worker id until logs found; then also fetch unfiltered if still empty to attempt local filtering
        for wid in worker_ids:
            logs = self.iter_issue_worklogs(issue_key=issue_key, worker=wid)
            if logs:
                break
        if not logs:
            # final unfiltered attempt
            logs = self.iter_issue_worklogs(issue_key=issue_key, worker=None)

        total_secs = 0
        today_secs = 0
        for w in logs:
            secs = int(w.get("timeSpentSeconds") or 0)
            author = w.get("author") or {}
            author_id = author.get("accountId") or w.get("authorAccountId") or author.get("name") or author.get("key")
            if author_id not in worker_ids:
                # skip logs not belonging to target user
                continue
            total_secs += secs
            # Determine date: Tempo uses startDate (YYYY-MM-DD) plus startTime
            sdate = w.get("startDate")
            if not sdate:
                # try started field pattern
                started = w.get("started")
                if started:
                    if "T" in started:
                        sdate = started.split("T", 1)[0]
            if sdate:
                try:
                    d = dt.datetime.strptime(sdate, "%Y-%m-%d").date()
                    if d == today_date:
                        today_secs += secs
                except Exception:
                    pass
        return today_secs, total_secs

    # -------- Bulk aggregation (preferred for many issues) --------
    def aggregate_issue_times(self, *, issue_keys: List[str], account_id: str,
                               alt_workers: Optional[List[str]] = None,
                               days_back: int = 365*3) -> Dict[str, Tuple[int, int]]:
        """Return mapping issue_key -> (today_secs, total_secs) using a single (or few) Tempo calls.

        Strategy:
          1. Build worker candidate list (accountId + alternates) and attempt to retrieve a superset of
             worklogs for the user over the window [today-days_back .. today].
          2. Filter locally by issue key for accuracy and speed instead of one HTTP call per issue.

        NOTE: Tempo's API may not support very large ranges for certain tenants; if performance becomes
        problematic consider narrowing days_back or implementing caching.
        """
        today = dt.date.today()
        from_date = today - dt.timedelta(days=days_back)
        worker_ids: List[str] = [account_id]
        if alt_workers:
            for w in alt_workers:
                if w and w not in worker_ids:
                    worker_ids.append(w)

        # Attempt worker-filtered fetches first; fall back to unfiltered if empty.
        all_logs: List[Dict] = []
        for wid in worker_ids:
            try:
                # Use iter_issue_worklogs with no issue filter by passing fake param combos: we simulate by
                # calling underlying endpoint directly here for clarity.
                offset = 0
                page_limit = 200
                got_any = False
                while True:
                    params = {
                        "worker": wid,
                        "from": from_date.strftime("%Y-%m-%d"),
                        "to": today.strftime("%Y-%m-%d"),
                        "limit": page_limit,
                        "offset": offset
                    }
                    r = self.session.get(f"{self.BASE}/worklogs", params=params, timeout=30)
                    if r.status_code == 404:
                        break
                    r.raise_for_status()
                    data = r.json() or {}
                    batch = data.get("results", []) or data.get("worklogs", []) or []
                    if not batch:
                        break
                    got_any = True
                    all_logs.extend(batch)
                    if len(batch) < page_limit:
                        break
                    offset += len(batch)
                if got_any:
                    break  # accept first successful worker variant
            except Exception:
                continue
        if not all_logs:
            # Last resort: unfiltered (may be heavy) then filter author locally
            try:
                offset = 0
                page_limit = 200
                while True:
                    params = {
                        "from": from_date.strftime("%Y-%m-%d"),
                        "to": today.strftime("%Y-%m-%d"),
                        "limit": page_limit,
                        "offset": offset
                    }
                    r = self.session.get(f"{self.BASE}/worklogs", params=params, timeout=30)
                    if r.status_code == 404:
                        break
                    r.raise_for_status()
                    data = r.json() or {}
                    batch = data.get("results", []) or data.get("worklogs", []) or []
                    if not batch:
                        break
                    all_logs.extend(batch)
                    if len(batch) < page_limit:
                        break
                    offset += len(batch)
            except Exception:
                pass

        issue_set = set(issue_keys)
        totals: Dict[str, Tuple[int, int]] = {k: (0, 0) for k in issue_keys}
        today_date = today
        for wl in all_logs:
            # Identify issue key
            issue_obj = wl.get("issue") or {}
            ik = issue_obj.get("key") or issue_obj.get("issueKey") or wl.get("issueKey") or wl.get("issue")
            if not ik or ik not in issue_set:
                continue
            # Author filter
            author = wl.get("author") or {}
            author_id = author.get("accountId") or wl.get("authorAccountId") or author.get("name") or author.get("key")
            if author_id not in worker_ids:
                continue
            secs = int(wl.get("timeSpentSeconds") or 0)
            today_secs, total_secs = totals.get(ik, (0, 0))
            total_secs += secs
            # Determine worklog date
            sdate = wl.get("startDate")
            if not sdate:
                started = wl.get("started")
                if started and "T" in started:
                    sdate = started.split("T", 1)[0]
            if sdate:
                try:
                    d = dt.datetime.strptime(sdate, "%Y-%m-%d").date()
                    if d == today_date:
                        today_secs += secs
                except Exception:
                    pass
            totals[ik] = (today_secs, total_secs)
        return totals

    # -------- Precise per-issue user query (preferred) --------
    def get_user_issue_time(self, *, issue_key: str, issue_id: Optional[str] = None, account_id: str, days_back: int = 365*5) -> Tuple[int, int]:
        """Return (today_secs, total_secs) for a single issue & user using direct filtered calls.

        Tempo Cloud (v4) supports filtering worklogs. issueId (numeric) is preferred over issue key.
        We paginate until exhaustion. We constrain by from= (days_back) to reduce dataset but wide enough
        to include historical time (default 5 years). If you need older, increase days_back.
        """
        today = dt.date.today()
        from_date = today - dt.timedelta(days=days_back)
        
        # Build query parameters - Tempo API v4 accepts issueId (numeric) and worker (accountId)
        params = {
            "worker": account_id,
            "from": from_date.strftime("%Y-%m-%d"),
            "to": today.strftime("%Y-%m-%d"),
            "limit": 100
        }
        
        # Add issue filter - prefer issueId (numeric) over issue key
        if issue_id:
            params["issueId"] = int(issue_id)
        else:
            # Fallback: some Tempo instances might accept other issue parameters
            # but issueId is the standard for API v4
            pass
        
        debug = os.environ.get("TEMPOY_DEBUG")
        total = 0
        today_total = 0
        
        if debug:
            print(f"[TEMPOY DEBUG] Querying Tempo API with params: {params}")
        
        # Paginate through results
        offset = 0
        max_pages = 20  # Reasonable limit
        page_count = 0
        
        while page_count < max_pages:
            current_params = dict(params)
            current_params.update({
                "offset": offset
            })
            
            if debug:
                print(f"[TEMPOY DEBUG] Page {page_count+1}, offset {offset}")
            
            try:
                r = self.session.get(f"{self.BASE}/worklogs", params=current_params, timeout=30)
                r.raise_for_status()
                
                data = r.json() or {}
                batch = data.get("results", [])
                
                if not batch:
                    if debug:
                        print(f"[TEMPOY DEBUG] No more worklogs, ending pagination")
                    break
                    
                if debug:
                    print(f"[TEMPOY DEBUG] Got {len(batch)} worklogs")
                
            except Exception as e:
                if debug:
                    print(f"[TEMPOY DEBUG] API request failed: {e}")
                break
            
            # Process worklogs - since we filtered by worker and issueId, all should be relevant
            for wl in batch:
                # Verify this is for the correct issue (if we're filtering by issue)
                if issue_id:
                    wl_issue = wl.get("issue", {})
                    wl_issue_id = wl_issue.get("id")
                    if str(wl_issue_id) != str(issue_id):
                        continue
                
                # Verify this is for the correct user (double-check since API should filter)
                wl_author = wl.get("author", {})
                wl_account_id = wl_author.get("accountId")
                
                if wl_account_id != account_id:
                    if debug:
                        print(f"[TEMPOY DEBUG] Skipping worklog - author {wl_account_id} != {account_id}")
                    continue
                
                secs = int(wl.get("timeSpentSeconds") or 0)
                total += secs
                
                # Check if this worklog is for today
                sdate = wl.get("startDate")
                if sdate:
                    try:
                        if dt.datetime.strptime(sdate, "%Y-%m-%d").date() == today:
                            today_total += secs
                    except Exception:
                        pass
                        
                if debug:
                    print(f"[TEMPOY DEBUG] Processed worklog: {secs}s on {sdate}")
            
            # Check if we should continue pagination
            if len(batch) < params["limit"]:
                if debug:
                    print(f"[TEMPOY DEBUG] Received {len(batch)} < {params['limit']}, ending pagination")
                break
                
            offset += len(batch)
            page_count += 1
        
        if debug:
            print(f"[TEMPOY DEBUG] Final result for {issue_key} (ID: {issue_id}): today={today_total}s, total={total}s")
        
        return today_total, total

    def get_user_daily_total(self, *, account_id: str, days_back: int = 1) -> int:
        """Return total seconds logged by user today across all issues."""
        today = dt.date.today()
        from_date = today - dt.timedelta(days=days_back)
        
        # Build query parameters for today's worklogs
        params = {
            "worker": account_id,
            "from": today.strftime("%Y-%m-%d"),
            "to": today.strftime("%Y-%m-%d"),
            "limit": 200
        }
        
        debug = os.environ.get("TEMPOY_DEBUG")
        daily_total = 0
        
        if debug:
            print(f"[TEMPOY DEBUG] Querying daily total with params: {params}")
        
        # Paginate through results
        offset = 0
        max_pages = 20
        page_count = 0
        
        while page_count < max_pages:
            current_params = dict(params)
            current_params["offset"] = offset
            
            try:
                r = self.session.get(f"{self.BASE}/worklogs", params=current_params, timeout=30)
                r.raise_for_status()
                
                data = r.json() or {}
                batch = data.get("results", [])
                
                if not batch:
                    break
                    
                # Process worklogs for today
                for wl in batch:
                    # Verify this is for the correct user
                    wl_author = wl.get("author", {})
                    wl_account_id = wl_author.get("accountId")
                    
                    if wl_account_id != account_id:
                        continue
                    
                    # Check if worklog is for today
                    sdate = wl.get("startDate")
                    if sdate:
                        try:
                            if dt.datetime.strptime(sdate, "%Y-%m-%d").date() == today:
                                secs = int(wl.get("timeSpentSeconds") or 0)
                                daily_total += secs
                        except Exception:
                            pass
                
                if len(batch) < params["limit"]:
                    break
                    
                offset += len(batch)
                page_count += 1
                
            except Exception as e:
                if debug:
                    print(f"[TEMPOY DEBUG] Daily total request failed: {e}")
                break
        
        if debug:
            print(f"[TEMPOY DEBUG] Daily total: {daily_total}s")
        
        return daily_total

    def get_recent_worked_issues(self, *, account_id: str, days_back: int = 7) -> List[Dict]:
        """Get recent worklogs for the user to find issues they've worked on.
        
        Returns list of worklog objects that include issue information.
        Used to find issues the user has logged time on recently, even if not assigned.
        """
        today = dt.date.today()
        from_date = today - dt.timedelta(days=days_back)
        
        params = {
            "worker": account_id,
            "from": from_date.strftime("%Y-%m-%d"),
            "to": today.strftime("%Y-%m-%d"),
            "limit": 200
        }
        
        debug = os.environ.get("TEMPOY_DEBUG")
        collected: List[Dict] = []
        
        if debug:
            print(f"[DEBUG] Fetching recent worklogs for {account_id} from {from_date} to {today}")
        
        # Paginate through results
        offset = 0
        max_pages = 10
        page_count = 0
        
        while page_count < max_pages:
            params["offset"] = offset
            page_count += 1
            
            try:
                r = self.session.get(f"{self.BASE}/worklogs", params=params, timeout=30)
                r.raise_for_status()
                data = r.json() or {}
                
                results = data.get("results", [])
                if not results:
                    break
                
                collected.extend(results)
                
                # Check if we have more pages
                metadata = data.get("metadata", {})
                total = metadata.get("count", 0)
                
                if len(collected) >= total:
                    break
                
                offset += len(results)
                
            except Exception as e:
                if debug:
                    print(f"[DEBUG] Error fetching recent worklogs: {e}")
                break
        
        if debug:
            print(f"[DEBUG] Found {len(collected)} recent worklogs")
        
        return collected

    def get_last_logged_date(self, *, issue_key: str, issue_id: Optional[str] = None, account_id: str, days_back: int = 365) -> Optional[str]:
        """Get the most recent date when the user logged time on this issue.
        
        Returns date string in format 'YYYY-MM-DD' or None if no worklogs found.
        """
        today = dt.date.today()
        from_date = today - dt.timedelta(days=days_back)
        
        debug = os.environ.get("TEMPOY_DEBUG")
        
        # Try different approaches to find worklogs for this issue
        attempts = []
        
        # First attempt: use issueId if available
        if issue_id:
            attempts.append(("issueId", {"issueId": int(issue_id)}))
        
        # Second attempt: try without any issue filter and filter manually
        attempts.append(("manual_filter", {}))
        
        for attempt_name, extra_params in attempts:
            params = {
                "worker": account_id,
                "from": from_date.strftime("%Y-%m-%d"),
                "to": today.strftime("%Y-%m-%d"),
                "limit": 200  # Get more entries to ensure we find all recent ones
            }
            params.update(extra_params)
            
            if debug:
                print(f"[DEBUG] Trying {attempt_name} for {issue_key} with params: {params}")
            
            try:
                r = self.session.get(f"{self.BASE}/worklogs", params=params, timeout=30)
                r.raise_for_status()
                data = r.json() or {}
                
                results = data.get("results", [])
                if debug:
                    print(f"[DEBUG] {attempt_name} returned {len(results)} worklogs for {issue_key}")
                
                # Filter results to only this issue if we're doing manual filtering
                if attempt_name == "manual_filter":
                    filtered_results = []
                    for worklog in results:
                        issue_obj = worklog.get("issue", {})
                        worklog_key = issue_obj.get("key")
                        if worklog_key == issue_key:
                            filtered_results.append(worklog)
                    results = filtered_results
                    if debug:
                        print(f"[DEBUG] After filtering by {issue_key}: {len(results)} worklogs")
                
                if not results:
                    continue
                
                # Find the most recent worklog by comparing startDate + startTime
                most_recent_entry = None
                most_recent_datetime = None
                
                for worklog in results:
                    start_date = worklog.get("startDate")  # YYYY-MM-DD
                    start_time = worklog.get("startTime")  # HH:MM:SS
                    
                    if not start_date:
                        continue
                    
                    try:
                        # Parse the full datetime to find the truly most recent entry
                        if start_time:
                            datetime_str = f"{start_date} {start_time}"
                            worklog_datetime = dt.datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
                        else:
                            # If no time, just use the date (assume start of day)
                            worklog_datetime = dt.datetime.strptime(start_date, "%Y-%m-%d")
                        
                        if most_recent_datetime is None or worklog_datetime > most_recent_datetime:
                            most_recent_datetime = worklog_datetime
                            most_recent_entry = worklog
                            
                    except Exception as e:
                        if debug:
                            print(f"[DEBUG] Error parsing datetime for worklog: {e}")
                        continue
                
                if most_recent_entry:
                    result_date = most_recent_entry.get("startDate")
                    if debug:
                        print(f"[DEBUG] Found most recent worklog for {issue_key} using {attempt_name}: {result_date}")
                    return result_date
                    
            except Exception as e:
                if debug:
                    print(f"[DEBUG] {attempt_name} failed for {issue_key}: {e}")
                continue
        
        if debug:
            print(f"[DEBUG] No worklogs found for {issue_key} after all attempts")
        return None
