from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Dict, Optional

from tempoy_app.config import CONFIG_DIR


class CopilotAuditService:
    def __init__(self, log_path: Optional[str] = None):
        self._log_path = log_path or os.path.join(CONFIG_DIR, "copilot_api_audit.log")

    @property
    def log_path(self) -> str:
        return self._log_path

    def log_event(
        self,
        *,
        operation: str,
        success: bool,
        category: str,
        detail: Optional[Dict[str, object]] = None,
    ) -> None:
        os.makedirs(os.path.dirname(self._log_path), exist_ok=True)
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "success": bool(success),
            "category": category,
            "detail": detail or {},
        }
        with open(self._log_path, "a", encoding="utf-8") as file_handle:
            file_handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
