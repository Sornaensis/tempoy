from __future__ import annotations

from typing import List

from PySide6 import QtCore, QtWidgets

from tempoy_app.models import IssueSnapshot


class IssueList(QtWidgets.QTreeWidget):
    issueSelected = QtCore.Signal(str, str)
    columnResized = QtCore.Signal()

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
        self.header().sectionResized.connect(self._on_column_resized)

    def restore_column_widths(self, widths: List[int]):
        if widths and len(widths) == self.columnCount():
            for index, width in enumerate(widths):
                if width > 0:
                    self.setColumnWidth(index, width)

    def get_column_widths(self) -> List[int]:
        return [self.columnWidth(index) for index in range(self.columnCount())]

    def _on_column_resized(self, logical_index: int, old_size: int, new_size: int):
        self.columnResized.emit()

    @staticmethod
    def _format_seconds(seconds: int) -> str:
        if seconds <= 0:
            return "…"
        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if not parts:
            parts.append("<1m")
        return " ".join(parts)

    def populate_snapshots(self, snapshots: List[IssueSnapshot]):
        self.clear()
        groups: dict[str, QtWidgets.QTreeWidgetItem] = {}
        for snapshot in snapshots:
            status = snapshot.status_name or "Unknown"
            if status not in groups:
                group_item = QtWidgets.QTreeWidgetItem([status, "", "", "", "", ""])
                group_item.setFirstColumnSpanned(True)
                group_item.setFlags(group_item.flags() & ~QtCore.Qt.ItemIsSelectable)
                self.addTopLevelItem(group_item)
                groups[status] = group_item
            parent_item = groups[status]
            child = QtWidgets.QTreeWidgetItem(
                [
                    snapshot.issue_key,
                    snapshot.summary,
                    snapshot.parent_or_epic,
                    self._format_seconds(snapshot.today_seconds),
                    self._format_seconds(snapshot.total_seconds),
                    "",
                ]
            )
            if snapshot.parent_lookup_key:
                child.setData(2, QtCore.Qt.UserRole, snapshot.parent_lookup_key)
            parent_item.addChild(child)
        for index in range(self.topLevelItemCount()):
            self.topLevelItem(index).setExpanded(True)

    @QtCore.Slot(str, str, str)
    def update_worklog(self, issue_key: str, today: str, total: str):
        for parent_index in range(self.topLevelItemCount()):
            parent = self.topLevelItem(parent_index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                if child.text(0) == issue_key:
                    child.setText(3, today)
                    child.setText(4, total)
                    return

    def update_last_logged(self, issue_key: str, last_logged: str):
        for parent_index in range(self.topLevelItemCount()):
            parent = self.topLevelItem(parent_index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                if child.text(0) == issue_key:
                    child.setText(5, last_logged)
                    return

    def _on_item_activated(self, item, col):
        if item and item.parent():
            self.issueSelected.emit(item.text(0), item.text(1))

    def _on_item_clicked(self, item, col):
        if item and item.parent():
            self.issueSelected.emit(item.text(0), item.text(1))
