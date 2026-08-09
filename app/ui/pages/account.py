"""Account page — cookie import for browser-restricted / private videos."""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)

from app.controllers.main_controller import MainController

_BROWSERS = ["None", "chrome", "firefox", "chromium", "brave", "edge", "opera", "vivaldi"]


class AccountPage(QWidget):
    def __init__(self, controller: MainController, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.controller = controller
        self.logger = logging.getLogger(__name__)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(16)

        heading = QLabel("👤 Account Settings")
        f = heading.font()
        f.setPointSize(22)
        f.setBold(True)
        heading.setFont(f)
        root.addWidget(heading)

        # Cookie import -----------------------------------------------------
        cookie_frame = QFrame()
        cookie_frame.setStyleSheet(
            "QFrame { background: rgba(128,128,128,0.08); border-radius: 10px; }")
        cl = QVBoxLayout(cookie_frame)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(8)

        head = QLabel("🍪 Cookie Import")
        hf = head.font()
        hf.setPointSize(14)
        hf.setBold(True)
        head.setFont(hf)
        cl.addWidget(head)
        cl.addWidget(QLabel("Import cookies from your browser to access restricted content"))

        current_file = self.controller.settings.get("cookie_file", "") or ""
        self.cookie_label = QLabel(current_file or "No cookie file loaded")
        self.cookie_label.setWordWrap(True)
        cl.addWidget(self.cookie_label)

        btn_row = QHBoxLayout()
        import_btn = QPushButton("📂 Import Cookies")
        import_btn.clicked.connect(self._import_cookies)
        remove_btn = QPushButton("🗑 Remove Cookies")
        remove_btn.clicked.connect(self._remove_cookies)
        btn_row.addWidget(import_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)
        cl.addLayout(btn_row)

        hint = QLabel("Supported format: Netscape cookies.txt")
        hint.setStyleSheet("color: rgba(128,128,128,0.8);")
        cl.addWidget(hint)
        root.addWidget(cookie_frame)

        # Browser cookies ---------------------------------------------------
        browser_frame = QFrame()
        browser_frame.setStyleSheet(
            "QFrame { background: rgba(128,128,128,0.08); border-radius: 10px; }")
        bl = QVBoxLayout(browser_frame)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(8)

        brow_head = QLabel("🌐 Browser Cookies")
        brow_head.setFont(hf)
        brow_head.setStyleSheet("font-weight: 600;")
        bl.addWidget(brow_head)
        bl.addWidget(QLabel("Use cookies directly from an installed browser (recommended, never expires)"))

        brow = QHBoxLayout()
        brow.addWidget(QLabel("Browser:"))
        self.browser_combo = QComboBox()
        self.browser_combo.addItems(_BROWSERS)
        current_browser = self.controller.settings.get("cookie_browser", "")
        idx = _BROWSERS.index(current_browser) if current_browser in _BROWSERS else 0
        self.browser_combo.setCurrentIndex(idx)
        self.browser_combo.currentTextChanged.connect(self._set_browser)
        brow.addWidget(self.browser_combo)
        brow.addStretch(1)
        bl.addLayout(brow)
        root.addWidget(browser_frame)

        root.addStretch(1)

    # ---------------------------------------------------------- actions

    def _set_browser(self, browser: str):
        value = None if browser == "None" else browser
        self.controller.settings.set("cookie_browser", value)
        self.logger.info(f"Browser cookies set to: {browser}")

    def _import_cookies(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Cookies File", str(Path.home()),
            "Netscape Cookies (*.txt);;All Files (*.*)")
        if path:
            self.controller.settings.set("cookie_file", path)
            self.controller.settings.set("cookie_browser", None)
            self.browser_combo.setCurrentIndex(0)
            self.cookie_label.setText(path)
            self.logger.info("Cookies imported successfully")

    def _remove_cookies(self):
        self.controller.settings.set("cookie_file", "")
        self.cookie_label.setText("No cookie file loaded")