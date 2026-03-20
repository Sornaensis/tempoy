from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from typing import Any


LOGGER_NAME = "tempoy"
LOG_FILE_NAME = "tempoy.log"
LOG_MAX_BYTES = 1_048_576
LOG_BACKUP_COUNT = 5

_logger_lock = threading.Lock()
_logger: logging.Logger | None = None
_logger_path: str | None = None


def debug_enabled() -> bool:
    return bool(os.environ.get("TEMPOY_DEBUG"))


def get_log_path() -> str:
    from tempoy_app import config as config_module

    return os.path.join(config_module.CONFIG_DIR, LOG_FILE_NAME)


def configure_logging() -> str:
    _get_logger()
    return get_log_path()


def shutdown_logging() -> None:
    global _logger_path

    with _logger_lock:
        logger = _logger
        if logger is None:
            _logger_path = None
            return
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        _logger_path = None


def _get_logger() -> logging.Logger:
    global _logger, _logger_path

    desired_path = get_log_path()
    with _logger_lock:
        if _logger is None:
            _logger = logging.getLogger(LOGGER_NAME)
            _logger.setLevel(logging.DEBUG)
            _logger.propagate = False

            # Ensure tempoy_app.* module loggers are captured too
            app_logger = logging.getLogger("tempoy_app")
            app_logger.setLevel(logging.DEBUG)
            app_logger.propagate = False
        if _logger_path != desired_path or not _logger.handlers:
            os.makedirs(os.path.dirname(desired_path), exist_ok=True)
            for handler in list(_logger.handlers):
                _logger.removeHandler(handler)
                handler.close()
            file_handler = RotatingFileHandler(
                desired_path,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            _logger.addHandler(file_handler)

            # Share the handler with the tempoy_app logger hierarchy
            app_logger = logging.getLogger("tempoy_app")
            for h in list(app_logger.handlers):
                app_logger.removeHandler(h)
                h.close()
            app_logger.addHandler(file_handler)

            _logger_path = desired_path
        return _logger


def _format_message(message: str, *args: Any) -> str:
    if args:
        try:
            if "%" in message:
                return message % args
            else:
                return message.format(*args)
        except Exception:
            try:
                return message.format(*args)
            except Exception:
                return " ".join([message, *[str(arg) for arg in args]])
    return message


def _log(level: int, label: str, message: str, *args: Any) -> None:
    formatted_message = _format_message(message, *args)
    _get_logger().log(level, formatted_message)
    if debug_enabled():
        print(f"[TEMPOY {label}] {formatted_message}")


def debug_log(message: str, *args: Any) -> None:
    _log(logging.DEBUG, "DEBUG", message, *args)


def audit_log(message: str, *args: Any) -> None:
    _log(logging.INFO, "INFO", message, *args)


def error_log(message: str, *args: Any) -> None:
    _log(logging.ERROR, "ERROR", message, *args)
