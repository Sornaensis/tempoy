from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from tempoy_app.copilot_adapter import TempoyApiAdapter, TempoyApiAdapterError


class _AdapterProtocol(Protocol):
    token: Optional[str]

    def start_session(self, *, client_name: str = "copilot-adapter") -> Dict[str, Any]: ...

    def stop_session(self) -> Dict[str, Any]: ...

    def invoke(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...

    def set_token(self, token: Optional[str]) -> None: ...


class TempoyMcpRuntimeError(RuntimeError):
    pass


class TempoyMcpConnectionError(TempoyMcpRuntimeError):
    pass


class TempoyMcpAuthenticationError(TempoyMcpRuntimeError):
    pass


class TempoyMcpPolicyError(TempoyMcpRuntimeError):
    pass


class TempoyMcpValidationError(TempoyMcpRuntimeError):
    pass


@dataclass
class TempoyMcpRuntime:
    adapter: _AdapterProtocol
    client_name: str = "tempoy-mcp"

    NO_SESSION_TOOLS = {"health", "capabilities"}

    @classmethod
    def create(cls, *, base_url: str = "http://127.0.0.1:8765", client_name: str = "tempoy-mcp") -> "TempoyMcpRuntime":
        return cls(adapter=TempoyApiAdapter(base_url=base_url), client_name=client_name)

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        normalized_tool_name = str(tool_name or "").strip()
        payload = dict(arguments or {})
        if normalized_tool_name not in self.NO_SESSION_TOOLS:
            self._ensure_session()
        try:
            return self.adapter.invoke(normalized_tool_name, payload)
        except TempoyApiAdapterError as exc:
            if normalized_tool_name not in self.NO_SESSION_TOOLS and self._is_unauthorized_error(exc):
                self.adapter.set_token(None)
                self._ensure_session()
                try:
                    return self.adapter.invoke(normalized_tool_name, payload)
                except TempoyApiAdapterError as retry_exc:
                    raise self._map_adapter_error(retry_exc) from retry_exc
            raise self._map_adapter_error(exc) from exc

    def shutdown(self) -> None:
        if not self.adapter.token:
            return
        try:
            self.adapter.stop_session()
        except TempoyApiAdapterError:
            self.adapter.set_token(None)

    def _ensure_session(self) -> None:
        if self.adapter.token:
            return
        try:
            self.adapter.start_session(client_name=self.client_name)
        except TempoyApiAdapterError as exc:
            raise self._map_adapter_error(exc) from exc

    @staticmethod
    def _is_unauthorized_error(exc: TempoyApiAdapterError) -> bool:
        return str(exc).startswith("HTTP 401:")

    @staticmethod
    def _map_adapter_error(exc: TempoyApiAdapterError) -> TempoyMcpRuntimeError:
        message = str(exc)
        if message.startswith("Connection failed:"):
            return TempoyMcpConnectionError(message)
        if message.startswith("HTTP 401:"):
            return TempoyMcpAuthenticationError(message)
        if message.startswith("HTTP 403:"):
            return TempoyMcpPolicyError(message)
        if message.startswith("HTTP 400:"):
            return TempoyMcpValidationError(message)
        return TempoyMcpRuntimeError(message)