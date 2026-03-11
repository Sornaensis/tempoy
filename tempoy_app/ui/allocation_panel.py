from __future__ import annotations

import html
from dataclasses import replace

from PySide6 import QtCore, QtWidgets

from tempoy_app.formatting import format_duration_hms, format_seconds, parse_duration_hms
from tempoy_app.models import AllocationRow, AllocationState
from tempoy_app.services.allocation_service import AllocationService


class AllocationRowWidget(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(str, int)
    lockChanged = QtCore.Signal(str, bool)
    timeEditRequested = QtCore.Signal(str, str)
    removeRequested = QtCore.Signal(str)

    def __init__(self, row: AllocationRow, total_units: int, parent=None):
        super().__init__(parent)
        self.issue_key = row.issue_key
        self.total_units = total_units
        self._building = False

        self.issue_label = QtWidgets.QLabel(f"{row.issue_key} — {row.summary}")
        self.issue_label.setTextFormat(QtCore.Qt.RichText)
        self.issue_label.setOpenExternalLinks(True)
        self.issue_label.setWordWrap(True)
        self.issue_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.parent_label = QtWidgets.QLabel("")
        self.parent_label.setTextFormat(QtCore.Qt.RichText)
        self.parent_label.setOpenExternalLinks(True)
        self.parent_label.setWordWrap(True)
        self.parent_label.setStyleSheet("QLabel { color: #555; }")
        self.parent_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.lock_checkbox = QtWidgets.QCheckBox("Lock")
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, total_units)
        self.percent_label = QtWidgets.QLabel()
        self.duration_label = QtWidgets.QLabel()
        self.duration_label.setTextFormat(QtCore.Qt.RichText)
        self.duration_label.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        self.duration_label.setOpenExternalLinks(False)
        self.duration_label.setCursor(QtCore.Qt.PointingHandCursor)
        self.duration_editor = QtWidgets.QLineEdit()
        self.duration_editor.setVisible(False)
        self.duration_editor.setMinimumWidth(110)
        self._duration_edit_canceled = False
        self.total_label = QtWidgets.QLabel()
        self.remove_button = QtWidgets.QToolButton()
        self.remove_button.setText("✕")
        self.remove_button.setToolTip("Remove ticket from allocation")
        self.separator = QtWidgets.QFrame()
        self.separator.setFrameShape(QtWidgets.QFrame.HLine)
        self.separator.setFrameShadow(QtWidgets.QFrame.Sunken)

        issue_info_row = QtWidgets.QVBoxLayout()
        issue_info_row.setContentsMargins(0, 0, 0, 0)
        issue_info_row.setSpacing(2)
        issue_info_row.addWidget(self.issue_label)
        issue_info_row.addWidget(self.parent_label)

        issue_info_widget = QtWidgets.QWidget()
        issue_info_widget.setLayout(issue_info_row)

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(issue_info_widget, 1)
        top_row.addWidget(self.lock_checkbox)
        top_row.addWidget(self.percent_label)
        top_row.addWidget(self.duration_label)
        top_row.addWidget(self.duration_editor)
        top_row.addWidget(self.total_label)
        top_row.addWidget(self.remove_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top_row)
        layout.addWidget(self.slider)
        layout.addWidget(self.separator)

        self.slider.valueChanged.connect(self._on_slider_changed)
        self.lock_checkbox.toggled.connect(self._on_lock_toggled)
        self.duration_label.linkActivated.connect(lambda _=None: self._begin_duration_edit())
        self.duration_editor.returnPressed.connect(self._commit_duration_edit)
        self.duration_editor.editingFinished.connect(self._finish_duration_edit)
        self.duration_editor.installEventFilter(self)
        self.remove_button.clicked.connect(lambda: self.removeRequested.emit(self.issue_key))

        self.update_from_row(row, 0)

    def _on_slider_changed(self, value: int):
        if self._building:
            return
        self.valueChanged.emit(self.issue_key, value)

    def _on_lock_toggled(self, locked: bool):
        if self._building:
            return
        self.lockChanged.emit(self.issue_key, locked)

    def _begin_duration_edit(self):
        if self._building:
            return
        self._duration_edit_canceled = False
        self.duration_editor.setText(self.duration_editor.property("durationText") or "")
        self.duration_label.setVisible(False)
        self.duration_editor.setVisible(True)
        self.duration_editor.setFocus()
        self.duration_editor.selectAll()

    def _commit_duration_edit(self):
        self.timeEditRequested.emit(self.issue_key, self.duration_editor.text().strip())

    def _finish_duration_edit(self):
        if self._duration_edit_canceled:
            self._duration_edit_canceled = False
            self.restore_duration_display()
            return
        if self.duration_editor.isVisible():
            self.duration_editor.setVisible(False)
            self.duration_label.setVisible(True)

    def restore_duration_display(self):
        self.duration_editor.blockSignals(True)
        self.duration_editor.setVisible(False)
        self.duration_label.setVisible(True)
        self.duration_editor.blockSignals(False)

    def eventFilter(self, watched, event):
        if watched is self.duration_editor and event.type() == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Escape:
                self._duration_edit_canceled = True
                self.duration_editor.setText(self.duration_editor.property("durationText") or "")
                self.duration_editor.clearFocus()
                return True
        return super().eventFilter(watched, event)

    def set_separator_visible(self, visible: bool):
        self.separator.setVisible(visible)

    @staticmethod
    def _render_issue_text(
        row: AllocationRow,
        *,
        jira_base_url: str,
    ) -> str:
        summary = html.escape((row.summary or "").strip())
        issue_key = html.escape(row.issue_key)
        if jira_base_url and row.issue_key:
            issue_url = html.escape(f"{jira_base_url}/browse/{row.issue_key}", quote=True)
            issue_part = f'<span style="color:#777">Issue:</span> <a href="{issue_url}">{issue_key}</a>'
        else:
            issue_part = f'<span style="color:#777">Issue:</span> {issue_key}'
        if summary:
            issue_part = f"{issue_part} — {summary}"

        return issue_part

    @staticmethod
    def _render_parent_text(*, jira_base_url: str, parent_key: str, parent_summary: str) -> str:

        parent_key = (parent_key or "").strip()
        parent_summary = (parent_summary or "").strip()
        if not parent_key:
            return ""

        escaped_parent_key = html.escape(parent_key)
        if jira_base_url:
            parent_url = html.escape(f"{jira_base_url}/browse/{parent_key}", quote=True)
            parent_part = f'<span style="color:#777">Parent:</span> <a href="{parent_url}">{escaped_parent_key}</a>'
        else:
            parent_part = f"<span style=\"color:#777\">Parent:</span> {escaped_parent_key}"
        if parent_summary:
            parent_part = f"{parent_part} — {html.escape(parent_summary)}"
        return parent_part

    def update_from_row(
        self,
        row: AllocationRow,
        duration_seconds: int,
        *,
        jira_base_url: str = "",
        parent_key: str = "",
        parent_summary: str = "",
        total_logged_seconds: int = 0,
    ):
        self._building = True
        self.issue_label.setText(
            self._render_issue_text(
                row,
                jira_base_url=jira_base_url,
            )
        )
        parent_text = self._render_parent_text(
            jira_base_url=jira_base_url,
            parent_key=parent_key,
            parent_summary=parent_summary,
        )
        self.parent_label.setVisible(bool(parent_text))
        self.parent_label.setText(parent_text)
        self.slider.setValue(row.allocation_units)
        self.lock_checkbox.setChecked(row.locked)
        self.percent_label.setText(f"{row.allocation_units / self.total_units:.1%}")
        hours, remainder = divmod(duration_seconds, 3600)
        minutes = remainder // 60
        total_logged_text = format_seconds(total_logged_seconds)
        editable_duration = format_duration_hms(duration_seconds)
        self.duration_label.setText(f'<a href="edit">{editable_duration}</a>')
        self.duration_editor.setText(editable_duration)
        self.duration_editor.setProperty("durationText", editable_duration)
        self.total_label.setText(f"/ {total_logged_text} total")
        self.restore_duration_display()
        self._building = False


class AllocationPanel(QtWidgets.QGroupBox):
    addSelectedIssueRequested = QtCore.Signal()
    submitRequested = QtCore.Signal(object)
    stateChanged = QtCore.Signal(object)

    def __init__(self, allocation_service: AllocationService, daily_time_seconds: int, parent=None):
        super().__init__("Daily Allocation", parent)
        self.service = allocation_service
        self.daily_time_seconds = max(0, int(daily_time_seconds))
        self.state = AllocationState(total_units=self.service.TOTAL_UNITS, rows=[])
        self.remaining_seconds: int | None = None
        self.allocatable_seconds: int | None = None
        self.jira_base_url: str = ""
        self.issue_context: dict[str, dict[str, object]] = {}
        self._row_widgets: dict[str, AllocationRowWidget] = {}

        self.info_label = QtWidgets.QLabel()
        self.empty_state_label = QtWidgets.QLabel("No tickets in today's allocation yet. Select an issue above, then add it here.")
        self.empty_state_label.setWordWrap(True)
        self.add_button = QtWidgets.QPushButton("Add selected issue")
        self.equalize_button = QtWidgets.QPushButton("Equalize")
        self.reset_button = QtWidgets.QPushButton("Reset")
        self.clear_button = QtWidgets.QPushButton("Clear")
        self.submit_button = QtWidgets.QPushButton("Submit day")
        self.rows_layout = QtWidgets.QVBoxLayout()
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch(1)

        self.rows_container = QtWidgets.QWidget()
        self.rows_container.setLayout(self.rows_layout)

        self.rows_scroll = QtWidgets.QScrollArea()
        self.rows_scroll.setWidgetResizable(True)
        self.rows_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.rows_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.rows_scroll.setWidget(self.rows_container)
        self.rows_scroll.setMinimumHeight(96)
        self.rows_scroll.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(self.add_button)
        button_row.addWidget(self.equalize_button)
        button_row.addWidget(self.reset_button)
        button_row.addWidget(self.clear_button)
        button_row.addStretch(1)
        button_row.addWidget(self.submit_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.info_label)
        layout.addWidget(self.empty_state_label)
        layout.addWidget(self.rows_scroll, 1)
        layout.addLayout(button_row)

        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        self.add_button.clicked.connect(self.addSelectedIssueRequested.emit)
        self.equalize_button.clicked.connect(self.equalize)
        self.reset_button.clicked.connect(self.reset_allocations)
        self.clear_button.clicked.connect(self.clear_allocations)
        self.submit_button.clicked.connect(lambda: self.submitRequested.emit(self.current_state()))

        self._refresh_ui()

    def set_daily_time_seconds(self, seconds: int):
        self.daily_time_seconds = max(0, int(seconds))
        self._refresh_ui()

    def set_remaining_seconds(self, remaining_seconds: int | None):
        self.remaining_seconds = None if remaining_seconds is None else max(0, int(remaining_seconds))
        self.allocatable_seconds = self.remaining_seconds
        self._refresh_ui()

    def set_jira_base_url(self, jira_base_url: str):
        self.jira_base_url = (jira_base_url or "").strip().rstrip("/")
        self._refresh_ui()

    def set_issue_context(
        self,
        issue_key: str,
        *,
        summary: str | None = None,
        parent_key: str = "",
        parent_summary: str = "",
        total_logged_seconds: int | None = None,
    ):
        if not issue_key:
            return
        context = dict(self.issue_context.get(issue_key, {}))
        if summary is not None:
            context["summary"] = summary
            self.state = AllocationState(
                total_units=self.state.total_units,
                rows=[replace(row, summary=summary) if row.issue_key == issue_key else replace(row) for row in self.state.rows],
            )
        context["parent_key"] = parent_key or ""
        context["parent_summary"] = parent_summary or ""
        if total_logged_seconds is not None:
            context["total_logged_seconds"] = max(0, int(total_logged_seconds))
        self.issue_context[issue_key] = context
        self._refresh_ui()

    def _effective_total_seconds(self) -> int:
        if self.allocatable_seconds is not None:
            return max(0, int(self.allocatable_seconds))
        return max(0, int(self.daily_time_seconds))

    def _set_row_duration_and_lock(self, issue_key: str, requested_seconds: int):
        effective_total_seconds = self._effective_total_seconds()
        if effective_total_seconds <= 0:
            requested_units = 0
        else:
            requested_seconds = max(0, min(int(requested_seconds), effective_total_seconds))
            requested_units = int(round((requested_seconds / effective_total_seconds) * self.service.TOTAL_UNITS))
        updated_state = self.service.set_row_units(self.current_state(), issue_key, requested_units)
        rows = []
        for row in updated_state.rows:
            if row.issue_key == issue_key:
                rows.append(replace(row, locked=True))
            else:
                rows.append(replace(row))
        self.state = AllocationState(total_units=self.service.TOTAL_UNITS, rows=rows)
        if not self.service.validate(self.state):
            self.state = self._rebalance_after_structure_change(self.state)
        self._refresh_ui()
        self.stateChanged.emit(self.current_state())

    def current_state(self) -> AllocationState:
        return AllocationState(total_units=self.state.total_units, rows=[replace(row, description="") for row in self.state.rows])

    def add_issue(self, issue_key: str, summary: str):
        if any(row.issue_key == issue_key for row in self.state.rows):
            return
        new_rows = [replace(row) for row in self.current_state().rows]
        new_rows.append(AllocationRow(issue_key=issue_key, summary=summary, allocation_units=0, locked=False, description=""))
        self.state = AllocationState(total_units=self.service.TOTAL_UNITS, rows=new_rows)
        self._rebuild_rows()
        self._refresh_ui()
        self.stateChanged.emit(self.current_state())

    def remove_issue(self, issue_key: str):
        self.state = self.service.remove_row(self.current_state(), issue_key)
        self.issue_context.pop(issue_key, None)
        self._rebuild_rows()
        self._refresh_ui()
        self.stateChanged.emit(self.current_state())

    def equalize(self):
        self.state = self.service.equalize_unlocked(self.current_state())
        self._refresh_ui()
        self.stateChanged.emit(self.current_state())

    def reset_allocations(self):
        rows = [replace(row, allocation_units=0, locked=False) for row in self.current_state().rows]
        self.state = AllocationState(total_units=self.service.TOTAL_UNITS, rows=rows)
        self.state = self._rebalance_after_structure_change(self.state)
        self._refresh_ui()
        self.stateChanged.emit(self.current_state())

    def clear_allocations(self):
        self.state = AllocationState(total_units=self.service.TOTAL_UNITS, rows=[])
        self.issue_context = {}
        self._rebuild_rows()
        self._refresh_ui()
        self.stateChanged.emit(self.current_state())

    def set_state(self, state: AllocationState):
        restored_rows = [replace(row) for row in state.rows]
        self.state = AllocationState(total_units=self.service.TOTAL_UNITS, rows=restored_rows)
        self._rebuild_rows()
        self._refresh_ui()

    def _rebalance_after_structure_change(self, state: AllocationState) -> AllocationState:
        if not state.rows:
            return state
        if not any(not row.locked for row in state.rows):
            unlocked_rows = [replace(row, locked=False) if index == 0 else replace(row) for index, row in enumerate(state.rows)]
            state = AllocationState(total_units=state.total_units, rows=unlocked_rows)
        return self.service.equalize_unlocked(state)

    def _rebuild_rows(self):
        while self.rows_layout.count() > 1:
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._row_widgets = {}
        for row in self.state.rows:
            widget = AllocationRowWidget(row, self.service.TOTAL_UNITS)
            widget.valueChanged.connect(self._on_row_value_changed)
            widget.lockChanged.connect(self._on_row_lock_changed)
            widget.timeEditRequested.connect(self._on_row_time_edit_requested)
            widget.removeRequested.connect(self.remove_issue)
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, widget)
            self._row_widgets[row.issue_key] = widget
        issue_keys = list(self._row_widgets)
        for index, issue_key in enumerate(issue_keys):
            self._row_widgets[issue_key].set_separator_visible(index < len(issue_keys) - 1)

    def _on_row_value_changed(self, issue_key: str, units: int):
        self.state = self.service.set_row_units(self.current_state(), issue_key, units)
        self._refresh_ui()
        self.stateChanged.emit(self.current_state())

    def _on_row_lock_changed(self, issue_key: str, locked: bool):
        rows = []
        for row in self.current_state().rows:
            if row.issue_key == issue_key:
                rows.append(replace(row, locked=locked))
            else:
                rows.append(replace(row))
        self.state = AllocationState(total_units=self.service.TOTAL_UNITS, rows=rows)
        if not self.service.validate(self.state):
            self.state = self._rebalance_after_structure_change(self.state)
        self._refresh_ui()
        self.stateChanged.emit(self.current_state())

    def _on_row_time_edit_requested(self, issue_key: str, text: str):
        parsed_seconds = parse_duration_hms(text)
        widget = self._row_widgets.get(issue_key)
        if parsed_seconds is None:
            if widget is not None:
                widget.restore_duration_display()
            QtWidgets.QMessageBox.warning(self, "Allocation", "Use a duration like 1hr 30m 15s.")
            return
        self._set_row_duration_and_lock(issue_key, parsed_seconds)

    def _refresh_ui(self):
        self.state = self.current_state() if self._row_widgets else self.state
        if set(self._row_widgets) != {row.issue_key for row in self.state.rows}:
            self._rebuild_rows()
        effective_total_seconds = self._effective_total_seconds()
        duration_map = self.service.allocations_to_total_seconds(self.state, effective_total_seconds)
        for row in self.state.rows:
            widget = self._row_widgets.get(row.issue_key)
            if widget is not None:
                context = self.issue_context.get(row.issue_key, {})
                widget.update_from_row(
                    row,
                    duration_map.get(row.issue_key, 0),
                    jira_base_url=self.jira_base_url,
                    parent_key=str(context.get("parent_key", "") or ""),
                    parent_summary=str(context.get("parent_summary", "") or ""),
                    total_logged_seconds=max(0, int(context.get("total_logged_seconds", 0) or 0)),
                )
        allocated_percent = self.state.allocated_units() / self.service.TOTAL_UNITS if self.service.TOTAL_UNITS else 0
        planned_seconds = sum(seconds for seconds in duration_map.values() if seconds > 0)
        status_parts = [
            f"Allocated: {allocated_percent:.1%}",
            f"Day: {format_seconds(self.daily_time_seconds)}",
        ]
        status_parts.append(f"Allocatable: {format_seconds(effective_total_seconds)}")
        if self.remaining_seconds is not None:
            status_parts.append(f"Remaining: {format_seconds(self.remaining_seconds)}")
            if self.remaining_seconds <= 0:
                status_parts.append("Daily limit reached")
            elif planned_seconds > self.remaining_seconds:
                status_parts.append("Reduce allocation to fit remaining time")
        self.info_label.setText(" · ".join(status_parts))
        has_rows = bool(self.state.rows)
        self.empty_state_label.setVisible(not has_rows)
        self.rows_scroll.setVisible(has_rows)
        self.clear_button.setEnabled(has_rows)
        within_remaining = self.remaining_seconds is None or planned_seconds <= self.remaining_seconds
        has_positive_allocatable_time = self.remaining_seconds is None or self.remaining_seconds > 0
        self.submit_button.setEnabled(bool(self.state.rows) and self.service.validate(self.state) and within_remaining and has_positive_allocatable_time)
