"""Idle Matrix-style code-rain overlay for the main FZAstro window."""

from __future__ import annotations

import gc
import math
import random
import weakref
from collections import deque

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QStaticText
from PySide6.QtWidgets import QApplication, QWidget

try:  # Prefer a GPU-backed paint device when Qt/OpenGL is available.
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
except Exception:  # pragma: no cover - optional Qt module on some installs
    QOpenGLWidget = None

_OverlayBaseWidget = QOpenGLWidget or QWidget
_OPENGL_ACCELERATED = QOpenGLWidget is not None

try:
    from shiboken6 import isValid as _qt_is_valid
except Exception:  # pragma: no cover - depends on PySide install shape
    _qt_is_valid = None


def _is_qt_valid(obj) -> bool:
    """Return false for deleted PySide wrappers before touching native Qt."""

    if obj is None:
        return False
    if _qt_is_valid is None:
        return True
    try:
        return bool(_qt_is_valid(obj))
    except Exception:
        return False


class _IdleActivityFilter(QObject):
    """Small QObject event filter that avoids using the QWidget as the filter."""

    def __init__(self, overlay: "IdleStarsOverlay") -> None:
        super().__init__()
        self._overlay_ref = weakref.ref(overlay)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override name
        overlay = self._overlay_ref()
        if not _is_qt_valid(overlay):
            return False
        try:
            overlay._handle_activity_event(event)
        except RuntimeError:
            return False
        except Exception:
            return False
        return False


class IdleStarsOverlay(_OverlayBaseWidget):
    """Low-cost idle screensaver with black-background code rain.

    The overlay is passive: it appears only after inactivity, ignores mouse
    events so the first user action reaches the normal UI, and hides as soon as
    any keyboard, mouse, wheel, or touch activity is seen by the application.
    The global activity filter is a separate QObject so teardown does not leave
    QApplication pointing at a native QWidget being destroyed.
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

    _GLYPHS = (
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "FZASTROAI"
        # Half-width katakana gives the classic Matrix texture.  Greek glyphs
        # add a more astronomy/ancient-notation feel without changing runtime
        # cost because each character is cached once as QStaticText.
        "ﾊﾐﾋｰｳｼﾅﾓﾆｻﾜﾂｵﾘｱﾎﾃﾏｹﾒｴｶｷﾑﾕﾗｾﾈｽﾀﾇﾍ"
        "アイウエオカキクケコサシスセソタチツテトナニヌネノ"
        "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
        "αβγδεζηθικλμνξοπρστυφχψω"
        "<>[]{}#$:/\\+-*=λπΩΣΔθφψ∞░▒▓"
    )

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
        self._elapsed_seconds = 0.0
        self._elapsed_timer = QElapsedTimer()
        # Screensaver profile: sustained low-load idle display.  Do not push
        # 60 FPS here; the overlay is a screensaver and must stay below normal
        # app/benchmark workloads.  A 24 FPS target avoids GPU spikes on long
        # idle sessions while still reading as smooth code rain.
        self._frame_interval_ms = 42
        self._target_fps = 24.0
        self._frame_budget_ms = 13.5
        self._last_tick_ms: int | None = None
        self._fps_samples: deque[float] = deque(maxlen=45)
        self._fps = 0.0
        self._last_frame_cost_ms = 0.0
        self._last_delta_ms = self._frame_interval_ms
        self._adaptive_skip_tier = 0
        self._adaptive_relax_until = 0.0
        self._frame_cost_timer = QElapsedTimer()
        self._gc_was_enabled: bool | None = None
        self._font_cache: dict[tuple[str, int, int], QFont] = {}
        self._glyph_cache: dict[tuple[int, str], QStaticText] = {}
        self._glyph_lookup_cache: dict[int, dict[str, QStaticText]] = {}
        self._tail_palette: dict[tuple[int, int], tuple[QColor, ...]] = {}
        self._color_cache: dict[tuple[int, int, int, int], QColor] = {}
        self._telemetry_cache: dict[str, float | None] = {
            "gpu": None,
            "vram": None,
            "cpu": None,
            "ram": None,
        }
        self._telemetry_refresh_at = -1.0
        self._columns = self._make_columns()
        self._activity_filter: _IdleActivityFilter | None = None
        self._activity_application: QApplication | None = None

        if _OPENGL_ACCELERATED:
            try:
                self.setUpdateBehavior(QOpenGLWidget.NoPartialUpdate)  # type: ignore[union-attr]
            except Exception:
                pass

        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._show_overlay)

        self._animation_timer = QTimer(self)
        self._animation_timer.setTimerType(Qt.PreciseTimer)
        self._animation_timer.setInterval(self._frame_interval_ms)
        self._animation_timer.timeout.connect(self._tick)

        self.destroyed.connect(lambda *_args: self._uninstall_activity_filter())
        self.hide()
        self.reset_idle_timer()

    def install_on(self, application: QApplication | None = None) -> None:
        """Install the global activity filter used to hide/reset the overlay."""

        app = application or QApplication.instance()
        if app is None or self._activity_filter is not None:
            return
        try:
            activity_filter = _IdleActivityFilter(self)
            activity_filter.setParent(app)
            app.installEventFilter(activity_filter)
            self._activity_filter = activity_filter
            self._activity_application = app
        except Exception:
            self._activity_filter = None
            self._activity_application = None

    def _uninstall_activity_filter(self) -> None:
        app = self._activity_application
        activity_filter = self._activity_filter
        self._activity_application = None
        self._activity_filter = None
        try:
            if app is not None and activity_filter is not None:
                app.removeEventFilter(activity_filter)
                activity_filter.setParent(None)
                activity_filter.deleteLater()
        except Exception:
            return

    def _enter_animation_mode(self) -> None:
        """Reduce periodic maintenance spikes while the fullscreen rain is visible."""

        if self._gc_was_enabled is not None:
            return
        try:
            self._gc_was_enabled = gc.isenabled()
            # Most of the screensaver cost is paint-loop churn.  A cyclic GC
            # pass during animation is visible as a deep dip every few seconds,
            # so run a light gen-0 sweep up front and pause cyclic GC until the
            # overlay hides.  Reference counting still frees normal objects.
            gc.collect(0)
            if self._gc_was_enabled:
                gc.disable()
        except Exception:
            self._gc_was_enabled = None

    def _leave_animation_mode(self) -> None:
        """Restore normal Python maintenance once the screensaver stops."""

        gc_was_enabled = self._gc_was_enabled
        self._gc_was_enabled = None
        if gc_was_enabled is None:
            return
        try:
            if gc_was_enabled and not gc.isenabled():
                gc.enable()
            if gc_was_enabled:
                QTimer.singleShot(300, lambda: gc.collect(0))
        except Exception:
            return

    def _cached_font(self, family: str, size: int, weight: int = QFont.Normal) -> QFont:
        key = (family, int(size), int(weight))
        cached = self._font_cache.get(key)
        if cached is None:
            cached = QFont(family, size, weight)
            self._font_cache[key] = cached
        return cached

    def reset_idle_timer(self) -> None:
        """Restart inactivity tracking without changing other application state."""

        try:
            if _is_qt_valid(self):
                self._idle_timer.start(self._idle_ms)
        except RuntimeError:
            return

    def _handle_activity_event(self, event) -> None:
        if event is None or event.type() not in self.ACTIVITY_EVENTS:
            return
        if self.isVisible():
            self.hide()
            self._animation_timer.stop()
        self.reset_idle_timer()

    def closeEvent(self, event):  # noqa: N802 - Qt override name
        self._animation_timer.stop()
        self._idle_timer.stop()
        self._leave_animation_mode()
        self._uninstall_activity_filter()
        super().closeEvent(event)

    def hideEvent(self, event):  # noqa: N802 - Qt override name
        try:
            self._animation_timer.stop()
            self._elapsed_timer.invalidate()
            self._leave_animation_mode()
        except RuntimeError:
            pass
        super().hideEvent(event)

    def resizeEvent(self, event):  # noqa: N802 - Qt override name
        super().resizeEvent(event)
        self._columns = self._make_columns()

    def _show_overlay(self) -> None:
        parent = self.parentWidget()
        if parent is None or not _is_qt_valid(parent) or not parent.isVisible():
            self.reset_idle_timer()
            return
        self.setGeometry(parent.rect())
        self.raise_()
        self.show()
        self._elapsed_seconds = 0.0
        self._last_tick_ms = None
        self._fps_samples.clear()
        self._fps = 0.0
        self._elapsed_timer.restart()
        self._enter_animation_mode()
        if not self._animation_timer.isActive():
            self._animation_timer.start()

    def _tick(self) -> None:
        if not self.isVisible():
            self._animation_timer.stop()
            self._elapsed_timer.invalidate()
            return
        if not self._elapsed_timer.isValid():
            self._elapsed_timer.restart()
        elapsed_ms = int(self._elapsed_timer.elapsed())
        if self._last_tick_ms is not None:
            delta_ms = max(1, elapsed_ms - self._last_tick_ms)
            self._last_delta_ms = delta_ms
            self._fps_samples.append(1000.0 / delta_ms)
            self._fps = sum(self._fps_samples) / max(1, len(self._fps_samples))
        self._last_tick_ms = elapsed_ms
        self._elapsed_seconds = max(0.0, elapsed_ms / 1000.0)
        if self._last_delta_ms > self._frame_interval_ms * 2.6:
            self._adaptive_skip_tier = min(3, self._adaptive_skip_tier + 1)
            self._adaptive_relax_until = self._elapsed_seconds + 8.0
        elif (
            self._adaptive_skip_tier
            and self._elapsed_seconds > self._adaptive_relax_until
        ):
            self._adaptive_skip_tier = max(0, self._adaptive_skip_tier - 1)
            self._adaptive_relax_until = self._elapsed_seconds + 4.0
        self._phase = (self._elapsed_seconds * 1.65) % (math.pi * 2.0)
        self.update()

    def _make_columns(self) -> tuple[dict[str, object], ...]:
        rng = random.Random(2106)
        width = max(900, self.width() or 900)
        height = max(600, self.height() or 600)

        # Screensaver Eco profile: sparse enough to keep idle GPU load low,
        # dense enough to remain clearly Matrix-like.  The previous profile drew
        # too many columns and dim ambient glyphs, which made periodic frame
        # stalls visible on some GPUs.
        cell = 21 if width < 1400 else 24
        count = min(92, max(42, int(width // cell) + 4))
        estimated_rows = max(48, int(height // 14) + 24)
        columns: list[dict[str, object]] = []
        for index in range(count):
            # Long trails are intentional: they keep every stream visible until
            # the tail has travelled fully past the bottom instead of popping
            # out mid-screen while the head wraps back to the top.
            trail_rows = rng.randint(
                max(38, int(estimated_rows * 0.9)),
                max(58, int(estimated_rows * 1.12)),
            )
            stream_count = rng.choice((1, 1, 1, 1, 2))
            head_seeds = tuple(
                ((slot + rng.uniform(-0.08, 0.08)) / stream_count) % 1.0
                for slot in range(stream_count)
            )
            text = tuple(rng.choice(self._GLYPHS) for _ in range(estimated_rows * 4))
            columns.append(
                {
                    "x": index * cell + rng.uniform(-1.5, 1.5),
                    "offset": rng.uniform(0.0, height + trail_rows * 18.0),
                    "speed": rng.uniform(44.0, 96.0),
                    "trail_rows": trail_rows,
                    "text": text,
                    "phase": rng.random() * math.pi * 2.0,
                    "glyph_rate": rng.uniform(7.0, 16.0),
                    "base_alpha": rng.randint(8, 18),
                    "brightness": rng.uniform(0.78, 1.05),
                    # Evenly staggered heads avoid a visible blank wave when a
                    # stream loops.  Random-only heads can cluster, which makes
                    # the overlay look like it pauses or leaves a horizontal gap.
                    "heads": head_seeds,
                    "cell": cell,
                    # Ambient rows are intentionally very sparse.  The visible
                    # rain comes from long trails, while low-alpha background
                    # glyphs are budgeted so the screensaver does not become a
                    # GPU load test.
                    "ambient_step": rng.choice((9, 10, 11, 12)),
                    "ambient_phase": rng.randint(0, 11),
                }
            )
        return tuple(columns)

    def paintEvent(self, event):  # noqa: N802 - Qt override name
        self._frame_cost_timer.restart()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        width = max(1, self.width())
        height = max(1, self.height())

        self._draw_black_backdrop(painter, width, height)
        self._draw_code_rain(painter, width, height)
        self._draw_performance_hud(painter, width, height)

        painter.end()
        self._last_frame_cost_ms = self._frame_cost_timer.nsecsElapsed() / 1_000_000.0
        self._apply_frame_budget_guard()

    def _draw_black_backdrop(self, painter: QPainter, width: int, height: int) -> None:
        """Paint a true opaque black background before the code rain."""

        painter.fillRect(self.rect(), QColor(0, 0, 0, 255))

    def _apply_frame_budget_guard(self) -> None:
        """Keep the screensaver in a stable low-load profile during long idle runs."""

        if self._last_frame_cost_ms > self._frame_budget_ms:
            self._adaptive_skip_tier = min(4, self._adaptive_skip_tier + 1)
            self._adaptive_relax_until = self._elapsed_seconds + 12.0
        elif (
            self._adaptive_skip_tier
            and self._elapsed_seconds > self._adaptive_relax_until
        ):
            self._adaptive_skip_tier = max(0, self._adaptive_skip_tier - 1)
            self._adaptive_relax_until = self._elapsed_seconds + 6.0

    def _draw_code_rain(self, painter: QPainter, width: int, height: int) -> None:
        font_size = 10 if width < 1200 else 11
        painter.setFont(self._cached_font("Cascadia Mono", font_size, QFont.Medium))
        row_step = font_size + 2
        visible_rows = max(1, int(height // row_step) + 8)
        glyph_cursor = int(self._elapsed_seconds * 11.0)
        static_glyphs = self._static_glyphs(font_size)
        tail_palette = self._code_rain_palette(font_size)

        for column in self._columns:
            x = float(column["x"])
            speed = float(column["speed"])
            text = column["text"]
            phase = float(column["phase"])
            offset = float(column["offset"])
            glyph_rate = float(column.get("glyph_rate", 9.0))
            base_alpha = int(column.get("base_alpha", 28))
            brightness = float(column.get("brightness", 1.0))
            trail_rows = int(column.get("trail_rows", max(24, visible_rows // 2)))
            heads = column.get("heads", (0.0,)) or (0.0,)
            ambient_step = max(
                1, int(column.get("ambient_step", 10)) + self._adaptive_skip_tier * 2
            )
            ambient_phase = int(column.get("ambient_phase", 0))

            flicker = 0.76 + 0.24 * ((math.sin(self._phase * 2.4 + phase) + 1.0) / 2.0)
            column_cursor = int(self._elapsed_seconds * glyph_rate + offset)
            row_scroll = (self._elapsed_seconds * speed + offset) % row_step
            # Seamless loop: the head restarts at the top exactly when the
            # previous tail has cleared the bottom.  No extra wrap gap is used,
            # because it produced a visible blank band after several seconds.
            head_span = height + row_step * trail_rows
            head_ys = tuple(
                (self._elapsed_seconds * speed + offset + float(head_seed) * head_span)
                % head_span
                for head_seed in heads
            )

            for row in range(-3, visible_rows):
                y = row * row_step + row_scroll
                if y < -row_step or y > height + row_step:
                    continue

                trail_strength = 0.0
                is_head = False
                for head_y in head_ys:
                    distance_rows = (head_y - y) / row_step
                    if -0.35 <= distance_rows <= 0.55:
                        trail_strength = 1.0
                        is_head = True
                        break
                    if 0.55 < distance_rows <= trail_rows:
                        fade = 1.0 - (distance_rows / max(1, trail_rows))
                        trail_strength = max(trail_strength, fade**1.35)

                if trail_strength <= 0.0:
                    if (row + ambient_phase) % ambient_step:
                        continue
                elif (
                    self._adaptive_skip_tier
                    and trail_strength < 0.16
                    and (row + ambient_phase) % (2 + self._adaptive_skip_tier)
                ):
                    continue

                char = text[(glyph_cursor + column_cursor + row) % len(text)]
                glyph = static_glyphs.get(char)
                if glyph is None:
                    continue

                if is_head:
                    color = tail_palette[-1]
                    alpha = int(color.alpha() * flicker)
                elif trail_strength > 0.0:
                    palette_index = max(
                        1,
                        min(
                            len(tail_palette) - 2,
                            int(trail_strength * (len(tail_palette) - 2)),
                        ),
                    )
                    color = tail_palette[palette_index]
                    alpha = int((44 + trail_strength * 190) * flicker * brightness)
                else:
                    color = tail_palette[0]
                    alpha = int(base_alpha * flicker)

                painter.setPen(self._cached_color(color, alpha))
                painter.drawStaticText(int(x), int(y), glyph)

    def _cached_color(self, color: QColor, alpha: int) -> QColor:
        bucket_alpha = max(10, min(248, int(alpha / 8) * 8))
        key = (color.red(), color.green(), color.blue(), bucket_alpha)
        cached = self._color_cache.get(key)
        if cached is None:
            cached = QColor(key[0], key[1], key[2], key[3])
            self._color_cache[key] = cached
        return cached

    def _draw_performance_hud(self, painter: QPainter, width: int, height: int) -> None:
        telemetry = self._read_parent_telemetry()
        panel_width = 260
        panel_height = 118
        x = max(18, width - panel_width - 24)
        y = 22
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QColor(84, 255, 150, 90))
        painter.setBrush(QColor(0, 18, 8, 190))
        painter.drawRoundedRect(x, y, panel_width, panel_height, 14, 14)

        accent = QColor(122, 255, 170, 210)
        dim = QColor(72, 140, 92, 160)
        painter.setPen(accent)
        painter.setFont(self._cached_font("Cascadia Mono", 9, QFont.DemiBold))
        backend = "GPU RENDER · ECO" if _OPENGL_ACCELERATED else "CPU FALLBACK · ECO"
        painter.drawText(x + 16, y + 22, f"MATRIX ENGINE · {backend}")

        fps_value = self._fps if self._fps > 0.0 else self._target_fps
        self._draw_metric_bar(
            painter,
            x + 16,
            y + 38,
            panel_width - 32,
            "FPS",
            fps_value,
            self._target_fps,
            f"{fps_value:04.1f}",
        )
        self._draw_metric_bar(
            painter,
            x + 16,
            y + 64,
            panel_width - 32,
            "GPU",
            telemetry.get("gpu"),
            100.0,
            self._format_metric_value(telemetry.get("gpu"), "%"),
        )
        self._draw_metric_bar(
            painter,
            x + 16,
            y + 90,
            panel_width - 32,
            "VRAM",
            telemetry.get("vram"),
            100.0,
            self._format_metric_value(telemetry.get("vram"), "%"),
        )

        painter.setPen(dim)
        painter.setFont(self._cached_font("Cascadia Mono", 7, QFont.Normal))
        painter.drawText(
            x + 16,
            y + panel_height - 8,
            f"FRAME {self._last_frame_cost_ms:04.1f} MS · ECO Q{self._adaptive_skip_tier} · LOW LOAD GREEK",
        )
        painter.restore()

    def _draw_metric_bar(
        self,
        painter: QPainter,
        x: int,
        y: int,
        width: int,
        label: str,
        value: float | None,
        maximum: float,
        value_text: str,
    ) -> None:
        label_width = 40
        bar_x = x + label_width + 8
        bar_width = max(20, width - label_width - 54)
        bar_height = 9
        painter.setPen(QColor(148, 255, 180, 188))
        painter.setFont(self._cached_font("Cascadia Mono", 8, QFont.DemiBold))
        painter.drawText(x, y + 10, label)
        painter.setPen(QColor(48, 130, 72, 110))
        painter.setBrush(QColor(4, 34, 13, 170))
        painter.drawRoundedRect(bar_x, y + 2, bar_width, bar_height, 4, 4)
        ratio = (
            0.0
            if value is None or maximum <= 0
            else max(0.0, min(1.0, value / maximum))
        )
        fill_width = int(bar_width * ratio)
        if fill_width > 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(96, 214, 118, 225))
            painter.drawRoundedRect(bar_x, y + 2, fill_width, bar_height, 4, 4)
        painter.setPen(QColor(214, 255, 220, 210))
        painter.drawText(bar_x + bar_width + 8, y + 10, value_text)

    def _read_parent_telemetry(self) -> dict[str, float | None]:
        if self._elapsed_seconds < self._telemetry_refresh_at:
            return self._telemetry_cache
        self._telemetry_refresh_at = self._elapsed_seconds + 3.0
        gpu_text = ""
        system_text = ""
        try:
            window = self.window()
            gpu_label = getattr(window, "gpu_label", None)
            system_label = getattr(window, "system_label", None)
            if gpu_label is not None:
                gpu_text = gpu_label.text()
            if system_label is not None:
                system_text = system_label.text()
        except Exception:
            pass
        self._telemetry_cache = {
            "gpu": self._extract_percent_after_label(gpu_text, "GPU"),
            "vram": self._extract_vram_percent(gpu_text),
            "cpu": self._extract_percent_after_label(system_text, "CPU"),
            "ram": self._extract_ram_percent(system_text),
        }
        return self._telemetry_cache

    def _extract_percent_after_label(self, text: str, label: str) -> float | None:
        marker = f"{label} "
        start = text.find(marker)
        if start < 0:
            return None
        remainder = text[start + len(marker) :]
        end = remainder.find("%")
        if end < 0:
            return None
        try:
            return max(0.0, min(100.0, float(remainder[:end].strip())))
        except ValueError:
            return None

    def _extract_vram_percent(self, text: str) -> float | None:
        marker = "VRAM "
        start = text.find(marker)
        if start < 0:
            return None
        remainder = text[start + len(marker) :]
        gb_index = remainder.find(" GB")
        if gb_index >= 0:
            remainder = remainder[:gb_index]
        if "/" not in remainder:
            return None
        used_text, total_text = remainder.split("/", 1)
        try:
            used = float(used_text.strip())
            total = float(total_text.strip())
        except ValueError:
            return None
        if total <= 0:
            return None
        return max(0.0, min(100.0, (used / total) * 100.0))

    def _extract_ram_percent(self, text: str) -> float | None:
        marker = "RAM "
        start = text.find(marker)
        if start < 0:
            return None
        remainder = text[start + len(marker) :]
        gb_index = remainder.find(" GB")
        if gb_index >= 0:
            remainder = remainder[:gb_index]
        if "/" not in remainder:
            return None
        used_text, total_text = remainder.split("/", 1)
        try:
            used = float(used_text.strip())
            total = float(total_text.strip())
        except ValueError:
            return None
        if total <= 0:
            return None
        return max(0.0, min(100.0, (used / total) * 100.0))

    def _format_metric_value(self, value: float | None, suffix: str) -> str:
        if value is None:
            return "--"
        return f"{value:02.0f}{suffix}"

    def _static_glyphs(self, font_size: int) -> dict[str, QStaticText]:
        cached_lookup = self._glyph_lookup_cache.get(font_size)
        if cached_lookup is not None:
            return cached_lookup
        glyphs = set(self._GLYPHS)
        cache = self._glyph_cache
        lookup: dict[str, QStaticText] = {}
        for char in glyphs:
            key = (font_size, char)
            if key not in cache:
                static_text = QStaticText(char)
                static_text.setPerformanceHint(QStaticText.AggressiveCaching)
                cache[key] = static_text
            lookup[char] = cache[key]
        self._glyph_lookup_cache[font_size] = lookup
        return lookup

    def _code_rain_palette(self, font_size: int) -> tuple[QColor, ...]:
        key = (font_size, 12)
        if key not in self._tail_palette:
            colors: list[QColor] = []
            for step in range(12):
                fade = step / 11.0
                colors.append(
                    QColor(
                        int(6 + fade * 42),
                        int(96 + fade * 154),
                        int(38 + fade * 92),
                        int(22 + fade * 196),
                    )
                )
            colors.append(QColor(238, 255, 238, 246))
            self._tail_palette[key] = tuple(colors)
        return self._tail_palette[key]
