"""Install or remove Tempoy MCP server entries in AI tool configurations.

Targets:
  - VS Code / Copilot  (user mcp.json → servers.tempoy)
  - Claude Code         (~/.claude.json → mcpServers.tempoy)
  - Claude Desktop      (claude_desktop_config.json → mcpServers.tempoy)

Usage:
  python -m tempoy_app.setup_mcp_config install
  python -m tempoy_app.setup_mcp_config uninstall
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TEMPOY_DIR = Path.home() / ".tempoy"
MCP_SERVER_NAME = "tempoy"

# ---------------------------------------------------------------------------
# Colour helpers (auto-disabled when stdout isn't a terminal)
# ---------------------------------------------------------------------------

_USE_COLOUR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOUR else text


def _green(t: str) -> str:
    return _c("92", t)


def _yellow(t: str) -> str:
    return _c("93", t)


def _red(t: str) -> str:
    return _c("91", t)


def _blue(t: str) -> str:
    return _c("94", t)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _venv_python() -> str:
    """Absolute path to the venv Python interpreter."""
    if platform.system() == "Windows":
        return str(TEMPOY_DIR / "venv" / "Scripts" / "python.exe")
    return str(TEMPOY_DIR / "venv" / "bin" / "python")


def _mcp_entry_claude(client_name: str = "tempoy-mcp") -> Dict[str, Any]:
    """MCP server entry for Claude configs (no 'type' field)."""
    return {
        "command": _venv_python(),
        "args": ["-m", "tempoy_app.mcp_server"],
        "env": {
            "PYTHONPATH": str(TEMPOY_DIR),
            "TEMPOY_API_BASE_URL": "http://127.0.0.1:8765",
            "TEMPOY_MCP_CLIENT_NAME": client_name,
        },
    }


def _mcp_entry_vscode() -> Dict[str, Any]:
    """MCP server entry for VS Code settings.json (has 'type' field)."""
    return {
        "type": "stdio",
        "command": _venv_python(),
        "args": ["-m", "tempoy_app.mcp_server"],
        "env": {
            "PYTHONPATH": str(TEMPOY_DIR),
            "TEMPOY_API_BASE_URL": "http://127.0.0.1:8765",
            "TEMPOY_MCP_CLIENT_NAME": "tempoy-copilot",
        },
    }


# ---------------------------------------------------------------------------
# JSONC helpers  (VS Code settings.json may contain comments)
# ---------------------------------------------------------------------------


def _strip_jsonc(text: str) -> str:
    """Remove ``//`` and ``/* */`` comments from JSONC, preserving strings."""
    # Phase 1: block comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # Phase 2: line comments (skip content inside strings)
    out: list[str] = []
    in_string = False
    esc = False
    i = 0
    while i < len(text):
        ch = text[i]
        if esc:
            out.append(ch)
            esc = False
            i += 1
            continue
        if ch == "\\" and in_string:
            out.append(ch)
            esc = True
            i += 1
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            i += 1
            continue
        if not in_string and ch == "/" and i + 1 < len(text) and text[i + 1] == "/":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)


# ---------------------------------------------------------------------------
# Safe JSON read / write
# ---------------------------------------------------------------------------


def _read_json(path: Path, *, jsonc: bool = False) -> Optional[Dict[str, Any]]:
    """Read a JSON (or JSONC) file.  Returns ``{}`` if missing, ``None`` on parse error."""
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        if jsonc:
            raw = _strip_jsonc(raw)
        raw = _remove_trailing_commas(raw)
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _backup(path: Path) -> Optional[Path]:
    if path.exists():
        bak = path.with_suffix(path.suffix + ".tempoy-backup")
        shutil.copy2(path, bak)
        return bak
    return None


# ---------------------------------------------------------------------------
# Target discovery
# ---------------------------------------------------------------------------


def _vscode_mcp_paths() -> List[Tuple[str, Path]]:
    """Return (label, path) pairs for every detected VS Code variant's mcp.json."""
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", ""))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"

    results: List[Tuple[str, Path]] = []
    for variant in ("Code", "Code - Insiders", "Cursor"):
        mcp_json = base / variant / "User" / "mcp.json"
        # Include if the editor User directory exists (even if mcp.json doesn't yet)
        if (base / variant / "User").is_dir() or mcp_json.exists():
            results.append((variant, mcp_json))
    return results


def _claude_code_path() -> Path:
    return Path.home() / ".claude.json"


def _claude_desktop_path() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


# ---------------------------------------------------------------------------
# Install / uninstall logic
# ---------------------------------------------------------------------------


def _install_vscode(label: str, path: Path) -> bool:
    data = _read_json(path, jsonc=True)
    if data is None:
        print(_yellow(f"  ⚠ {label}: mcp.json has unparseable content — skipped"))
        return False

    _backup(path)
    servers = data.setdefault("servers", {})
    servers[MCP_SERVER_NAME] = _mcp_entry_vscode()
    _write_json(path, data)
    print(_green(f"  ✓ {label}: MCP server configured"))
    return True


def _uninstall_vscode(label: str, path: Path) -> bool:
    data = _read_json(path, jsonc=True)
    if data is None or "servers" not in data:
        return False
    servers = data.get("servers", {})
    if MCP_SERVER_NAME not in servers:
        return False
    _backup(path)
    del servers[MCP_SERVER_NAME]
    if not servers:
        del data["servers"]
    _write_json(path, data)
    print(_green(f"  ✓ {label}: MCP server entry removed"))
    return True


def _install_claude(label: str, path: Path, client_name: str) -> bool:
    data = _read_json(path)
    if data is None:
        print(_yellow(f"  ⚠ {label}: config has unparseable content — skipped"))
        return False

    _backup(path)
    servers = data.setdefault("mcpServers", {})
    servers[MCP_SERVER_NAME] = _mcp_entry_claude(client_name)
    _write_json(path, data)
    print(_green(f"  ✓ {label}: MCP server configured"))
    return True


def _uninstall_claude(label: str, path: Path) -> bool:
    data = _read_json(path)
    if data is None or "mcpServers" not in data:
        return False
    servers = data.get("mcpServers", {})
    if MCP_SERVER_NAME not in servers:
        return False
    _backup(path)
    del servers[MCP_SERVER_NAME]
    if not servers:
        del data["mcpServers"]
    _write_json(path, data)
    print(_green(f"  ✓ {label}: MCP server entry removed"))
    return True


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def install() -> int:
    """Add Tempoy MCP server to all detected AI tool configurations."""
    print(_blue("Configuring Tempoy MCP server..."))
    configured = 0

    # VS Code / Copilot (user-level mcp.json)
    for label, path in _vscode_mcp_paths():
        if _install_vscode(label, path):
            configured += 1

    if not _vscode_mcp_paths():
        print(_yellow("  No VS Code installation detected — Copilot MCP skipped"))

    # Claude Code
    if _install_claude("Claude Code", _claude_code_path(), "tempoy-claude-code"):
        configured += 1

    # Claude Desktop
    desktop_path = _claude_desktop_path()
    if desktop_path.parent.is_dir():
        if _install_claude("Claude Desktop", desktop_path, "tempoy-claude-desktop"):
            configured += 1
    else:
        print(_yellow("  Claude Desktop not detected — skipped"))

    if configured:
        print(_green(f"✓ MCP server configured in {configured} location(s)"))
    else:
        print(_yellow("No AI tool configurations were updated"))
    return 0


def uninstall() -> int:
    """Remove Tempoy MCP server from all AI tool configurations."""
    print(_blue("Removing Tempoy MCP server configuration..."))
    removed = 0

    for label, path in _vscode_mcp_paths():
        if _uninstall_vscode(label, path):
            removed += 1

    if _uninstall_claude("Claude Code", _claude_code_path()):
        removed += 1

    if _uninstall_claude("Claude Desktop", _claude_desktop_path()):
        removed += 1

    if removed:
        print(_green(f"✓ MCP server removed from {removed} location(s)"))
    else:
        print("  No Tempoy MCP entries found to remove")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] not in ("install", "uninstall"):
        print("Usage: python -m tempoy_app.setup_mcp_config {install|uninstall}", file=sys.stderr)
        return 2
    return install() if args[0] == "install" else uninstall()


if __name__ == "__main__":
    sys.exit(main())
