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
import json
import datetime as dt
import time
from typing import Dict, List, Optional, Tuple
import webbrowser
import threading
from datetime import datetime, timezone

import requests
from PySide6 import QtCore, QtGui, QtWidgets

# Import restructured modules
from models import AppConfig
from api import JiraClient, TempoClient
from services import ConfigManager, CONFIG_DIR, CONFIG_PATH, OLD_CONFIG_DIR, OLD_CONFIG_PATH

APP_NAME = "Tempoy"

# Added finer granularity (1m & 4m) at user request
INCREMENTS_MIN = [1, 4, 5, 10, 15, 20, 30, 60]


def human_err(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"


def setup_windowless_process():
    """Set up the process to be truly windowless on Windows from the very start."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            
            # Get handles to Windows APIs
            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32
            
            # Method 1: Detach from any existing console
            try:
                kernel32.FreeConsole()
            except:
                pass
            
            # Method 2: Prevent console allocation for this process
            try:
                # Set process creation flags to prevent console window
                CREATE_NO_WINDOW = 0x08000000
                DETACHED_PROCESS = 0x00000008
                
                # Get current process handle
                current_process = kernel32.GetCurrentProcess()
                
                # Try to set process flags (this may not work for already-running process)
                # but it helps prevent future console allocations
                pass
            except:
                pass
                
        except Exception:
            pass


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — Settings")
        self.cfg = cfg

        form = QtWidgets.QFormLayout()
        self.jira_url = QtWidgets.QLineEdit(self.cfg.jira_base_url)
        self.jira_email = QtWidgets.QLineEdit(self.cfg.jira_email)
        self.jira_token = QtWidgets.QLineEdit(self.cfg.jira_api_token)
        self.jira_token.setEchoMode(QtWidgets.QLineEdit.Password)
        self.tempo_token = QtWidgets.QLineEdit(self.cfg.tempo_api_token)
        self.tempo_token.setEchoMode(QtWidgets.QLineEdit.Password)
        self.reminder = QtWidgets.QSpinBox()
        self.reminder.setRange(0, 480)
        self.reminder.setValue(self.cfg.reminder_minutes)
        self.reminder.setSuffix(" min (0 = off)")
        self.always_on_top = QtWidgets.QCheckBox("Keep window always on top")
        self.always_on_top.setChecked(self.cfg.always_on_top)

        form.addRow("Jira base URL (https://...atlassian.net)", self.jira_url)
        form.addRow("Jira email", self.jira_email)
        form.addRow("Jira API token", self.jira_token)
        form.addRow("Tempo API token", self.tempo_token)
        form.addRow("Reminder interval", self.reminder)
        form.addRow(self.always_on_top)

        btns = QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        self.bb = QtWidgets.QDialogButtonBox(btns)
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)

        v = QtWidgets.QVBoxLayout(self)
        v.addLayout(form)
        v.addWidget(self.bb)

        help_lbl = QtWidgets.QLabel(
            '<a href="https://id.atlassian.com/manage-profile/security/api-tokens">Create Jira API token</a> · '
            '<a href="https://help.tempo.io/timesheets/latest/using-rest-api-integrations">Tempo API token</a>'
        )
        help_lbl.setOpenExternalLinks(True)
        v.addWidget(help_lbl)

    def accept(self):
        self.cfg.jira_base_url = self.jira_url.text().strip()
        self.cfg.jira_email = self.jira_email.text().strip()
        self.cfg.jira_api_token = self.jira_token.text().strip()
        self.cfg.tempo_api_token = self.tempo_token.text().strip()
        self.cfg.reminder_minutes = int(self.reminder.value())
        self.cfg.always_on_top = bool(self.always_on_top.isChecked())
        super().accept()


class IssueList(QtWidgets.QTreeWidget):
    issueSelected = QtCore.Signal(str, str)  # key, summary
    columnResized = QtCore.Signal()  # Signal when columns are resized

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(6)
        self.setHeaderLabels(["Key", "Summary", "Epic/Parent", "Today", "Total", "Last Logged"])
        self.setRootIsDecorated(True)
        self.setAlternatingRowColors(True)
        self.itemActivated.connect(self._on_item_activated)
        self.itemClicked.connect(self._on_item_clicked)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setAllColumnsShowFocus(False)
        # Improve selection readability: white text on selection background
        self.setStyleSheet(
            """
            QTreeWidget { outline: 0; }
            QTreeWidget::item { padding: 2px; }
            QTreeWidget::item:hover { background-color: #3d7cef; color: #ffffff; }
            QTreeWidget::item:selected { background-color: #2d6cdf; color: #ffffff; }
            QTreeWidget::item:selected:active { background-color: #2d6cdf; color: #ffffff; }
            QTreeWidget::item:selected:!active { background-color: #4a7fe0; color: #ffffff; }
            QTreeWidget::item:selected:hover { background-color: #2b61c2; color: #ffffff; }
            QTreeWidget::item:focus { outline: none; }
            """
        )
        
        # Connect header resize signal
        self.header().sectionResized.connect(self._on_column_resized)
    
    def restore_column_widths(self, widths: List[int]):
        """Restore column widths from saved configuration."""
        if widths and len(widths) == self.columnCount():
            for i, width in enumerate(widths):
                if width > 0:  # Only set if valid width
                    self.setColumnWidth(i, width)
    
    def get_column_widths(self) -> List[int]:
        """Get current column widths."""
        return [self.columnWidth(i) for i in range(self.columnCount())]
    
    def _on_column_resized(self, logical_index: int, old_size: int, new_size: int):
        """Handle column resize event."""
        # Emit signal that columns have been resized
        self.columnResized.emit()

    def populate(self, issues: List[Dict]):
        self.clear()
        # group by status
        groups: Dict[str, QtWidgets.QTreeWidgetItem] = {}
        for iss in issues:
            key = iss.get("key")
            fields = iss.get("fields", {})
            summary = fields.get("summary", "")
            status = (fields.get("status") or {}).get("name", "Unknown")
            
            # Get epic or parent information
            epic_parent_text = ""
            epic_key_to_fetch = None
            
            # First try epic (customfield_10014)
            epic = fields.get("customfield_10014")
            if epic:
                if isinstance(epic, str):
                    # Epic field is just the key as a string - need to fetch summary
                    epic_key_to_fetch = epic
                    epic_parent_text = epic  # Temporary, will be updated below
                elif isinstance(epic, dict):
                    # Epic field is an object with key and potentially summary
                    epic_key = epic.get("key", "")
                    epic_summary = ""
                    if epic.get("fields"):
                        epic_summary = epic.get("fields", {}).get("summary", "")
                    elif epic.get("summary"):
                        epic_summary = epic.get("summary", "")
                    
                    if epic_key:
                        if epic_summary:
                            epic_parent_text = f"{epic_key}: {epic_summary}"
                        else:
                            epic_key_to_fetch = epic_key
                            epic_parent_text = epic_key
            
            # If no epic, try parent
            if not epic_parent_text and fields.get("parent"):
                parent = fields["parent"]
                if isinstance(parent, dict):
                    parent_key = parent.get("key", "")
                    parent_summary = parent.get("fields", {}).get("summary", "")
                    if parent_key:
                        if parent_summary:
                            epic_parent_text = f"{parent_key}: {parent_summary}"
                        else:
                            epic_key_to_fetch = parent_key
                            epic_parent_text = parent_key
            
            if status not in groups:
                parent = QtWidgets.QTreeWidgetItem([status, "", "", "", "", ""])
                parent.setFirstColumnSpanned(True)
                parent.setFlags(parent.flags() & ~QtCore.Qt.ItemIsSelectable)
                self.addTopLevelItem(parent)
                groups[status] = parent
            parent = groups[status]
            child = QtWidgets.QTreeWidgetItem([key, summary, epic_parent_text, "…", "…", ""])
            # Store epic/parent key for later summary fetching if needed
            if epic_key_to_fetch:
                child.setData(2, QtCore.Qt.UserRole, epic_key_to_fetch)
            parent.addChild(child)
        for i in range(self.topLevelItemCount()):
            self.topLevelItem(i).setExpanded(True)
        # Don't auto-resize columns anymore - let user control widths
        # self.resizeColumnToContents(0)
        # self.resizeColumnToContents(2)

    @QtCore.Slot(str, str, str)
    def update_worklog(self, issue_key: str, today: str, total: str):
        # Traverse and update matching child
        for i in range(self.topLevelItemCount()):
            parent = self.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.text(0) == issue_key:
                    child.setText(3, today)
                    child.setText(4, total)
                    return

    def update_last_logged(self, issue_key: str, last_logged: str):
        """Update the last logged date for a specific issue."""
        for i in range(self.topLevelItemCount()):
            parent = self.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.text(0) == issue_key:
                    child.setText(5, last_logged)
                    return

    def _on_item_activated(self, item, col):
        if item and item.parent():
            self.issueSelected.emit(item.text(0), item.text(1))

    def _on_item_clicked(self, item, col):
        if item and item.parent():
            self.issueSelected.emit(item.text(0), item.text(1))


class Floater(QtWidgets.QMainWindow):
    worklogFetched = QtCore.Signal(str, str, str)  # issue_key, today, total
    def __init__(self, cfg: AppConfig):
        super().__init__()
        self.cfg = cfg
        self.jira: Optional[JiraClient] = None
        self.tempo: Optional[TempoClient] = None
        self.account_id: Optional[str] = None
        # Track selected issue for logging
        self._selected_issue_id: Optional[str] = None
        self._selected_issue_key: Optional[str] = None
        
        # Worklog caching system
        self._worklog_cache: Dict[str, Tuple[int, int, float]] = {}  # issue_key -> (today_secs, total_secs, timestamp)
        self._cache_duration = 300  # 5 minutes in seconds
        self._current_issues: List[str] = []  # Track currently displayed issues
        # Cache for last logged date: issue_key -> (date_str, timestamp)
        self._last_logged_cache: Dict[str, Tuple[str, float]] = {}
        
        # Window sizing for expand/collapse (from config)
        self._collapsed_size = (cfg.collapsed_width, cfg.collapsed_height)
        self._expanded_size = (cfg.expanded_width, cfg.expanded_height)
        
        # Flag to prevent resize tracking during programmatic resizing
        self._programmatic_resize = False
        
        # Track the current expanded state explicitly
        self._is_expanded = cfg.expanded
        
        # Track daily total time
        self._daily_total_secs = 0
        self._daily_total_cache_time = 0
        self._daily_total_cache_duration = 300  # 5 minutes
        
        # Startup state tracking
        self._startup_complete = False
        self._daily_total_lock = threading.Lock()
        
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
        self.search.lineEdit().setPlaceholderText("Search issue (key or text)… Enter = search")
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
        self.btn_expand.toggled.connect(self.on_toggle_expand)
        self.btn_settings = QtWidgets.QToolButton(text="⚙")
        self.btn_settings.clicked.connect(self.open_settings)

        # Two-row increment button layout
        inc_grid = QtWidgets.QGridLayout()
        inc_grid.setHorizontalSpacing(6)
        inc_grid.setVerticalSpacing(4)
        half = (len(INCREMENTS_MIN) + 1) // 2  # top row length
        buttons = []
        for idx, m in enumerate(INCREMENTS_MIN):
            row = 0 if idx < half else 1
            col = idx if row == 0 else idx - half
            b = QtWidgets.QPushButton(f"+{m}m")
            b.setFixedHeight(26)
            b.clicked.connect(lambda _, mm=m: self.log_increment(minutes=mm))
            inc_grid.addWidget(b, row, col)
            buttons.append(b)

        # Timer control button spans both rows at the end
        self.timer_btn = QtWidgets.QPushButton("Starting...")
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
        self.btn_clear_history.setToolTip("Clear search & issue history")
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
        
        self.btn_refresh = QtWidgets.QPushButton("Refresh issues (assigned + worked on)")
        self.btn_refresh.clicked.connect(self.refresh_assigned)

        self.desc = QtWidgets.QLineEdit()
        self.desc.setPlaceholderText("Optional description / comment for the worklog")

        expanded = QtWidgets.QWidget()
        lay_exp = QtWidgets.QVBoxLayout(expanded)
        lay_exp.setContentsMargins(8, 0, 8, 8)
        lay_exp.addWidget(self.btn_refresh)
        lay_exp.addWidget(self.issue_list, 1)
        lay_exp.addWidget(self.desc)

        self.expanded = expanded
        self.expanded.setVisible(False)

        central = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(central)
        v.addWidget(head_widget)
        v.addWidget(self.expanded, 1)
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
        act_log5 = menu.addAction("Log +5m to last issue")
        act_log5.triggered.connect(lambda: self.log_increment(5, to_last=True))
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

        # Position and size window from saved config
        if cfg.expanded:
            self.resize(*self._expanded_size)
            self.expanded.setVisible(True)
            self.btn_expand.setText("▲")
        else:
            self.resize(*self._collapsed_size)
            self.expanded.setVisible(False)
            self.btn_expand.setText("▼")
        
        self.move(cfg.window_x, cfg.window_y)
        # Set reasonable minimum size but not too restrictive
        self.setMinimumSize(300, 100)  # Prevent window from getting too small but allow flexibility

    def _delayed_init(self):
        """Initialize clients after window is shown to ensure proper UI updates."""
        debug = os.environ.get("TEMPOY_DEBUG")
        if debug:
            print(f"[TEMPOY DEBUG] _delayed_init called")
        
        # Initialize clients if config is present
        self.ensure_clients()
    
    # ---------- Window overrides ----------
    def show(self):
        """Override show method."""
        super().show()
    
    def raise_(self):
        """Override raise_ method."""
        super().raise_()
    
    def activateWindow(self):
        """Override activateWindow method."""
        super().activateWindow()

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
            self.account_id = self.jira.get_myself().get("accountId")
            
            # Update window title immediately to show "Today: 0m" format
            self._update_window_title()
            
            # If this is the first time clients are initialized, start proper initialization
            if not was_initialized and not self._startup_complete:
                QtCore.QTimer.singleShot(100, self._initialize_after_clients)
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Auth error", f"Failed to initialize clients:\n{human_err(e)}")
            return False
        return True

    def _initialize_after_clients(self):
        """Initialize application state after clients are ready - ensures proper startup sequence."""
        debug = os.environ.get("TEMPOY_DEBUG")
        if debug:
            print(f"[TEMPOY DEBUG] _initialize_after_clients called")
        
        if self._startup_complete:
            if debug:
                print(f"[TEMPOY DEBUG] Startup already complete, skipping")
            return
        
        try:
            # Step 1: Fetch daily total synchronously like the working paths do
            if self.tempo and self.account_id:
                if debug:
                    print(f"[TEMPOY DEBUG] Fetching daily total synchronously")
                try:
                    daily_total = self.tempo.get_user_daily_total(account_id=self.account_id)
                    self._daily_total_secs = daily_total
                    self._daily_total_cache_time = dt.datetime.now().timestamp()
                    if debug:
                        print(f"[TEMPOY DEBUG] Got daily total: {daily_total} seconds")
                    # Update window title immediately (like log_increment does)
                    self._update_window_title()
                except Exception as e:
                    if debug:
                        print(f"[TEMPOY DEBUG] Failed to get daily total: {e}")
                    # Still update title to show "Today: 0m"
                    self._daily_total_secs = 0
                    self._update_window_title()
            
            # Step 2: Restore last issue if any (this may trigger search/worklog fetches)
            if self.cfg.last_issue_key:
                if debug:
                    print(f"[TEMPOY DEBUG] Restoring last issue: {self.cfg.last_issue_key}")
                self._restore_last_issue()
            
            # Step 3: Mark startup as complete
            self._startup_complete = True
            if debug:
                print(f"[TEMPOY DEBUG] Startup marked as complete")
            
            # Step 4: Start periodic timers with a small delay to avoid conflicts
            QtCore.QTimer.singleShot(1000, self._start_periodic_timers)
            
        except Exception as e:
            if debug:
                print(f"[TEMPOY DEBUG] Error during initialization: {e}")
            # Still mark startup complete to avoid hanging in incomplete state
            self._startup_complete = True
    
    def _start_periodic_timers(self):
        """Start periodic timers after startup is complete."""
        debug = os.environ.get("TEMPOY_DEBUG")
        if debug:
            print(f"[TEMPOY DEBUG] Starting periodic timers")
        
        # Start daily total timer (10 minutes)
        self.daily_total_timer.start(600000)
        
        if debug:
            print(f"[TEMPOY DEBUG] Periodic timers started")
    
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
            self.timer_btn.setText("⏸ Stopped")
            self.timer_btn.setStyleSheet("QPushButton { background-color: #ff6b6b; color: white; font-weight: bold; }")
            return

        # Paused states
        if self._timer_paused:
            if self._paused_due_to_lock and self._was_locked:
                # Currently locked
                self.timer_btn.setText("⏸ Paused (Locked)")
                self.timer_btn.setStyleSheet("QPushButton { background-color: #ffa94d; color: #222; font-weight: bold; }")
            elif self._paused_due_to_lock and not self._was_locked:
                # Lock released; awaiting manual resume
                self.timer_btn.setText("⏸ Resume?")
                self.timer_btn.setStyleSheet("QPushButton { background-color: #ffd43b; color: #222; font-weight: bold; }")
            else:
                # Generic manual pause (future-proof)
                self.timer_btn.setText("⏸ Paused")
                self.timer_btn.setStyleSheet("QPushButton { background-color: #ffec99; color: #222; font-weight: bold; }")
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
            self.timer_btn.setText("⏱ Ready")
            self.timer_btn.setStyleSheet("QPushButton { background-color: #51cf66; color: white; font-weight: bold; }")
            return

        now = time.time()
        remaining = self._next_reminder_time - now

        if remaining <= 0:
            self.timer_btn.setText("⏱ Ready")
            self.timer_btn.setStyleSheet("QPushButton { background-color: #51cf66; color: white; font-weight: bold; }")
        else:
            mins, secs = divmod(int(remaining), 60)
            countdown_text = f"⏱ {mins}:{secs:02d}" if mins > 0 else f"⏱ {secs}s"
            self.timer_btn.setText(countdown_text)
            self.timer_btn.setStyleSheet("QPushButton { background-color: #51cf66; color: white; font-weight: bold; }")
    
    def _reset_reminder(self):
        self.reminder_timer.stop()
        mins = int(self.cfg.reminder_minutes or 0)
        if mins > 0 and self._timer_running and not self._timer_paused:
            self.reminder_timer.start(mins * 60 * 1000)
            self._next_reminder_time = time.time() + (mins * 60)
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
        if issue_key not in self._worklog_cache:
            return False
        _, _, timestamp = self._worklog_cache[issue_key]
        return (dt.datetime.now().timestamp() - timestamp) < self._cache_duration
    
    def _get_cached_worklog(self, issue_key: str) -> Optional[Tuple[int, int]]:
        """Get cached worklog data if valid, otherwise return None."""
        if self._is_cache_valid(issue_key):
            today_secs, total_secs, _ = self._worklog_cache[issue_key]
            return (today_secs, total_secs)
        return None
    
    def _cache_worklog(self, issue_key: str, today_secs: int, total_secs: int):
        """Cache worklog data with current timestamp."""
        self._worklog_cache[issue_key] = (today_secs, total_secs, dt.datetime.now().timestamp())
    
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
            debug = os.environ.get("TEMPOY_DEBUG")
            if debug:
                print(f"[TEMPOY DEBUG] Periodic refresh for {len(issues_to_refresh)} issues")
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
    
    def closeEvent(self, event):
        """Handle window close event - close application instead of hiding."""
        # Save current state before closing
        self.cfg.window_x = self.x()
        self.cfg.window_y = self.y()
        self.cfg.window_width = self.width()
        self.cfg.window_height = self.height()
        ConfigManager.save(self.cfg)
        
        # Clean up tray icon before closing
        if hasattr(self, 'tray'):
            self.tray.hide()
        
        # Accept the close event - this will naturally close the app
        event.accept()
        
        # Use a timer to quit after the event is processed to avoid segfault
        QtCore.QTimer.singleShot(0, QtWidgets.QApplication.instance().quit)
    
    def resizeEvent(self, event):
        """Track manual resizing to update config."""
        super().resizeEvent(event)
        
        debug = os.environ.get("TEMPOY_DEBUG")
        if debug:
            new_size = event.size()
            old_size = event.oldSize()
            is_programmatic = getattr(self, '_programmatic_resize', False)
            print(f"[TEMPOY DEBUG] ResizeEvent: {old_size.width()}x{old_size.height()} -> {new_size.width()}x{new_size.height()}, programmatic: {is_programmatic}")
        
        # Don't track resize if it's programmatic (from expand/collapse)
        if getattr(self, '_programmatic_resize', False):
            if debug:
                print(f"[TEMPOY DEBUG] Ignoring programmatic resize")
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
        debug = os.environ.get("TEMPOY_DEBUG")
        
        if self.btn_expand.isChecked():  # Currently expanded
            self.cfg.expanded_width = size.width()
            self.cfg.expanded_height = size.height()
            self._expanded_size = (self.cfg.expanded_width, self.cfg.expanded_height)
            if debug:
                print(f"[TEMPOY DEBUG] Saved expanded size: {size.width()}x{size.height()}")
        else:  # Currently collapsed
            self.cfg.collapsed_width = size.width()
            self.cfg.collapsed_height = size.height()
            self._collapsed_size = (self.cfg.collapsed_width, self.cfg.collapsed_height)
            if debug:
                print(f"[TEMPOY DEBUG] Saved collapsed size: {size.width()}x{size.height()}")
        
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
        debug = os.environ.get("TEMPOY_DEBUG")
        if debug:
            print(f"[TEMPOY DEBUG] Resize verification - Expected: {expected_size}, Actual: {actual_size.width()}x{actual_size.height()}")
            
        if (actual_size.width(), actual_size.height()) != expected_size:
            if debug:
                print(f"[TEMPOY DEBUG] Resize verification FAILED - forcing resize again")
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

    # ---------- UI callbacks ----------
    def on_toggle_expand(self, expanded: bool):
        current_size = self.size()
        debug = os.environ.get("TEMPOY_DEBUG")
        
        if debug:
            print(f"[TEMPOY DEBUG] Toggle: was_expanded={self._is_expanded}, switching_to_expanded={expanded}")
            print(f"[TEMPOY DEBUG] Current size: {current_size.width()}x{current_size.height()}")
            print(f"[TEMPOY DEBUG] Saved collapsed: {self.cfg.collapsed_width}x{self.cfg.collapsed_height}")
            print(f"[TEMPOY DEBUG] Saved expanded: {self.cfg.expanded_width}x{self.cfg.expanded_height}")
        
        # Save current size based on the state we're LEAVING (using our tracked state)
        if self._is_expanded:  # We were expanded, now collapsing - save current as expanded size
            self.cfg.expanded_width = current_size.width()
            self.cfg.expanded_height = current_size.height()
            if debug:
                print(f"[TEMPOY DEBUG] Saving current size as expanded: {current_size.width()}x{current_size.height()}")
        else:  # We were collapsed, now expanding - save current as collapsed size
            self.cfg.collapsed_width = current_size.width()
            self.cfg.collapsed_height = current_size.height()
            if debug:
                print(f"[TEMPOY DEBUG] Saving current size as collapsed: {current_size.width()}x{current_size.height()}")
        
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
                print(f"[TEMPOY DEBUG] Switching to expanded, target size: {target_size}")
        else:
            target_size = self._collapsed_size
            if debug:
                print(f"[TEMPOY DEBUG] Switching to collapsed, target size: {target_size}")
        
        # Use programmatic resize flag to prevent tracking this resize
        self._programmatic_resize = True
        
        # Force resize window to target size with multiple methods
        if debug:
            print(f"[TEMPOY DEBUG] About to resize to: {target_size}")
        
        # Method 1: Direct resize
        self.resize(*target_size)
        
        # Method 2: Force immediate geometry update
        self.setGeometry(self.x(), self.y(), target_size[0], target_size[1])
        
        # Method 3: Process events to ensure resize takes effect
        QtWidgets.QApplication.processEvents()
        
        # Verify the resize worked
        actual_size = self.size()
        if debug:
            print(f"[TEMPOY DEBUG] After resize - Actual size: {actual_size.width()}x{actual_size.height()}")
            if (actual_size.width(), actual_size.height()) != target_size:
                print(f"[TEMPOY DEBUG] WARNING: Resize failed! Expected {target_size}, got {actual_size.width()}x{actual_size.height()}")
        
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

    def on_issue_selected(self, key: str, summary: str):
        self.cfg.last_issue_key = key
        self._selected_issue_key = key
        
        # Record issue selection (with summary) in history
        self._record_issue_history(key, summary)
        # Refresh the combo box to show updated history (always safe now)
        self._populate_search_history()
        
        # Create clickable link to the Jira ticket
        if self.cfg.jira_base_url and key:
            ticket_url = f"{self.cfg.jira_base_url}/browse/{key}"
            self.issue_label.setText(f'<a href="{ticket_url}">{key}</a> — {summary}')
        else:
            self.issue_label.setText(f"{key} — {summary}")
        
        # Get and cache the issue ID for Tempo API calls
        if self.jira:
            self._selected_issue_id = self.jira.get_issue_id(key)
        
        # Update time display for selected issue
        self._update_selected_issue_time(key)

        # Update parent/epic label
        self._update_parent_label(key)
        
        ConfigManager.save(self.cfg)

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
                QtWidgets.QMessageBox.information(self, "Search", "No issues found.")
                return
            # Prefer selecting exact key if query looks like one
            preferred_key = None
            if self._looks_like_issue_key(query):
                preferred_key = query
            elif self.cfg.last_issue_key in [i.get("key") for i in issues]:
                preferred_key = self.cfg.last_issue_key
            self._display_issue_results(issues, preferred_key)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Search failed", human_err(e))

    def refresh_assigned(self):
        if not self.ensure_clients():
            return
        try:
            # Get assigned issues as before
            assigned_issues = self.jira.search_assigned()
            all_issues = assigned_issues[:]
            
            # Also get issues with recent worklogs from Tempo
            if self.tempo and self.account_id:
                try:
                    # Get recent worklogs to find additional issues
                    recent_worklogs = self.tempo.get_recent_worked_issues(
                        account_id=self.account_id,
                        days_back=7  # Last week
                    )
                    
                    # Get unique issue keys from worklogs
                    worked_issue_keys = set()
                    for wl in recent_worklogs:
                        issue_obj = wl.get("issue", {})
                        issue_key = issue_obj.get("key")
                        if issue_key:
                            worked_issue_keys.add(issue_key)
                    
                    # Fetch details for worked issues not in assigned list
                    assigned_keys = {i.get("key") for i in assigned_issues}
                    additional_keys = worked_issue_keys - assigned_keys
                    
                    if additional_keys:
                        # Search for these specific issues
                        key_list = '","'.join(additional_keys)
                        jql = f'key in ("{key_list}") ORDER BY updated DESC'
                        additional_issues = self.jira._search_jql(
                            jql=jql,
                            max_results=len(additional_keys),
                            fields=["summary", "status", "issuetype", "project", "priority", "parent", "customfield_10014"]
                        )
                        
                        # Combine all issues
                        all_issues = assigned_issues + additional_issues
                
                except Exception as e:
                    # If Tempo lookup fails, just use assigned issues
                    print(f"Warning: Could not fetch recent worked issues: {human_err(e)}")
            
            preferred_key = self.cfg.last_issue_key if self.cfg.last_issue_key in [i.get("key") for i in all_issues] else None
            self._display_issue_results(all_issues, preferred_key)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Load failed", human_err(e))

    def _fetch_epic_parent_summaries(self):
        """Fetch summaries for epic/parent keys that need them."""
        if not self.jira:
            return
        
        keys_to_fetch = set()
        items_to_update = []
        
        # Collect all epic/parent keys that need summaries
        for i in range(self.issue_list.topLevelItemCount()):
            parent = self.issue_list.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                epic_key = child.data(2, QtCore.Qt.UserRole)
                if epic_key and isinstance(epic_key, str):
                    keys_to_fetch.add(epic_key)
                    items_to_update.append((child, epic_key))
        
        if not keys_to_fetch:
            return
        
        try:
            # Fetch all needed epic/parent issues at once
            key_list = '","'.join(keys_to_fetch)
            jql = f'key in ("{key_list}")'
            epic_issues = self.jira._search_jql(
                jql=jql,
                max_results=len(keys_to_fetch),
                fields=["summary"]
            )
            
            # Create lookup map
            summaries = {}
            for issue in epic_issues:
                issue_key = issue.get("key")
                summary = issue.get("fields", {}).get("summary", "")
                if issue_key:
                    summaries[issue_key] = summary
            
            # Update the items with fetched summaries
            for child, epic_key in items_to_update:
                summary = summaries.get(epic_key, "")
                if summary:
                    child.setText(2, f"{epic_key}: {summary}")
                else:
                    child.setText(2, epic_key)  # Keep just the key if no summary found
                    
        except Exception as e:
            # Silently fail - epic/parent summaries are nice-to-have
            debug = os.environ.get("TEMPOY_DEBUG")
            if debug:
                print(f"[DEBUG] Failed to fetch epic/parent summaries: {e}")

    def log_increment(self, minutes: int, to_last: bool=False):
        if not self.ensure_clients():
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
            QtWidgets.QMessageBox.information(self, "Select issue", "Pick or search for an issue first.")
            return
        
        # Get issue ID for Tempo API - this is required!
        issue_id = None
        if to_last and self.jira:
            issue_id = self.jira.get_issue_id(key)
        elif not to_last:
            issue_id = self._selected_issue_id
            
        if not issue_id:
            QtWidgets.QMessageBox.critical(self, "Missing Issue ID", 
                f"Could not get issue ID for {key}. Please refresh the issue list and try again.")
            return
            
        seconds = int(minutes * 60)
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
            self.tray.showMessage(APP_NAME, f"Logged +{minutes}m to {key}", QtWidgets.QSystemTrayIcon.Information, 4000)
            
            # Invalidate cache for this issue and refresh its worklog data
            if key in self._worklog_cache:
                del self._worklog_cache[key]
            self._start_worklog_fetch([key], force_refresh=True)
            
            # If this is the selected issue, update its time display
            if key == self._selected_issue_key:
                self._update_selected_issue_time(key)
            
            # Update daily total in window title
            self._daily_total_secs += seconds
            self._daily_total_cache_time = dt.datetime.now().timestamp()
            self._update_window_title()
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Log failed", human_err(e))

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            ConfigManager.save(self.cfg)
            self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, self.cfg.always_on_top)
            self.show()  # refresh flags
            self._reset_reminder()

    def _remind(self):
        # Only show reminder if timer is running
        if not self._timer_running:
            return
        # Play audible cue
        self._play_reminder_sound()
            
        self.tray.showMessage("Time reminder", "Don't forget to register your time in Tempo.", QtWidgets.QSystemTrayIcon.Warning, 8000)
        
        # Reset reminder for next cycle
        self._reset_reminder()

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
    
    def _update_selected_issue_time(self, issue_key: str):
        """Update the time display for the currently selected issue."""
        debug = os.environ.get("TEMPOY_DEBUG")
        
        if debug:
            print(f"[TEMPOY DEBUG] _update_selected_issue_time called for {issue_key}")
            print(f"[TEMPOY DEBUG] tempo: {bool(self.tempo)}, account_id: {bool(self.account_id)}")
        
        if not (self.tempo and self.account_id):
            self.time_label.setText("")
            if debug:
                print(f"[TEMPOY DEBUG] Missing tempo client or account_id - clearing time label")
            return
        
        # Check cache first
        cached = self._get_cached_worklog(issue_key)
        if cached:
            today_secs, total_secs = cached
            if debug:
                print(f"[TEMPOY DEBUG] Using cached time data: today={today_secs}s, total={total_secs}s")
            self._display_selected_issue_time(today_secs, total_secs)
        else:
            # Show loading state and fetch in background
            if debug:
                print(f"[TEMPOY DEBUG] No cached data - starting background fetch")
            self.time_label.setText("Loading time...")
            threading.Thread(target=self._fetch_selected_issue_time, args=(issue_key,), daemon=True).start()
    
    def _display_selected_issue_time(self, today_secs: int, total_secs: int):
        """Display the time information for the selected issue."""
        today_str = self._format_secs(today_secs)
        total_str = self._format_secs(total_secs)
        
        if today_secs > 0 or total_secs > 0:
            self.time_label.setText(f"Today: {today_str} | Total: {total_str}")
        else:
            self.time_label.setText("No time logged")
    
    def _fetch_selected_issue_time(self, issue_key: str):
        """Fetch time data for selected issue in background thread."""
        debug = os.environ.get("TEMPOY_DEBUG")
        try:
            if debug:
                print(f"[TEMPOY DEBUG] _fetch_selected_issue_time starting for {issue_key}")
            
            issue_id = self.jira.get_issue_id(issue_key) if self.jira else None
            
            if debug:
                print(f"[TEMPOY DEBUG] Got issue_id: {issue_id} for {issue_key}")
            
            today_secs, total_secs = self.tempo.get_user_issue_time(
                issue_key=issue_key, 
                issue_id=issue_id, 
                account_id=self.account_id
            )
            
            if debug:
                print(f"[TEMPOY DEBUG] Fetched time data for {issue_key}: today={today_secs}s, total={total_secs}s")
            
            # Cache the result
            self._cache_worklog(issue_key, today_secs, total_secs)
            
            # Update UI on main thread
            QtCore.QTimer.singleShot(0, lambda: self._display_selected_issue_time(today_secs, total_secs))
            
        except Exception as e:
            if debug:
                print(f"[TEMPOY DEBUG] Failed to fetch time for selected issue {issue_key}: {e}")
            QtCore.QTimer.singleShot(0, lambda: self.time_label.setText("Failed to load time"))

    # ---------- Worklog enrichment ----------
    def _start_worklog_fetch(self, issue_keys: List[str], force_refresh: bool = False):
        """Start fetching worklog data for issues, using cache when possible."""
        debug = os.environ.get("TEMPOY_DEBUG")
        
        if debug:
            print(f"[TEMPOY DEBUG] _start_worklog_fetch called with {issue_keys}, force_refresh={force_refresh}")
            print(f"[TEMPOY DEBUG] jira: {bool(self.jira)}, account_id: {bool(self.account_id)}")
        
        if not (self.jira and self.account_id):
            if debug:
                print(f"[TEMPOY DEBUG] Missing jira client or account_id - returning early")
            return
        
        # Filter out issues that have valid cached data (unless forcing refresh)
        original_count = len(issue_keys)
        if not force_refresh:
            issue_keys = [key for key in issue_keys if not self._is_cache_valid(key)]
        
        if debug:
            print(f"[TEMPOY DEBUG] After cache filtering: {original_count} -> {len(issue_keys)} issues to fetch")
        
        if issue_keys:
            # Ensure IDs before launching background thread
            self._ensure_issue_ids(issue_keys)
            if debug:
                print(f"[TEMPOY DEBUG] Starting background thread for worklog fetch: {issue_keys}")
            # Run in background thread to avoid blocking UI
            threading.Thread(target=self._fetch_and_update_worklogs, args=(issue_keys, True), daemon=True).start()
        elif debug:
            print(f"[TEMPOY DEBUG] No issues to fetch (all cached or empty list)")

    def _fetch_and_update_worklogs(self, issue_keys: List[str], update_cache: bool = True):
        """Fetch worklog data for issues and optionally update cache."""
        debug = os.environ.get("TEMPOY_DEBUG")
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
            if self.tempo and self.account_id:
                try:
                    issue_id = self.jira.get_issue_id(key) if self.jira else None
                    if not issue_id and debug:
                        print(f"[TEMPOY DEBUG] Warning: Missing issue_id for {key} prior to Tempo call")
                    today_secs, total_secs = self.tempo.get_user_issue_time(issue_key=key, issue_id=issue_id, account_id=self.account_id)
                except Exception as e:
                    if debug:
                        print(f"[TEMPOY DEBUG] Tempo per-issue fetch failed for {key}: {e}")
            # Jira fallback if still zero
            if total_secs == 0 and self.jira and self.account_id:
                try:
                    jt_today, jt_total = self.jira.sum_worklog_times(key, self.account_id)
                    # Only override if Jira reports any time or we have none
                    if jt_total > 0:
                        today_secs, total_secs = jt_today, jt_total
                except Exception as e:
                    if debug:
                        print(f"[TEMPOY DEBUG] Jira fallback failed for {key}: {e}")
            
            # Cache the results if requested
            if update_cache:
                self._cache_worklog(key, today_secs, total_secs)
            
            today_str = self._format_secs(today_secs)
            total_str = self._format_secs(total_secs)
            
            # Also fetch last logged date
            last_logged = ""
            if self.tempo and self.account_id:
                try:
                    issue_id = self.jira.get_issue_id(key) if self.jira else None
                    if not issue_id and debug:
                        print(f"[TEMPOY DEBUG] Warning: Missing issue_id for last logged lookup {key}")
                    if debug:
                        print(f"[TEMPOY DEBUG] Fetching last logged for {key}, issue_id={issue_id}")
                    last_logged_date = self.tempo.get_last_logged_date(issue_key=key, issue_id=issue_id, account_id=self.account_id)
                    if last_logged_date:
                        last_logged = last_logged_date
                        if debug:
                            print(f"[TEMPOY DEBUG] Found last logged date for {key}: {last_logged_date}")
                    elif debug:
                        print(f"[TEMPOY DEBUG] No last logged date found for {key}")
                        
                except Exception as e:
                    if debug:
                        print(f"[TEMPOY DEBUG] Last logged date fetch failed for {key}: {e}")
            
            # Update the issue list with last logged date in relative format
            if last_logged:
                # Cache raw date
                self._last_logged_cache[key] = (last_logged, dt.datetime.now().timestamp())
                relative_time = self._format_relative_time(last_logged)
                self.issue_list.update_last_logged(key, relative_time)
            
            if debug:
                print(f"[TEMPOY DEBUG] Final time {key}: today={today_secs}s total={total_secs}s")
            self.worklogFetched.emit(key, today_str, total_str)

    def _on_worklog_fetched(self, issue_key: str, today_str: str, total_str: str):
        """Handle worklog data being fetched for any issue."""
        if issue_key == self._selected_issue_key:
            # Convert back to seconds for display
            try:
                cached = self._get_cached_worklog(issue_key)
                if cached:
                    today_secs, total_secs = cached
                    self._display_selected_issue_time(today_secs, total_secs)
            except Exception:
                pass
    
    def _restore_last_issue(self):
        """Restore the last selected issue from config by simulating a search."""
        last_issue_key = self.cfg.last_issue_key.strip() if self.cfg.last_issue_key else ""
        if not last_issue_key:
            return
        
        debug = os.environ.get("TEMPOY_DEBUG")
        if debug:
            print(f"[TEMPOY DEBUG] Restoring last issue by simulating search: {last_issue_key}")
        
        # If we don't have clients set up yet, we can't search for issues
        if not (self.jira and self.tempo and self.account_id):
            if debug:
                print(f"[TEMPOY DEBUG] Clients not ready, cannot restore last issue")
            return
        
        # Put the last issue key in the search box and trigger search
        # This ensures we get exactly the same behavior as manual search
        try:
            if debug:
                print(f"[TEMPOY DEBUG] Setting search text to: {last_issue_key}")
            
            # Set the search text
            self.search.setCurrentText(last_issue_key)
            
            # Call the search function - this will do everything correctly
            if debug:
                print(f"[TEMPOY DEBUG] Calling on_search() to trigger full search behavior")
            self.on_search()
            
        except Exception as e:
            if debug:
                print(f"[TEMPOY DEBUG] Failed to restore last issue via search {last_issue_key}: {e}")
    
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
        """Save window state before closing."""
        self._save_window_state()
        super().closeEvent(event)
    
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
        
        debug = os.environ.get("TEMPOY_DEBUG")
        if debug:
            print(f"[TEMPOY DEBUG] Saved column widths: {self.cfg.issue_list_column_widths}")
    
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
        
        ConfigManager.save(self.cfg)
    
    def _update_window_title(self):
        """Update window title to include daily total time."""
        debug = os.environ.get("TEMPOY_DEBUG")
        if hasattr(self, 'tempo') and self.tempo and self.account_id:
            daily_str = self._format_secs(self._daily_total_secs)
            base_title = f"{APP_NAME} — Today: {daily_str}"
            if debug:
                print(f"[TEMPOY DEBUG] Updating window title to: {base_title}")
        else:
            base_title = APP_NAME
            if debug:
                print(f"[TEMPOY DEBUG] Using default window title (no clients): {base_title}")
        self.setWindowTitle(base_title)
    
    def _refresh_daily_total(self):
        """Refresh daily total time in background thread."""
        debug = os.environ.get("TEMPOY_DEBUG")
        
        if debug:
            print(f"[TEMPOY DEBUG] _refresh_daily_total called")
            print(f"[TEMPOY DEBUG] tempo: {bool(self.tempo)}, account_id: {bool(self.account_id)}")
        
        if not (self.tempo and self.account_id):
            if debug:
                print(f"[TEMPOY DEBUG] Missing tempo client or account_id - cannot refresh daily total")
            return
        
        # During startup, only allow refresh if we're in initialization phase
        if not self._startup_complete:
            if debug:
                print(f"[TEMPOY DEBUG] Startup not complete - skipping periodic refresh")
            return
        
        # Check if cache is still valid
        now = dt.datetime.now().timestamp()
        cache_age = now - self._daily_total_cache_time
        
        if debug:
            print(f"[TEMPOY DEBUG] Cache age: {cache_age}s, duration limit: {self._daily_total_cache_duration}s")
        
        if cache_age < self._daily_total_cache_duration:
            if debug:
                print(f"[TEMPOY DEBUG] Cache still valid - not refreshing daily total")
            return
        
        # Use lock to prevent concurrent fetches
        if not self._daily_total_lock.acquire(blocking=False):
            if debug:
                print(f"[TEMPOY DEBUG] Daily total fetch already in progress - skipping")
            return
        
        # Fetch in background thread
        if debug:
            print(f"[TEMPOY DEBUG] Starting background fetch for daily total")
        threading.Thread(target=self._fetch_daily_total, daemon=True).start()
    
    def _fetch_daily_total(self):
        """Fetch daily total time and update window title."""
        debug = os.environ.get("TEMPOY_DEBUG")
        try:
            if debug:
                print(f"[TEMPOY DEBUG] Fetching daily total for account: {self.account_id}")
            daily_total = self.tempo.get_user_daily_total(account_id=self.account_id)
            self._daily_total_secs = daily_total
            self._daily_total_cache_time = dt.datetime.now().timestamp()
            
            if debug:
                print(f"[TEMPOY DEBUG] Fetched daily total: {daily_total} seconds")
            
            # Update UI on main thread
            QtCore.QTimer.singleShot(0, lambda: self._update_window_title())
        except Exception as e:
            if debug:
                print(f"[TEMPOY DEBUG] Failed to fetch daily total: {e}")
            # Set to 0 and update title anyway to show "Today: 0m"
            self._daily_total_secs = 0
            QtCore.QTimer.singleShot(0, lambda: self._update_window_title())
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
            "Clear History",
            "Clear all search and selected issue history entries?",
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
        if os.environ.get("TEMPOY_DEBUG"):
            print(f"[TEMPOY DEBUG] Recorded search history: {query}")

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
        if os.environ.get("TEMPOY_DEBUG"):
            print(f"[TEMPOY DEBUG] Recorded issue selection history: {key}")

    # ---------- Issue ID management ----------
    def _ensure_issue_ids(self, issue_keys: List[str]):
        """Ensure Jira numeric issue IDs are cached for all provided keys.

        Bulk fetches missing IDs using a single JQL query to avoid per-issue HTTP round trips.
        Safe to call multiple times; silently ignores failures.
        """
        if not (self.jira and issue_keys):
            return
        # Determine missing keys
        cache = getattr(self.jira, "_issue_id_cache", {})
        missing = [k for k in issue_keys if k and k not in cache]
        if not missing:
            return
        debug = os.environ.get("TEMPOY_DEBUG")
        try:
            # Chunk if large
            chunk_size = 40  # conservative for JQL length
            for i in range(0, len(missing), chunk_size):
                chunk = missing[i:i+chunk_size]
                key_list = '\",\"'.join(chunk)
                jql = f'key in ("{key_list}")'
                # We only need id field, but existing helper requires fields list
                self.jira._search_jql(jql=jql, max_results=len(chunk), fields=["summary"])
                if debug:
                    print(f"[TEMPOY DEBUG] Ensured issue IDs for chunk: {chunk}")
        except Exception as e:
            if debug:
                print(f"[TEMPOY DEBUG] Failed to bulk ensure issue IDs: {e}")

    # ---------- Unified issue result display ----------
    def _display_issue_results(self, issues: List[Dict], preferred_key: Optional[str] = None):
        """Central handler to display a list of issues and trigger enrichment.

        Args:
            issues: Raw Jira issue objects
            preferred_key: Issue key to auto-select if present
        """
        if not issues:
            return
        issue_keys = [i.get("key") for i in issues if i.get("key")]
        self._current_issues = issue_keys
        self.issue_list.populate(issues)
        # Ensure IDs & epic/parent summaries
        self._ensure_issue_ids(issue_keys)
        self._fetch_epic_parent_summaries()
        # Apply any cached last logged dates immediately (avoid blank flicker)
        self._apply_last_logged_cache(issue_keys)
        # Apply cached worklog data then fetch missing
        self._update_ui_from_cache(issue_keys)
        self._start_worklog_fetch(issue_keys, force_refresh=True)
        # Refresh daily total if safe
        if self._startup_complete:
            self._refresh_daily_total()
        # Determine selection
        select_key = None
        if preferred_key and preferred_key in issue_keys:
            select_key = preferred_key
        elif self.cfg.last_issue_key in issue_keys:
            select_key = self.cfg.last_issue_key
        else:
            select_key = issue_keys[0]
        # Find summary for selected key
        summary = ""
        for issue in issues:
            if issue.get("key") == select_key:
                summary = issue.get("fields", {}).get("summary", "")
                break
        self.on_issue_selected(select_key, summary)
        self._select_issue_in_list(select_key)

    def _update_parent_label(self, issue_key: str):
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
        if display_text:
            if ":" in display_text:
                parts = display_text.split(":", 1)
                epic_key = epic_key or parts[0].strip()
                epic_summary = parts[1].strip()
            else:
                epic_key = epic_key or display_text.strip()
        # If we have only key but no summary, attempt fetch
        if epic_key and not epic_summary and self.jira:
            try:
                jql = f'key = "{epic_key}"'
                res = self.jira._search_jql(jql=jql, max_results=1, fields=["summary"]) or []
                if res:
                    epic_summary = (res[0].get("fields", {}) or {}).get("summary", "") or ""
            except Exception:
                pass
        # Build label
        if epic_key:
            if self.cfg.jira_base_url:
                epic_url = f"{self.cfg.jira_base_url}/browse/{epic_key}"
                if epic_summary:
                    short = epic_summary[:80] + ("..." if len(epic_summary) > 80 else "")
                    self.parent_label.setText(f'<span style="color:#777">Parent:</span> <a href="{epic_url}">{epic_key}</a> — {short}')
                else:
                    self.parent_label.setText(f'<span style="color:#777">Parent:</span> <a href="{epic_url}">{epic_key}</a>')
            else:
                if epic_summary:
                    self.parent_label.setText(f"Parent: {epic_key} — {epic_summary}")
                else:
                    self.parent_label.setText(f"Parent: {epic_key}")
        else:
            self.parent_label.setText("")

    def _apply_last_logged_cache(self, issue_keys: List[str]):
        """Fill last logged column from cache for provided issue keys."""
        if not self._last_logged_cache:
            return
        now = dt.datetime.now().timestamp()
        for key in issue_keys:
            entry = self._last_logged_cache.get(key)
            if not entry:
                continue
            date_str, ts = entry
            # Recompute relative time (could have changed day boundary)
            rel = self._format_relative_time(date_str)
            self.issue_list.update_last_logged(key, rel)

    @staticmethod
    def _format_secs(secs: int) -> str:
        if secs <= 0:
            return "0m"
        hours, rem = divmod(secs, 3600)
        mins = rem // 60
        parts = []
        if hours:
            parts.append(f"{hours}h")
        if mins:
            parts.append(f"{mins}m")
        if not parts:
            parts.append("<1m")
        return " ".join(parts)

    @staticmethod
    def _format_relative_time(date_str: str) -> str:
        """Format a date string as relative time ago (e.g. '2 days ago')."""
        if not date_str:
            return ""
        
        try:
            # Parse YYYY-MM-DD format
            logged_date = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
            today = dt.date.today()
            diff = today - logged_date
            
            if diff.days == 0:
                return "Today"
            elif diff.days == 1:
                return "Yesterday"
            elif diff.days < 7:
                return f"{diff.days} days ago"
            elif diff.days < 30:
                weeks = diff.days // 7
                return f"{weeks} week{'s' if weeks > 1 else ''} ago"
            elif diff.days < 365:
                months = diff.days // 30
                return f"{months} month{'s' if months > 1 else ''} ago"
            else:
                years = diff.days // 365
                return f"{years} year{'s' if years > 1 else ''} ago"
        except Exception:
            return date_str


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
