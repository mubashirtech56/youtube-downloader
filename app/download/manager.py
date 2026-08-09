"""Download orchestration layer.

Runs yt-dlp (and ffmpeg post-processors) in background workers, applies the
concurrency limits from settings, emits Qt signals whose payloads are plain
dictionaries so the UI (or any other consumer) never touches worker threads.

Layout grows toward the UI/ViewModel:
    DownloadManager -> yt-dlp / FFmpeg (no Qt UI knowledge)
"""

import logging
import threading
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, Signal, QTimer

from app.core.history import HistoryManager
from app.core.models import DownloadItem
from app.core.settings import SettingsManager
from app.core.utils import bundled_js_runtime, sanitize_filename, strip_ansi
from app.services import imports
from app.services.errors import is_cookie_error


class DownloadCancelled(Exception):
    """Raised from a progress hook to abort an in-flight download."""


class DownloadManager(QObject):
    """Queue + workers for youtube downloads. Emits snapshots via signals."""

    EVENT_ADDED = "added"
    EVENT_STARTED = "started"
    EVENT_PROGRESS = "progress"
    EVENT_COMPLETED = "completed"
    EVENT_FAILED = "failed"
    EVENT_CANCELLED = "cancelled"
    EVENT_PAUSED = "paused"
    EVENT_RESUMED = "resumed"
    EVENT_RETRY = "retry"

    # event_name(str), payload(dict snapshot or {})
    event = Signal(str, dict)

    def __init__(self, settings: SettingsManager, db: HistoryManager, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.db = db
        self.logger = logging.getLogger(__name__)

        self.download_queue: List[DownloadItem] = []
        self.active_downloads: Dict[str, threading.Thread] = {}
        self.max_concurrent = int(settings.get("max_concurrent_downloads", 3) or 3)
        self.lock = threading.RLock()
        self._progress_last: Dict[str, float] = {}
        self._prune_interval = 15.0
        self._progress_throttle = 0.25

        self._scheduler: Optional[QTimer] = None
        self._stopped = threading.Event()

    # ------------------------------------------------------------------ API

    def _outfile_exists(self, output_path: str, title: str) -> bool:
        base = Path(output_path) / sanitize_filename(title)
        try:
            for path in Path(output_path).glob(f"{base.name}.*"):
                if path.is_file() and path.suffix.lower() in (
                        ".mp4", ".mkv", ".webm", ".mov", ".avi",
                        ".mp3", ".m4a", ".opus", ".flac", ".wav", ".ogg"):
                    return True
        except OSError:
            return False
        return False

    def add_to_queue(self, video_info: Dict[str, Any], format_info: Dict[str, Any], output_path: str) -> str:
        with self.lock:
            video_id = video_info.get("id", "")
            existing = next((item for item in self.download_queue
                             if item.id == video_id and item.status in ("pending", "downloading", "paused")), None)
            if existing:
                return existing.id

            title = video_info.get("title", "")
            if not title or self._outfile_exists(output_path, title):
                return ""

            item = DownloadItem(
                id=video_id,
                url=video_info.get("webpage_url", ""),
                title=title,
                format_info=format_info,
                format_selector=format_info.get("_selector"),
                output_path=output_path,
                total_size=format_info.get("filesize", 0),
            )
            self.download_queue.append(item)
            self._prune_queue_locked()
            self.event.emit(self.EVENT_ADDED, deepcopy(item.snapshot()))
            return item.id

    def add_many_to_queue(self, video_infos: List[Dict[str, Any]], format_info: Dict[str, Any], output_path: str) -> int:
        added = 0
        with self.lock:
            active_ids = {item.id for item in self.download_queue
                          if item.status in ("pending", "downloading", "paused", "starting")}
            for video_info in video_infos:
                video_id = video_info.get("id", "")
                if not video_id or not video_info.get("title"):
                    continue
                if video_id in active_ids:
                    continue
                if self._outfile_exists(output_path, video_info.get("title", "")):
                    continue
                item = DownloadItem(
                    id=video_id,
                    url=video_info.get("webpage_url", ""),
                    title=video_info.get("title", ""),
                    format_info=format_info,
                    format_selector=format_info.get("_selector"),
                    output_path=output_path,
                    total_size=format_info.get("filesize", 0),
                )
                self.download_queue.append(item)
                active_ids.add(video_id)
                added += 1
            self._prune_queue_locked()
        if added:
            self.event.emit(self.EVENT_ADDED, {"added": added, "id": None})
        return added

    # ----------------------------------------------------------------------

    def start(self):
        """Start the timed scheduler that promotes pending items to workers."""
        if self._scheduler is not None:
            return
        self._stopped.clear()
        self._scheduler = QTimer(self)
        self._scheduler.setInterval(1000)
        self._scheduler.timeout.connect(self._on_tick)
        self._scheduler.start()

    def _on_tick(self):
        self._process_next()

    def _process_next(self):
        if self._stopped.is_set():
            return
        with self.lock:
            pending = [item for item in self.download_queue if item.status == "pending"]
            active_count = len([item for item in self.download_queue if item.status == "downloading"])
            to_start = pending[: max(0, self.max_concurrent - active_count)]
            for item in to_start:
                item.status = "starting"
                try:
                    self._start_download(item)
                except Exception as e:  # noqa: BLE001
                    self.logger.error(f"Failed to start download {item.id}: {e}")
                    item.status = "failed"
                    self.event.emit(self.EVENT_FAILED, {"id": item.id, "error": str(e)})
        self._prune_queue()

    def _start_download(self, item: DownloadItem):
        item.status = "downloading"
        item.start_time = datetime.now()
        item.cancel_event.clear()
        item.retries = 0
        output_dir = Path(item.output_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = sanitize_filename(item.title)

        format_info = item.format_info or {}
        format_id = format_info.get("format_id") or "best"
        format_selector = item.format_selector
        if not format_selector:
            has_video = format_info.get("has_video", False)
            has_audio = format_info.get("has_audio", False)
            if format_id == "best":
                format_selector = "bestvideo*+bestaudio/best"
            elif has_video and not has_audio:
                format_selector = f"{format_id}+bestaudio"
            else:
                format_selector = format_id

        is_audio_only = format_info.get("has_video") is False and format_info.get("has_audio") is True

        opts = {
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [lambda d: self._progress_hook(d, item)],
            "extract_flat": False,
            "ignoreerrors": True,
            "no_color": True,
            "geo_bypass": True,
            "geo_bypass_country": "US",
            "restrictfilenames": True,
            "outtmpl": str(output_dir / f"{filename}.%(ext)s"),
            "format": format_selector,
            "extractor_args": {"youtube": {"player_client": ["default", "android_vr", "tv"]}},
        }
        deno = bundled_js_runtime()
        if deno:
            opts["js_runtimes"] = {"deno": {"path": deno}}
        if is_audio_only:
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(self.settings.get("default_audio_quality", "192")),
            }]
        cookie_file = self.settings.get("cookie_file")
        cookie_browser = self.settings.get("cookie_browser")
        if cookie_file:
            opts["cookiefile"] = cookie_file
        elif cookie_browser:
            opts["cookiesfrombrowser"] = (cookie_browser, None, None, None)

        thread = threading.Thread(target=self._download_thread, args=(item, opts), daemon=True)
        self.active_downloads[item.id] = thread
        self.event.emit(self.EVENT_STARTED, deepcopy(item.snapshot()))
        thread.start()

    def _download_thread(self, item: DownloadItem, opts: Dict[str, Any]):
        try:
            self._run_download(item, opts)
            item.status = "completed"
            item.end_time = datetime.now()
            self._record_completed(item)
            self.event.emit(self.EVENT_COMPLETED, deepcopy(item.snapshot()))
        except DownloadCancelled:
            item.status = "cancelled"
            item.end_time = datetime.now()
            self.event.emit(self.EVENT_CANCELLED, deepcopy(item.snapshot()))
        except Exception as e:  # noqa: BLE001
            self.logger.error(f"Download failed for {item.id}: {e}")
            item.retries += 1
            if item.retries < item.max_retries:
                item.status = "pending"
                item.start_time = None
                self.event.emit(self.EVENT_RETRY, {"id": item.id, "attempt": item.retries})
            else:
                item.status = "failed"
                item.end_time = datetime.now()
                self.event.emit(self.EVENT_FAILED, {"id": item.id, "error": str(e)})
        finally:
            with self.lock:
                self.active_downloads.pop(item.id, None)

    def _run_download(self, item: DownloadItem, opts: Dict[str, Any]):
        """Run yt-dlp once, retrying without cookies on cookie errors or stale
        cookies that produce "Requested format is not available"."""
        used_cookies = bool(opts.get("cookiefile") or opts.get("cookiesfrombrowser"))
        try:
            with imports.yt_dlp().YoutubeDL(opts) as ydl:
                ydl.download([item.url])
        except Exception as e:
            no_formats = "requested format is not available" in str(e).lower()
            if is_cookie_error(e) or (used_cookies and no_formats):
                self.logger.warning("Cookie-related download failure, retrying without cookies: %s", e)
                stripped = dict(opts)
                stripped.pop("cookiefile", None)
                stripped.pop("cookiesfrombrowser", None)
                with imports.yt_dlp().YoutubeDL(stripped) as ydl:
                    ydl.download([item.url])
            else:
                raise

    def _progress_hook(self, d: Dict[str, Any], item: DownloadItem):
        if item.cancel_event.is_set():
            raise DownloadCancelled()
        status = d.get("status")
        if status == "downloading":
            try:
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes", 0)
                if total:
                    item.progress = min(downloaded / max(total, 1), 1.0)
                else:
                    percent = strip_ansi(str(d.get("_percent_str", "0%"))).strip().rstrip("%")
                    item.progress = min(float(percent) / 100.0, 1.0)
                item.speed = strip_ansi(str(d.get("_speed_str", "0")))
                item.eta = strip_ansi(str(d.get("_eta_str", "0")))
                item.downloaded_size = downloaded
                now = time.monotonic()
                last = self._progress_last.get(item.id, 0.0)
                if now - last >= self._progress_throttle:
                    self._progress_last[item.id] = now
                    self.event.emit(self.EVENT_PROGRESS, deepcopy(item.snapshot()))
            except DownloadCancelled:
                raise
            except Exception:  # noqa: BLE001
                pass

    def _record_completed(self, item: DownloadItem):
        try:
            output_dir = Path(item.output_path)
            base = sanitize_filename(item.title)
            fmt = (item.format_info or {}).get("resolution", "Unknown")
            download_path = ""
            file_size = item.total_size or item.downloaded_size or 0
            for path in output_dir.glob(f"{base}.*"):
                if path.is_file():
                    try:
                        file_size = path.stat().st_size
                    except OSError:
                        pass
                    download_path = str(path)
                    break
            self.db.add_history_entry({
                "id": item.id,
                "video_id": item.id,
                "title": item.title,
                "url": item.url,
                "format": fmt,
                "file_size": file_size,
                "download_path": download_path,
                "status": "completed",
                "created_at": datetime.now().isoformat(),
            })
        except Exception as e:
            self.logger.error(f"Failed to record history for {item.id}: {e}")

    # ----------------------------------------------------------- controls

    def pause_download(self, download_id: str):
        with self.lock:
            item = self._find_item(download_id)
            if item and item.status == "downloading":
                item.status = "paused"
                self.event.emit(self.EVENT_PAUSED, deepcopy(item.snapshot()))

    def resume_download(self, download_id: str):
        with self.lock:
            item = self._find_item(download_id)
            if item and item.status == "paused":
                item.status = "pending"
                self.event.emit(self.EVENT_RESUMED, deepcopy(item.snapshot()))

    def cancel_download(self, download_id: str):
        with self.lock:
            item = self._find_item(download_id)
            if item:
                item.status = "cancelled"
                item.end_time = datetime.now()
                item.cancel_event.set()
                self.event.emit(self.EVENT_CANCELLED, deepcopy(item.snapshot()))

    def retry_download(self, download_id: str):
        with self.lock:
            item = self._find_item(download_id)
            if item and item.status == "failed":
                item.status = "pending"
                item.retries = 0
                self.event.emit(self.EVENT_RETRY, {"id": item.id})

    def stop_all(self):
        with self.lock:
            for item in self.download_queue:
                if item.status in ("downloading", "pending", "starting", "paused"):
                    item.status = "cancelled"
                    item.end_time = datetime.now()
                    item.cancel_event.set()

    def shutdown(self):
        """Cancel all downloads and stop the scheduler so closing the app
        leaves no orphaned workers."""
        self._stopped.set()
        if self._scheduler is not None:
            self._scheduler.stop()
        with self.lock:
            for item in self.download_queue:
                if item.status in ("downloading", "pending", "starting", "paused"):
                    item.status = "cancelled"
                    item.end_time = datetime.now()
                    item.cancel_event.set()

    # ------------------------------------------------------------ helpers

    def active_items(self) -> List[DownloadItem]:
        with self.lock:
            return [item for item in self.download_queue
                    if item.status in ("pending", "downloading", "paused", "starting", "failed", "cancelled")]

    def find(self, download_id: str) -> Optional[DownloadItem]:
        with self.lock:
            return self._find_item(download_id)

    def _find_item(self, download_id: str) -> Optional[DownloadItem]:
        return next((item for item in self.download_queue if item.id == download_id), None)

    def _prune_queue(self):
        with self.lock:
            self._prune_queue_locked()

    def _prune_queue_locked(self):
        now = datetime.now()
        self.download_queue[:] = [
            item for item in self.download_queue
            if item.status in ("pending", "downloading", "paused", "starting", "failed")
            or (item.end_time and (now - item.end_time).total_seconds() < self._prune_interval)
        ]
        active_ids = {item.id for item in self.download_queue}
        for key in list(self._progress_last):
            if key not in active_ids:
                self._progress_last.pop(key, None)