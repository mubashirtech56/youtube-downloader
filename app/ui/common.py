"""Shared Qt widget helpers used across pages."""

from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel


def pil_to_qpixmap(image: Any, size: Optional[tuple] = None) -> QPixmap:
    """Convert a PIL image to a QPixmap, optionally scaled to `size`."""
    if image is None:
        return QPixmap()
    try:
        if image.mode in ("RGBA", "LA"):
            img = image.convert("RGBA")
            from PySide6.QtGui import QImage

            data = QImage(img.tobytes("raw", "RGBA"), img.width, img.height, 4 * img.width, QImage.Format.Format_RGBA8888)
        else:
            img = image.convert("RGB")
            from PySide6.QtGui import QImage

            data = QImage(img.tobytes(), img.width, img.height, 3 * img.width, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(data)
        if size is not None:
            pix = pix.scaled(size[0], size[1], Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        return pix
    except Exception:
        return QPixmap()


def make_thumbnail_label(size: tuple = (320, 180)) -> QLabel:
    """A fixed-size label used to display a video thumbnail (or placeholder)."""
    label = QLabel()
    label.setFixedSize(*size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet("background: rgba(128,128,128,0.25); border-radius: 8px; color: #8899aa;")
    return label


def set_shadow(widget) -> None:
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(20)
    shadow.setOffset(0, 4)
    widget.setGraphicsEffect(shadow)