"""Idle Matrix-style code-rain overlay for the main FZAstro window."""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget


class IdleStarsOverlay(QWidget):
    """Low-cost idle screensaver with black-background code rain.

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

    _GLYPHS = "01FZASTROAI<>[]{}#$:/\\+-*=░▒▓"

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
        self._tick_count = 0
        self._columns = self._make_columns()

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._show_overlay)

        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(65)
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
        self._columns = self._make_columns()

    def _show_overlay(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.raise_()
        self.show()
        if not self._animation_timer.isActive():
            self._animation_timer.start()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.065) % (math.pi * 2.0)
        self._tick_count = (self._tick_count + 1) % 1_000_000
        self.update()

    def _make_columns(self) -> tuple[dict[str, object], ...]:
        rng = random.Random(2106)
        width = max(900, self.width() or 900)
        height = max(600, self.height() or 600)
        cell = 17 if width < 1200 else 19
        count = max(48, int(width // cell) + 2)
        rows = max(38, int(height // 18) + 12)
        columns: list[dict[str, object]] = []
        for index in range(count):
            stream_length = rng.randint(10, 34)
            text = "".join(
                rng.choice(self._GLYPHS) for _ in range(rows + stream_length + 10)
            )
            columns.append(
                {
                    "x": index * cell + rng.uniform(-3.5, 3.5),
                    "offset": rng.uniform(-height, height),
                    "speed": rng.uniform(1.8, 5.6),
                    "length": stream_length,
                    "text": text,
                    "phase": rng.random() * math.pi * 2.0,
                    "cell": cell,
                }
            )
        return tuple(columns)

    def paintEvent(self, event):  # noqa: N802 - Qt override name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        width = max(1, self.width())
        height = max(1, self.height())

        self._draw_black_backdrop(painter, width, height)
        self._draw_code_rain(painter, width, height)
        self._draw_scanlines(painter, width, height)
        self._draw_matrix_frame(painter, width, height)

        painter.end()

    def _draw_black_backdrop(self, painter: QPainter, width: int, height: int) -> None:
        """Paint a true opaque black background before the code rain."""

        painter.fillRect(self.rect(), QColor(0, 0, 0, 255))
        glow = QLinearGradient(0, 0, 0, height)
        glow.setColorAt(0.0, QColor(0, 20, 8, 54))
        glow.setColorAt(0.44, QColor(0, 0, 0, 0))
        glow.setColorAt(1.0, QColor(0, 32, 13, 76))
        painter.fillRect(self.rect(), QBrush(glow))

    def _draw_code_rain(self, painter: QPainter, width: int, height: int) -> None:
        font_size = 13 if width < 1200 else 14
        painter.setFont(QFont("Consolas", font_size, QFont.Medium))
        row_step = font_size + 4
        horizon = height + row_step * 3

        for column in self._columns:
            x = float(column["x"])
            speed = float(column["speed"])
            length = int(column["length"])
            text = str(column["text"])
            phase = float(column["phase"])
            y_head = (float(column["offset"]) + self._tick_count * speed) % horizon
            flicker = 0.72 + 0.28 * ((math.sin(self._phase * 2.2 + phase) + 1.0) / 2.0)

            for row in range(length):
                y = y_head - row * row_step
                if y < -row_step or y > height + row_step:
                    continue
                char = text[(self._tick_count // 3 + row) % len(text)]
                fade = 1.0 - (row / max(1, length))
                if row == 0:
                    color = QColor(226, 255, 226, int(238 * flicker))
                    painter.setPen(QPen(color, 1))
                    painter.drawText(QPointF(x, y), char)
                    continue
                green = int(128 + fade * 100)
                alpha = int((36 + fade * 184) * flicker)
                painter.setPen(QPen(QColor(18, green, 72, alpha), 1))
                painter.drawText(QPointF(x, y), char)

    def _draw_scanlines(self, painter: QPainter, width: int, height: int) -> None:
        painter.setPen(QPen(QColor(0, 0, 0, 46), 1))
        for y in range(0, height, 4):
            painter.drawLine(0, y, width, y)

        sweep_y = int((self._tick_count * 3) % max(1, height))
        painter.setPen(QPen(QColor(99, 255, 144, 36), 1))
        painter.drawLine(0, sweep_y, width, sweep_y)

    def _draw_matrix_frame(self, painter: QPainter, width: int, height: int) -> None:
        margin = 18
        frame = QRectF(margin, margin, width - margin * 2, height - margin * 2)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(0, 255, 116, 132), 1.2))
        painter.drawRect(frame)

        painter.setFont(QFont("Consolas", 11, QFont.Bold))
        painter.setPen(QPen(QColor(154, 255, 185, 230), 1))
        header = QRectF(width * 0.33, 24, width * 0.34, 34)
        painter.fillRect(header, QColor(0, 0, 0, 216))
        painter.drawRect(header)
        painter.drawText(header, Qt.AlignCenter, "FZASTRO MATRIX IDLE MODE")

        painter.setFont(QFont("Consolas", 9, QFont.Medium))
        painter.setPen(QPen(QColor(88, 255, 140, 190), 1))
        painter.drawText(
            QRectF(28, height - 36, 360, 18),
            Qt.AlignLeft,
            "CODE RAIN: ACTIVE · BLACK BACKDROP: TRUE",
        )
        painter.drawText(
            QRectF(width - 430, height - 36, 402, 18),
            Qt.AlignRight,
            "INPUT RESTORES WORKSPACE · LOOP: 65 ms",
        )
