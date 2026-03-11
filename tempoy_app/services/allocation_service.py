from __future__ import annotations

from dataclasses import replace
from typing import Dict, List

from tempoy_app.models import AllocationRow, AllocationState


class AllocationService:
    TOTAL_UNITS = 10_000

    def equalize_unlocked(self, state: AllocationState) -> AllocationState:
        rows = [replace(row) for row in state.rows]
        unlocked_indexes = [index for index, row in enumerate(rows) if not row.locked]
        if not unlocked_indexes:
            return AllocationState(total_units=state.total_units, rows=rows)
        locked_total = sum(row.allocation_units for row in rows if row.locked)
        available = max(0, state.total_units - locked_total)
        base, remainder = divmod(available, len(unlocked_indexes))
        for offset, index in enumerate(unlocked_indexes):
            rows[index].allocation_units = base + (1 if offset < remainder else 0)
        return AllocationState(total_units=state.total_units, rows=rows)

    def set_row_units(self, state: AllocationState, issue_key: str, requested_units: int) -> AllocationState:
        rows = [replace(row) for row in state.rows]
        target_index = next((index for index, row in enumerate(rows) if row.issue_key == issue_key), None)
        if target_index is None:
            return AllocationState(total_units=state.total_units, rows=rows)
        target_row = rows[target_index]
        if target_row.locked:
            return AllocationState(total_units=state.total_units, rows=rows)
        other_locked_total = sum(row.allocation_units for index, row in enumerate(rows) if row.locked and index != target_index)
        other_unlocked_indexes = [index for index, row in enumerate(rows) if index != target_index and not row.locked]
        max_for_target = max(0, state.total_units - other_locked_total)
        clamped_units = max(0, min(requested_units, max_for_target))
        target_row.allocation_units = clamped_units
        remaining = state.total_units - other_locked_total - clamped_units
        if not other_unlocked_indexes:
            target_row.allocation_units = max(0, state.total_units - other_locked_total)
            return AllocationState(total_units=state.total_units, rows=rows)
        previous_total = sum(max(0, rows[index].allocation_units) for index in other_unlocked_indexes)
        if previous_total <= 0:
            base, remainder = divmod(remaining, len(other_unlocked_indexes))
            for offset, index in enumerate(other_unlocked_indexes):
                rows[index].allocation_units = base + (1 if offset < remainder else 0)
            return AllocationState(total_units=state.total_units, rows=rows)
        provisional: List[tuple[int, int, int]] = []
        assigned_total = 0
        for index in other_unlocked_indexes:
            numerator = max(0, rows[index].allocation_units) * remaining
            units = numerator // previous_total
            remainder_value = numerator % previous_total
            provisional.append((index, units, remainder_value))
            assigned_total += units
        leftover = remaining - assigned_total
        provisional.sort(key=lambda item: (-item[2], item[0]))
        for offset in range(leftover):
            index, units, remainder_value = provisional[offset]
            provisional[offset] = (index, units + 1, remainder_value)
        for index, units, _ in provisional:
            rows[index].allocation_units = units
        return AllocationState(total_units=state.total_units, rows=rows)

    def remove_row(self, state: AllocationState, issue_key: str) -> AllocationState:
        rows = [replace(row) for row in state.rows]
        target_index = next((index for index, row in enumerate(rows) if row.issue_key == issue_key), None)
        if target_index is None:
            return AllocationState(total_units=state.total_units, rows=rows)
        target_row = rows[target_index]
        remaining_rows = [row for index, row in enumerate(rows) if index != target_index]
        if not remaining_rows:
            return AllocationState(total_units=state.total_units, rows=[])
        removed_units = max(0, int(target_row.allocation_units))
        unlocked_indexes = [index for index, row in enumerate(remaining_rows) if not row.locked]
        if removed_units > 0 and unlocked_indexes:
            previous_total = sum(max(0, remaining_rows[index].allocation_units) for index in unlocked_indexes)
            if previous_total <= 0:
                base, remainder = divmod(removed_units, len(unlocked_indexes))
                for offset, index in enumerate(unlocked_indexes):
                    remaining_rows[index].allocation_units += base + (1 if offset < remainder else 0)
            else:
                provisional: List[tuple[int, int, int]] = []
                assigned_total = 0
                for index in unlocked_indexes:
                    numerator = max(0, remaining_rows[index].allocation_units) * removed_units
                    units = numerator // previous_total
                    remainder_value = numerator % previous_total
                    provisional.append((index, units, remainder_value))
                    assigned_total += units
                leftover = removed_units - assigned_total
                provisional.sort(key=lambda item: (-item[2], item[0]))
                for offset in range(leftover):
                    index, units, remainder_value = provisional[offset]
                    provisional[offset] = (index, units + 1, remainder_value)
                for index, units, _ in provisional:
                    remaining_rows[index].allocation_units += units
        return AllocationState(total_units=state.total_units, rows=remaining_rows)

    def allocations_to_total_seconds(self, state: AllocationState, total_seconds: int) -> Dict[str, int]:
        total_seconds = max(0, int(total_seconds))
        allocations: Dict[str, int] = {}
        provisional: List[tuple[str, int, int]] = []
        assigned_total = 0
        if state.total_units <= 0 or not state.rows:
            return {row.issue_key: 0 for row in state.rows}
        for row in state.rows:
            numerator = max(0, row.allocation_units) * total_seconds
            seconds = numerator // state.total_units
            remainder = numerator % state.total_units
            provisional.append((row.issue_key, seconds, remainder))
            assigned_total += seconds
        leftover = total_seconds - assigned_total
        provisional.sort(key=lambda item: (-item[2], item[0]))
        for offset in range(leftover):
            issue_key, seconds, remainder = provisional[offset]
            provisional[offset] = (issue_key, seconds + 1, remainder)
        for issue_key, seconds, _ in provisional:
            allocations[issue_key] = seconds
        return allocations

    def allocations_to_seconds(self, state: AllocationState, daily_time_minutes: int) -> Dict[str, int]:
        return self.allocations_to_total_seconds(state, max(0, int(daily_time_minutes) * 60))

    def validate(self, state: AllocationState) -> bool:
        return state.allocated_units() == state.total_units and all(row.allocation_units >= 0 for row in state.rows)
