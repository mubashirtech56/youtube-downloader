"""Theme application for Qt (PySide6) — Modern-Dark / Light stylesheets."""

import logging
from typing import Optional

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from app.core.settings import SettingsManager

_DARK_QSS = """
QMainWindow {
    background: #0e1524;
    color: #e6edf3;
    font-size: 13px;
}
QWidget#Sidebar {
    background-color: #131c2d;
    border-right: 1px solid #243349;
}
QPushButton {
    background-color: #1c2740;
    border: 1px solid #2d3f5c;
    border-radius: 6px;
    padding: 6px 14px;
    color: #e6edf3;
}
QPushButton:hover { background-color: #26344f; }
QPushButton:pressed { background-color: #31405d; }
QPushButton:disabled { color: #5b6b83; background-color: #16202f; }
QPushButton#PrimaryButton {
    background-color: #2563eb; border: none; color: white; font-weight: 600;
}
QPushButton#PrimaryButton:hover { background-color: #3b82f6; }
QPushButton#SuccessButton {
    background-color: #16a34a; border: none; color: white; font-weight: 600;
}
QPushButton#SuccessButton:hover { background-color: #22c55e; }
QPushButton#SidebarButton {
    background: transparent; border: none; border-radius: 8px;
    text-align: left; padding: 10px 16px; color: #94a3b8;
}
QPushButton#SidebarButton:hover { background-color: #1c2740; color: #e6edf3; }
QPushButton#SidebarButtonActive {
    background-color: #2563eb; border: none; border-radius: 8px;
    text-align: left; padding: 10px 16px; color: white; font-weight: 600;
}
QLineEdit, QComboBox, QSpinBox {
    background-color: #131c2d; border: 1px solid #2d3f5c;
    border-radius: 6px; padding: 6px 10px; selection-background-color: #2563eb;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #3b82f6; }
QComboBox QAbstractItemView {
    background-color: #131c2d; border: 1px solid #2d3f5c;
    selection-background-color: #2563eb; selection-color: white;
}
QListWidget, QTableWidget {
    background-color: #101828; border: 1px solid #24324a; border-radius: 8px;
}
QListWidget::item { padding: 8px 10px; border-radius: 6px; }
QListWidget::item:selected { background-color: #1d3557; color: #e6edf3; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #2d3f5c; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3b82f6; }
QScrollBar:horizontal { background: transparent; height: 10px; }
QScrollBar::handle:horizontal { background: #2d3f5c; border-radius: 5px; min-width: 30px; }
QProgressBar {
    background-color: #1c2740; border: none; border-radius: 5px;
    height: 12px; max-height: 12px; text-align: center; color: transparent;
}
QProgressBar::chunk { background-color: #2563eb; border-radius: 5px; }
QProgressBar::chunk#Done { background-color: #16a34a; }
QCheckBox::indicator, QRadioButton::indicator { width: 18px; height: 18px; }
QTabWidget::pane { border: 1px solid #2d3f5c; border-radius: 8px; }
QTabBar::tab {
    background: #131c2d; color: #94a3b8; padding: 8px 16px; border: 1px solid #24324a;
    border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px;
}
QTabBar::tab:selected { background: #1c2740; color: #e6edf3; }
QToolTip { background-color: #1c2740; color: #e6edf3; border: 1px solid #2d3f5c; }
QStatusBar { background: #131c2d; color: #94a3b8; }
"""

_LIGHT_QSS = """
QWidget {
    background: #f7f8fa; color: #1f2933; font-size: 13px;
}
QWidget#Sidebar { background: #eceef1; border-right: 1px solid #d7dbe0; }
QPushButton {
    background-color: #ffffff; border: 1px solid #cdd3da; border-radius: 6px;
    padding: 6px 14px; color: #1f2933;
}
QPushButton:hover { background-color: #f0f2f5; }
QPushButton:pressed { background-color: #e7eaee; }
QPushButton:disabled { color: #9aa3ad; background-color: #f0f2f5; }
QPushButton#PrimaryButton {
    background-color: #2563eb; border: #2563eb; color: white; font-weight: 600;
}
QPushButton#PrimaryButton:hover { background-color: #3b82f6; }
QPushButton#SuccessButton {
    background-color: #16a34a; border: #16a34a; color: white; font-weight: 600;
}
QPushButton#SuccessButton:hover { background-color: #22c55e; }
QPushButton#SidebarButton {
    background: transparent; border: none; border-radius: 8px; text-align: left;
    padding: 10px 16px; color: #5c6670;
}
QPushButton#SidebarButton:hover { background-color: #e2e5ea; color: #1f2933; }
QPushButton#SidebarButtonActive {
    background-color: #2563eb; border: none; border-radius: 8px; text-align: left;
    padding: 10px 16px; color: white; font-weight: 600;
}
QLineEdit, QComboBox, QSpinBox {
    background-color: #ffffff; border: 1px solid #cdd3da; border-radius: 6px;
    padding: 6px 10px; selection-background-color: #bfdbfe;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #2563eb; }
QComboBox QAbstractItemView { background-color: #ffffff; border: 1px solid #cdd3da; }
QListWidget, QGroupBox { background-color: #ffffff; border: 1px solid #e0e4e9; border-radius: 8px; }
QListWidget::item { padding: 8px 10px; border-radius: 6px; }
QListWidget::item:selected { background-color: #2563eb; color: white; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #c6ccd4; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #2563eb; }
QScrollBar:horizontal { background: transparent; height: 10px; }
QScrollBar::handle:horizontal { background: #c6ccd4; border-radius: 5px; min-width: 30px; }
QProgressBar {
    background-color: #e6e9ed; border: none; border-radius: 5px; height: 12px;
    max-height: 12px; text-align: center; color: transparent;
}
QProgressBar::chunk { background: #2563eb; border-radius: 5px; }
QProgressBar::chunk#Done { background: #16a34a; }
QTabWidget::pane { border: 1px solid #d7dbe0; border-radius: 8px; }
QTabBar::tab { background: #eceef1; color: #5c6670; padding: 8px 16px; border: 1px solid #d7dbe0; border-bottom: none; }
QTabBar::tab:selected { background: #ffffff; color: #1f2933; }
QToolTip { background-color: #ffffff; color: #1f2933; border: 1px solid #cdd3da; }
QStatusBar { background: #eceef1; color: #5c6670; }
"""


class ThemeManager:
    def __init__(self, settings: SettingsManager):
        self.logger = logging.getLogger(__name__)
        self.settings = settings
        self.current_theme = settings.get("theme", "dark")

    def apply(self, app: QApplication):
        app.setStyle("Fusion")
        if self.current_theme == "light":
            app.setStyleSheet(_LIGHT_QSS)
            self._apply_palette(app, "light")
        else:
            app.setStyleSheet(_DARK_QSS)
            self._apply_palette(app, "dark")

    def _apply_palette(self, app: QApplication, mode: str):
        if mode == "dark":
            base, text, window, highlight = "#131c2d", "#e6edf3", "#0e1524", "#2563eb"
        else:
            base, text, window, highlight = "#ffffff", "#1f2933", "#f7f8fa", "#2563eb"
        p = app.palette()
        p.setColor(QPalette.ColorRole.Window, QColor(window))
        p.setColor(QPalette.ColorRole.WindowText, QColor(text))
        p.setColor(QPalette.ColorRole.Base, QColor(base))
        p.setColor(QPalette.ColorRole.AlternateBase, QColor(window))
        p.setColor(QPalette.ColorRole.Text, QColor(text))
        p.setColor(QPalette.ColorRole.Button, QColor(window))
        p.setColor(QPalette.ColorRole.ButtonText, QColor(text))
        p.setColor(QPalette.ColorRole.Highlight, QColor(highlight))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        app.setPalette(p)

    def toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self.settings.set("theme", self.current_theme)

    def get_theme(self) -> str:
        return self.current_theme