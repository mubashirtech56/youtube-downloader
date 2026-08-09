"""Settings page — preferences for downloads, appearance and actions."""

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.controllers.main_controller import MainController
from app.core.utils import open_folder


class SettingsPage(QWidget):
    def __init__(self, controller: MainController, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.controller = controller
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setSpacing(14)
        self.scroll.setWidget(body)
        root.addWidget(self.scroll)

        heading = QLabel("⚙ Settings")
        f = heading.font()
        f.setPointSize(22)
        f.setBold(True)
        heading.setFont(f)
        self.body.addWidget(heading)

        settings = self.controller.settings

        # General
        general_frame, general = self._section("General Settings")
        row = QHBoxLayout()
        row.addWidget(QLabel("Download Location"))
        self.folder_label = QLabel(settings.get("download_folder", ""))
        self.folder_label.setStyleSheet("color: rgba(128,128,128,0.9);")
        row.addWidget(self.folder_label, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_folder)
        row.addWidget(browse_btn)
        general.addLayout(row)
        self.body.addWidget(general_frame)

        # Download settings
        download_frame, download = self._section("Download Settings")
        items = [
            ("Maximum Simultaneous Downloads", "max_concurrent_downloads",
             ["1", "2", "3", "4", "5", "6", "8", "10"]),
            ("Default Video Quality", "default_quality",
             ["Best", "2160p", "1440p", "1080p", "720p", "480p", "360p", "240p", "144p"]),
            ("Default Audio Quality", "default_audio_quality", ["320", "256", "192", "128", "64"]),
            ("Default Output Format", "default_output_format", ["mp4", "mkv", "webm", "avi", "mov"]),
        ]
        for label, key, values in items:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            combo = QComboBox()
            combo.addItems(values)
            current = str(settings.get(key, values[0]))
            combo.setCurrentText(current if current in values else values[0])
            combo.currentTextChanged.connect(lambda text, k=key: settings.set(k, text))
            row.addWidget(combo)
            download.addLayout(row)
        self.body.addWidget(download_frame)

        # Appearance
        appearance_frame, appearance = self._section("Appearance")
        row = QHBoxLayout()
        row.addWidget(QLabel("Dark Mode"))
        theme_switch = QCheckBox("Dark Mode")
        theme_switch.setChecked(settings.get("theme", "dark") == "dark")
        theme_switch.toggled.connect(self._toggle_theme)
        row.addWidget(theme_switch, 0)
        row.addStretch(1)
        appearance.addLayout(row)
        self.body.addWidget(appearance_frame)

        # Actions
        actions_frame, actions = self._section("Actions")
        btn_row = QHBoxLayout()
        open_btn = QPushButton("📁 Open Download Folder")
        open_btn.clicked.connect(self._open_folder)
        reset_btn = QPushButton("🔄 Reset Settings")
        reset_btn.clicked.connect(self._reset_settings)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)
        actions.addLayout(btn_row)
        self.body.addWidget(actions_frame)

        self.body.addStretch(1)

    @staticmethod
    def _section(title: str):
        """Returns (frame, layout); the frame must be added to a container so
        the layout (and nested widgets) are not garbage-collected."""
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: rgba(128,128,128,0.08); border-radius: 10px; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        head = QLabel(title)
        hf = head.font()
        hf.setPointSize(14)
        hf.setBold(True)
        head.setFont(hf)
        layout.addWidget(head)
        return frame, layout

    # ---------------------------------------------------------- actions

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Download Folder")
        if path:
            self.controller.settings.set("download_folder", path)
            self.folder_label.setText(path)

    def _toggle_theme(self, checked: bool):
        theme = "dark" if checked else "light"
        self.controller.settings.set("theme", theme)
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            from app.ui.theme import ThemeManager

            ThemeManager(self.controller.settings).apply(app)

    def _open_folder(self):
        folder = self.controller.settings.get("download_folder", "")
        if folder:
            open_folder(folder)

    def _reset_settings(self):
        self.controller.settings.reset()
        self.folder_label.setText(self.controller.settings.get("download_folder", ""))