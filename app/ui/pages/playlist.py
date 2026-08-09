"""Playlist page — fetch a playlist, select entries and add to the queue."""

import logging
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.controllers.main_controller import MainController
from app.core.utils import format_duration


class PlaylistPage(QWidget):
    _BATCH_SIZE = 40

    def __init__(self, controller: MainController, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.controller = controller
        self.logger = logging.getLogger(__name__)
        self.current_playlist: Optional[Dict[str, Any]] = None
        self._entries: List[Dict[str, Any]] = []
        self._entry_checkboxes: List[tuple] = []  # (id, entry, QCheckBox)
        self._batch_index = 0
        self._render_job = 0

        controller.playlistFetched.connect(self._on_playlist_fetched)
        controller.playlistFailed.connect(self._on_playlist_failed)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        search = QHBoxLayout()
        self.url_entry = QLineEdit()
        self.url_entry.setPlaceholderText("Enter YouTube Playlist URL...")
        self.url_entry.setMinimumHeight(40)
        self.url_entry.returnPressed.connect(self.fetch_playlist)
        self.fetch_btn = QPushButton("🔍 Fetch Playlist")
        self.fetch_btn.setObjectName("PrimaryButton")
        self.fetch_btn.setMinimumHeight(40)
        self.fetch_btn.clicked.connect(self.fetch_playlist)
        search.addWidget(self.url_entry, 1)
        search.addWidget(self.fetch_btn)
        root.addLayout(search)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.select_all_check = QCheckBox("Select All")
        self.select_all_check.toggled.connect(self._toggle_select_all)
        toolbar.addWidget(self.select_all_check)

        toolbar.addWidget(QLabel("Max videos:"))
        self.max_entry = QLineEdit()
        self.max_entry.setPlaceholderText("all")
        self.max_entry.setFixedWidth(64)
        self.max_entry.returnPressed.connect(self.fetch_playlist)
        toolbar.addWidget(self.max_entry)

        toolbar.addWidget(QLabel("Default:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["Best Quality", "Best Audio", "1080p", "720p", "480p", "360p"])
        toolbar.addWidget(self.format_combo)

        download_btn = QPushButton("⬇ Download Selected")
        download_btn.setObjectName("SuccessButton")
        download_btn.clicked.connect(self._download_selected)
        toolbar.addWidget(download_btn)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        self.info_label = QLabel("Enter a playlist URL to get started")
        f = self.info_label.font()
        f.setPointSize(14)
        f.setBold(True)
        self.info_label.setFont(f)
        root.addWidget(self.info_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.list_container = QWidget()
        self.entries_layout = QVBoxLayout(self.list_container)
        self.entries_layout.setSpacing(4)
        self.entries_layout.setContentsMargins(0, 0, 8, 0)
        self.scroll.setWidget(self.list_container)
        root.addWidget(self.scroll, 1)

    # ------------------------------------------------------------- actions

    def fetch_playlist(self):
        url = self.url_entry.text().strip()
        if not url:
            return
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("⏳ Loading...")
        self.controller.fetch_playlist(url, self._get_max_items())

    def _get_max_items(self) -> int:
        raw = self.max_entry.text().strip()
        if not raw:
            return 0
        try:
            return max(0, int(raw))
        except ValueError:
            return 0

    def _download_selected(self):
        entries = [data["entry"] for data in self._entry_checkbox_data if data["cb"].isChecked()]
        if not entries:
            return
        self.controller.queue_playlist(entries, self.controller.quality_format(self.format_combo.currentText()))

    # ------------------------------------------------------- controller

    def _on_playlist_fetched(self, payload: dict):
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("🔍 Fetch Playlist")
        info = payload.get("result")
        if not info:
            self._on_playlist_failed(payload)
            return
        self.current_playlist = info
        self._render_playlist(info)

    def _on_playlist_failed(self, payload: dict):
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("🔍 Fetch Playlist")
        self.info_label.setText("Failed to fetch playlist (invalid URL or unavailable)")

    def _render_playlist(self, playlist: Dict[str, Any]):
        count = playlist.get("entry_count", 0)
        max_items = playlist.get("max_items", 0)
        if max_items > 0:
            self.info_label.setText(f"📋 {playlist.get('title', 'Unknown')} — showing {count} / {max_items} videos")
        else:
            self.info_label.setText(f"📋 {playlist.get('title', 'Unknown')} — {count} videos")

        self._entries = playlist.get("entries", [])
        self._entry_checkbox_data = []
        self.select_all_check.blockSignals(True)
        self.select_all_check.setChecked(False)
        self.select_all_check.blockSignals(False)

        for i in reversed(range(self.entries_layout.count())):
            widget = self.entries_layout.takeAt(i).widget()
            if widget is not None:
                widget.deleteLater()

        self._batch_index = 0
        self._render_job += 1
        self._render_batch()

    def _render_batch(self):
        if not self._entries:
            return
        start = self._batch_index
        end = min(start + self._BATCH_SIZE, len(self._entries))
        for idx in range(start, end):
            self._render_entry(self._entries[idx], idx + 1)
        self._batch_index = end
        if self._batch_index < len(self._entries):
            job = self._render_job
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, lambda: self._render_batch() if job == self._render_job else None)

    def _render_entry(self, entry: Dict[str, Any], idx: int):
        frame = QFrame()
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)

        cb = QCheckBox()
        row.addWidget(cb)

        num = QLabel(f"{idx}.")
        num.setStyleSheet("color: rgba(128,128,128,0.8);")
        num.setFixedWidth(36)
        row.addWidget(num)

        title = QLabel(entry.get("title", "Unknown"))
        title.setWordWrap(False)
        title.setToolTip(entry.get("title", ""))
        row.addWidget(title, 1)

        duration = QLabel(format_duration(entry.get("duration", 0)))
        duration.setStyleSheet("color: rgba(128,128,128,0.8);")
        row.addWidget(duration)

        self.entries_layout.addWidget(frame)
        self._entry_checkbox_data.append({"id": entry.get("id", idx), "entry": entry, "cb": cb})

    def _toggle_select_all(self, checked: bool):
        for data in self._entry_checkbox_data:
            data["cb"].blockSignals(True)
            data["cb"].setChecked(checked)
            data["cb"].blockSignals(False)