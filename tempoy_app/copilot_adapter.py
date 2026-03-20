from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple


class TempoyApiAdapterError(RuntimeError):
    pass


class TempoyApiAdapter:
    def __init__(self, *, base_url: str = "http://127.0.0.1:8765", token: Optional[str] = None):
        self._base_url = str(base_url or "").rstrip("/")
        self._token = str(token or "").strip() or None

    @property
    def token(self) -> Optional[str]:
        return self._token

    def set_token(self, token: Optional[str]) -> None:
        self._token = str(token or "").strip() or None

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/health")

    def capabilities(self) -> Dict[str, Any]:
        return self._request("GET", "/capabilities")

    def start_session(self, *, client_name: str = "copilot-adapter") -> Dict[str, Any]:
        payload = self._request("POST", "/session/start", {"client_name": client_name}, include_token=False)
        token = str(payload.get("token") or "").strip()
        if token:
            self._token = token
        return payload

    def stop_session(self) -> Dict[str, Any]:
        payload = self._request("POST", "/session/stop", {})
        if payload.get("stopped"):
            self._token = None
        return payload

    def list_projects(self) -> Dict[str, Any]:
        return self._request("GET", "/projects")

    def list_project_issue_types(self, project_key: str) -> Dict[str, Any]:
        return self._request("GET", f"/projects/{self._normalize_key(project_key)}/issue-types")

    def get_project_create_schema(self, project_key: str) -> Dict[str, Any]:
        return self._request("GET", f"/projects/{self._normalize_key(project_key)}/create-schema")

    def search_tickets(self, **body: Any) -> Dict[str, Any]:
        return self._request("POST", "/issues/search", body)

    def get_issue_details(self, issue_key: str) -> Dict[str, Any]:
        return self._request("GET", f"/issues/{self._normalize_key(issue_key)}")

    def analyze_hierarchy(self, **body: Any) -> Dict[str, Any]:
        return self._request("POST", "/issues/hierarchy", body)

    def create_ticket(self, **body: Any) -> Dict[str, Any]:
        payload = dict(body)
        payload["issue_type"] = "Task"
        return self._request("POST", "/issues/create", payload)

    def update_issue_fields(self, **body: Any) -> Dict[str, Any]:
        return self._request("POST", "/issues/update", body)

    def get_issue_transitions(self, issue_key: str) -> Dict[str, Any]:
        return self._request("GET", f"/issues/{self._normalize_key(issue_key)}/transitions")

    def transition_issue(self, **body: Any) -> Dict[str, Any]:
        return self._request("POST", "/issues/transition", body)

    def get_allocation_draft(self) -> Dict[str, Any]:
        return self._request("GET", "/allocation/draft")

    def add_ticket_to_allocation(self, **body: Any) -> Dict[str, Any]:
        return self._request("POST", "/allocation/add", body)

    def remove_ticket_from_allocation(self, **body: Any) -> Dict[str, Any]:
        return self._request("POST", "/allocation/remove", body)

    def set_allocation_units(self, **body: Any) -> Dict[str, Any]:
        return self._request("POST", "/allocation/set-units", body)

    def set_allocation_lock(self, **body: Any) -> Dict[str, Any]:
        return self._request("POST", "/allocation/set-lock", body)

    def equalize_allocation(self) -> Dict[str, Any]:
        return self._request("POST", "/allocation/equalize", {})

    def reset_allocation(self) -> Dict[str, Any]:
        return self._request("POST", "/allocation/reset", {})

    def discover_custom_fields(self) -> Dict[str, Any]:
        return self._request("GET", "/custom-fields/schema")

    def update_custom_fields(self, **body: Any) -> Dict[str, Any]:
        return self._request("POST", "/issues/update-custom-fields", body)

    def invoke(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        normalized_tool_name = str(tool_name or "").strip()
        handlers = {
            "health": lambda payload: self.health(),
            "capabilities": lambda payload: self.capabilities(),
            "start_session": lambda payload: self.start_session(client_name=str((payload or {}).get("client_name") or "copilot-adapter")),
            "stop_session": lambda payload: self.stop_session(),
            "list_projects": lambda payload: self.list_projects(),
            "list_project_issue_types": lambda payload: self.list_project_issue_types(str((payload or {}).get("project_key") or "")),
            "get_project_create_schema": lambda payload: self.get_project_create_schema(str((payload or {}).get("project_key") or "")),
            "search_tickets": lambda payload: self.search_tickets(**(payload or {})),
            "get_issue_details": lambda payload: self.get_issue_details(str((payload or {}).get("issue_key") or "")),
            "analyze_hierarchy": lambda payload: self.analyze_hierarchy(**(payload or {})),
            "create_ticket": lambda payload: self.create_ticket(**(payload or {})),
            "update_issue_fields": lambda payload: self.update_issue_fields(**(payload or {})),
            "get_issue_transitions": lambda payload: self.get_issue_transitions(str((payload or {}).get("issue_key") or "")),
            "transition_issue": lambda payload: self.transition_issue(**(payload or {})),
            "get_allocation_draft": lambda payload: self.get_allocation_draft(),
            "add_ticket_to_allocation": lambda payload: self.add_ticket_to_allocation(**(payload or {})),
            "remove_ticket_from_allocation": lambda payload: self.remove_ticket_from_allocation(**(payload or {})),
            "set_allocation_units": lambda payload: self.set_allocation_units(**(payload or {})),
            "set_allocation_lock": lambda payload: self.set_allocation_lock(**(payload or {})),
            "equalize_allocation": lambda payload: self.equalize_allocation(),
            "reset_allocation": lambda payload: self.reset_allocation(),
            "discover_custom_fields": lambda payload: self.discover_custom_fields(),
            "update_custom_fields": lambda payload: self.update_custom_fields(**(payload or {})),
        }
        if normalized_tool_name not in handlers:
            raise TempoyApiAdapterError(f"Unknown tool: {normalized_tool_name}")
        return handlers[normalized_tool_name](arguments or {})

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        include_token: bool = True,
    ) -> Dict[str, Any]:
        url = f"{self._base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if include_token and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8") if exc.fp is not None else ""
            detail = raw_body
            if raw_body:
                try:
                    parsed = json.loads(raw_body)
                    if isinstance(parsed, dict):
                        detail = str(parsed.get("error") or raw_body)
                except json.JSONDecodeError:
                    detail = raw_body
            if exc.code == 401:
                self._token = None
            raise TempoyApiAdapterError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise TempoyApiAdapterError(f"Connection failed: {exc.reason}") from exc

    @staticmethod
    def _normalize_key(value: str) -> str:
        normalized = str(value or "").strip().upper()
        if not normalized:
            raise TempoyApiAdapterError("A project or issue key is required")
        return normalized


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Thin adapter for Tempoy's localhost Copilot API")
    parser.add_argument("tool", help="Tool name to invoke, such as search_tickets or get_issue_details")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765", help="Tempoy API base URL")
    parser.add_argument("--token", default=None, help="Session token returned by /session/start")
    parser.add_argument("--args", default="{}", help="JSON object of tool arguments")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        tool_args = json.loads(args.args)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"Invalid JSON for --args: {exc.msg}"}), file=sys.stderr)
        return 2
    if not isinstance(tool_args, dict):
        print(json.dumps({"error": "--args must decode to a JSON object"}), file=sys.stderr)
        return 2

    adapter = TempoyApiAdapter(base_url=args.base_url, token=args.token)
    try:
        result = adapter.invoke(args.tool, tool_args)
    except TempoyApiAdapterError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    output = {"tool": args.tool, "result": result}
    if adapter.token:
        output["token"] = adapter.token
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())