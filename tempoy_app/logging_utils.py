from __future__ import annotations

import os
from typing import Any


def debug_enabled() -> bool:
    return bool(os.environ.get("TEMPOY_DEBUG"))


def debug_log(message: str, *args: Any) -> None:
    if not debug_enabled():
        return
    if args:
        try:
            if "%" in message:
                message = message % args
            else:
                message = message.format(*args)
        except Exception:
            try:
                message = message.format(*args)
            except Exception:
                message = " ".join([message, *[str(arg) for arg in args]])
    print(f"[TEMPOY DEBUG] {message}")
