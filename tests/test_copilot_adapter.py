from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from tempoy_app.copilot_adapter import TempoyApiAdapter, TempoyApiAdapterError, main


class _FakeHttpResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TempoyApiAdapterTests(unittest.TestCase):
    def test_start_session_sets_token_from_response(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout=10):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeHttpResponse({"token": "abc123", "mode": "read-only"})

        adapter = TempoyApiAdapter(base_url="http://127.0.0.1:9999")
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            payload = adapter.start_session(client_name="tests")

        self.assertEqual(payload["token"], "abc123")
        self.assertEqual(adapter.token, "abc123")
        self.assertEqual(captured["url"], "http://127.0.0.1:9999/session/start")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["body"]["client_name"], "tests")

    def test_get_issue_details_adds_bearer_token(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout=10):
            captured["auth"] = request.headers.get("Authorization")
            captured["url"] = request.full_url
            return _FakeHttpResponse({"key": "ABC-1"})

        adapter = TempoyApiAdapter(base_url="http://127.0.0.1:9999", token="session-token")
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            payload = adapter.get_issue_details("abc-1")

        self.assertEqual(payload["key"], "ABC-1")
        self.assertEqual(captured["auth"], "Bearer session-token")
        self.assertEqual(captured["url"], "http://127.0.0.1:9999/issues/ABC-1")

    def test_create_ticket_forces_task_issue_type(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout=10):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeHttpResponse({"applied": False})

        adapter = TempoyApiAdapter(base_url="http://127.0.0.1:9999", token="session-token")
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            adapter.create_ticket(project_key="ABC", summary="Task only", issue_type="Epic")

        self.assertEqual(captured["body"]["issue_type"], "Task")

    def test_invoke_rejects_unknown_tool(self) -> None:
        adapter = TempoyApiAdapter()

        with self.assertRaises(TempoyApiAdapterError):
            adapter.invoke("unknown_tool", {})

    def test_request_raises_friendly_http_error(self) -> None:
        response = io.BytesIO(json.dumps({"error": "Unauthorized"}).encode("utf-8"))
        error = urllib.error.HTTPError(
            url="http://127.0.0.1:9999/issues/ABC-1",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=response,
        )
        adapter = TempoyApiAdapter(base_url="http://127.0.0.1:9999")

        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(TempoyApiAdapterError) as exc_info:
                adapter.get_issue_details("ABC-1")

        self.assertIn("HTTP 401", str(exc_info.exception))
        self.assertIn("Unauthorized", str(exc_info.exception))
        self.assertIsNone(adapter.token)


class TempoyApiAdapterCliTests(unittest.TestCase):
    def test_main_prints_tool_result_json(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch("tempoy_app.copilot_adapter.TempoyApiAdapter.invoke", return_value={"status": "ok"}), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr):
            exit_code = main(["health", "--base-url", "http://127.0.0.1:9999", "--args", "{}"])

        self.assertEqual(exit_code, 0)
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["tool"], "health")
        self.assertEqual(output["result"]["status"], "ok")
        self.assertEqual(stderr.getvalue(), "")

    def test_main_rejects_non_object_args(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            exit_code = main(["health", "--args", '[]'])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("JSON object", stderr.getvalue())