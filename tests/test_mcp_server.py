from __future__ import annotations

import asyncio
import unittest

import mcp.types as types

from tempoy_app.mcp_runtime import TempoyMcpRuntimeError
from tempoy_app.mcp_server import build_error_result, build_success_result, execute_mcp_tool, list_mcp_tools, _configure_mcp_logging, _parse_args


class _FakeRuntime:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def call_tool(self, tool_name, arguments=None):
        self.calls.append((tool_name, dict(arguments or {})))
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return {"tool": tool_name}


class TempoyMcpServerTests(unittest.TestCase):
    def test_list_mcp_tools_includes_expected_names(self) -> None:
        tools = asyncio.run(list_mcp_tools())

        tool_names = {tool.name for tool in tools}
        self.assertIn("search_tickets", tool_names)
        self.assertIn("get_issue_details", tool_names)
        self.assertIn("create_ticket", tool_names)
        self.assertIn("reset_allocation", tool_names)

    def test_build_success_result_includes_structured_content(self) -> None:
        result = build_success_result({"ok": True})

        self.assertFalse(result.isError)
        self.assertEqual(result.structuredContent["ok"], True)
        self.assertIsInstance(result.content[0], types.TextContent)

    def test_build_error_result_marks_error(self) -> None:
        result = build_error_result("Nope")

        self.assertTrue(result.isError)
        self.assertEqual(result.structuredContent["error"], "Nope")

    def test_execute_mcp_tool_dispatches_to_runtime(self) -> None:
        runtime = _FakeRuntime([{"projects": []}])

        result = asyncio.run(execute_mcp_tool(runtime, "list_projects", {}))

        self.assertFalse(result.isError)
        self.assertEqual(result.structuredContent, {"projects": []})
        self.assertEqual(runtime.calls, [("list_projects", {})])

    def test_execute_mcp_tool_returns_error_for_unknown_tool(self) -> None:
        runtime = _FakeRuntime()

        result = asyncio.run(execute_mcp_tool(runtime, "unknown_tool", {}))

        self.assertTrue(result.isError)
        self.assertIn("Unknown tool", result.structuredContent["error"])

    def test_execute_mcp_tool_returns_runtime_errors_as_calltool_errors(self) -> None:
        runtime = _FakeRuntime([TempoyMcpRuntimeError("Tempoy API unavailable")])

        result = asyncio.run(execute_mcp_tool(runtime, "list_projects", {}))

        self.assertTrue(result.isError)
        self.assertEqual(result.structuredContent["error"], "Tempoy API unavailable")

    def test_execute_mcp_tool_returns_error_for_empty_tool_name(self) -> None:
        runtime = _FakeRuntime()

        result = asyncio.run(execute_mcp_tool(runtime, "", {}))

        self.assertTrue(result.isError)
        self.assertIn("Unknown tool", result.structuredContent["error"])

    def test_execute_mcp_tool_returns_error_for_whitespace_tool_name(self) -> None:
        runtime = _FakeRuntime()

        result = asyncio.run(execute_mcp_tool(runtime, "  ", {}))

        self.assertTrue(result.isError)
        self.assertIn("Unknown tool", result.structuredContent["error"])

    def test_execute_mcp_tool_with_none_arguments(self) -> None:
        runtime = _FakeRuntime([{"projects": []}])

        result = asyncio.run(execute_mcp_tool(runtime, "list_projects", None))

        self.assertFalse(result.isError)
        self.assertEqual(runtime.calls, [("list_projects", {})])

    def test_execute_mcp_tool_catches_unexpected_exceptions(self) -> None:
        runtime = _FakeRuntime([ValueError("oops")])

        result = asyncio.run(execute_mcp_tool(runtime, "list_projects", {}))

        self.assertTrue(result.isError)
        self.assertIn("Unexpected MCP server error", result.structuredContent["error"])

    def test_list_mcp_tools_returns_all_defined_tools(self) -> None:
        from tempoy_app.mcp_tools import get_tool_definitions

        tools = asyncio.run(list_mcp_tools())

        self.assertEqual(len(tools), len(get_tool_definitions()))
        for tool in tools:
            self.assertIsNotNone(tool.name)
            self.assertIsNotNone(tool.inputSchema)


class TempoyMcpServerArgsTests(unittest.TestCase):
    def test_parse_args_defaults(self) -> None:
        import os
        env = os.environ.copy()
        os.environ.pop("TEMPOY_API_BASE_URL", None)
        os.environ.pop("TEMPOY_MCP_CLIENT_NAME", None)
        os.environ.pop("TEMPOY_MCP_VERBOSE", None)
        try:
            args = _parse_args([])
            self.assertEqual(args.base_url, "http://127.0.0.1:8765")
            self.assertEqual(args.client_name, "tempoy-mcp")
            self.assertFalse(args.verbose)
        finally:
            os.environ.clear()
            os.environ.update(env)

    def test_parse_args_explicit_values(self) -> None:
        args = _parse_args(["--base-url", "http://localhost:9999", "--client-name", "test-client", "--verbose"])

        self.assertEqual(args.base_url, "http://localhost:9999")
        self.assertEqual(args.client_name, "test-client")
        self.assertTrue(args.verbose)

    def test_configure_mcp_logging_creates_stderr_handler(self) -> None:
        import logging
        import sys
        logger = logging.getLogger("tempoy-mcp")
        original_handlers = list(logger.handlers)
        try:
            _configure_mcp_logging(verbose=True)
            self.assertTrue(any(
                isinstance(h, logging.StreamHandler) and h.stream is sys.stderr
                for h in logger.handlers
            ))
            self.assertEqual(logger.level, logging.DEBUG)
        finally:
            logger.handlers = original_handlers


if __name__ == "__main__":
    unittest.main()