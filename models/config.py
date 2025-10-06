"""Configuration data model for Tempoy application."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class AppConfig:
    """Application configuration with persistence support."""
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    tempo_api_token: str = ""
    reminder_minutes: int = 60
    always_on_top: bool = True
    last_issue_key: str = ""
    expanded: bool = False  # Remember expand/collapse state
    # Window geometry persistence
    window_x: int = 100
    window_y: int = 100
    collapsed_width: int = 500
    collapsed_height: int = 120
    expanded_width: int = 840
    expanded_height: int = 420
    # Search/selection history persistence
    # New structured format (post-fix): list of dict entries
    #  {"type": "search", "term": str, "ts": float}
    #  {"type": "issue", "term": issue_key, "summary": str, "ts": float}
    # Backward compatibility: old entries were list of (term, ts) tuples treated as type 'search'
    search_history: List = field(default_factory=list)
    # Column widths persistence
    issue_list_column_widths: List[int] = field(default_factory=lambda: [100, 300, 150, 60, 60, 100])  # Default widths for 6 columns
    
    def prune_old_history(self, days_back: int = 3):
        """Remove history entries older than specified days."""
        cutoff_time = time.time() - (days_back * 24 * 60 * 60)
        new_hist = []
        for entry in self.search_history:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                term, ts = entry[0], entry[1]
                if ts >= cutoff_time:
                    new_hist.append(entry)
            elif isinstance(entry, dict):
                ts = entry.get('ts')
                if isinstance(ts, (int, float)) and ts >= cutoff_time:
                    new_hist.append(entry)
        self.search_history = new_hist

    def to_dict(self) -> Dict:
        """Convert configuration to dictionary for JSON serialization."""
        return self.__dict__

    @staticmethod
    def from_dict(d: Dict) -> "AppConfig":
        """Create AppConfig from dictionary, handling migrations."""
        ac = AppConfig()
        ac.__dict__.update(d or {})
        # Initialize search_history if not present or if it's None
        if not hasattr(ac, 'search_history') or ac.search_history is None:
            ac.search_history = []
        # Migration: convert legacy (term, ts) tuples to dict format
        migrated = []
        changed = False
        for entry in ac.search_history:
            if isinstance(entry, dict):
                migrated.append(entry)
            elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                migrated.append({"type": "search", "term": entry[0], "ts": entry[1]})
                changed = True
        if changed:
            ac.search_history = migrated
        # Initialize column widths if not present
        if not hasattr(ac, 'issue_list_column_widths') or ac.issue_list_column_widths is None:
            ac.issue_list_column_widths = [100, 300, 150, 60, 60, 100]
        return ac
