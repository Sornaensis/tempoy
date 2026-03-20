from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from PySide6 import QtCore, QtWidgets

from tempoy_app.config import CustomFieldsConfig, SUPPORTED_CUSTOM_FIELD_TYPES, _normalize_custom_fields

logger = logging.getLogger(__name__)

# Mapping from Jira schema type strings to our supported types.
_JIRA_SCHEMA_TO_TYPE: Dict[str, str] = {
    "string": "string",
    "number": "number",
    "option": "option",
    "option-with-child": "option",
    "team": "option",
    "user": "option",
    "priority": "option",
    "resolution": "option",
    "security": "option",
    "version": "option",
    "array:option": "multi_option",
    "array:string": "labels",
    "array:version": "multi_option",
    "array:user": "multi_option",
    "array:group": "multi_option",
    "array:component": "multi_option",
}

# Jira custom type keys (the part after the last ':') that indicate
# an option-like field even when schema.type doesn't say "option".
_CUSTOM_OPTION_TYPES: set = {
    "select", "radiobuttons", "cascadingselect",
    "atlassian-team", "team",
}
_CUSTOM_MULTI_OPTION_TYPES: set = {
    "multiselect", "multicheckboxes",
}

# Friendly display labels for our types.
_TYPE_LABELS: Dict[str, str] = {
    "string": "String",
    "number": "Number",
    "option": "Select (single)",
    "multi_option": "Select (multi)",
    "duration": "Duration",
    "labels": "Labels",
}


def _guess_type_from_jira_field(field: Dict[str, Any]) -> str:
    """Best-effort mapping from a Jira field schema to a Tempoy custom field type."""
    schema = field.get("schema") or {}
    jira_type = str(schema.get("type") or "")
    items = str(schema.get("items") or "")

    if jira_type == "array" and items:
        key = f"array:{items}"
        if key in _JIRA_SCHEMA_TO_TYPE:
            return _JIRA_SCHEMA_TO_TYPE[key]
        return "labels" if items == "string" else "multi_option"

    custom = str(schema.get("custom") or "")
    # Extract the short type key from the full custom type URI
    # e.g. "com.atlassian.jira.plugin.system.customfieldtypes:select" -> "select"
    custom_key = custom.rsplit(":", 1)[-1] if custom else ""
    if custom_key in _CUSTOM_OPTION_TYPES:
        return "option"
    if custom_key in _CUSTOM_MULTI_OPTION_TYPES:
        return "multi_option"
    if "float" in custom or jira_type == "number":
        return "number"

    return _JIRA_SCHEMA_TO_TYPE.get(jira_type, "string")


def _format_type_confidence(field: Dict[str, Any]) -> str:
    """Return a display string showing the detected Tempoy type and what Jira schema it came from."""
    schema = field.get("schema") or {}
    custom = str(schema.get("custom") or "")
    jira_type = str(schema.get("type") or "unknown")
    source = custom.rsplit(":", 1)[-1] if custom else jira_type
    detected = _guess_type_from_jira_field(field)
    label = _TYPE_LABELS.get(detected, detected)
    return f"{label}  (jira: {source})"


class _FieldLoaderSignals(QtCore.QObject):
    finished = QtCore.Signal(list)
    error = QtCore.Signal(str)


class CustomFieldPickerDialog(QtWidgets.QDialog):
    """Dialog that fetches custom fields from Jira and lets the user pick which ones to configure."""

    def __init__(
        self,
        jira_client_factory: Callable,
        *,
        existing_field_ids: Optional[set] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Add Custom Fields")
        self.setMinimumSize(680, 480)
        self._jira_client_factory = jira_client_factory
        self._existing_field_ids = existing_field_ids or set()
        self._all_fields: List[Dict[str, Any]] = []
        self._selected_entries: List[Dict[str, Any]] = []

        self._signals = _FieldLoaderSignals()
        self._signals.finished.connect(self._on_fields_loaded)
        self._signals.error.connect(self._on_load_error)

        layout = QtWidgets.QVBoxLayout(self)

        # Filter bar
        filter_row = QtWidgets.QHBoxLayout()
        filter_row.addWidget(QtWidgets.QLabel("Filter:"))
        self._filter_input = QtWidgets.QLineEdit()
        self._filter_input.setPlaceholderText("Type to filter fields by name or ID…")
        self._filter_input.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._filter_input)
        layout.addLayout(filter_row)

        # Field table
        self._table = QtWidgets.QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["", "Name", "Field ID", "Detected Type"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Fixed)
        self._table.setColumnWidth(0, 30)
        self._table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        # Status label
        self._status_label = QtWidgets.QLabel("Loading fields from Jira…")
        layout.addWidget(self._status_label)

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        self._btn_add = QtWidgets.QPushButton("Add Selected")
        self._btn_add.setEnabled(False)
        self._btn_add.clicked.connect(self._on_add_clicked)
        btn_layout.addWidget(self._btn_add)
        self._btn_cancel = QtWidgets.QPushButton("Cancel")
        self._btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self._btn_cancel)
        layout.addLayout(btn_layout)

        # Start loading fields in background
        self._load_fields()

    def _load_fields(self) -> None:
        def _worker():
            try:
                jira = self._jira_client_factory()
                fields = jira.get_all_fields()
                self._signals.finished.emit(fields)
            except Exception as exc:
                logger.warning("Failed to fetch Jira fields: %s", exc)
                self._signals.error.emit(str(exc))

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _on_fields_loaded(self, fields: list) -> None:
        logger.info("Loaded %d total fields from Jira", len(fields))
        custom_fields = [
            f for f in fields
            if isinstance(f, dict) and f.get("custom", False)
        ]
        custom_fields.sort(key=lambda f: str(f.get("name") or "").lower())
        self._all_fields = custom_fields
        for f in custom_fields:
            schema = f.get("schema") or {}
            logger.info(
                "  field: id=%s name=%r schema.type=%s schema.custom=%s schema.items=%s -> detected=%s",
                f.get("id"), f.get("name"),
                schema.get("type"), schema.get("custom"), schema.get("items"),
                _guess_type_from_jira_field(f),
            )
        self._populate_table(custom_fields)
        count = len(custom_fields)
        self._status_label.setText(f"{count} custom field{'s' if count != 1 else ''} found.")
        self._btn_add.setEnabled(True)

    def _on_load_error(self, error_msg: str) -> None:
        self._status_label.setText(f"Failed to load fields: {error_msg}")

    def _populate_table(self, fields: List[Dict[str, Any]]) -> None:
        self._table.setRowCount(len(fields))
        for row, field in enumerate(fields):
            field_id = str(field.get("id") or field.get("key") or "")
            name = str(field.get("name") or "")
            type_display = _format_type_confidence(field)

            # Checkbox
            cb = QtWidgets.QCheckBox()
            already_configured = field_id in self._existing_field_ids
            if already_configured:
                cb.setEnabled(False)
                cb.setToolTip("Already configured")
            cb_widget = QtWidgets.QWidget()
            cb_layout = QtWidgets.QHBoxLayout(cb_widget)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(QtCore.Qt.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self._table.setCellWidget(row, 0, cb_widget)

            name_item = QtWidgets.QTableWidgetItem(name)
            if already_configured:
                name_item.setForeground(QtCore.Qt.gray)
            self._table.setItem(row, 1, name_item)
            self._table.setItem(row, 2, QtWidgets.QTableWidgetItem(field_id))
            self._table.setItem(row, 3, QtWidgets.QTableWidgetItem(type_display))

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self._table.rowCount()):
            name = (self._table.item(row, 1).text() or "").lower()
            field_id = (self._table.item(row, 2).text() or "").lower()
            visible = not needle or needle in name or needle in field_id
            self._table.setRowHidden(row, not visible)

    def _on_add_clicked(self) -> None:
        selected: List[Dict[str, Any]] = []
        for row in range(self._table.rowCount()):
            cb_widget = self._table.cellWidget(row, 0)
            cb = cb_widget.findChild(QtWidgets.QCheckBox) if cb_widget else None
            if cb and cb.isEnabled() and cb.isChecked():
                field_id = self._table.item(row, 2).text()
                name = self._table.item(row, 1).text()
                orig = next((f for f in self._all_fields
                             if str(f.get("id") or f.get("key") or "") == field_id), {})
                guessed_type = _guess_type_from_jira_field(orig)
                logger.info(
                    "Selected field: name=%r field_id=%s detected_type=%s schema=%s",
                    name, field_id, guessed_type,
                    (orig.get("schema") or {}) if orig else "(not found in _all_fields)",
                )
                entry: Dict[str, Any] = {
                    "name": name,
                    "field_id": field_id,
                    "type": guessed_type,
                }
                selected.append(entry)

        if not selected:
            QtWidgets.QMessageBox.information(self, "No Selection", "Please check at least one field to add.")
            return

        # Fetch allowed values for option/multi_option fields
        option_entries = [e for e in selected if e["type"] in ("option", "multi_option")]
        if option_entries:
            self._status_label.setText("Fetching allowed values for select fields…")
            self._btn_add.setEnabled(False)
            QtWidgets.QApplication.processEvents()
            try:
                jira = self._jira_client_factory()
                for entry in option_entries:
                    logger.info(
                        "Fetching allowed values for %s (%s)",
                        entry["name"], entry["field_id"],
                    )
                    values = jira.get_field_options(entry["field_id"])
                    if values:
                        logger.info(
                            "Found %d allowed values for %s: %s",
                            len(values), entry["name"],
                            values[:5] if len(values) > 5 else values,
                        )
                        entry["allowed_values"] = values
                    else:
                        logger.info(
                            "No allowed values found for %s (%s)",
                            entry["name"], entry["field_id"],
                        )
            except Exception as exc:
                logger.warning("Failed to fetch field options: %s", exc)

        self._selected_entries = selected
        self.accept()

    def get_selected_entries(self) -> List[Dict[str, Any]]:
        return list(self._selected_entries)


class CustomFieldEditDialog(QtWidgets.QDialog):
    """Edit the type and constraints of a single custom field definition."""

    _TYPE_OPTIONS = list(_TYPE_LABELS.items())

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Custom Field — {entry.get('name', '')}")
        self.setMinimumWidth(400)
        self._entry = dict(entry)

        form = QtWidgets.QFormLayout(self)

        form.addRow("Name:", QtWidgets.QLabel(str(entry.get("name", ""))))
        form.addRow("Field ID:", QtWidgets.QLabel(str(entry.get("field_id", ""))))

        self._type_combo = QtWidgets.QComboBox()
        for value, label in self._TYPE_OPTIONS:
            self._type_combo.addItem(label, value)
        current_type = str(entry.get("type", "string"))
        idx = next((i for i, (v, _) in enumerate(self._TYPE_OPTIONS) if v == current_type), 0)
        self._type_combo.setCurrentIndex(idx)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("Type:", self._type_combo)

        self._constraints_group = QtWidgets.QGroupBox("Constraints")
        constraints_layout = QtWidgets.QFormLayout(self._constraints_group)

        self._min_spin = QtWidgets.QDoubleSpinBox()
        self._min_spin.setRange(-1e9, 1e9)
        self._min_spin.setDecimals(2)
        self._min_spin.setSpecialValueText("(none)")
        constraints_layout.addRow("Min:", self._min_spin)

        self._max_spin = QtWidgets.QDoubleSpinBox()
        self._max_spin.setRange(-1e9, 1e9)
        self._max_spin.setDecimals(2)
        self._max_spin.setSpecialValueText("(none)")
        constraints_layout.addRow("Max:", self._max_spin)

        self._max_length_spin = QtWidgets.QSpinBox()
        self._max_length_spin.setRange(0, 100_000)
        self._max_length_spin.setSpecialValueText("(none)")
        constraints_layout.addRow("Max length:", self._max_length_spin)

        self._allowed_values_edit = QtWidgets.QLineEdit()
        self._allowed_values_edit.setPlaceholderText("Comma-separated values (optional)")
        constraints_layout.addRow("Allowed values:", self._allowed_values_edit)

        form.addRow(self._constraints_group)

        if entry.get("min") is not None:
            self._min_spin.setValue(float(entry["min"]))
        else:
            self._min_spin.setValue(self._min_spin.minimum())
        if entry.get("max") is not None:
            self._max_spin.setValue(float(entry["max"]))
        else:
            self._max_spin.setValue(self._max_spin.minimum())
        if entry.get("max_length") is not None:
            self._max_length_spin.setValue(int(entry["max_length"]))
        else:
            self._max_length_spin.setValue(0)
        av = entry.get("allowed_values")
        if isinstance(av, list) and av:
            self._allowed_values_edit.setText(", ".join(str(v) for v in av))

        self._on_type_changed()

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_type_changed(self) -> None:
        t = self._type_combo.currentData()
        is_number = t == "number"
        is_string = t == "string"
        is_option = t in ("option", "multi_option")
        self._min_spin.setEnabled(is_number)
        self._max_spin.setEnabled(is_number)
        self._max_length_spin.setEnabled(is_string)
        self._allowed_values_edit.setEnabled(is_option)

    def get_entry(self) -> dict:
        result = dict(self._entry)
        result["type"] = self._type_combo.currentData()

        for key in ("min", "max", "max_length", "allowed_values"):
            result.pop(key, None)

        t = result["type"]
        if t == "number":
            if self._min_spin.value() > self._min_spin.minimum():
                result["min"] = self._min_spin.value()
            if self._max_spin.value() > self._max_spin.minimum():
                result["max"] = self._max_spin.value()
        elif t == "string":
            val = self._max_length_spin.value()
            if val > 0:
                result["max_length"] = val
        elif t in ("option", "multi_option"):
            raw = self._allowed_values_edit.text().strip()
            if raw:
                values = [v.strip() for v in raw.split(",") if v.strip()]
                if values:
                    result["allowed_values"] = values

        if t == "duration":
            result["field_id"] = "timetracking.originalEstimate"

        return result


class CustomFieldsDialog(QtWidgets.QDialog):
    """Standalone dialog for managing MCP custom field configuration."""

    def __init__(
        self,
        *,
        jira_client_factory: Optional[Callable] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("MCP Custom Fields")
        self.setMinimumSize(600, 400)
        self._jira_client_factory = jira_client_factory
        self._custom_fields: List[Dict[str, Any]] = CustomFieldsConfig.load()

        layout = QtWidgets.QVBoxLayout(self)

        # Description
        desc = QtWidgets.QLabel(
            "Configure which Jira custom fields can be read and written by MCP agents. "
            "Fields are auto-detected from Jira when adding, but you can edit the type "
            "and constraints for each field."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Table
        self._table = QtWidgets.QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Name", "Field ID", "Type", "Constraints"])
        self._table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.doubleClicked.connect(self._on_edit_field)
        layout.addWidget(self._table)
        self._refresh_table()

        # Button rows
        btn_row1 = QtWidgets.QHBoxLayout()
        self._btn_add = QtWidgets.QPushButton("Add from Jira…")
        self._btn_add.setToolTip("Fetch custom fields from Jira and pick which ones to configure.")
        self._btn_add.setEnabled(jira_client_factory is not None)
        self._btn_add.clicked.connect(self._on_add_fields)
        btn_row1.addWidget(self._btn_add)

        self._btn_edit = QtWidgets.QPushButton("Edit…")
        self._btn_edit.setToolTip("Edit type and constraints for the selected field.")
        self._btn_edit.clicked.connect(self._on_edit_field)
        btn_row1.addWidget(self._btn_edit)

        self._btn_remove = QtWidgets.QPushButton("Remove")
        self._btn_remove.setToolTip("Remove the selected field(s) from the configuration.")
        self._btn_remove.clicked.connect(self._on_remove_fields)
        btn_row1.addWidget(self._btn_remove)

        btn_row1.addStretch()

        self._btn_copy = QtWidgets.QPushButton("Copy Config")
        self._btn_copy.setToolTip("Copy custom fields JSON to clipboard for sharing with team.")
        self._btn_copy.clicked.connect(self._on_copy)
        btn_row1.addWidget(self._btn_copy)

        self._btn_paste = QtWidgets.QPushButton("Paste Config")
        self._btn_paste.setToolTip("Paste a custom fields JSON config from clipboard.")
        self._btn_paste.clicked.connect(self._on_paste)
        btn_row1.addWidget(self._btn_paste)

        layout.addLayout(btn_row1)

        if jira_client_factory is None:
            hint = QtWidgets.QLabel(
                "<i>Connect to Jira first (configure credentials in Settings) "
                "to add fields from your instance. You can still paste a config.</i>"
            )
            hint.setWordWrap(True)
            layout.addWidget(hint)

        # OK / Cancel
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _refresh_table(self) -> None:
        self._table.setRowCount(len(self._custom_fields))
        for row, entry in enumerate(self._custom_fields):
            self._table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(entry.get("name", ""))))
            self._table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(entry.get("field_id", ""))))
            t = str(entry.get("type", ""))
            self._table.setItem(row, 2, QtWidgets.QTableWidgetItem(_TYPE_LABELS.get(t, t)))
            self._table.setItem(row, 3, QtWidgets.QTableWidgetItem(self._format_constraints(entry)))

    @staticmethod
    def _format_constraints(entry: dict) -> str:
        parts: List[str] = []
        t = entry.get("type", "")
        if t == "number":
            if entry.get("min") is not None:
                parts.append(f"min={entry['min']}")
            if entry.get("max") is not None:
                parts.append(f"max={entry['max']}")
        elif t == "string":
            if entry.get("max_length") is not None:
                parts.append(f"max_length={entry['max_length']}")
        elif t in ("option", "multi_option"):
            av = entry.get("allowed_values")
            if isinstance(av, list) and av:
                if len(av) <= 4:
                    parts.append(", ".join(av))
                else:
                    parts.append(f"{len(av)} values")
        return "; ".join(parts) if parts else "—"

    def _on_add_fields(self) -> None:
        if self._jira_client_factory is None:
            return
        existing_ids = {str(e.get("field_id", "")) for e in self._custom_fields}
        dlg = CustomFieldPickerDialog(
            self._jira_client_factory,
            existing_field_ids=existing_ids,
            parent=self,
        )
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            new_entries = dlg.get_selected_entries()
            if new_entries:
                self._custom_fields.extend(_normalize_custom_fields(new_entries))
                self._refresh_table()
                self._save()

    def _on_edit_field(self) -> None:
        selected_rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        if not selected_rows:
            return
        row = selected_rows[0]
        if row < 0 or row >= len(self._custom_fields):
            return
        entry = self._custom_fields[row]
        dlg = CustomFieldEditDialog(entry, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._custom_fields[row] = dlg.get_entry()
            self._refresh_table()
            self._save()

    def _on_remove_fields(self) -> None:
        selected_rows = sorted({idx.row() for idx in self._table.selectedIndexes()}, reverse=True)
        if not selected_rows:
            return
        for row in selected_rows:
            if 0 <= row < len(self._custom_fields):
                self._custom_fields.pop(row)
        self._refresh_table()
        self._save()

    def _on_copy(self) -> None:
        text = json.dumps(self._custom_fields, indent=2)
        QtWidgets.QApplication.clipboard().setText(text)
        QtWidgets.QMessageBox.information(self, "Copied", "Custom fields config copied to clipboard.")

    def _on_paste(self) -> None:
        text = (QtWidgets.QApplication.clipboard().text() or "").strip()
        if not text:
            QtWidgets.QMessageBox.warning(self, "Empty Clipboard", "Clipboard is empty.")
            return
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid JSON", f"Clipboard does not contain valid JSON:\n{exc}")
            return
        raw_list = data.get("custom_fields") if isinstance(data, dict) else data
        if not isinstance(raw_list, list):
            QtWidgets.QMessageBox.warning(
                self, "Invalid Format",
                "Expected a JSON array of custom field entries, or an object with a 'custom_fields' key.",
            )
            return
        normalized = _normalize_custom_fields(raw_list)
        if not normalized:
            QtWidgets.QMessageBox.warning(
                self, "No Valid Fields",
                f"None of the {len(raw_list)} entries passed validation. "
                f"Each entry needs name, field_id, and a valid type.",
            )
            return
        preview_lines = [f"  • {e['name']} ({e['field_id']}) — {e['type']}" for e in normalized]
        preview_text = "\n".join(preview_lines)
        reply = QtWidgets.QMessageBox.question(
            self, "Paste Custom Fields",
            f"Replace current custom fields with {len(normalized)} entries?\n\n{preview_text}",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self._custom_fields = normalized
            self._refresh_table()
            self._save()

    def _save(self) -> None:
        """Persist current custom fields to disk immediately."""
        CustomFieldsConfig.save(self._custom_fields)
        logger.info("Custom fields config saved (%d fields)", len(self._custom_fields))

    def accept(self) -> None:
        self._save()
        super().accept()
