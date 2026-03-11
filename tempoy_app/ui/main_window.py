#!/usr/bin/env python3
"""
Tempoy — a minimal cross‑platform floating window to log time to Tempo for Jira issues.

Features:
- Always‑on‑top, collapsible mini bar for quick time logging (5,10,15,20,30,60 min).
- Shows your assigned issues grouped by status; search by key or text.
- Logs work to Tempo (Cloud) via API v4.
- Optional periodic reminder to log time via system tray notifications.

Setup (first run opens Settings dialog automatically):
- Jira Cloud: base URL (e.g., https://your-domain.atlassian.net), email, API token.
- Tempo Cloud: API token.
Tokens are stored in a local config file in your home directory (~/.tempoy/config.json).
On first run after rename, any legacy ~/.tempo_floater/config.json will be migrated automatically.
Review the README for security notes.
"""
from __future__ import annotations

import sys
import os
import datetime as dt
import time
from typing import Dict, List, Optional, Tuple
import threading

from PySide6 import QtCore, QtGui, QtWidgets

from tempoy_app.api.jira import JiraClient
from tempoy_app.api.tempo import TempoClient
from tempoy_app.config import AppConfig, ConfigManager
from tempoy_app.formatting import format_relative_time, format_seconds
from tempoy_app.logging_utils import debug_enabled, debug_log
from tempoy_app.models import AllocationState, IssueSnapshot
from tempoy_app.services.allocation_service import AllocationService
from tempoy_app.services.cache_service import CacheService
from tempoy_app.services.issue_catalog import IssueCatalog
from tempoy_app.services.reminder_service import ReminderService
from tempoy_app.services.worklog_service import WorklogService
from tempoy_app.ui import messages
from tempoy_app.ui.allocation_panel import AllocationPanel
from tempoy_app.ui.issue_browser_state import IssueBrowserState
from tempoy_app.ui.issue_list import IssueList
from tempoy_app.ui.settings_dialog import SettingsDialog

APP_NAME = "Tempoy"

# Added finer granularity (1m & 4m) at user request
INCREMENTS_MIN = [1, 4, 5, 10, 15, 20, 30, 60]


def human_err(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"


class Floater(QtWidgets.QMainWindow):
    worklogFetched = QtCore.Signal(str, str, str)  # issue_key, today, total
    issueListRerenderRequested = QtCore.Signal()
    issueResultsFetched = QtCore.Signal(object, object, object)
    dailyTotalUpdated = QtCore.Signal()
    selectedIssueParentFetched = QtCore.Signal(str, str, int)
    allocationIssueDetailsFetched = QtCore.Signal(object, int)
    allocationParentSummariesFetched = QtCore.Signal(object, int)
    gridParentSummariesFetched = QtCore.Signal(object, int)
    def __init__(self, cfg: AppConfig):
        super().__init__()
        self.cfg = cfg
        self.jira: Optional[JiraClient] = None
        self.tempo: Optional[TempoClient] = None
        self.worklog_service: Optional[WorklogService] = None
        self.allocation_service = AllocationService()
        self.issue_catalog = IssueCatalog()
        self.reminder_service = ReminderService()
        self.issue_browser = IssueBrowserState(self.issue_catalog)
        self.account_id: Optional[str] = None
        self._current_issue_snapshots: List[IssueSnapshot] = []
        self._raw_issues_by_key: Dict[str, Dict] = {}
        self._assigned_issue_keys: set[str] = set()
        self._worked_issue_keys: set[str] = set()
        # Track selected issue for logging
        self._selected_issue_id: Optional[str] = None
        self._selected_issue_key: Optional[str] = None
        
        # Worklog caching system
        self._cache_duration = 300  # 5 minutes in seconds
        self._current_issues: List[str] = []  # Track currently displayed issues
        self._worklog_cache = CacheService()
        self._last_logged_cache = CacheService()
        
        # Window sizing for expand/collapse (from config)
        self._collapsed_size = (cfg.collapsed_width, cfg.collapsed_height)
        self._expanded_size = (cfg.expanded_width, cfg.expanded_height)
        
        # Flag to prevent resize tracking during programmatic resizing
        self._programmatic_resize = False
        self._applying_splitter_sizes = False
        
        # Track the current expanded state explicitly
        self._is_expanded = cfg.expanded
        
        # Track daily total time
        self._daily_total_secs = 0
        self._daily_total_cache_time = 0
        self._daily_total_cache_duration = 300  # 5 minutes
        self._daily_total_initialized = False
        self._grid_parent_summary_loading = False
        
        # Startup state tracking
        self._startup_complete = False
        self._daily_total_lock = threading.Lock()
        self._selected_issue_request_token = 0
        self._restore_issue_request_token = 0
        self._allocation_context_request_token = 0
        self._grid_parent_summary_request_token = 0
        
        # Timer tracking state
        self._timer_running = True  # Start in running state
        self._next_reminder_time = None

        # --- New: Paused/lock tracking state ---
        # _timer_paused differs from stopped: paused preserves remaining countdown and running flag.
        self._timer_paused = False

        self._paused_due_to_lock = False  # Whether current pause originated from workstation lock
        self._pause_time = None  # Timestamp when pause started
        self._remaining_to_next_reminder = None  # Seconds remaining to reminder when paused
        self._was_locked = False  # Previous poll lock state
        self._bring_to_front_on_unlock = False  # Defer focusing window until unlock

        # Periodic Windows lock state poller (every 3 seconds)
        self.lock_check_timer = QtCore.QTimer(self)
        self.lock_check_timer.timeout.connect(self._check_lock_state)
        self.lock_check_timer.start(3000)
        
    # Removed legacy dropdown refresh delay flag (now handled by clean data separation)
        
        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, cfg.always_on_top)

        # Collapsible header bar
        self.search = QtWidgets.QComboBox()
        self.search.setEditable(True)
        self.search.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.search.lineEdit().setPlaceholderText(messages.SEARCH_PLACEHOLDER)
        self.search.setToolTip(messages.SEARCH_TOOLTIP)
        self.search.lineEdit().returnPressed.connect(self.on_search)
        self.search.activated.connect(self.on_search_from_dropdown)
        # Initialize search history dropdown
        self._populate_search_history()
        self.issue_label = QtWidgets.QLabel("—")
        self.issue_label.setTextFormat(QtCore.Qt.RichText)
        self.issue_label.setOpenExternalLinks(True)
        self.time_label = QtWidgets.QLabel("")
        self.time_label.setStyleSheet("QLabel { color: #666; font-size: 11px; }")
        self.btn_expand = QtWidgets.QToolButton(text="▼")
        self.btn_expand.setCheckable(True)
        self.btn_expand.setChecked(cfg.expanded)  # Restore saved state
        self.btn_expand.setToolTip(messages.SHOW_HIDE_BROWSER_TOOLTIP)
        self.btn_expand.toggled.connect(self.on_toggle_expand)
        self.btn_settings = QtWidgets.QToolButton(text="⚙")
        self.btn_settings.clicked.connect(self.open_settings)

        # Two-row increment button layout
        inc_grid = QtWidgets.QGridLayout()
        inc_grid.setHorizontalSpacing(6)
        inc_grid.setVerticalSpacing(4)
        half = (len(INCREMENTS_MIN) + 1) // 2  # top row length
        self._increment_buttons: dict[int, QtWidgets.QPushButton] = {}
        for idx, m in enumerate(INCREMENTS_MIN):
            row = 0 if idx < half else 1
            col = idx if row == 0 else idx - half
            b = QtWidgets.QPushButton(f"+{m}m")
            b.setFixedHeight(26)
            b.clicked.connect(lambda _, mm=m: self.log_increment(minutes=mm))
            inc_grid.addWidget(b, row, col)
            self._increment_buttons[m] = b

        # Timer control button spans both rows at the end
        self.timer_btn = QtWidgets.QPushButton(messages.TIMER_BUTTON_STARTING)
        self.timer_btn.setMinimumWidth(100)
        self.timer_btn.setFixedHeight(56)  # approximate two button heights + spacing
        self.timer_btn.clicked.connect(self._toggle_timer)
        timer_col = half  # place after last column of top row
        inc_grid.addWidget(self.timer_btn, 0, timer_col, 2, 1)

        inc_container = QtWidgets.QWidget()
        inc_container.setLayout(inc_grid)

        header = QtWidgets.QHBoxLayout()
        header.addWidget(self.btn_expand, 0)
        header.addWidget(self.search, 1)
        # Clear history button
        self.btn_clear_history = QtWidgets.QToolButton(text="🗑")
        self.btn_clear_history.setToolTip(messages.CLEAR_HISTORY_TOOLTIP)
        self.btn_clear_history.clicked.connect(self._on_clear_history)
        header.addWidget(self.btn_clear_history, 0)
        header.addWidget(self.btn_settings, 0)

        head2 = QtWidgets.QHBoxLayout()
        
        # Create layout for issue + parent labels on one row, time below
        self.parent_label = QtWidgets.QLabel("")
        self.parent_label.setTextFormat(QtCore.Qt.RichText)
        self.parent_label.setOpenExternalLinks(True)
        self.parent_label.setStyleSheet("QLabel { color: #555; }")

        issue_row = QtWidgets.QHBoxLayout()
        issue_row.setSpacing(12)
        issue_row.addWidget(self.issue_label, 0)
        issue_row.addWidget(self.parent_label, 0)
        issue_row.addStretch(1)

        issue_info = QtWidgets.QVBoxLayout()
        issue_info.setSpacing(2)
        issue_info.addLayout(issue_row)
        issue_info.addWidget(self.time_label)
        issue_info_widget = QtWidgets.QWidget()
        issue_info_widget.setLayout(issue_info)

        head2.addWidget(issue_info_widget, 1)
        head2.addWidget(inc_container, 0)

        head_widget = QtWidgets.QWidget()
        vhead = QtWidgets.QVBoxLayout(head_widget)
        vhead.setContentsMargins(8, 8, 8, 8)
        vhead.addLayout(header)
        vhead.addLayout(head2)

        # Expanded area
        self.issue_list = IssueList()
        self.issue_list.issueSelected.connect(self.on_issue_selected)
        self.issue_list.columnResized.connect(self._on_column_resized)  # Connect to column resize signal
        
        # Restore saved column widths
        self.issue_list.restore_column_widths(cfg.issue_list_column_widths)
        
        self.btn_refresh = QtWidgets.QPushButton(messages.REFRESH_ISSUES_BUTTON)
        self.btn_refresh.clicked.connect(self.refresh_assigned)

        self.grid_filter = QtWidgets.QLineEdit()
        self.grid_filter.setPlaceholderText(messages.GRID_FILTER_PLACEHOLDER)
        self.grid_filter.setToolTip(messages.GRID_FILTER_TOOLTIP)
        self.grid_filter.textChanged.connect(self._on_grid_filter_changed)

        self.issue_browser_status = QtWidgets.QLabel(messages.ISSUE_BROWSER_INITIAL_STATUS)
        self.issue_browser_status.setWordWrap(True)
        self.issue_browser_status.setStyleSheet("QLabel { color: #666; font-size: 11px; }")

        self.desc = QtWidgets.QLineEdit()
        self.desc.setPlaceholderText(messages.WORKLOG_DESCRIPTION_PLACEHOLDER)

        self.daily_limit_label = QtWidgets.QLabel("")
        self.daily_limit_label.setWordWrap(True)
        self.daily_limit_label.setStyleSheet("QLabel { color: #666; font-size: 11px; }")

        self.allocation_panel = AllocationPanel(self.allocation_service, self.cfg.daily_time_seconds)
        self.allocation_panel.set_jira_base_url(self.cfg.jira_base_url)
        self.allocation_panel.addSelectedIssueRequested.connect(self._add_selected_issue_to_allocation_panel)
        self.allocation_panel.submitRequested.connect(self._submit_allocation)
        self.allocation_panel.stateChanged.connect(self._persist_allocation_draft)
        self.allocation_panel.stateChanged.connect(lambda _: self._refresh_submission_controls())
        self._restore_allocation_draft()

        expanded = QtWidgets.QWidget()
        lay_exp = QtWidgets.QVBoxLayout(expanded)
        lay_exp.setContentsMargins(8, 0, 8, 8)
        lay_exp.addWidget(self.btn_refresh)
        lay_exp.addWidget(self.grid_filter)
        lay_exp.addWidget(self.issue_browser_status)
        lay_exp.addWidget(self.issue_list, 1)
        lay_exp.addWidget(self.desc)

        self.expanded = expanded
        self.expanded.setVisible(False)

        self.main_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(8)
        self.main_splitter.addWidget(self.allocation_panel)
        self.main_splitter.addWidget(self.expanded)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.splitterMoved.connect(self._on_main_splitter_moved)

        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central)
        v.addWidget(head_widget)
        v.addWidget(self.daily_limit_label)
        v.addWidget(self.main_splitter, 1)
        self.setCentralWidget(central)

        # Tray icon + menu with fallback icon
        tray_icon = QtGui.QIcon.fromTheme("alarm", QtGui.QIcon())
        if tray_icon.isNull():
            tray_icon = self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon)
        self.tray = QtWidgets.QSystemTrayIcon(tray_icon)
        self.tray.setToolTip(APP_NAME)
        menu = QtWidgets.QMenu()
        act_show = menu.addAction("Show / Hide")
        act_show.triggered.connect(self.toggle_visibility)
        self.act_log5 = menu.addAction("Log +5m to last issue")
        self.act_log5.triggered.connect(lambda: self.log_increment(5, to_last=True))
        menu.addSeparator()
        act_quit = menu.addAction("Quit")
        act_quit.triggered.connect(QtWidgets.QApplication.instance().quit)
        self.tray.setContextMenu(menu)
        self.tray.show()
        
        # Connect tray icon signals to bring window to focus
        # Use a safer approach on Windows to prevent console spawning
        self.tray.messageClicked.connect(self._safe_bring_to_front)
        self.tray.activated.connect(self._on_tray_activated)

        # Reminder timer
        self.reminder_timer = QtCore.QTimer(self)
        self.reminder_timer.timeout.connect(self._remind)
        
        # Countdown display timer (updates every second)
        self.countdown_timer = QtCore.QTimer(self)
        self.countdown_timer.timeout.connect(self._update_countdown)
        self.countdown_timer.start(1000)  # Update every second
        
        self._reset_reminder()
        
        # Periodic worklog refresh timer (every 5 minutes)
        self.worklog_refresh_timer = QtCore.QTimer(self)
        self.worklog_refresh_timer.timeout.connect(self._refresh_worklog_cache)
        self.worklog_refresh_timer.start(300000)  # 5 minutes
        
        # Periodic daily total refresh timer (every 10 minutes)
        # Don't start until after startup is complete
        self.daily_total_timer = QtCore.QTimer(self)
        self.daily_total_timer.timeout.connect(self._refresh_daily_total)

        # Defer client initialization until after window is shown
        QtCore.QTimer.singleShot(50, self._delayed_init)

        # Connect worklog signal to list updater and selected issue updater
        self.worklogFetched.connect(self.issue_list.update_worklog)
        self.worklogFetched.connect(self._on_worklog_fetched)
        self.issueListRerenderRequested.connect(self._rerender_issue_list_from_state)
        self.issueResultsFetched.connect(self._on_issue_results_fetched)
        self.dailyTotalUpdated.connect(self._on_daily_total_updated)
        self.selectedIssueParentFetched.connect(self._apply_selected_issue_parent_summary)
        self.allocationIssueDetailsFetched.connect(self._apply_allocation_issue_details)
        self.allocationParentSummariesFetched.connect(self._apply_allocation_parent_summaries)
        self.gridParentSummariesFetched.connect(self._apply_grid_parent_summaries)
        self._register_shortcuts()

        # Position and size window from saved config
        if cfg.expanded:
            self.resize(*self._expanded_size)
            self.expanded.setVisible(True)
            self.btn_expand.setText("▲")
            self._apply_main_splitter_sizes(self.cfg.expanded_splitter_sizes)
        else:
            self.resize(*self._collapsed_size)
            self.expanded.setVisible(False)
            self.btn_expand.setText("▼")
            self._apply_main_splitter_sizes([max(260, self.height()), 0])
        
        self.move(cfg.window_x, cfg.window_y)
        # Set reasonable minimum size but not too restrictive
        self.setMinimumSize(300, 240)  # Prevent window from getting too small for the always-visible allocation panel
        self._refresh_submission_controls()

    def _delayed_init(self):
        """Initialize clients after window is shown to ensure proper UI updates."""
        debug_log("_delayed_init called")
        
        # Initialize clients if config is present
        self.ensure_clients()

    def _next_request_token(self, attr_name: str) -> int:
        next_token = int(getattr(self, attr_name, 0)) + 1
        setattr(self, attr_name, next_token)
        return next_token

    def _is_current_request(self, attr_name: str, request_token: int) -> bool:
        return int(getattr(self, attr_name, 0)) == int(request_token)

    def _start_background_worker(self, name: str, target, *args):
        debug_log("Starting background worker: %s", name)
        threading.Thread(target=target, args=args, daemon=True).start()

    def _set_daily_total_initialized(self, initialized: bool):
        self._daily_total_initialized = bool(initialized)

    def _set_grid_parent_summary_loading(self, loading: bool):
        self._grid_parent_summary_loading = bool(loading)
        self._update_issue_browser_status()

    def _set_selected_issue_time_loading(self):
        self.time_label.setText(messages.TIME_LOADING)

    def _set_selected_issue_time_failed(self):
        self.time_label.setText(messages.TIME_FAILED_TO_LOAD)

    def _set_daily_limit_loading_state(self):
        self.allocation_panel.set_remaining_seconds(0)
        self.daily_limit_label.setText(messages.DAILY_LIMIT_LOADING)
        self.daily_limit_label.setStyleSheet("QLabel { color: #1c7ed6; font-size: 11px; font-weight: bold; }")
        self._set_submit_actions_enabled(False)

    def _apply_allocation_issue_context(self, issue_key: str, *, summary: str, parent_key: str, parent_summary: str, total_logged_seconds: int):
        self.allocation_panel.set_issue_context(
            issue_key,
            summary=summary,
            parent_key=parent_key,
            parent_summary=parent_summary,
            total_logged_seconds=total_logged_seconds,
        )

    def _begin_startup_hydration(self):
        self._update_window_title()
        self._refresh_submission_controls()
        self._request_daily_total_refresh(allow_during_startup=True, ignore_cache=True)

    def _restore_last_issue_if_needed(self):
        if self.cfg.last_issue_key:
            if debug_enabled():
                debug_log("Restoring last issue: %s", self.cfg.last_issue_key)
            self._restore_last_issue()

    def _finish_startup_initialization(self):
        self._startup_complete = True
        if debug_enabled():
            debug_log("Startup marked as complete")
        QtCore.QTimer.singleShot(1000, self._start_periodic_timers)

    # ---------- Utility ----------
    def ensure_clients(self) -> bool:
        was_initialized = bool(self.jira and self.tempo and self.account_id)
        
        if not (self.cfg.jira_base_url and self.cfg.jira_email and self.cfg.jira_api_token and self.cfg.tempo_api_token):
            self.open_settings()
        if not (self.cfg.jira_base_url and self.cfg.jira_email and self.cfg.jira_api_token and self.cfg.tempo_api_token):
            return False
        try:
            self.jira = JiraClient(self.cfg.jira_base_url, self.cfg.jira_email, self.cfg.jira_api_token)
            self.tempo = TempoClient(self.cfg.tempo_api_token)
            self.worklog_service = WorklogService(self.jira, self.tempo)
            self.account_id = self.jira.get_myself().get("accountId")
            
            # Update window title immediately to show "Today: 0m" format
            self._update_window_title()
            
            # If this is the first time clients are initialized, start proper initialization
            if not was_initialized and not self._startup_complete:
                QtCore.QTimer.singleShot(100, self._initialize_after_clients)
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, messages.AUTH_ERROR_TITLE, messages.auth_error_init_failed(human_err(e)))
            return False
        return True

    def _initialize_after_clients(self):
        """Initialize application state after clients are ready - ensures proper startup sequence."""
        debug_log("_initialize_after_clients called")
        
        if self._startup_complete:
            debug_log("Startup already complete, skipping")
            return
        
        try:
            self._begin_startup_hydration()
            self._restore_last_issue_if_needed()
            self._preload_allocation_panel_data()
            self._finish_startup_initialization()
            
        except Exception as e:
            debug_log("Error during initialization: %s", e)
            # Still mark startup complete to avoid hanging in incomplete state
            self._startup_complete = True
    
    def _start_periodic_timers(self):
        """Start periodic timers after startup is complete."""
        debug_log("Starting periodic timers")
        
        # Start daily total timer (10 minutes)
        self.daily_total_timer.start(600000)
        
        debug_log("Periodic timers started")
    
    def _toggle_timer(self):
        """Toggle timer button action depending on current state.

        Priority order:
          1. If paused -> resume.
          2. Else toggle running <-> stopped.
        """
        # If currently paused, resume instead of changing running/stopped flag
        if self._timer_paused:
            self._resume_timer()
            return

        # Normal toggle between running and stopped
        self._timer_running = not self._timer_running
        if self._timer_running:
            # Restart reminders fresh when going from stopped -> running
            self._reset_reminder()
        else:
            # Stopping clears reminders (distinct from pause which preserves)
            self.reminder_timer.stop()
            self._next_reminder_time = None
        self._update_timer_button()
    
    def _update_timer_button(self):
        """Update the timer button appearance based on current state.

        States:
          - Stopped: red
          - Paused (Locked): orange (auto pause due to lock while still locked)
          - Paused (Resume?): yellow (was locked, now unlocked waiting for manual resume)
          - Running: handled by _update_countdown (green with countdown/ready)
        """
        # Stopped overrides everything
        if not self._timer_running:
            self.timer_btn.setText(messages.TIMER_BUTTON_STOPPED)
            self.timer_btn.setStyleSheet("QPushButton { background-color: #ff6b6b; color: white; font-weight: bold; }")
            self._update_reminder_tooltip()
            return

        # Paused states
        if self._timer_paused:
            if self._paused_due_to_lock and self._was_locked:
                # Currently locked
                self.timer_btn.setText(messages.TIMER_BUTTON_PAUSED_LOCKED)
                self.timer_btn.setStyleSheet("QPushButton { background-color: #ffa94d; color: #222; font-weight: bold; }")
            elif self._paused_due_to_lock and not self._was_locked:
                # Lock released; awaiting manual resume
                self.timer_btn.setText(messages.TIMER_BUTTON_RESUME)
                self.timer_btn.setStyleSheet("QPushButton { background-color: #ffd43b; color: #222; font-weight: bold; }")
            else:
                # Generic manual pause (future-proof)
                self.timer_btn.setText(messages.TIMER_BUTTON_PAUSED)
                self.timer_btn.setStyleSheet("QPushButton { background-color: #ffec99; color: #222; font-weight: bold; }")
            self._update_reminder_tooltip()
            return

        # Running - let countdown paint it
        self._update_countdown()
    
    def _update_countdown(self):
        """Update countdown display on timer button (running state only)."""
        if not self._timer_running:
            return

        # If paused, delegate to update button (ensures correct paused style) and exit
        if self._timer_paused:
            self._update_timer_button()
            return

        if self._next_reminder_time is None:
            self.timer_btn.setText(messages.TIMER_BUTTON_READY)
            self.timer_btn.setStyleSheet("QPushButton { background-color: #51cf66; color: white; font-weight: bold; }")
            self._update_reminder_tooltip()
            return

        now = time.time()
        remaining = self._next_reminder_time - now

        if remaining <= 0:
            self.timer_btn.setText(messages.TIMER_BUTTON_READY)
            self.timer_btn.setStyleSheet("QPushButton { background-color: #51cf66; color: white; font-weight: bold; }")
        else:
            total_seconds = max(0, int(remaining))
            countdown_text = messages.reminder_countdown(total_seconds)
            self.timer_btn.setText(countdown_text)
            self.timer_btn.setStyleSheet("QPushButton { background-color: #51cf66; color: white; font-weight: bold; }")
        self._update_reminder_tooltip()

    def _update_reminder_tooltip(self):
        if not getattr(self.cfg, "reminder_enabled", True):
            self.timer_btn.setToolTip(messages.REMINDER_TIMER_DISABLED_TOOLTIP)
            return
        if not self._timer_running:
            self.timer_btn.setToolTip(messages.REMINDER_TIMER_STOPPED_TOOLTIP)
            return
        if self._next_reminder_time is None:
            self.timer_btn.setToolTip(messages.REMINDER_TIMER_READY_TOOLTIP)
            return
        self.timer_btn.setToolTip(messages.reminder_timer_next(self.reminder_service.format_local_time(self._next_reminder_time)))
    
    def _reset_reminder(self):
        self.reminder_timer.stop()
        next_reminder = self.reminder_service.next_reminder_datetime(
            reminder_enabled=bool(getattr(self.cfg, "reminder_enabled", True)),
            reminder_value=str(getattr(self.cfg, "reminder_time", "1500") or "1500"),
        )
        if next_reminder and self._timer_running and not self._timer_paused:
            remaining_seconds = max(0, int((next_reminder - dt.datetime.now()).total_seconds()))
            self.reminder_timer.start(max(1, remaining_seconds * 1000))
            self._next_reminder_time = time.time() + remaining_seconds
        else:
            self._next_reminder_time = None
        self._update_timer_button()

    # ---------------- Pausing / Lock Handling -----------------
    def _pause_timer(self, *, auto_lock: bool = False):
        """Pause the timer (distinct from stopped). Preserve remaining reminder time."""
        if self._timer_paused:
            return
        if not self._timer_running:
            # If already stopped, no special pause state
            return
        self._timer_paused = True
        self._paused_due_to_lock = auto_lock
        self._pause_time = time.time()
        # Store remaining time to reminder
        if self._next_reminder_time:
            remaining = self._next_reminder_time - self._pause_time
            self._remaining_to_next_reminder = max(0, remaining)
        else:
            self._remaining_to_next_reminder = None
        # Stop the active reminder timer while paused
        self.reminder_timer.stop()
        self._update_timer_button()

    def _resume_timer(self):
        """Resume from paused state, restoring remaining reminder interval."""
        if not self._timer_paused:
            return
        self._timer_paused = False
        # Restore reminder timer if needed
        if self._timer_running:
            if self._remaining_to_next_reminder and self._remaining_to_next_reminder > 0:
                # Resume with remaining time rather than full interval
                ms = int(self._remaining_to_next_reminder * 1000)
                self.reminder_timer.start(ms)
                self._next_reminder_time = time.time() + self._remaining_to_next_reminder
            else:
                self._reset_reminder()
        # Clear pause meta
        self._pause_time = None
        self._remaining_to_next_reminder = None
        self._paused_due_to_lock = False
        self._update_timer_button()

    def _check_lock_state(self):
        """Poll Windows lock state and handle transitions.

        Strategy:
          - Use Win32 APIs (ctypes) attempting to open the input desktop and switch it.
          - If SwitchDesktop returns False, treat as locked.
          - Fallback gracefully on any exception.
        """
        if sys.platform != "win32":
            return
        try:
            locked = self._is_workstation_locked()
        except Exception:
            # On failure, do not change state (avoid flapping)
            return

        if locked and not self._was_locked:
            self._on_lock_detected()
        elif (not locked) and self._was_locked:
            self._on_unlock_detected()
        self._was_locked = locked

    def _is_workstation_locked(self) -> bool:
        """Return True if workstation appears locked (Windows only)."""
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        DESKTOP_SWITCHDESKTOP = 0x0100
        hDesktop = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if not hDesktop:
            # If cannot open input desktop, assume locked (conservative)
            return True
        try:
            result = user32.SwitchDesktop(hDesktop)
            # When locked, SwitchDesktop returns 0 (False)
            return not bool(result)
        finally:
            user32.CloseDesktop(hDesktop)

    def _on_lock_detected(self):
        """Handle transition to locked state."""
        # Only auto-pause if actively running and not already paused
        if self._timer_running and not self._timer_paused:
            self._pause_timer(auto_lock=True)
        # Mark to bring to front on unlock (cannot force focus while locked)
        self._bring_to_front_on_unlock = True
        # Increase polling frequency while locked for quicker unlock detection
        try:
            if self.lock_check_timer.interval() != 1000:
                self.lock_check_timer.setInterval(1000)
        except Exception:
            pass
        # Update immediately to show locked paused state
        self._update_timer_button()

    def _on_unlock_detected(self):
        """Handle transition to unlocked state."""
        # If we auto-paused due to lock, change button to Resume? state (handled by _update_timer_button)
        if self._timer_paused and self._paused_due_to_lock:
            # Show resume prompt (style changes automatically because _was_locked becomes False before call completes)
            self._update_timer_button()
        # Bring window to front if requested
        if self._bring_to_front_on_unlock:
            self._bring_to_front_on_unlock = False
            self._schedule_focus_attempts()
        # Restore normal polling interval
        try:
            if self.lock_check_timer.interval() != 3000:
                self.lock_check_timer.setInterval(3000)
        except Exception:
            pass

    def _schedule_focus_attempts(self):
        """Attempt to focus/raise the window multiple times after unlock.

        Some Windows environments or other foreground restrictions may block the
        first attempt; we try a few spaced attempts to improve reliability.
        """
        # Immediate attempt
        self.bring_to_front()
        # Additional deferred attempts
        delays = [150, 350, 700]
        for d in delays:
            QtCore.QTimer.singleShot(d, self.bring_to_front)
    
    def _is_cache_valid(self, issue_key: str) -> bool:
        """Check if cached worklog data for an issue is still valid (within 5 minutes)."""
        return self._worklog_cache.get(f"worklog:{issue_key}") is not None
    
    def _get_cached_worklog(self, issue_key: str) -> Optional[Tuple[int, int]]:
        """Get cached worklog data if valid, otherwise return None."""
        cached = self._worklog_cache.get(f"worklog:{issue_key}")
        if cached is None:
            return None
        return cached
    
    def _cache_worklog(self, issue_key: str, today_secs: int, total_secs: int):
        """Cache worklog data with current timestamp."""
        self._worklog_cache.set(f"worklog:{issue_key}", (today_secs, total_secs), ttl_seconds=self._cache_duration)

    def _get_cached_last_logged(self, issue_key: str) -> Optional[str]:
        return self._last_logged_cache.get(f"last_logged:{issue_key}")

    def _cache_last_logged(self, issue_key: str, last_logged: str):
        self._last_logged_cache.set(f"last_logged:{issue_key}", last_logged, ttl_seconds=self._cache_duration)
    
    def _refresh_worklog_cache(self):
        """Periodic refresh of worklog cache for currently displayed issues."""
        if not (self.tempo and self.account_id and self._current_issues):
            return
        
        # Only refresh issues that are currently displayed
        issues_to_refresh = [key for key in self._current_issues if not self._is_cache_valid(key)]
        
        # Limit the number of issues to refresh at once to prevent API spam
        max_refresh = 5
        if len(issues_to_refresh) > max_refresh:
            issues_to_refresh = issues_to_refresh[:max_refresh]
        
        if issues_to_refresh:
            debug_log("Periodic refresh for %s issues", len(issues_to_refresh))
            # Run in background thread to avoid blocking UI
            threading.Thread(target=self._fetch_and_update_worklogs, 
                           args=(issues_to_refresh, False), daemon=True).start()

    def _on_tray_activated(self, reason):
        """Handle tray icon activation (single or double click)."""
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            # Single click - just toggle visibility
            self.toggle_visibility()
        elif reason == QtWidgets.QSystemTrayIcon.DoubleClick:
            # Double click - force show and focus
            if not self.isVisible():
                self.show()
            self.raise_()
            self.activateWindow()
    
    def _safe_bring_to_front(self):
        """Bring the window to front."""
        QtCore.QTimer.singleShot(50, self._do_bring_to_front)
    
    def bring_to_front(self):
        """Bring the window to front and focus - deferred to avoid console issues."""
        # Use a timer to defer the action to avoid console window issues
        QtCore.QTimer.singleShot(50, self._do_bring_to_front)
    
    def _do_bring_to_front(self):
        """Actually bring window to front - deferred execution."""
        try:
            if not self.isVisible():
                self.show()
            
            # Ensure window is not minimized
            if self.isMinimized():
                self.setWindowState(QtCore.Qt.WindowNoState)
            
            # Bring window to front
            self.raise_()
            self.activateWindow()
            
        except Exception:
            pass
    
    def toggle_visibility(self):
        
        if self.isVisible():
            self.hide()
        else:
            self.bring_to_front()
    
    def resizeEvent(self, event):
        """Track manual resizing to update config."""
        super().resizeEvent(event)
        
        debug = debug_enabled()
        if debug:
            new_size = event.size()
            old_size = event.oldSize()
            is_programmatic = getattr(self, '_programmatic_resize', False)
            debug_log(
                "ResizeEvent: %sx%s -> %sx%s, programmatic: %s",
                old_size.width(),
                old_size.height(),
                new_size.width(),
                new_size.height(),
                is_programmatic,
            )
        
        # Don't track resize if it's programmatic (from expand/collapse)
        if getattr(self, '_programmatic_resize', False):
            if debug:
                debug_log("Ignoring programmatic resize")
            return
        
        # Update config with new size (debounced to avoid too frequent saves)
        if hasattr(self, '_resize_timer'):
            self._resize_timer.stop()
        else:
            self._resize_timer = QtCore.QTimer()
            self._resize_timer.setSingleShot(True)
            self._resize_timer.timeout.connect(self._on_resize_finished)
        
        self._resize_timer.start(500)  # Save after 500ms of no resizing
    
    def _on_resize_finished(self):
        """Called after user finishes resizing window."""
        size = self.size()
        debug = debug_enabled()
        
        if self.btn_expand.isChecked():  # Currently expanded
            self.cfg.expanded_width = size.width()
            self.cfg.expanded_height = size.height()
            self._expanded_size = (self.cfg.expanded_width, self.cfg.expanded_height)
            if debug:
                debug_log("Saved expanded size: %sx%s", size.width(), size.height())
        else:  # Currently collapsed
            self.cfg.collapsed_width = size.width()
            self.cfg.collapsed_height = size.height()
            self._collapsed_size = (self.cfg.collapsed_width, self.cfg.collapsed_height)
            if debug:
                debug_log("Saved collapsed size: %sx%s", size.width(), size.height())
        
        ConfigManager.save(self.cfg)
    
    def moveEvent(self, event):
        """Track window movement to update config."""
        super().moveEvent(event)
        
        # Update config with new position (debounced)
        if hasattr(self, '_move_timer'):
            self._move_timer.stop()
        else:
            self._move_timer = QtCore.QTimer()
            self._move_timer.setSingleShot(True)
            self._move_timer.timeout.connect(self._on_move_finished)
        
        self._move_timer.start(500)  # Save after 500ms of no moving
    
    def _on_move_finished(self):
        """Called after user finishes moving window."""
        pos = self.pos()
        self.cfg.window_x = pos.x()
        self.cfg.window_y = pos.y()
        ConfigManager.save(self.cfg)
    
    def _verify_resize(self, expected_size):
        """Verify that resize actually worked."""
        actual_size = self.size()
        debug = debug_enabled()
        if debug:
            debug_log(
                "Resize verification - Expected: %s, Actual: %sx%s",
                expected_size,
                actual_size.width(),
                actual_size.height(),
            )
            
        if (actual_size.width(), actual_size.height()) != expected_size:
            if debug:
                debug_log("Resize verification FAILED - forcing resize again")
            # Force resize again
            self._programmatic_resize = True
            self.resize(*expected_size)
            self.setGeometry(self.x(), self.y(), expected_size[0], expected_size[1])
            QtWidgets.QApplication.processEvents()
            QtCore.QTimer.singleShot(100, lambda: setattr(self, '_programmatic_resize', False))
    
    def _ensure_window_on_screen(self):
        """Ensure the window is fully visible on screen after resize."""
        screen = QtWidgets.QApplication.primaryScreen().geometry()
        window = self.geometry()
        
        # Adjust position if window goes off screen
        new_x = window.x()
        new_y = window.y()
        
        if window.right() > screen.right():
            new_x = screen.right() - window.width()
        if window.bottom() > screen.bottom():
            new_y = screen.bottom() - window.height()
        if new_x < screen.left():
            new_x = screen.left()
        if new_y < screen.top():
            new_y = screen.top()
            
        if new_x != window.x() or new_y != window.y():
            self.move(new_x, new_y)

    def _apply_main_splitter_sizes(self, sizes: List[int]):
        self._applying_splitter_sizes = True
        try:
            normalized_sizes = [max(1, int(size)) for size in sizes[:2]]
            if len(normalized_sizes) < 2:
                normalized_sizes.extend([1] * (2 - len(normalized_sizes)))
            self.main_splitter.setSizes(normalized_sizes)
        finally:
            QtCore.QTimer.singleShot(0, lambda: setattr(self, '_applying_splitter_sizes', False))

    def _on_main_splitter_moved(self, _pos: int, _index: int):
        if self._applying_splitter_sizes or not self.btn_expand.isChecked():
            return
        if hasattr(self, '_splitter_timer'):
            self._splitter_timer.stop()
        else:
            self._splitter_timer = QtCore.QTimer()
            self._splitter_timer.setSingleShot(True)
            self._splitter_timer.timeout.connect(self._save_splitter_sizes)
        self._splitter_timer.start(250)

    def _save_splitter_sizes(self):
        sizes = [max(1, int(size)) for size in self.main_splitter.sizes()[:2]]
        if len(sizes) == 2:
            self.cfg.expanded_splitter_sizes = sizes
            ConfigManager.save(self.cfg)

    # ---------- UI callbacks ----------
    def on_toggle_expand(self, expanded: bool):
        current_size = self.size()
        debug = debug_enabled()
        
        if debug:
            debug_log("Toggle: was_expanded=%s, switching_to_expanded=%s", self._is_expanded, expanded)
            debug_log("Current size: %sx%s", current_size.width(), current_size.height())
            debug_log("Saved collapsed: %sx%s", self.cfg.collapsed_width, self.cfg.collapsed_height)
            debug_log("Saved expanded: %sx%s", self.cfg.expanded_width, self.cfg.expanded_height)
        
        # Save current size based on the state we're LEAVING (using our tracked state)
        if self._is_expanded:  # We were expanded, now collapsing - save current as expanded size
            self.cfg.expanded_width = current_size.width()
            self.cfg.expanded_height = current_size.height()
            if debug:
                debug_log("Saving current size as expanded: %sx%s", current_size.width(), current_size.height())
        else:  # We were collapsed, now expanding - save current as collapsed size
            self.cfg.collapsed_width = current_size.width()
            self.cfg.collapsed_height = current_size.height()
            if debug:
                debug_log("Saving current size as collapsed: %sx%s", current_size.width(), current_size.height())
        
        # Update our tracked state
        self._is_expanded = expanded
        
        # Update UI state
        self.expanded.setVisible(expanded)
        self.btn_expand.setText("▲" if expanded else "▼")
        
        # Save expanded state to config
        self.cfg.expanded = expanded
        
        # Update internal size references with latest config values
        self._collapsed_size = (self.cfg.collapsed_width, self.cfg.collapsed_height)
        self._expanded_size = (self.cfg.expanded_width, self.cfg.expanded_height)
        
        # Determine target size based on new state
        if expanded:
            target_size = self._expanded_size
            if debug:
                debug_log("Switching to expanded, target size: %s", target_size)
        else:
            target_size = self._collapsed_size
            if debug:
                debug_log("Switching to collapsed, target size: %s", target_size)
        
        # Use programmatic resize flag to prevent tracking this resize
        self._programmatic_resize = True
        
        # Force resize window to target size with multiple methods
        if debug:
            debug_log("About to resize to: %s", target_size)
        
        # Method 1: Direct resize
        self.resize(*target_size)
        
        # Method 2: Force immediate geometry update
        self.setGeometry(self.x(), self.y(), target_size[0], target_size[1])
        
        # Method 3: Process events to ensure resize takes effect
        QtWidgets.QApplication.processEvents()

        if expanded:
            self._apply_main_splitter_sizes(self.cfg.expanded_splitter_sizes)
        else:
            self._apply_main_splitter_sizes([max(260, target_size[1] - 24), 0])
        
        # Verify the resize worked
        actual_size = self.size()
        if debug:
            debug_log("After resize - Actual size: %sx%s", actual_size.width(), actual_size.height())
            if (actual_size.width(), actual_size.height()) != target_size:
                debug_log(
                    "WARNING: Resize failed! Expected %s, got %sx%s",
                    target_size,
                    actual_size.width(),
                    actual_size.height(),
                )
        
        if expanded and self.jira:
            # Only refresh if we don't have recent data
            if not self._current_issues or any(not self._is_cache_valid(key) for key in self._current_issues):
                self.refresh_assigned()
        
        # Reset the flag after a short delay
        QtCore.QTimer.singleShot(100, lambda: setattr(self, '_programmatic_resize', False))
        
        # Save all changes to config
        ConfigManager.save(self.cfg)
        
        # Verify resize worked after a delay
        if debug:
            QtCore.QTimer.singleShot(200, lambda: self._verify_resize(target_size))
            
        # Ensure window stays visible on screen after resize completes
        QtCore.QTimer.singleShot(150, self._ensure_window_on_screen)

    def _apply_selected_issue(self, key: str, summary: str, *, record_history: bool):
        request_token = self._next_request_token("_selected_issue_request_token")
        self.cfg.last_issue_key = key
        self._selected_issue_key = key
        self._selected_issue_id = None
        raw_issue = self.issue_browser.known_issues_by_key.get(key)
        
        if record_history:
            self._record_issue_history(key, summary)
            self._populate_search_history()
        
        # Create clickable link to the Jira ticket
        if self.cfg.jira_base_url and key:
            ticket_url = f"{self.cfg.jira_base_url}/browse/{key}"
            self.issue_label.setText(f'<a href="{ticket_url}">{key}</a> — {summary}')
        else:
            self.issue_label.setText(f"{key} — {summary}")
        
        self._resolve_selected_issue_id_async(key, request_token)
        
        # Update time display for selected issue
        self._update_selected_issue_time(key, request_token=request_token)

        # Update parent/epic label
        self._update_parent_label(key, raw_issue=raw_issue)
        
        ConfigManager.save(self.cfg)

    def on_issue_selected(self, key: str, summary: str):
        self._apply_selected_issue(key, summary, record_history=True)

    def _add_selected_issue_to_allocation_panel(self):
        issue_key = self._selected_issue_key or self.cfg.last_issue_key
        if not issue_key:
            QtWidgets.QMessageBox.information(self, messages.ALLOCATION_TITLE, messages.ALLOCATION_SELECT_GRID_FIRST)
            return
        summary = next((snapshot.summary for snapshot in self.issue_browser.all_snapshots if snapshot.issue_key == issue_key), "")
        if not summary:
            summary = (self.issue_browser.known_issues_by_key.get(issue_key, {}).get("fields", {}) or {}).get("summary", "")
        self.allocation_panel.add_issue(issue_key, summary)
        self._sync_allocation_panel_context([issue_key])

    def _restore_allocation_draft(self):
        allocation_draft = self.cfg.allocation_draft if isinstance(self.cfg.allocation_draft, dict) else {"rows": []}
        state = AllocationState.from_dict(allocation_draft, self.allocation_service.TOTAL_UNITS)
        if state.rows:
            self.allocation_panel.set_state(state)

    def _persist_allocation_draft(self, allocation_state):
        state = allocation_state if isinstance(allocation_state, AllocationState) else self.allocation_panel.current_state()
        self.cfg.allocation_draft = state.to_dict()
        ConfigManager.save(self.cfg)

    def _apply_known_allocation_panel_context(self, issue_keys: List[str]) -> tuple[list[str], list[str]]:
        missing_context_keys: list[str] = []
        missing_parent_summary_keys: set[str] = set()
        for issue_key in issue_keys:
            cached = self._get_cached_worklog(issue_key)
            context = self.issue_browser.allocation_issue_context(
                issue_key,
                raw_issue_by_key=self._raw_issues_by_key,
                cached_total_seconds=cached[1] if cached else None,
            )
            if not context["has_raw_issue"]:
                missing_context_keys.append(issue_key)
            parent_key = str(context.get("parent_key", "") or "")
            parent_summary = str(context.get("parent_summary", "") or "")
            if parent_key and not parent_summary:
                missing_parent_summary_keys.add(parent_key)
            self._apply_allocation_issue_context(
                issue_key,
                summary=str(context.get("summary", "") or ""),
                parent_key=parent_key,
                parent_summary=parent_summary,
                total_logged_seconds=max(0, int(context.get("total_logged_seconds", 0) or 0)),
            )
        return missing_context_keys, sorted(missing_parent_summary_keys)

    def _sync_allocation_panel_context(self, issue_keys: Optional[List[str]] = None):
        rows = self.allocation_panel.current_state().rows
        target_keys = issue_keys or [row.issue_key for row in rows]
        target_keys = [issue_key for issue_key in target_keys if issue_key]
        if not target_keys:
            return
        missing_context_keys, missing_parent_summary_keys = self._apply_known_allocation_panel_context(target_keys)
        if not self.jira:
            return
        if not missing_context_keys and not missing_parent_summary_keys:
            return
        request_token = self._next_request_token("_allocation_context_request_token")
        self._start_background_worker(
            "allocation-context",
            self._fetch_allocation_context_in_background,
            sorted(set(target_keys)),
            sorted(set(missing_context_keys)),
            missing_parent_summary_keys,
            request_token,
        )

    def _fetch_allocation_context_in_background(
        self,
        target_keys: List[str],
        missing_context_keys: List[str],
        missing_parent_summary_keys: List[str],
        request_token: int,
    ):
        if not self.jira:
            return
        fetched_issues: List[Dict] = []
        parent_keys_to_fetch = set(missing_parent_summary_keys)
        if missing_context_keys:
            try:
                fetched_issues = self.jira.search_by_keys(
                    missing_context_keys,
                    fields=["summary", "parent", "customfield_10014"],
                )
            except Exception as error:
                debug_log("Failed to fetch allocation issue context: %s", error)
            for issue in fetched_issues:
                fields = issue.get("fields", {}) if isinstance(issue, dict) else {}
                raw_parent_text, raw_parent_key = self.issue_catalog.extract_parent_info(fields)
                parent_key, parent_summary = self.issue_catalog.split_parent_text(raw_parent_text, raw_parent_key)
                if parent_key and not parent_summary:
                    parent_keys_to_fetch.add(parent_key)
            if fetched_issues:
                self.allocationIssueDetailsFetched.emit(fetched_issues, request_token)

        if parent_keys_to_fetch:
            parent_summaries: dict[str, str] = {}
            try:
                parent_issues = self.jira.search_by_keys(sorted(parent_keys_to_fetch), fields=["summary"]) or []
                for issue in parent_issues:
                    parent_key = str(issue.get("key") or "")
                    parent_summary = str((issue.get("fields", {}) or {}).get("summary", "") or "")
                    if parent_key and parent_summary:
                        parent_summaries[parent_key] = parent_summary
            except Exception as error:
                debug_log("Failed to fetch allocation parent summaries: %s", error)
            if parent_summaries:
                self.allocationParentSummariesFetched.emit(parent_summaries, request_token)

    @QtCore.Slot(object, int)
    def _apply_allocation_issue_details(self, issues, request_token: int):
        if not self._is_current_request("_allocation_context_request_token", request_token):
            debug_log("Discarding stale allocation issue details for token %s", request_token)
            return
        if not issues:
            return
        normalized_issues = list(issues)
        self._cache_known_issues(normalized_issues)
        issue_keys: List[str] = []
        for issue in normalized_issues:
            issue_key = issue.get("key")
            if issue_key:
                self._raw_issues_by_key[issue_key] = issue
                issue_keys.append(issue_key)
        if issue_keys:
            self._apply_known_allocation_panel_context(issue_keys)

    @QtCore.Slot(object, int)
    def _apply_allocation_parent_summaries(self, parent_summaries, request_token: int):
        if not self._is_current_request("_allocation_context_request_token", request_token):
            debug_log("Discarding stale allocation parent summaries for token %s", request_token)
            return
        if not parent_summaries:
            return
        summary_map = dict(parent_summaries)
        for row in self.allocation_panel.current_state().rows:
            issue_key = row.issue_key
            context = self.issue_browser.allocation_issue_context(
                issue_key,
                raw_issue_by_key=self._raw_issues_by_key,
            )
            parent_key = str(context.get("parent_key", "") or "")
            if not parent_key or parent_key not in summary_map:
                continue
            self._apply_allocation_issue_context(
                issue_key,
                summary=str(context.get("summary", "") or ""),
                parent_key=parent_key,
                parent_summary=summary_map[parent_key],
                total_logged_seconds=max(0, int(context.get("total_logged_seconds", 0) or 0)),
            )

    def _preload_allocation_panel_data(self):
        issue_keys = [row.issue_key for row in self.allocation_panel.current_state().rows if row.issue_key]
        if not issue_keys:
            return
        self._sync_allocation_panel_context(issue_keys)
        self._start_worklog_fetch(issue_keys, force_refresh=False)

    def _cache_known_issues(self, issues: List[Dict]):
        self.issue_browser.cache_known_issues(issues)

    def _render_filtered_issue_list(self, preferred_key: Optional[str] = None, *, update_selection_context: bool = False):
        filtered_snapshots = self.issue_browser.apply_filter(self.grid_filter.text())
        self._current_issue_snapshots = filtered_snapshots
        visible_issue_keys = self.issue_browser.visible_issue_keys()
        self._current_issues = visible_issue_keys
        self.issue_list.populate_snapshots(filtered_snapshots)
        self._fetch_epic_parent_summaries()
        self._apply_last_logged_cache(visible_issue_keys)
        self._update_ui_from_cache(visible_issue_keys)

        current_key = self._selected_issue_key or self.cfg.last_issue_key
        select_key = self.issue_browser.choose_selection(
            preferred_key,
            current_key,
            update_selection_context=update_selection_context,
        )

        if select_key:
            self._select_issue_in_list(select_key)
            summary = next((snapshot.summary for snapshot in filtered_snapshots if snapshot.issue_key == select_key), "")
            if update_selection_context or select_key != current_key:
                self._apply_selected_issue(select_key, summary, record_history=False)
            elif select_key == current_key:
                self._update_parent_label(select_key, raw_issue=self.issue_browser.known_issues_by_key.get(select_key))
        else:
            self.issue_list.clearSelection()
        self._update_issue_browser_status()

    def _on_grid_filter_changed(self, text: str):
        self._render_filtered_issue_list()

    def _select_issue_from_search_results(self, issues: List[Dict], preferred_key: Optional[str] = None):
        if not issues:
            return
        self._cache_known_issues(issues)
        issue_by_key = {issue.get("key"): issue for issue in issues if issue.get("key")}
        selected_issue = issue_by_key.get(preferred_key) if preferred_key else None
        if selected_issue is None:
            selected_issue = issues[0]
        issue_key = selected_issue.get("key", "")
        summary = (selected_issue.get("fields", {}) or {}).get("summary", "")
        if issue_key:
            self.on_issue_selected(issue_key, summary)
            if issue_key in self._current_issues:
                self._select_issue_in_list(issue_key)

    def _configured_day_seconds(self) -> int:
        return max(0, int(self.cfg.daily_time_seconds))

    def _remaining_daily_seconds(self) -> int:
        return max(0, self._configured_day_seconds() - max(0, int(self._daily_total_secs)))

    def _set_submit_actions_enabled(self, enabled: bool):
        for button in self._increment_buttons.values():
            button.setEnabled(enabled)
        if hasattr(self, "act_log5"):
            self.act_log5.setEnabled(enabled)
        if not enabled:
            self.allocation_panel.submit_button.setEnabled(False)

    def _refresh_submission_controls(self):
        configured_day_seconds = self._configured_day_seconds()
        remaining_seconds = self._remaining_daily_seconds()
        logged_seconds = max(0, int(self._daily_total_secs))

        if self.account_id and not self._daily_total_initialized:
            self._set_daily_limit_loading_state()
            return

        self.allocation_panel.set_remaining_seconds(remaining_seconds)
        self._set_submit_actions_enabled(True)

        if configured_day_seconds <= 0:
            self.daily_limit_label.setText(messages.DAILY_LIMIT_ZERO)
            self.daily_limit_label.setStyleSheet("QLabel { color: #c92a2a; font-size: 11px; font-weight: bold; }")
            return

        limit_str = self._format_secs(configured_day_seconds)
        logged_str = self._format_secs(logged_seconds)
        remaining_str = self._format_secs(remaining_seconds)
        if remaining_seconds <= 0:
            self.daily_limit_label.setText(messages.daily_limit_reached(logged_str, limit_str))
            self.daily_limit_label.setStyleSheet("QLabel { color: #c92a2a; font-size: 11px; font-weight: bold; }")
        else:
            self.daily_limit_label.setText(messages.daily_limit_remaining(remaining_str, limit_str, logged_str))
            self.daily_limit_label.setStyleSheet("QLabel { color: #666; font-size: 11px; }")

    def _set_issue_browser_status(self, text: str, *, tone: str = "neutral"):
        tone_styles = {
            "neutral": "QLabel { color: #666; font-size: 11px; }",
            "busy": "QLabel { color: #1c7ed6; font-size: 11px; font-weight: bold; }",
            "warning": "QLabel { color: #c92a2a; font-size: 11px; font-weight: bold; }",
            "success": "QLabel { color: #2b8a3e; font-size: 11px; }",
        }
        self.issue_browser_status.setText(text)
        self.issue_browser_status.setStyleSheet(tone_styles.get(tone, tone_styles["neutral"]))

    def _update_issue_browser_status(self):
        status = self.issue_browser.status()
        text = status.text
        tone = status.tone
        if self._grid_parent_summary_loading:
            text = messages.issue_browser_enriching_status(text)
            if tone not in {"warning", "busy"}:
                tone = "busy"
        self._set_issue_browser_status(text, tone=tone)

    def _register_shortcuts(self):
        self._shortcuts = [
            QtGui.QShortcut(QtGui.QKeySequence("Ctrl+R"), self, activated=self.refresh_assigned),
            QtGui.QShortcut(QtGui.QKeySequence("Ctrl+K"), self, activated=self._focus_main_search),
            QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Shift+F"), self, activated=self._focus_grid_filter),
            QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Shift+A"), self, activated=self._add_selected_issue_to_allocation_panel),
            QtGui.QShortcut(QtGui.QKeySequence("Escape"), self, activated=self._clear_grid_filter_shortcut),
        ]

    def _focus_main_search(self):
        self.search.setFocus()
        self.search.lineEdit().selectAll()

    def _focus_grid_filter(self):
        if not self.btn_expand.isChecked():
            self.btn_expand.setChecked(True)
        self.grid_filter.setFocus()
        self.grid_filter.selectAll()

    def _clear_grid_filter_shortcut(self):
        if self.grid_filter.hasFocus() and self.grid_filter.text():
            self.grid_filter.clear()

    def on_search(self):
        if not self.ensure_clients():
            return
        query = self.search.currentText().strip()
        if not query:
            return
        # Record raw search (not issue selection) in history
        self._record_search_history(query)
        
        try:
            issues = self.jira.search(query)
            if not issues:
                QtWidgets.QMessageBox.information(self, messages.SEARCH_TITLE, messages.SEARCH_NO_ISSUES)
                return
            # Prefer selecting exact key if query looks like one
            preferred_key = None
            if self._looks_like_issue_key(query):
                preferred_key = query
            elif self.cfg.last_issue_key in [i.get("key") for i in issues]:
                preferred_key = self.cfg.last_issue_key
            self._select_issue_from_search_results(issues, preferred_key)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, messages.SEARCH_FAILED_TITLE, human_err(e))

    def refresh_assigned(self):
        if not self.ensure_clients():
            return
        self.btn_refresh.setEnabled(False)
        self._set_issue_browser_status(messages.ISSUE_BROWSER_REFRESHING, tone="busy")
        if self._current_issue_snapshots:
            self._rerender_issue_list_from_state()
        self._start_background_worker("refresh-assigned", self._refresh_assigned_in_background)

    def _refresh_assigned_in_background(self):
        try:
            # Get assigned issues as before
            assigned_issues = self.jira.search_assigned()
            all_issues = assigned_issues[:]
            assigned_keys = {i.get("key") for i in assigned_issues}
            worked_issue_keys: set[str] = set()
            
            # Also get issues with recent worklogs from Tempo
            if self.worklog_service and self.account_id:
                try:
                    worked_issue_keys = set(
                        self.worklog_service.get_recent_worked_issue_keys(
                            account_id=self.account_id,
                            days_back=60,
                        )
                    )
                    
                    # Fetch details for worked issues not in assigned list
                    additional_keys = worked_issue_keys - assigned_keys
                    
                    if additional_keys:
                        additional_issues = self.jira.search_by_keys(
                            sorted(additional_keys),
                            fields=["summary", "status", "issuetype", "project", "priority", "parent", "customfield_10014"],
                            order_by_updated=True
                        )
                        
                        all_issues = self.issue_catalog.merge_issues(assigned_issues, additional_issues)
                
                except Exception as e:
                    # If Tempo lookup fails, just use assigned issues
                    debug_log("Could not fetch recent worked issues: %s", human_err(e))
            
            preferred_key = self.cfg.last_issue_key if self.cfg.last_issue_key in [i.get("key") for i in all_issues] else None
            self.issueResultsFetched.emit(all_issues, preferred_key, {
                "assigned_keys": assigned_keys,
                "worked_keys": worked_issue_keys,
            })
        except Exception as e:
            QtCore.QTimer.singleShot(0, lambda: self._handle_issue_refresh_failure(human_err(e)))

    @QtCore.Slot(object, object, object)
    def _on_issue_results_fetched(self, issues, preferred_key, metadata):
        self.btn_refresh.setEnabled(True)
        self._display_issue_results(
            issues,
            preferred_key,
            assigned_keys=metadata.get("assigned_keys", set()),
            worked_keys=metadata.get("worked_keys", set()),
        )

    def _handle_issue_refresh_failure(self, message: str):
        self.btn_refresh.setEnabled(True)
        self._set_issue_browser_status(messages.issue_browser_refresh_failed_status(message), tone="warning")
        QtWidgets.QMessageBox.critical(self, messages.LOAD_FAILED_TITLE, message)

    def _fetch_epic_parent_summaries(self):
        """Fetch summaries for epic/parent keys that need them."""
        if not self.jira:
            return
        
        keys_to_fetch = set()
        
        # Collect all epic/parent keys that need summaries
        for i in range(self.issue_list.topLevelItemCount()):
            parent = self.issue_list.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                epic_key = child.data(2, QtCore.Qt.UserRole)
                if epic_key and isinstance(epic_key, str):
                    known_parent = self.issue_browser.known_issues_by_key.get(epic_key) or self._raw_issues_by_key.get(epic_key) or {}
                    known_summary = str((known_parent.get("fields", {}) or {}).get("summary", "") or "") if isinstance(known_parent, dict) else ""
                    if known_summary:
                        self.issue_list.update_parent_summary(epic_key, known_summary)
                    else:
                        keys_to_fetch.add(epic_key)
        
        if not keys_to_fetch:
            self._set_grid_parent_summary_loading(False)
            return

        request_token = self._next_request_token("_grid_parent_summary_request_token")
        self._set_grid_parent_summary_loading(True)
        self._start_background_worker(
            "grid-parent-summaries",
            self._fetch_grid_parent_summaries_in_background,
            sorted(keys_to_fetch),
            request_token,
        )

    def _fetch_grid_parent_summaries_in_background(self, parent_keys: List[str], request_token: int):
        if not self.jira or not parent_keys:
            return
        summaries: dict[str, str] = {}
        try:
            parent_issues = self.jira.search_by_keys(parent_keys, fields=["summary"]) or []
            for issue in parent_issues:
                issue_key = str(issue.get("key") or "")
                summary = str((issue.get("fields", {}) or {}).get("summary", "") or "")
                if issue_key:
                    summaries[issue_key] = summary
            self.gridParentSummariesFetched.emit(parent_issues, request_token)
        except Exception as e:
            debug_log("Failed to fetch epic/parent summaries: %s", e)

    @QtCore.Slot(object, int)
    def _apply_grid_parent_summaries(self, parent_issues, request_token: int):
        if not self._is_current_request("_grid_parent_summary_request_token", request_token):
            debug_log("Discarding stale grid parent summaries for token %s", request_token)
            return
        self._grid_parent_summary_loading = False
        issues = list(parent_issues or [])
        if not issues:
            self._update_issue_browser_status()
            return
        self._cache_known_issues(issues)
        for issue in issues:
            issue_key = str(issue.get("key") or "")
            summary = str((issue.get("fields", {}) or {}).get("summary", "") or "")
            if not issue_key:
                continue
            self.issue_list.update_parent_summary(issue_key, summary)
        self._update_issue_browser_status()

    def log_increment(self, minutes: int, to_last: bool=False):
        if not self.ensure_clients():
            return
        requested_seconds = int(minutes * 60)
        remaining_seconds = self._remaining_daily_seconds()
        if requested_seconds > remaining_seconds:
            QtWidgets.QMessageBox.information(
                self,
                messages.DAILY_LIMIT_TITLE,
                messages.daily_limit_increment_disabled(self._format_secs(remaining_seconds), minutes),
            )
            self._refresh_submission_controls()
            return
        if to_last:
            key = self.cfg.last_issue_key
        else:
            # Extract key from potentially HTML-formatted text
            label_text = self.issue_label.text()
            if label_text != "—":
                # Handle both plain text and HTML link formats
                if '>' in label_text and '<' in label_text:
                    # HTML format: extract key from <a href="...">KEY</a> — summary
                    import re
                    match = re.search(r'>([^<]+)</a>', label_text)
                    key = match.group(1) if match else ""
                else:
                    # Plain text format: KEY — summary
                    key = label_text.split(" — ")[0].strip()
            else:
                key = ""
        if not key:
            QtWidgets.QMessageBox.information(self, messages.SELECT_ISSUE_TITLE, messages.SELECT_ISSUE_MESSAGE)
            return
        
        # Get issue ID for Tempo API - this is required!
        issue_id = None
        if to_last and self.jira:
            issue_id = self.jira.get_issue_id(key)
        elif not to_last:
            issue_id = self._selected_issue_id

        if not issue_id and self.worklog_service:
            issue_id = self.worklog_service.resolve_issue_ids([key]).get(key)
            if key == self._selected_issue_key:
                self._selected_issue_id = issue_id
            
        if not issue_id:
            QtWidgets.QMessageBox.critical(self, messages.MISSING_ISSUE_ID_TITLE, 
                f"Could not get issue ID for {key}. Please refresh the issue list and try again.")
            return
            
        seconds = requested_seconds
        desc = self.desc.text().strip()
        try:
            wl = self.tempo.create_worklog(
                issue_key=key,
                issue_id=issue_id,
                account_id=self.account_id or "",
                seconds=seconds,
                when=dt.datetime.now(),
                description=desc
            )
            self.tray.showMessage(APP_NAME, messages.tray_logged(minutes, key), QtWidgets.QSystemTrayIcon.Information, 4000)
            
            self._optimistically_update_issue_after_log(key, seconds)
            self._start_worklog_fetch([key], force_refresh=True)
            
            # If this is the selected issue, update its time display
            if key == self._selected_issue_key:
                self._update_selected_issue_time(key)
            
            # Update daily total in window title
            self._daily_total_secs += seconds
            self._daily_total_cache_time = dt.datetime.now().timestamp()
            self._update_window_title()
            self._refresh_submission_controls()
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, messages.LOG_FAILED_TITLE, human_err(e))

    def _optimistically_update_issue_after_log(self, issue_key: str, seconds: int):
        today_str = dt.date.today().strftime("%Y-%m-%d")
        cached = self._get_cached_worklog(issue_key)
        if cached:
            today_secs, total_secs = cached
            self._cache_worklog(issue_key, today_secs + seconds, total_secs + seconds)
            self.worklogFetched.emit(issue_key, self._format_secs(today_secs + seconds), self._format_secs(total_secs + seconds))
        else:
            self._worklog_cache.invalidate(f"worklog:{issue_key}", reason="new_worklog")
        self._cache_last_logged(issue_key, today_str)
        self.issue_list.update_last_logged(issue_key, self._format_relative_time(today_str))
        refreshed_cached = self._get_cached_worklog(issue_key)
        if refreshed_cached:
            _, total_secs = refreshed_cached
            self.allocation_panel.set_issue_context(issue_key, total_logged_seconds=total_secs)
        self.issueListRerenderRequested.emit()

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            ConfigManager.save(self.cfg)
            self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, self.cfg.always_on_top)
            self.show()  # refresh flags
            self.allocation_panel.set_daily_time_seconds(self.cfg.daily_time_seconds)
            self.allocation_panel.set_jira_base_url(self.cfg.jira_base_url)
            self._sync_allocation_panel_context()
            self._refresh_submission_controls()
            self._reset_reminder()

    def _submit_allocation(self, allocation_state):
        if not self.ensure_clients():
            return
        state = allocation_state
        if not self.allocation_service.validate(state):
            QtWidgets.QMessageBox.warning(self, messages.ALLOCATION_TITLE, messages.ALLOCATION_SUM_MUST_BE_100)
            return
        if not state.rows:
            QtWidgets.QMessageBox.information(self, messages.ALLOCATION_TITLE, messages.ALLOCATION_ADD_ONE_ISSUE)
            return
        remaining_seconds = self._remaining_daily_seconds()
        allocations = self.allocation_service.allocations_to_total_seconds(state, remaining_seconds)
        submittable_rows = [row for row in state.rows if allocations.get(row.issue_key, 0) > 0]
        if not submittable_rows:
            QtWidgets.QMessageBox.information(
                self,
                messages.ALLOCATION_TITLE,
                messages.ALLOCATION_NO_NONZERO,
            )
            self._persist_allocation_draft(self.allocation_panel.current_state())
            return
        planned_seconds = sum(allocations.get(row.issue_key, 0) for row in submittable_rows)
        if planned_seconds > remaining_seconds:
            QtWidgets.QMessageBox.warning(
                self,
                messages.ALLOCATION_TITLE,
                messages.allocation_exceeds_remaining(self._format_secs(remaining_seconds)),
            )
            self._refresh_submission_controls()
            return
        resolved_issue_ids = self.worklog_service.resolve_issue_ids([row.issue_key for row in submittable_rows])
        successes = []
        failures = []
        for row in submittable_rows:
            issue_id = resolved_issue_ids.get(row.issue_key)
            if not issue_id:
                failures.append(f"{row.issue_key}: missing issue id")
                continue
            seconds = allocations.get(row.issue_key, 0)
            try:
                self.tempo.create_worklog(
                    issue_key=row.issue_key,
                    issue_id=issue_id,
                    account_id=self.account_id or "",
                    seconds=seconds,
                    when=dt.datetime.now(),
                    description=row.description,
                )
                successes.append((row.issue_key, seconds))
                self._optimistically_update_issue_after_log(row.issue_key, seconds)
            except Exception as error:
                failures.append(f"{row.issue_key}: {human_err(error)}")
        if successes:
            self._start_worklog_fetch([issue_key for issue_key, _ in successes], force_refresh=True)
            self._daily_total_secs += sum(seconds for _, seconds in successes)
            self._daily_total_cache_time = dt.datetime.now().timestamp()
            self._update_window_title()
            self._refresh_submission_controls()
        if failures:
            success_lines = "\n".join(f"- {issue_key}: {seconds // 60}m" for issue_key, seconds in successes)
            failure_lines = "\n".join(f"- {failure}" for failure in failures)
            success_section = f"Succeeded:\n{success_lines}\n\n" if success_lines else ""
            QtWidgets.QMessageBox.warning(
                self,
                messages.ALLOCATION_PARTIAL_FAILURE_TITLE,
                success_section + "Failed:\n" + failure_lines,
            )
        else:
            QtWidgets.QMessageBox.information(
                self,
                messages.ALLOCATION_SUBMITTED_TITLE,
                messages.ALLOCATION_SUBMITTED_PREFIX + "\n".join(f"- {issue_key}: {seconds // 60}m" for issue_key, seconds in successes),
            )
        self._persist_allocation_draft(self.allocation_panel.current_state())

    def _remind(self):
        # Only show reminder if timer is running
        if not self._timer_running:
            return
        # Play audible cue
        self._play_reminder_sound()
        
        # Reset reminder for next cycle
        self._reset_reminder()
        reminder_body = messages.REMINDER_BODY
        next_time_text = self._format_local_reminder_time(self._next_reminder_time)
        if next_time_text:
            reminder_body = messages.reminder_body_with_next(next_time_text)
        self.tray.showMessage(messages.REMINDER_TITLE, reminder_body, QtWidgets.QSystemTrayIcon.Warning, 8000)

    def _play_reminder_sound(self):
        """Play a short notification sound for the reminder.

        Priority:
          1. On Windows use winsound.MessageBeep (non-blocking system sound).
          2. Else fallback to QApplication.beep (cross‑platform basic beep).
        Silently ignore any failures so the reminder still shows.
        """
        try:
            if sys.platform == "win32":
                try:
                    import winsound
                    # MB_ICONEXCLAMATION is typically attention grabbing without being harsh
                    winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                    return
                except Exception:
                    pass
            # Fallback (may be no‑op on some desktops)
            try:
                QtWidgets.QApplication.beep()
            except Exception:
                pass
        except Exception:
            pass
    
    def _update_ui_from_cache(self, issue_keys: List[str]):
        """Update UI with cached worklog data where available."""
        for key in issue_keys:
            cached = self._get_cached_worklog(key)
            if cached:
                today_secs, total_secs = cached
                today_str = self._format_secs(today_secs)
                total_str = self._format_secs(total_secs)
                self.worklogFetched.emit(key, today_str, total_str)
                
                # Also update selected issue time if this is the selected one
                if key == self._selected_issue_key:
                    self._display_selected_issue_time(today_secs, total_secs)
    
    def _update_selected_issue_time(self, issue_key: str, *, request_token: Optional[int] = None):
        """Update the time display for the currently selected issue."""
        debug = debug_enabled()
        active_token = self._selected_issue_request_token if request_token is None else request_token
        
        if debug:
            debug_log("_update_selected_issue_time called for %s", issue_key)
            debug_log("tempo: %s, account_id: %s", bool(self.tempo), bool(self.account_id))
        
        if not (self.worklog_service and self.account_id):
            self.time_label.setText("")
            if debug:
                debug_log("Missing tempo client or account_id - clearing time label")
            return
        
        # Check cache first
        cached = self._get_cached_worklog(issue_key)
        if cached:
            today_secs, total_secs = cached
            if debug:
                debug_log("Using cached time data: today=%ss, total=%ss", today_secs, total_secs)
            self.worklogFetched.emit(issue_key, self._format_secs(today_secs), self._format_secs(total_secs))
        else:
            # Show loading state and fetch in background
            if debug:
                debug_log("No cached data - starting background fetch")
            self._set_selected_issue_time_loading()
            self._start_background_worker("selected-issue-time", self._fetch_selected_issue_time, issue_key, active_token)
    
    def _display_selected_issue_time(self, today_secs: int, total_secs: int):
        """Display the time information for the selected issue."""
        today_str = self._format_secs(today_secs)
        total_str = self._format_secs(total_secs)
        
        if today_secs > 0 or total_secs > 0:
            self.time_label.setText(messages.selected_issue_time(today_str, total_str))
        else:
            self.time_label.setText(messages.TIME_NONE_LOGGED)
    
    def _fetch_selected_issue_time(self, issue_key: str, request_token: int):
        """Fetch time data for selected issue in background thread."""
        debug = debug_enabled()
        try:
            if debug:
                debug_log("_fetch_selected_issue_time starting for %s", issue_key)
            today_secs, total_secs = self.worklog_service.get_user_issue_time(
                issue_key=issue_key,
                account_id=self.account_id,
            )
            
            if debug:
                debug_log("Fetched time data for %s: today=%ss, total=%ss", issue_key, today_secs, total_secs)
            
            # Cache the result
            self._cache_worklog(issue_key, today_secs, total_secs)
            
            if self._is_current_request("_selected_issue_request_token", request_token) and issue_key == self._selected_issue_key:
                today_str = self._format_secs(today_secs)
                total_str = self._format_secs(total_secs)
                QtCore.QTimer.singleShot(0, lambda: self.worklogFetched.emit(issue_key, today_str, total_str))
            else:
                debug_log("Discarding stale selected issue time for %s token %s", issue_key, request_token)
            
        except Exception as e:
            if debug:
                debug_log("Failed to fetch time for selected issue %s: %s", issue_key, e)
            QtCore.QTimer.singleShot(0, lambda: self._apply_selected_issue_time_failure(issue_key, request_token))

    def _apply_selected_issue_time_failure(self, issue_key: str, request_token: int):
        if not self._is_current_request("_selected_issue_request_token", request_token) or issue_key != self._selected_issue_key:
            debug_log("Discarding stale selected issue time failure for %s token %s", issue_key, request_token)
            return
        self._set_selected_issue_time_failed()

    def _resolve_selected_issue_id_async(self, issue_key: str, request_token: int):
        if not self.worklog_service:
            return
        self._start_background_worker("selected-issue-id", self._fetch_selected_issue_id, issue_key, request_token)

    def _fetch_selected_issue_id(self, issue_key: str, request_token: int):
        issue_id = None
        try:
            if self.worklog_service:
                issue_id = self.worklog_service.resolve_issue_ids([issue_key]).get(issue_key)
        except Exception as error:
            debug_log("Failed to resolve selected issue id for %s: %s", issue_key, error)
        QtCore.QTimer.singleShot(0, lambda: self._apply_selected_issue_id(issue_key, issue_id, request_token))

    def _apply_selected_issue_id(self, issue_key: str, issue_id: Optional[str], request_token: int):
        if not self._is_current_request("_selected_issue_request_token", request_token) or issue_key != self._selected_issue_key:
            debug_log("Discarding stale selected issue id for %s token %s", issue_key, request_token)
            return
        self._selected_issue_id = issue_id

    # ---------- Worklog enrichment ----------
    def _start_worklog_fetch(self, issue_keys: List[str], force_refresh: bool = False):
        """Start fetching worklog data for issues, using cache when possible."""
        debug = debug_enabled()
        
        if debug:
            debug_log("_start_worklog_fetch called with %s, force_refresh=%s", issue_keys, force_refresh)
            debug_log("jira: %s, account_id: %s", bool(self.jira), bool(self.account_id))
        
        if not (self.jira and self.account_id):
            if debug:
                debug_log("Missing jira client or account_id - returning early")
            return
        
        # Filter out issues that have valid cached data (unless forcing refresh)
        original_count = len(issue_keys)
        if not force_refresh:
            issue_keys = [key for key in issue_keys if not self._is_cache_valid(key)]
        
        if debug:
            debug_log("After cache filtering: %s -> %s issues to fetch", original_count, len(issue_keys))
        
        if issue_keys:
            if debug:
                debug_log("Starting background thread for worklog fetch: %s", issue_keys)
            # Run in background thread to avoid blocking UI
            self._start_background_worker("worklog-fetch", self._fetch_and_update_worklogs, issue_keys, True)
        elif debug:
            debug_log("No issues to fetch (all cached or empty list)")

    def _fetch_and_update_worklogs(self, issue_keys: List[str], update_cache: bool = True):
        """Fetch worklog data for issues and optionally update cache."""
        debug = debug_enabled()
        # Ensure we have issue IDs for all keys up-front to avoid per-issue latency/race
        self._ensure_issue_ids(issue_keys)
        for key in issue_keys:
            # Check cache first (unless we're doing a forced refresh)
            if update_cache:
                cached = self._get_cached_worklog(key)
                if cached:
                    today_secs, total_secs = cached
                    today_str = self._format_secs(today_secs)
                    total_str = self._format_secs(total_secs)
                    self.worklogFetched.emit(key, today_str, total_str)
                    continue
            
            today_secs = total_secs = 0
            if self.worklog_service and self.account_id:
                try:
                    today_secs, total_secs = self.worklog_service.get_user_issue_time(
                        issue_key=key,
                        account_id=self.account_id,
                    )
                except Exception as e:
                    if debug:
                        debug_log("Worklog service fetch failed for %s: %s", key, e)
            
            # Cache the results if requested
            if update_cache:
                self._cache_worklog(key, today_secs, total_secs)
            
            today_str = self._format_secs(today_secs)
            total_str = self._format_secs(total_secs)
            
            # Also fetch last logged date
            last_logged = ""
            if self.worklog_service and self.account_id:
                try:
                    last_logged_date = self.worklog_service.get_last_logged_date(
                        issue_key=key,
                        account_id=self.account_id,
                    )
                    if last_logged_date:
                        last_logged = last_logged_date
                        if debug:
                            debug_log("Found last logged date for %s: %s", key, last_logged_date)
                    elif debug:
                        debug_log("No last logged date found for %s", key)
                        
                except Exception as e:
                    if debug:
                        debug_log("Last logged date fetch failed for %s: %s", key, e)
            
            # Update the issue list with last logged date in relative format
            if last_logged:
                self._cache_last_logged(key, last_logged)
                relative_time = self._format_relative_time(last_logged)
                self.issue_list.update_last_logged(key, relative_time)
            
            if debug:
                debug_log("Final time %s: today=%ss total=%ss", key, today_secs, total_secs)
            self.worklogFetched.emit(key, today_str, total_str)
        if issue_keys:
            self.issueListRerenderRequested.emit()

    def _on_worklog_fetched(self, issue_key: str, today_str: str, total_str: str):
        """Handle worklog data being fetched for any issue."""
        cached = self._get_cached_worklog(issue_key)
        if cached:
            _, total_secs = cached
            existing_context = self.issue_browser.allocation_issue_context(
                issue_key,
                raw_issue_by_key=self._raw_issues_by_key,
                cached_total_seconds=total_secs,
            )
            self._apply_allocation_issue_context(
                issue_key,
                summary=str(existing_context.get("summary", "") or ""),
                parent_key=str(existing_context.get("parent_key", "") or ""),
                parent_summary=str(existing_context.get("parent_summary", "") or ""),
                total_logged_seconds=total_secs,
            )
        if issue_key == self._selected_issue_key:
            # Convert back to seconds for display
            try:
                if cached:
                    today_secs, total_secs = cached
                    self._display_selected_issue_time(today_secs, total_secs)
            except Exception:
                pass
    
    def _restore_last_issue(self):
        """Restore the last selected issue from config via a background search."""
        last_issue_key = self.cfg.last_issue_key.strip() if self.cfg.last_issue_key else ""
        if not last_issue_key:
            return
        
        debug = debug_enabled()
        if debug:
            debug_log("Restoring last issue by simulating search: %s", last_issue_key)
        
        # If we don't have clients set up yet, we can't search for issues
        if not (self.jira and self.tempo and self.account_id):
            if debug:
                debug_log("Clients not ready, cannot restore last issue")
            return
        
        request_token = self._next_request_token("_restore_issue_request_token")

        try:
            if debug:
                debug_log("Setting search text to: %s", last_issue_key)
            self.search.setCurrentText(last_issue_key)
            self._start_background_worker("restore-last-issue", self._restore_last_issue_in_background, last_issue_key, request_token)
            
        except Exception as e:
            if debug:
                debug_log("Failed to restore last issue via search %s: %s", last_issue_key, e)

    def _restore_last_issue_in_background(self, issue_key: str, request_token: int):
        debug = debug_enabled()
        try:
            issues = self.jira.search(issue_key) if self.jira else []
            QtCore.QTimer.singleShot(0, lambda: self._apply_restored_issue_search(issue_key, issues, request_token))
        except Exception as error:
            if debug:
                debug_log("Failed to restore last issue %s in background: %s", issue_key, error)

    def _apply_restored_issue_search(self, issue_key: str, issues: List[Dict], request_token: int):
        if not self._is_current_request("_restore_issue_request_token", request_token):
            debug_log("Discarding stale restore-last-issue results for token %s", request_token)
            return
        if self._selected_issue_key and self._selected_issue_key != issue_key:
            return
        if not issues:
            return
        preferred_key = issue_key if issue_key in [issue.get("key") for issue in issues] else None
        self._select_issue_from_search_results(issues, preferred_key)
    
    def _select_issue_in_list(self, issue_key: str):
        """Select a specific issue in the issue list by key."""
        # Traverse the tree widget to find and select the issue
        for i in range(self.issue_list.topLevelItemCount()):
            parent = self.issue_list.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.text(0) == issue_key:
                    # Select this item
                    self.issue_list.setCurrentItem(child)
                    self.issue_list.scrollToItem(child)
                    return True
        return False
    


    def closeEvent(self, event):
        """Persist window state and fully shut down the tray-backed app."""
        self._save_window_state()
        if hasattr(self, 'tray'):
            self.tray.hide()
        event.accept()
        QtCore.QTimer.singleShot(0, QtWidgets.QApplication.instance().quit)
    
    def _on_column_resized(self):
        """Handle column resize event from issue list."""
        # Save column widths to config with debouncing
        if hasattr(self, '_column_resize_timer'):
            self._column_resize_timer.stop()
        else:
            self._column_resize_timer = QtCore.QTimer()
            self._column_resize_timer.setSingleShot(True)
            self._column_resize_timer.timeout.connect(self._save_column_widths)
        
        self._column_resize_timer.start(500)  # Save after 500ms of no resizing
    
    def _save_column_widths(self):
        """Save current column widths to configuration."""
        self.cfg.issue_list_column_widths = self.issue_list.get_column_widths()
        ConfigManager.save(self.cfg)
        
        debug = debug_enabled()
        if debug:
            debug_log("Saved column widths: %s", self.cfg.issue_list_column_widths)
    
    def _save_window_state(self):
        """Save current window position and size to config."""
        # Save position
        pos = self.pos()
        self.cfg.window_x = pos.x()
        self.cfg.window_y = pos.y()
        
        # Save size based on current state
        size = self.size()
        if self.btn_expand.isChecked():  # Expanded
            self.cfg.expanded_width = size.width()
            self.cfg.expanded_height = size.height()
        else:  # Collapsed
            self.cfg.collapsed_width = size.width()
            self.cfg.collapsed_height = size.height()
        
        # Update our internal size references
        self._collapsed_size = (self.cfg.collapsed_width, self.cfg.collapsed_height)
        self._expanded_size = (self.cfg.expanded_width, self.cfg.expanded_height)
        
        # Also save column widths
        self.cfg.issue_list_column_widths = self.issue_list.get_column_widths()
        if self.btn_expand.isChecked():
            self.cfg.expanded_splitter_sizes = [max(1, int(size)) for size in self.main_splitter.sizes()[:2]]
        
        ConfigManager.save(self.cfg)
    
    def _update_window_title(self):
        """Update window title to include daily total time."""
        if hasattr(self, 'tempo') and self.tempo and self.account_id:
            daily_str = self._format_secs(self._daily_total_secs)
            remaining_str = self._format_secs(self._remaining_daily_seconds())
            base_title = messages.window_title(APP_NAME, daily_str, remaining_str)
            debug_log("Updating window title to: %s", base_title)
        else:
            base_title = APP_NAME
            debug_log("Using default window title (no clients): %s", base_title)
        self.setWindowTitle(base_title)

    def _on_daily_total_updated(self):
        self._set_daily_total_initialized(True)
        self._update_window_title()
        self._refresh_submission_controls()
    
    def _refresh_daily_total(self):
        """Refresh daily total time in background thread."""
        self._request_daily_total_refresh()

    def _request_daily_total_refresh(self, *, allow_during_startup: bool = False, ignore_cache: bool = False):
        """Queue a daily-total refresh if startup/cache/lock conditions allow it."""
        debug = debug_enabled()
        
        if debug:
            debug_log("_request_daily_total_refresh called")
            debug_log("tempo: %s, account_id: %s", bool(self.tempo), bool(self.account_id))
        
        if not (self.worklog_service and self.account_id):
            if debug:
                debug_log("Missing tempo client or account_id - cannot refresh daily total")
            return
        
        if not allow_during_startup and not self._startup_complete:
            if debug:
                debug_log("Startup not complete - skipping periodic refresh")
            return
        
        # Check if cache is still valid
        now = dt.datetime.now().timestamp()
        cache_age = now - self._daily_total_cache_time
        
        if debug:
            debug_log("Cache age: %ss, duration limit: %ss", cache_age, self._daily_total_cache_duration)
        
        if not ignore_cache and cache_age < self._daily_total_cache_duration:
            if debug:
                debug_log("Cache still valid - not refreshing daily total")
            return
        
        # Use lock to prevent concurrent fetches
        if not self._daily_total_lock.acquire(blocking=False):
            if debug:
                debug_log("Daily total fetch already in progress - skipping")
            return
        
        # Fetch in background thread
        if debug:
            debug_log("Starting background fetch for daily total")
        self._start_background_worker("daily-total", self._fetch_daily_total)
    
    def _fetch_daily_total(self):
        """Fetch daily total time and update window title."""
        debug = debug_enabled()
        try:
            if debug:
                debug_log("Fetching daily total for account: %s", self.account_id)
            daily_total = self.worklog_service.get_daily_total(account_id=self.account_id)
            self._daily_total_secs = daily_total
            self._daily_total_cache_time = dt.datetime.now().timestamp()
            
            if debug:
                debug_log("Fetched daily total: %s seconds", daily_total)
            
            self.dailyTotalUpdated.emit()
        except Exception as e:
            if debug:
                debug_log("Failed to fetch daily total: %s", e)
            # Set to 0 and update title anyway to show "Today: 0m"
            self._daily_total_secs = 0
            self.dailyTotalUpdated.emit()
        finally:
            # Always release the lock
            try:
                self._daily_total_lock.release()
            except Exception:
                pass  # Lock might not be held in some cases



    def on_search_from_dropdown(self):
        """Handle selection from search history dropdown using stored raw value via UserRole."""
        idx = self.search.currentIndex()
        raw_value = None
        if idx >= 0:
            raw_value = self.search.itemData(idx, QtCore.Qt.UserRole)
            entry_type = self.search.itemData(idx, QtCore.Qt.UserRole + 1)
        # Fallback to displayed text if no raw data (e.g., first run placeholder)
        if not raw_value:
            raw_value = self.search.currentText().strip()
        # If entry is an issue selection, set last_issue_key early so it'll be preferred
        if entry_type == 'issue' and self._looks_like_issue_key(raw_value):
            self.cfg.last_issue_key = raw_value
            self._selected_issue_key = raw_value
        # Set the line edit to the raw value (clean issue key or search term)
        self.search.setCurrentText(raw_value)
        self.on_search()

    def _on_clear_history(self):
        """Clear both search and issue selection history after confirmation."""
        if not self.cfg.search_history:
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            messages.CLEAR_HISTORY_TITLE,
            messages.CLEAR_HISTORY_CONFIRMATION,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        self.cfg.search_history = []
        ConfigManager.save(self.cfg)
        self._populate_search_history()
    
    def _populate_search_history(self):
        """Populate combo with dual-type history entries (search vs issue)."""
        current_text = self.search.currentText()
        self.search.clear()
        # Normalize and sort
        entries = []
        for entry in self.cfg.search_history:
            if isinstance(entry, dict):
                term = entry.get('term', '').strip()
                ts = entry.get('ts', 0)
                etype = entry.get('type', 'search')
                summary = entry.get('summary', '')
                if term:
                    entries.append((ts, etype, term, summary))
        entries.sort(key=lambda x: x[0], reverse=True)
        # Deduplicate by (type, term)
        seen_keys = set()
        limited = []
        for ts, etype, term, summary in entries:
            key = (etype, term)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            limited.append((etype, term, summary))
            if len(limited) >= 25:
                break
        if not limited:
            self.search.addItem("Start typing to search issues...", userData=None)
        else:
            for etype, term, summary in limited:
                if etype == 'issue':
                    display = self._format_issue_history_display(term, summary)
                else:  # search
                    display = term
                self.search.addItem(display, userData=term)
                # Store entry type in adjacent role (UserRole+1)
                idx = self.search.count() - 1
                self.search.setItemData(idx, etype, QtCore.Qt.UserRole + 1)
                if summary:
                    self.search.setItemData(idx, summary, QtCore.Qt.ToolTipRole)
        # Restore text if user was typing
        if current_text and current_text not in [self.search.itemData(i, QtCore.Qt.UserRole) for i in range(self.search.count())]:
            self.search.setCurrentText(current_text)
        elif not current_text:
            self.search.setCurrentText("")

    def _format_issue_history_display(self, key: str, summary: str) -> str:
        summary = (summary or '').strip()
        if not summary:
            return key
        short = summary[:70] + ('...' if len(summary) > 70 else '')
        return f"{key}: {short}"

    @staticmethod
    def _looks_like_issue_key(text: str) -> bool:
        if not text or '-' not in text:
            return False
        # Very lightweight heuristic: PREFIX-NUMBER where prefix is alnum+ and number digits
        parts = text.split('-', 1)
        return parts[0].isalnum() and parts[1].isdigit()
    
    # Removed obsolete _delayed_dropdown_refresh (formatting now stable via item data)
    
    def _record_search_history(self, query: str):
        query = (query or '').strip()
        if not query:
            return
        now_ts = time.time()
        # Remove any existing entry with same type+term
        new_hist = []
        for entry in self.cfg.search_history:
            if isinstance(entry, dict) and entry.get('type') == 'search' and entry.get('term') == query:
                continue
            new_hist.append(entry)
        new_hist.insert(0, {"type": "search", "term": query, "ts": now_ts})
        self.cfg.search_history = new_hist[:50]
        ConfigManager.save(self.cfg)
        debug_log("Recorded search history: %s", query)

    def _record_issue_history(self, key: str, summary: str):
        key = (key or '').strip()
        if not key:
            return
        now_ts = time.time()
        new_hist = []
        for entry in self.cfg.search_history:
            if isinstance(entry, dict) and entry.get('type') == 'issue' and entry.get('term') == key:
                continue
            new_hist.append(entry)
        new_hist.insert(0, {"type": "issue", "term": key, "summary": summary or '', "ts": now_ts})
        self.cfg.search_history = new_hist[:50]
        ConfigManager.save(self.cfg)
        debug_log("Recorded issue selection history: %s", key)

    # ---------- Issue ID management ----------
    def _ensure_issue_ids(self, issue_keys: List[str]):
        """Ensure Jira numeric issue IDs are cached for all provided keys.

        Bulk fetches missing IDs using a single JQL query to avoid per-issue HTTP round trips.
        Safe to call multiple times; silently ignores failures.
        """
        if not (self.jira and issue_keys):
            return
        debug = debug_enabled()
        try:
            resolved = self.jira.ensure_issue_ids(issue_keys)
            if debug and resolved:
                debug_log("Ensured issue IDs for: %s", sorted(resolved))
        except Exception as e:
            if debug:
                debug_log("Failed to bulk ensure issue IDs: %s", e)

    # ---------- Unified issue result display ----------
    def _build_issue_snapshots(self, issues: List[Dict]) -> List[IssueSnapshot]:
        totals_by_key = {}
        for issue_key in [issue.get("key") for issue in issues if issue.get("key")]:
            cached = self._get_cached_worklog(issue_key)
            if cached:
                totals_by_key[issue_key] = cached
        last_logged_by_key = {
            issue_key: cached_last_logged
            for issue_key in self._raw_issues_by_key
            for cached_last_logged in [self._get_cached_last_logged(issue_key)]
            if cached_last_logged
        }
        return self.issue_catalog.build_snapshots(
            issues,
            assigned_keys=self._assigned_issue_keys,
            worked_keys=self._worked_issue_keys,
            totals_by_key=totals_by_key,
            last_logged_by_key=last_logged_by_key,
        )

    def _display_issue_results(
        self,
        issues: List[Dict],
        preferred_key: Optional[str] = None,
        *,
        assigned_keys: Optional[set[str]] = None,
        worked_keys: Optional[set[str]] = None,
    ):
        """Central handler to display a list of issues and trigger enrichment.

        Args:
            issues: Raw Jira issue objects
            preferred_key: Issue key to auto-select if present
        """
        if not issues:
            self._raw_issues_by_key = {}
            self._assigned_issue_keys = set(assigned_keys or set())
            self._worked_issue_keys = set(worked_keys or set())
            self.issue_browser.set_snapshots([])
            self._current_issue_snapshots = []
            self._current_issues = []
            self.issue_list.clear()
            self._update_issue_browser_status()
            return
        self._cache_known_issues(issues)
        self._raw_issues_by_key = {issue.get("key"): issue for issue in issues if issue.get("key")}
        self._assigned_issue_keys = set(assigned_keys or set())
        self._worked_issue_keys = set(worked_keys or set())
        snapshots = self._build_issue_snapshots(issues)
        self.issue_browser.set_snapshots(snapshots)
        issue_keys = [snapshot.issue_key for snapshot in snapshots]
        self._start_worklog_fetch(issue_keys, force_refresh=True)
        # Refresh daily total if safe
        if self._startup_complete:
            self._refresh_daily_total()
        self._render_filtered_issue_list(preferred_key, update_selection_context=True)
        self._sync_allocation_panel_context()

    @QtCore.Slot()
    def _rerender_issue_list_from_state(self):
        if not self._raw_issues_by_key:
            return
        snapshots = self._build_issue_snapshots(list(self._raw_issues_by_key.values()))
        self.issue_browser.set_snapshots(snapshots)
        self._render_filtered_issue_list(update_selection_context=True)
        self._sync_allocation_panel_context()

    def _update_parent_label(self, issue_key: str, raw_issue: Optional[Dict] = None):
        """Update the parent/epic label for currently selected issue."""
        if not issue_key:
            self.parent_label.setText("")
            return
        # Find the item in the issue list
        display_text = ""
        epic_key = None
        epic_summary = ""
        for i in range(self.issue_list.topLevelItemCount()):
            parent = self.issue_list.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.text(0) == issue_key:
                    display_text = child.text(2)  # Epic/Parent column
                    # May have key stored in user role
                    data_key = child.data(2, QtCore.Qt.UserRole)
                    if data_key:
                        epic_key = data_key
                    break
        if not display_text and raw_issue:
            fields = raw_issue.get("fields", {}) if isinstance(raw_issue, dict) else {}
            display_text, lookup_key = self.issue_catalog.extract_parent_info(fields)
            if lookup_key:
                epic_key = lookup_key
        if display_text:
            if ":" in display_text:
                parts = display_text.split(":", 1)
                epic_key = epic_key or parts[0].strip()
                epic_summary = parts[1].strip()
            else:
                epic_key = epic_key or display_text.strip()
        self._render_parent_label(epic_key, epic_summary)
        if epic_key and not epic_summary and self.jira:
            self._fetch_selected_issue_parent_summary_async(issue_key, epic_key, self._selected_issue_request_token)

    def _render_parent_label(self, parent_key: Optional[str], parent_summary: str = ""):
        if not parent_key:
            self.parent_label.setText("")
            return
        if self.cfg.jira_base_url:
            epic_url = f"{self.cfg.jira_base_url}/browse/{parent_key}"
            if parent_summary:
                short = parent_summary[:80] + ("..." if len(parent_summary) > 80 else "")
                self.parent_label.setText(messages.parent_label_html(parent_key, epic_url, short))
            else:
                self.parent_label.setText(messages.parent_label_html(parent_key, epic_url))
        else:
            if parent_summary:
                self.parent_label.setText(messages.parent_label_plain(parent_key, parent_summary))
            else:
                self.parent_label.setText(messages.parent_label_plain(parent_key))

    def _fetch_selected_issue_parent_summary_async(self, issue_key: str, parent_key: str, request_token: int):
        if not self.jira:
            return
        self._start_background_worker("selected-issue-parent", self._fetch_selected_issue_parent_summary, issue_key, parent_key, request_token)

    def _fetch_selected_issue_parent_summary(self, issue_key: str, parent_key: str, request_token: int):
        parent_summary = ""
        try:
            if self.jira:
                res = self.jira.search_by_keys([parent_key], fields=["summary"]) or []
                if res:
                    parent_summary = (res[0].get("fields", {}) or {}).get("summary", "") or ""
        except Exception as error:
            debug_log("Failed to fetch selected issue parent summary for %s: %s", parent_key, error)
        if parent_summary:
            self.selectedIssueParentFetched.emit(issue_key, parent_summary, request_token)

    @QtCore.Slot(str, str, int)
    def _apply_selected_issue_parent_summary(self, issue_key: str, parent_summary: str, request_token: int):
        if not self._is_current_request("_selected_issue_request_token", request_token) or issue_key != self._selected_issue_key:
            debug_log("Discarding stale selected issue parent summary for %s token %s", issue_key, request_token)
            return
        current_text = self.parent_label.text()
        parent_key = ""
        if current_text:
            import re
            match = re.search(r'>([^<]+)</a>', current_text)
            if match:
                parent_key = match.group(1)
            elif ":" in current_text:
                parent_key = current_text.split(":", 1)[1].split("—", 1)[0].strip()
        if not parent_key:
            raw_issue = self.issue_browser.known_issues_by_key.get(issue_key) or self._raw_issues_by_key.get(issue_key) or {}
            fields = raw_issue.get("fields", {}) if isinstance(raw_issue, dict) else {}
            _, parent_key = self.issue_catalog.extract_parent_info(fields)
        self._render_parent_label(parent_key, parent_summary)

    def _apply_last_logged_cache(self, issue_keys: List[str]):
        """Fill last logged column from cache for provided issue keys."""
        for key in issue_keys:
            date_str = self._get_cached_last_logged(key)
            if not date_str:
                continue
            # Recompute relative time (could have changed day boundary)
            rel = self._format_relative_time(date_str)
            self.issue_list.update_last_logged(key, rel)

    @staticmethod
    def _format_secs(secs: int) -> str:
        return format_seconds(secs)

    @staticmethod
    def _format_relative_time(date_str: str) -> str:
        return format_relative_time(date_str)


def main():
   
    
    app = QtWidgets.QApplication(sys.argv)
    # Note: Using default behavior - app closes when last window is closed

        # App icon fallback
    app.setApplicationName(APP_NAME)
    
    # On Windows, set additional Qt attributes to prevent console issues
    if sys.platform == "win32":
        try:
            # Prevent Qt from trying to allocate console
            app.setAttribute(QtCore.Qt.AA_DisableWindowContextHelpButton, True)
            # Make sure Qt doesn't try to show console on errors
            import os
            os.environ['QT_LOGGING_RULES'] = '*.debug=false'
        except:
            pass
    
    w = Floater(ConfigManager.load())
    
    w.show()
        
    sys.exit(app.exec())
if __name__ == "__main__":
    main()
