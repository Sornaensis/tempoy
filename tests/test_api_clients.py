from __future__ import annotations

import datetime as dt
import importlib
import sys
import types
import unittest
from unittest.mock import patch

if "requests" not in sys.modules:
    sys.modules["requests"] = types.SimpleNamespace(Session=lambda: None)

JiraClient = importlib.import_module("tempoy_app.api.jira").JiraClient
TempoClient = importlib.import_module("tempoy_app.api.tempo").TempoClient


class _FakeResponse:
    def __init__(self, payload, *, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeSession:
    def __init__(self, responses=None):
        self.headers = {}
        self.auth = None
        self.responses = list(responses or [])
        self.post_calls = []
        self.get_calls = []
        self.put_calls = []

    def post(self, url, json=None, timeout=None):
        self.post_calls.append({"url": url, "json": dict(json or {}), "timeout": timeout})
        if self.responses:
            return self.responses.pop(0)
        return _FakeResponse({})

    def get(self, url, params=None, timeout=None):
        self.get_calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        if self.responses:
            return self.responses.pop(0)
        return _FakeResponse({})

    def put(self, url, json=None, timeout=None):
        self.put_calls.append({"url": url, "json": dict(json or {}), "timeout": timeout})
        if self.responses:
            return self.responses.pop(0)
        return _FakeResponse({}, status_code=204)


class ApiClientTests(unittest.TestCase):
    def test_jira_ensure_issue_ids_batches_missing_keys_and_reuses_cache(self) -> None:
        client = JiraClient.__new__(JiraClient)
        client._issue_id_cache = {"ABC-1": "101"}

        searched_chunks = []

        def fake_search_by_keys(issue_keys, fields, order_by_updated=False):
            searched_chunks.append((list(issue_keys), list(fields), order_by_updated))
            for issue_key in issue_keys:
                client._issue_id_cache[issue_key] = f"id-{issue_key}"
            return []

        client.search_by_keys = fake_search_by_keys

        resolved = client.ensure_issue_ids(["ABC-1", "ABC-2", "ABC-3", "ABC-2"], chunk_size=1)

        self.assertEqual(searched_chunks, [(["ABC-2"], ["summary"], False), (["ABC-3"], ["summary"], False)])
        self.assertEqual(resolved, {"ABC-1": "101", "ABC-2": "id-ABC-2", "ABC-3": "id-ABC-3"})

    def test_tempo_create_worklog_posts_expected_payload(self) -> None:
        fake_session = _FakeSession([_FakeResponse({"ok": True})])
        with patch("tempoy_app.api.tempo.requests.Session", return_value=fake_session):
            client = TempoClient("tempo-token")

        when = dt.datetime(2026, 3, 10, 9, 30, 0)
        result = client.create_worklog(
            issue_key="ABC-1",
            issue_id="12345",
            account_id="acct-1",
            seconds=1800,
            when=when,
            description="Worked on it",
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(fake_session.post_calls), 1)
        payload = fake_session.post_calls[0]["json"]
        self.assertEqual(payload["issueId"], 12345)
        self.assertEqual(payload["timeSpentSeconds"], 1800)
        self.assertEqual(payload["startDate"], "2026-03-10")
        self.assertEqual(payload["startTime"], "09:30:00")
        self.assertEqual(payload["authorAccountId"], "acct-1")
        self.assertEqual(payload["description"], "Worked on it")

    def test_tempo_get_recent_worked_issues_paginates_until_count_reached(self) -> None:
        responses = [
            _FakeResponse(
                {
                    "results": [{"issue": {"key": "ABC-1"}}],
                    "metadata": {"count": 2},
                }
            ),
            _FakeResponse(
                {
                    "results": [{"issue": {"key": "ABC-2"}}],
                    "metadata": {"count": 2},
                }
            ),
        ]
        fake_session = _FakeSession(responses)
        with patch("tempoy_app.api.tempo.requests.Session", return_value=fake_session):
            client = TempoClient("tempo-token")

        worklogs = client.get_recent_worked_issues(account_id="acct-1", days_back=60)

        self.assertEqual([item["issue"]["key"] for item in worklogs], ["ABC-1", "ABC-2"])
        self.assertEqual(len(fake_session.get_calls), 2)
        self.assertEqual(fake_session.get_calls[0]["params"]["offset"], 0)
        self.assertEqual(fake_session.get_calls[1]["params"]["offset"], 1)

    def test_jira_get_issue_fetches_requested_fields(self) -> None:
        fake_session = _FakeSession([_FakeResponse({"id": "101", "key": "ABC-1", "fields": {"summary": "Hello"}})])
        with patch("tempoy_app.api.jira.requests.Session", return_value=fake_session):
            client = JiraClient("https://example.atlassian.net", "me@example.com", "token")

        issue = client.get_issue("ABC-1", fields=["summary", "status"])

        self.assertEqual(issue["id"], "101")
        self.assertEqual(fake_session.get_calls[0]["params"], {"fields": "summary,status"})
        self.assertEqual(client._issue_id_cache["ABC-1"], "101")

    def test_jira_search_issues_builds_jql_with_optional_filters(self) -> None:
        fake_session = _FakeSession([_FakeResponse({"issues": []})])
        with patch("tempoy_app.api.jira.requests.Session", return_value=fake_session):
            client = JiraClient("https://example.atlassian.net", "me@example.com", "token")

        client.search_issues(
            query="refactor widget",
            project_key="abc",
            issue_types=["Task", "Bug"],
            status_filters=["In Progress", "To Do"],
            max_results=10,
        )

        payload = fake_session.post_calls[0]["json"]
        self.assertIn('project = "ABC"', payload["jql"])
        self.assertIn('summary ~ "refactor widget"', payload["jql"])
        self.assertIn('issuetype in ("Task", "Bug")', payload["jql"])
        self.assertIn('status in ("In Progress", "To Do")', payload["jql"])
        self.assertEqual(payload["maxResults"], 10)

    def test_jira_get_issues_by_keys_uses_default_fields(self) -> None:
        fake_session = _FakeSession([_FakeResponse({"issues": []})])
        with patch("tempoy_app.api.jira.requests.Session", return_value=fake_session):
            client = JiraClient("https://example.atlassian.net", "me@example.com", "token")

        client.get_issues_by_keys(["ABC-1", "ABC-2"])

        payload = fake_session.post_calls[0]["json"]
        self.assertIn("summary", payload["fields"])
        self.assertIn("issuelinks", payload["fields"])

    def test_jira_get_projects_reads_project_search_endpoint(self) -> None:
        fake_session = _FakeSession([_FakeResponse({"values": [{"id": "1", "key": "ABC", "name": "Alpha"}]})])
        with patch("tempoy_app.api.jira.requests.Session", return_value=fake_session):
            client = JiraClient("https://example.atlassian.net", "me@example.com", "token")

        projects = client.get_projects(max_results=200)

        self.assertEqual(projects, [{"id": "1", "key": "ABC", "name": "Alpha"}])
        self.assertEqual(fake_session.get_calls[0]["params"], {"startAt": 0, "maxResults": 200})

    def test_jira_get_project_issue_types_reads_project_endpoint(self) -> None:
        fake_session = _FakeSession([_FakeResponse({"issueTypes": [{"id": "10", "name": "Task"}]})])
        with patch("tempoy_app.api.jira.requests.Session", return_value=fake_session):
            client = JiraClient("https://example.atlassian.net", "me@example.com", "token")

        issue_types = client.get_project_issue_types("abc")

        self.assertEqual(issue_types, [{"id": "10", "name": "Task"}])
        self.assertEqual(fake_session.get_calls[0]["params"], {"expand": "issueTypes"})

    def test_jira_get_create_schema_fetches_each_issue_type_schema(self) -> None:
        fake_session = _FakeSession(
            [
                _FakeResponse({"issueTypes": [{"id": "10", "name": "Task"}, {"id": "11", "name": "Epic"}]}),
                _FakeResponse({"issueTypeId": "10", "name": "Task", "fields": {}}),
                _FakeResponse({"issueTypeId": "11", "name": "Epic", "fields": {}}),
            ]
        )
        with patch("tempoy_app.api.jira.requests.Session", return_value=fake_session):
            client = JiraClient("https://example.atlassian.net", "me@example.com", "token")

        schemas = client.get_create_schema("abc")

        self.assertEqual([item["issueTypeId"] for item in schemas], ["10", "11"])
        self.assertIn("/project/ABC", fake_session.get_calls[0]["url"])
        self.assertIn("/issue/createmeta/ABC/issuetypes/10", fake_session.get_calls[1]["url"])
        self.assertIn("/issue/createmeta/ABC/issuetypes/11", fake_session.get_calls[2]["url"])

    def test_jira_create_issue_posts_fields_payload(self) -> None:
        fake_session = _FakeSession([_FakeResponse({"id": "501", "key": "ABC-99"})])
        with patch("tempoy_app.api.jira.requests.Session", return_value=fake_session):
            client = JiraClient("https://example.atlassian.net", "me@example.com", "token")

        result = client.create_issue({"summary": "Create me", "project": {"key": "ABC"}, "issuetype": {"name": "Task"}})

        self.assertEqual(result["key"], "ABC-99")
        self.assertEqual(fake_session.post_calls[0]["json"]["fields"]["summary"], "Create me")
        self.assertEqual(client._issue_id_cache["ABC-99"], "501")

    def test_jira_get_edit_schema_reads_editmeta_endpoint(self) -> None:
        fake_session = _FakeSession([_FakeResponse({"fields": {"summary": {"name": "Summary"}}})])
        with patch("tempoy_app.api.jira.requests.Session", return_value=fake_session):
            client = JiraClient("https://example.atlassian.net", "me@example.com", "token")

        schema = client.get_edit_schema("abc-1")

        self.assertIn("/issue/ABC-1/editmeta", fake_session.get_calls[0]["url"])
        self.assertIn("summary", schema["fields"])

    def test_jira_update_issue_puts_fields_payload(self) -> None:
        fake_session = _FakeSession([_FakeResponse({}, status_code=204)])
        with patch("tempoy_app.api.jira.requests.Session", return_value=fake_session):
            client = JiraClient("https://example.atlassian.net", "me@example.com", "token")

        result = client.update_issue("abc-1", {"summary": "Updated"})

        self.assertEqual(result, {})
        self.assertIn("/issue/ABC-1", fake_session.put_calls[0]["url"])
        self.assertEqual(fake_session.put_calls[0]["json"]["fields"]["summary"], "Updated")


if __name__ == "__main__":
    unittest.main()