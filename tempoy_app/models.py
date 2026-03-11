from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(slots=True)
class WorklogTotals:
    today_seconds: int = 0
    total_seconds: int = 0
    last_logged_at: Optional[str] = None


@dataclass(slots=True)
class IssueSnapshot:
    issue_key: str
    summary: str = ""
    status_name: str = "Unknown"
    parent_or_epic: str = ""
    parent_lookup_key: str = ""
    today_seconds: int = 0
    total_seconds: int = 0
    last_logged_at: Optional[str] = None
    is_assigned_to_me: bool = False
    is_recently_worked: bool = False
    updated_at: Optional[str] = None


@dataclass(slots=True)
class CacheEntry:
    value: object
    fetched_at: float
    ttl_seconds: int
    source_window_days: Optional[int] = None
    invalidation_reason: Optional[str] = None

    def is_valid(self, now: float) -> bool:
        return (now - self.fetched_at) < self.ttl_seconds


@dataclass(slots=True)
class AllocationRow:
    issue_key: str
    summary: str = ""
    allocation_units: int = 0
    locked: bool = False
    description: str = ""


@dataclass(slots=True)
class AllocationState:
    total_units: int
    rows: List[AllocationRow] = field(default_factory=list)

    def allocated_units(self) -> int:
        return sum(row.allocation_units for row in self.rows)

    def unlocked_rows(self) -> List[AllocationRow]:
        return [row for row in self.rows if not row.locked]
