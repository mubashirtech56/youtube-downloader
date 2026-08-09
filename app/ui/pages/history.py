"""History page — searchable, filterable list of past downloads."""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from app.controllers.main_controller import MainController
from app.core.utils import format_size, format_timestamp

_HISTORY_COLORS = {
    "completed": "#22c55e",
    "failed": "#ef4444",
    "pending": "#eab308",
}


class HistoryPage(QWidget):
    _BATCH_SIZE = 20

    def __init__(self, controller: MainController, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.controller = controller
        self._entries: List[Dict[str, Any]] = []
        self._batch_index = 0
        self._render_job = 0
        self._build()

    def on_show(self):
        self._load_history()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Search history...")
        self.search_entry.setFixedWidth(260)
        self.search_entry.returnPressed.connect(self._load_history)
        controls.addWidget(self.search_entry)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Completed", "Failed", "Pending"])
        self.filter_combo.currentIndexChanged.connect(lambda _=0: self._load_history())
        controls.addWidget(self.filter_combo)

        controls.addStretch(1)
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._load_history)
        delete_all_btn = QPushButton("🗑 Delete All")
        delete_all_btn.clicked.connect(self._delete_all)
        controls.addWidget(refresh_btn)
        controls.addWidget(delete_all_btn)
        root.addLayout(controls)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)
        self.layout.setSpacing(4)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)

    # ----------------------------------------------------------- data

    def _load_history(self):
        for i in reversed(range(self.layout.count())):
            widget = self.layout.takeAt(i).widget()
            if widget is not None:
                widget.deleteLater()

        status = self.filter_combo.currentText().lower()
        status = None if status == "all" else status
        search = self.search_entry.text().strip() or None

        self._entries = self.controller.db.get_history(limit=200, status=status, search=search)
        if not self._entries:
            empty = QLabel("No history entries")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.layout.addWidget(empty)
            return

        self._batch_index = 0
        self._render_job += 1
        self._render_batch()

    def _render_batch(self):
        if not self._entries:
            return
        start = self._batch_index
        end = min(start + self._BATCH_SIZE, len(self._entries))
        for idx in range(start, end):
            self._render_row(self._entries[idx])
        self._batch_index = end
        if self._batch_index < len(self._entries):
            job = self._render_job
            QTimer.singleShot(0, lambda: self._render_batch() if job == self._render_job else None)

    def _render_row(self, entry: Dict[str, Any]):
        frame = QFrame()
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(12)

        title = QLabel((entry.get("title", "Unknown") or "")[:50])
        title.setToolTip(entry.get("title", ""))
        title.setFixedWidth(280)
        row.addWidget(title)

        fmt = QLabel(entry.get("format", "Unknown"))
        fmt.setFixedWidth(110)
        row.addWidget(fmt)

        size = QLabel(format_size(entry.get("file_size", 0)))
        size.setFixedWidth(80)
        row.addWidget(size)

        status = entry.get("status", "unknown")
        status_label = QLabel(status.title())
        status_label.setStyleSheet(f"color: {_HISTORY_COLORS.get(status, 'gray')};")
        status_label.setFixedWidth(90)
        row.addWidget(status_label)

        when = QLabel(format_timestamp(entry.get("created_at", "")))
        when.setStyleSheet("color: rgba(128,128,128,0.8);")
        row.addWidget(when, 1)

        delete_btn = QPushButton("🗑")
        delete_btn.setFixedWidth(34)
        delete_btn.clicked.connect(lambda _=False, e=entry: self._delete_entry(e))
        row.addWidget(delete_btn)

        self.layout.addWidget(frame)

    def _delete_entry(self, entry: Dict[str, Any]):
        self.controller.db.delete_history_entry(entry.get("id", ""))
        self._load_history()

    def _delete_all(self):
        self.controller.db.clear_history()
        self._load_history()