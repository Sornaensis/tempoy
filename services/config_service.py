"""Configuration management service for Tempoy application."""
from __future__ import annotations

import json
import os

from models import AppConfig

# Configuration paths
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".tempoy")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
# Legacy location for seamless migration
OLD_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".tempo_floater")
OLD_CONFIG_PATH = os.path.join(OLD_CONFIG_DIR, "config.json")


class ConfigManager:
    """Manager for loading and saving application configuration."""
    
    @staticmethod
    def load() -> AppConfig:
        """Load configuration from disk, migrating from old location if necessary."""
        # Prefer new location; migrate from old if necessary.
        cfg = None
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = AppConfig.from_dict(json.load(f))
        elif os.path.exists(OLD_CONFIG_PATH):
            # Attempt migration (copy then rename original to .bak for safety)
            try:
                os.makedirs(CONFIG_DIR, exist_ok=True)
                with open(OLD_CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = f.read()
                tmp_new = CONFIG_PATH + ".tmp_migrate"
                with open(tmp_new, "w", encoding="utf-8") as f:
                    f.write(data)
                os.replace(tmp_new, CONFIG_PATH)
                # Keep old directory/file as backup instead of deleting (safer)
                cfg = AppConfig.from_dict(json.loads(data))
            except Exception:
                # Fallback: load old directly without migrating
                try:
                    with open(OLD_CONFIG_PATH, "r", encoding="utf-8") as f:
                        cfg = AppConfig.from_dict(json.load(f))
                except Exception:
                    cfg = AppConfig()
        else:
            cfg = AppConfig()
        
        # Prune old history entries (older than 3 days)
        cfg.prune_old_history()
        return cfg

    @staticmethod
    def save(cfg: AppConfig) -> None:
        """Save configuration to disk."""
        # Prune old history before saving
        cfg.prune_old_history()
        
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg.to_dict(), f, indent=2)
        os.replace(tmp, CONFIG_PATH)
