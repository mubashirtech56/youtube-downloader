"""Main application window: sidebar navigation + stacked pages."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from app.controllers.main_controller import MainController
from app.core.utils import app_icon_path
from app.ui.pages.account import AccountPage
from app.ui.pages.downloads import DownloadsPage
from app.ui.pages.history import HistoryPage
from app.ui.pages.home import HomePage
from app.ui.pages.playlist import PlaylistPage
from app.ui.pages.settings import SettingsPage

NAV_ITEMS = [
    ("🏠 Home", "home"),
    ("📃 Playlist", "playlist"),
    ("⬇ Downloading", "downloading"),
    ("🕒 History", "history"),
    ("👤 Account", "account"),
    ("⚙ Settings", "settings"),
]

_VERSION = "v3.0.0"


class MainWindow(QMainWindow):
    def __init__(self, controller: MainController):
        super().__init__()
        self.controller = controller
        self.logger = logging.getLogger(__name__)
        self.setWindowTitle("YouTube Downloader Pro")
        self.resize(1200, 800)
        self.setMinimumSize(1024, 650)
        self._set_icon()

        self._sidebar_buttons: dict = {}
        self._build_layout()
        self._show_page("home")

    # ----------------------------------------------------------- window

    def _set_icon(self):
        path = app_icon_path()
        if path:
            try:
                self.setWindowIcon(QIcon(path))
            except Exception:  # noqa: BLE001
                pass

    def _build_layout(self):
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 20, 14, 12)
        side_layout.setSpacing(6)

        brand = QLabel("🎬 YouTube\nDownloader")
        bf = brand.font()
        bf.setPointSize(16)
        bf.setBold(True)
        brand.setFont(bf)
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side_layout.addWidget(brand)
        side_layout.addSpacing(10)

        for text, page_name in NAV_ITEMS:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setObjectName("SidebarButton")
            btn.clicked.connect(lambda _=False, p=page_name: self._show_page(p))
            side_layout.addWidget(btn)
            self._sidebar_buttons[page_name] = btn

        side_layout.addStretch(1)
        version = QLabel(_VERSION)
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet("color: #8899aa;")
        side_layout.addWidget(version)

        # Page stack
        self.stack = QStackedWidget()
        self.pages = {}
        for _text, page_id in NAV_ITEMS:
            widget = self._make_page(page_id)
            self.pages[page_id] = widget
            self.stack.addWidget(widget)

        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

    def _make_page(self, page_id: str) -> QWidget:
        if page_id == "home":
            return HomePage(self.controller)
        if page_id == "playlist":
            return PlaylistPage(self.controller)
        if page_id == "downloading":
            return DownloadsPage(self.controller)
        if page_id == "history":
            return HistoryPage(self.controller)
        if page_id == "account":
            return AccountPage(self.controller)
        if page_id == "settings":
            return SettingsPage(self.controller)
        return QWidget()

    def _show_page(self, page_id: str):
        if page_id not in self.pages:
            return
        for pid, btn in self._sidebar_buttons.items():
            active = pid == page_id
            btn.setChecked(active)
            btn.setObjectName("SidebarButtonActive" if active else "SidebarButton")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.stack.setCurrentWidget(self.pages[page_id])
        on_show = getattr(self.pages[page_id], "on_show", None)
        if on_show:
            on_show()

    def closeEvent(self, event):
        try:
            self.controller.shutdown()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)