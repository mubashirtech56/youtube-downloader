"""Home page — search, preview and download a single video."""

import logging
from typing import Any, Dict, Optional

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QRadioButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from app.controllers.main_controller import MainController
from app.core.utils import format_duration, format_size, sanitize_filename
from app.ui.common import make_thumbnail_label, pil_to_qpixmap


class HomePage(QWidget):
    def __init__(self, controller: MainController, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.controller = controller
        self.logger = logging.getLogger(__name__)
        self.current_video: Optional[Dict[str, Any]] = None
        self.selected_format: Optional[Dict[str, Any]] = None
        self._rendered_video_id: Optional[str] = None

        controller.videoFetched.connect(self._on_video_fetched)
        controller.videoFailed.connect(self._on_video_failed)
        controller.thumbnailReady.connect(self._on_thumbnail)
        self._build()

    # ------------------------------------------------------------- UI build

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        # Search bar
        search = QHBoxLayout()
        self.url_entry = QLineEdit()
        self.url_entry.setPlaceholderText("Enter YouTube URL...")
        self.url_entry.setMinimumHeight(40)
        self.url_entry.returnPressed.connect(self.fetch_video)
        self.fetch_btn = QPushButton("🔍 Fetch")
        self.fetch_btn.setObjectName("PrimaryButton")
        self.fetch_btn.setMinimumHeight(40)
        self.fetch_btn.clicked.connect(self.fetch_video)
        search.addWidget(self.url_entry, 1)
        search.addWidget(self.fetch_btn)
        root.addLayout(search)

        # Content split: left info / right details
        content = QHBoxLayout()
        content.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(10)
        self.thumbnail_label = make_thumbnail_label((360, 200))
        left.addWidget(self.thumbnail_label)

        info_frame = QFrame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(4, 4, 4, 4)
        info_layout.setSpacing(4)
        self.info_values: Dict[str, QLabel] = {}
        rows = [("channel", "Channel"), ("duration", "Duration"), ("date", "Upload Date"),
                ("views", "Views"), ("likes", "Likes"), ("resolution", "Resolution")]
        for key, label in rows:
            row = QHBoxLayout()
            row.setSpacing(8)
            caption = QLabel(f"{label}:")
            caption.setStyleSheet("font-weight: 600;")
            value = QLabel("—")
            value.setWordWrap(True)
            row.addWidget(caption, 0)
            row.addWidget(value, 1)
            info_layout.addLayout(row)
            self.info_values[key] = value
        left.addWidget(info_frame)
        left.addStretch(1)

        right = QVBoxLayout()
        right.setSpacing(8)
        self.title_label = QLabel("Enter a URL to get started")
        self.title_label.setWordWrap(True)
        f = self.title_label.font()
        f.setPointSize(16)
        f.setBold(True)
        self.title_label.setFont(f)
        right.addWidget(self.title_label)

        self.desc_label = QLabel("")
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("color: rgba(128,128,128,0.9);")
        right.addWidget(self.desc_label, 0)

        # download buttons
        self.size_label = QLabel("Estimated Size: —")
        self.filename_label = QLabel("Filename: —")
        right.addWidget(self.size_label)
        right.addWidget(self.filename_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        add_btn = QPushButton("📋 Add to Batch")
        add_btn.clicked.connect(self.add_to_batch)
        start_btn = QPushButton("⬇ Start Download")
        start_btn.setObjectName("SuccessButton")
        start_btn.clicked.connect(self.start_download)
        folder_btn = QPushButton("📁 Open Folder")
        folder_btn.clicked.connect(self._open_folder)
        copy_btn = QPushButton("📋 Copy URL")
        copy_btn.clicked.connect(self._copy_url)
        for b in (add_btn, start_btn, folder_btn, copy_btn):
            buttons.addWidget(b)
        right.addLayout(buttons)

        # format selector tabs (built lazily)
        self.tabs = QTabWidget()
        self.tabs.setVisible(False)
        self._build_format_tabs()
        right.addWidget(self.tabs, 1)

        content.addLayout(left, 2)
        content.addLayout(right, 3)
        root.addLayout(content, 1)

    def _build_format_tabs(self):
        self.video_scroll = QScrollArea()
        self.video_scroll.setWidgetResizable(True)
        self.audio_scroll = QScrollArea()
        self.audio_scroll.setWidgetResizable(True)
        self.video_container = QWidget()
        self.video_layout = QVBoxLayout(self.video_container)
        self.video_layout.setSpacing(6)
        self.audio_container = QWidget()
        self.audio_layout = QVBoxLayout(self.audio_container)
        self.audio_layout.setSpacing(6)
        self.video_scroll.setWidget(self.video_container)
        self.audio_scroll.setWidget(self.audio_container)
        self.tabs.addTab(self.video_scroll, "🎬 Video")
        self.tabs.addTab(self.audio_scroll, "🎵 Audio")
        self.video_group = QButtonGroup(self)
        self.audio_group = QButtonGroup(self)

    # ------------------------------------------------------------- actions

    def fetch_video(self):
        url = self.url_entry.text().strip()
        if not url:
            return
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("⏳ Loading...")
        self.controller.fetch_video(url)

    def add_to_batch(self):
        if not (self.selected_format and self.current_video):
            return
        self.controller.queue_direct(self.current_video, self.selected_format)

    def start_download(self):
        if not (self.selected_format and self.current_video):
            return
        self.controller.queue_direct(self.current_video, self.selected_format)

    def _open_folder(self):
        self.controller.open_download_folder()

    def _copy_url(self):
        url = self.url_entry.text().strip()
        if url:
            clip = QGuiApplication.clipboard()
            if clip:
                clip.setText(url)

    # ---------------------------------------------------------- controller

    def _on_video_fetched(self, payload: dict):
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("🔍 Fetch")
        info = payload.get("result")
        if not info:
            self._show_error("Failed to fetch video (invalid URL or unavailable)")
            return
        self.current_video = info
        self._render_video_info(info)
        self.controller.fetch_thumbnail_async(info.get("id", ""), info.get("thumbnail", ""))

    def _on_video_failed(self, payload: dict):
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("🔍 Fetch")
        self._show_error(payload.get("error", "Failed to fetch video"))

    def _show_error(self, message: str):
        self.title_label.setText("Failed to fetch video")
        self.desc_label.setText(message)

    def _render_video_info(self, info: Dict[str, Any]):
        self.title_label.setText(info.get("title", "Unknown Title"))
        desc = info.get("description", "No description available")
        self.desc_label.setText(desc[:500] + ("..." if len(desc) > 500 else ""))

        values = {
            "channel": info.get("channel", "—"),
            "duration": format_duration(info.get("duration", 0)),
            "date": info.get("upload_date", "—"),
            "views": f"{info.get('view_count', 0):,}",
            "likes": f"{info.get('like_count', 0):,}" if info.get("like_count") else "—",
            "resolution": f"{info.get('height', 0)}p",
        }
        for key, label in self.info_values.items():
            label.setText(values.get(key, "—"))

        self._render_formats(info)

    def _render_formats(self, info: Dict[str, Any]):
        video_id = info.get("id", "")
        if self._rendered_video_id == video_id and self.tabs.isVisible():
            return
        self._rendered_video_id = video_id

        self._clear(self.video_layout, self.video_group)
        self._clear(self.audio_layout, self.audio_group)

        for fmt in info.get("video_formats", []):
            self._create_format_row(self.video_layout, self.video_group, fmt, "video")
        for fmt in info.get("audio_formats", []):
            self._create_format_row(self.audio_layout, self.audio_group, fmt, "audio")

        self.tabs.setVisible(True)
        if info.get("video_formats"):
            self._select_format(info["video_formats"][0])

    def _clear(self, layout, group: Optional[QButtonGroup]):
        for i in reversed(range(layout.count())):
            item = layout.takeAt(i)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if group is not None:
            for rb in group.buttons():
                group.removeButton(rb)

    def _create_format_row(self, layout, group: QButtonGroup, fmt: Dict[str, Any], kind: str):
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(8, 4, 8, 4)
        radio = QRadioButton()
        hl.addWidget(radio)

        details = []
        if kind == "video":
            details.append(fmt.get("resolution", "Unknown"))
            details.append(f"{fmt.get('fps', '?')} FPS")
            details.append(str(fmt.get("codec", "Unknown")))
            details.append(fmt.get("container", "mp4"))
        else:
            details.append(f"{fmt.get('bitrate', '?')} kbps")
            details.append(str(fmt.get("codec", "Unknown")))
            details.append(fmt.get("container", "mp3"))
            details.append(format_size(fmt.get("filesize", 0)))
        label = QLabel(" • ".join(details))
        hl.addWidget(label, 1)
        layout.addWidget(row)
        group.addButton(radio)
        radio.toggled.connect(lambda checked, f=fmt: self._on_radio(checked, f))

    def _on_radio(self, checked: bool, fmt: Dict[str, Any]):
        if checked:
            self._select_format(fmt)

    def _select_format(self, fmt):
        self.selected_format = fmt
        self._update_download_info()

    def _update_download_info(self):
        if not (self.selected_format and self.current_video):
            return
        fmt = self.selected_format
        info = self.current_video
        self.size_label.setText(f"Estimated Size: {format_size(fmt.get('filesize', 0))}")
        title = sanitize_filename(info.get("title", "video"))
        ext = fmt.get("container", "mp4")
        self.filename_label.setText(f"Filename: {title}.{ext}")

    def _on_thumbnail(self, payload: dict):
        pix = pil_to_qpixmap(payload.get("image"), (360, 200))
        if pix and not pix.isNull():
            self.thumbnail_label.setPixmap(pix)