from __future__ import annotations

import os
from typing import Any


def debug_enabled() -> bool:
    return bool(os.environ.get("TEMPOY_DEBUG"))


def debug_log(message: str, *args: Any) -> None:
    if not debug_enabled():
        return
    if args:
        message = message.format(*args)
    print(f"[TEMPOY DEBUG] {message}")
