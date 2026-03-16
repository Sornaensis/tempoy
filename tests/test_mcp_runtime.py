from __future__ import annotations

import unittest

from tempoy_app.copilot_adapter import TempoyApiAdapterError
from tempoy_app.mcp_runtime import (
    TempoyMcpAuthenticationError,
    TempoyMcpConnectionError,
    TempoyMcpPolicyError,
    TempoyMcpRuntime,
    TempoyMcpValidationError,
)


class _FakeAdapter:
    def __init__(self):
        self.token = None
        self.start_session_calls = []
        self.stop_session_calls = 0
        self.invoke_calls = []
        self.invoke_responses = []

    def start_session(self, *, client_name: str = "copilot-adapter"):
        self.start_session_calls.append(client_name)
        self.token = f"token-{len(self.start_session_calls)}"
        return {"token": self.token}

    def stop_session(self):
        self.stop_session_calls += 1
        self.token = None
        return {"stopped": True}

    def invoke(self, tool_name, arguments=None):
        self.invoke_calls.append((tool_name, dict(arguments or {}), self.token))
        if self.invoke_responses:
            response = self.invoke_responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return {"tool": tool_name}

    def set_token(self, token):
        self.token = token


class TempoyMcpRuntimeTests(unittest.TestCase):
    def test_health_does_not_start_session(self) -> None:
        adapter = _FakeAdapter()
        runtime = TempoyMcpRuntime(adapter=adapter)

        payload = runtime.call_tool("health")

        self.assertEqual(payload["tool"], "health")
        self.assertEqual(adapter.start_session_calls, [])

    def test_protected_tool_starts_session_automatically(self) -> None:
        adapter = _FakeAdapter()
        runtime = TempoyMcpRuntime(adapter=adapter, client_name="tests")

        payload = runtime.call_tool("list_projects")

        self.assertEqual(payload["tool"], "list_projects")
        self.assertEqual(adapter.start_session_calls, ["tests"])
        self.assertEqual(adapter.invoke_calls[0][2], "token-1")

    def test_unauthorized_error_restarts_session_and_retries_once(self) -> None:
        adapter = _FakeAdapter()
        adapter.invoke_responses = [TempoyApiAdapterError("HTTP 401: Unauthorized"), {"ok": True}]
        runtime = TempoyMcpRuntime(adapter=adapter, client_name="tests")

        payload = runtime.call_tool("list_projects")

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(adapter.start_session_calls, ["tests", "tests"])
        self.assertEqual(len(adapter.invoke_calls), 2)

    def test_maps_connection_error(self) -> None:
        adapter = _FakeAdapter()
        adapter.invoke_responses = [TempoyApiAdapterError("Connection failed: refused")]
        runtime = TempoyMcpRuntime(adapter=adapter)

        with self.assertRaises(TempoyMcpConnectionError):
            runtime.call_tool("list_projects")

    def test_maps_policy_error(self) -> None:
        adapter = _FakeAdapter()
        adapter.invoke_responses = [TempoyApiAdapterError("HTTP 403: Project is not allowed")]
        runtime = TempoyMcpRuntime(adapter=adapter)

        with self.assertRaises(TempoyMcpPolicyError):
            runtime.call_tool("list_projects")

    def test_maps_validation_error(self) -> None:
        adapter = _FakeAdapter()
        adapter.invoke_responses = [TempoyApiAdapterError("HTTP 400: Project key is required")]
        runtime = TempoyMcpRuntime(adapter=adapter)

        with self.assertRaises(TempoyMcpValidationError):
            runtime.call_tool("list_project_issue_types", {"project_key": ""})

    def test_maps_authentication_error_after_retry(self) -> None:
        adapter = _FakeAdapter()
        adapter.invoke_responses = [
            TempoyApiAdapterError("HTTP 401: Unauthorized"),
            TempoyApiAdapterError("HTTP 401: Unauthorized"),
        ]
        runtime = TempoyMcpRuntime(adapter=adapter)

        with self.assertRaises(TempoyMcpAuthenticationError):
            runtime.call_tool("list_projects")

    def test_shutdown_stops_active_session(self) -> None:
        adapter = _FakeAdapter()
        runtime = TempoyMcpRuntime(adapter=adapter)
        runtime.call_tool("list_projects")

        runtime.shutdown()

        self.assertEqual(adapter.stop_session_calls, 1)
        self.assertIsNone(adapter.token)

    def test_shutdown_is_noop_when_no_session(self) -> None:
        adapter = _FakeAdapter()
        runtime = TempoyMcpRuntime(adapter=adapter)

        runtime.shutdown()

        self.assertEqual(adapter.stop_session_calls, 0)

    def test_shutdown_clears_token_on_stop_failure(self) -> None:
        adapter = _FakeAdapter()
        runtime = TempoyMcpRuntime(adapter=adapter)
        runtime.call_tool("list_projects")
        self.assertIsNotNone(adapter.token)

        # Make stop_session raise
        original_stop = adapter.stop_session
        def failing_stop():
            raise TempoyApiAdapterError("Connection failed: refused")
        adapter.stop_session = failing_stop

        runtime.shutdown()

        self.assertIsNone(adapter.token)

    def test_shutdown_can_be_called_multiple_times(self) -> None:
        adapter = _FakeAdapter()
        runtime = TempoyMcpRuntime(adapter=adapter)
        runtime.call_tool("list_projects")

        runtime.shutdown()
        runtime.shutdown()

        self.assertEqual(adapter.stop_session_calls, 1)

    def test_normalizes_empty_tool_name(self) -> None:
        adapter = _FakeAdapter()
        runtime = TempoyMcpRuntime(adapter=adapter)

        payload = runtime.call_tool("  health  ")

        self.assertEqual(payload["tool"], "health")
        self.assertEqual(adapter.start_session_calls, [])

    def test_session_start_failure_maps_to_connection_error(self) -> None:
        adapter = _FakeAdapter()
        original_start = adapter.start_session
        def failing_start(*, client_name="copilot-adapter"):
            raise TempoyApiAdapterError("Connection failed: refused")
        adapter.start_session = failing_start
        runtime = TempoyMcpRuntime(adapter=adapter)

        with self.assertRaises(TempoyMcpConnectionError):
            runtime.call_tool("list_projects")


if __name__ == "__main__":
    unittest.main()