#!/usr/bin/env python3
"""
YouTube Downloader Pro - Main Entry Point
A professional YouTube downloader desktop application
"""

import sys
import os
import logging
import hashlib
from pathlib import Path
from datetime import datetime
import threading
import queue
import json
import subprocess
import re
from typing import Optional, Dict, Any, List, Callable, Tuple
from dataclasses import dataclass, field
import time
import io
from tkinter import filedialog

import customtkinter as ctk

# ----------------------------------------------------------------------------
# customtkinter 6.0.0 bug: CTkOptionMenu and CTkScrollbar redraw calls
# self._canvas.update_idletasks() synchronously. Inside that synchronous flush,
# the Canvas can drag in a <Configure>/scrollbar-set event that triggers another
# redraw -> update_idletasks -> ... , an unbounded ping-pong that freezes the
# GUI. Fix: make CTkCanvas.update_idletasks() defer the actual flush to the next
# idle cycle (deduplicated), so redraw storms settle one event at a time instead
# of recursing inside a single draw call.
# ----------------------------------------------------------------------------
try:
    from customtkinter.windows.widgets.core_rendering import CTkCanvas as _CTkCanvas

    _ORIGINAL_CANVAS_UPDATE_IDLETASKS = _CTkCanvas.update_idletasks

    def _deferred_canvas_update_idletasks(self):
        if getattr(self, '_ctk_flush_pending', False):
            return
        self._ctk_flush_pending = True

        def _flush():
            self._ctk_flush_pending = False
            try:
                _ORIGINAL_CANVAS_UPDATE_IDLETASKS(self)
            except Exception:
                pass

        self.after_idle(_flush)

    _CTkCanvas.update_idletasks = _deferred_canvas_update_idletasks
except ImportError:
    pass  # Open-source customtkinter builds that don't need the workaround

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

# Lazy import helpers for the expensive third-party dependencies.
#
# `yt_dlp` is by far the most costly import in the project (it pulls in its
# entire extractor/postprocessor tree, ~1s when cold). `requests` and `PIL`
# also add noticeable overhead. None of them are needed before the user
# actually fetches/downloads something, so we defer importing them until their
# first use and cache the result on the module. Tests that want to substitute
# fakes can still `mock.patch.object(main, 'yt_dlp', ...)` etc. and the
# getters will pick the injected module up because they resolve the name from
# module globals at call time.

class DownloadCancelled(Exception):
    """Raised from a progress hook to abort an in-flight download."""
    pass


def app_icon_path() -> Optional[str]:
    """Locate the bundled YouTube icon (PNG) both in dev and frozen builds."""
    candidates = []
    if getattr(sys, 'frozen', False):
        base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
        candidates.append(base / 'youtube-dl.png')
        candidates.append(Path(sys.executable).parent / 'youtube-dl.png')
        candidates.append(base / 'youtube-downloader.png')
        candidates.append(base / 'icons' / 'youtube-downloader-256.png')
    candidates.append(Path(__file__).resolve().parent / 'youtube-dl.png')
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def app_icon_ico_path() -> Optional[str]:
    """Locate a packaged Windows .ico (fallback for iconbitmap)."""
    if not getattr(sys, 'frozen', False):
        return None
    base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    for c in (base / 'icons' / 'youtube-downloader.ico',
              Path(sys.executable).parent / 'youtube-downloader.ico'):
        if c.is_file():
            return str(c)
    return None


def _load_module(name: str):
    """Resolve `name` from globals (honoring mocks), importing it if absent."""
    module = globals().get(name)
    if module is None:
        module = __import__(name)
        globals()[name] = module
    return module


def _yt_dlp():
    """Return the `yt_dlp` module, importing it lazily on first use."""
    return _load_module('yt_dlp')


def _requests():
    """Return the `requests` module, importing it lazily on first use."""
    return _load_module('requests')


def _pil():
    """Return the `PIL.Image` module, importing it lazily on first use."""
    image = globals().get('Image')
    if image is None:
        from PIL import Image
        globals()['Image'] = Image
        image = Image
    return image

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
_FILENAME_RE = re.compile(r'[<>:"/\\|?*]')
_URL_PATTERNS = [
    re.compile(r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v='),
    re.compile(r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/'),
    re.compile(r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/shorts\/'),
    re.compile(r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/playlist\?list='),
]

def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)

def sanitize_filename(filename: str) -> str:
    """Sanitize filename by removing invalid characters"""
    sanitized = _FILENAME_RE.sub('', filename)
    sanitized = sanitized.strip('. ')
    if len(sanitized) > 200:
        sanitized = sanitized[:200]
    return sanitized or 'video'

def format_size(size: int) -> str:
    """Format file size in human-readable format"""
    if not size:
        return 'Unknown'
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.1f} {units[i]}"

def format_duration(seconds: int) -> str:
    """Format duration in human-readable format"""
    if not seconds:
        return '0:00'
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"

def format_timestamp(timestamp: Optional[str]) -> str:
    """Format timestamp to readable date/time"""
    if not timestamp:
        return '—'
    try:
        dt = datetime.fromisoformat(timestamp)
        return dt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        return timestamp

def is_valid_youtube_url(url: str) -> bool:
    """Validate YouTube URL"""
    for pattern in _URL_PATTERNS:
        if pattern.match(url):
            return True
    return False

# ============================================================================
# THREAD-SAFE GUI DISPATCH
#
# Tkinter is NOT thread-safe. Work that happens on background threads (yt-dlp
# extraction, downloads, thumbnail downloads) must NEVER call widget methods
# or `after()` directly. All cross-thread GUI updates go through this queue and
# are drained by the main thread inside a single `after()` poller.
# ============================================================================

_GUI_QUEUE: "queue.Queue[Tuple[Callable, tuple, dict]]" = queue.Queue()

_FONT_CACHE: Dict[Tuple[int, str], "ctk.CTkFont"] = {}

def get_font(size: int = 12, weight: str = "normal") -> "ctk.CTkFont":
    """Return a cached CTkFont. Creating fonts is expensive, so reuse them."""
    key = (size, weight)
    font = _FONT_CACHE.get(key)
    if font is None:
        font = ctk.CTkFont(size=size, weight=weight)
        _FONT_CACHE[key] = font
    return font

def gui_call(fn: Callable, *args, **kwargs):
    """Marshal a callable onto the main thread. Safe to call from any thread."""
    _GUI_QUEUE.put((fn, args, kwargs))

def drain_gui_queue():
    """Execute all pending main-thread callbacks. Must run on the GUI thread."""
    while True:
        try:
            fn, args, kwargs = _GUI_QUEUE.get_nowait()
        except queue.Empty:
            return
        try:
            fn(*args, **kwargs)
        except Exception:
            logging.getLogger(__name__).exception("Error in scheduled GUI callback")

# ============================================================================
# SETTINGS MANAGER
# ============================================================================

class SettingsManager:
    """Manage application settings"""

    DEFAULT_SETTINGS = {
        'theme': 'dark',
        'language': 'en',
        'download_folder': str(Path.home() / "Downloads" / "YouTube"),
        'max_concurrent_downloads': 3,
        'default_quality': '1080p',
        'default_audio_quality': '192',
        'default_output_format': 'mp4',
        'notifications': True,
        'auto_update_check': True,
        'cookie_file': None,
        'cookie_browser': None,
        'ffmpeg_path': None,
        'window_width': 1200,
        'window_height': 800,
        'window_maximized': True,
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.settings_path = Path.home() / ".youtube_downloader" / "settings.json"
        self.settings = self._load_settings()

    def _load_settings(self) -> Dict[str, Any]:
        try:
            if self.settings_path.exists():
                with open(self.settings_path, 'r') as f:
                    settings = json.load(f)
                    return {**self.DEFAULT_SETTINGS, **settings}
        except Exception as e:
            self.logger.error(f"Failed to load settings: {e}")
        return self.DEFAULT_SETTINGS.copy()

    def save(self):
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.settings_path, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save settings: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any):
        self.settings[key] = value
        self.save()

    def reset(self):
        self.settings = self.DEFAULT_SETTINGS.copy()
        self.save()

# ============================================================================
# HISTORY MANAGER
# ============================================================================

class HistoryManager:
    """Record successfully downloaded videos to a plain-text history file.

    Only downloads that actually complete are written to history.txt; queued
    or merely fetched videos are never recorded.
    """

    _SEP = '\t'

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.history_path = Path.home() / ".youtube_downloader" / "history.txt"
        self.history_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _serialize(cls, data: Dict[str, Any]) -> str:
        created_at = data.get('created_at') or datetime.now().isoformat()
        fields = [
            created_at,
            str(data.get('id', '')),
            str(data.get('title', '')),
            str(data.get('url', '')),
            str(data.get('format', '')),
            str(data.get('file_size', 0) or 0),
            str(data.get('download_path', '')),
        ]
        return cls._SEP.join(field.replace(cls._SEP, ' ') for field in fields)

    @classmethod
    def _parse_line(cls, line: str) -> Optional[Dict[str, Any]]:
        parts = line.rstrip('\n').split(cls._SEP)
        if len(parts) < 7:
            return None
        created_at, entry_id, title, url, fmt, size, path = parts[:7]
        return {
            'id': entry_id,
            'video_id': entry_id,
            'title': title,
            'url': url,
            'format': fmt,
            'file_size': int(size) if size.isdigit() else 0,
            'download_path': path,
            'status': 'completed',
            'metadata': {},
            'created_at': created_at,
        }

    def _append(self, data: Dict[str, Any]) -> str:
        try:
            line = self._serialize(data)
            with open(self.history_path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
            return str(data.get('id', ''))
        except Exception as e:
            self.logger.error(f"Failed to append history: {e}")
            return ''

    def add_history_entry(self, data: Dict[str, Any]) -> str:
        """Append one entry, but only when the download completed."""
        if data.get('status') != 'completed':
            return ''
        return self._append(data)

    def add_history_entries(self, rows: List[Dict[str, Any]]):
        """Append only the rows whose download completed."""
        for row in rows:
            if row.get('status') == 'completed':
                self._append(row)

    def get_history(self, limit: int = 100, offset: int = 0, status: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            lines = self.history_path.read_text(encoding='utf-8').splitlines()
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
            if status and entry['status'] != status:
                continue
            if search:
                haystack = " ".join([entry['title'], entry['url'], entry['id']])
                if search.lower() not in haystack.lower():
                    continue
            entries.append(entry)
        return entries[offset:offset + limit]

    def delete_history_entry(self, entry_id: str):
        try:
            matching_id = entry_id
            lines = self.history_path.read_text(encoding='utf-8').splitlines()
            kept = [line for line in lines
                    if not (self._parse_line(line) and self._parse_line(line)['id'] == matching_id)]
            self.history_path.write_text('\n'.join(kept) + ('\n' if kept else ''), encoding='utf-8')
        except FileNotFoundError:
            return
        except Exception as e:
            self.logger.error(f"Failed to delete history entry: {e}")

    def clear_history(self):
        try:
            self.history_path.write_text('', encoding='utf-8')
        except Exception as e:
            self.logger.error(f"Failed to clear history: {e}")

    def close(self):
        """Called when the app shuts down. No OS resources are held, so this
        is a no-op kept so `_on_close` can treat every manager uniformly."""

# ============================================================================
# DOWNLOAD ITEM MODEL
# ============================================================================

@dataclass
class DownloadItem:
    """Download item data model"""
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

# ============================================================================
# YOUTUBE SERVICE
# ============================================================================

class YouTubeService:
    """Service for interacting with YouTube"""

    _CACHE_TTL = 300.0
    _CACHE_MAX = 64

    def __init__(self, settings: Optional[SettingsManager] = None):
        self.logger = logging.getLogger(__name__)
        self.settings = settings
        # In-process TTL cache so repeated fetches of the same URL do not cause
        # repeated network extraction (the slowest, most expensive operation).
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'ignoreerrors': True,
            'no_color': True,
            'geo_bypass': True,
            'geo_bypass_country': 'US',
            'format': 'best',
            'cookiefile': self.settings.get('cookie_file') if self.settings else None,
            'js_runtimes': {'node': {}},
            'extractor_args': {'youtube': {'player_client': ['default', 'android_vr', 'tv']}},
        }

    def _cache_get(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry is not None:
            ts, value = entry
            if time.monotonic() - ts < self._CACHE_TTL:
                return value
            self._cache.pop(key, None)
        return None

    def _cache_put(self, key: str, value: Any):
        if len(self._cache) >= self._CACHE_MAX:
            self._cache.pop(next(iter(self._cache)), None)
        self._cache[key] = (time.monotonic(), value)

    def _get_opts(self) -> Dict[str, Any]:
        opts = dict(self.ydl_opts)
        if self.settings:
            cookie_file = self.settings.get('cookie_file')
            cookie_browser = self.settings.get('cookie_browser')
            opts.pop('cookiefile', None)
            opts.pop('cookiesfrombrowser', None)
            if cookie_file:
                opts['cookiefile'] = cookie_file
            elif cookie_browser:
                opts['cookiesfrombrowser'] = (cookie_browser, None, None, None)
        return opts

    def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            if not is_valid_youtube_url(url):
                raise ValueError("Invalid YouTube URL")

            cache_key = f"video:{url}"
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

            with _yt_dlp().YoutubeDL(self._get_opts()) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return None

                video_formats, audio_formats = self._process_formats(info)

                result = {
                    'id': info.get('id', ''),
                    'title': info.get('title', ''),
                    'description': info.get('description', ''),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'upload_date': info.get('upload_date', ''),
                    'uploader': info.get('uploader', ''),
                    'channel': info.get('channel', ''),
                    'channel_id': info.get('channel_id', ''),
                    'view_count': info.get('view_count', 0),
                    'like_count': info.get('like_count', 0),
                    'comment_count': info.get('comment_count', 0),
                    'tags': info.get('tags', []),
                    'categories': info.get('categories', []),
                    'age_limit': info.get('age_limit', 0),
                    'is_live': info.get('is_live', False),
                    'webpage_url': info.get('webpage_url', url),
                    'video_formats': video_formats,
                    'audio_formats': audio_formats,
                    'best_video': video_formats[0] if video_formats else None,
                    'best_audio': audio_formats[0] if audio_formats else None,
                    'height': video_formats[0].get('height', 0) if video_formats else 0,
                }
                self._cache_put(cache_key, result)
                return result
        except Exception as e:
            self.logger.error(f"Error fetching video info: {e}")
            return None

    def _process_formats(self, info: Dict[str, Any]) -> tuple:
        video_formats = []
        audio_formats = []
        formats = info.get('formats', [])

        for fmt in formats:
            if fmt.get('vcodec') != 'none' and fmt.get('acodec') != 'none':
                video_formats.append({
                    'format_id': fmt.get('format_id', ''),
                    'resolution': fmt.get('resolution', ''),
                    'height': fmt.get('height', 0),
                    'width': fmt.get('width', 0),
                    'fps': fmt.get('fps', 0),
                    'codec': fmt.get('vcodec', ''),
                    'acodec': fmt.get('acodec', ''),
                    'container': fmt.get('ext', 'mp4'),
                    'filesize': fmt.get('filesize', 0),
                    'abr': fmt.get('abr', 0),
                    'quality': fmt.get('height', 0),
                    'has_video': True,
                    'has_audio': True,
                })
            elif fmt.get('vcodec') != 'none':
                video_formats.append({
                    'format_id': fmt.get('format_id', ''),
                    'resolution': fmt.get('resolution', ''),
                    'height': fmt.get('height', 0),
                    'width': fmt.get('width', 0),
                    'fps': fmt.get('fps', 0),
                    'codec': fmt.get('vcodec', ''),
                    'container': fmt.get('ext', 'mp4'),
                    'filesize': fmt.get('filesize', 0),
                    'quality': fmt.get('height', 0),
                    'has_video': True,
                    'has_audio': False,
                })
            elif fmt.get('acodec') != 'none':
                audio_formats.append({
                    'format_id': fmt.get('format_id', ''),
                    'codec': fmt.get('acodec', ''),
                    'container': fmt.get('ext', 'mp3'),
                    'filesize': fmt.get('filesize', 0),
                    'abr': fmt.get('abr', 0),
                    'bitrate': fmt.get('abr', 0),
                    'has_video': False,
                    'has_audio': True,
                })

        video_formats = self._dedupe_video_formats(video_formats)
        audio_formats = self._dedupe_audio_formats(audio_formats)
        return video_formats, audio_formats

    def _dedupe_video_formats(self, formats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        best_by_height = {}
        for fmt in formats:
            height = fmt.get('height', 0)
            if not height:
                continue
            current = best_by_height.get(height)
            if current is None or fmt.get('quality', 0) > current.get('quality', 0):
                best_by_height[height] = fmt
        return [best_by_height[h] for h in sorted(best_by_height, reverse=True)]

    def _dedupe_audio_formats(self, formats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        best_by_bitrate = {}
        for fmt in formats:
            bitrate = int(round(fmt.get('abr', 0) / 16.0) * 16)
            current = best_by_bitrate.get(bitrate)
            if current is None or fmt.get('abr', 0) > current.get('abr', 0):
                best_by_bitrate[bitrate] = fmt
        return [best_by_bitrate[b] for b in sorted(best_by_bitrate, reverse=True)]

    def get_playlist_info(self, url: str, max_items: int = 0) -> Optional[Dict[str, Any]]:
        try:
            if not is_valid_youtube_url(url):
                raise ValueError("Invalid YouTube URL")

            # Cache under a key including the limit so a limited fetch is never
            # served from an unlimited one (and vice-versa).
            cache_key = f"playlist:{url}:{max_items}"
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

            opts = self._get_opts()
            opts['extract_flat'] = 'in_playlist'
            if max_items > 0:
                # yt-dlp `playlist_items` limits how many videos are actually
                # extracted from the playlist (1-based, inclusive), so we never
                # download metadata for the whole playlist just to drop most of it.
                opts['playlist_items'] = f'1-{max_items}'
            with _yt_dlp().YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return None

                entries = []
                for entry in info.get('entries', []):
                    if entry:
                        video_id = entry.get('id', '')
                        thumbnail = entry.get('thumbnail', '')
                        if not thumbnail and video_id:
                            thumbnail = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
                        webpage_url = entry.get('webpage_url') or entry.get('url') or f"https://www.youtube.com/watch?v={video_id}"
                        entries.append({
                            'id': video_id,
                            'title': entry.get('title', ''),
                            'duration': entry.get('duration', 0),
                            'thumbnail': thumbnail,
                            'webpage_url': webpage_url,
                        })

                # Safety net in case the yt-dlp build ignores `playlist_items`.
                if max_items > 0 and len(entries) > max_items:
                    entries = entries[:max_items]

                result = {
                    'title': info.get('title', ''),
                    'description': info.get('description', ''),
                    'uploader': info.get('uploader', ''),
                    'view_count': info.get('view_count', 0),
                    'entries': entries,
                    'entry_count': len(entries),
                    'max_items': max_items,
                    'thumbnail': info.get('thumbnail', ''),
                    'webpage_url': info.get('webpage_url', url),
                }
                self._cache_put(cache_key, result)
                return result
        except Exception as e:
            self.logger.error(f"Error fetching playlist info: {e}")
            return None

# ============================================================================
# DOWNLOAD SERVICE
# ============================================================================

class DownloadService:
    """Manages video downloads"""

    def __init__(self, settings: SettingsManager, db: HistoryManager):
        self.settings = settings
        self.db = db
        self.logger = logging.getLogger(__name__)

        self.download_queue: List[DownloadItem] = []
        self.active_downloads: Dict[str, threading.Thread] = {}
        self.download_callbacks: List[Callable] = []
        self.is_processing = False
        self.max_concurrent = settings.get('max_concurrent_downloads', 3)
        self.lock = threading.Lock()
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._loop_thread: Optional[threading.Thread] = None
        self._progress_last: Dict[str, float] = {}
        self._prune_interval = 15.0
        # Progress callbacks are throttled to ~4/s per item. The GUI additionally
        # coalesces refreshes, so this must not be called on every yt-dlp hook.
        self._progress_throttle = 0.25

    def _outfile_exists(self, output_path: str, title: str) -> bool:
        """Cheap local existence check so already-downloaded files are skipped
        without ever contacting YouTube."""
        base = Path(output_path) / sanitize_filename(title)
        try:
            for path in Path(output_path).glob(f"{base.name}.*"):
                if path.is_file() and path.suffix.lower() in ('.mp4', '.mkv', '.webm', '.mov', '.avi',
                                                              '.mp3', '.m4a', '.opus', '.flac', '.wav', '.ogg'):
                    return True
        except OSError:
            return False
        return False

    def add_to_queue(self, video_info: Dict[str, Any], format_info: Dict[str, Any], output_path: str) -> str:
        with self.lock:
            video_id = video_info.get('id', '')
            existing = next((item for item in self.download_queue if item.id == video_id and item.status in ['pending', 'downloading', 'paused']), None)
            if existing:
                return existing.id

            title = video_info.get('title', '')
            if not title or self._outfile_exists(output_path, title):
                return ''

            item = DownloadItem(
                id=video_id,
                url=video_info.get('webpage_url', ''),
                title=title,
                format_info=format_info,
                format_selector=format_info.get('_selector'),
                output_path=output_path,
                total_size=format_info.get('filesize', 0)
            )
            self.download_queue.append(item)
            self._prune_queue_locked()
            self._notify_callbacks('added', item)
            self._wake_event.set()
            return item.id

    def add_many_to_queue(self, video_infos: List[Dict[str, Any]], format_info: Dict[str, Any], output_path: str) -> int:
        added = 0
        with self.lock:
            active_ids = {item.id for item in self.download_queue
                          if item.status in ['pending', 'downloading', 'paused', 'starting']}
            for video_info in video_infos:
                video_id = video_info.get('id', '')
                if not video_id or not video_info.get('title'):
                    continue
                if video_id in active_ids:
                    continue
                if self._outfile_exists(output_path, video_info.get('title', '')):
                    continue
                item = DownloadItem(
                    id=video_id,
                    url=video_info.get('webpage_url', ''),
                    title=video_info.get('title', ''),
                    format_info=format_info,
                    format_selector=format_info.get('_selector'),
                    output_path=output_path,
                    total_size=format_info.get('filesize', 0)
                )
                self.download_queue.append(item)
                active_ids.add(video_id)
                added += 1
            self._prune_queue_locked()
        if added:
            self._wake_event.set()
        return added

    def start_queue(self):
        with self.lock:
            if not self.is_processing:
                self.is_processing = True
                self._wake_event.set()
                if self._loop_thread is None or not self._loop_thread.is_alive():
                    self._loop_thread = threading.Thread(target=self._process_queue, daemon=True, name="download-scheduler")
                    self._loop_thread.start()

    def _process_queue(self):
        """Event-driven scheduler loop. Blocks on an event and only wakes when
        the queue changes or the prune interval elapses."""
        while not self._stop_event.is_set():
            self._wake_event.wait(1.0)
            self._wake_event.clear()
            if self._stop_event.is_set():
                break
            with self.lock:
                if not self.is_processing:
                    continue
                pending = [item for item in self.download_queue if item.status == 'pending']
                active_count = len([item for item in self.download_queue if item.status == 'downloading'])
                to_start = pending[:max(0, self.max_concurrent - active_count)]
                for item in to_start:
                    item.status = 'starting'
                    self._start_download(item)
            self._prune_queue()

    def _prune_queue(self):
        with self.lock:
            self._prune_queue_locked()

    def _prune_queue_locked(self):
        now = datetime.now()
        self.download_queue[:] = [
            item for item in self.download_queue
            if item.status in ['pending', 'downloading', 'paused', 'starting']
            or (item.end_time and (now - item.end_time).total_seconds() < self._prune_interval)
        ]
        active_ids = {item.id for item in self.download_queue}
        for key in list(self._progress_last):
            if key not in active_ids:
                self._progress_last.pop(key, None)

    def _start_download(self, item: DownloadItem):
        try:
            item.status = 'downloading'
            item.start_time = datetime.now()
            item.cancel_event.clear()
            item.retries = item.retries if item.retries else 0
            output_dir = Path(item.output_path)
            output_dir.mkdir(parents=True, exist_ok=True)

            filename = sanitize_filename(item.title)

            format_info = item.format_info or {}
            format_id = format_info.get('format_id') or 'best'
            format_selector = item.format_selector
            if not format_selector:
                has_video = format_info.get('has_video', False)
                has_audio = format_info.get('has_audio', False)
                if format_id == 'best':
                    format_selector = 'bestvideo*+bestaudio/best'
                elif has_video and not has_audio:
                    format_selector = f"{format_id}+bestaudio"
                else:
                    format_selector = format_id

            # Audio-only downloads: yt-dlp grabs an opus stream in a webm/opus
            # container, so convert it to MP3 via ffmpeg (which also renames the
            # finished file to .mp3). The two required keys (`has_video`/`has_audio`)
            # are always set to booleans for every format we produce, so `is False`
            # reliably means "audio-only" and never mis-fires for video items.
            is_audio_only = format_info.get('has_video') is False and format_info.get('has_audio') is True

            opts = {
                'quiet': True,
                'no_warnings': True,
                'progress_hooks': [lambda d: self._progress_hook(d, item)],
                'extract_flat': False,
                'ignoreerrors': True,
                'no_color': True,
                'geo_bypass': True,
                'geo_bypass_country': 'US',
                'restrictfilenames': True,
                'outtmpl': str(output_dir / f"{filename}.%(ext)s"),
                'format': format_selector,
                'js_runtimes': {'node': {}},
                'extractor_args': {'youtube': {'player_client': ['default', 'android_vr', 'tv']}},
            }
            if is_audio_only:
                opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': str(self.settings.get('default_audio_quality', '192')),
                }]
            cookie_file = self.settings.get('cookie_file')
            cookie_browser = self.settings.get('cookie_browser')
            if cookie_file:
                opts['cookiefile'] = cookie_file
            elif cookie_browser:
                opts['cookiesfrombrowser'] = (cookie_browser, None, None, None)

            thread = threading.Thread(target=self._download_thread, args=(item, opts), daemon=True)
            self.active_downloads[item.id] = thread
            thread.start()

        except Exception as e:
            self.logger.error(f"Failed to start download {item.id}: {e}")
            item.status = 'failed'
            self._handle_failure(item, str(e))

    def _download_thread(self, item: DownloadItem, opts: Dict[str, Any]):
        try:
            with _yt_dlp().YoutubeDL(opts) as ydl:
                ydl.download([item.url])
                item.status = 'completed'
                item.end_time = datetime.now()
                self._record_completed(item)
                self._notify_callbacks('completed', item)
        except DownloadCancelled:
            item.status = 'cancelled'
            item.end_time = datetime.now()
            self._notify_callbacks('cancelled', item)
        except Exception as e:
            self.logger.error(f"Download failed for {item.id}: {e}")
            item.retries += 1
            if item.retries < item.max_retries:
                item.status = 'pending'
                item.start_time = None
                self._notify_callbacks('retry', item)
            else:
                item.status = 'failed'
                item.end_time = datetime.now()
                self._handle_failure(item, str(e))
        finally:
            with self.lock:
                self.active_downloads.pop(item.id, None)
                self._wake_event.set()

    def _progress_hook(self, d: Dict[str, Any], item: DownloadItem):
        if item.cancel_event.is_set():
            raise DownloadCancelled()
        status = d.get('status')
        if status == 'downloading':
            try:
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes', 0)
                if total:
                    item.progress = min(downloaded / total, 1.0)
                else:
                    percent = strip_ansi(str(d.get('_percent_str', '0%'))).strip().rstrip('%')
                    item.progress = min(float(percent) / 100, 1.0)
                item.speed = strip_ansi(str(d.get('_speed_str', '0')))
                item.eta = strip_ansi(str(d.get('_eta_str', '0')))
                item.downloaded_size = downloaded
                now = time.monotonic()
                last = self._progress_last.get(item.id, 0.0)
                if now - last >= self._progress_throttle:
                    self._progress_last[item.id] = now
                    self._notify_callbacks('progress', item)
            except DownloadCancelled:
                raise
            except Exception:
                pass

    def _record_completed(self, item: DownloadItem):
        """Record a successfully downloaded video in history.txt."""
        try:
            output_dir = Path(item.output_path)
            base = sanitize_filename(item.title)
            fmt = (item.format_info or {}).get('resolution', 'Unknown')
            download_path = ''
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
                'id': item.id,
                'video_id': item.id,
                'title': item.title,
                'url': item.url,
                'format': fmt,
                'file_size': file_size,
                'download_path': download_path,
                'status': 'completed',
                'created_at': datetime.now().isoformat(),
            })
        except Exception as e:
            self.logger.error(f"Failed to record history for {item.id}: {e}")

    def _handle_failure(self, item: DownloadItem, error: str):
        item.end_time = datetime.now()
        self._notify_callbacks('failed', item, error)

    def pause_download(self, download_id: str):
        with self.lock:
            item = self._find_item(download_id)
            if item and item.status == 'downloading':
                item.status = 'paused'
                self._notify_callbacks('paused', item)

    def resume_download(self, download_id: str):
        with self.lock:
            item = self._find_item(download_id)
            if item and item.status == 'paused':
                item.status = 'pending'
                self._notify_callbacks('resumed', item)

    def cancel_download(self, download_id: str):
        with self.lock:
            item = self._find_item(download_id)
            if item:
                item.status = 'cancelled'
                item.end_time = datetime.now()
                item.cancel_event.set()
                self._notify_callbacks('cancelled', item)

    def retry_download(self, download_id: str):
        with self.lock:
            item = self._find_item(download_id)
            if item and item.status == 'failed':
                item.status = 'pending'
                item.retries = 0
                self._notify_callbacks('retry', item)

    def stop_all(self):
        with self.lock:
            self.is_processing = False
            for item in self.download_queue:
                if item.status in ['downloading', 'pending', 'starting', 'paused']:
                    item.status = 'cancelled'
                    item.end_time = datetime.now()
                    item.cancel_event.set()
            self._wake_event.set()

    def shutdown(self):
        """Stop scheduling, cancel every in-flight download and wait for the
        scheduler thread to exit so closing the app leaves no orphans."""
        with self.lock:
            self.is_processing = False
            self._stop_event.set()
            for item in self.download_queue:
                if item.status in ['downloading', 'pending', 'starting', 'paused']:
                    item.status = 'cancelled'
                    item.end_time = datetime.now()
                    item.cancel_event.set()
            self._wake_event.set()
        # Give in-flight yt-dlp workers a moment to observe the cancellation and
        # terminate their ffmpeg subprocesses before the interpreter shuts down.
        self.logger.info("Waiting for in-flight workers to stop...")
        time.sleep(0.4)
        loop = self._loop_thread
        if loop and loop.is_alive():
            loop.join(timeout=3.0)

    def _find_item(self, download_id: str) -> Optional[DownloadItem]:
        return next((item for item in self.download_queue if item.id == download_id), None)

    def register_callback(self, callback: Callable):
        self.download_callbacks.append(callback)

    def _notify_callbacks(self, event: str, item: DownloadItem, *args):
        for callback in self.download_callbacks:
            try:
                callback(event, item, *args)
            except Exception as e:
                self.logger.error(f"Callback error: {e}")

# ============================================================================
# THEME MANAGER
# ============================================================================

class ThemeManager:
    """Manage application themes"""

    def __init__(self, settings: SettingsManager):
        self.settings = settings
        self.current_theme = settings.get('theme', 'dark')
        ctk.set_appearance_mode("dark" if self.current_theme == 'dark' else "light")
        ctk.set_default_color_theme("blue")

    def apply_theme(self, widget: Optional[ctk.CTk] = None):
        if widget:
            ctk.set_appearance_mode("dark" if self.current_theme == 'dark' else "light")

    def toggle_theme(self):
        self.current_theme = 'light' if self.current_theme == 'dark' else 'dark'
        self.settings.set('theme', self.current_theme)
        ctk.set_appearance_mode(self.current_theme)

    def get_theme(self) -> str:
        return self.current_theme

# ============================================================================
# THUMBNAIL CACHE
# ============================================================================

class ThumbnailCache:
    """Cache and manage thumbnails"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.cache_dir = Path.home() / ".youtube_downloader" / "thumbnails"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_cache_size = 100 * 1024 * 1024
        self._memory_cache: Dict[str, Any] = {}
        self._max_memory_items = 30
        self._last_cleanup = 0.0
        self._cleanup_interval = 300.0

    def _memory_get(self, key: str) -> Optional[Any]:
        return self._memory_cache.get(key)

    def _memory_put(self, key: str, image: Any):
        if len(self._memory_cache) >= self._max_memory_items:
            self._memory_cache.pop(next(iter(self._memory_cache)), None)
        self._memory_cache[key] = image

    def get_thumbnail(self, video_id: str, url: str, size: tuple = (400, 225)) -> Optional[Any]:
        try:
            Image = _pil()
            cache_key = hashlib.md5(f"{video_id}_{size[0]}x{size[1]}".encode()).hexdigest()

            cached = self._memory_get(cache_key)
            if cached is not None:
                return cached

            cache_path = self.cache_dir / f"{cache_key}.jpg"
            if cache_path.exists():
                image = Image.open(cache_path)
                image.load()
                self._memory_put(cache_key, image)
                return image

            if url:
                response = _requests().get(url, timeout=10)
                if response.status_code == 200:
                    image = Image.open(io.BytesIO(response.content))
                    image.thumbnail(size, Image.Resampling.LANCZOS)
                    image.save(cache_path, 'JPEG', quality=85)
                    self._memory_put(cache_key, image)
                    now = time.monotonic()
                    if now - self._last_cleanup > self._cleanup_interval:
                        self._last_cleanup = now
                        self._cleanup_cache()
                    return image
            return None
        except Exception as e:
            self.logger.error(f"Failed to get thumbnail: {e}")
            return None

    def _cleanup_cache(self):
        try:
            cache_files = list(self.cache_dir.glob("*.jpg"))
            total_size = sum(f.stat().st_size for f in cache_files)
            if total_size > self.max_cache_size:
                cache_files.sort(key=lambda f: f.stat().st_mtime)
                for file in cache_files:
                    total_size -= file.stat().st_size
                    file.unlink()
                    if total_size <= self.max_cache_size * 0.8:
                        break
        except Exception as e:
            self.logger.error(f"Failed to clean cache: {e}")

# ============================================================================
# SIDEBAR
# ============================================================================

class Sidebar(ctk.CTkFrame):
    """Sidebar navigation component"""

    NAV_ITEMS = [
        ("🏠 Home", "home"),
        ("📃 Playlist", "playlist"),
        ("⬇ Downloading", "downloading"),
        ("🕒 History", "history"),
        ("👤 Account", "account"),
        ("⚙ Settings", "settings")
    ]

    def __init__(self, parent, on_navigate: Callable, width: int = 240, **kwargs):
        super().__init__(parent, width=width, **kwargs)
        self.on_navigate = on_navigate
        self.buttons = {}
        self.active_button = None
        self._create_layout()

    def _create_layout(self):
        self.logo_label = ctk.CTkLabel(
            self,
            text="🎬 YouTube\nDownloader",
            font=get_font(20, "bold"),
            justify="center"
        )
        self.logo_label.pack(pady=30)

        self.separator = ctk.CTkFrame(self, height=2, fg_color="gray30")
        self.separator.pack(fill="x", padx=20, pady=10)

        for text, page_name in self.NAV_ITEMS:
            btn = ctk.CTkButton(
                self,
                text=text,
                command=lambda p=page_name: self._navigate(p),
                font=get_font(14),
                height=45,
                anchor="w",
                corner_radius=8,
                fg_color="transparent",
                hover_color="gray30"
            )
            btn.pack(fill="x", padx=15, pady=5)
            self.buttons[page_name] = btn

        self.spacer = ctk.CTkFrame(self, fg_color="transparent")
        self.spacer.pack(fill="both", expand=True)

        self.version_label = ctk.CTkLabel(
            self,
            text="v1.0.0",
            font=get_font(10),
            text_color="gray50"
        )
        self.version_label.pack(pady=10)

    def _navigate(self, page_name: str):
        self.on_navigate(page_name)
        self.set_active(page_name)

    def set_active(self, page_name: str):
        for name, btn in self.buttons.items():
            btn.configure(fg_color="transparent", text_color=("gray10", "gray90"))
        if page_name in self.buttons:
            self.buttons[page_name].configure(fg_color="blue", text_color="white")
            self.active_button = page_name

# ============================================================================
# HOME PAGE
# ============================================================================

class HomePage(ctk.CTkFrame):
    """Home page for single video downloads"""

    def __init__(self, parent, settings: SettingsManager, db: HistoryManager, download_service: DownloadService, youtube_service: Optional[YouTubeService] = None, thumbnail_cache: Optional[ThumbnailCache] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.logger = logging.getLogger(__name__)
        self.settings = settings
        self.db = db
        self.download_service = download_service
        self.youtube_service = youtube_service or YouTubeService(settings)
        self.thumbnail_cache = thumbnail_cache or ThumbnailCache()

        self.current_video_info: Optional[Dict[str, Any]] = None
        self.selected_format: Optional[Dict[str, Any]] = None
        self.is_fetching = False

        self._create_layout()

    def _create_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Search bar
        search_frame = ctk.CTkFrame(self, fg_color="transparent")
        search_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=20)
        search_frame.grid_columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(search_frame, placeholder_text="Enter YouTube URL...", height=45, font=get_font(14))
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.url_entry.bind("<Return>", lambda e: self._fetch_video())

        self.fetch_btn = ctk.CTkButton(search_frame, text="🔍 Fetch", command=self._fetch_video, height=45, width=120)
        self.fetch_btn.grid(row=0, column=1)

        # Content area
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        content.grid_columnconfigure(0, weight=4)
        content.grid_columnconfigure(1, weight=6)
        content.grid_rowconfigure(0, weight=1)

        # Left column
        self.left_frame = ctk.CTkFrame(content, fg_color="transparent")
        self.left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self.thumbnail_label = ctk.CTkLabel(self.left_frame, text="No video loaded", width=400, height=225, corner_radius=10, fg_color="gray20")
        self.thumbnail_label.pack(pady=(0, 10))

        # Info labels
        info_frame = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        info_frame.pack(fill="x")

        self.info_labels = {}
        for key, label in [("channel", "Channel"), ("duration", "Duration"), ("date", "Upload Date"),
                           ("views", "Views"), ("likes", "Likes"), ("resolution", "Resolution")]:
            frame = ctk.CTkFrame(info_frame, fg_color="transparent")
            frame.pack(fill="x", pady=2)
            ctk.CTkLabel(frame, text=f"{label}:", font=get_font(12, "bold"), width=100).pack(side="left")
            self.info_labels[key] = ctk.CTkLabel(frame, text="—", font=get_font(12))
            self.info_labels[key].pack(side="left", padx=(10, 0))

        # Right column
        self.right_frame = ctk.CTkFrame(content, fg_color="transparent")
        self.right_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.right_frame.grid_rowconfigure(1, weight=1)
        self.right_frame.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(self.right_frame, text="Enter a URL to get started", font=get_font(20, "bold"), wraplength=600, justify="left")
        self.title_label.grid(row=0, column=0, sticky="w", padx=(10, 10), pady=(0, 10))

        self.desc_frame = ctk.CTkFrame(self.right_frame, height=100, fg_color="gray20", corner_radius=8)
        self.desc_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        self.desc_frame.grid_columnconfigure(0, weight=1)
        self.desc_label = ctk.CTkLabel(self.desc_frame, text="", wraplength=580, justify="left", anchor="nw", font=get_font(12))
        self.desc_label.grid(row=0, column=0, sticky="nw", padx=10, pady=10)

        # Download controls
        controls = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="ew")

        btn_row = ctk.CTkFrame(controls, fg_color="transparent")
        btn_row.pack(fill="x", pady=10)

        self.size_label = ctk.CTkLabel(btn_row, text="Estimated Size: —", font=get_font(12))
        self.size_label.pack(side="left", padx=(0, 20))

        self.filename_label = ctk.CTkLabel(btn_row, text="Filename: —", font=get_font(12))
        self.filename_label.pack(side="left")

        btn_row2 = ctk.CTkFrame(controls, fg_color="transparent")
        btn_row2.pack(fill="x")

        for text, command in [("📋 Add to Batch", self._add_to_batch), ("⬇ Start Download", self._start_download),
                              ("📁 Open Folder", self._open_folder), ("📋 Copy URL", self._copy_url)]:
            btn = ctk.CTkButton(btn_row2, text=text, command=command, height=35, font=get_font(12))
            btn.pack(side="left", padx=5)

    def _fetch_video(self):
        if self.is_fetching:
            return
        url = self.url_entry.get().strip()
        if not url:
            return
        self.is_fetching = True
        self.fetch_btn.configure(text="⏳ Loading...", state="disabled")
        threading.Thread(target=self._fetch_video_thread, args=(url,), daemon=True).start()

    def _fetch_video_thread(self, url: str):
        try:
            video_info = self.youtube_service.get_video_info(url)
            if video_info:
                gui_call(self._on_video_fetched, video_info)
            else:
                gui_call(self._fetch_failed, "Failed to fetch video (invalid URL or unavailable)")
        except Exception as e:
            gui_call(self._on_fetch_error, e)
        finally:
            self.is_fetching = False
            gui_call(lambda: self.fetch_btn.configure(text="🔍 Fetch", state="normal"))

    def _fetch_failed(self, message: str):
        self.title_label.configure(text="Failed to fetch video")
        self.desc_label.configure(text=message)

    def _on_fetch_error(self, error: Exception):
        self.title_label.configure(text="Error fetching video")
        self.desc_label.configure(text=str(error))

    def _on_video_fetched(self, video_info: Dict[str, Any]):
        self.current_video_info = video_info
        self._update_video_info()
        self._fetch_thumbnail(video_info.get('thumbnail', ''))

    def _update_video_info(self):
        if not self.current_video_info:
            return
        info = self.current_video_info
        self.title_label.configure(text=info.get('title', 'Unknown Title'))
        desc = info.get('description', 'No description available')
        self.desc_label.configure(text=desc[:500] + ('...' if len(desc) > 500 else ''))

        info_map = {'channel': info.get('channel', '—'), 'duration': format_duration(info.get('duration', 0)),
                    'date': info.get('upload_date', '—'), 'views': f"{info.get('view_count', 0):,}",
                    'likes': f"{info.get('like_count', 0):,}" if info.get('like_count') else '—',
                    'resolution': f"{info.get('height', 0)}p"}
        for key, value in info_map.items():
            if key in self.info_labels:
                self.info_labels[key].configure(text=value)
        self._update_format_lists(info)

    def _fetch_thumbnail_thread(self, video_id: str, url: str):
        try:
            image = self.thumbnail_cache.get_thumbnail(video_id, url)
            if image:
                gui_call(self._set_thumbnail, image)
        except Exception as e:
            self.logger.warning(f"Failed to fetch thumbnail: {e}")

    def _fetch_thumbnail(self, url: str):
        if not url:
            return
        video_id = self.current_video_info.get('id', '') if self.current_video_info else ''
        threading.Thread(target=self._fetch_thumbnail_thread, args=(video_id, url), daemon=True, name="thumbnail-download").start()

    def _set_thumbnail(self, image):
        try:
            self._thumbnail_image = ctk.CTkImage(light_image=image, dark_image=image, size=(400, 225))
            self.thumbnail_label.configure(image=self._thumbnail_image, text="")
        except Exception:
            pass

    def _ensure_format_area(self):
        """Lazily build the format tabview the first time a video is loaded.

        The tabview and its two scrollable frames are the most expensive widgets
        on the Home page, so they are deferred until they are actually needed
        (this keeps the initial Home page build much lighter)."""
        if getattr(self, 'tab_view', None) is not None:
            return
        self.tab_view = ctk.CTkTabview(self.right_frame, height=250)
        self.tab_view.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
        self.tab_view.add("🎬 Video")
        self.tab_view.add("🎵 Audio")

        self.video_formats_frame = ctk.CTkScrollableFrame(self.tab_view.tab("🎬 Video"), fg_color="transparent")
        self.video_formats_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.audio_formats_frame = ctk.CTkScrollableFrame(self.tab_view.tab("🎵 Audio"), fg_color="transparent")
        self.audio_formats_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.video_format_var = ctk.StringVar(value="")
        self.audio_format_var = ctk.StringVar(value="")

    def _update_format_lists(self, info: Dict[str, Any]):
        video_id = info.get('id', '')
        self._ensure_format_area()
        if getattr(self, '_rendered_video_id', None) == video_id:
            return
        self._rendered_video_id = video_id

        for widget in self.video_formats_frame.winfo_children():
            widget.destroy()
        for widget in self.audio_formats_frame.winfo_children():
            widget.destroy()

        for fmt in info.get('video_formats', []):
            self._create_format_item(self.video_formats_frame, fmt, 'video', self.video_format_var)
        for fmt in info.get('audio_formats', []):
            self._create_format_item(self.audio_formats_frame, fmt, 'audio', self.audio_format_var)

        if info.get('video_formats'):
            self.selected_format = info['video_formats'][0]
            self._update_download_info()

    def _create_format_item(self, parent, format_info: Dict[str, Any], format_type: str, group_var):
        frame = ctk.CTkFrame(parent, fg_color="gray20", corner_radius=8)
        frame.pack(fill="x", pady=3)

        var = group_var
        radio = ctk.CTkRadioButton(frame, text="", variable=var, value=format_info.get('format_id', ''),
                                   command=lambda: self._select_format(format_info))
        radio.pack(side="left", padx=10)

        details = []
        if format_type == 'video':
            details.append(f"{format_info.get('resolution', 'Unknown')}")
            details.append(f"{format_info.get('fps', '?')} FPS")
            details.append(format_info.get('codec', 'Unknown'))
            details.append(format_info.get('container', 'mp4'))
        else:
            details.append(f"{format_info.get('bitrate', '?')} kbps")
            details.append(format_info.get('codec', 'Unknown'))
            details.append(format_info.get('container', 'mp3'))
            details.append(format_size(format_info.get('filesize', 0)))

        label = ctk.CTkLabel(frame, text=" • ".join(details), font=get_font(12))
        label.pack(side="left", padx=5)
        frame.format_info = format_info

    def _select_format(self, format_info: Dict[str, Any]):
        self.selected_format = format_info
        self._update_download_info()

    def _update_download_info(self):
        if not self.selected_format or not self.current_video_info:
            return
        fmt = self.selected_format
        info = self.current_video_info
        size = fmt.get('filesize', 0)
        self.size_label.configure(text=f"Estimated Size: {format_size(size)}")
        title = sanitize_filename(info.get('title', 'video'))
        ext = fmt.get('container', 'mp4')
        self.filename_label.configure(text=f"Filename: {title}.{ext}")

    def _add_to_batch(self):
        if not self.selected_format or not self.current_video_info:
            return
        self.download_service.add_to_queue(self.current_video_info, self.selected_format,
                                           self.settings.get('download_folder', str(Path.home() / "Downloads")))
        logging.getLogger(__name__).info("Added to download queue")

    def _start_download(self):
        if not self.selected_format or not self.current_video_info:
            return
        self._add_to_batch()
        self.download_service.start_queue()

    def _open_folder(self):
        folder = self.settings.get('download_folder', str(Path.home() / "Downloads"))
        Path(folder).mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.Popen(f'xdg-open "{folder}"', shell=True)

    def _copy_url(self):
        url = self.url_entry.get().strip()
        if url:
            self.clipboard_clear()
            self.clipboard_append(url)
            logging.getLogger(__name__).info("URL copied to clipboard")

# ============================================================================
# PLAYLIST PAGE
# ============================================================================

class PlaylistPage(ctk.CTkFrame):
    def __init__(self, parent, settings, db, download_service, youtube_service: Optional[YouTubeService] = None, thumbnail_cache: Optional[ThumbnailCache] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.logger = logging.getLogger(__name__)
        self.settings = settings
        self.db = db
        self.download_service = download_service
        self.youtube_service = youtube_service or YouTubeService(settings)
        self.thumbnail_cache = thumbnail_cache or ThumbnailCache()
        self.current_playlist = None
        self.selected_entries = set()
        self._entry_vars = {}
        self._create_layout()

    def _create_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        search_frame = ctk.CTkFrame(self, fg_color="transparent")
        search_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))
        search_frame.grid_columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(search_frame, placeholder_text="Enter YouTube Playlist URL...", height=45)
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.url_entry.bind("<Return>", lambda e: self._fetch_playlist())

        self.fetch_btn = ctk.CTkButton(search_frame, text="🔍 Fetch Playlist", command=self._fetch_playlist, height=45, width=140)
        self.fetch_btn.grid(row=0, column=1)

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))
        toolbar.grid_columnconfigure(0, weight=1)

        self.select_all_var = ctk.BooleanVar(value=False)
        self.select_all_check = ctk.CTkCheckBox(toolbar, text="Select All", variable=self.select_all_var, command=self._toggle_select_all, height=30)
        self.select_all_check.grid(row=0, column=0, sticky="w", padx=(0, 10))

        self.max_label = ctk.CTkLabel(toolbar, text="Max videos:", font=get_font(12))
        self.max_label.grid(row=0, column=1, padx=(10, 5))
        self.max_entry = ctk.CTkEntry(toolbar, placeholder_text="all", width=70, height=30)
        self.max_entry.grid(row=0, column=2, padx=(0, 10))
        self.max_entry.bind("<Return>", lambda e: self._fetch_playlist())

        self.format_label = ctk.CTkLabel(toolbar, text="Default:", font=get_font(12))
        self.format_label.grid(row=0, column=3, padx=(10, 5))
        self.format_combo = ctk.CTkOptionMenu(toolbar, values=["Best Quality", "Best Audio", "1080p", "720p", "480p", "360p"], width=130, height=30)
        self.format_combo.set("Best Quality")
        self.format_combo.grid(row=0, column=4, padx=(0, 10))

        self.download_selected_btn = ctk.CTkButton(toolbar, text="⬇ Download Selected", command=self._download_selected, height=32, width=160)
        self.download_selected_btn.grid(row=0, column=5, padx=(10, 0))
        content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        content.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 20))

        self.info_label = ctk.CTkLabel(content, text="Enter a playlist URL to get started", font=get_font(16, "bold"))
        self.info_label.pack(pady=20)

        self.video_list = ctk.CTkScrollableFrame(content, fg_color="transparent", height=400)
        self.video_list.pack(fill="both", expand=True)

    def _get_max_items(self) -> int:
        raw = self.max_entry.get().strip()
        if not raw:
            return 0
        try:
            value = int(raw)
        except ValueError:
            return 0
        return max(0, value)

    def _fetch_playlist(self):
        url = self.url_entry.get().strip()
        if not url:
            return
        max_items = self._get_max_items()
        self.fetch_btn.configure(text="⏳ Loading...", state="disabled")
        threading.Thread(target=self._fetch_playlist_thread, args=(url, max_items), daemon=True).start()

    def _fetch_playlist_thread(self, url: str, max_items: int = 0):
        try:
            playlist_info = self.youtube_service.get_playlist_info(url, max_items=max_items)
            gui_call(self._on_playlist_fetched, playlist_info) if playlist_info else gui_call(self._on_playlist_failed)
        except Exception as e:
            self.logger.warning(f"Error fetching playlist: {e}")
        finally:
            gui_call(lambda: self.fetch_btn.configure(text="🔍 Fetch Playlist", state="normal"))

    def _on_playlist_failed(self):
        self.info_label.configure(text="Failed to fetch playlist (invalid URL or unavailable)")

    def _on_playlist_fetched(self, playlist_info: Dict[str, Any]):
        self.current_playlist = playlist_info
        self._update_playlist_info()

    _BATCH_SIZE = 50

    def _update_playlist_info(self):
        if not self.current_playlist:
            return
        playlist = self.current_playlist
        count = playlist.get('entry_count', 0)
        max_items = playlist.get('max_items', 0)
        if max_items > 0:
            self.info_label.configure(text=f"📋 {playlist.get('title', 'Unknown')} - showing {count} / {max_items} videos")
        else:
            self.info_label.configure(text=f"📋 {playlist.get('title', 'Unknown')} - {count} videos")

        self._playlist_entries = playlist.get('entries', [])
        self._entry_vars = {}
        self.selected_entries = set()
        self.select_all_var.set(False)
        self._batch_index = 0
        self._render_job = getattr(self, '_render_job', 0) + 1

        for widget in self.video_list.winfo_children():
            widget.destroy()

        self._render_batch()

    def _render_batch(self):
        if not hasattr(self, '_playlist_entries'):
            return
        start = self._batch_index
        end = min(self._batch_index + self._BATCH_SIZE, len(self._playlist_entries))
        for idx in range(start, end):
            self._render_entry(self._playlist_entries[idx], idx + 1)
        self._batch_index = end
        if self._batch_index < len(self._playlist_entries):
            job = self._render_job
            self.after(1, lambda: self._render_batch() if job == self._render_job else None)

    def _render_entry(self, entry: Dict[str, Any], idx: int):
        frame = ctk.CTkFrame(self.video_list, fg_color="gray20" if idx % 2 == 0 else "gray25", corner_radius=5)
        frame.pack(fill="x", pady=2)

        var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(frame, text="", variable=var, width=30,
                        command=lambda e=entry, v=var: self._toggle_entry(e, v)).pack(side="left", padx=(8, 2))

        ctk.CTkLabel(frame, text=f"{idx}.", width=44, anchor="w", font=get_font(12, "bold"),
                     text_color="gray60").pack(side="left", padx=(2, 2))

        title = entry.get('title', 'Unknown')
        title_text = title[:60] + ('...' if len(title) > 60 else '')
        ctk.CTkLabel(frame, text=title_text, anchor="w", font=get_font(12)).pack(side="left", fill="x", expand=True, padx=5)

        ctk.CTkLabel(frame, text=format_duration(entry.get('duration', 0)), anchor="e",
                     font=get_font(11), text_color="gray60").pack(side="right", padx=8)

        self._entry_vars[entry.get('id', idx)] = {'entry': entry, 'var': var}

    def _quality_format(self, choice: str) -> Dict[str, Any]:
        if choice == "Best Audio":
            return {'format_id': 'bestaudio', 'has_video': False, 'has_audio': True,
                    'resolution': 'Best Audio', 'filesize': 0, '_selector': 'bestaudio/best'}
        if choice in ("1080p", "720p", "480p", "360p"):
            height = int(choice.replace('p', ''))
            return {'format_id': 'best', 'has_video': True, 'has_audio': False,
                    'resolution': choice, 'filesize': 0,
                    '_selector': f'bestvideo*[height<={height}]+bestaudio/best'}
        return {'format_id': 'best', 'has_video': True, 'has_audio': False,
                'resolution': 'Best Quality', 'filesize': 0,
                '_selector': 'bestvideo*+bestaudio/best'}

    def _toggle_entry(self, entry: Dict[str, Any], var: ctk.BooleanVar):
        if var.get():
            self.selected_entries.add(entry.get('id', ''))
        else:
            self.selected_entries.discard(entry.get('id', ''))
        self.select_all_var.set(len(self._entry_vars) > 0 and len(self.selected_entries) == len(self._entry_vars))

    def _toggle_select_all(self):
        selected = self.select_all_var.get()
        self.selected_entries.clear()
        for data in self._entry_vars.values():
            data['var'].set(selected)
            if selected:
                self.selected_entries.add(data['entry'].get('id', ''))

    def _get_selected_entries(self) -> List[Dict[str, Any]]:
        selected = []
        for data in self._entry_vars.values():
            if data['var'].get():
                selected.append(data['entry'])
        return selected

    def _download_selected(self):
        entries = [self._to_video_info(e) for e in self._get_selected_entries()
                   if e.get('id') and e.get('title')]
        if not entries:
            logging.getLogger(__name__).info("No videos selected")
            return
        fmt = self._quality_format(self.format_combo.get())
        added = self.download_service.add_many_to_queue(
            entries, fmt, self.settings.get('download_folder', str(Path.home() / "Downloads")))
        if added:
            self.download_service.start_queue()
            logging.getLogger(__name__).info(f"Added {added} video(s) to queue")

    def _to_video_info(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        return {'id': entry.get('id', ''), 'title': entry.get('title', ''), 'webpage_url': entry.get('webpage_url', ''),
                'duration': entry.get('duration', 0), 'thumbnail': entry.get('thumbnail', '')}

# ============================================================================
# DOWNLOADING PAGE
# ============================================================================

class DownloadingPage(ctk.CTkFrame):
    def __init__(self, parent, settings, db, download_service, youtube_service: Optional[YouTubeService] = None, thumbnail_cache: Optional[ThumbnailCache] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.settings = settings
        self.db = db
        self.download_service = download_service
        self.download_service.register_callback(self._on_download_event)
        self._last_refresh = 0
        self._refresh_scheduled = False
        self._create_layout()

    def _create_layout(self):
        self.main_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        self.main_frame.grid_columnconfigure(0, weight=1)

        self._cards = {}
        self._placeholder = None
        self._placeholder = ctk.CTkLabel(self.main_frame, text="No active downloads", font=get_font(16, "bold"))
        self._placeholder.pack(expand=True)

    def _on_download_event(self, event: str, item: Any, *args):
        now = time.monotonic()
        if event == 'progress':
            if now - self._last_refresh < 0.3:
                return
        elif self._last_refresh and now - self._last_refresh < 0.05:
            return
        if self._refresh_scheduled:
            return
        self._refresh_scheduled = True
        gui_call(self._refresh_now)

    def _refresh_now(self):
        self._refresh_scheduled = False
        self._last_refresh = time.monotonic()
        self._update_downloads()

    def _update_downloads(self):
        with self.download_service.lock:
            active_downloads = [item for item in self.download_service.download_queue
                                if item.status in ['pending', 'downloading', 'paused', 'starting']]
        if not active_downloads:
            if self._cards:
                for refs in self._cards.values():
                    refs['card'].destroy()
                self._cards = {}
            if self._placeholder is None:
                self._placeholder = ctk.CTkLabel(self.main_frame, text="No active downloads", font=get_font(16, "bold"))
                self._placeholder.pack(expand=True)
            return

        if self._placeholder is not None:
            self._placeholder.destroy()
            self._placeholder = None

        active_ids = set()
        for item in active_downloads:
            active_ids.add(item.id)
            if item.id in self._cards:
                self._update_card(self._cards[item.id], item)
            else:
                card = self._create_card(item)
                self._cards[item.id] = card
        for item_id in list(self._cards):
            if item_id not in active_ids:
                self._cards.pop(item_id)['card'].destroy()

    def _create_card(self, item: DownloadItem) -> Dict[str, Any]:
        card = ctk.CTkFrame(self.main_frame, corner_radius=10, fg_color="gray20")
        card.pack(fill="x", pady=5)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text=item.title[:60] + ('...' if len(item.title) > 60 else ''), font=get_font(14, "bold")).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 5))

        status_label = ctk.CTkLabel(card, text=item.status.title(), font=get_font(12))
        status_label.grid(row=1, column=0, sticky="w", padx=10, pady=5)

        progress = ctk.CTkProgressBar(card, height=15, corner_radius=5)
        progress.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        progress.set(min(item.progress, 1.0))

        details = ctk.CTkFrame(card, fg_color="transparent")
        details.grid(row=3, column=0, sticky="ew", padx=10, pady=5)

        speed_label = ctk.CTkLabel(details, text=f"Speed: {item.speed}", font=get_font(11))
        speed_label.pack(side="left", padx=10)
        eta_label = ctk.CTkLabel(details, text=f"ETA: {item.eta}", font=get_font(11))
        eta_label.pack(side="left", padx=10)

        controls = ctk.CTkFrame(card, fg_color="transparent")
        controls.grid(row=4, column=0, sticky="ew", padx=10, pady=(5, 10))

        pause_btn = ctk.CTkButton(controls, text="⏸ Pause", command=lambda: self.download_service.pause_download(item.id), height=30, width=80, font=get_font(11))
        resume_btn = ctk.CTkButton(controls, text="▶ Resume", command=lambda: self.download_service.resume_download(item.id), height=30, width=80, font=get_font(11))
        cancel_btn = ctk.CTkButton(controls, text="⏹ Cancel", command=lambda: self.download_service.cancel_download(item.id), height=30, width=80, font=get_font(11))
        cancel_btn.pack(side="left", padx=5)

        return {
            'card': card,
            'status_label': status_label,
            'progress': progress,
            'speed_label': speed_label,
            'eta_label': eta_label,
            'controls': controls,
            'pause_btn': pause_btn,
            'resume_btn': resume_btn,
            'item': item,
        }

    def _update_card(self, refs: Dict[str, Any], item: DownloadItem):
        refs['status_label'].configure(text=item.status.title(),
                                       text_color={"pending": "yellow", "downloading": "blue", "paused": "orange"}.get(item.status, "gray"))
        refs['progress'].set(min(item.progress, 1.0))
        refs['speed_label'].configure(text=f"Speed: {item.speed}")
        refs['eta_label'].configure(text=f"ETA: {item.eta}")

        for btn in (refs['pause_btn'], refs['resume_btn']):
            btn.pack_forget()
        if item.status == 'downloading':
            refs['pause_btn'].pack(side="left", padx=5)
        elif item.status == 'paused':
            refs['resume_btn'].pack(side="left", padx=5)

# ============================================================================
# HISTORY PAGE
# ============================================================================

class HistoryPage(ctk.CTkFrame):
    def __init__(self, parent, settings, db, download_service, youtube_service: Optional[YouTubeService] = None, thumbnail_cache: Optional[ThumbnailCache] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.settings = settings
        self.db = db
        self._create_layout()

    def on_show(self):
        self._load_history()

    def _create_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=0, column=0, sticky="ew", padx=20, pady=20)
        controls.grid_columnconfigure(0, weight=1)

        self.search_entry = ctk.CTkEntry(controls, placeholder_text="Search history...", width=250, height=35)
        self.search_entry.pack(side="left", padx=(0, 10))
        self.search_entry.bind("<Return>", lambda e: self._load_history())

        self.filter_combo = ctk.CTkOptionMenu(controls, values=["All", "Completed", "Failed", "Pending"], command=lambda x: self._load_history(), width=120, height=35)
        self.filter_combo.pack(side="left", padx=10)

        ctk.CTkButton(controls, text="🗑 Delete All", command=self._delete_all, height=35).pack(side="right", padx=5)
        ctk.CTkButton(controls, text="🔄 Refresh", command=self._load_history, height=35).pack(side="right", padx=5)

        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        self.scroll_frame.grid_columnconfigure(0, weight=1)

        self.items_container = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        self.items_container.pack(fill="both", expand=True)

    _BATCH_SIZE = 20

    def _load_history(self):
        for widget in self.items_container.winfo_children():
            widget.destroy()

        status = self.filter_combo.get() if self.filter_combo.get() != "All" else None
        if status:
            status = status.lower()
        search = self.search_entry.get().strip() or None

        entries = self.db.get_history(limit=100, status=status, search=search)
        self._history_entries = entries
        if not entries:
            ctk.CTkLabel(self.items_container, text="No history entries", font=get_font(16, "bold")).pack(expand=True)
            return

        self._history_index = 0
        self._history_job = getattr(self, '_history_job', 0) + 1
        self._render_history_batch()

    def _render_history_batch(self):
        if not hasattr(self, '_history_entries'):
            return
        start = self._history_index
        end = min(start + self._BATCH_SIZE, len(self._history_entries))
        entries = self._history_entries
        for idx in range(start, end):
            self._render_history_row(entries[idx])
        self._history_index = end
        if self._history_index < len(entries):
            job = self._history_job
            self.after(1, lambda: self._render_history_batch() if job == self._history_job else None)

    def _render_history_row(self, entry):
        frame = ctk.CTkFrame(self.items_container, corner_radius=5, fg_color="gray20")
        frame.pack(fill="x", pady=2)

        ctk.CTkLabel(frame, text=entry.get('title', 'Unknown')[:40], width=300, anchor="w", font=get_font(12)).pack(side="left", padx=10, pady=8)
        ctk.CTkLabel(frame, text=entry.get('format', 'Unknown'), width=100, font=get_font(12)).pack(side="left", padx=10)
        ctk.CTkLabel(frame, text=format_size(entry.get('file_size', 0)), width=80, font=get_font(12)).pack(side="left", padx=10)

        status = entry.get('status', 'unknown')
        colors = {"completed": "green", "failed": "red", "pending": "yellow"}
        ctk.CTkLabel(frame, text=status.title(), width=80, font=get_font(12), text_color=colors.get(status, "gray")).pack(side="left", padx=10)

        ctk.CTkLabel(frame, text=format_timestamp(entry.get('created_at', '')), width=150, font=get_font(11)).pack(side="left", padx=10)

        ctk.CTkButton(frame, text="🗑", command=lambda e=entry: self._delete_entry(e), width=40, height=25, font=get_font(12)).pack(side="right", padx=5)

    def _delete_entry(self, entry):
        self.db.delete_history_entry(entry.get('id', ''))
        self._load_history()

    def _delete_all(self):
        self.db.clear_history()
        self._load_history()

# ============================================================================
# ACCOUNT PAGE
# ============================================================================

class AccountPage(ctk.CTkFrame):
    def __init__(self, parent, settings, db, download_service, youtube_service: Optional[YouTubeService] = None, thumbnail_cache: Optional[ThumbnailCache] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.settings = settings
        self._create_layout()

    def _create_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        main_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        main_frame.grid(row=0, column=0, sticky="nsew", padx=40, pady=40)
        main_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(main_frame, text="👤 Account Settings", font=get_font(28, "bold")).pack(anchor="w", pady=(0, 30))

        section = ctk.CTkFrame(main_frame, corner_radius=10, fg_color="gray20")
        section.pack(fill="x", pady=10)

        ctk.CTkLabel(section, text="🍪 Cookie Import", font=get_font(18, "bold")).pack(anchor="w", padx=20, pady=(20, 10))
        ctk.CTkLabel(section, text="Import cookies from your browser to access restricted content", font=get_font(12), text_color="gray60").pack(anchor="w", padx=20, pady=(0, 15))

        cookie_file = self.settings.get('cookie_file', '')
        self.cookie_label = ctk.CTkLabel(section, text=cookie_file or "No cookie file loaded", font=get_font(12), wraplength=600)
        self.cookie_label.pack(anchor="w", padx=20, pady=(0, 10))

        btn_frame = ctk.CTkFrame(section, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 20))

        ctk.CTkButton(btn_frame, text="📂 Import Cookies", command=self._import_cookies, height=35).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="🗑 Remove Cookies", command=self._remove_cookies, height=35).pack(side="left", padx=5)

        ctk.CTkLabel(section, text="Supported format: Netscape cookies.txt", font=get_font(11), text_color="gray50").pack(anchor="w", padx=20, pady=(0, 20))

        browser_section = ctk.CTkFrame(main_frame, corner_radius=10, fg_color="gray20")
        browser_section.pack(fill="x", pady=10)

        ctk.CTkLabel(browser_section, text="🌐 Browser Cookies", font=get_font(18, "bold")).pack(anchor="w", padx=20, pady=(20, 10))
        ctk.CTkLabel(browser_section, text="Use cookies directly from an installed browser (recommended, never expires)", font=get_font(12), text_color="gray60").pack(anchor="w", padx=20, pady=(0, 15))

        browser_frame = ctk.CTkFrame(browser_section, fg_color="transparent")
        browser_frame.pack(fill="x", padx=20, pady=(0, 20))

        ctk.CTkLabel(browser_frame, text="Browser:", font=get_font(13, "bold")).pack(side="left", padx=(0, 10))

        self.browser_combo = ctk.CTkOptionMenu(
            browser_frame,
            values=["None", "chrome", "firefox", "chromium", "brave", "edge", "opera", "vivaldi"],
            command=self._set_browser,
            width=140, height=35
        )
        self.browser_combo.pack(side="left", padx=(0, 10))

        current_browser = self.settings.get('cookie_browser', '')
        self.browser_combo.set(current_browser if current_browser in self.browser_combo._values else "None")

    def _set_browser(self, browser: str):
        value = None if browser == "None" else browser
        self.settings.set('cookie_browser', value)
        logging.getLogger(__name__).info(f"Browser cookies set to: {browser}")

    def _import_cookies(self):
        file_path = filedialog.askopenfilename(title="Select Cookies File", filetypes=[("Netscape Cookies", "*.txt"), ("All Files", "*.*")])
        if file_path:
            self.settings.set('cookie_file', file_path)
            self.settings.set('cookie_browser', None)
            self.browser_combo.set("None")
            self.cookie_label.configure(text=file_path)
            logging.getLogger(__name__).info("Cookies imported successfully")

    def _remove_cookies(self):
        self.settings.set('cookie_file', '')
        self.cookie_label.configure(text="No cookie file loaded")
        logging.getLogger(__name__).info("Cookies removed")

# ============================================================================
# SETTINGS PAGE
# ============================================================================

class SettingsPage(ctk.CTkFrame):
    def __init__(self, parent, settings, db, download_service, youtube_service: Optional[YouTubeService] = None, thumbnail_cache: Optional[ThumbnailCache] = None, **kwargs):
        super().__init__(parent, **kwargs)
        self.settings = settings
        self.db = db
        self._create_layout()

    def _create_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        main_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        main_frame.grid(row=0, column=0, sticky="nsew", padx=40, pady=40)
        main_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(main_frame, text="⚙ Settings", font=get_font(28, "bold")).pack(anchor="w", pady=(0, 30))

        # General
        section = self._create_section(main_frame, "General Settings")

        frame = ctk.CTkFrame(section, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(frame, text="Download Location", font=get_font(13, "bold")).pack(side="left", padx=(0, 20))

        self.folder_label = ctk.CTkLabel(frame, text=self.settings.get('download_folder', ''), font=get_font(12))
        self.folder_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(frame, text="Browse", command=self._browse_folder, height=30, width=80).pack(side="right", padx=(10, 0))

        # Download
        section = self._create_section(main_frame, "Download Settings")

        settings_items = [
            ("Maximum Simultaneous Downloads", "max_concurrent_downloads", ["1", "2", "3", "4", "5", "6", "8", "10"]),
            ("Default Video Quality", "default_quality", ["Best", "2160p", "1440p", "1080p", "720p", "480p", "360p", "240p", "144p"]),
            ("Default Audio Quality", "default_audio_quality", ["320", "256", "192", "128", "64"]),
            ("Default Output Format", "default_output_format", ["mp4", "mkv", "webm", "avi", "mov"])
        ]

        for label, key, values in settings_items:
            frame = ctk.CTkFrame(section, fg_color="transparent")
            frame.pack(fill="x", padx=20, pady=5)
            ctk.CTkLabel(frame, text=label, font=get_font(13, "bold")).pack(side="left", padx=(0, 20))
            combo = ctk.CTkOptionMenu(frame, values=values, command=lambda x, k=key: self.settings.set(k, x), width=100, height=30)
            combo.pack(side="right")
            current = str(self.settings.get(key, values[0]))
            combo.set(current if current in values else values[0])

        # Appearance
        section = self._create_section(main_frame, "Appearance")

        frame = ctk.CTkFrame(section, fg_color="transparent")
        frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(frame, text="Theme", font=get_font(13, "bold")).pack(side="left", padx=(0, 20))

        theme_switch = ctk.CTkSwitch(frame, text="Dark Mode", command=lambda: self._toggle_theme(theme_switch), font=get_font(12))
        theme_switch.pack(side="right")
        if self.settings.get('theme', 'dark') == 'dark':
            theme_switch.select()
        else:
            theme_switch.deselect()

        # Actions
        section = self._create_section(main_frame, "Actions")

        action_frame = ctk.CTkFrame(section, fg_color="transparent")
        action_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkButton(action_frame, text="📁 Open Download Folder", command=self._open_download_folder, height=35).pack(side="left", padx=5)
        ctk.CTkButton(action_frame, text="🔄 Reset Settings", command=self._reset_settings, height=35).pack(side="left", padx=5)

    def _create_section(self, parent, title):
        section = ctk.CTkFrame(parent, corner_radius=10, fg_color="gray20")
        section.pack(fill="x", pady=10)
        ctk.CTkLabel(section, text=title, font=get_font(18, "bold")).pack(anchor="w", padx=20, pady=(20, 10))
        return section

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select Download Folder")
        if folder:
            self.settings.set('download_folder', folder)
            self.folder_label.configure(text=folder)

    def _toggle_theme(self, switch):
        theme = 'dark' if switch.get() else 'light'
        self.settings.set('theme', theme)
        ctk.set_appearance_mode(theme)

    def _open_download_folder(self):
        folder = self.settings.get('download_folder', '')
        if folder and Path(folder).exists():
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                subprocess.Popen(f'xdg-open "{folder}"', shell=True)

    def _reset_settings(self):
        self.settings.reset()
        self.folder_label.configure(text=self.settings.get('download_folder', ''))

# ============================================================================
# MAIN APPLICATION
# ============================================================================

class YouTubeDownloaderApp(ctk.CTk):
    """Main application class"""

    def __init__(self):
        super().__init__()

        # Configure window. Everything below that is not strictly required to
        # show the window is deferred to `_startup_init()` so the WM can map and
        # paint the shell before any heavy initialization runs.
        self.title("YouTube Downloader Pro")
        self.geometry("1200x800")
        self.minsize(1024, 650)
        self._maximize_window()

        # Bind close event immediately so the window can be closed even while
        # deferred startup is still running.
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Defer all other initialization to the next event-loop iteration so
        # the main window appears as soon as possible.
        self.after(1, self._startup_init)

    def _startup_init(self):
        # Setup logging
        self._setup_logging()

        # Initialize managers
        self.settings = SettingsManager()
        self.db = HistoryManager()
        self.theme_manager = ThemeManager(self.settings)
        self.theme_manager.apply_theme(self)
        # A single shared thumbnail cache reused by every page.
        self.thumbnail_cache = ThumbnailCache()
        self.youtube_service = YouTubeService(self.settings)
        self.download_service = DownloadService(self.settings, self.db)

        # Create main layout
        self._create_layout()

        # Start background tasks
        self.download_service.start_queue()

        # Start the main-thread poller that drains cross-thread GUI callbacks
        self.after(50, self._poll_gui_queue)

        # Defer building the first page until the window is actually visible so
        # startup feels instant.
        self.after(80, lambda: self.show_page("home"))

        # The window is now being mapped: let the native C++ splash know it can
        # hand over (and hide itself) as soon as the WM shows this window.
        self.after_idle(self._signal_native_launcher)
        self._set_window_icon()

    def _signal_native_launcher(self):
        """Tell the C++ splash launcher the real window is up.

        The native launcher sets YDL_SPLASH_READY to a temp path; touching that
        file tells it to destroy the splash and wait silently for the app to
        exit. Harmless no-op when run outside the launcher.
        """
        path = os.environ.get("YDL_SPLASH_READY")
        if path:
            try:
                Path(path).touch(exist_ok=True)
            except OSError as e:
                logging.getLogger(__name__).debug("splash ready signal: %s", e)

    def _set_window_icon(self):
        """Apply the bundled YouTube icon to the window/taskbar."""
        try:
            icon = app_icon_path()
            if not icon:
                return
            if sys.platform == "win32":
                ico = None
                bundled_ico = app_icon_ico_path()
                if bundled_ico:
                    ico = Path(bundled_ico)
                if ico is None or not ico.is_file():
                    ico = self._cook_ico(icon)
                if ico and ico.is_file() and getattr(self, 'iconbitmap', None):
                    self.iconbitmap(str(ico))
                    return
            tk_photo = None
            Image = _pil()
            from PIL import ImageTk
            image = Image.open(icon)
            tk_photo = ImageTk.PhotoImage(image)
            self.iconphoto(True, tk_photo)
            self._icon_img = tk_photo  # keep a reference
        except Exception as e:
            self.logger.warning(f"Could not set window icon: {e}")

    def _cook_ico(self, png_path: str) -> Optional[Path]:
        """Best-effort .ico generation for Windows taskbar icons."""
        try:
            Image = _pil()
            image = Image.open(png_path)
            ico = Path(png_path).with_suffix(".ico")
            image.save(ico, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
            return ico
        except Exception as e:
            self.logger.warning(f"Could not build .ico icon: {e}")
            return None

    def _poll_gui_queue(self):
        drain_gui_queue()
        self.after(60, self._poll_gui_queue)

    def _maximize_window(self):
        try:
            if sys.platform == 'win32':
                self.state('zoomed')
            else:
                self.attributes('-zoomed', True)
        except Exception:
            try:
                self.state('zoomed')
            except Exception:
                pass
        # Positions are clamped a little later (after the WM maps the window)
        # via `after` so we never call update_idletasks()/update() on the main
        # loop while customtkinter scrollbars are reflowing.
        self.after(150, self._clamp_window)

    def _clamp_window(self):
        """Make sure the maximized window stays fully on screen. Uses only
        non-blocking geometry queries so the GUI can never freeze."""
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            w = self.winfo_width()
            h = self.winfo_height()
            if w < 10 or h < 10:
                return
            nw, nh = w, h
            if w > screen_w or h > screen_h:
                nw, nh = min(w, screen_w), min(h, screen_h)
                self.geometry(f"{nw}x{nh}")
            x = self.winfo_rootx()
            y = self.winfo_rooty()
            if x < 0 or y < 0 or x + nw > screen_w or y + nh > screen_h:
                nx = max(0, min(x, screen_w - nw))
                ny = max(0, min(y, screen_h - nh))
                self.geometry(f"{nw}x{nh}+{nx}+{ny}")
        except Exception:
            pass

    def _setup_logging(self):
        log_dir = Path.home() / ".youtube_downloader" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log"

        # Debug logs go to the file by default; console stays quiet so normal
        # operation does not spam stdout. Set YOUTUBE_DOWNLOADER_DEBUG=1 for
        # verbose console output.
        debug = os.environ.get('YOUTUBE_DOWNLOADER_DEBUG') == '1'
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.DEBUG if debug else logging.WARNING)

        logging.basicConfig(
            level=logging.DEBUG if debug else logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[file_handler, console]
        )
        # yt-dlp is chatty; keep its logging out of the console.
        logging.getLogger('yt_dlp').setLevel(logging.WARNING)
        self.logger = logging.getLogger(__name__)

    def _create_layout(self):
        # Main container
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=0, pady=0)

        # Sidebar
        self.sidebar = Sidebar(self.main_container, self.show_page, width=240, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")

        # Content area
        self.content_frame = ctk.CTkFrame(self.main_container, fg_color="transparent", corner_radius=0)
        self.content_frame.pack(side="right", fill="both", expand=True)

        # Pages are created lazily on first navigation (faster startup, less
        # memory and no upfront DB/window work for pages the user never opens).
        self.page_classes = {
            "home": HomePage,
            "playlist": PlaylistPage,
            "downloading": DownloadingPage,
            "history": HistoryPage,
            "account": AccountPage,
            "settings": SettingsPage
        }
        self.pages = {}
        self.current_page = None

    def page(self, name: str):
        """Get (lazily creating) the page widget for the given name."""
        page = self.pages.get(name)
        if page is None:
            page_class = self.page_classes[name]
            page = page_class(self.content_frame, self.settings, self.db, self.download_service,
                              self.youtube_service, thumbnail_cache=self.thumbnail_cache)
            self.pages[name] = page
        return page

    def show_page(self, page_name: str):
        if page_name not in self.page_classes:
            return
        if self.current_page and self.current_page in self.pages:
            self.pages[self.current_page].pack_forget()
        page = self.page(page_name)
        page.pack(fill="both", expand=True)
        self.current_page = page_name
        self.sidebar.set_active(page_name)
        on_show = getattr(page, 'on_show', None)
        if on_show:
            on_show()

    def _on_close(self):
        logger = getattr(self, 'logger', None)
        if logger:
            logger.info("Application closing...")
        for name in ('download_service', 'db'):
            obj = getattr(self, name, None)
            if obj is None:
                continue
            try:
                if name == 'download_service':
                    obj.shutdown()
                else:
                    obj.close()
            except Exception:
                pass
        self.destroy()

    def run(self):
        self.mainloop()

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    app = YouTubeDownloaderApp()
    app.run()
