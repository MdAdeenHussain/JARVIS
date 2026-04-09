import math
import random
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QTimer,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QBrush,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsOpacityEffect,
    QGraphicsScene,
    QGraphicsView,
    QMainWindow,
)

# ══════════════════════════════════════════════════════════════════════════
# ██  HUD PALETTE
# ══════════════════════════════════════════════════════════════════════════

HUD_CYAN = QColor(0, 212, 255)
HUD_BLUE = QColor(0, 102, 255)
HUD_PURPLE = QColor(108, 99, 255)
HUD_AMBER = QColor(255, 180, 0)
HUD_RED = QColor(255, 51, 51)
HUD_GREEN = QColor(0, 255, 128)
HUD_BG = QColor(0, 0, 0, 0)
HUD_PANEL_BG = QColor(0, 8, 20, 160)
HUD_PANEL_BORDER = QColor(0, 212, 255, 60)

OPACITY_IDLE = 50
OPACITY_ACTIVE = 220
OPACITY_PANEL_TEXT = 200
OPACITY_PANEL_DIM = 100

SCREEN_UPDATE_INTERVAL_MS = 33

HUD_FONT_SMALL = QFont("Courier New", 9)
HUD_FONT_MEDIUM = QFont("Courier New", 10)
HUD_FONT_LARGE = QFont("Courier New", 32, QFont.Weight.Normal)


def draw_panel_base(painter: QPainter, rect: QRectF, title: str, border_color: QColor = HUD_CYAN) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(HUD_PANEL_BG)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(rect, 6, 6)

    border_pen = QPen(border_color)
    border_pen.setWidthF(0.5)
    border_pen.setColor(border_color)
    painter.setPen(border_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, 6, 6)

    accent_gradient = QLinearGradient(rect.topLeft(), rect.topRight())
    accent_gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
    accent_gradient.setColorAt(0.5, border_color)
    accent_gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
    accent_pen = QPen(QColor(border_color.red(), border_color.green(), border_color.blue(), 180))
    accent_pen.setWidth(2)
    painter.setPen(accent_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(rect.topLeft() + QPointF(10, 1), rect.topRight() - QPointF(10, -1))

    painter.setFont(HUD_FONT_SMALL)
    painter.setPen(QColor(border_color.red(), border_color.green(), border_color.blue(), OPACITY_PANEL_TEXT))
    painter.drawText(rect.adjusted(10, 6, -10, 0), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, title)

    separator_pen = QPen(QColor(border_color.red(), border_color.green(), border_color.blue(), 100))
    separator_pen.setWidthF(0.3)
    painter.setPen(separator_pen)
    painter.drawLine(rect.topLeft() + QPointF(10, 20), rect.topRight() - QPointF(10, -0))
    painter.restore()


def set_window_click_through(window: QMainWindow) -> None:
    try:
        from AppKit import NSApplication

        nsapp = NSApplication.sharedApplication()
        for nswindow in nsapp.windows():
            try:
                nswindow.setIgnoresMouseEvents_(True)
            except Exception:
                pass
    except Exception:
        _set_click_through_swift(window)


def _set_click_through_swift(window: QMainWindow) -> None:
    swift_code = r'''
import Cocoa
let app = NSApplication.shared
for window in app.windows {
    window.ignoresMouseEvents = true
}
'''
    try:
        subprocess.run(["swift", "-"], input=swift_code.encode("utf-8"), timeout=3, check=True)
    except Exception:
        pass


class HudBaseItem(QGraphicsObject):
    def __init__(self) -> None:
        super().__init__()
        self.dirty = True
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

    def mark_dirty(self) -> None:
        self.dirty = True
        self.update(self.boundingRect())

    def paint(self, painter: QPainter, option, widget=None) -> None:
        raise NotImplementedError

    def boundingRect(self) -> QRectF:
        return QRectF()


class HexGrid(HudBaseItem):
    def __init__(self, screen_rect: QRectF) -> None:
        super().__init__()
        self.screen_rect = QRectF(screen_rect)
        self.hex_size = 28
        self.path = QPainterPath()
        self.pixmap: Optional[QPixmap] = None
        self.build_grid()
        self.setZValue(-50)

    def build_grid(self) -> None:
        self.path = QPainterPath()
        r = self.hex_size
        h = r * math.sqrt(3) / 2
        width = int(self.screen_rect.width())
        height = int(self.screen_rect.height())
        x_step = 1.5 * r
        y_step = h * 2
        row = 0
        y = 0.0
        while y - h <= height:
            x_offset = 0 if row % 2 == 0 else r * 0.75
            x = 0.0
            while x - r <= width:
                self.path.addPolygon(self._hexagon(QPointF(x + x_offset, y), r))
                x += x_step
            y += h + h
            row += 1

        self.pixmap = QPixmap(int(self.screen_rect.width()), int(self.screen_rect.height()))
        self.pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.pixmap)
        pen = QPen(HUD_CYAN)
        pen.setWidthF(0.3)
        pen.setColor(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 20))
        painter.setPen(pen)
        painter.drawPath(self.path)
        painter.end()

    def _hexagon(self, center: QPointF, radius: float):
        path = QPainterPath()
        for index in range(6):
            angle = math.radians(60 * index - 30)
            point = QPointF(center.x() + math.cos(angle) * radius, center.y() + math.sin(angle) * radius)
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        path.closeSubpath()
        return path

    def boundingRect(self) -> QRectF:
        return self.screen_rect

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self.pixmap is not None:
            painter.drawPixmap(self.screen_rect.topLeft(), self.pixmap)


class ScanLine(HudBaseItem):
    def __init__(self, screen_rect: QRectF) -> None:
        super().__init__()
        self.screen_rect = QRectF(screen_rect)
        self._y_pos = 0.0
        self.setZValue(-40)
        self.animation = QPropertyAnimation(self, b"y_pos")
        self.animation.setDuration(10000)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(self.screen_rect.height())
        self.animation.setLoopCount(-1)
        self.animation.setEasingCurve(QEasingCurve.Type.Linear)
        self.animation.start()

    def boundingRect(self) -> QRectF:
        return self.screen_rect

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.save()
        gradient = QLinearGradient(0, self._y_pos, self.screen_rect.width(), self._y_pos)
        gradient.setColorAt(0.0, QColor(0, 212, 255, 0))
        gradient.setColorAt(0.5, QColor(0, 212, 255, 100))
        gradient.setColorAt(1.0, QColor(0, 212, 255, 0))
        pen = QPen(QBrush(gradient), 1)
        painter.setPen(pen)
        painter.drawLine(self.screen_rect.left(), self._y_pos, self.screen_rect.right(), self._y_pos)

        trail_rect = QRectF(self.screen_rect.left(), self._y_pos + 2, self.screen_rect.width(), 40)
        trail_gradient = QLinearGradient(trail_rect.topLeft(), trail_rect.bottomLeft())
        trail_gradient.setColorAt(0.0, QColor(0, 212, 255, 30))
        trail_gradient.setColorAt(1.0, QColor(0, 212, 255, 0))
        painter.setBrush(trail_gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(trail_rect)
        painter.restore()

    def get_y_pos(self) -> float:
        return self._y_pos

    def set_y_pos(self, value: float) -> None:
        self._y_pos = value
        self.update(self.boundingRect())

    y_pos = pyqtProperty(float, fget=get_y_pos, fset=set_y_pos)


class CornerBrackets(HudBaseItem):
    def __init__(self, screen_rect: QRectF) -> None:
        super().__init__()
        self.screen_rect = QRectF(screen_rect)
        self._pulse_value = 0.5
        self.setZValue(-30)
        self.animation = QPropertyAnimation(self, b"pulse_value")
        self.animation.setDuration(4000)
        self.animation.setStartValue(0.5)
        self.animation.setEndValue(0.9)
        self.animation.setLoopCount(-1)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.animation.start()
        self.labels = [
            (20, 20, "SYS MONITOR v2.1"),
            (self.screen_rect.width() - 20, 20, "JARVIS ONLINE", Qt.AlignmentFlag.AlignRight),
            (20, self.screen_rect.height() - 20, "ENV: KOLKATA, IN"),
            (self.screen_rect.width() - 20, self.screen_rect.height() - 20, "SESSION ACTIVE", Qt.AlignmentFlag.AlignRight),
        ]

    def boundingRect(self) -> QRectF:
        return self.screen_rect

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.save()
        opacity = int(50 + self._pulse_value * 40)
        pen = QPen(QColor(0, 212, 255, opacity))
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        length = 55.0
        inset = 20.0
        w = self.screen_rect.width()
        h = self.screen_rect.height()
        for x, y, label, *rest in self.labels:
            align = rest[0] if rest else Qt.AlignmentFlag.AlignLeft
            if x < w / 2:
                hx = inset
            else:
                hx = w - inset
            if y < h / 2:
                hy = inset
            else:
                hy = h - inset
            if x < w / 2:
                painter.drawLine(hx, hy, hx + length, hy)
            else:
                painter.drawLine(hx, hy, hx - length, hy)
            if y < h / 2:
                painter.drawLine(hx, hy, hx, hy + length)
            else:
                painter.drawLine(hx, hy, hx, hy - length)
            painter.setFont(HUD_FONT_SMALL)
            painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 60))
            text_rect = QRectF(x - 100 if align == Qt.AlignmentFlag.AlignRight else x, y + 8, 120, 14)
            painter.drawText(text_rect, align, label)
        painter.restore()

    def get_pulse_value(self) -> float:
        return self._pulse_value

    def set_pulse_value(self, value: float) -> None:
        self._pulse_value = value
        self.update(self.boundingRect())

    pulse_value = pyqtProperty(float, fget=get_pulse_value, fset=set_pulse_value)


class ArcReactorRings(HudBaseItem):
    def __init__(self, screen_rect: QRectF) -> None:
        super().__init__()
        self.screen_rect = QRectF(screen_rect)
        self._outer_rotation = 0.0
        self._middle_rotation = 0.0
        self._inner_rotation = 0.0
        self._active_opacity = OPACITY_ACTIVE
        self.screen_center = QPointF(screen_rect.width() / 2, screen_rect.height() - 85)
        self.setZValue(-20)
        self._build_animations()
        self.active = False

    def _build_animations(self) -> None:
        self.outer_animation = QPropertyAnimation(self, b"outer_rotation")
        self.outer_animation.setDuration(12000)
        self.outer_animation.setStartValue(0.0)
        self.outer_animation.setEndValue(360.0)
        self.outer_animation.setLoopCount(-1)
        self.outer_animation.setEasingCurve(QEasingCurve.Type.Linear)
        self.outer_animation.start()

        self.middle_animation = QPropertyAnimation(self, b"middle_rotation")
        self.middle_animation.setDuration(18000)
        self.middle_animation.setStartValue(0.0)
        self.middle_animation.setEndValue(-360.0)
        self.middle_animation.setLoopCount(-1)
        self.middle_animation.setEasingCurve(QEasingCurve.Type.Linear)
        self.middle_animation.start()

        self.inner_animation = QPropertyAnimation(self, b"inner_rotation")
        self.inner_animation.setDuration(8000)
        self.inner_animation.setStartValue(0.0)
        self.inner_animation.setEndValue(360.0)
        self.inner_animation.setLoopCount(-1)
        self.inner_animation.setEasingCurve(QEasingCurve.Type.Linear)
        self.inner_animation.start()

    def boundingRect(self) -> QRectF:
        radius = 75
        return QRectF(self.screen_center.x() - radius - 8, self.screen_center.y() - radius - 8, 2 * radius + 16, 2 * radius + 16)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.save()
        painter.translate(self.screen_center)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer_pen = QPen(HUD_BLUE)
        outer_pen.setWidthF(1.0)
        outer_pen.setColor(QColor(HUD_BLUE.red(), HUD_BLUE.green(), HUD_BLUE.blue(), 180 if not self.active else 230))
        painter.setPen(outer_pen)
        painter.drawEllipse(QPointF(0, 0), 75, 75)
        painter.save()
        painter.rotate(self._outer_rotation)
        for i in range(4):
            painter.drawLine(0, -75, 0, -67)
            painter.rotate(90)
        painter.restore()

        painter.setPen(QPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 200 if not self.active else 230), 1.5))
        painter.drawEllipse(QPointF(0, 0), 52, 52)
        painter.save()
        painter.rotate(self._middle_rotation)
        for i in range(8):
            painter.drawLine(0, -52, 0, -44)
            painter.rotate(45)
        painter.restore()
        for angle in [0, 90, 180, 270]:
            painter.save()
            painter.rotate(angle)
            painter.setBrush(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 180))
            painter.drawRect(-3, -50, 6, 6)
            painter.restore()

        painter.setPen(QPen(QColor(HUD_PURPLE.red(), HUD_PURPLE.green(), HUD_PURPLE.blue(), 190 if not self.active else 230), 1.0, Qt.PenStyle.DashLine))
        painter.setDashPattern([5.0, 4.0])
        painter.drawEllipse(QPointF(0, 0), 28, 28)

        painter.restore()
        painter.save()
        painter.translate(self.screen_center)
        painter.setBrush(QColor(HUD_PURPLE.red(), HUD_PURPLE.green(), HUD_PURPLE.blue(), 120 if not self.active else 180))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(self._flat_top_hexagon(16))
        painter.setBrush(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 255))
        painter.drawEllipse(QPointF(0, 0), 4, 4)
        painter.restore()
        painter.restore()

    def _flat_top_hexagon(self, radius: float) -> QPainterPath:
        path = QPainterPath()
        for index in range(6):
            angle = math.radians(60 * index)
            point = QPointF(math.cos(angle) * radius, math.sin(angle) * radius)
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        path.closeSubpath()
        return path

    def set_active(self, active: bool) -> None:
        self.active = active
        speed = 7200 if active else 12000
        self.outer_animation.setDuration(int(speed * 1.0))
        self.middle_animation.setDuration(int(speed * 1.5))
        self.inner_animation.setDuration(int(speed * 0.67))
        self.mark_dirty()

    def get_outer_rotation(self) -> float:
        return self._outer_rotation

    def set_outer_rotation(self, value: float) -> None:
        self._outer_rotation = value
        self.update(self.boundingRect())

    def get_middle_rotation(self) -> float:
        return self._middle_rotation

    def set_middle_rotation(self, value: float) -> None:
        self._middle_rotation = value
        self.update(self.boundingRect())

    def get_inner_rotation(self) -> float:
        return self._inner_rotation

    def set_inner_rotation(self, value: float) -> None:
        self._inner_rotation = value
        self.update(self.boundingRect())

    outer_rotation = pyqtProperty(float, fget=get_outer_rotation, fset=set_outer_rotation)
    middle_rotation = pyqtProperty(float, fget=get_middle_rotation, fset=set_middle_rotation)
    inner_rotation = pyqtProperty(float, fget=get_inner_rotation, fset=set_inner_rotation)


class PhantomBlip:
    def __init__(self, angle: float, radius: float, special: bool = False) -> None:
        self.angle = angle
        self.radius = radius
        self.special = special
        self.alpha = 0
        self.visible = False
        self.created_at = time.time()

    def position(self, center: QPointF) -> QPointF:
        rad = math.radians(self.angle)
        return QPointF(center.x() + math.cos(rad) * self.radius, center.y() + math.sin(rad) * self.radius)


class RadarPanel(HudBaseItem):
    def __init__(self, screen_rect: QRectF) -> None:
        super().__init__()
        self.screen_rect = QRectF(screen_rect)
        self._angle = 0.0
        self.center = QPointF(screen_rect.width() - 80, screen_rect.height() / 2 - 70)
        self.blips: List[PhantomBlip] = []
        self._build_blips()
        self.sweep_animation = QPropertyAnimation(self, b"sweep_angle")
        self.sweep_animation.setDuration(4000)
        self.sweep_animation.setStartValue(0.0)
        self.sweep_animation.setEndValue(360.0)
        self.sweep_animation.setLoopCount(-1)
        self.sweep_animation.setEasingCurve(QEasingCurve.Type.Linear)
        self.sweep_animation.start()
        self.timer = QTimer()
        self.timer.timeout.connect(self._advance_blips)
        self.timer.start(100)
        self.setZValue(-25)

    def _build_blips(self) -> None:
        self.blips.clear()
        for index in range(5):
            angle = random.uniform(0, 360)
            radius = random.uniform(20, 50)
            special = index == 0
            self.blips.append(PhantomBlip(angle=angle, radius=radius, special=special))

    def _advance_blips(self) -> None:
        for blip in self.blips:
            delta = (self._angle - blip.angle + 360) % 360
            if delta < 15 and not blip.visible:
                blip.visible = True
                blip.alpha = 255
                blip.created_at = time.time()
            if blip.visible:
                elapsed = time.time() - blip.created_at
                blip.alpha = max(0, 255 - int((elapsed / 2.5) * 255))
                if blip.alpha == 0:
                    blip.visible = False
                    blip.angle = random.uniform(0, 360)
                    blip.radius = random.uniform(20, 50)
        self.update(self.boundingRect())

    def boundingRect(self) -> QRectF:
        return QRectF(self.center.x() - 70, self.center.y() - 70, 140, 140)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.translate(self.center)
        pen = QPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 180))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), 65, 65)
        painter.setPen(QPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 80), 1.0))
        painter.drawEllipse(QPointF(0, 0), 50, 50)
        painter.drawEllipse(QPointF(0, 0), 33, 33)
        cross_pen = QPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 60), 0.5)
        painter.setPen(cross_pen)
        painter.drawLine(-60, 0, 60, 0)
        painter.drawLine(0, -60, 0, 60)
        painter.rotate(self._angle)
        sweep_gradient = QLinearGradient(0, 0, 60, 0)
        sweep_gradient.setColorAt(0.0, QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 0))
        sweep_gradient.setColorAt(1.0, QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 180))
        sweep_pen = QPen(QBrush(sweep_gradient), 1.5)
        painter.setPen(sweep_pen)
        painter.drawLine(0, 0, 60, 0)
        painter.restore()
        painter.save()
        for blip in self.blips:
            if not blip.visible:
                continue
            pos = blip.position(self.center)
            color = HUD_AMBER if blip.special else HUD_CYAN
            alpha = int(blip.alpha)
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), alpha))
            painter.setPen(Qt.PenStyle.NoPen)
            size = 6 if blip.special else 4
            painter.drawEllipse(pos, size, size)
        painter.restore()
        painter.save()
        painter.setFont(HUD_FONT_SMALL)
        painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 60))
        painter.drawText(QRectF(self.center.x() - 70, self.center.y() - 80, 140, 14), Qt.AlignmentFlag.AlignCenter, "PROXIMITY SCAN")
        painter.drawText(QRectF(self.center.x() - 70, self.center.y() + 70, 140, 14), Qt.AlignmentFlag.AlignCenter, "KOLKATA 22.57°N")
        painter.restore()

    def get_sweep_angle(self) -> float:
        return self._angle

    def set_sweep_angle(self, value: float) -> None:
        self._angle = value % 360
        self.update(self.boundingRect())

    sweep_angle = pyqtProperty(float, fget=get_sweep_angle, fset=set_sweep_angle)


class SystemVitalsPanel(HudBaseItem):
    def __init__(self) -> None:
        super().__init__()
        self.rect = QRectF(20, 20, 280, 180)
        self.data = {
            "cpu": 12,
            "ram": 38,
            "disk": 44,
            "temp": 43,
            "download": "1.2MB",
            "upload": "4.8MB",
        }
        self.last_net_bytes = None
        self.last_net_time = time.time()
        self.setZValue(10)

    def boundingRect(self) -> QRectF:
        return self.rect

    def set_metrics(self, metrics: Dict[str, Any]) -> None:
        changed = False
        for key in ["cpu", "ram", "disk", "temp", "download", "upload"]:
            if key in metrics and metrics[key] != self.data.get(key):
                self.data[key] = metrics[key]
                changed = True
        if changed:
            self.mark_dirty()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if not self.dirty:
            return
        self.dirty = False
        painter.save()
        draw_panel_base(painter, self.rect, "SYSTEM VITALS")
        painter.setFont(HUD_FONT_MEDIUM)
        labels = ["CPU", "RAM", "DISK"]
        values = [self.data["cpu"], self.data["ram"], self.data["disk"]]
        for index, label in enumerate(labels):
            y = 40 + index * 24
            painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 180))
            painter.setFont(HUD_FONT_SMALL)
            painter.drawText(25, y + 10, label)
            pct = int(values[index]) if isinstance(values[index], (int, float)) else 0
            bar_width = min(120, pct * 1.2)
            color = HUD_GREEN if pct < 60 else HUD_AMBER if pct < 80 else HUD_RED
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 220))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(95, y + 2, bar_width, 4, 2, 2)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 180))
            painter.drawRoundedRect(95, y + 2, 120, 4, 2, 2)
            painter.setFont(HUD_FONT_SMALL)
            painter.drawText(220, y + 10, f"{pct}%")

        y_offset = 40 + 3 * 24
        painter.setFont(HUD_FONT_SMALL)
        temp_color = HUD_GREEN if self.data["temp"] < 70 else HUD_AMBER if self.data["temp"] < 85 else HUD_RED
        painter.setPen(temp_color)
        painter.drawText(25, y_offset + 10, f"TEMP {self.data['temp']}°C")
        painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 180))
        painter.drawText(150, y_offset + 10, f"HUMIDITY {self.data.get('humidity', 44)}%")
        painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 180))
        painter.drawText(25, y_offset + 34, f"↑ {self.data['upload']}   ↓ {self.data['download']}")
        painter.restore()


class TemporalPanel(HudBaseItem):
    def __init__(self) -> None:
        super().__init__()
        self.rect = QRectF(0, 0, 260, 180)
        self.rect.moveTo(0, 20)
        self.provider = "GEMINI"
        self.db_status = "OK"
        self.net_status = "ONLINE"
        self.mic_status = "SLEEPING"
        self.dot_states = {"AI": 255, "DB": 255, "NET": 255, "MIC": 255}
        self.dot_timer = QTimer()
        self.dot_timer.timeout.connect(self._pulse_dots)
        self.dot_timer.start(1000)
        self.setZValue(10)

    def boundingRect(self) -> QRectF:
        return self.rect

    def set_provider(self, provider: str) -> None:
        self.provider = provider.upper()
        self.mark_dirty()

    def set_status(self, db_status: str, net_status: str, mic_status: str) -> None:
        self.db_status = db_status
        self.net_status = net_status
        self.mic_status = mic_status
        self.mark_dirty()

    def _pulse_dots(self) -> None:
        for key in self.dot_states:
            self.dot_states[key] = 180 if self.dot_states[key] > 200 else 255
        self.mark_dirty()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if not self.dirty:
            return
        self.dirty = False
        painter.save()
        draw_panel_base(painter, self.rect, "TEMPORAL + AI STATUS")
        painter.setFont(HUD_FONT_LARGE)
        painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 255))
        painter.drawText(self.rect.adjusted(15, 32, -15, 0), Qt.AlignmentFlag.AlignLeft, time.strftime("%H:%M"))
        painter.setFont(HUD_FONT_SMALL)
        painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 160))
        painter.drawText(self.rect.adjusted(15, 70, -15, 0), Qt.AlignmentFlag.AlignLeft, time.strftime("%A, %d %b"))
        rows = [
            ("AI", f"{self.provider} ACTIVE", HUD_GREEN if self.provider != "ERROR" else HUD_RED),
            ("DB", f"POSTGRESQL {self.db_status}", HUD_GREEN),
            ("NET", self.net_status, HUD_GREEN if self.net_status == "ONLINE" else HUD_RED),
            ("MIC", self.mic_status, HUD_GREEN if self.mic_status == "LISTENING" else HUD_AMBER),
        ]
        y = 106
        for label, status, color in rows:
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), self.dot_states[label]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(18, y - 8, 6, 6)
            painter.setFont(HUD_FONT_SMALL)
            painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 200))
            painter.drawText(30, y, f"{label}: {status}")
            y += 24
        badge_rect = QRectF(self.rect.right() - 80, self.rect.top() + 32, 64, 18)
        painter.setBrush(QColor(HUD_PURPLE.red(), HUD_PURPLE.green(), HUD_PURPLE.blue(), 180))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, 9, 9)
        painter.setPen(Qt.PenStyle.SolidLine)
        painter.setPen(QColor(255, 255, 255, 220))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, self.provider)
        painter.restore()


class EnvironmentPanel(HudBaseItem):
    def __init__(self) -> None:
        super().__init__()
        self.rect = QRectF(20, 0, 240, 160)
        self.rect.moveBottomLeft(QPointF(20, 20))
        self.rect.moveBottomLeft(QPointF(20, -20))
        self.data = {
            "location": "KOLKATA, IN",
            "temperature": 28,
            "condition": "PARTLY CLOUDY",
            "humidity": 74,
            "wind": "12km/h NE",
            "aqi": 48,
            "updated": time.strftime("%H:%M"),
        }
        self.setZValue(10)

    def boundingRect(self) -> QRectF:
        return self.rect

    def set_live_data(self, data: Dict[str, any]) -> None:
        changed = False
        for key in self.data:
            if key in data and data[key] != self.data[key]:
                self.data[key] = data[key]
                changed = True
        if changed:
            self.mark_dirty()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if not self.dirty:
            return
        self.dirty = False
        painter.save()
        draw_panel_base(painter, self.rect, "ENVIRONMENT")
        painter.setFont(HUD_FONT_SMALL)
        painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 160))
        painter.drawText(self.rect.adjusted(10, 32, -10, 0), Qt.AlignmentFlag.AlignLeft, self.data["location"])
        painter.setFont(QFont("Courier New", 28))
        painter.setPen(HUD_CYAN)
        painter.drawText(self.rect.adjusted(10, 52, -10, 0), Qt.AlignmentFlag.AlignLeft, f"{self.data['temperature']}°C")
        painter.setFont(HUD_FONT_MEDIUM)
        painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 220))
        painter.drawText(self.rect.adjusted(10, 90, -10, 0), Qt.AlignmentFlag.AlignLeft, self.data["condition"])
        painter.setFont(HUD_FONT_SMALL)
        painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 180))
        painter.drawText(self.rect.adjusted(10, 110, -10, 0), Qt.AlignmentFlag.AlignLeft, f"HUMIDITY {self.data['humidity']}%   WIND {self.data['wind']}")
        aqi_label = "GOOD"
        aqi_color = HUD_GREEN
        if self.data["aqi"] > 200:
            aqi_label = "HAZARDOUS"
            aqi_color = HUD_RED
        elif self.data["aqi"] > 100:
            aqi_label = "UNHEALTHY"
            aqi_color = HUD_AMBER
        elif self.data["aqi"] > 50:
            aqi_label = "MODERATE"
            aqi_color = QColor(255, 255, 128)
        painter.setPen(aqi_color)
        painter.drawText(self.rect.adjusted(10, 132, -10, 0), Qt.AlignmentFlag.AlignLeft, f"AQI {self.data['aqi']} {aqi_label}")
        painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 80))
        painter.setFont(QFont("Courier New", 8))
        painter.drawText(self.rect.adjusted(10, 150, -10, 0), Qt.AlignmentFlag.AlignLeft, f"Updated {self.data['updated']}")
        painter.restore()


class LiveIntelPanel(HudBaseItem):
    def __init__(self) -> None:
        super().__init__()
        self.rect = QRectF(0, 0, 260, 200)
        self.rect.moveTo(0, 0)
        self.rect.moveTopRight(QPointF(0, 0))
        self.data = {
            "crypto": [{"symbol": "BTC", "price": "$68,240", "change": 1.3}],
            "news": ["Jarvis HUD initialization complete.", "Local LLM fallback active.", "Hardware monitor stable."],
        }
        self.headline_index = 0
        self.marquee_timer = QTimer()
        self.marquee_timer.timeout.connect(self._advance_headline)
        self.marquee_timer.start(4000)
        self.blink_on = True
        self.blink_timer = QTimer()
        self.blink_timer.timeout.connect(self._toggle_blink)
        self.blink_timer.start(1000)
        self.setZValue(10)

    def boundingRect(self) -> QRectF:
        return QRectF(self.rect.right() - 260, self.rect.bottom() - 200, 260, 200)

    def set_live_data(self, data: Dict[str, any]) -> None:
        changed = False
        if "crypto" in data and data["crypto"] != self.data["crypto"]:
            self.data["crypto"] = data["crypto"]
            changed = True
        if "news" in data and data["news"] != self.data["news"]:
            self.data["news"] = data["news"]
            self.headline_index = 0
            changed = True
        if changed:
            self.mark_dirty()

    def _advance_headline(self) -> None:
        self.headline_index = (self.headline_index + 1) % max(1, len(self.data["news"]))
        self.mark_dirty()

    def _toggle_blink(self) -> None:
        self.blink_on = not self.blink_on
        self.mark_dirty()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if not self.dirty:
            return
        self.dirty = False
        origin = QPointF(self.rect.right() - 260, self.rect.bottom() - 200)
        painter.save()
        draw_panel_base(painter, QRectF(origin, self.rect.size()), "LIVE INTEL")
        painter.setFont(HUD_FONT_SMALL)
        painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), OPACITY_PANEL_TEXT))
        y = origin.y() + 30
        for item in self.data["crypto"][:3]:
            change_color = HUD_GREEN if item["change"] >= 0 else HUD_RED
            arrow = "▲" if item["change"] >= 0 else "▼"
            painter.drawText(origin.x() + 10, y, f"{item['symbol']}  {item['price']}  ")
            painter.setPen(change_color)
            painter.drawText(origin.x() + 140, y, f"{arrow}{abs(item['change']):.1f}%")
            painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), OPACITY_PANEL_TEXT))
            y += 22
        painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), 80))
        painter.drawLine(origin.x() + 10, y + 4, origin.x() + 250, y + 4)
        y += 20
        painter.setPen(QColor(HUD_CYAN.red(), HUD_CYAN.green(), HUD_CYAN.blue(), OPACITY_PANEL_TEXT))
        for index in range(min(3, len(self.data["news"]))):
            headline = self.data["news"][(self.headline_index + index) % len(self.data["news"])]
            truncated = headline if len(headline) <= 38 else headline[:35] + "..."
            painter.drawText(origin.x() + 10, y, truncated)
            y += 16
        painter.setPen(QColor(HUD_RED.red(), HUD_RED.green(), HUD_RED.blue(), 255 if self.blink_on else 80))
        painter.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        painter.drawText(origin.x() + 10, origin.y() + 14, "LIVE INTEL")
        painter.restore()


class CenterActivePanel(HudBaseItem):
    def __init__(self) -> None:
        super().__init__()
        self.rect = QRectF(0, 0, 500, 200)
        self.rect.moveCenter(QPointF(0, 0))
        self.state = "idle"
        self.heard_text = ""
        self.response_text = ""
        self.opacity = 0.0
        self.animation = QPropertyAnimation(self, b"panel_opacity")
        self.animation.setDuration(300)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.bar_levels = [20] * 24
        self.bar_timer = QTimer()
        self.bar_timer.timeout.connect(self._animate_bars)
        self.bar_timer.start(200)
        self.setZValue(20)

    def boundingRect(self) -> QRectF:
        return QRectF(self.rect)

    def _animate_bars(self) -> None:
        if self.state not in {"listening", "speaking"}:
            return
        self.bar_levels = [random.uniform(4, 60) for _ in self.bar_levels]
        self.update(self.boundingRect())

    def set_state(self, state: str, heard: str = "", response: str = "") -> None:
        self.state = state
        self.heard_text = heard
        self.response_text = response
        self.animation.stop()
        self.animation.setStartValue(self.opacity)
        self.animation.setEndValue(220.0 if state != "idle" else 0.0)
        self.animation.start()
        self.mark_dirty()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self.opacity <= 0.0:
            return
        painter.save()
        painter.setOpacity(self.opacity / 255.0)
        draw_panel_base(painter, self.rect.translated(self.scenePos()), "VOICE CAPTURE ACTIVE" if self.state == "listening" else "SYSTEM STATUS")
        painter.restore()

    def get_panel_opacity(self) -> float:
        return self.opacity

    def set_panel_opacity(self, value: float) -> None:
        self.opacity = value
        self.update(self.boundingRect())

    panel_opacity = pyqtProperty(float, fget=get_panel_opacity, fset=set_panel_opacity)


class TaskTimeline(HudBaseItem):
    def __init__(self, screen_rect: QRectF) -> None:
        super().__init__()
        self.screen_rect = QRectF(screen_rect)
        self.rect = QRectF(0, 0, screen_rect.width() - 40, 45)
        self.rect.moveBottomLeft(QPointF(20, screen_rect.height() - 95))
        self.tasks: Deque[Dict[str, str]] = deque(maxlen=6)
        self.setZValue(15)

    def boundingRect(self) -> QRectF:
        return self.rect

    def set_tasks(self, task_list: List[Dict[str, str]]) -> None:
        self.tasks = deque(task_list[-6:], maxlen=6)
        self.mark_dirty()

    def add_task(self, task: Dict[str, str]) -> None:
        self.tasks.append(task)
        self.mark_dirty()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if not self.dirty:
            return
        self.dirty = False
        painter.save()
        draw_panel_base(painter, self.rect, "TASK TIMELINE")
        painter.setPen(Qt.PenStyle.NoPen)
        x = self.rect.left() + 10
        y = self.rect.top() + 20
        for task in list(self.tasks):
            status = task.get("status", "PENDING")
            label = task.get("label", "Task")
            if status == "RUNNING":
                color = QColor(HUD_AMBER.red(), HUD_AMBER.green(), HUD_AMBER.blue(), 100)
            elif status == "DONE":
                color = QColor(HUD_GREEN.red(), HUD_GREEN.green(), HUD_GREEN.blue(), 80)
            elif status == "ERROR":
                color = QColor(HUD_RED.red(), HUD_RED.green(), HUD_RED.blue(), 120)
            else:
                color = QColor(HUD_BLUE.red(), HUD_BLUE.green(), HUD_BLUE.blue(), 80)
            pill_width = min(160, 14 + len(label) * 7)
            pill_rect = QRectF(x, y - 12, pill_width, 24)
            painter.setBrush(color)
            painter.drawRoundedRect(pill_rect, 12, 12)
            painter.setPen(QColor(255, 255, 255, 220))
            painter.setFont(HUD_FONT_SMALL)
            painter.drawText(pill_rect.adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, f"{status} {label}")
            x += pill_width + 10
            if x > self.rect.right() - 100:
                break
        painter.restore()


class JARVISHUDWindow(QMainWindow):
    def __init__(self, bridge: QObject, logger=None) -> None:
        super().__init__()
        self.bridge = bridge
        self.logger = logger
        self.screen_geometry = QApplication.primaryScreen().geometry()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setGeometry(self.screen_geometry)
        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(QRectF(self.screen_geometry))
        self.view = QGraphicsView(self.scene, self)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setFrameStyle(0)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.view.setStyleSheet("background: transparent; border: none;")
        self.view.setGeometry(self.screen_geometry)
        self.view.setSceneRect(self.scene.sceneRect())
        self.view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.view.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)

        self.hidden = False
        self.dimmed = False
        self.fullscreen_mode = False
        self.night_mode = False

        self._build_hud_items()
        self._connect_bridge()
        QTimer.singleShot(250, lambda: set_window_click_through(self))

    def _build_hud_items(self) -> None:
        screen_rect = QRectF(self.screen_geometry)
        self.hex_grid = HexGrid(screen_rect)
        self.scan_line = ScanLine(screen_rect)
        self.corner_brackets = CornerBrackets(screen_rect)
        self.arc_reactor = ArcReactorRings(screen_rect)
        self.radar_panel = RadarPanel(screen_rect)
        self.system_vitals = SystemVitalsPanel()
        self.temporal_panel = TemporalPanel()
        self.environment_panel = EnvironmentPanel()
        self.live_intel_panel = LiveIntelPanel()
        self.center_panel = CenterActivePanel()
        self.task_timeline = TaskTimeline(screen_rect)

        self.night_filter = self.scene.addRect(self.scene.sceneRect(), Qt.PenStyle.NoPen, QBrush(QColor(4, 10, 35, 20)))
        self.night_filter.setZValue(-80)
        self.night_filter.setVisible(False)

        self.scene.addItem(self.hex_grid)
        self.scene.addItem(self.scan_line)
        self.scene.addItem(self.corner_brackets)
        self.scene.addItem(self.arc_reactor)
        self.scene.addItem(self.radar_panel)
        self.scene.addItem(self.system_vitals)
        self.scene.addItem(self.temporal_panel)
        self.scene.addItem(self.environment_panel)
        self.scene.addItem(self.live_intel_panel)
        self.scene.addItem(self.center_panel)
        self.scene.addItem(self.task_timeline)

    def _connect_bridge(self) -> None:
        if self.bridge is None:
            return
        if getattr(self.bridge, "state_signal", None):
            self.bridge.state_signal.connect(self.on_state_changed)
        if getattr(self.bridge, "metric_update", None):
            self.bridge.metric_update.connect(self.on_metric_update)
        if getattr(self.bridge, "live_data_update", None):
            self.bridge.live_data_update.connect(self.on_live_data_update)
        if getattr(self.bridge, "transcript_update", None):
            self.bridge.transcript_update.connect(self.on_transcript_update)
        if getattr(self.bridge, "provider_signal", None):
            self.bridge.provider_signal.connect(self.on_provider_changed)
        if getattr(self.bridge, "project_opened", None):
            self.bridge.project_opened.connect(self.on_project_opened)
        if getattr(self.bridge, "alert_signal", None):
            self.bridge.alert_signal.connect(self.on_alert)
        if getattr(self.bridge, "hud_command", None):
            self.bridge.hud_command.connect(self.on_hud_command)

    def on_state_changed(self, state: str) -> None:
        active = state in {"listening", "thinking", "speaking"}
        self.arc_reactor.set_active(active)
        self.center_panel.set_state(state)
        if state == "error":
            QTimer.singleShot(2500, lambda: self.center_panel.set_state("idle"))
        self.apply_visibility()

    def on_metric_update(self, metrics: Dict[str, any]) -> None:
        self.system_vitals.set_metrics(metrics)

    def on_live_data_update(self, data: Dict[str, any]) -> None:
        self.environment_panel.set_live_data(data)
        self.live_intel_panel.set_live_data(data)

    def on_transcript_update(self, heard: str, response: str) -> None:
        self.center_panel.set_state("speaking", heard, response)

    def on_provider_changed(self, provider: str) -> None:
        self.temporal_panel.set_provider(provider)

    def on_project_opened(self, project_name: str) -> None:
        self.task_timeline.add_task({"status": "RUNNING", "label": project_name})

    def on_alert(self, alert_type: str, message: str) -> None:
        self.task_timeline.add_task({"status": "ERROR", "label": message[:20]})

    def on_hud_command(self, command: str) -> None:
        cmd = command.strip().lower()
        if cmd == "hide display":
            self.hidden = True
        elif cmd == "show display":
            self.hidden = False
        elif cmd == "dim display":
            self.dimmed = True
        elif cmd == "brighten display":
            self.dimmed = False
        elif cmd == "fullscreen mode":
            self.fullscreen_mode = True
        elif cmd == "dashboard mode":
            self.fullscreen_mode = False
        elif cmd == "night mode":
            self.night_mode = not self.night_mode
        self.apply_visibility()

    def apply_visibility(self) -> None:
        self.setWindowOpacity(0.0 if self.hidden else 0.85 if self.dimmed else 1.0)
        self.hex_grid.setVisible(not self.fullscreen_mode)
        self.corner_brackets.setVisible(not self.fullscreen_mode)
        self.radar_panel.setVisible(not self.fullscreen_mode)
        self.system_vitals.setVisible(not self.fullscreen_mode)
        self.temporal_panel.setVisible(not self.fullscreen_mode)
        self.environment_panel.setVisible(not self.fullscreen_mode)
        self.live_intel_panel.setVisible(not self.fullscreen_mode)
        self.task_timeline.setVisible(not self.fullscreen_mode)
        self.arc_reactor.setVisible(True)
        self.center_panel.setVisible(True)
        if self.night_mode:
            self._apply_night_palette()
        else:
            self._apply_day_palette()

    def _apply_night_palette(self) -> None:
        self.setWindowOpacity(0.88)
        self.night_filter.setVisible(True)
        self.scene.setBackgroundBrush(QColor(0, 0, 0, 18))

    def _apply_day_palette(self) -> None:
        self.setWindowOpacity(1.0)
        self.night_filter.setVisible(False)
        self.scene.setBackgroundBrush(QColor(0, 0, 0, 0))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.view.setGeometry(self.screen_geometry)
        self.view.show()

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        QApplication.quit()


class HudOverlayThread(threading.Thread):
    def __init__(self, bridge: QObject, logger=None) -> None:
        super().__init__(daemon=True, name="jarvis-hud-overlay")
        self.bridge = bridge
        self.logger = logger
        self.ready_event = threading.Event()
        self.failed = False
        self.app: Optional[QApplication] = None
        self.window: Optional[JARVISHUDWindow] = None

    def run(self) -> None:
        try:
            self.app = QApplication.instance() or QApplication(sys.argv)
            self.app.setQuitOnLastWindowClosed(False)
            self.window = JARVISHUDWindow(self.bridge, self.logger)
            if self.bridge is not None and getattr(self.bridge, "stop_signal", None):
                self.bridge.stop_signal.connect(self.window.close)
                self.bridge.stop_signal.connect(self.app.quit)
            self.window.showFullScreen()
            self.window.show()
            self.ready_event.set()
            self.app.exec()
        except Exception as error:
            self.failed = True
            if self.logger:
                self.logger.error("HUD failed to start: %s", error)
            self.ready_event.set()

    def stop(self) -> None:
        if self.app is not None:
            self.app.quit()
