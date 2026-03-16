from __future__ import annotations

import secrets
import time
from typing import Callable, Optional

from tempoy_app.config import AppConfig
from tempoy_app.models_copilot_api import CopilotApiCapabilities, CopilotApiSession


class CopilotPolicyError(RuntimeError):
    pass


class CopilotPolicyService:
    def __init__(
        self,
        *,
        config_loader: Callable[[], AppConfig],
        config_saver: Callable[[AppConfig], None],
        time_provider: Callable[[], float] = time.time,
    ):
        self._config_loader = config_loader
        self._config_saver = config_saver
        self._time_provider = time_provider

    def get_config(self) -> AppConfig:
        return self._config_loader()

    def is_enabled(self) -> bool:
        return self.get_config().copilot_api_enabled

    def get_capabilities(self) -> CopilotApiCapabilities:
        config = self.get_config()
        can_read = config.copilot_api_enabled
        can_refine = config.copilot_api_enabled and config.copilot_api_mode in {"refine-only", "create-and-refine"}
        can_create = config.copilot_api_enabled and config.copilot_api_mode == "create-and-refine"
        session_active = self.has_active_session(config)
        return CopilotApiCapabilities(
            api_enabled=config.copilot_api_enabled,
            mode=config.copilot_api_mode,
            allowed_projects=list(config.copilot_allowed_projects),
            allowed_issue_types=list(config.copilot_allowed_issue_types),
            require_write_confirmation=config.copilot_require_write_confirmation,
            session_active=session_active,
            session_expires_at=config.copilot_session_expires_at if session_active else None,
            endpoints={
                "health": True,
                "capabilities": True,
                "session": config.copilot_api_enabled,
                "projects_read": can_read,
                "issues_read": can_read,
                "issues_refine": can_refine,
                "issues_create": can_create,
                "allocation_read": can_read,
                "allocation_write": can_refine,
            },
        )

    def start_session(self, *, client_name: Optional[str] = None) -> CopilotApiSession:
        config = self.get_config()
        if not config.copilot_api_enabled:
            raise CopilotPolicyError("Copilot API is disabled")
        config.copilot_session_token = secrets.token_urlsafe(24)
        now = int(self._time_provider())
        config.copilot_session_expires_at = now + int(config.copilot_session_ttl_seconds)
        self._config_saver(config)
        return CopilotApiSession(
            token=config.copilot_session_token,
            mode=config.copilot_api_mode,
            client_name=client_name,
            expires_at=config.copilot_session_expires_at,
        )

    def stop_session(self, *, token: Optional[str] = None) -> bool:
        config = self.get_config()
        if self._is_session_expired(config):
            self._clear_session(config)
            self._config_saver(config)
            return False
        if not config.copilot_session_token:
            return False
        if not token or token != config.copilot_session_token:
            raise CopilotPolicyError("Unauthorized")
        self._clear_session(config)
        self._config_saver(config)
        return True

    def require_enabled(self) -> AppConfig:
        config = self.get_config()
        if not config.copilot_api_enabled:
            raise CopilotPolicyError("Copilot API is disabled")
        return config

    def require_session_token(self, token: Optional[str]) -> AppConfig:
        config = self.require_enabled()
        if self._is_session_expired(config):
            self._clear_session(config)
            self._config_saver(config)
            raise CopilotPolicyError("Unauthorized")
        if not token or token != config.copilot_session_token:
            raise CopilotPolicyError("Unauthorized")
        return config

    def has_active_session(self, config: Optional[AppConfig] = None) -> bool:
        current_config = config or self.get_config()
        return bool(current_config.copilot_session_token) and not self._is_session_expired(current_config)

    def is_project_allowed(self, project_key: Optional[str]) -> bool:
        config = self.get_config()
        allowed_projects = config.copilot_allowed_projects
        if not allowed_projects:
            return True
        normalized_key = str(project_key or "").strip().upper()
        if not normalized_key:
            return False
        return normalized_key in allowed_projects

    def filter_allowed_projects(self, project_keys: list[str]) -> list[str]:
        config = self.get_config()
        if not config.copilot_allowed_projects:
            return [project_key for project_key in project_keys if str(project_key or "").strip()]
        filtered: list[str] = []
        for project_key in project_keys:
            normalized_key = str(project_key or "").strip().upper()
            if normalized_key and normalized_key in config.copilot_allowed_projects:
                filtered.append(normalized_key)
        return filtered

    def is_issue_type_allowed(self, issue_type_name: Optional[str]) -> bool:
        config = self.get_config()
        allowed_issue_types = [str(item or "").strip().casefold() for item in config.copilot_allowed_issue_types if str(item or "").strip()]
        if not allowed_issue_types:
            return True
        normalized_name = str(issue_type_name or "").strip().casefold()
        if not normalized_name:
            return False
        return normalized_name in allowed_issue_types

    def require_create_access(self, token: Optional[str], *, issue_type_name: str) -> AppConfig:
        config = self.require_session_token(token)
        if config.copilot_api_mode != "create-and-refine":
            raise CopilotPolicyError("Create access is disabled")
        if not self.is_issue_type_allowed(issue_type_name):
            raise CopilotPolicyError("Issue type is not allowed")
        return config

    def require_refine_access(self, token: Optional[str], *, issue_type_name: Optional[str] = None) -> AppConfig:
        config = self.require_session_token(token)
        if config.copilot_api_mode not in {"refine-only", "create-and-refine"}:
            raise CopilotPolicyError("Refine access is disabled")
        if issue_type_name is not None and not self.is_issue_type_allowed(issue_type_name):
            raise CopilotPolicyError("Issue type is not allowed")
        return config

    def _is_session_expired(self, config: AppConfig) -> bool:
        if not config.copilot_session_token:
            return False
        if config.copilot_session_expires_at is None:
            return False
        return int(self._time_provider()) >= int(config.copilot_session_expires_at)

    @staticmethod
    def _clear_session(config: AppConfig) -> None:
        config.copilot_session_token = None
        config.copilot_session_expires_at = None
