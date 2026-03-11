from __future__ import annotations

import time
from typing import Dict, Optional

from tempoy_app.models import CacheEntry


class CacheService:
    def __init__(self):
        self._entries: Dict[str, CacheEntry] = {}

    def get(self, key: str, now: Optional[float] = None):
        entry = self._entries.get(key)
        if entry is None:
            return None
        current_time = time.time() if now is None else now
        if not entry.is_valid(current_time):
            return None
        return entry.value

    def set(self, key: str, value, ttl_seconds: int, *, source_window_days: Optional[int] = None, invalidation_reason: Optional[str] = None, now: Optional[float] = None):
        fetched_at = time.time() if now is None else now
        self._entries[key] = CacheEntry(
            value=value,
            fetched_at=fetched_at,
            ttl_seconds=ttl_seconds,
            source_window_days=source_window_days,
            invalidation_reason=invalidation_reason,
        )

    def invalidate(self, key: str, reason: Optional[str] = None):
        entry = self._entries.get(key)
        if entry is None:
            return
        if reason:
            entry.invalidation_reason = reason
        self._entries.pop(key, None)

    def clear(self):
        self._entries.clear()
