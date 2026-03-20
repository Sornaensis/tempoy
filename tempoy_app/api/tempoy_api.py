from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any, Dict, Optional

from tempoy_app.api.copilot_routes import CopilotRoutes
from tempoy_app.config import AppConfig, ConfigManager
from tempoy_app.models_copilot_api import CopilotApiHealth
from tempoy_app.services.copilot_allocation_service import CopilotAllocationService
from tempoy_app.services.copilot_audit_service import CopilotAuditService
from tempoy_app.services.copilot_policy_service import CopilotPolicyError, CopilotPolicyService

if TYPE_CHECKING:
    from tempoy_app.api.jira import JiraClient


class TempoyApiServer:
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
        policy_service: Optional[CopilotPolicyService] = None,
        audit_service: Optional[CopilotAuditService] = None,
        jira_client_factory: Optional[callable] = None,
        allocation_service: Optional[CopilotAllocationService] = None,
        on_allocation_changed: Optional[callable] = None,
    ):
        self._policy_service = policy_service or CopilotPolicyService(
            config_loader=ConfigManager.load,
            config_saver=ConfigManager.save,
        )
        self._audit_service = audit_service or CopilotAuditService()
        config = self._policy_service.get_config()
        self._host = host
        self._requested_port = port if port is not None else config.copilot_api_port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._jira_client_factory = jira_client_factory or self._default_jira_client_factory
        self._allocation_service = allocation_service or CopilotAllocationService(
            config_loader=self._policy_service.get_config,
            config_saver=ConfigManager.save,
            on_state_changed=on_allocation_changed,
        )
        self._routes = CopilotRoutes(
            policy_service=self._policy_service,
            audit_service=self._audit_service,
            jira_client_factory=self._jira_client_factory,
            allocation_service=self._allocation_service,
        )

    @property
    def server_address(self) -> tuple[str, int]:
        if self._server is None:
            return (self._host, self._requested_port)
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> tuple[str, int]:
        config = self._policy_service.get_config()
        if not config.copilot_api_enabled:
            raise RuntimeError("Copilot API is disabled in config")
        if self._server is not None:
            return self.server_address

        server = ThreadingHTTPServer((self._host, self._requested_port), self._build_handler())
        server.tempoy_api = self
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, name="tempoy-copilot-api", daemon=True)
        self._thread.start()
        return self.server_address

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    def health_payload(self) -> Dict[str, object]:
        config = self._policy_service.get_config()
        host, port = self.server_address
        status = "ok" if config.copilot_api_enabled else "disabled"
        session_active = self._policy_service.has_active_session(config)
        return CopilotApiHealth(
            status=status,
            api_enabled=config.copilot_api_enabled,
            mode=config.copilot_api_mode,
            session_active=session_active,
            session_expires_at=config.copilot_session_expires_at if session_active else None,
            bound_host=host,
            bound_port=port,
        ).to_dict()

    def capabilities_payload(self) -> Dict[str, object]:
        return self._policy_service.get_capabilities().to_dict()

    def start_session(self, body: Dict[str, Any]) -> Dict[str, object]:
        client_name = str(body.get("client_name") or "").strip() or None
        session = self._policy_service.start_session(client_name=client_name)
        self._audit_service.log_event(
            operation="session.start",
            success=True,
            category="session",
            detail={"client_name": client_name},
        )
        return session.to_dict()

    def stop_session(self, token: Optional[str]) -> Dict[str, object]:
        result = self._policy_service.stop_session(token=token)
        self._audit_service.log_event(
            operation="session.stop",
            success=result,
            category="session",
            detail={},
        )
        return {"stopped": result}

    def _default_jira_client_factory(self) -> JiraClient:
        from tempoy_app.api.jira import JiraClient

        config = self._policy_service.get_config()
        if not (config.jira_base_url and config.jira_email and config.jira_api_token):
            raise RuntimeError("Jira is not configured")
        return JiraClient(config.jira_base_url, config.jira_email, config.jira_api_token)

    def _build_handler(self):
        outer = self

        class TempoyApiHandler(BaseHTTPRequestHandler):
            server_version = "TempoyCopilotAPI/0.1"

            def do_GET(self) -> None:
                try:
                    if self.path == "/health":
                        self._send_json(HTTPStatus.OK, outer.health_payload())
                        return
                    if self.path == "/capabilities":
                        self._send_json(HTTPStatus.OK, outer.capabilities_payload())
                        return
                    if self.path == "/projects":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.get_projects(token=token))
                        return
                    if self.path.startswith("/projects/") and self.path.endswith("/issue-types"):
                        token = self._read_bearer_token()
                        project_key = self.path.removeprefix("/projects/").removesuffix("/issue-types").strip("/")
                        self._send_json(HTTPStatus.OK, outer._routes.get_project_issue_types(project_key, token=token))
                        return
                    if self.path.startswith("/projects/") and self.path.endswith("/create-schema"):
                        token = self._read_bearer_token()
                        project_key = self.path.removeprefix("/projects/").removesuffix("/create-schema").strip("/")
                        self._send_json(HTTPStatus.OK, outer._routes.get_project_create_schema(project_key, token=token))
                        return
                    if self.path == "/allocation/draft":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.get_allocation_draft(token=token))
                        return
                    if self.path == "/custom-fields/schema":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.discover_custom_fields(token=token))
                        return
                    if self.path.startswith("/issues/") and self.path.endswith("/transitions"):
                        token = self._read_bearer_token()
                        issue_key = self.path.removeprefix("/issues/").removesuffix("/transitions")
                        self._send_json(HTTPStatus.OK, outer._routes.get_issue_transitions(issue_key, token=token))
                        return
                    if self.path.startswith("/issues/"):
                        token = self._read_bearer_token()
                        issue_key = self.path.removeprefix("/issues/")
                        self._send_json(HTTPStatus.OK, outer._routes.get_issue_detail(issue_key, token=token))
                        return
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                except CopilotPolicyError as exc:
                    status = HTTPStatus.UNAUTHORIZED if str(exc) == "Unauthorized" else HTTPStatus.FORBIDDEN
                    self._send_json(status, {"error": str(exc)})
                except ValueError as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                except RuntimeError as exc:
                    self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
                except Exception:
                    outer._audit_service.log_event(
                        operation=f"http.{self.command.lower()} {self.path}",
                        success=False,
                        category="server",
                        detail={"status": HTTPStatus.INTERNAL_SERVER_ERROR},
                    )
                    self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Internal server error"})

            def do_POST(self) -> None:
                try:
                    body = self._read_json_body()
                    if self.path == "/session/start":
                        self._send_json(HTTPStatus.OK, outer.start_session(body))
                        return
                    if self.path == "/session/stop":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer.stop_session(token))
                        return
                    if self.path == "/issues/search":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.search_issues(body, token=token))
                        return
                    if self.path == "/issues/hierarchy":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.get_issue_hierarchy(body, token=token))
                        return
                    if self.path == "/issues/create":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.create_issue(body, token=token))
                        return
                    if self.path == "/issues/update":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.update_issue(body, token=token))
                        return
                    if self.path == "/issues/update-custom-fields":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.update_custom_fields(body, token=token))
                        return
                    if self.path == "/issues/transition":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.transition_issue(body, token=token))
                        return
                    if self.path == "/allocation/add":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.add_allocation_issue(body, token=token))
                        return
                    if self.path == "/allocation/remove":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.remove_allocation_issue(body, token=token))
                        return
                    if self.path == "/allocation/set-units":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.set_allocation_units(body, token=token))
                        return
                    if self.path == "/allocation/set-lock":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.set_allocation_lock(body, token=token))
                        return
                    if self.path == "/allocation/equalize":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.equalize_allocation(token=token))
                        return
                    if self.path == "/allocation/reset":
                        token = self._read_bearer_token()
                        self._send_json(HTTPStatus.OK, outer._routes.reset_allocation(token=token))
                        return
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                except CopilotPolicyError as exc:
                    status = HTTPStatus.UNAUTHORIZED if str(exc) == "Unauthorized" else HTTPStatus.FORBIDDEN
                    self._send_json(status, {"error": str(exc)})
                except ValueError as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                except RuntimeError as exc:
                    self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
                except Exception:
                    outer._audit_service.log_event(
                        operation=f"http.{self.command.lower()} {self.path}",
                        success=False,
                        category="server",
                        detail={"status": HTTPStatus.INTERNAL_SERVER_ERROR},
                    )
                    self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Internal server error"})

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _read_json_body(self) -> Dict[str, Any]:
                raw_length = self.headers.get("Content-Length", "0")
                try:
                    content_length = max(0, int(raw_length))
                except ValueError as exc:
                    raise ValueError("Invalid Content-Length") from exc
                if content_length == 0:
                    return {}
                raw_body = self.rfile.read(content_length)
                if not raw_body:
                    return {}
                try:
                    parsed = json.loads(raw_body.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    raise ValueError("Request body must be valid JSON") from exc
                if not isinstance(parsed, dict):
                    raise ValueError("Request body must be a JSON object")
                return parsed

            def _read_bearer_token(self) -> Optional[str]:
                authorization = self.headers.get("Authorization", "")
                prefix = "Bearer "
                if not authorization.startswith(prefix):
                    return None
                token = authorization[len(prefix):].strip()
                return token or None

            def _send_json(self, status: HTTPStatus, payload: Dict[str, object]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(int(status))
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return TempoyApiHandler


def create_tempoy_api_server(config: Optional[AppConfig] = None) -> TempoyApiServer:
    if config is None:
        return TempoyApiServer()

    current_config = config

    def load_config() -> AppConfig:
        return current_config

    def save_config(updated: AppConfig) -> None:
        nonlocal current_config
        current_config = updated

    return TempoyApiServer(
        port=config.copilot_api_port,
        policy_service=CopilotPolicyService(config_loader=load_config, config_saver=save_config),
    )