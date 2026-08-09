"""Core utilities shared across all layers."""

import re
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_FILENAME_RE = re.compile(r'[<>:"/\\|?*]')
_URL_PATTERNS = [
    re.compile(r"(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v="),
    re.compile(r"(?:https?:\/\/)?(?:www\.)?youtu\.be\/"),
    re.compile(r"(?:https?:\/\/)?(?:www\.)?youtube\.com\/shorts\/"),
    re.compile(r"(?:https?:\/\/)?(?:www\.)?youtube\.com\/playlist\?list="),
]

logger = None  # set by setup_logging()


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def sanitize_filename(filename: str) -> str:
    sanitized = _FILENAME_RE.sub("", filename)
    sanitized = sanitized.strip(". ")
    if len(sanitized) > 200:
        sanitized = sanitized[:200]
    return sanitized or "video"


def format_size(size: int) -> str:
    if not size:
        return "Unknown"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.1f} {units[i]}"


def format_duration(seconds: int) -> str:
    if not seconds:
        return "0:00"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_timestamp(timestamp: Optional[str]) -> str:
    if not timestamp:
        return "—"
    try:
        dt = datetime.fromisoformat(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return timestamp


def is_valid_youtube_url(url: str) -> bool:
    for pattern in _URL_PATTERNS:
        if pattern.match(url):
            return True
    return False


# ----------------------------------------------------------------------------
# Packaged asset discovery (dev tree and PyInstaller bundles)
# ----------------------------------------------------------------------------

def app_icon_path() -> Optional[str]:
    """Locate the bundled YouTube icon (PNG) both in dev and frozen builds."""
    candidates = []
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates.append(base / "youtube-dl.png")
        candidates.append(Path(sys.executable).parent / "youtube-dl.png")
        candidates.append(base / "youtube-downloader.png")
        candidates.append(base / "icons" / "youtube-downloader-256.png")
    candidates.append(Path(__file__).resolve().parent.parent.parent / "youtube-dl.png")
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def data_dir() -> Path:
    return Path.home() / ".youtube_downloader"


def setup_logging() -> None:
    import logging

    global logger
    log_dir = data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"app_{datetime.now().strftime('%Y%m%d')}.log"

    debug = __import__("os").environ.get("YOUTUBE_DOWNLOADER_DEBUG") == "1"
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if debug else logging.WARNING)

    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[file_handler, console],
    )
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)
    logger = logging.getLogger("youtube_downloader")


def open_folder(path: str) -> None:
    """Open a folder in the OS file manager (fire-and-forget)."""
    import os
    import subprocess

    try:
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(f'xdg-open "{path}"', shell=True)
    except Exception:
        pass