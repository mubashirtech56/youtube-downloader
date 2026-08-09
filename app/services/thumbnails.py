"""On-disk thumbnail cache (PIL images keyed by md5 hash)."""

import hashlib
import io
import logging
import time
from typing import Any, Dict, Optional

from app.core.utils import data_dir
from app.services import imports


class ThumbnailCache:
    """Download, size, cache (disk + memory) video thumbnails."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.cache_dir = data_dir() / "thumbnails"
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

    def get_thumbnail(self, video_id: str, url: str, size: tuple = (320, 180)) -> Optional[Any]:
        """Return a PIL image (or None) for the given video/URL."""
        try:
            Image = imports.pil_image()
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
                response = imports.requests().get(url, timeout=10)
                if response.status_code == 200:
                    image = Image.open(io.BytesIO(response.content))
                    image.thumbnail(size, Image.Resampling.LANCZOS)
                    image.save(cache_path, "JPEG", quality=85)
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