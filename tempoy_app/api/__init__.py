from __future__ import annotations

from typing import Any

__all__ = ["JiraClient", "TempoClient"]


def __getattr__(name: str) -> Any:
	if name == "JiraClient":
		from .jira import JiraClient

		return JiraClient
	if name == "TempoClient":
		from .tempo import TempoClient

		return TempoClient
	raise AttributeError(name)
