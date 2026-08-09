"""Main Controller (ViewModel).

Owns the core services and mediates between the Qt UI layer and the service /
download layers. Runs blocking work (yt-dlp extraction, thumbnails) on a
background thread pool and reports results back through Qt signals on the GUI
thread, so the UI never touches threading itself.
"""

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from app.core.history import HistoryManager
from app.core.settings import SettingsManager
from app.download.manager import DownloadManager
from app.services.thumbnails import ThumbnailCache
from app.services.youtube import YouTubeService


class _FunctionTask(QRunnable):
    """Runs a callable on the threadpool and reports via a controller signal."""

    def __init__(self, fn: Callable[[], Any], done_signal: Signal, failed_signal: Signal):
        super().__init__()
        self.fn = fn
        self.done_signal = done_signal
        self.failed_signal = failed_signal

    def run(self):
        try:
            result = self.fn()
            self.done_signal.emit({"result": result})
        except Exception as e:  # noqa: BLE001
            self.failed_signal.emit({"error": str(e)})


class _ThumbnailTask(QRunnable):
    def __init__(self, fn: Callable[[], Any], signal: Signal, video_id: str):
        super().__init__()
        self.fn = fn
        self.signal = signal
        self.video_id = video_id

    def run(self):
        try:
            image = self.fn()
        except Exception:  # noqa: BLE001
            image = None
        self.signal.emit({"video_id": self.video_id, "image": image})


class MainController(QObject):
    """Single facade the UI pages use to reach the rest of the app."""

    videoFetched = Signal(dict)
    videoFailed = Signal(dict)
    playlistFetched = Signal(dict)
    playlistFailed = Signal(dict)
    thumbnailReady = Signal(dict)
    downloadEvent = Signal(str, dict)

    def __init__(self, settings: Optional[SettingsManager] = None, db: Optional[HistoryManager] = None,
                 thumbnail_cache: Optional[ThumbnailCache] = None,
                 youtube_service: Optional[YouTubeService] = None,
                 download_manager: Optional[DownloadManager] = None):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.settings = settings or SettingsManager()
        self.db = db or HistoryManager()
        self.thumbnail_cache = thumbnail_cache or ThumbnailCache()
        self.youtube_service = youtube_service or YouTubeService(self.settings)
        self.download_manager = download_manager or DownloadManager(self.settings, self.db)

        self.download_manager.event.connect(self._on_download_event)
        self._pool = QThreadPool.globalInstance()
        self._start_lock = threading.Lock()
        self._started = False

    # ------------------------------------------------------------- lifecycle

    def start(self):
        with self._start_lock:
            if not self._started:
                self._started = True
                self.download_manager.start()

    def shutdown(self):
        self.download_manager.shutdown()
        self.db.close()
        self.settings.close()

    # ----------------------------------------------------------- downloads

    @Slot(str, dict)
    def _on_download_event(self, event: str, payload: dict):
        self.downloadEvent.emit(event, payload)

    def queue_direct(self, video_info: Dict[str, Any], format_info: Dict[str, Any]):
        return self.download_manager.add_to_queue(
            video_info, format_info, self.settings.get("download_folder", str(Path.home() / "Downloads")))

    def queue_playlist(self, entries: List[Dict[str, Any]], format_info: Dict[str, Any]) -> int:
        return self.download_manager.add_many_to_queue(
            entries, format_info, self.settings.get("download_folder", str(Path.home() / "Downloads")))

    def quality_format(self, choice: str) -> Dict[str, Any]:
        """Translate a playlist "Default quality" option into a format dict."""
        if choice == "Best Audio":
            return {"format_id": "bestaudio", "has_video": False, "has_audio": True,
                    "resolution": "Best Audio", "filesize": 0, "_selector": "bestaudio/best"}
        if choice in ("1080p", "720p", "480p", "360p"):
            height = int(choice.replace("p", ""))
            return {"format_id": "best", "has_video": True, "has_audio": False,
                    "resolution": choice, "filesize": 0,
                    "_selector": f"bestvideo*[height<={height}]+bestaudio/best"}
        return {"format_id": "best", "has_video": True, "has_audio": False,
                "resolution": "Best Quality", "filesize": 0,
                "_selector": "bestvideo*+bestaudio/best"}

    def pause(self, item_id):
        self.download_manager.pause_download(item_id)

    def resume(self, item_id):
        self.download_manager.resume_download(item_id)

    def cancel(self, item_id):
        self.download_manager.cancel_download(item_id)

    def retry(self, item_id):
        self.download_manager.retry_download(item_id)

    def stop_all(self):
        self.download_manager.stop_all()

    def active_items(self):
        return self.download_manager.active_items()

    # -------------------------------------------------------------- fetch

    def fetch_video(self, url: str):
        task = _FunctionTask(lambda: self.youtube_service.get_video_info(url),
                             self.videoFetched, self.videoFailed)
        self._pool.start(task)

    def fetch_playlist(self, url: str, max_items: int = 0):
        task = _FunctionTask(lambda: self.youtube_service.get_playlist_info(url, max_items=max_items),
                             self.playlistFetched, self.playlistFailed)
        self._pool.start(task)

    def fetch_thumbnail_async(self, video_id: str, url: str):
        def _work() -> Optional[Any]:
            if not url:
                return None
            return self.thumbnail_cache.get_thumbnail(video_id, url)

        task = _ThumbnailTask(_work, self.thumbnailReady, video_id)
        self._pool.start(task)

    # ------------------------------------------------------------- helpers

    def open_download_folder(self):
        from app.core.utils import open_folder

        folder = self.settings.get("download_folder", str(Path.home() / "Downloads"))
        Path(folder).mkdir(parents=True, exist_ok=True)
        open_folder(folder)