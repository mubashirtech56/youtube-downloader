"""Application settings persistence."""

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict

from app.core.utils import data_dir


class SettingsManager:
    """Load/save user preferences to a JSON file in the user's home dir."""

    DEFAULT_SETTINGS: Dict[str, Any] = {
        "theme": "dark",
        "language": "en",
        "download_folder": str(Path.home() / "Downloads" / "YouTube"),
        "max_concurrent_downloads": 3,
        "default_quality": "1080p",
        "default_audio_quality": "192",
        "default_output_format": "mp4",
        "notifications": True,
        "auto_update_check": True,
        "cookie_file": None,
        "cookie_browser": None,
        "ffmpeg_path": None,
        "window_width": 1200,
        "window_height": 800,
        "window_maximized": True,
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.settings_path = data_dir() / "settings.json"
        self._lock = threading.Lock()
        self.settings = self._load_settings()

    def _load_settings(self) -> Dict[str, Any]:
        try:
            if self.settings_path.exists():
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                return {**self.DEFAULT_SETTINGS, **loaded}
        except Exception as e:
            self.logger.error(f"Failed to load settings: {e}")
        return self.DEFAULT_SETTINGS.copy()

    def save(self):
        with self._lock:
            try:
                self.settings_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.settings_path, "w", encoding="utf-8") as f:
                    json.dump(self.settings, f, indent=2)
            except Exception as e:
                self.logger.error(f"Failed to save settings: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any):
        with self._lock:
            self.settings[key] = value
        self.save()

    def reset(self):
        with self._lock:
            self.settings = self.DEFAULT_SETTINGS.copy()
        self.save()

    def close(self):
        pass