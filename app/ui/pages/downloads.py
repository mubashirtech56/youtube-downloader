"""Downloads page — live progress cards for active/paused downloads."""

import logging
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from app.controllers.main_controller import MainController

_STATUS_COLORS = {
    "pending": "#eab308",
    "starting": "#eab308",
    "downloading": "#3b82f6",
    "paused": "#f97316",
    "failed": "#ef4444",
    "cancelled": "#64748b",
    "completed": "#22c55e",
}


class DownloadsPage(QWidget):
    def __init__(self, controller: MainController, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.controller = controller
        self.logger = logging.getLogger(__name__)
        self._cards: Dict[str, Dict[str, Any]] = {}
        self._refresh_timer_active = False
        self._refresh_pending = False
        self._placeholder: Optional[QLabel] = None

        controller.downloadEvent.connect(self._on_download_event)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)

        header = QHBoxLayout()
        title = QLabel("⬇ Downloads")
        f = title.font()
        f.setPointSize(18)
        f.setBold(True)
        title.setFont(f)
        header.addWidget(title)
        header.addStretch(1)
        stop_btn = QPushButton("⏹ Stop All")
        stop_btn.clicked.connect(self.controller.stop_all)
        header.addWidget(stop_btn)
        root.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)
        self.layout.setSpacing(8)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)

        self._placeholder = QLabel("No active downloads")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #8899aa; font-size: 15px;")
        self.layout.addWidget(self._placeholder)

    # ------------------------------------------------------------- events

    def _on_download_event(self, event: str, payload: dict):
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(120, self._refresh_now)

    def _refresh_now(self):
        self._refresh_pending = False
        items = self.controller.active_items()
        if not items:
            self._clear_cards()
            self._show_placeholder()
            return
        self._hide_placeholder()
        active_ids = set()
        for item in items:
            active_ids.add(item.id)
            if item.id in self._cards:
                self._update_card(self._cards[item.id], item)
            else:
                self._create_card(item)
        for item_id in list(self._cards):
            if item_id not in active_ids:
                refs = self._cards.pop(item_id)
                refs["card"].deleteLater()

    def _clear_cards(self):
        for refs in list(self._cards.values()):
            refs["card"].deleteLater()
        self._cards = {}

    def _show_placeholder(self):
        if self._placeholder is None:
            self._placeholder = QLabel("No active downloads")
            self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._placeholder.setStyleSheet("color: #8899aa; font-size: 15px;")
            self.layout.addWidget(self._placeholder)

    def _hide_placeholder(self):
        if self._placeholder is not None:
            self._placeholder.deleteLater()
            self._placeholder = None

    # ------------------------------------------------------------- cards

    def _create_card(self, item):
        card = QFrame()
        card.setStyleSheet("background: rgba(128,128,128,0.08); border-radius: 10px;")
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setSpacing(6)

        title = QLabel(item.title[:60] + ("..." if len(item.title) > 60 else ""))
        tf = title.font()
        tf.setPointSize(13)
        tf.setBold(True)
        title.setFont(tf)
        grid.addWidget(title, 0, 0, 1, 4)

        status = QLabel(item.status.title())
        status.setStyleSheet(f"color: {_STATUS_COLORS.get(item.status, 'gray')};")
        grid.addWidget(status, 1, 0)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(int(item.progress * 100))
        grid.addWidget(bar, 2, 0, 1, 4)

        speed = QLabel(f"Speed: {item.speed}")
        eta = QLabel(f"ETA: {item.eta}")
        grid.addWidget(speed, 3, 0)
        grid.addWidget(eta, 3, 1)

        btn_row = QHBoxLayout()
        pause_btn = QPushButton("⏸ Pause")
        resume_btn = QPushButton("▶ Resume")
        cancel_btn = QPushButton("⏹ Cancel")
        pause_btn.clicked.connect(lambda _=False, i=item.id: self.controller.pause(i))
        resume_btn.clicked.connect(lambda _=False, i=item.id: self.controller.resume(i))
        cancel_btn.clicked.connect(lambda _=False, i=item.id: self.controller.cancel(i))
        btn_row.addWidget(pause_btn)
        btn_row.addWidget(resume_btn)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch(1)
        grid.addLayout(btn_row, 4, 0, 1, 4)

        self.layout.addWidget(card)
        self._cards[item.id] = {
            "card": card, "status": status, "bar": bar, "speed": speed, "eta": eta,
            "pause": pause_btn, "resume": resume_btn, "item": item,
        }

    def _update_card(self, refs: Dict[str, Any], item):
        status = item.status
        refs["status"].setText(status.title())
        refs["status"].setStyleSheet(f"color: {_STATUS_COLORS.get(status, 'gray')};")
        refs["bar"].setValue(int(item.progress * 100))
        refs["speed"].setText(f"Speed: {item.speed}")
        refs["eta"].setText(f"ETA: {item.eta}")
        refs["pause"].setVisible(status == "downloading")
        refs["resume"].setVisible(status == "paused")