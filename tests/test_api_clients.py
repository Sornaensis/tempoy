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


if __name__ == "__main__":
    unittest.main()