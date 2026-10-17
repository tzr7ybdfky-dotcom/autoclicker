"""Иконка приложения, нарисованная кодом (без внешних файлов)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

from .theme import ACCENT, ACCENT_PRESSED


def render_icon(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 1024.0

    # Фон — скруглённый квадрат с мягким градиентом акцентного цвета.
    margin = 100 * s
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0, QColor(ACCENT))
    grad.setColorAt(1, QColor(ACCENT_PRESSED))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(rect, 185 * s, 185 * s)

    # Круги «клика».
    center = QPointF(430 * s, 430 * s)
    pen = QPen(QColor(255, 255, 255, 110), 34 * s)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(center, 190 * s, 190 * s)
    pen.setColor(QColor(255, 255, 255, 200))
    p.setPen(pen)
    p.drawEllipse(center, 105 * s, 105 * s)

    # Стрелка курсора.
    pts = [(430, 430), (430, 810), (525, 715), (590, 860), (665, 828), (600, 685), (735, 685)]
    path = QPainterPath(QPointF(pts[0][0] * s, pts[0][1] * s))
    for x, y in pts[1:]:
        path.lineTo(x * s, y * s)
    path.closeSubpath()
    p.setPen(QPen(QColor("#10233f"), 30 * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(QColor("white"))
    p.drawPath(path)
    p.end()
    return img


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256, 512):
        icon.addPixmap(QPixmap.fromImage(render_icon(size)))
    return icon
