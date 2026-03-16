# Tempoy MCP Server

A standalone MCP (Model Context Protocol) server that exposes Tempoy capabilities to AI agents and MCP-compatible clients.

## Overview

The Tempoy MCP server bridges MCP-speaking clients to the Tempoy localhost API. It:

- Exposes Jira read and write operations as MCP tools
- Manages Tempoy API sessions automatically (start, renew on expiry, stop on shutdown)
- Runs as a stdio process — no additional ports required
- Never sees Jira credentials; all access is mediated by the Tempoy API's policy layer

## Prerequisites

1. **Python 3.10+**
2. **MCP SDK**: `pip install mcp>=1.26`
3. **Tempoy application** running locally with the Copilot API enabled
4. The Tempoy repo available on `PYTHONPATH`

## Quick start

```bash
# From the Tempoy repo root:
python -m tempoy_app.mcp_server
```

The server communicates over stdin/stdout using the MCP protocol. It connects to the Tempoy API at `http://127.0.0.1:8765` by default.

## Command-line options

| Option | Env variable | Default | Description |
|--------|-------------|---------|-------------|
| `--base-url` | `TEMPOY_API_BASE_URL` | `http://127.0.0.1:8765` | Tempoy API base URL |
| `--client-name` | `TEMPOY_MCP_CLIENT_NAME` | `tempoy-mcp` | Client name for Tempoy sessions |
| `--verbose` | `TEMPOY_MCP_VERBOSE` | `false` | Enable DEBUG-level logging to stderr |

Examples:

```bash
# Custom port
python -m tempoy_app.mcp_server --base-url http://127.0.0.1:9000

# Verbose logging
python -m tempoy_app.mcp_server --verbose

# Using environment variables
TEMPOY_API_BASE_URL=http://127.0.0.1:9000 python -m tempoy_app.mcp_server
```

## Available tools

### Read tools

| Tool | Description |
|------|-------------|
| `health` | Get Tempoy API health and session status |
| `capabilities` | Get Tempoy API capabilities and enabled endpoints |
| `list_projects` | List Jira projects visible through Tempoy |
| `list_project_issue_types` | List issue types for a project |
| `get_project_create_schema` | Get normalized create metadata for a project |
| `search_tickets` | Search Jira tickets through Tempoy's safe search surface |
| `get_issue_details` | Get normalized details for a Jira issue |
| `analyze_hierarchy` | Get hierarchy and related-work view for issues |
| `get_allocation_draft` | Get the current allocation draft and daily context |

### Write tools

| Tool | Description |
|------|-------------|
| `create_ticket` | Create a Task through Tempoy's preview/apply flow |
| `update_issue_fields` | Update issue fields through Tempoy's constrained update flow |
| `add_ticket_to_allocation` | Add an issue to the allocation draft |
| `remove_ticket_from_allocation` | Remove an issue from the allocation draft |
| `set_allocation_units` | Set allocation units for a draft row |
| `set_allocation_lock` | Lock or unlock an allocation draft row |
| `equalize_allocation` | Equalize unlocked rows in the draft |
| `reset_allocation` | Reset the allocation draft |

## Session management

The MCP server manages Tempoy sessions transparently:

1. First tool call (other than `health`/`capabilities`) triggers session start
2. Session token is held in memory only — never written to disk
3. On HTTP 401, the server clears the token and retries once with a new session
4. On process shutdown, the server sends a best-effort session stop

## Using with VS Code

### Via the Tempoy extension

Install the Tempoy MCP VS Code extension from `vscode-extension/`. It auto-registers this MCP server with VS Code — no manual configuration needed.

### Via manual mcp.json

Create `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "tempoy": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "tempoy_app.mcp_server"],
      "env": {
        "PYTHONPATH": "${workspaceFolder}",
        "TEMPOY_API_BASE_URL": "http://127.0.0.1:8765",
        "TEMPOY_MCP_CLIENT_NAME": "tempoy-vscode"
      }
    }
  }
}
```

## Using with other MCP clients

Any MCP client that supports stdio transport can use this server. The general pattern:

1. Launch `python -m tempoy_app.mcp_server` as a subprocess
2. Communicate over stdin/stdout using the MCP protocol
3. The server advertises its tools via `tools/list`
4. Call tools via `tools/call` with the appropriate arguments

Example for Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "tempoy": {
      "command": "python",
      "args": ["-m", "tempoy_app.mcp_server"],
      "env": {
        "PYTHONPATH": "/path/to/tempoy",
        "TEMPOY_API_BASE_URL": "http://127.0.0.1:8765"
      }
    }
  }
}
```

## Security model

- The MCP server runs locally and connects only to `127.0.0.1`
- It never handles Jira credentials — those stay in the Tempoy application
- All operations are subject to Tempoy's policy enforcement (project/type/mode restrictions)
- Session tokens exist only in process memory
- Write operations go through Tempoy's preview/apply confirmation flow
- The server logs to stderr only; stdout is reserved for MCP protocol messages

## Logging

The server logs to stderr (never stdout, which is reserved for MCP protocol). Set `--verbose` or `TEMPOY_MCP_VERBOSE=1` for detailed DEBUG-level output.

In VS Code, MCP server stderr output appears in the Output panel under the MCP server's name.

## Architecture

```
MCP Client (VS Code, Claude Desktop, etc.)
    ↓ stdin/stdout (MCP protocol)
Tempoy MCP Server (this module)
    ↓ HTTP (localhost only)
Tempoy API (127.0.0.1:8765)
    ↓
Tempoy policy engine → Jira Cloud / Tempo
```
