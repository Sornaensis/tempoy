from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from tempoy_app import config as config_module
from tempoy_app.logging_utils import configure_logging, debug_log, get_log_path, shutdown_logging


class LoggingUtilsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_config_dir = config_module.CONFIG_DIR
        self.original_debug = os.environ.get("TEMPOY_DEBUG")
        config_module.CONFIG_DIR = os.path.join(self.temp_dir.name, ".tempoy")
        shutdown_logging()

    def tearDown(self) -> None:
        config_module.CONFIG_DIR = self.original_config_dir
        if self.original_debug is None:
            os.environ.pop("TEMPOY_DEBUG", None)
        else:
            os.environ["TEMPOY_DEBUG"] = self.original_debug
        shutdown_logging()
        self.temp_dir.cleanup()

    def test_debug_log_suppresses_output_when_debug_disabled(self) -> None:
        os.environ.pop("TEMPOY_DEBUG", None)

        stream = io.StringIO()
        with redirect_stdout(stream):
            debug_log("hidden {}", "message")

        self.assertEqual(stream.getvalue(), "")

    def test_debug_log_formats_output_when_debug_enabled(self) -> None:
        os.environ["TEMPOY_DEBUG"] = "1"

        stream = io.StringIO()
        with redirect_stdout(stream):
            debug_log("hello {}", "world")

        self.assertIn("[TEMPOY DEBUG] hello world", stream.getvalue())

    def test_debug_log_formats_percent_style_output_when_debug_enabled(self) -> None:
        os.environ["TEMPOY_DEBUG"] = "1"

        stream = io.StringIO()
        with redirect_stdout(stream):
            debug_log("hello %s", "world")

        self.assertIn("[TEMPOY DEBUG] hello world", stream.getvalue())

    def test_configure_logging_uses_tempoy_config_dir(self) -> None:
        log_path = configure_logging()

        self.assertEqual(log_path, get_log_path())
        self.assertEqual(log_path, os.path.join(config_module.CONFIG_DIR, "tempoy.log"))
        self.assertTrue(os.path.isdir(config_module.CONFIG_DIR))

    def test_debug_log_writes_to_file_when_console_debug_disabled(self) -> None:
        os.environ.pop("TEMPOY_DEBUG", None)

        debug_log("persisted {}", "message")

        with open(get_log_path(), "r", encoding="utf-8") as file_handle:
            contents = file_handle.read()
        self.assertIn("DEBUG persisted message", contents)


if __name__ == "__main__":
    unittest.main()
