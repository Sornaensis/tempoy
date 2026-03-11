from __future__ import annotations

from dataclasses import replace

from PySide6 import QtCore, QtWidgets

from tempoy_app.models import AllocationRow, AllocationState
from tempoy_app.services.allocation_service import AllocationService


class AllocationRowWidget(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(str, int)
    lockChanged = QtCore.Signal(str, bool)
    removeRequested = QtCore.Signal(str)

    def __init__(self, row: AllocationRow, total_units: int, parent=None):
        super().__init__(parent)
        self.issue_key = row.issue_key
        self.total_units = total_units
        self._building = False

        self.issue_label = QtWidgets.QLabel(f"{row.issue_key} — {row.summary}")
        self.lock_checkbox = QtWidgets.QCheckBox("Lock")
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, total_units)
        self.percent_label = QtWidgets.QLabel()
        self.duration_label = QtWidgets.QLabel()
        self.description_edit = QtWidgets.QLineEdit(row.description)
        self.description_edit.setPlaceholderText("Description for this ticket")
        self.remove_button = QtWidgets.QToolButton()
        self.remove_button.setText("✕")
        self.remove_button.setToolTip("Remove ticket from allocation")

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self.issue_label, 1)
        top_row.addWidget(self.lock_checkbox)
        top_row.addWidget(self.percent_label)
        top_row.addWidget(self.duration_label)
        top_row.addWidget(self.remove_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top_row)
        layout.addWidget(self.slider)
        layout.addWidget(self.description_edit)

        self.slider.valueChanged.connect(self._on_slider_changed)
        self.lock_checkbox.toggled.connect(self._on_lock_toggled)
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

    def update_from_row(self, row: AllocationRow, duration_seconds: int):
        self._building = True
        self.issue_label.setText(f"{row.issue_key} — {row.summary}")
        self.slider.setValue(row.allocation_units)
        self.lock_checkbox.setChecked(row.locked)
        self.description_edit.setText(row.description)
        self.percent_label.setText(f"{row.allocation_units / self.total_units:.1%}")
        hours, remainder = divmod(duration_seconds, 3600)
        minutes = remainder // 60
        self.duration_label.setText(f"{hours}h {minutes:02d}m")
        self._building = False


class AllocationPanel(QtWidgets.QGroupBox):
    addSelectedIssueRequested = QtCore.Signal()
    submitRequested = QtCore.Signal(object)

    def __init__(self, allocation_service: AllocationService, daily_time_minutes: int, parent=None):
        super().__init__("Daily Allocation", parent)
        self.service = allocation_service
        self.daily_time_minutes = daily_time_minutes
        self.state = AllocationState(total_units=self.service.TOTAL_UNITS, rows=[])
        self._row_widgets: dict[str, AllocationRowWidget] = {}

        self.info_label = QtWidgets.QLabel()
        self.add_button = QtWidgets.QPushButton("Add selected issue")
        self.equalize_button = QtWidgets.QPushButton("Equalize")
        self.reset_button = QtWidgets.QPushButton("Reset")
        self.submit_button = QtWidgets.QPushButton("Submit day")
        self.rows_layout = QtWidgets.QVBoxLayout()
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch(1)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(self.add_button)
        button_row.addWidget(self.equalize_button)
        button_row.addWidget(self.reset_button)
        button_row.addStretch(1)
        button_row.addWidget(self.submit_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.info_label)
        layout.addLayout(self.rows_layout)
        layout.addLayout(button_row)

        self.add_button.clicked.connect(self.addSelectedIssueRequested.emit)
        self.equalize_button.clicked.connect(self.equalize)
        self.reset_button.clicked.connect(self.reset_allocations)
        self.submit_button.clicked.connect(lambda: self.submitRequested.emit(self.current_state()))

        self._refresh_ui()

    def set_daily_time_minutes(self, minutes: int):
        self.daily_time_minutes = max(0, int(minutes))
        self._refresh_ui()

    def current_state(self) -> AllocationState:
        rows = []
        for row in self.state.rows:
            widget = self._row_widgets[row.issue_key]
            rows.append(replace(row, description=widget.description_edit.text().strip()))
        return AllocationState(total_units=self.state.total_units, rows=rows)

    def add_issue(self, issue_key: str, summary: str):
        if any(row.issue_key == issue_key for row in self.state.rows):
            return
        new_rows = [replace(row) for row in self.current_state().rows]
        new_rows.append(AllocationRow(issue_key=issue_key, summary=summary, allocation_units=0, locked=False, description=""))
        self.state = AllocationState(total_units=self.service.TOTAL_UNITS, rows=new_rows)
        self.state = self._rebalance_after_structure_change(self.state)
        self._rebuild_rows()
        self._refresh_ui()

    def remove_issue(self, issue_key: str):
        new_rows = [replace(row) for row in self.current_state().rows if row.issue_key != issue_key]
        self.state = AllocationState(total_units=self.service.TOTAL_UNITS, rows=new_rows)
        self.state = self._rebalance_after_structure_change(self.state)
        self._rebuild_rows()
        self._refresh_ui()

    def equalize(self):
        self.state = self.service.equalize_unlocked(self.current_state())
        self._refresh_ui()

    def reset_allocations(self):
        rows = [replace(row, allocation_units=0, locked=False) for row in self.current_state().rows]
        self.state = AllocationState(total_units=self.service.TOTAL_UNITS, rows=rows)
        self.state = self._rebalance_after_structure_change(self.state)
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
            widget.removeRequested.connect(self.remove_issue)
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, widget)
            self._row_widgets[row.issue_key] = widget

    def _on_row_value_changed(self, issue_key: str, units: int):
        self.state = self.service.set_row_units(self.current_state(), issue_key, units)
        self._refresh_ui()

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

    def _refresh_ui(self):
        self.state = self.current_state() if self._row_widgets else self.state
        if set(self._row_widgets) != {row.issue_key for row in self.state.rows}:
            self._rebuild_rows()
        duration_map = self.service.allocations_to_seconds(self.state, self.daily_time_minutes)
        for row in self.state.rows:
            widget = self._row_widgets.get(row.issue_key)
            if widget is not None:
                widget.update_from_row(row, duration_map.get(row.issue_key, 0))
        allocated_percent = self.state.allocated_units() / self.service.TOTAL_UNITS if self.service.TOTAL_UNITS else 0
        self.info_label.setText(
            f"Allocated: {allocated_percent:.1%} · Day: {self.daily_time_minutes // 60}h {self.daily_time_minutes % 60:02d}m · Rows: {len(self.state.rows)}"
        )
        self.submit_button.setEnabled(bool(self.state.rows) and self.service.validate(self.state))
