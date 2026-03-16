from __future__ import annotations

import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from tempoy_app.api.tempoy_api import TempoyApiServer
from tempoy_app.config import AppConfig
from tempoy_app.services.copilot_allocation_service import CopilotAllocationService
from tempoy_app.services.copilot_audit_service import CopilotAuditService
from tempoy_app.services.copilot_policy_service import CopilotPolicyService


class _FakeJiraClient:
    def __init__(self):
        self.base_url = "https://example.atlassian.net"
        self.search_calls = []
        self.get_issue_calls = []
        self.get_issues_by_keys_calls = []
        self.get_projects_calls = []
        self.get_project_issue_types_calls = []
        self.get_create_schema_calls = []
        self.create_issue_calls = []
        self.get_edit_schema_calls = []
        self.update_issue_calls = []
        self.search_children_calls = []

    def search_issues(self, **kwargs):
        self.search_calls.append(dict(kwargs))
        return [
            {
                "id": "101",
                "key": "ABC-1",
                "fields": {
                    "summary": "First issue",
                    "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hello world"}]}]},
                    "status": {"name": "In Progress"},
                    "issuetype": {"name": "Task"},
                    "project": {"key": "ABC"},
                    "priority": {"name": "Medium"},
                    "labels": ["backend"],
                    "parent": {"key": "ABC-0", "fields": {"summary": "Platform"}},
                    "issuelinks": [
                        {"type": {"outward": "relates to"}, "outwardIssue": {"key": "ABC-2", "fields": {"summary": "Neighbor"}}}
                    ],
                },
            },
            {
                "id": "202",
                "key": "OPS-1",
                "fields": {
                    "summary": "Other project issue",
                    "status": {"name": "To Do"},
                    "issuetype": {"name": "Task"},
                    "project": {"key": "OPS"},
                },
            },
        ]

    def get_issue(self, issue_key, fields=None):
        self.get_issue_calls.append({"issue_key": issue_key, "fields": fields})
        if issue_key == "ABC-99":
            return {
                "id": "501",
                "key": issue_key,
                "fields": {
                    "summary": "Created task",
                    "description": "Created from API",
                    "status": {"name": "To Do"},
                    "issuetype": {"name": "Task"},
                    "project": {"key": "ABC"},
                    "priority": {"name": "Highest"},
                    "labels": ["api"],
                },
            }
        return {
            "id": "101",
            "key": issue_key,
            "fields": {
                "summary": "First issue",
                "description": "Already plain text",
                "status": {"name": "In Progress"},
                "issuetype": {"name": "Task"},
                "project": {"key": "ABC"},
                "priority": {"name": "Medium"},
                "labels": ["backend"],
                "customfield_10014": "EPIC-1",
            },
        }

    def get_issues_by_keys(self, issue_keys, fields=None, order_by_updated=False):
        self.get_issues_by_keys_calls.append({"issue_keys": list(issue_keys), "fields": fields, "order_by_updated": order_by_updated})
        issues = {
            "ABC-1": {
                "id": "101",
                "key": "ABC-1",
                "fields": {
                    "summary": "First issue",
                    "description": "Already plain text",
                    "status": {"name": "In Progress"},
                    "issuetype": {"name": "Task"},
                    "project": {"key": "ABC"},
                    "priority": {"name": "Medium"},
                    "labels": ["backend"],
                    "parent": {"key": "EPIC-1", "fields": {"summary": "Epic summary"}},
                    "issuelinks": [
                        {"type": {"outward": "relates to"}, "outwardIssue": {"key": "ABC-2", "fields": {"summary": "Neighbor"}}}
                    ],
                },
            },
            "EPIC-1": {
                "id": "301",
                "key": "EPIC-1",
                "fields": {
                    "summary": "Epic summary",
                    "status": {"name": "To Do"},
                    "issuetype": {"name": "Epic"},
                    "project": {"key": "ABC"},
                    "priority": {"name": "High"},
                },
            },
            "ABC-2": {
                "id": "202",
                "key": "ABC-2",
                "fields": {
                    "summary": "Neighbor",
                    "status": {"name": "To Do"},
                    "issuetype": {"name": "Task"},
                    "project": {"key": "ABC"},
                    "priority": {"name": "Low"},
                },
            },
        }
        return [issues[key] for key in issue_keys if key in issues]

    def search_children(self, parent_keys, *, fields=None, max_results=50):
        self.search_children_calls.append({"parent_keys": list(parent_keys), "fields": fields, "max_results": max_results})
        children = {
            "ABC-1": [
                {
                    "id": "401",
                    "key": "ABC-10",
                    "fields": {
                        "summary": "Child task one",
                        "status": {"name": "To Do"},
                        "issuetype": {"name": "Sub-task"},
                        "project": {"key": "ABC"},
                        "priority": {"name": "Medium"},
                        "parent": {"key": "ABC-1", "fields": {"summary": "First issue"}},
                    },
                },
                {
                    "id": "402",
                    "key": "ABC-11",
                    "fields": {
                        "summary": "Child task two",
                        "status": {"name": "In Progress"},
                        "issuetype": {"name": "Sub-task"},
                        "project": {"key": "ABC"},
                        "priority": {"name": "Low"},
                        "parent": {"key": "ABC-1", "fields": {"summary": "First issue"}},
                    },
                },
            ],
        }
        result = []
        for key in parent_keys:
            result.extend(children.get(key, []))
        return result

    def get_projects(self, max_results=100):
        self.get_projects_calls.append({"max_results": max_results})
        return [
            {"id": "1", "key": "ABC", "name": "Alpha", "projectTypeKey": "software", "simplified": False, "style": "classic"},
            {"id": "2", "key": "OPS", "name": "Operations", "projectTypeKey": "service_desk", "simplified": True, "style": "next-gen"},
        ]

    def get_project_issue_types(self, project_key):
        self.get_project_issue_types_calls.append({"project_key": project_key})
        return [
            {"id": "10", "name": "Task", "description": "Standard work", "subtask": False},
            {"id": "11", "name": "Epic", "description": "Large body of work", "subtask": False},
            {"id": "12", "name": "Sub-task", "description": "Child work", "subtask": True},
        ]

    def get_create_schema(self, project_key, issue_type_ids=None):
        self.get_create_schema_calls.append({"project_key": project_key, "issue_type_ids": issue_type_ids})
        return [
            {
                "issueTypeId": "10",
                "name": "Task",
                "fields": {
                    "summary": {
                        "name": "Summary",
                        "required": True,
                        "schema": {"type": "string"},
                        "operations": ["set"],
                    },
                    "priority": {
                        "name": "Priority",
                        "required": False,
                        "schema": {"type": "option", "custom": "com.atlassian.jira.plugin.system.customfieldtypes:select"},
                        "allowedValues": [{"id": "1", "name": "Highest"}, {"id": "2", "name": "Medium"}],
                        "operations": ["set"],
                    },
                },
            },
            {
                "issueTypeId": "11",
                "name": "Epic",
                "fields": {
                    "summary": {
                        "name": "Summary",
                        "required": True,
                        "schema": {"type": "string"},
                        "operations": ["set"],
                    }
                },
            },
        ]

    def create_issue(self, fields):
        self.create_issue_calls.append(fields)
        return {"id": "501", "key": "ABC-99"}

    def get_edit_schema(self, issue_key):
        self.get_edit_schema_calls.append({"issue_key": issue_key})
        return {
            "fields": {
                "summary": {"name": "Summary", "schema": {"type": "string"}, "operations": ["set"]},
                "description": {"name": "Description", "schema": {"type": "string"}, "operations": ["set"]},
                "labels": {"name": "Labels", "schema": {"type": "array", "items": "string"}, "operations": ["set"]},
                "priority": {
                    "name": "Priority",
                    "schema": {"type": "option"},
                    "allowedValues": [{"id": "1", "name": "Highest"}, {"id": "2", "name": "Medium"}],
                    "operations": ["set"],
                },
                "parent": {"name": "Parent", "schema": {"type": "issuelink"}, "operations": ["set"]},
                "customfield_12345": {"name": "Acceptance Criteria", "schema": {"type": "string"}, "operations": ["set"]},
            }
        }

    def update_issue(self, issue_key, fields):
        self.update_issue_calls.append({"issue_key": issue_key, "fields": fields})
        return {}


class _ConfigStore:
    def __init__(self, config: AppConfig):
        self.config = config

    def load(self) -> AppConfig:
        return self.config

    def save(self, config: AppConfig) -> None:
        self.config = config


class CopilotPolicyServiceTests(unittest.TestCase):
    def test_get_capabilities_respects_mode_and_session_state(self) -> None:
        store = _ConfigStore(
            AppConfig(
                copilot_api_enabled=True,
                copilot_api_mode="refine-only",
                copilot_allowed_projects=["ABC"],
                copilot_allowed_issue_types=["Task"],
                copilot_session_token="token-1",
            )
        )
        service = CopilotPolicyService(config_loader=store.load, config_saver=store.save)

        capabilities = service.get_capabilities()

        self.assertTrue(capabilities.api_enabled)
        self.assertEqual(capabilities.mode, "refine-only")
        self.assertTrue(capabilities.session_active)
        self.assertTrue(capabilities.endpoints["issues_refine"])
        self.assertFalse(capabilities.endpoints["issues_create"])

    def test_project_policy_allows_all_projects_when_allowlist_empty(self) -> None:
        store = _ConfigStore(AppConfig(copilot_api_enabled=True, copilot_allowed_projects=[]))
        service = CopilotPolicyService(config_loader=store.load, config_saver=store.save)

        self.assertTrue(service.is_project_allowed("ABC"))
        self.assertTrue(service.is_project_allowed("xyz"))
        self.assertEqual(service.filter_allowed_projects(["ABC", "xyz", ""]), ["ABC", "xyz"])

    def test_project_policy_filters_when_allowlist_present(self) -> None:
        store = _ConfigStore(AppConfig(copilot_api_enabled=True, copilot_allowed_projects=["ABC", "PLAT"]))
        service = CopilotPolicyService(config_loader=store.load, config_saver=store.save)

        self.assertTrue(service.is_project_allowed("abc"))
        self.assertFalse(service.is_project_allowed("OPS"))
        self.assertEqual(service.filter_allowed_projects(["ops", "abc", "plat"]), ["ABC", "PLAT"])

    def test_expired_session_is_cleared_when_validated(self) -> None:
        store = _ConfigStore(
            AppConfig(
                copilot_api_enabled=True,
                copilot_session_token="token-1",
                copilot_session_expires_at=50,
            )
        )
        service = CopilotPolicyService(config_loader=store.load, config_saver=store.save, time_provider=lambda: 60)

        with self.assertRaises(RuntimeError):
            service.require_session_token("token-1")

        self.assertIsNone(store.config.copilot_session_token)
        self.assertIsNone(store.config.copilot_session_expires_at)

    def test_start_session_sets_expiry_timestamp(self) -> None:
        store = _ConfigStore(
            AppConfig(
                copilot_api_enabled=True,
                copilot_api_mode="read-only",
                copilot_session_ttl_seconds=120,
            )
        )
        service = CopilotPolicyService(config_loader=store.load, config_saver=store.save, time_provider=lambda: 1000)

        session = service.start_session(client_name="tests")

        self.assertEqual(session.expires_at, 1120)
        self.assertEqual(store.config.copilot_session_expires_at, 1120)


class TempoyApiServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.fake_jira_client = _FakeJiraClient()
        self.store = _ConfigStore(
            AppConfig(
                copilot_api_enabled=True,
                copilot_api_port=0,
                copilot_api_mode="read-only",
                copilot_allowed_projects=[],
            )
        )
        self.server = TempoyApiServer(
            port=0,
            policy_service=CopilotPolicyService(config_loader=self.store.load, config_saver=self.store.save),
            audit_service=CopilotAuditService(log_path=self.temp_dir.name + "/audit.log"),
            jira_client_factory=lambda: self.fake_jira_client,
            allocation_service=CopilotAllocationService(
                config_loader=self.store.load,
                daily_total_resolver=lambda config: 1800,
            ),
        )
        host, port = self.server.start()
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.stop()
        self.temp_dir.cleanup()

    def _request(self, method: str, path: str, *, payload=None, headers=None):
        data = None
        final_headers = dict(headers or {})
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            final_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(self.base_url + path, data=data, headers=final_headers, method=method)
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_and_capabilities_endpoints_return_expected_payloads(self) -> None:
        health_status, health = self._request("GET", "/health")
        capabilities_status, capabilities = self._request("GET", "/capabilities")

        self.assertEqual(health_status, 200)
        self.assertEqual(health["status"], "ok")
        self.assertTrue(health["api_enabled"])
        self.assertEqual(health["bound_host"], "127.0.0.1")
        self.assertEqual(capabilities_status, 200)
        self.assertEqual(capabilities["allowed_projects"], [])
        self.assertTrue(capabilities["endpoints"]["issues_read"])
        self.assertFalse(capabilities["endpoints"]["issues_create"])

    def test_session_start_and_stop_require_expected_auth(self) -> None:
        start_status, start_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        self.assertEqual(start_status, 200)
        self.assertEqual(start_payload["mode"], "read-only")
        token = start_payload["token"]
        self.assertTrue(token)
        self.assertGreater(start_payload["expires_at"], int(time.time()))

        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._request("POST", "/session/stop", payload={})
        self.assertEqual(exc_info.exception.code, 401)

        stop_status, stop_payload = self._request(
            "POST",
            "/session/stop",
            payload={},
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(stop_status, 200)
        self.assertEqual(stop_payload, {"stopped": True})
        self.assertIsNone(self.store.config.copilot_session_token)

    def test_health_and_capabilities_treat_expired_session_as_inactive(self) -> None:
        self.server.stop()
        self.store.config.copilot_session_token = "expired-token"
        self.store.config.copilot_session_expires_at = 1
        policy_service = CopilotPolicyService(
            config_loader=self.store.load,
            config_saver=self.store.save,
            time_provider=lambda: 10,
        )
        self.server = TempoyApiServer(
            port=0,
            policy_service=policy_service,
            audit_service=CopilotAuditService(log_path=self.temp_dir.name + "/audit.log"),
            jira_client_factory=lambda: self.fake_jira_client,
            allocation_service=CopilotAllocationService(
                config_loader=self.store.load,
                daily_total_resolver=lambda config: 1800,
            ),
        )
        host, port = self.server.start()
        self.base_url = f"http://{host}:{port}"

        _, health = self._request("GET", "/health")
        _, capabilities = self._request("GET", "/capabilities")

        self.assertFalse(health["session_active"])
        self.assertIsNone(health["session_expires_at"])
        self.assertFalse(capabilities["session_active"])
        self.assertIsNone(capabilities["session_expires_at"])

    def test_expired_session_token_is_rejected_by_server(self) -> None:
        self.server.stop()
        self.store.config.copilot_session_token = "expired-token"
        self.store.config.copilot_session_expires_at = 1
        policy_service = CopilotPolicyService(
            config_loader=self.store.load,
            config_saver=self.store.save,
            time_provider=lambda: 10,
        )
        self.server = TempoyApiServer(
            port=0,
            policy_service=policy_service,
            audit_service=CopilotAuditService(log_path=self.temp_dir.name + "/audit.log"),
            jira_client_factory=lambda: self.fake_jira_client,
            allocation_service=CopilotAllocationService(
                config_loader=self.store.load,
                daily_total_resolver=lambda config: 1800,
            ),
        )
        host, port = self.server.start()
        self.base_url = f"http://{host}:{port}"

        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._request(
                "GET",
                "/projects",
                headers={"Authorization": "Bearer expired-token"},
            )

        self.assertEqual(exc_info.exception.code, 401)
        self.assertIsNone(self.store.config.copilot_session_token)

    def test_start_raises_when_api_disabled(self) -> None:
        self.server.stop()
        self.store.config.copilot_api_enabled = False

        with self.assertRaises(RuntimeError):
            self.server.start()

    def test_issue_search_returns_normalized_results_and_filters_optional_project(self) -> None:
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})
        status, payload = self._request(
            "POST",
            "/issues/search",
            payload={"query": "widget", "project_key": "ABC", "page_size": 5, "status_filters": ["In Progress"]},
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["project_key"], "ABC")
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["key"], "ABC-1")
        self.assertEqual(payload["results"][0]["description_text"], "Hello world")
        self.assertEqual(payload["results"][0]["parent"]["key"], "ABC-0")
        self.assertEqual(payload["results"][0]["linked_issues"][0]["key"], "ABC-2")
        self.assertEqual(self.fake_jira_client.search_calls[0]["project_key"], "ABC")

    def test_issue_detail_requires_session_and_returns_normalized_payload(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._request("GET", "/issues/ABC-1")
        self.assertEqual(exc_info.exception.code, 401)

        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})
        status, payload = self._request(
            "GET",
            "/issues/ABC-1",
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["key"], "ABC-1")
        self.assertEqual(payload["parent"]["key"], "EPIC-1")
        self.assertEqual(payload["hierarchy_level"], "standard")

    def test_issue_search_rejects_disallowed_project_filter(self) -> None:
        self.server.stop()
        self.store.config.copilot_allowed_projects = ["ABC"]
        self.store.config.allocation_draft = {
            "total_units": 10000,
            "rows": [{"issue_key": "ABC-1", "summary": "Draft row", "allocation_units": 5000, "locked": False, "description": ""}],
        }
        self.server = TempoyApiServer(
            port=0,
            policy_service=CopilotPolicyService(config_loader=self.store.load, config_saver=self.store.save),
            audit_service=CopilotAuditService(log_path=self.temp_dir.name + "/audit.log"),
            jira_client_factory=lambda: self.fake_jira_client,
            allocation_service=CopilotAllocationService(
                config_loader=self.store.load,
                daily_total_resolver=lambda config: 1800,
            ),
        )
        host, port = self.server.start()
        self.base_url = f"http://{host}:{port}"
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._request(
                "POST",
                "/issues/search",
                payload={"project_key": "OPS"},
                headers={"Authorization": f"Bearer {session_payload['token']}"},
            )
        self.assertEqual(exc_info.exception.code, 403)

    def test_allocation_draft_endpoint_returns_derived_context(self) -> None:
        self.store.config.allocation_draft = {
            "total_units": 10000,
            "rows": [
                {"issue_key": "ABC-1", "summary": "Draft row", "allocation_units": 2500, "locked": False, "description": ""},
                {"issue_key": "ABC-2", "summary": "Locked row", "allocation_units": 7500, "locked": True, "description": ""},
            ],
        }
        self.store.config.daily_time_seconds = 7200
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        status, payload = self._request(
            "GET",
            "/allocation/draft",
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["configured_day_seconds"], 7200)
        self.assertEqual(payload["daily_logged_seconds"], 1800)
        self.assertEqual(payload["remaining_seconds"], 5400)
        self.assertEqual(payload["allocatable_seconds"], 5400)
        self.assertEqual(payload["planned_seconds"], 5400)
        self.assertEqual(payload["rows"][0]["allocated_seconds"], 1350)
        self.assertEqual(payload["rows"][1]["allocated_seconds"], 4050)

    def test_allocation_draft_endpoint_requires_session(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._request("GET", "/allocation/draft")
        self.assertEqual(exc_info.exception.code, 401)

    def test_issue_hierarchy_returns_shallow_parent_and_linked_context(self) -> None:
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        status, payload = self._request(
            "POST",
            "/issues/hierarchy",
            payload={"issue_key": "ABC-1", "depth": 2, "include_children": True},
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["root_issue"]["key"], "ABC-1")
        self.assertEqual(payload["parents"][0]["key"], "EPIC-1")
        self.assertEqual(payload["related_epic"]["key"], "EPIC-1")
        self.assertEqual(payload["linked_issues"][0]["key"], "ABC-2")
        self.assertEqual(len(payload["children"]), 2)
        self.assertEqual(payload["children"][0]["key"], "ABC-10")
        self.assertEqual(payload["children"][1]["key"], "ABC-11")
        self.assertEqual(payload["root_issue"]["children"][0]["key"], "ABC-10")
        self.assertEqual(payload["descendants"], [])
        self.assertNotIn("Child discovery is not implemented yet", payload["warnings"])
        self.assertIn("Depth greater than 1 is not implemented yet", payload["warnings"])

    def test_issue_hierarchy_requires_session(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._request("POST", "/issues/hierarchy", payload={"issue_key": "ABC-1"})
        self.assertEqual(exc_info.exception.code, 401)

    def test_projects_endpoint_returns_normalized_project_list(self) -> None:
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        status, payload = self._request(
            "GET",
            "/projects",
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )

        self.assertEqual(status, 200)
        self.assertEqual([project["key"] for project in payload["projects"]], ["ABC", "OPS"])
        self.assertEqual(payload["projects"][0]["name"], "Alpha")
        self.assertEqual(payload["projects"][0]["project_type"], "software")

    def test_project_issue_types_endpoint_returns_normalized_issue_types(self) -> None:
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        status, payload = self._request(
            "GET",
            "/projects/ABC/issue-types",
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["project_key"], "ABC")
        self.assertEqual([item["name"] for item in payload["issue_types"]], ["Epic", "Sub-task", "Task"])
        self.assertEqual(payload["issue_types"][0]["hierarchy_level"], "epic")
        self.assertEqual(payload["issue_types"][1]["hierarchy_level"], "subtask")

    def test_projects_endpoint_filters_by_allowlist_when_present(self) -> None:
        self.server.stop()
        self.store.config.copilot_allowed_projects = ["ABC"]
        self.server = TempoyApiServer(
            port=0,
            policy_service=CopilotPolicyService(config_loader=self.store.load, config_saver=self.store.save),
            audit_service=CopilotAuditService(log_path=self.temp_dir.name + "/audit.log"),
            jira_client_factory=lambda: self.fake_jira_client,
            allocation_service=CopilotAllocationService(
                config_loader=self.store.load,
                daily_total_resolver=lambda config: 1800,
            ),
        )
        host, port = self.server.start()
        self.base_url = f"http://{host}:{port}"
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        status, payload = self._request(
            "GET",
            "/projects",
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )

        self.assertEqual(status, 200)
        self.assertEqual([project["key"] for project in payload["projects"]], ["ABC"])

    def test_project_issue_types_rejects_disallowed_project(self) -> None:
        self.server.stop()
        self.store.config.copilot_allowed_projects = ["ABC"]
        self.server = TempoyApiServer(
            port=0,
            policy_service=CopilotPolicyService(config_loader=self.store.load, config_saver=self.store.save),
            audit_service=CopilotAuditService(log_path=self.temp_dir.name + "/audit.log"),
            jira_client_factory=lambda: self.fake_jira_client,
            allocation_service=CopilotAllocationService(
                config_loader=self.store.load,
                daily_total_resolver=lambda config: 1800,
            ),
        )
        host, port = self.server.start()
        self.base_url = f"http://{host}:{port}"
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._request(
                "GET",
                "/projects/OPS/issue-types",
                headers={"Authorization": f"Bearer {session_payload['token']}"},
            )
        self.assertEqual(exc_info.exception.code, 403)

    def test_project_create_schema_returns_normalized_field_metadata(self) -> None:
        self.store.config.copilot_allowed_issue_types = ["Task"]
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        status, payload = self._request(
            "GET",
            "/projects/ABC/create-schema",
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["project_key"], "ABC")
        self.assertEqual([item["issue_type"] for item in payload["issue_types"]], ["Epic", "Task"])
        self.assertFalse(payload["issue_types"][0]["write_allowed"])
        self.assertTrue(payload["issue_types"][1]["write_allowed"])
        self.assertEqual(payload["issue_types"][1]["fields"][0]["name"], "Summary")
        self.assertTrue(payload["issue_types"][1]["fields"][0]["required"])
        self.assertEqual(payload["issue_types"][1]["fields"][1]["allowed_values"][0]["value"], "Highest")

    def test_project_create_schema_rejects_disallowed_project(self) -> None:
        self.server.stop()
        self.store.config.copilot_allowed_projects = ["ABC"]
        self.server = TempoyApiServer(
            port=0,
            policy_service=CopilotPolicyService(config_loader=self.store.load, config_saver=self.store.save),
            audit_service=CopilotAuditService(log_path=self.temp_dir.name + "/audit.log"),
            jira_client_factory=lambda: self.fake_jira_client,
            allocation_service=CopilotAllocationService(
                config_loader=self.store.load,
                daily_total_resolver=lambda config: 1800,
            ),
        )
        host, port = self.server.start()
        self.base_url = f"http://{host}:{port}"
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._request(
                "GET",
                "/projects/OPS/create-schema",
                headers={"Authorization": f"Bearer {session_payload['token']}"},
            )
        self.assertEqual(exc_info.exception.code, 403)

    def test_task_create_returns_preview_by_default(self) -> None:
        self.store.config.copilot_api_mode = "create-and-refine"
        self.store.config.copilot_allowed_issue_types = ["Task"]
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        status, payload = self._request(
            "POST",
            "/issues/create",
            payload={"project_key": "ABC", "summary": "Create task", "description_text": "Created from API", "labels": ["api"], "priority": "Highest"},
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )

        self.assertEqual(status, 200)
        self.assertFalse(payload["applied"])
        self.assertEqual(payload["preview"]["issue_type"], "Task")
        self.assertTrue(payload["preview"]["requires_confirmation"])
        self.assertEqual(payload["preview"]["validated_fields"]["summary"], "Create task")
        self.assertEqual(payload["preview"]["validated_fields"]["project"]["key"], "ABC")

    def test_task_create_applies_when_confirmed(self) -> None:
        self.store.config.copilot_api_mode = "create-and-refine"
        self.store.config.copilot_allowed_issue_types = ["Task"]
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        status, payload = self._request(
            "POST",
            "/issues/create",
            payload={
                "project_key": "ABC",
                "summary": "Create task",
                "description_text": "Created from API",
                "labels": ["api"],
                "priority": "Highest",
                "apply": True,
                "confirm": True,
            },
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["applied"])
        self.assertEqual(payload["issue"]["key"], "ABC-99")
        self.assertEqual(self.fake_jira_client.create_issue_calls[0]["issuetype"]["id"], "10")

    def test_task_create_rejects_non_task_issue_types(self) -> None:
        self.store.config.copilot_api_mode = "create-and-refine"
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._request(
                "POST",
                "/issues/create",
                payload={"project_key": "ABC", "summary": "Create epic", "issue_type": "Epic"},
                headers={"Authorization": f"Bearer {session_payload['token']}"},
            )
        self.assertEqual(exc_info.exception.code, 400)

    def test_task_create_rejects_when_create_mode_disabled(self) -> None:
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._request(
                "POST",
                "/issues/create",
                payload={"project_key": "ABC", "summary": "Create task"},
                headers={"Authorization": f"Bearer {session_payload['token']}"},
            )
        self.assertEqual(exc_info.exception.code, 403)

    def test_issue_update_returns_preview_by_default(self) -> None:
        self.store.config.copilot_api_mode = "refine-only"
        self.store.config.copilot_allowed_issue_types = ["Task"]
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        status, payload = self._request(
            "POST",
            "/issues/update",
            payload={
                "issue_key": "ABC-1",
                "summary": "Refined summary",
                "description_text": "New description",
                "labels": ["backend", "api"],
                "priority": "Highest",
                "parent_key": "EPIC-2",
                "acceptance_criteria_text": "Given X when Y then Z",
            },
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )

        self.assertEqual(status, 200)
        self.assertFalse(payload["applied"])
        self.assertEqual(payload["preview"]["issue_key"], "ABC-1")
        self.assertEqual(payload["preview"]["validated_fields"]["summary"], "Refined summary")
        self.assertEqual(payload["preview"]["validated_fields"]["priority"]["name"], "Highest")
        self.assertEqual(payload["preview"]["validated_fields"]["parent"]["key"], "EPIC-2")
        self.assertEqual(payload["preview"]["validated_fields"]["customfield_12345"], "Given X when Y then Z")
        self.assertTrue(payload["preview"]["requires_confirmation"])

    def test_issue_update_applies_when_confirmed(self) -> None:
        self.store.config.copilot_api_mode = "refine-only"
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        status, payload = self._request(
            "POST",
            "/issues/update",
            payload={
                "issue_key": "ABC-1",
                "summary": "Refined summary",
                "apply": True,
                "confirm": True,
            },
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["applied"])
        self.assertEqual(payload["issue"]["key"], "ABC-1")
        self.assertEqual(self.fake_jira_client.update_issue_calls[0]["issue_key"], "ABC-1")
        self.assertEqual(self.fake_jira_client.update_issue_calls[0]["fields"]["summary"], "Refined summary")

    def test_issue_update_rejects_unsupported_fields(self) -> None:
        self.store.config.copilot_api_mode = "refine-only"
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._request(
                "POST",
                "/issues/update",
                payload={"issue_key": "ABC-1", "status": "Done"},
                headers={"Authorization": f"Bearer {session_payload['token']}"},
            )
        self.assertEqual(exc_info.exception.code, 400)

    def test_issue_update_rejects_disallowed_issue_type(self) -> None:
        self.store.config.copilot_api_mode = "refine-only"
        self.store.config.copilot_allowed_issue_types = ["Epic"]
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._request(
                "POST",
                "/issues/update",
                payload={"issue_key": "ABC-1", "summary": "Refined summary"},
                headers={"Authorization": f"Bearer {session_payload['token']}"},
            )
        self.assertEqual(exc_info.exception.code, 403)

    def test_allocation_mutation_endpoints_require_refine_mode(self) -> None:
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        with self.assertRaises(urllib.error.HTTPError) as exc_info:
            self._request(
                "POST",
                "/allocation/add",
                payload={"issue_key": "ABC-1"},
                headers={"Authorization": f"Bearer {session_payload['token']}"},
            )
        self.assertEqual(exc_info.exception.code, 403)

    def test_allocation_mutation_endpoints_update_persisted_draft(self) -> None:
        self.server.stop()
        self.store.config.copilot_api_mode = "refine-only"
        self.store.config.allocation_draft = {
            "total_units": 10000,
            "rows": [
                {"issue_key": "ABC-1", "summary": "Existing", "allocation_units": 10000, "locked": False, "description": ""},
            ],
        }
        self.server = TempoyApiServer(
            port=0,
            policy_service=CopilotPolicyService(config_loader=self.store.load, config_saver=self.store.save),
            audit_service=CopilotAuditService(log_path=self.temp_dir.name + "/audit.log"),
            jira_client_factory=lambda: self.fake_jira_client,
            allocation_service=CopilotAllocationService(
                config_loader=self.store.load,
                config_saver=self.store.save,
                daily_total_resolver=lambda config: 1800,
                issue_summary_resolver=lambda issue_key: "Fetched summary",
            ),
        )
        host, port = self.server.start()
        self.base_url = f"http://{host}:{port}"
        _, session_payload = self._request("POST", "/session/start", payload={"client_name": "tests"})

        add_status, add_payload = self._request(
            "POST",
            "/allocation/add",
            payload={"issue_key": "ABC-2"},
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )
        self.assertEqual(add_status, 200)
        self.assertEqual(len(add_payload["rows"]), 2)
        self.assertEqual(add_payload["rows"][1]["summary"], "Fetched summary")

        units_status, units_payload = self._request(
            "POST",
            "/allocation/set-units",
            payload={"issue_key": "ABC-2", "allocation_units": 2500},
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )
        self.assertEqual(units_status, 200)
        self.assertEqual([row["allocation_units"] for row in units_payload["rows"]], [7500, 2500])

        lock_status, lock_payload = self._request(
            "POST",
            "/allocation/set-lock",
            payload={"issue_key": "ABC-2", "locked": True},
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )
        self.assertEqual(lock_status, 200)
        self.assertTrue(lock_payload["rows"][1]["locked"])

        equalize_status, equalize_payload = self._request(
            "POST",
            "/allocation/equalize",
            payload={},
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )
        self.assertEqual(equalize_status, 200)
        self.assertEqual([row["allocation_units"] for row in equalize_payload["rows"]], [7500, 2500])

        remove_status, remove_payload = self._request(
            "POST",
            "/allocation/remove",
            payload={"issue_key": "ABC-2"},
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )
        self.assertEqual(remove_status, 200)
        self.assertEqual([row["issue_key"] for row in remove_payload["rows"]], ["ABC-1"])

        reset_status, reset_payload = self._request(
            "POST",
            "/allocation/reset",
            payload={},
            headers={"Authorization": f"Bearer {session_payload['token']}"},
        )
        self.assertEqual(reset_status, 200)
        self.assertEqual(reset_payload["rows"][0]["allocation_units"], 10000)
        self.assertEqual(self.store.config.allocation_draft["rows"][0]["issue_key"], "ABC-1")


if __name__ == "__main__":
    unittest.main()