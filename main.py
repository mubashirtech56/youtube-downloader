#!/usr/bin/env python3
"""YouTube Downloader Pro — main entry point.

NEW (layered) architecture:

    PySide6            -> Qt UI layer (app.ui.*)
    MainController     -> Controller / ViewModel (app.controllers)
    DownloadManager    -> Download Manager (app.download)
    yt-dlp / FFmpeg    -> underlying download engine (app.services / app.download)

The old monolith (CustomTkinter + mixed threading) is split into the `app/`
package; the native C++ splash launcher still hands over to this process.
"""

import os
import sys
from pathlib import Path

# Only force the offscreen platform on headless Linux/macOS (CI/tests).
# On Windows we must use the native "windows" platform or the GUI never shows.
if os.environ.get("QT_QPA_PLATFORM") is None and sys.platform != "win32":
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from app.controllers.main_controller import MainController
    from app.ui.main_window import MainWindow
    from app.ui.theme import ThemeManager

    app = QApplication(sys.argv)
    app.setApplicationName("YouTube Downloader Pro")
    app.setOrganizationName("youtube-downloader")

    # Setup logging to ~/.youtube_downloader/logs
    from app.core.utils import setup_logging
    setup_logging()

    controller = MainController()
    # The window is mapped before the heavy init in MainController finishes on
    # the first event-loop turn, so startup stays instant behind the C++ splash.
    controller.start()

    # Apply the saved theme before any window paints.
    theme = ThemeManager(controller.settings)
    theme.apply(app)

    win = MainWindow(controller)

    # Signal the native C++ splash launcher that the real window is up.
    ready = os.environ.get("YDL_SPLASH_READY")
    if ready:
        QTimer.singleShot(0, lambda: _touch_splash_ready(ready))

    win.show()

    # Maximize after layout settles (matches legacy behaviour).
    QTimer.singleShot(60, lambda: win.showMaximized())

    exit_code = app.exec()
    controller.shutdown()
    sys.exit(exit_code)


def _touch_splash_ready(path: str):
    """Touch the temp path the C++ splash watches so it hands over to the GUI."""
    try:
        Path(path).touch(exist_ok=True)
    except OSError:
        pass


if __name__ == "__main__":
    main()