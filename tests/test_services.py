"""Unit tests for the layered architecture's service/core layers.

These tests do NOT touch the network, the real yt-dlp, or the GUI. yt-dlp is
mocked at the injection point (app.services.imports.yt_dlp) exactly as the
application layers use it.

Run with:  ./venv/bin/python -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.history import HistoryManager  # noqa: E402
from app.core.utils import (  # noqa: E402
    format_duration,
    format_size,
    is_valid_youtube_url,
    sanitize_filename,
)
from app.download.manager import DownloadCancelled, DownloadItem, DownloadManager  # noqa: E402
from app.services import imports  # noqa: E402
from app.services.thumbnails import ThumbnailCache  # noqa: E402
from app.services.youtube import YouTubeService  # noqa: E402


class FakeSettings:
    def __init__(self, **kwargs):
        self.data = dict(kwargs)

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


class FakeDB:
    def add_history_entry(self, data):
        return data.get("id", "id")

    def add_history_entries(self, rows):
        pass


def make_ytdl_module(ydl_cls):
    return type("FakeYTDLP", (), {"YoutubeDL": ydl_cls})


class TestHelpers(unittest.TestCase):
    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("   "), "video")
        self.assertEqual(sanitize_filename("a/b:c*d"), "abcd")
        self.assertLessEqual(len(sanitize_filename("x" * 500)), 200)

    def test_url_validation(self):
        valid = [
            "https://www.youtube.com/watch?v=abc123",
            "https://youtu.be/abc123",
            "youtube.com/watch?v=abc123",
            "https://www.youtube.com/playlist?list=abc123",
        ]
        for url in valid:
            self.assertTrue(is_valid_youtube_url(url), url)
        self.assertFalse(is_valid_youtube_url("https://example.com/video"))

    def test_format_size(self):
        self.assertEqual(format_size(0), "Unknown")
        self.assertEqual(format_size(1024), "1.0 KB")

    def test_format_duration(self):
        self.assertEqual(format_duration(0), "0:00")
        self.assertEqual(format_duration(3661), "1:01:01")


class TestYouTubeCache(unittest.TestCase):
    def _build_service(self):
        return YouTubeService(FakeSettings(cookie_file=None, cookie_browser=None))

    def _info(self, url):
        return {
            "id": "abc123",
            "title": "Test Video",
            "formats": [{"format_id": "18", "vcodec": "avc1", "acodec": "mp4a",
                         "height": 360, "width": 640, "ext": "mp4"}],
            "webpage_url": url,
            "thumbnail": "https://i.ytimg.com/vi/abc123/mqdefault.jpg",
        }

    def test_repeat_extraction_is_cached(self):
        svc = self._build_service()
        extract_calls = {"n": 0}

        class FakeYDL:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def extract_info(self, u, download=False):
                extract_calls["n"] += 1
                return {
                    "id": "abc123",
                    "title": "Test Video",
                    "formats": [{"format_id": "18", "vcodec": "avc1", "acodec": "mp4a",
                                 "height": 360, "width": 640, "ext": "mp4"}],
                    "thumbnail": "https://i.ytimg.com/vi/abc123/mqdefault.jpg",
                }

        with mock.patch.object(imports, "yt_dlp", return_value=make_ytdl_module(FakeYDL)):
            URL = "https://www.youtube.com/watch?v=abc123"
            first = svc.get_video_info(URL)
            second = svc.get_video_info(URL)

        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertEqual(extract_calls["n"], 1)

    def test_playlist_cached_separately(self):
        svc = self._build_service()
        calls = {"n": 0}

        class FakeYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def extract_info(self, u, download=False):
                calls["n"] += 1
                return {"id": "pl", "title": "Playlist", "webpage_url": u,
                        "entries": [{"id": "v1", "title": "Video 1"}]}

        with mock.patch.object(imports, "yt_dlp", return_value=make_ytdl_module(FakeYDL)):
            URL = "https://www.youtube.com/playlist?list=xyz"
            a = svc.get_playlist_info(URL)
            b = svc.get_playlist_info(URL)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(a["entry_count"], 1)
        self.assertEqual(b["entries"][0]["id"], "v1")

    def test_playlist_limit_sets_playlist_items(self):
        svc = self._build_service()
        seen_opts = []

        class FakeYDL:
            def __init__(self, opts):
                seen_opts.append(opts)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def extract_info(self, u, download=False):
                return {"id": "pl", "title": "Playlist", "webpage_url": u,
                        "entries": [{"id": f"v{i}", "title": f"Video {i}"}
                                    for i in range(10)]}

        with mock.patch.object(imports, "yt_dlp", return_value=make_ytdl_module(FakeYDL)):
            URL = "https://www.youtube.com/playlist?list=xyz"
            info = svc.get_playlist_info(URL, max_items=3)
            info2 = svc.get_playlist_info(URL, max_items=6)
        self.assertEqual(seen_opts[0].get("playlist_items"), "1-3")
        self.assertEqual(seen_opts[1].get("playlist_items"), "1-6")
        self.assertEqual(info["entry_count"], 3)
        self.assertEqual(info2["entry_count"], 6)


class TestDownloadManager(unittest.TestCase):
    def setUp(self):
        self.settings = FakeSettings(max_concurrent_downloads=3,
                                     cookie_file=None, cookie_browser=None)
        self.manager = DownloadManager(self.settings, FakeDB())

    def test_add_many_dedupes_existing(self):
        items = [
            {"id": "v1", "title": "One", "webpage_url": "u1"},
            {"id": "v2", "title": "Two", "webpage_url": "u2"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            added = self.manager.add_many_to_queue(items, {}, tmp)
            again = self.manager.add_many_to_queue(items, {}, tmp)
        self.assertEqual(added, 2)
        self.assertEqual(again, 0)

    def test_add_many_skips_existing_files(self):
        items = [{"id": "v9", "title": "Already Here", "webpage_url": "u9"}]
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "Already Here.mp4").write_bytes(b"content")
            added = self.manager.add_many_to_queue(items, {}, tmp)
        self.assertEqual(added, 0)

    def test_progress_emits_throttled_events(self):
        events = []
        self.manager.event.connect(lambda e, p: events.append(e))
        item = DownloadItem(id="x1", url="https://youtu.be/x1", title="T",
                            format_info={}, output_path="/tmp")
        for _ in range(20):
            self.manager._progress_hook({"status": "downloading",
                                         "downloaded_bytes": 1000,
                                         "total_bytes": 5000,
                                         "_speed_str": "1MiB/s", "_eta_str": "5"}, item)
        self.assertLess(len([e for e in events if e == "progress"]), 20)

    def test_cancel_raises_downloadcancelled(self):
        item = DownloadItem(id="x2", url="u", title="T", format_info={}, output_path="/tmp")
        item.cancel_event.set()
        with self.assertRaises(DownloadCancelled):
            self.manager._progress_hook({"status": "downloading"}, item)

    def test_shutdown_cancels_pending_downloads(self):
        self.manager.add_to_queue({"id": "p1", "title": "P", "webpage_url": "up"}, {}, "/tmp")
        self.manager.start()
        self.manager.shutdown()
        self.assertTrue(self.manager._stopped.is_set())
        self.assertTrue(all(i.status == "cancelled" for i in self.manager.download_queue))

    def test_quality_format_selector(self):
        from app.controllers.main_controller import MainController

        ctrl = MainController()
        try:
            fmt = ctrl.quality_format("720p")
            self.assertEqual(fmt["_selector"], "bestvideo*[height<=720]+bestaudio/best")
            audio = ctrl.quality_format("Best Audio")
            self.assertTrue(audio["has_audio"] and not audio["has_video"])
        finally:
            ctrl.shutdown()


class TestHistoryManager(unittest.TestCase):
    def test_roundtrip_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = HistoryManager()
            db.history_path = Path(tmp) / "history.txt"
            db.add_history_entry({"id": "h1", "title": "Video", "url": "u", "format": "720p",
                                  "file_size": 10, "download_path": "/x/v.mp4",
                                  "status": "completed"})
            db.add_history_entry({"id": "h2", "title": "Skipped", "status": "cancelled"})
            entries = db.get_history()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["id"], "h1")
            db.delete_history_entry("h1")
            self.assertEqual(len(db.get_history()), 0)

    def test_only_completed_are_appended(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = HistoryManager()
            db.history_path = Path(tmp) / "history.txt"
            db.add_history_entry({"id": "a", "title": "A", "status": "failed"})
            db.add_history_entry({"id": "b", "title": "B", "status": "completed"})
            ids = [e["id"] for e in db.get_history()]
            self.assertEqual(ids, ["b"])


class TestThumbnailCache(unittest.TestCase):
    def test_disk_cache_returned_without_network(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("PIL not installed")
        with tempfile.TemporaryDirectory() as tmp:
            cache = ThumbnailCache()
            cache.cache_dir = Path(tmp)
            key = __import__("hashlib").md5(b"vid1_320x180").hexdigest()
            img = Image.new("RGB", (320, 180), (10, 20, 30))
            img.save(cache.cache_dir / f"{key}.jpg", "JPEG", quality=85)

            with mock.patch.object(imports, "requests") as req:
                result = cache.get_thumbnail("vid1", "https://example.com/t.jpg")
            self.assertIsNotNone(result)
            req.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)