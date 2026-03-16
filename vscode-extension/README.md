# Tempoy MCP VS Code Extension

This extension is a thin VS Code integration layer for the Tempoy MCP server.

It does not talk to Jira directly. Instead, it publishes the local Python Tempoy MCP server to VS Code, which then talks to the Tempoy localhost API.

## Prerequisites

1. **Tempoy application** must be running locally with the Copilot API enabled in Tempoy settings.
2. **Python 3.10+** with the `mcp` package installed (`pip install mcp>=1.26`).
3. The Tempoy repo must be available locally so the MCP server module can be imported.

## How it works

```
VS Code Agent / Copilot Chat
    ↓
VS Code MCP host
    ↓
Tempoy MCP Server (stdio, Python)
    ↓
Tempoy localhost API (127.0.0.1:8765)
    ↓
Tempoy policy + Jira/Tempo integration
```

The extension registers a `McpStdioServerDefinition` that launches the Python MCP server as a child process. VS Code manages the process lifecycle. The MCP server automatically starts and stops Tempoy API sessions as needed.

## Extension settings

| Setting | Default | Description |
|---------|---------|-------------|
| `tempoy.apiBaseUrl` | *(empty)* | Base URL for the local Tempoy API. Leave empty to auto-detect from `~/.tempoy/config.json`. Falls back to `http://127.0.0.1:8765`. |
| `tempoy.mcp.pythonCommand` | `python` | Python command used to launch the MCP server |
| `tempoy.mcp.clientName` | `tempoy-vscode` | Client name for Tempoy API sessions |
| `tempoy.mcp.serverVersion` | `0.1.0` | Version tag for the MCP server definition |

If you use a Python virtual environment, set `tempoy.mcp.pythonCommand` to the full path of the Python executable inside it.

## Port auto-detection

When `tempoy.apiBaseUrl` is not set, the extension reads the Tempoy config file at `~/.tempoy/config.json` and uses the `copilot_api_port` value. If the file doesn't exist or the key is missing, it falls back to the default port 8765.

This means the extension automatically picks up whatever port Tempoy is configured to use — no manual setting needed in most cases.

## Commands

| Command | Description |
|---------|-------------|
| `Tempoy: Check API Health` | Ping the Tempoy API and show status |
| `Tempoy: Show Tempoy Connection Status` | Open a detailed connection report |
| `Tempoy: Open MCP Configuration` | Create or open `.vscode/mcp.json` with a pre-populated Tempoy entry |
| `Tempoy: Start MCP Session Test` | Start a Tempoy API session to verify connectivity |

## Status bar

The extension shows a status bar item on the right side:

- **$(check) Tempoy: preview** — Tempoy API is reachable (shows current mode)
- **$(warning) Tempoy: offline** — Tempoy API is not reachable

Click the status bar item to open the connection status report.

## Manual MCP configuration (without the extension)

If you prefer not to install the extension, you can register the Tempoy MCP server manually.

### Workspace configuration

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

Adjust `command` to point to your Python interpreter and `PYTHONPATH` to the Tempoy repo root if different from the workspace folder.

### User-level configuration

Add the same server entry to your VS Code user settings under `mcp.servers` to make the Tempoy MCP server available in all workspaces.

## Troubleshooting

### Tempoy API not reachable

- Ensure the Tempoy desktop application is running.
- Ensure the Copilot API is enabled in Tempoy settings.
- Check that the port matches `tempoy.apiBaseUrl` (default: 8765).
- Run `Tempoy: Check API Health` to verify connectivity.

### MCP server fails to start

- Ensure Python is on your PATH or set `tempoy.mcp.pythonCommand` to the full path.
- Ensure the `mcp` package is installed: `pip install mcp>=1.26`.
- Ensure `PYTHONPATH` includes the Tempoy repo root so `tempoy_app.mcp_server` is importable.
- Check the MCP server output in VS Code's Output panel for stderr logs.

### Session errors

The MCP server manages Tempoy sessions automatically. If you see authentication errors:

- Ensure no other MCP client or CLI session is consuming the same Tempoy session slot.
- The server retries once on session expiry. Persistent 401 errors indicate a configuration or policy issue.

## Development

```powershell
cd vscode-extension
npm install
npm run build     # compile TypeScript
npm run watch     # compile on change
```

The compiled output goes to `dist/`. The extension's `main` entry point is `dist/extension.js`.
