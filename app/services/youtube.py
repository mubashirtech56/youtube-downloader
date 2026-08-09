"""YouTube metadata extraction, wrapped around yt-dlp.

This is the service layer: it knows nothing about Qt or the UI. It runs
synchronously and callers are responsible for running it off the GUI thread.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.utils import is_valid_youtube_url
from app.services import imports
from app.core.settings import SettingsManager


class YouTubeService:
    """Fetch metadata for YouTube videos and playlists."""

    _CACHE_TTL = 300.0
    _CACHE_MAX = 64

    def __init__(self, settings: SettingsManager):
        self.logger = logging.getLogger(__name__)
        self.settings = settings
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "ignoreerrors": True,
            "no_color": True,
            "geo_bypass": True,
            "geo_bypass_country": "US",
            "format": "best",
            "cookiefile": self.settings.get("cookie_file") if self.settings else None,
            "js_runtimes": {"node": {}},
            "extractor_args": {"youtube": {"player_client": ["default", "android_vr", "tv"]}},
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
            cookie_file = self.settings.get("cookie_file")
            cookie_browser = self.settings.get("cookie_browser")
            opts.pop("cookiefile", None)
            opts.pop("cookiesfrombrowser", None)
            if cookie_file:
                opts["cookiefile"] = cookie_file
            elif cookie_browser:
                opts["cookiesfrombrowser"] = (cookie_browser, None, None, None)
        return opts

    def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            if not is_valid_youtube_url(url):
                raise ValueError("Invalid YouTube URL")

            cache_key = f"video:{url}"
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

            with imports.yt_dlp().YoutubeDL(self._get_opts()) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return None

                video_formats, audio_formats = self._process_formats(info)

                result = {
                    "id": info.get("id", ""),
                    "title": info.get("title", ""),
                    "description": info.get("description", ""),
                    "duration": info.get("duration", 0),
                    "thumbnail": info.get("thumbnail", ""),
                    "upload_date": info.get("upload_date", ""),
                    "uploader": info.get("uploader", ""),
                    "channel": info.get("channel", ""),
                    "channel_id": info.get("channel_id", ""),
                    "view_count": info.get("view_count", 0),
                    "like_count": info.get("like_count", 0),
                    "comment_count": info.get("comment_count", 0),
                    "tags": info.get("tags", []),
                    "categories": info.get("categories", []),
                    "age_limit": info.get("age_limit", 0),
                    "is_live": info.get("is_live", False),
                    "webpage_url": info.get("webpage_url", url),
                    "video_formats": video_formats,
                    "audio_formats": audio_formats,
                    "best_video": video_formats[0] if video_formats else None,
                    "best_audio": audio_formats[0] if audio_formats else None,
                    "height": video_formats[0].get("height", 0) if video_formats else 0,
                }
                self._cache_put(cache_key, result)
                return result
        except Exception as e:
            self.logger.error(f"Error fetching video info: {e}")
            return None

    def _process_formats(self, info: Dict[str, Any]) -> Tuple[List[Dict], List[Dict]]:
        video_formats: List[Dict[str, Any]] = []
        audio_formats: List[Dict[str, Any]] = []
        formats = info.get("formats", [])

        for fmt in formats:
            vcodec = fmt.get("vcodec")
            acodec = fmt.get("acodec")
            if vcodec != "none" and acodec != "none":
                video_formats.append(self._video_fmt(fmt, has_audio=True))
            elif vcodec != "none":
                video_formats.append(self._video_fmt(fmt, has_audio=False))
            elif acodec != "none":
                audio_formats.append({
                    "format_id": fmt.get("format_id", ""),
                    "codec": acodec,
                    "container": fmt.get("ext", "mp3"),
                    "filesize": fmt.get("filesize", 0),
                    "abr": fmt.get("abr", 0),
                    "bitrate": fmt.get("abr", 0),
                    "has_video": False,
                    "has_audio": True,
                })

        video_formats = self._dedupe_video_formats(video_formats)
        audio_formats = self._dedupe_audio_formats(audio_formats)
        return video_formats, audio_formats

    def _video_fmt(self, fmt: Dict[str, Any], has_audio: bool) -> Dict[str, Any]:
        return {
            "format_id": fmt.get("format_id", ""),
            "resolution": fmt.get("resolution", ""),
            "height": fmt.get("height", 0),
            "width": fmt.get("width", 0),
            "fps": fmt.get("fps", 0),
            "codec": fmt.get("vcodec", ""),
            "acodec": fmt.get("acodec", ""),
            "container": fmt.get("ext", "mp4"),
            "filesize": fmt.get("filesize", 0),
            "abr": fmt.get("abr", 0),
            "quality": fmt.get("height", 0),
            "has_video": True,
            "has_audio": has_audio,
        }

    def _dedupe_video_formats(self, formats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        best_by_height: Dict[int, Dict[str, Any]] = {}
        for fmt in formats:
            height = fmt.get("height", 0)
            if not height:
                continue
            current = best_by_height.get(height)
            if current is None or fmt.get("quality", 0) > current.get("quality", 0):
                best_by_height[height] = fmt
        return [best_by_height[h] for h in sorted(best_by_height, reverse=True)]

    def _dedupe_audio_formats(self, formats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        best_by_bitrate: Dict[int, Dict[str, Any]] = {}
        for fmt in formats:
            bitrate = int(round(fmt.get("abr", 0) / 16.0) * 16)
            current = best_by_bitrate.get(bitrate)
            if current is None or fmt.get("abr", 0) > current.get("abr", 0):
                best_by_bitrate[bitrate] = fmt
        return [best_by_bitrate[b] for b in sorted(best_by_bitrate, reverse=True)]

    def get_playlist_info(self, url: str, max_items: int = 0) -> Optional[Dict[str, Any]]:
        try:
            if not is_valid_youtube_url(url):
                raise ValueError("Invalid YouTube URL")

            cache_key = f"playlist:{url}:{max_items}"
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

            opts = self._get_opts()
            opts["extract_flat"] = "in_playlist"
            if max_items > 0:
                opts["playlist_items"] = f"1-{max_items}"

            with imports.yt_dlp().YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    return None

                entries = []
                for entry in info.get("entries", []):
                    if entry:
                        video_id = entry.get("id", "")
                        thumbnail = entry.get("thumbnail", "")
                        if not thumbnail and video_id:
                            thumbnail = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
                        webpage_url = entry.get("webpage_url") or entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"
                        entries.append({
                            "id": video_id,
                            "title": entry.get("title", ""),
                            "duration": entry.get("duration", 0),
                            "thumbnail": thumbnail,
                            "webpage_url": webpage_url,
                        })

                if max_items > 0 and len(entries) > max_items:
                    entries = entries[:max_items]

                result = {
                    "title": info.get("title", ""),
                    "description": info.get("description", ""),
                    "uploader": info.get("uploader", ""),
                    "view_count": info.get("view_count", 0),
                    "entries": entries,
                    "entry_count": len(entries),
                    "max_items": max_items,
                    "thumbnail": info.get("thumbnail", ""),
                    "webpage_url": info.get("webpage_url", url),
                }
                self._cache_put(cache_key, result)
                return result
        except Exception as e:
            self.logger.error(f"Error fetching playlist info: {e}")
            return None