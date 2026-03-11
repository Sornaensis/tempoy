from __future__ import annotations

from PySide6 import QtWidgets

from tempoy_app.config import AppConfig

APP_NAME = "Tempoy"


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
        self.daily_time = QtWidgets.QSpinBox()
        self.daily_time.setRange(0, 1440)
        self.daily_time.setValue(self.cfg.daily_time_minutes)
        self.daily_time.setSuffix(" min")
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
        form.addRow("Default time per day", self.daily_time)
        form.addRow("Reminder interval", self.reminder)
        form.addRow(self.always_on_top)

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

    def accept(self):
        self.cfg.jira_base_url = self.jira_url.text().strip()
        self.cfg.jira_email = self.jira_email.text().strip()
        self.cfg.jira_api_token = self.jira_token.text().strip()
        self.cfg.tempo_api_token = self.tempo_token.text().strip()
        self.cfg.daily_time_minutes = int(self.daily_time.value())
        self.cfg.reminder_minutes = int(self.reminder.value())
        self.cfg.always_on_top = bool(self.always_on_top.isChecked())
        super().accept()
