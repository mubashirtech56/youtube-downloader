"""Data model for a queued download."""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class DownloadItem:
    """Download item data model (shared by the manager and the UI snapshot)."""

    id: str
    url: str
    title: str
    format_info: Dict[str, Any]
    output_path: str
    format_selector: Optional[str] = None
    status: str = "pending"
    progress: float = 0
    speed: float = 0
    eta: int = 0
    downloaded_size: int = 0
    total_size: int = 0
    retries: int = 0
    max_retries: int = 3
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def snapshot(self) -> Dict[str, Any]:
        """Thread-safe plain-dict snapshot for crossing layer boundaries."""
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "format_info": self.format_info,
            "output_path": self.output_path,
            "status": self.status,
            "progress": self.progress,
            "speed": self.speed,
            "eta": self.eta,
            "downloaded_size": self.downloaded_size,
            "total_size": self.total_size,
            "retries": self.retries,
        }