"""Download history persistence (plain-text log of completed downloads)."""

import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.utils import data_dir


class HistoryManager:
    """Record successfully downloaded videos to a plain-text history file.

    Only downloads that actually complete are written to history.txt; queued
    or merely fetched videos are never recorded. Reads/writes are guarded by a
    lock because the download workers may record history off the GUI thread.
    """

    _SEP = "\t"

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.history_path = data_dir() / "history.txt"
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @classmethod
    def _serialize(cls, data: Dict[str, Any]) -> str:
        created_at = data.get("created_at") or datetime.now().isoformat()
        fields = [
            created_at,
            str(data.get("id", "")),
            str(data.get("title", "")),
            str(data.get("url", "")),
            str(data.get("format", "")),
            str(data.get("file_size", 0) or 0),
            str(data.get("download_path", "")),
        ]
        return cls._SEP.join(field.replace(cls._SEP, " ") for field in fields)

    @classmethod
    def _parse_line(cls, line: str) -> Optional[Dict[str, Any]]:
        parts = line.rstrip("\n").split(cls._SEP)
        if len(parts) < 7:
            return None
        created_at, entry_id, title, url, fmt, size, path = parts[:7]
        return {
            "id": entry_id,
            "video_id": entry_id,
            "title": title,
            "url": url,
            "format": fmt,
            "file_size": int(size) if size.isdigit() else 0,
            "download_path": path,
            "status": "completed",
            "metadata": {},
            "created_at": created_at,
        }

    def _append(self, data: Dict[str, Any]) -> str:
        try:
            line = self._serialize(data)
            with self._lock:
                with open(self.history_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            return str(data.get("id", ""))
        except Exception as e:
            self.logger.error(f"Failed to append history: {e}")
            return ""

    def add_history_entry(self, data: Dict[str, Any]) -> str:
        """Append one entry, but only when the download completed."""
        if data.get("status") != "completed":
            return ""
        return self._append(data)

    def add_history_entries(self, rows: List[Dict[str, Any]]):
        for row in rows:
            if row.get("status") == "completed":
                self._append(row)

    def get_history(self, limit: int = 100, offset: int = 0,
                    status: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            with self._lock:
                lines = self.history_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        except Exception as e:
            self.logger.error(f"Failed to read history: {e}")
            return []

        entries = []
        for line in reversed(lines):
            entry = self._parse_line(line)
            if not entry:
                continue
            if status and entry["status"] != status:
                continue
            if search:
                haystack = " ".join([entry["title"], entry["url"], entry["id"]])
                if search.lower() not in haystack.lower():
                    continue
            entries.append(entry)
        return entries[offset:offset + limit]

    def delete_history_entry(self, entry_id: str):
        try:
            with self._lock:
                lines = self.history_path.read_text(encoding="utf-8").splitlines()
                kept = [line for line in lines
                        if not (self._parse_line(line) and self._parse_line(line)["id"] == entry_id)]
                self.history_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        except FileNotFoundError:
            return
        except Exception as e:
            self.logger.error(f"Failed to delete history entry: {e}")

    def clear_history(self):
        try:
            with self._lock:
                self.history_path.write_text("", encoding="utf-8")
        except Exception as e:
            self.logger.error(f"Failed to clear history: {e}")

    def close(self):
        pass