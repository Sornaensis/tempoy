from __future__ import annotations


SEARCH_PLACEHOLDER = "Search issue to select/add… Enter = search"
SEARCH_TOOLTIP = "Search for an issue to select, then use Add selected issue in Daily Allocation."
GRID_FILTER_PLACEHOLDER = "Filter visible tickets by key or title…"
GRID_FILTER_TOOLTIP = "Filters only the expanded ticket browser; it does not change the selected issue search."
ISSUE_BROWSER_INITIAL_STATUS = "No relevant tickets loaded yet. Press Refresh issues to populate the browser."
ISSUE_BROWSER_EMPTY_STATUS = "No relevant tickets loaded yet. Press Refresh issues to load assigned and recently worked tickets."
ISSUE_BROWSER_REFRESHING = "Refreshing relevant tickets…"
CLEAR_HISTORY_TOOLTIP = "Clear search & issue history"
SHOW_HIDE_BROWSER_TOOLTIP = "Show or hide the ticket browser"
WORKLOG_DESCRIPTION_PLACEHOLDER = "Optional description / comment for the worklog"
AUTH_ERROR_TITLE = "Auth error"
AUTH_ERROR_INIT_FAILED_TEMPLATE = "Failed to initialize clients:\n{message}"
SEARCH_TITLE = "Search"
SEARCH_NO_ISSUES = "No issues found."
SEARCH_FAILED_TITLE = "Search failed"
LOAD_FAILED_TITLE = "Load failed"
REFRESH_ISSUES_BUTTON = "Refresh issues (assigned + worked on)"
ALLOCATION_TITLE = "Allocation"
ALLOCATION_SELECT_GRID_FIRST = "Select an issue in the grid first."
ALLOCATION_SUM_MUST_BE_100 = "Allocation must sum exactly to 100% before submit."
ALLOCATION_ADD_ONE_ISSUE = "Add at least one issue to submit the day."
ALLOCATION_NO_NONZERO = "Your allocation draft is saved, but there is no non-zero time to submit yet."
ALLOCATION_SUBMITTED_TITLE = "Allocation submitted"
ALLOCATION_SUBMITTED_PREFIX = "Submitted worklogs for:\n"
ALLOCATION_PARTIAL_FAILURE_TITLE = "Allocation submit completed with issues"
SELECT_ISSUE_TITLE = "Select issue"
SELECT_ISSUE_MESSAGE = "Pick or search for an issue first."
MISSING_ISSUE_ID_TITLE = "Missing Issue ID"
LOG_FAILED_TITLE = "Log failed"
DAILY_LIMIT_TITLE = "Daily limit"
DAILY_LIMIT_ZERO = "Daily limit is set to 0m, so logging is disabled until you update Settings."
DAILY_LIMIT_LOADING = "Loading today's remaining time…"
REMINDER_TITLE = "Time reminder"
REMINDER_BODY = "Don't forget to register your time in Tempo."
REMINDER_BODY_WITH_NEXT_TEMPLATE = "Don't forget to register your time in Tempo. Next reminder: {time_text} local time."
REMINDER_TIME_TOOLTIP = "Reminder time uses your local system time."
TIMER_BUTTON_STARTING = "Starting..."
TIMER_BUTTON_STOPPED = "⏸ Stopped"
TIMER_BUTTON_PAUSED_LOCKED = "⏸ Paused (Locked)"
TIMER_BUTTON_RESUME = "⏸ Resume?"
TIMER_BUTTON_PAUSED = "⏸ Paused"
TIMER_BUTTON_READY = "⏱ Ready"
REMINDER_TIMER_STOPPED_TOOLTIP = "Reminder timer is stopped."
REMINDER_TIMER_DISABLED_TOOLTIP = "Daily reminder is disabled."
REMINDER_TIMER_READY_TOOLTIP = "Next reminder will be scheduled using your local system time."
REMINDER_TIMER_NEXT_TEMPLATE = "Next reminder: {time_text} local time"
TRAY_LOGGED_TEMPLATE = "Logged +{minutes}m to {issue_key}"
CLEAR_HISTORY_TITLE = "Clear History"
CLEAR_HISTORY_CONFIRMATION = "Clear all search and selected issue history entries?"
DAILY_LIMIT_REACHED_TEMPLATE = "Daily limit reached ({logged} / {limit})"
DAILY_LIMIT_REMAINING_TEMPLATE = "Remaining today: {remaining} of {limit} ({logged} logged)"
ALLOCATION_EXCEEDS_REMAINING_TEMPLATE = "Allocation exceeds remaining time today. Reduce it to {remaining} or less before submitting."
DAILY_LIMIT_INCREMENT_DISABLED_TEMPLATE = "Only {remaining} remains today, so +{minutes}m is disabled."
ISSUE_BROWSER_REFRESH_FAILED_TEMPLATE = "Failed to refresh tickets: {message}"
ISSUE_BROWSER_FILTERED_TEMPLATE = "Showing {visible} of {total} relevant tickets for filter “{filter_text}”."
ISSUE_BROWSER_COUNT_TEMPLATE = "Showing {visible} relevant tickets."
ISSUE_BROWSER_NO_MATCHES_TEMPLATE = "No tickets match “{filter_text}”. Clear the filter to see all {total} relevant tickets."
ISSUE_BROWSER_ENRICHING_SUFFIX = "Loading parent details…"
TIME_LOADING = "Loading time..."
TIME_NONE_LOGGED = "No time logged"
TIME_FAILED_TO_LOAD = "Failed to load time"
SELECTED_ISSUE_TIME_TEMPLATE = "Today: {today} | Total: {total}"
WINDOW_TITLE_TEMPLATE = "{app_name} — Today: {daily} · Remaining: {remaining}"
PARENT_LABEL_HTML_TEMPLATE = '<span style="color:#777">Parent:</span> <a href="{parent_url}">{parent_key}</a>'
PARENT_LABEL_HTML_WITH_SUMMARY_TEMPLATE = '<span style="color:#777">Parent:</span> <a href="{parent_url}">{parent_key}</a> — {parent_summary}'
PARENT_LABEL_PLAIN_TEMPLATE = "Parent: {parent_key}"
PARENT_LABEL_PLAIN_WITH_SUMMARY_TEMPLATE = "Parent: {parent_key} — {parent_summary}"


def issue_browser_refresh_failed_status(message: str) -> str:
	return ISSUE_BROWSER_REFRESH_FAILED_TEMPLATE.format(message=message)


def issue_browser_filtered_status(visible: int, total: int, filter_text: str) -> str:
	return ISSUE_BROWSER_FILTERED_TEMPLATE.format(visible=visible, total=total, filter_text=filter_text)


def issue_browser_count_status(visible: int) -> str:
	return ISSUE_BROWSER_COUNT_TEMPLATE.format(visible=visible)


def issue_browser_no_matches_status(filter_text: str, total: int) -> str:
	return ISSUE_BROWSER_NO_MATCHES_TEMPLATE.format(filter_text=filter_text, total=total)


def issue_browser_enriching_status(base_text: str) -> str:
	base = (base_text or "").strip()
	if not base:
		return ISSUE_BROWSER_ENRICHING_SUFFIX
	return f"{base} · {ISSUE_BROWSER_ENRICHING_SUFFIX}"


def daily_limit_reached(logged: str, limit: str) -> str:
	return DAILY_LIMIT_REACHED_TEMPLATE.format(logged=logged, limit=limit)


def daily_limit_remaining(remaining: str, limit: str, logged: str) -> str:
	return DAILY_LIMIT_REMAINING_TEMPLATE.format(remaining=remaining, limit=limit, logged=logged)


def allocation_exceeds_remaining(remaining: str) -> str:
	return ALLOCATION_EXCEEDS_REMAINING_TEMPLATE.format(remaining=remaining)


def daily_limit_increment_disabled(remaining: str, minutes: int) -> str:
	return DAILY_LIMIT_INCREMENT_DISABLED_TEMPLATE.format(remaining=remaining, minutes=minutes)


def tray_logged(minutes: int, issue_key: str) -> str:
	return TRAY_LOGGED_TEMPLATE.format(minutes=minutes, issue_key=issue_key)


def reminder_timer_next(time_text: str) -> str:
	return REMINDER_TIMER_NEXT_TEMPLATE.format(time_text=time_text)


def reminder_body_with_next(time_text: str) -> str:
	return REMINDER_BODY_WITH_NEXT_TEMPLATE.format(time_text=time_text)


def auth_error_init_failed(message: str) -> str:
	return AUTH_ERROR_INIT_FAILED_TEMPLATE.format(message=message)


def reminder_countdown(total_seconds: int) -> str:
	total = max(0, int(total_seconds))
	hours, rem = divmod(total, 3600)
	mins, secs = divmod(rem, 60)
	if hours > 0:
		return f"⏱ {hours}:{mins:02d}:{secs:02d}"
	if mins > 0:
		return f"⏱ {mins}:{secs:02d}"
	return f"⏱ {secs}s"


def selected_issue_time(today: str, total: str) -> str:
	return SELECTED_ISSUE_TIME_TEMPLATE.format(today=today, total=total)


def window_title(app_name: str, daily: str, remaining: str) -> str:
	return WINDOW_TITLE_TEMPLATE.format(app_name=app_name, daily=daily, remaining=remaining)


def parent_label_html(parent_key: str, parent_url: str, parent_summary: str = "") -> str:
	if parent_summary:
		return PARENT_LABEL_HTML_WITH_SUMMARY_TEMPLATE.format(parent_key=parent_key, parent_url=parent_url, parent_summary=parent_summary)
	return PARENT_LABEL_HTML_TEMPLATE.format(parent_key=parent_key, parent_url=parent_url)


def parent_label_plain(parent_key: str, parent_summary: str = "") -> str:
	if parent_summary:
		return PARENT_LABEL_PLAIN_WITH_SUMMARY_TEMPLATE.format(parent_key=parent_key, parent_summary=parent_summary)
	return PARENT_LABEL_PLAIN_TEMPLATE.format(parent_key=parent_key)
