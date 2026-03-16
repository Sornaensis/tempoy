from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Callable, Dict, Optional

from tempoy_app.config import AppConfig
from tempoy_app.models import AllocationRow, AllocationState
from tempoy_app.services.allocation_service import AllocationService
from tempoy_app.services.worklog_service import WorklogService

if TYPE_CHECKING:
    from tempoy_app.api.jira import JiraClient
    from tempoy_app.api.tempo import TempoClient


class CopilotAllocationService:
    def __init__(
        self,
        *,
        config_loader: Callable[[], AppConfig],
        config_saver: Optional[Callable[[AppConfig], None]] = None,
        allocation_service: Optional[AllocationService] = None,
        daily_total_resolver: Optional[Callable[[AppConfig], Optional[int]]] = None,
        issue_summary_resolver: Optional[Callable[[str], str]] = None,
        on_state_changed: Optional[Callable[[], None]] = None,
    ):
        self._config_loader = config_loader
        self._config_saver = config_saver
        self._allocation_service = allocation_service or AllocationService()
        self._daily_total_resolver = daily_total_resolver or self._resolve_daily_total_from_clients
        self._issue_summary_resolver = issue_summary_resolver or self._resolve_issue_summary
        self._on_state_changed = on_state_changed

    def get_allocation_draft(self) -> Dict[str, object]:
        config = self._config_loader()
        return self._serialize_state(config)

    def add_issue(self, issue_key: str, *, summary: Optional[str] = None) -> Dict[str, object]:
        normalized_issue_key = str(issue_key or "").strip().upper()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        config, state = self._load_state()
        if any(row.issue_key == normalized_issue_key for row in state.rows):
            return self._serialize_state(config)
        issue_summary = str(summary or "").strip()
        if not issue_summary:
            issue_summary = self._issue_summary_resolver(normalized_issue_key)
        state = AllocationState(
            total_units=state.total_units,
            rows=[*state.rows, AllocationRow(issue_key=normalized_issue_key, summary=issue_summary, allocation_units=0, locked=False, description="")],
        )
        state = self._rebalance_after_structure_change(state)
        return self._save_state(config, state)

    def remove_issue(self, issue_key: str) -> Dict[str, object]:
        normalized_issue_key = str(issue_key or "").strip().upper()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        config, state = self._load_state()
        updated_state = self._allocation_service.remove_row(state, normalized_issue_key)
        return self._save_state(config, updated_state)

    def set_row_units(self, issue_key: str, allocation_units: int) -> Dict[str, object]:
        normalized_issue_key = str(issue_key or "").strip().upper()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        config, state = self._load_state()
        updated_state = self._allocation_service.set_row_units(state, normalized_issue_key, max(0, int(allocation_units)))
        return self._save_state(config, updated_state)

    def set_row_lock(self, issue_key: str, locked: bool) -> Dict[str, object]:
        normalized_issue_key = str(issue_key or "").strip().upper()
        if not normalized_issue_key:
            raise ValueError("Issue key is required")
        config, state = self._load_state()
        rows = []
        for row in state.rows:
            if row.issue_key == normalized_issue_key:
                rows.append(replace(row, locked=bool(locked)))
            else:
                rows.append(replace(row))
        updated_state = AllocationState(total_units=state.total_units, rows=rows)
        if not self._allocation_service.validate(updated_state):
            updated_state = self._rebalance_after_structure_change(updated_state)
        return self._save_state(config, updated_state)

    def equalize(self) -> Dict[str, object]:
        config, state = self._load_state()
        updated_state = self._allocation_service.equalize_unlocked(state)
        return self._save_state(config, updated_state)

    def reset(self) -> Dict[str, object]:
        config, state = self._load_state()
        rows = [replace(row, allocation_units=0, locked=False) for row in state.rows]
        updated_state = self._rebalance_after_structure_change(AllocationState(total_units=state.total_units, rows=rows))
        return self._save_state(config, updated_state)

    def _load_state(self) -> tuple[AppConfig, AllocationState]:
        config = self._config_loader()
        allocation_draft = config.allocation_draft if isinstance(config.allocation_draft, dict) else {"rows": []}
        state = AllocationState.from_dict(allocation_draft, self._allocation_service.TOTAL_UNITS)
        return config, state

    def _save_state(self, config: AppConfig, state: AllocationState) -> Dict[str, object]:
        config.allocation_draft = state.to_dict()
        if self._config_saver is not None:
            self._config_saver(config)
        if self._on_state_changed is not None:
            try:
                self._on_state_changed()
            except Exception:
                pass
        return self._serialize_state(config)

    def _serialize_state(self, config: AppConfig) -> Dict[str, object]:
        configured_day_seconds = max(0, int(getattr(config, "daily_time_seconds", 0) or 0))
        allocation_draft = config.allocation_draft if isinstance(config.allocation_draft, dict) else {"rows": []}
        state = AllocationState.from_dict(allocation_draft, self._allocation_service.TOTAL_UNITS)
        daily_logged_seconds = self._daily_total_resolver(config)
        remaining_seconds = None if daily_logged_seconds is None else max(0, configured_day_seconds - max(0, int(daily_logged_seconds)))
        allocatable_seconds = configured_day_seconds if remaining_seconds is None else remaining_seconds
        duration_state = state if self._allocation_service.validate(state) or not state.rows else self._rebalance_after_structure_change(state)
        durations = self._allocation_service.allocations_to_total_seconds(duration_state, allocatable_seconds)
        planned_seconds = sum(max(0, seconds) for seconds in durations.values())
        rows = []
        for row in state.rows:
            rows.append(
                {
                    **row.to_dict(),
                    "allocated_seconds": durations.get(row.issue_key, 0),
                }
            )
        return {
            "draft": state.to_dict(),
            "rows": rows,
            "total_units": state.total_units,
            "allocated_units": state.allocated_units(),
            "is_valid": self._allocation_service.validate(state),
            "configured_day_seconds": configured_day_seconds,
            "daily_logged_seconds": daily_logged_seconds,
            "remaining_seconds": remaining_seconds,
            "allocatable_seconds": allocatable_seconds,
            "planned_seconds": planned_seconds,
            "warnings": self._build_warnings(remaining_seconds=remaining_seconds, planned_seconds=planned_seconds),
        }

    def _rebalance_after_structure_change(self, state: AllocationState) -> AllocationState:
        if not state.rows:
            return state
        if not any(not row.locked for row in state.rows):
            unlocked_rows = [replace(row, locked=False) if index == 0 else replace(row) for index, row in enumerate(state.rows)]
            state = AllocationState(total_units=state.total_units, rows=unlocked_rows)
        return self._allocation_service.equalize_unlocked(state)

    @staticmethod
    def _build_warnings(*, remaining_seconds: Optional[int], planned_seconds: int) -> list[str]:
        warnings: list[str] = []
        if remaining_seconds is not None and remaining_seconds <= 0:
            warnings.append("Daily limit reached")
        elif remaining_seconds is not None and planned_seconds > remaining_seconds:
            warnings.append("Allocation exceeds remaining daily time")
        return warnings

    @staticmethod
    def _resolve_daily_total_from_clients(config: AppConfig) -> Optional[int]:
        if not (config.jira_base_url and config.jira_email and config.jira_api_token and config.tempo_api_token):
            return None
        try:
            from tempoy_app.api.jira import JiraClient
            from tempoy_app.api.tempo import TempoClient

            jira_client = JiraClient(config.jira_base_url, config.jira_email, config.jira_api_token)
            myself = jira_client.get_myself() or {}
            account_id = str(myself.get("accountId") or "").strip()
            if not account_id:
                return None
            tempo_client = TempoClient(config.tempo_api_token)
            return WorklogService(jira_client, tempo_client).get_daily_total(account_id=account_id)
        except Exception:
            return None

    @staticmethod
    def _resolve_issue_summary(issue_key: str) -> str:
        return ""