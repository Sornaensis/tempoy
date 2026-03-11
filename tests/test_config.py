from __future__ import annotations

import json
import os
import tempfile
import time
import unittest

from tempoy_app import config as config_module
from tempoy_app.config import AppConfig, ConfigManager, DEFAULT_ISSUE_LIST_COLUMN_WIDTHS


class ConfigManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_paths = (
            config_module.CONFIG_DIR,
            config_module.CONFIG_PATH,
            config_module.OLD_CONFIG_DIR,
            config_module.OLD_CONFIG_PATH,
        )
        config_module.CONFIG_DIR = os.path.join(self.temp_dir.name, ".tempoy")
        config_module.CONFIG_PATH = os.path.join(config_module.CONFIG_DIR, "config.json")
        config_module.OLD_CONFIG_DIR = os.path.join(self.temp_dir.name, ".tempo_floater")
        config_module.OLD_CONFIG_PATH = os.path.join(config_module.OLD_CONFIG_DIR, "config.json")

    def tearDown(self) -> None:
        (
            config_module.CONFIG_DIR,
            config_module.CONFIG_PATH,
            config_module.OLD_CONFIG_DIR,
            config_module.OLD_CONFIG_PATH,
        ) = self.original_paths
        self.temp_dir.cleanup()

    def test_from_dict_migrates_legacy_history_entries(self) -> None:
        cfg = AppConfig.from_dict({"search_history": [["ABC-123", 123.0]], "issue_list_column_widths": None})

        self.assertEqual(cfg.search_history, [{"type": "search", "term": "ABC-123", "ts": 123.0}])
        self.assertEqual(cfg.issue_list_column_widths, DEFAULT_ISSUE_LIST_COLUMN_WIDTHS)

    def test_load_migrates_legacy_config_file(self) -> None:
        os.makedirs(config_module.OLD_CONFIG_DIR, exist_ok=True)
        with open(config_module.OLD_CONFIG_PATH, "w", encoding="utf-8") as file_handle:
            json.dump({"jira_base_url": "https://example.atlassian.net"}, file_handle)

        cfg = ConfigManager.load()

        self.assertEqual(cfg.jira_base_url, "https://example.atlassian.net")
        self.assertTrue(os.path.exists(config_module.CONFIG_PATH))

    def test_save_prunes_old_history_before_writing(self) -> None:
        cfg = AppConfig(
            search_history=[
                {"type": "search", "term": "recent", "ts": time.time()},
                {"type": "search", "term": "stale", "ts": time.time() - (10 * 24 * 60 * 60)},
            ]
        )

        ConfigManager.save(cfg)

        with open(config_module.CONFIG_PATH, "r", encoding="utf-8") as file_handle:
            saved = json.load(file_handle)
        self.assertEqual(len(saved["search_history"]), 1)
        self.assertEqual(saved["search_history"][0]["term"], "recent")


if __name__ == "__main__":
    unittest.main()
