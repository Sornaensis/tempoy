from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".tempoy")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
OLD_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".tempo_floater")
OLD_CONFIG_PATH = os.path.join(OLD_CONFIG_DIR, "config.json")
DEFAULT_ISSUE_LIST_COLUMN_WIDTHS = [100, 300, 150, 60, 60, 100]


@dataclass
class AppConfig:
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    tempo_api_token: str = ""
    daily_time_minutes: int = 480
    reminder_minutes: int = 60
    always_on_top: bool = True
    last_issue_key: str = ""
    expanded: bool = False
    window_x: int = 100
    window_y: int = 100
    collapsed_width: int = 500
    collapsed_height: int = 120
    expanded_width: int = 840
    expanded_height: int = 420
    search_history: List = field(default_factory=list)
    issue_list_column_widths: List[int] = field(default_factory=lambda: DEFAULT_ISSUE_LIST_COLUMN_WIDTHS.copy())

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
        cfg = AppConfig()
        cfg.__dict__.update(data or {})
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
