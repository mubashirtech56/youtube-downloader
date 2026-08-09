"""Lazy lazy-imported heavy third-party dependencies.

`yt_dlp`, `requests` and `PIL` are expensive to import. They are deferred until
first use and cached here so tests can patch the getters (or their backing
modules) cleanly without loading them at import time.
"""

def _resolve(name):
    import sys

    module = sys.modules.get(name)
    if module is None:
        module = __import__(name)
    return module


def yt_dlp():
    """Return the lazily-imported `yt_dlp` module."""
    return _resolve("yt_dlp")


def requests():
    """Return the lazily-imported `requests` module."""
    return _resolve("requests")


def pil_image():
    """Return the `PIL.Image` module."""
    return _resolve("PIL.Image")