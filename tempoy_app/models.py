from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


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

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, object]) -> "AllocationRow":
        return AllocationRow(
            issue_key=str(data.get("issue_key", "")).strip(),
            summary=str(data.get("summary", "")),
            allocation_units=max(0, int(data.get("allocation_units", 0) or 0)),
            locked=bool(data.get("locked", False)),
            description=str(data.get("description", "")),
        )


@dataclass(slots=True)
class AllocationState:
    total_units: int
    rows: List[AllocationRow] = field(default_factory=list)

    def allocated_units(self) -> int:
        return sum(row.allocation_units for row in self.rows)

    def unlocked_rows(self) -> List[AllocationRow]:
        return [row for row in self.rows if not row.locked]

    def to_dict(self) -> Dict[str, object]:
        return {
            "total_units": self.total_units,
            "rows": [row.to_dict() for row in self.rows],
        }

    @staticmethod
    def from_dict(data: Dict[str, object], default_total_units: int) -> "AllocationState":
        rows_data = data.get("rows", []) if isinstance(data, dict) else []
        rows = []
        if isinstance(rows_data, list):
            for raw_row in rows_data:
                if not isinstance(raw_row, dict):
                    continue
                row = AllocationRow.from_dict(raw_row)
                if row.issue_key:
                    rows.append(row)
        total_units = default_total_units
        if isinstance(data, dict):
            raw_total_units = data.get("total_units", default_total_units)
            try:
                total_units = max(0, int(raw_total_units))
            except (TypeError, ValueError):
                total_units = default_total_units
        return AllocationState(total_units=total_units, rows=rows)
