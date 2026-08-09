"""Shared fetch/download error helpers.

YouTube blocks requests in several well-known ways (bot-checks, DRM, rate
limits, broken cookie configs). These helpers centralise the detection and the
user-facing wording so the service layer, download manager and UI all agree on
what went wrong.
"""

# Substrings that tell us the failure was caused by cookie handling. yt-dlp
# words these differently across versions/platforms (e.g. "failed to load
# cookies", "Could not copy ... cookie database", "cookies were not requested").
_COOKIE_ERROR_MARKERS = (
    "cookie",
    "cookiefile",
    "cookiesfrombrowser",
    "keyring",
    "could not decrypt",
)


class FetchError(Exception):
    """A user-facing fetch/download failure with a friendly message."""


def is_cookie_error(exc: BaseException) -> bool:
    """True when the exception is caused by reading/loading cookies."""
    message = str(exc).lower()
    return any(marker in message for marker in _COOKIE_ERROR_MARKERS)


def friendly_fetch_error(exc: BaseException) -> str:
    """Turn a raw exception into a short, actionable user message."""
    message = str(exc)
    lowered = message.lower()

    if "not a bot" in lowered or "sign in to confirm" in lowered:
        return ("YouTube blocked this request (\"Sign in to confirm you're not a bot\"). "
                "Go to Account -> import cookies from your browser or a cookies.txt file and try again.")
    if "drm" in lowered:
        return ("YouTube reports this as DRM-protected with no downloadable streams. "
                "Some videos cannot be saved by any app. If it should be playable, "
                "re-export fresh cookies from a signed-in browser (Account page) and retry.")
    if "too many requests" in lowered or "http error 429" in lowered:
        return "YouTube rate-limited the request (HTTP 429). Wait a few minutes and try again."
    if "requested format is not available" in lowered:
        return ("YouTube returned no usable streams (\"Requested format is not available\"). "
                "This usually means the saved cookies are stale or the video is restricted. "
                "The app retries without cookies automatically.")
    if is_cookie_error(exc):
        return ("Could not read the configured cookies. The app retried without them; "
                "if the video still needs cookies, re-import them on the Account page.")
    if "invalid youtube url" in lowered:
        return "Invalid YouTube URL. Please paste a valid video or playlist link."
    if "unavailable" in lowered or "removed" in lowered or "video is private" in lowered:
        return "This video is unavailable, private or has been removed."
    # Fall back to the raw text, stripped of yt-dlp's prefix noise.
    text = message.strip()
    for prefix in ("ERROR: ", "[youtube] "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text[:300] or "Failed to fetch the video. Please check the URL and try again."


def is_expected_failure(exc: BaseException) -> bool:
    """Whether an exception is an "expected" yt-dlp failure (a DownloadError)."""
    return type(exc).__name__ == "DownloadError"
