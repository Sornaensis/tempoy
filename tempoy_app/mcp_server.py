from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, Optional

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from tempoy_app.mcp_runtime import TempoyMcpRuntime, TempoyMcpRuntimeError
from tempoy_app.mcp_tools import get_tool_definition, get_tool_definitions

logger = logging.getLogger("tempoy-mcp")


def _configure_mcp_logging(*, verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root = logging.getLogger("tempoy-mcp")
    root.setLevel(level)
    root.addHandler(handler)


def build_mcp_tool(definition) -> types.Tool:
    return types.Tool(name=definition.name, description=definition.description, inputSchema=definition.input_schema)


def build_success_result(payload: Dict[str, Any]) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, indent=2, sort_keys=True))],
        structuredContent=payload,
        isError=False,
    )


def build_error_result(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)],
        structuredContent={"error": message},
        isError=True,
    )


async def list_mcp_tools() -> list[types.Tool]:
    tools = [build_mcp_tool(definition) for definition in get_tool_definitions()]
    logger.debug("Listed %d tools", len(tools))
    return tools


async def execute_mcp_tool(runtime: TempoyMcpRuntime, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> types.CallToolResult:
    if get_tool_definition(tool_name) is None:
        logger.warning("Unknown tool requested: %s", tool_name)
        return build_error_result(f"Unknown tool: {tool_name}")
    logger.info("Executing tool: %s", tool_name)
    try:
        payload = runtime.call_tool(tool_name, dict(arguments or {}))
    except TempoyMcpRuntimeError as exc:
        logger.error("Tool %s failed: %s", tool_name, exc)
        return build_error_result(str(exc))
    except Exception as exc:
        logger.exception("Unexpected error in tool %s", tool_name)
        return build_error_result(f"Unexpected MCP server error: {exc}")
    logger.info("Tool %s completed successfully", tool_name)
    return build_success_result(payload)


def create_tempoy_mcp_server(runtime: Optional[TempoyMcpRuntime] = None) -> Server:
    runtime_instance = runtime or TempoyMcpRuntime.create()
    server = Server("tempoy-mcp")

    @server.list_tools()
    async def _handle_list_tools() -> list[types.Tool]:
        return await list_mcp_tools()

    @server.call_tool()
    async def _handle_call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        return await execute_mcp_tool(runtime_instance, name, arguments)

    server._tempoy_runtime = runtime_instance  # type: ignore[attr-defined]
    return server


async def run_stdio_server(*, runtime: Optional[TempoyMcpRuntime] = None) -> None:
    server = create_tempoy_mcp_server(runtime=runtime)
    logger.info("Starting Tempoy MCP stdio server")
    try:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="tempoy-mcp",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )
    finally:
        logger.info("Shutting down Tempoy MCP server")
        runtime_instance = getattr(server, "_tempoy_runtime", None)
        if runtime_instance is not None:
            runtime_instance.shutdown()


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tempoy MCP stdio server")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("TEMPOY_API_BASE_URL", "http://127.0.0.1:8765"),
        help="Tempoy API base URL",
    )
    parser.add_argument(
        "--client-name",
        default=os.environ.get("TEMPOY_MCP_CLIENT_NAME", "tempoy-mcp"),
        help="Tempoy session client name",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=os.environ.get("TEMPOY_MCP_VERBOSE", "").lower() in ("1", "true", "yes"),
        help="Enable verbose (DEBUG) logging to stderr",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    _configure_mcp_logging(verbose=args.verbose)
    logger.info("Tempoy MCP server starting (base_url=%s, client_name=%s)", args.base_url, args.client_name)
    runtime = TempoyMcpRuntime.create(base_url=args.base_url, client_name=args.client_name)
    asyncio.run(run_stdio_server(runtime=runtime))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())