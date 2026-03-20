from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".tempoy")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
CUSTOM_FIELDS_PATH = os.path.join(CONFIG_DIR, "custom_fields.json")
OLD_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".tempo_floater")
OLD_CONFIG_PATH = os.path.join(OLD_CONFIG_DIR, "config.json")
DEFAULT_ISSUE_LIST_COLUMN_WIDTHS = [100, 300, 150, 60, 60, 100]
DEFAULT_COPILOT_API_PORT = 8765
DEFAULT_COPILOT_API_MODE = "read-only"
DEFAULT_COPILOT_SESSION_TTL_SECONDS = 3600
COPILOT_API_MODES = {"read-only", "refine-only", "create-and-refine"}
SUPPORTED_CUSTOM_FIELD_TYPES = {"string", "number", "option", "multi_option", "duration", "labels"}


def _normalize_custom_fields(raw_list: Any) -> List[Dict]:
    if not isinstance(raw_list, list):
        return []
    result: List[Dict] = []
    for i, entry in enumerate(raw_list):
        if not isinstance(entry, dict):
            logger.warning("Custom field entry %d is not a dict, skipping", i)
            continue
        name = str(entry.get("name") or "").strip()
        field_id = str(entry.get("field_id") or "").strip()
        field_type = str(entry.get("type") or "").strip().lower()
        if not name or not field_id or field_type not in SUPPORTED_CUSTOM_FIELD_TYPES:
            logger.warning(
                "Custom field entry %d dropped (name=%r, field_id=%r, type=%r)",
                i, name, field_id, field_type,
            )
            continue
        normalized: Dict[str, Any] = {"name": name, "field_id": field_id, "type": field_type}
        if field_type == "number":
            if "min" in entry:
                normalized["min"] = float(entry["min"])
            if "max" in entry:
                normalized["max"] = float(entry["max"])
        elif field_type in ("option", "multi_option"):
            values = entry.get("allowed_values")
            if isinstance(values, list) and values:
                normalized["allowed_values"] = [str(v) for v in values if str(v).strip()]
        elif field_type == "string":
            if "max_length" in entry:
                normalized["max_length"] = max(1, int(entry["max_length"]))
        elif field_type == "duration":
            if field_id != "timetracking.originalEstimate":
                logger.warning(
                    "Custom field entry %d: duration type only supports field_id "
                    "'timetracking.originalEstimate', got %r — skipping", i, field_id,
                )
                continue
        result.append(normalized)
    return result


def _normalize_string_list(raw_values: object, *, uppercase: bool = False) -> List[str]:
    if not isinstance(raw_values, list):
        return []
    normalized: List[str] = []
    seen = set()
    for raw_value in raw_values:
        value = str(raw_value or "").strip()
        if not value:
            continue
        if uppercase:
            value = value.upper()
        dedupe_key = value.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(value)
    return normalized


@dataclass
class AppConfig:
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    tempo_api_token: str = ""
    daily_time_seconds: int = 28_800
    reminder_enabled: bool = True
    reminder_time: str = "1500"
    always_on_top: bool = True
    last_issue_key: str = ""
    expanded: bool = False
    window_x: int = 100
    window_y: int = 100
    collapsed_width: int = 500
    collapsed_height: int = 120
    expanded_width: int = 840
    expanded_height: int = 420
    expanded_splitter_sizes: List[int] = field(default_factory=lambda: [320, 220])
    search_history: List = field(default_factory=list)
    issue_list_column_widths: List[int] = field(default_factory=lambda: DEFAULT_ISSUE_LIST_COLUMN_WIDTHS.copy())
    allocation_draft: Dict = field(default_factory=lambda: {"rows": []})
    copilot_api_enabled: bool = False
    copilot_api_port: int = DEFAULT_COPILOT_API_PORT
    copilot_api_mode: str = DEFAULT_COPILOT_API_MODE
    copilot_allowed_projects: List[str] = field(default_factory=list)
    copilot_allowed_issue_types: List[str] = field(default_factory=list)
    copilot_require_write_confirmation: bool = True
    copilot_session_token: str | None = None
    copilot_session_expires_at: int | None = None
    copilot_session_ttl_seconds: int = DEFAULT_COPILOT_SESSION_TTL_SECONDS

    def prune_old_history(self, days_back: int = 3) -> None:
        cutoff_time = time.time() - (days_back * 24 * 60 * 60)
        new_hist = []
        for entry in self.search_history:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                _, ts = entry[0], entry[1]
                if ts >= cutoff_time:
                    new_hist.append(entry)
            elif isinstance(entry, dict):
                ts = entry.get("ts")
                if isinstance(ts, (int, float)) and ts >= cutoff_time:
                    new_hist.append(entry)
        self.search_history = new_hist

    def to_dict(self) -> Dict:
        return self.__dict__

    @staticmethod
    def from_dict(data: Dict) -> "AppConfig":
        raw_data = data or {}
        legacy_reminder_minutes = raw_data.get("reminder_minutes") if isinstance(raw_data, dict) else None
        legacy_daily_time_minutes = raw_data.get("daily_time_minutes") if isinstance(raw_data, dict) else None
        cfg = AppConfig()
        cfg.__dict__.update(raw_data)
        if not hasattr(cfg, "search_history") or cfg.search_history is None:
            cfg.search_history = []
        migrated = []
        changed = False
        for entry in cfg.search_history:
            if isinstance(entry, dict):
                migrated.append(entry)
            elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                migrated.append({"type": "search", "term": entry[0], "ts": entry[1]})
                changed = True
        if changed:
            cfg.search_history = migrated
        if not hasattr(cfg, "issue_list_column_widths") or cfg.issue_list_column_widths is None:
            cfg.issue_list_column_widths = DEFAULT_ISSUE_LIST_COLUMN_WIDTHS.copy()
        splitter_sizes = getattr(cfg, "expanded_splitter_sizes", None)
        if not isinstance(splitter_sizes, list) or len(splitter_sizes) != 2:
            cfg.expanded_splitter_sizes = [320, 220]
        else:
            normalized_sizes = []
            for raw_value in splitter_sizes[:2]:
                try:
                    normalized_sizes.append(max(1, int(raw_value)))
                except (TypeError, ValueError):
                    normalized_sizes.append(1)
            cfg.expanded_splitter_sizes = normalized_sizes
        if not hasattr(cfg, "allocation_draft") or not isinstance(cfg.allocation_draft, dict):
            cfg.allocation_draft = {"rows": []}
        if not isinstance(cfg.allocation_draft.get("rows"), list):
            cfg.allocation_draft = {"rows": []}
        cfg.copilot_api_enabled = bool(getattr(cfg, "copilot_api_enabled", False))
        try:
            cfg.copilot_api_port = int(getattr(cfg, "copilot_api_port", DEFAULT_COPILOT_API_PORT))
        except (TypeError, ValueError):
            cfg.copilot_api_port = DEFAULT_COPILOT_API_PORT
        if cfg.copilot_api_port <= 0 or cfg.copilot_api_port > 65535:
            cfg.copilot_api_port = DEFAULT_COPILOT_API_PORT
        raw_mode = str(getattr(cfg, "copilot_api_mode", DEFAULT_COPILOT_API_MODE) or DEFAULT_COPILOT_API_MODE).strip()
        cfg.copilot_api_mode = raw_mode if raw_mode in COPILOT_API_MODES else DEFAULT_COPILOT_API_MODE
        cfg.copilot_allowed_projects = _normalize_string_list(getattr(cfg, "copilot_allowed_projects", []), uppercase=True)
        cfg.copilot_allowed_issue_types = _normalize_string_list(getattr(cfg, "copilot_allowed_issue_types", []))
        cfg.copilot_require_write_confirmation = bool(getattr(cfg, "copilot_require_write_confirmation", True))
        raw_session_token = getattr(cfg, "copilot_session_token", None)
        if raw_session_token is None:
            cfg.copilot_session_token = None
        else:
            session_token = str(raw_session_token).strip()
            cfg.copilot_session_token = session_token or None
        raw_session_expires_at = getattr(cfg, "copilot_session_expires_at", None)
        try:
            cfg.copilot_session_expires_at = None if raw_session_expires_at in {None, ""} else max(0, int(raw_session_expires_at))
        except (TypeError, ValueError):
            cfg.copilot_session_expires_at = None
        try:
            cfg.copilot_session_ttl_seconds = int(getattr(cfg, "copilot_session_ttl_seconds", DEFAULT_COPILOT_SESSION_TTL_SECONDS))
        except (TypeError, ValueError):
            cfg.copilot_session_ttl_seconds = DEFAULT_COPILOT_SESSION_TTL_SECONDS
        if cfg.copilot_session_ttl_seconds <= 0:
            cfg.copilot_session_ttl_seconds = DEFAULT_COPILOT_SESSION_TTL_SECONDS
        if "daily_time_seconds" not in raw_data:
            try:
                cfg.daily_time_seconds = max(0, int(legacy_daily_time_minutes or 480) * 60)
            except (TypeError, ValueError):
                cfg.daily_time_seconds = 28_800
        else:
            try:
                cfg.daily_time_seconds = max(0, int(cfg.daily_time_seconds))
            except (TypeError, ValueError):
                cfg.daily_time_seconds = 28_800
        if "reminder_enabled" not in raw_data:
            try:
                cfg.reminder_enabled = int(legacy_reminder_minutes) > 0
            except (TypeError, ValueError):
                cfg.reminder_enabled = True
        else:
            cfg.reminder_enabled = bool(cfg.reminder_enabled)
        reminder_time = str(getattr(cfg, "reminder_time", "1500") or "1500").strip()
        normalized_digits = "".join(ch for ch in reminder_time if ch.isdigit())
        if len(normalized_digits) != 4:
            normalized_digits = "1500"
        hours = int(normalized_digits[:2])
        minutes = int(normalized_digits[2:])
        if hours > 23 or minutes > 59:
            normalized_digits = "1500"
        cfg.reminder_time = normalized_digits
        cfg.__dict__.pop("daily_time_minutes", None)
        cfg.__dict__.pop("reminder_minutes", None)
        return cfg


class ConfigManager:
    @staticmethod
    def load() -> AppConfig:
        cfg = None
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as file_handle:
                cfg = AppConfig.from_dict(json.load(file_handle))
        elif os.path.exists(OLD_CONFIG_PATH):
            try:
                os.makedirs(CONFIG_DIR, exist_ok=True)
                with open(OLD_CONFIG_PATH, "r", encoding="utf-8") as file_handle:
                    data = file_handle.read()
                tmp_new = CONFIG_PATH + ".tmp_migrate"
                with open(tmp_new, "w", encoding="utf-8") as file_handle:
                    file_handle.write(data)
                os.replace(tmp_new, CONFIG_PATH)
                cfg = AppConfig.from_dict(json.loads(data))
            except Exception:
                try:
                    with open(OLD_CONFIG_PATH, "r", encoding="utf-8") as file_handle:
                        cfg = AppConfig.from_dict(json.load(file_handle))
                except Exception:
                    cfg = AppConfig()
        else:
            cfg = AppConfig()

        cfg.prune_old_history()
        return cfg

    @staticmethod
    def save(cfg: AppConfig) -> None:
        cfg.prune_old_history()
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as file_handle:
            json.dump(cfg.to_dict(), file_handle, indent=2)
        os.replace(tmp, CONFIG_PATH)


class CustomFieldsConfig:
    @staticmethod
    def load() -> List[Dict]:
        if not os.path.exists(CUSTOM_FIELDS_PATH):
            return []
        try:
            with open(CUSTOM_FIELDS_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load custom fields config: %s", exc)
            return []
        raw_list = data.get("custom_fields") if isinstance(data, dict) else data
        return _normalize_custom_fields(raw_list)

    @staticmethod
    def save(fields: List[Dict]) -> None:
        normalized = _normalize_custom_fields(fields)
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CUSTOM_FIELDS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"custom_fields": normalized}, fh, indent=2)
        os.replace(tmp, CUSTOM_FIELDS_PATH)
