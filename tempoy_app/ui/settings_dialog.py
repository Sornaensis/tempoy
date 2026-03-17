from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

import os
import subprocess
import sys

from tempoy_app.config import AppConfig, CONFIG_DIR, COPILOT_API_MODES, DEFAULT_COPILOT_API_PORT
from tempoy_app.formatting import format_duration_hms, parse_duration_hms

APP_NAME = "Tempoy"


class DurationSpinBox(QtWidgets.QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 24 * 60 * 60)
        self.setSingleStep(60)
        self.setAccelerated(True)

    def textFromValue(self, value: int) -> str:
        return format_duration_hms(value)

    def valueFromText(self, text: str) -> int:
        parsed = parse_duration_hms(text)
        if parsed is None:
            return self.value()
        return max(self.minimum(), min(self.maximum(), parsed))

    def validate(self, text: str, pos: int):
        stripped = (text or "").strip()
        if not stripped:
            return (QtGui.QValidator.Intermediate, text, pos)
        if parse_duration_hms(stripped) is not None:
            return (QtGui.QValidator.Acceptable, text, pos)
        return (QtGui.QValidator.Intermediate, text, pos)

    def stepBy(self, steps: int):
        self.setValue(max(self.minimum(), min(self.maximum(), self.value() + (steps * 60))))


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
        self.daily_time = DurationSpinBox()
        self.daily_time.setValue(self.cfg.daily_time_seconds)
        self.reminder_enabled = QtWidgets.QCheckBox("Enable daily reminder")
        self.reminder_enabled.setChecked(self.cfg.reminder_enabled)
        self.reminder_time = QtWidgets.QTimeEdit()
        self.reminder_time.setDisplayFormat("HHmm'hrs'")
        self.reminder_time.setTime(self._parse_reminder_time(self.cfg.reminder_time))
        self.reminder_time.setEnabled(self.cfg.reminder_enabled)
        self.reminder_time.setToolTip("Reminder time uses your local system time.")
        self.reminder_enabled.toggled.connect(self.reminder_time.setEnabled)
        self.always_on_top = QtWidgets.QCheckBox("Keep window always on top")
        self.always_on_top.setChecked(self.cfg.always_on_top)

        form.addRow("Jira base URL (https://...atlassian.net)", self.jira_url)
        form.addRow("Jira email", self.jira_email)
        form.addRow("Jira API token", self.jira_token)
        form.addRow("Tempo API token", self.tempo_token)
        form.addRow("Default time per day", self.daily_time)
        form.addRow("Daily reminder", self.reminder_enabled)
        form.addRow("Reminder time (local)", self.reminder_time)
        form.addRow(self.always_on_top)

        # --- MCP API section ---
        mcp_separator = QtWidgets.QFrame()
        mcp_separator.setFrameShape(QtWidgets.QFrame.HLine)
        mcp_separator.setFrameShadow(QtWidgets.QFrame.Sunken)
        form.addRow(mcp_separator)

        mcp_label = QtWidgets.QLabel("<b>MCP API</b>")
        form.addRow(mcp_label)

        self.copilot_enabled = QtWidgets.QCheckBox("Enable MCP API")
        self.copilot_enabled.setChecked(self.cfg.copilot_api_enabled)
        self.copilot_enabled.setToolTip(
            "Start a local HTTP API that allows MCP clients and AI agents to interact with Tempoy."
        )
        form.addRow(self.copilot_enabled)

        self.copilot_port = QtWidgets.QSpinBox()
        self.copilot_port.setRange(1024, 65535)
        self.copilot_port.setValue(self.cfg.copilot_api_port)
        self.copilot_port.setToolTip(f"TCP port for the MCP API (default: {DEFAULT_COPILOT_API_PORT}).")
        self.copilot_port.setEnabled(self.cfg.copilot_api_enabled)
        form.addRow("API port", self.copilot_port)

        self.copilot_mode = QtWidgets.QComboBox()
        mode_labels = [
            ("read-only", "Read-only"),
            ("refine-only", "Read + Refine"),
            ("create-and-refine", "Read + Refine + Create"),
        ]
        for value, label in mode_labels:
            self.copilot_mode.addItem(label, value)
        current_mode_index = next(
            (i for i, (v, _) in enumerate(mode_labels) if v == self.cfg.copilot_api_mode), 0
        )
        self.copilot_mode.setCurrentIndex(current_mode_index)
        self.copilot_mode.setToolTip("Controls what agents are allowed to do through the API.")
        self.copilot_mode.setEnabled(self.cfg.copilot_api_enabled)
        form.addRow("API mode", self.copilot_mode)

        self.copilot_enabled.toggled.connect(self.copilot_port.setEnabled)
        self.copilot_enabled.toggled.connect(self.copilot_mode.setEnabled)

        buttons = QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        self.button_box = QtWidgets.QDialogButtonBox(buttons)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.button_box)

        help_label = QtWidgets.QLabel(
            '<a href="https://id.atlassian.com/manage-profile/security/api-tokens">Create Jira API token</a> · '
            '<a href="https://help.tempo.io/timesheets/latest/using-rest-api-integrations">Tempo API token</a>'
        )
        help_label.setOpenExternalLinks(True)
        layout.addWidget(help_label)

        open_config_btn = QtWidgets.QPushButton("Open Config Directory")
        open_config_btn.setToolTip(CONFIG_DIR)
        open_config_btn.clicked.connect(self._open_config_directory)
        layout.addWidget(open_config_btn)

    @staticmethod
    def _parse_reminder_time(value: str) -> QtCore.QTime:
        raw_value = str(value or "1500").strip()
        parsed = QtCore.QTime.fromString(raw_value, "HHmm")
        if not parsed.isValid():
            parsed = QtCore.QTime(15, 0)
        return parsed

    def accept(self):
        self.cfg.jira_base_url = self.jira_url.text().strip()
        self.cfg.jira_email = self.jira_email.text().strip()
        self.cfg.jira_api_token = self.jira_token.text().strip()
        self.cfg.tempo_api_token = self.tempo_token.text().strip()
        self.cfg.daily_time_seconds = int(self.daily_time.value())
        self.cfg.reminder_enabled = bool(self.reminder_enabled.isChecked())
        self.cfg.reminder_time = self.reminder_time.time().toString("HHmm")
        self.cfg.always_on_top = bool(self.always_on_top.isChecked())
        self.cfg.copilot_api_enabled = bool(self.copilot_enabled.isChecked())
        self.cfg.copilot_api_port = int(self.copilot_port.value())
        self.cfg.copilot_api_mode = str(self.copilot_mode.currentData())
        super().accept()

    @staticmethod
    def _open_config_directory():
        path = os.path.realpath(CONFIG_DIR)
        os.makedirs(path, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
