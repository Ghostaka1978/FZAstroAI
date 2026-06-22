"""Idle mission-control orbit overlay for the main FZAstro window."""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QBrush,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget


class IdleStarsOverlay(QWidget):
    """Low-cost idle screensaver with an engineering mission-control theme.

    The overlay is passive: it appears only after inactivity, ignores mouse
    events so the first user action reaches the normal UI, and hides as soon as
    any keyboard, mouse, wheel, or touch activity is seen by the application.
    """

    ACTIVITY_EVENTS = {
        QEvent.KeyPress,
        QEvent.MouseButtonPress,
        QEvent.MouseButtonRelease,
        QEvent.MouseButtonDblClick,
        QEvent.MouseMove,
        QEvent.Wheel,
        QEvent.TouchBegin,
        QEvent.TouchUpdate,
    }

    def __init__(self, parent: QWidget | None = None, *, idle_ms: int = 120_000):
        super().__init__(parent)
        self.setObjectName("idleStarsOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: #000000;")
        self.setFocusPolicy(Qt.NoFocus)
        self._idle_ms = max(10_000, int(idle_ms or 120_000))
        self._phase = 0.0
        self._stars = self._make_stars()

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._show_overlay)

        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(80)
        self._animation_timer.timeout.connect(self._tick)

        self.hide()
        self.reset_idle_timer()

    def install_on(self, application: QApplication | None = None) -> None:
        """Install the global activity filter used to hide/reset the overlay."""

        app = application or QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def reset_idle_timer(self) -> None:
        """Restart inactivity tracking without changing other application state."""

        self._idle_timer.start(self._idle_ms)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override name
        try:
            if event is not None and event.type() in self.ACTIVITY_EVENTS:
                if self.isVisible():
                    self.hide()
                    self._animation_timer.stop()
                self.reset_idle_timer()
        except RuntimeError:
            pass
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):  # noqa: N802 - Qt override name
        super().resizeEvent(event)
        self._stars = self._make_stars()

    def _show_overlay(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.raise_()
        self.show()
        if not self._animation_timer.isActive():
            self._animation_timer.start()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.035) % (math.pi * 2.0)
        self.update()

    def _make_stars(self) -> tuple[tuple[float, float, float, float, float], ...]:
        rng = random.Random(1978)
        width = max(900, self.width() or 900)
        height = max(600, self.height() or 600)
        count = max(170, min(420, (width * height) // 5200))
        stars = []
        for _ in range(int(count)):
            stars.append(
                (
                    rng.random(),
                    rng.random(),
                    0.55 + rng.random() * 2.1,
                    rng.random() * math.pi * 2.0,
                    0.25 + rng.random() * 0.95,
                )
            )
        return tuple(stars)

    def paintEvent(self, event):  # noqa: N802 - Qt override name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        width = max(1, self.width())
        height = max(1, self.height())

        self._draw_black_space_backdrop(painter, width, height)
        self._draw_stars(painter, width, height)
        self._draw_grid(painter, width, height)
        earth_center = QPointF(width * 0.5, height * 1.05)
        earth_radius = min(width * 0.56, height * 0.62)
        self._draw_earth_limb(painter, earth_center, earth_radius)
        self._draw_moon(painter, width, height)
        spacecraft = self._draw_orbit(
            painter, earth_center, earth_radius, width, height
        )
        self._draw_spacecraft(painter, spacecraft, min(width, height))
        self._draw_telemetry(painter, width, height)
        self._draw_mission_frame(painter, width, height)

        painter.setPen(QPen(QColor(212, 236, 255, 235), 1))
        painter.setFont(QFont("Consolas", 11, QFont.Medium))
        painter.drawText(
            QRectF(0, height - 44, width, 30),
            Qt.AlignCenter,
            "BLACK IDLE MISSION CONTROL · input restores workspace",
        )
        painter.end()

    def _draw_black_space_backdrop(
        self, painter: QPainter, width: int, height: int
    ) -> None:
        """Paint an opaque black mission-display background before overlays."""

        painter.fillRect(self.rect(), QColor(0, 0, 0, 255))

        upper_glow = QRadialGradient(
            QPointF(width * 0.52, height * 1.02), max(width, height) * 0.72
        )
        upper_glow.setColorAt(0.0, QColor(11, 28, 55, 210))
        upper_glow.setColorAt(0.38, QColor(4, 10, 21, 126))
        upper_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), QBrush(upper_glow))

        horizon_glow = QLinearGradient(0, height * 0.42, 0, height)
        horizon_glow.setColorAt(0.0, QColor(0, 0, 0, 0))
        horizon_glow.setColorAt(0.7, QColor(0, 26, 48, 82))
        horizon_glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), QBrush(horizon_glow))

    def _draw_grid(self, painter: QPainter, width: int, height: int) -> None:
        painter.setPen(QPen(QColor(72, 148, 210, 24), 1))
        step = max(48, min(96, width // 16))
        for x in range(0, width + step, step):
            painter.drawLine(QPointF(x, 0), QPointF(x, height))
        for y in range(0, height + step, step):
            painter.drawLine(QPointF(0, y), QPointF(width, y))

        painter.setPen(QPen(QColor(82, 183, 255, 58), 1))
        painter.drawLine(QPointF(width * 0.5, 0), QPointF(width * 0.5, height))
        painter.drawLine(QPointF(0, height * 0.5), QPointF(width, height * 0.5))

    def _draw_stars(self, painter: QPainter, width: int, height: int) -> None:
        painter.setPen(Qt.NoPen)
        drift_span = width * 0.035
        for x_ratio, y_ratio, radius, offset, drift in self._stars:
            twinkle = 0.45 + 0.55 * ((math.sin(self._phase * 1.7 + offset) + 1.0) / 2.0)
            alpha = int(92 + twinkle * 163)
            x = (x_ratio * width + self._phase * drift * drift_span) % width
            y = (
                y_ratio * height * 0.82 + math.sin(self._phase + offset) * drift * 1.6
            ) % height
            size = radius * (0.75 + twinkle * 0.35)
            painter.setBrush(QColor(216, 236, 255, alpha))
            painter.drawEllipse(QPointF(x, y), size, size)

    def _draw_earth_limb(
        self, painter: QPainter, center: QPointF, radius: float
    ) -> None:
        planet = QRectF(
            center.x() - radius, center.y() - radius, radius * 2, radius * 2
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(12, 38, 82, 238))
        painter.drawEllipse(planet)

        painter.setBrush(QColor(29, 93, 137, 170))
        painter.drawEllipse(
            QRectF(
                planet.left() + radius * 0.18,
                planet.top() + radius * 0.22,
                radius * 0.75,
                radius * 0.34,
            )
        )
        painter.setBrush(QColor(25, 113, 86, 150))
        painter.drawEllipse(
            QRectF(
                planet.left() + radius * 0.92,
                planet.top() + radius * 0.18,
                radius * 0.46,
                radius * 0.3,
            )
        )
        painter.setBrush(QColor(222, 241, 255, 80))
        painter.drawEllipse(
            QRectF(
                planet.left() + radius * 0.45,
                planet.top() + radius * 0.12,
                radius * 1.1,
                radius * 0.13,
            )
        )
        painter.drawEllipse(
            QRectF(
                planet.left() + radius * 0.26,
                planet.top() + radius * 0.36,
                radius * 1.45,
                radius * 0.1,
            )
        )

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(111, 207, 255, 150), 4))
        painter.drawArc(planet.adjusted(-7, -7, 7, 7), 17 * 16, 146 * 16)
        painter.setPen(QPen(QColor(111, 207, 255, 52), 11))
        painter.drawArc(planet.adjusted(-16, -16, 16, 16), 17 * 16, 146 * 16)

    def _draw_moon(self, painter: QPainter, width: int, height: int) -> None:
        moon_radius = max(22.0, min(width, height) * 0.045)
        center = QPointF(width * 0.82, height * 0.22)
        moon = QRectF(
            center.x() - moon_radius,
            center.y() - moon_radius,
            moon_radius * 2,
            moon_radius * 2,
        )
        painter.setPen(QPen(QColor(220, 229, 236, 210), 1))
        painter.setBrush(QColor(183, 192, 199, 232))
        painter.drawEllipse(moon)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(94, 103, 112, 92))
        painter.drawEllipse(
            QRectF(
                moon.left() + moon_radius * 0.35,
                moon.top() + moon_radius * 0.42,
                moon_radius * 0.34,
                moon_radius * 0.24,
            )
        )
        painter.drawEllipse(
            QRectF(
                moon.left() + moon_radius * 1.04,
                moon.top() + moon_radius * 0.58,
                moon_radius * 0.26,
                moon_radius * 0.2,
            )
        )
        painter.setBrush(QColor(5, 8, 16, 96))
        painter.drawEllipse(
            moon.adjusted(
                moon_radius * 0.32,
                -moon_radius * 0.06,
                moon_radius * 0.2,
                moon_radius * 0.06,
            )
        )

    def _draw_orbit(
        self,
        painter: QPainter,
        earth_center: QPointF,
        earth_radius: float,
        width: int,
        height: int,
    ) -> QPointF:
        orbit = QRectF(
            earth_center.x() - earth_radius * 0.92,
            earth_center.y() - earth_radius * 1.18,
            earth_radius * 1.84,
            earth_radius * 0.82,
        )
        painter.setBrush(Qt.NoBrush)
        dashed = QPen(QColor(83, 211, 255, 138), 1.4)
        dashed.setDashPattern([6.0, 8.0])
        painter.setPen(dashed)
        painter.drawEllipse(orbit)

        angle = self._phase * 0.7 + 4.1
        x = orbit.center().x() + math.cos(angle) * orbit.width() * 0.5
        y = orbit.center().y() + math.sin(angle) * orbit.height() * 0.5
        painter.setPen(QPen(QColor(83, 211, 255, 76), 1))
        painter.drawLine(
            QPointF(earth_center.x(), earth_center.y() - earth_radius * 0.75),
            QPointF(x, y),
        )
        return QPointF(x, y)

    def _draw_spacecraft(
        self, painter: QPainter, center: QPointF, scale_base: int
    ) -> None:
        scale = max(0.72, min(1.25, scale_base / 850.0))
        body_w = 42.0 * scale
        body_h = 24.0 * scale
        panel_w = 52.0 * scale
        panel_h = 16.0 * scale
        bob = math.sin(self._phase * 2.1) * 2.2
        c = QPointF(center.x(), center.y() + bob)

        painter.setPen(QPen(QColor(156, 199, 230, 218), 1.2))
        painter.setBrush(QColor(26, 34, 48, 236))
        bus = QRectF(c.x() - body_w * 0.5, c.y() - body_h * 0.5, body_w, body_h)
        painter.drawRoundedRect(bus, 4 * scale, 4 * scale)

        painter.setBrush(QColor(35, 87, 134, 205))
        left_panel = QRectF(
            bus.left() - panel_w - 8 * scale, c.y() - panel_h * 0.5, panel_w, panel_h
        )
        right_panel = QRectF(
            bus.right() + 8 * scale, c.y() - panel_h * 0.5, panel_w, panel_h
        )
        painter.drawRect(left_panel)
        painter.drawRect(right_panel)
        painter.setPen(QPen(QColor(125, 184, 226, 170), 1))
        for i in range(1, 4):
            painter.drawLine(
                QPointF(
                    left_panel.left() + left_panel.width() * i / 4.0, left_panel.top()
                ),
                QPointF(
                    left_panel.left() + left_panel.width() * i / 4.0,
                    left_panel.bottom(),
                ),
            )
            painter.drawLine(
                QPointF(
                    right_panel.left() + right_panel.width() * i / 4.0,
                    right_panel.top(),
                ),
                QPointF(
                    right_panel.left() + right_panel.width() * i / 4.0,
                    right_panel.bottom(),
                ),
            )

        painter.setPen(QPen(QColor(156, 199, 230, 210), 1.2))
        painter.drawLine(QPointF(left_panel.right(), c.y()), QPointF(bus.left(), c.y()))
        painter.drawLine(
            QPointF(bus.right(), c.y()), QPointF(right_panel.left(), c.y())
        )
        painter.drawLine(
            QPointF(bus.center().x(), bus.top()),
            QPointF(bus.center().x() + 17 * scale, bus.top() - 18 * scale),
        )
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(
            QPointF(bus.center().x() + 20 * scale, bus.top() - 20 * scale),
            5 * scale,
            5 * scale,
        )

        nose = QPolygonF(
            [
                QPointF(bus.right() - 2 * scale, bus.top() + 4 * scale),
                QPointF(bus.right() + 13 * scale, bus.center().y()),
                QPointF(bus.right() - 2 * scale, bus.bottom() - 4 * scale),
            ]
        )
        painter.setBrush(QColor(196, 209, 219, 230))
        painter.setPen(QPen(QColor(222, 237, 247, 180), 1))
        painter.drawPolygon(nose)

    def _draw_telemetry(self, painter: QPainter, width: int, height: int) -> None:
        alt = 408.0 + math.sin(self._phase * 0.8) * 2.8
        velocity = 7.66 + math.cos(self._phase * 0.6) * 0.03
        roll = math.sin(self._phase * 1.2) * 1.4
        signal = 94 + int((math.sin(self._phase * 1.9) + 1.0) * 2.5)
        telemetry_left = [
            "MISSION CONTROL",
            "ORBIT TELEMETRY",
            f"ALTITUDE     {alt:06.1f} km",
            f"VELOCITY     {velocity:04.2f} km/s",
            f"INCLINATION  51.6 deg",
            f"ROLL         {roll:+04.1f} deg",
            f"SIGNAL       {signal:02d}% LOCK",
        ]
        telemetry_right = [
            "FLIGHT SYSTEMS",
            "GUIDANCE      NOMINAL",
            "STAR TRACKER  LOCKED",
            "IMU           STABLE",
            "POWER BUS     GREEN",
            "THERMAL       IN LIMIT",
            "COMM          S-BAND OK",
        ]
        panel_w = max(245.0, min(330.0, width * 0.28))
        self._draw_panel(painter, QRectF(24, 24, panel_w, 172), telemetry_left)
        self._draw_panel(
            painter, QRectF(width - panel_w - 24, 24, panel_w, 172), telemetry_right
        )

        small = [
            "TRAJECTORY PLOT",
            "EARTH LIMB + MOON REF",
            "ORBIT ARC: DISPLAY SIM",
        ]
        self._draw_panel(painter, QRectF(24, height - 150, panel_w, 94), small)

    def _draw_mission_frame(self, painter: QPainter, width: int, height: int) -> None:
        """Draw a crisp mission-control frame so the overlay reads as intentional UI."""

        margin = 18
        frame = QRectF(margin, margin, width - margin * 2, height - margin * 2)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(76, 185, 255, 116), 1.2))
        painter.drawRect(frame)

        tick = 34
        painter.setPen(QPen(QColor(109, 221, 255, 205), 2.0))
        corners = (
            (frame.left(), frame.top(), 1, 1),
            (frame.right(), frame.top(), -1, 1),
            (frame.left(), frame.bottom(), 1, -1),
            (frame.right(), frame.bottom(), -1, -1),
        )
        for x, y, sx, sy in corners:
            painter.drawLine(QPointF(x, y), QPointF(x + tick * sx, y))
            painter.drawLine(QPointF(x, y), QPointF(x, y + tick * sy))

        header = QRectF(width * 0.34, 23, width * 0.32, 34)
        painter.setPen(QPen(QColor(93, 202, 255, 145), 1))
        painter.setBrush(QColor(0, 0, 0, 220))
        painter.drawRoundedRect(header, 8, 8)
        painter.setPen(QPen(QColor(216, 241, 255, 235), 1))
        painter.setFont(QFont("Consolas", 12, QFont.Bold))
        painter.drawText(header, Qt.AlignCenter, "FZASTRO ORBITAL ENGINEERING DISPLAY")

        painter.setFont(QFont("Consolas", 9, QFont.Medium))
        painter.setPen(QPen(QColor(98, 255, 190, 215), 1))
        painter.drawText(
            QRectF(28, height - 34, 260, 18),
            Qt.AlignLeft,
            "DISPLAY: BLACKOUT / LOW POWER",
        )
        painter.drawText(
            QRectF(width - 292, height - 34, 264, 18),
            Qt.AlignRight,
            "SIM RATE: 1x · LOOP: 80 ms",
        )

    def _draw_panel(self, painter: QPainter, rect: QRectF, lines: list[str]) -> None:
        painter.setPen(QPen(QColor(93, 202, 255, 165), 1))
        painter.setBrush(QColor(0, 0, 0, 218))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setFont(QFont("Consolas", 10, QFont.Medium))
        y = rect.top() + 24
        for index, line in enumerate(lines):
            if index == 0:
                painter.setPen(QPen(QColor(213, 241, 255, 245), 1))
                painter.setFont(QFont("Consolas", 11, QFont.Bold))
            elif index == 1:
                painter.setPen(QPen(QColor(115, 255, 194, 230), 1))
                painter.setFont(QFont("Consolas", 9, QFont.Medium))
            else:
                painter.setPen(QPen(QColor(210, 235, 255, 226), 1))
                painter.setFont(QFont("Consolas", 9, QFont.Medium))
            painter.drawText(
                QRectF(rect.left() + 14, y - 15, rect.width() - 28, 18),
                Qt.AlignLeft | Qt.AlignVCenter,
                line,
            )
            y += 20
