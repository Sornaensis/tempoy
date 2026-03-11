from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout

from tempoy_app.logging_utils import debug_log


class LoggingUtilsTests(unittest.TestCase):
    def test_debug_log_suppresses_output_when_debug_disabled(self) -> None:
        previous = os.environ.pop("TEMPOY_DEBUG", None)
        try:
            stream = io.StringIO()
            with redirect_stdout(stream):
                debug_log("hidden {}", "message")
            self.assertEqual(stream.getvalue(), "")
        finally:
            if previous is not None:
                os.environ["TEMPOY_DEBUG"] = previous

    def test_debug_log_formats_output_when_debug_enabled(self) -> None:
        previous = os.environ.get("TEMPOY_DEBUG")
        os.environ["TEMPOY_DEBUG"] = "1"
        try:
            stream = io.StringIO()
            with redirect_stdout(stream):
                debug_log("hello {}", "world")
            self.assertIn("[TEMPOY DEBUG] hello world", stream.getvalue())
        finally:
            if previous is None:
                os.environ.pop("TEMPOY_DEBUG", None)
            else:
                os.environ["TEMPOY_DEBUG"] = previous

    def test_debug_log_formats_percent_style_output_when_debug_enabled(self) -> None:
        previous = os.environ.get("TEMPOY_DEBUG")
        os.environ["TEMPOY_DEBUG"] = "1"
        try:
            stream = io.StringIO()
            with redirect_stdout(stream):
                debug_log("hello %s", "world")
            self.assertIn("[TEMPOY DEBUG] hello world", stream.getvalue())
        finally:
            if previous is None:
                os.environ.pop("TEMPOY_DEBUG", None)
            else:
                os.environ["TEMPOY_DEBUG"] = previous


if __name__ == "__main__":
    unittest.main()
