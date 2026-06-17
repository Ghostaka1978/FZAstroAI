from __future__ import annotations

import html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..astro_tools.seeing_data import (
    SEEING_PROVIDER_HYBRID,
    score_label,
)
from ..astro_tools.sky_quality import (
    bortle_from_sqm,
    sky_brightness_from_sqm,
    sqm_from_bortle,
)
from ..workers.seeing_worker import SeeingWorker
from ..workers.sky_quality_worker import SkyQualityFetchWorker
from .astro_location_dialog import choose_astro_location
from .window_utils import apply_window_defaults


class CloudCoverageWidget(QWidget):
    """Focused cloud / astronomical-darkness / Moon timeline for the SEEING window."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict[str, Any]] = []
        self.selected_index = -1
        self.setObjectName("seeingCloudTimeline")
        self.setMinimumHeight(180)

    def set_rows(self, rows: list[dict[str, Any]] | None):
        self.rows = [dict(row) for row in (rows or [])]
        self.selected_index = 0 if self.rows else -1
        self.update()

    def set_selected_index(self, index: int):
        self.selected_index = int(index)
        self.update()

    def _cloud_color(self, pct: int) -> QColor:
        if pct <= 20:
            return QColor("#2fb36b")
        if pct <= 45:
            return QColor("#b6a747")
        if pct <= 70:
            return QColor("#b6793a")
        return QColor("#9aa5b1")

    def _lane_color(self, active: bool | None, active_color: str) -> QColor:
        if active is True:
            return QColor(active_color)
        if active is False:
            return QColor("#26313d")
        return QColor("#3a4550")

    def paintEvent(self, event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.fillRect(rect, QColor("#0f1318"))
        painter.setPen(QPen(QColor("#29313b"), 1))
        painter.drawRoundedRect(rect, 10, 10)

        if not self.rows:
            painter.setPen(QColor("#8f9ba8"))
            painter.drawText(
                rect,
                Qt.AlignCenter,
                "Cloud, astronomical darkness, and Moon timeline will appear after loading.",
            )
            return

        rows = self.rows[:56]
        count = len(rows)
        left = 86
        right = 18
        top = 18
        width = max(1, rect.width() - left - right)
        step = width / max(1, count)
        cell_width = max(3.0, step - 2.0)

        dark_y = top + 24
        moon_y = dark_y + 30
        cloud_y = moon_y + 34
        cloud_h = max(42, rect.height() - cloud_y - 34)
        cloud_bottom = cloud_y + cloud_h

        painter.setPen(QColor("#a9b7c7"))
        painter.drawText(
            QRectF(12, dark_y - 3, 64, 18),
            Qt.AlignRight | Qt.AlignVCenter,
            "Astro dark",
        )
        painter.drawText(
            QRectF(12, moon_y - 3, 64, 18), Qt.AlignRight | Qt.AlignVCenter, "Moon"
        )
        painter.drawText(
            QRectF(12, cloud_y - 3, 64, 18), Qt.AlignRight | Qt.AlignVCenter, "Cloud"
        )

        painter.setPen(QColor("#7f8fa1"))
        painter.drawText(
            QRectF(12, cloud_y + 2, 64, 16), Qt.AlignRight | Qt.AlignVCenter, "0%"
        )
        painter.drawText(
            QRectF(12, cloud_bottom - 16, 64, 16),
            Qt.AlignRight | Qt.AlignVCenter,
            "100%",
        )

        painter.setPen(QPen(QColor("#26313d"), 1))
        for y in (
            dark_y + 18,
            moon_y + 18,
            cloud_y,
            cloud_y + cloud_h * 0.5,
            cloud_bottom,
        ):
            painter.drawLine(left, int(y), left + width, int(y))

        painter.setPen(QColor("#9fb8d4"))
        painter.drawText(
            QRectF(left, 4, width, 16),
            Qt.AlignRight | Qt.AlignVCenter,
            "Blue = astronomical darkness   Gold = moon up   Cloud bar = cloud cover",
        )

        for index, row in enumerate(rows):
            x = left + index * step + 1.0
            pct = max(0, min(100, int(row.get("cloud_mid_pct") or 0)))
            cloud_height = max(2.0, cloud_h * (pct / 100.0))
            selected = index == self.selected_index

            if selected:
                painter.fillRect(
                    QRectF(
                        x - 2, dark_y - 8, cell_width + 4, cloud_bottom - dark_y + 12
                    ),
                    QColor(28, 45, 63, 155),
                )

            dark_color = self._lane_color(row.get("astro_dark"), "#3296dc")
            moon_up = row.get("moon_up")
            moon_color = self._lane_color(moon_up, "#c5a149")

            painter.fillRect(QRectF(x, dark_y, cell_width, 14), dark_color)
            painter.fillRect(QRectF(x, moon_y, cell_width, 14), moon_color)
            painter.fillRect(
                QRectF(x, cloud_bottom - cloud_height, cell_width, cloud_height),
                self._cloud_color(pct),
            )

            if selected:
                painter.setPen(QPen(QColor("#d8e8ff"), 2))
                painter.drawRect(
                    QRectF(
                        x - 2, dark_y - 8, cell_width + 4, cloud_bottom - dark_y + 12
                    )
                )
                painter.setPen(QPen(QColor("#26313d"), 1))

            if index % max(1, count // 7) == 0 or index == count - 1:
                painter.setPen(QColor("#95a4b4"))
                painter.drawText(
                    QRectF(x - 24, cloud_bottom + 7, 66, 16),
                    Qt.AlignCenter,
                    str(row.get("hour_label") or ""),
                )
                painter.setPen(QPen(QColor("#26313d"), 1))


class Seeing24HourGraphWidget(QWidget):
    """Detailed 24-hour SEEING record graph for cloud, Moon, darkness, and seeing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.block: dict[str, Any] = {}
        self.selected_local_iso = ""
        self.setObjectName("seeing24HourGraph")
        self.setMinimumHeight(230)

    def set_block(
        self, block: dict[str, Any] | None, selected_local_iso: str | None = None
    ):
        self.block = dict(block or {})
        self.selected_local_iso = str(
            selected_local_iso or self.selected_local_iso or ""
        )
        self.update()

    def set_selected_local_iso(self, value: Any):
        self.selected_local_iso = str(value or "")
        self.update()

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    @staticmethod
    def _quality_from_code(value: Any, max_code: int) -> int:
        try:
            code = int(value)
        except Exception:
            return 0
        if code <= 0:
            return 0
        return max(0, min(100, round(100 - ((code - 1) / max(1, max_code - 1)) * 100)))

    @staticmethod
    def _cloud_color(pct: Any) -> QColor:
        try:
            value = int(pct)
        except Exception:
            value = 100
        if value <= 20:
            return QColor("#2fb36b")
        if value <= 45:
            return QColor("#b6a747")
        if value <= 70:
            return QColor("#b6793a")
        return QColor("#9aa5b1")

    @staticmethod
    def _seeing_color(quality: int) -> QColor:
        if quality >= 75:
            return QColor("#2fb36b")
        if quality >= 55:
            return QColor("#b6a747")
        if quality >= 35:
            return QColor("#b6793a")
        return QColor("#9aa5b1")

    def paintEvent(self, event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.fillRect(rect, QColor("#0f1318"))
        painter.setPen(QPen(QColor("#29313b"), 1))
        painter.drawRoundedRect(rect, 10, 10)

        rows = (
            self.block.get("rows") if isinstance(self.block.get("rows"), list) else []
        )
        if not rows:
            painter.setPen(QColor("#8f9ba8"))
            painter.drawText(
                rect,
                Qt.AlignCenter,
                "Select a 24-hour record to show cloud, Moon, astronomical darkness, and seeing.",
            )
            return

        start_dt = self._parse_dt(self.block.get("start_iso"))
        end_dt = self._parse_dt(self.block.get("end_iso"))
        if start_dt is None:
            first_dt = self._parse_dt(rows[0].get("local_iso"))
            start_dt = first_dt or datetime.now()
        if end_dt is None:
            end_dt = start_dt + timedelta(hours=24)
        total_seconds = max(1.0, (end_dt - start_dt).total_seconds())

        left = 104
        right = 18
        top = 26
        bottom = 34
        width = max(1.0, rect.width() - left - right)
        chart_bottom = rect.height() - bottom
        cloud_y = top + 34
        cloud_h = max(54, min(86, int(rect.height() * 0.28)))
        seeing_y = cloud_y + cloud_h + 24
        seeing_h = max(42, min(62, int(rect.height() * 0.20)))
        dark_y = seeing_y + seeing_h + 22
        lane_h = 16
        moon_y = dark_y + lane_h + 11

        painter.setPen(QColor("#dce9f6"))
        title = str(self.block.get("label") or "24-hour imaging planner")
        painter.drawText(
            QRectF(left, 7, width * 0.62, 18), Qt.AlignLeft | Qt.AlignVCenter, title
        )
        painter.setPen(QColor("#9fb8d4"))
        painter.drawText(
            QRectF(left + width * 0.36, 7, width * 0.64, 18),
            Qt.AlignRight | Qt.AlignVCenter,
            "Cloud bars · Seeing dots/line · Blue astro dark · Gold Moon up",
        )

        # Lane labels.
        painter.setPen(QColor("#a9b7c7"))
        painter.drawText(
            QRectF(12, cloud_y + cloud_h * 0.5 - 10, 80, 18),
            Qt.AlignRight | Qt.AlignVCenter,
            "Cloud cover",
        )
        painter.drawText(
            QRectF(12, seeing_y + seeing_h * 0.5 - 10, 80, 18),
            Qt.AlignRight | Qt.AlignVCenter,
            "Seeing",
        )
        painter.drawText(
            QRectF(12, dark_y - 1, 80, 18),
            Qt.AlignRight | Qt.AlignVCenter,
            "Astro dark",
        )
        painter.drawText(
            QRectF(12, moon_y - 1, 80, 18), Qt.AlignRight | Qt.AlignVCenter, "Moon up"
        )

        painter.setPen(QColor("#7f8fa1"))
        painter.drawText(
            QRectF(24, cloud_y - 2, 68, 16), Qt.AlignRight | Qt.AlignVCenter, "0%"
        )
        painter.drawText(
            QRectF(24, cloud_y + cloud_h - 16, 68, 16),
            Qt.AlignRight | Qt.AlignVCenter,
            "100%",
        )
        painter.drawText(
            QRectF(24, seeing_y - 2, 68, 16), Qt.AlignRight | Qt.AlignVCenter, "best"
        )
        painter.drawText(
            QRectF(24, seeing_y + seeing_h - 16, 68, 16),
            Qt.AlignRight | Qt.AlignVCenter,
            "poor",
        )

        # Background lanes and guides.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#111923"))
        painter.drawRoundedRect(QRectF(left, cloud_y, width, cloud_h), 4, 4)
        painter.drawRoundedRect(QRectF(left, seeing_y, width, seeing_h), 4, 4)
        painter.fillRect(QRectF(left, dark_y, width, lane_h), QColor("#26313d"))
        painter.fillRect(QRectF(left, moon_y, width, lane_h), QColor("#26313d"))

        painter.setPen(QPen(QColor("#26313d"), 1))
        for y in (
            cloud_y,
            cloud_y + cloud_h * 0.25,
            cloud_y + cloud_h * 0.5,
            cloud_y + cloud_h * 0.75,
            cloud_y + cloud_h,
            seeing_y,
            seeing_y + seeing_h * 0.5,
            seeing_y + seeing_h,
            dark_y + lane_h,
            moon_y + lane_h,
        ):
            painter.drawLine(left, int(y), left + width, int(y))
        for hour in range(0, 25, 3):
            x = left + width * (hour / 24.0)
            painter.drawLine(int(x), cloud_y - 8, int(x), moon_y + lane_h + 8)
            label_dt = start_dt + timedelta(hours=hour)
            painter.setPen(QColor("#95a4b4"))
            painter.drawText(
                QRectF(x - 28, chart_bottom + 4, 56, 14),
                Qt.AlignCenter,
                label_dt.strftime("%H:%M"),
            )
            painter.setPen(QPen(QColor("#26313d"), 1))

        default_span = width * (3.0 / 24.0) * 0.82
        selected_center: float | None = None
        seeing_points: list[tuple[float, float, QColor, bool]] = []
        best_score = max((int(row.get("score") or 0) for row in rows), default=0)

        for row in rows:
            local_dt = self._parse_dt(row.get("local_iso"))
            if local_dt is None:
                continue
            center = left + width * max(
                0.0, min(1.0, (local_dt - start_dt).total_seconds() / total_seconds)
            )
            bar_w = max(9.0, min(default_span, width / max(4, len(rows)) * 0.78))
            x = center - bar_w / 2.0
            selected = str(row.get("local_iso") or "") == self.selected_local_iso
            if selected:
                selected_center = center

            cloud_pct = max(0, min(100, int(row.get("cloud_mid_pct") or 0)))
            cloud_bar_h = max(2.0, cloud_h * (cloud_pct / 100.0))
            painter.fillRect(
                QRectF(x, cloud_y + cloud_h - cloud_bar_h, bar_w, cloud_bar_h),
                self._cloud_color(cloud_pct),
            )

            # Best score gets a subtle marker at the top of the cloud lane.
            try:
                row_score = int(row.get("score") or 0)
            except Exception:
                row_score = 0
            if row_score == best_score and best_score > 0:
                painter.fillRect(QRectF(x, cloud_y - 5, bar_w, 3), QColor("#d8e8ff"))

            seeing_quality = self._quality_from_code(row.get("seeing_code"), 8)
            point_y = seeing_y + seeing_h - (seeing_h * (seeing_quality / 100.0))
            seeing_points.append(
                (center, point_y, self._seeing_color(seeing_quality), selected)
            )

            if row.get("astro_dark") is True:
                painter.fillRect(QRectF(x, dark_y, bar_w, lane_h), QColor("#3296dc"))
            if row.get("moon_up") is True:
                painter.fillRect(QRectF(x, moon_y, bar_w, lane_h), QColor("#c5a149"))

        # Draw seeing as a line/dot lane so it does not visually compete with cloud bars.
        if len(seeing_points) > 1:
            painter.setPen(QPen(QColor("#668fb8"), 2))
            for first, second in zip(seeing_points, seeing_points[1:]):
                painter.drawLine(
                    QPointF(first[0], first[1]), QPointF(second[0], second[1])
                )
        for x, y, color, selected in seeing_points:
            painter.setPen(QPen(QColor("#0f1318"), 2))
            painter.setBrush(color)
            radius = 5.0 if selected else 4.0
            painter.drawEllipse(QPointF(x, y), radius, radius)

        if selected_center is not None:
            painter.setPen(QPen(QColor("#d8e8ff"), 2))
            painter.drawLine(
                QPointF(selected_center, cloud_y - 9),
                QPointF(selected_center, moon_y + lane_h + 10),
            )
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(
                QRectF(
                    selected_center - 7,
                    cloud_y - 10,
                    14,
                    moon_y + lane_h - cloud_y + 20,
                ),
                5,
                5,
            )

        painter.setPen(QColor("#95a4b4"))
        painter.drawText(
            QRectF(left, chart_bottom + 18, width / 2, 14),
            Qt.AlignLeft | Qt.AlignVCenter,
            start_dt.strftime("%a %Y-%m-%d"),
        )
        painter.drawText(
            QRectF(left + width / 2, chart_bottom + 18, width / 2, 14),
            Qt.AlignRight | Qt.AlignVCenter,
            end_dt.strftime("%a %Y-%m-%d"),
        )


class SeeingNightPlannerWidget(QWidget):
    """Card-style weekly SEEING planner.

    The widget avoids a dense 24-column grid. Each record remains one exact
    24-hour period, but it is summarized as a readable day/night card with the
    three decision metrics astrophotographers usually scan first: cloud cover,
    seeing, and transparency. Clicking a card selects the best forecast point
    inside that 24-hour record and updates the table/details panel.
    """

    forecast_row_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.blocks: list[dict[str, Any]] = []
        self.selected_row_index = -1
        self._hit_regions: list[tuple[QRectF, int]] = []
        self.setObjectName("seeingNightPlanner")
        self.setMouseTracking(True)
        self.setMinimumHeight(420)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)

    def set_blocks(
        self, blocks: list[dict[str, Any]] | None, selected_row_index: int = -1
    ):
        self.blocks = [dict(block) for block in (blocks or [])]
        self.selected_row_index = int(selected_row_index)
        self._update_height()
        self.update()

    def set_selected_row_index(self, value: Any):
        try:
            self.selected_row_index = int(value)
        except Exception:
            self.selected_row_index = -1
        self.update()

    def _update_height(self):
        row_count = max(1, len(self.blocks))
        self.setMinimumHeight(44 + row_count * 112 + 18)

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    @staticmethod
    def _score_color(score: Any) -> QColor:
        try:
            value = int(score)
        except Exception:
            value = 0
        if value >= 80:
            return QColor("#38c875")
        if value >= 65:
            return QColor("#8bcf61")
        if value >= 50:
            return QColor("#e48b3c")
        if value >= 35:
            return QColor("#d36b4c")
        return QColor("#d95d72")

    @staticmethod
    def _quality_color(value: int) -> QColor:
        if value >= 80:
            return QColor("#38c875")
        if value >= 65:
            return QColor("#8bcf61")
        if value >= 45:
            return QColor("#e48b3c")
        return QColor("#d95d72")

    @staticmethod
    def _quality_from_code(value: Any, max_code: int) -> int:
        try:
            code = int(value)
        except Exception:
            return 0
        if code <= 0:
            return 0
        return max(0, min(100, round(100 - ((code - 1) / max(1, max_code - 1)) * 100)))

    @staticmethod
    def _cloud_quality(value: Any) -> int:
        try:
            pct = int(value)
        except Exception:
            pct = 100
        return max(0, min(100, 100 - pct))

    @staticmethod
    def _record_cloud_cap(value: Any, has_dark: bool) -> int:
        """Cap card score by the same cloud value printed on the card.

        This keeps the planner honest: a card that says 60–70% cloud should not
        keep the same score as a mostly clear card just because one twilight
        point hit a darkness cap.
        """
        try:
            pct = max(0, min(100, int(value)))
        except Exception:
            pct = 100
        if has_dark:
            if pct >= 85:
                return 25
            if pct >= 75:
                return 35
            if pct >= 65:
                return 42
            if pct >= 55:
                return 48
            if pct >= 45:
                return 60
            if pct >= 35:
                return 70
            if pct >= 25:
                return 78
            return 100
        # When there is no astronomical darkness, keep the score useful for
        # comparison but never let it read like a normal imaging night.
        if pct >= 85:
            return 8
        if pct >= 75:
            return 14
        if pct >= 65:
            return 22
        if pct >= 55:
            return 28
        if pct >= 45:
            return 34
        if pct >= 35:
            return 38
        if pct >= 25:
            return 42
        return 45

    @staticmethod
    def _cloud_condition(value: Any) -> str:
        try:
            pct = int(value)
        except Exception:
            pct = 100
        if pct <= 15:
            return "Clear"
        if pct <= 40:
            return "Mostly clear"
        if pct <= 65:
            return "Partly cloudy"
        if pct <= 85:
            return "Mostly cloudy"
        return "Cloudy"

    @staticmethod
    def _moon_glyph(phase: str) -> str:
        phase_l = str(phase or "").lower()
        if "new" in phase_l:
            return "●"
        if "crescent" in phase_l and "wax" in phase_l:
            return "☽"
        if "first" in phase_l:
            return "◐"
        if "gibbous" in phase_l and "wax" in phase_l:
            return "◑"
        if "full" in phase_l:
            return "○"
        if "gibbous" in phase_l:
            return "◐"
        if "last" in phase_l:
            return "◑"
        if "crescent" in phase_l:
            return "☾"
        return "☾"

    def _draw_moon_icon(self, painter: QPainter, rect: QRectF, phase: str) -> None:
        """Draw a dark-theme moon icon with the unlit part dark, not white text."""
        phase_l = str(phase or "").lower()
        painter.save()
        circle = QRectF(rect)
        path = QPainterPath()
        path.addEllipse(circle)
        dark = QColor("#070a0e")
        light = QColor("#e7edf5")
        outline = QColor("#b8cee6")

        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)

        def fill_left_half() -> None:
            painter.fillPath(path, dark)
            painter.setClipPath(path)
            painter.fillRect(
                QRectF(
                    circle.left(), circle.top(), circle.width() / 2.0, circle.height()
                ),
                light,
            )
            painter.setClipping(False)

        def fill_right_half() -> None:
            painter.fillPath(path, dark)
            painter.setClipPath(path)
            painter.fillRect(
                QRectF(
                    circle.center().x(),
                    circle.top(),
                    circle.width() / 2.0,
                    circle.height(),
                ),
                light,
            )
            painter.setClipping(False)

        if "new" in phase_l:
            painter.fillPath(path, dark)
        elif "full" in phase_l:
            painter.fillPath(path, light)
        elif "first" in phase_l:
            fill_right_half()
        elif "last" in phase_l:
            fill_left_half()
        else:
            waxing = "wax" in phase_l
            crescent = "crescent" in phase_l
            painter.fillPath(path, light)
            painter.setClipPath(path)
            shift = circle.width() * (0.42 if crescent else 0.92)
            if waxing:
                dark_rect = circle.translated(-shift, 0)
            else:
                dark_rect = circle.translated(shift, 0)
            painter.setBrush(QBrush(dark))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(dark_rect)
            painter.setClipping(False)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(outline, 1.4))
        painter.drawEllipse(circle.adjusted(0.8, 0.8, -0.8, -0.8))
        painter.restore()

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _imaging_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Rows that should drive night-imaging planner decisions."""
        dark_rows = [row for row in rows if row.get("astro_dark") is True]
        return dark_rows or rows

    def _best_row(self, block: dict[str, Any]) -> dict[str, Any]:
        rows = block.get("rows") if isinstance(block.get("rows"), list) else []
        if not rows:
            return {}
        candidates = self._imaging_rows(rows)
        return max(candidates, key=lambda row: self._safe_int(row.get("score")))

    def _block_metrics(self, block: dict[str, Any]) -> dict[str, Any]:
        rows = block.get("rows") if isinstance(block.get("rows"), list) else []
        best = self._best_row(block)
        if not rows:
            return {
                "best": {},
                "cloud_pct": None,
                "cloud_quality": 0,
                "seeing_quality": 0,
                "transparency_quality": 0,
                "score": None,
                "score_label": "Waiting",
                "dark_count": 0,
                "moon_up_count": 0,
                "has_dark": False,
            }
        candidates = self._imaging_rows(rows)
        cloud_values = [
            self._safe_int(row.get("cloud_mid_pct"), 100) for row in candidates
        ]
        seeing_values = [
            self._quality_from_code(row.get("seeing_code"), 8) for row in candidates
        ]
        trans_values = [
            self._quality_from_code(row.get("transparency_code"), 8)
            for row in candidates
        ]
        cloud_pct = round(sum(cloud_values) / max(1, len(cloud_values)))
        seeing_quality = max(seeing_values) if seeing_values else 0
        trans_quality = max(trans_values) if trans_values else 0
        dark_count = sum(1 for row in rows if row.get("astro_dark") is True)
        has_dark = dark_count > 0
        score = min(
            self._safe_int(best.get("score"), 0),
            self._record_cloud_cap(cloud_pct, has_dark),
        )
        moon_up_count = sum(1 for row in candidates if row.get("moon_up") is True)
        return {
            "best": best,
            "cloud_pct": cloud_pct,
            "cloud_quality": self._cloud_quality(cloud_pct),
            "seeing_quality": seeing_quality,
            "transparency_quality": trans_quality,
            "score": score,
            "score_label": score_label(score),
            "dark_count": dark_count,
            "moon_up_count": moon_up_count,
            "has_dark": has_dark,
        }

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        position = event.position() if hasattr(event, "position") else event.localPos()
        for rect, row_index in self._hit_regions:
            if rect.contains(position):
                self.selected_row_index = row_index
                self.forecast_row_selected.emit(row_index)
                self.update()
                return
        super().mousePressEvent(event)

    def _draw_tag(self, painter: QPainter, rect: QRectF, text: str, color: QColor):
        painter.setPen(QPen(color, 1))
        painter.setBrush(QBrush(QColor(18, 27, 35, 210)))
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignCenter, text)

    def _draw_gauge(
        self, painter: QPainter, rect: QRectF, title: str, quality: int, value_text: str
    ):
        quality = max(0, min(100, int(quality)))
        title_rect = QRectF(rect.x(), rect.y(), rect.width(), 18)
        track_rect = QRectF(rect.x(), rect.y() + 28, rect.width(), 12)
        text_rect = QRectF(rect.x(), rect.y() + 45, rect.width(), 18)

        painter.setPen(QColor("#a9b7c7"))
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, title)

        # Red-to-green track with a bright marker, similar to the reference UI,
        # but native Qt and dark-theme safe.
        half_w = track_rect.width() / 2.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#c9636d"))
        painter.drawRoundedRect(
            QRectF(track_rect.x(), track_rect.y(), half_w + 5, track_rect.height()),
            5,
            5,
        )
        painter.setBrush(QColor("#75bd7d"))
        painter.drawRoundedRect(
            QRectF(
                track_rect.x() + half_w - 5,
                track_rect.y(),
                half_w + 5,
                track_rect.height(),
            ),
            5,
            5,
        )
        marker_x = track_rect.x() + track_rect.width() * (quality / 100.0)
        painter.setPen(QPen(QColor("#11151a"), 3))
        painter.drawLine(
            QPointF(marker_x, track_rect.y() - 5),
            QPointF(marker_x, track_rect.bottom() + 5),
        )
        painter.setPen(QPen(QColor("#f4f7fb"), 2))
        painter.drawLine(
            QPointF(marker_x, track_rect.y() - 6),
            QPointF(marker_x, track_rect.bottom() + 6),
        )

        painter.setPen(self._quality_color(quality))
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, value_text)

    def paintEvent(self, event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.fillRect(rect, QColor("#0f1318"))
        painter.setPen(QPen(QColor("#29313b"), 1))
        painter.drawRoundedRect(rect, 12, 12)
        self._hit_regions = []

        if not self.blocks:
            painter.setPen(QColor("#8f9ba8"))
            painter.drawText(
                rect,
                Qt.AlignCenter,
                "Night-planner cards will appear after loading SEEING data.",
            )
            return

        left = 18
        right = 18
        top = 34
        row_h = 102
        row_gap = 10
        width = max(1.0, rect.width() - left - right)
        card_w = width

        # Responsive card columns. The old fixed 150 px date box clipped
        # labels like "Wednesday 17" and squeezed the score bubble at smaller
        # widths. Keep a protected date/moon area, three gauges, and a stable
        # score block.
        info_w = max(330.0, min(390.0, card_w * 0.32))
        score_w = max(145.0, min(175.0, card_w * 0.16))
        metric_x = left + info_w
        score_x = left + card_w - score_w - 14
        metric_total_w = max(320.0, score_x - metric_x - 14)
        metric_w = max(106.0, metric_total_w / 3.0)

        painter.setPen(QColor("#cfe4ff"))
        painter.drawText(
            QRectF(left, 11, width, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            "Week forecast cards · click a card to show night-first forecast points",
        )

        for block_index, block in enumerate(self.blocks):
            y = top + block_index * (row_h + row_gap)
            start_dt = (
                self._parse_dt(block.get("display_iso"))
                or self._parse_dt(block.get("start_iso"))
                or datetime.now()
            )
            day_label = str(block.get("day_label") or start_dt.strftime("%A %d"))
            metrics = self._block_metrics(block)
            best = metrics["best"] if isinstance(metrics.get("best"), dict) else {}
            best_index = self._safe_int(best.get("row_index"), -1)
            is_selected = best_index == self.selected_row_index or any(
                self._safe_int(row.get("row_index"), -2) == self.selected_row_index
                for row in (
                    block.get("rows") if isinstance(block.get("rows"), list) else []
                )
            )
            card_rect = QRectF(left, y, card_w, row_h)
            score_color = self._score_color(metrics.get("score"))

            painter.setPen(
                QPen(
                    score_color if is_selected else QColor("#26313d"),
                    2 if is_selected else 1,
                )
            )
            painter.setBrush(QBrush(QColor("#141a20" if is_selected else "#11161c")))
            painter.drawRoundedRect(card_rect, 12, 12)
            painter.fillRect(QRectF(left, y + 8, 4, row_h - 16), score_color)

            # Date and Moon area.
            rows = block.get("rows") if isinstance(block.get("rows"), list) else []
            moon_row = rows[len(rows) // 2] if rows else best
            moon_pct = moon_row.get("moon_pct", "—")
            moon_phase = str(moon_row.get("moon_phase") or "Moon")
            painter.setPen(QColor("#f0f4f8"))
            font = painter.font()
            old_size = font.pointSize()
            font.setPointSize(max(18, old_size + 6))
            font.setBold(True)
            painter.setFont(font)
            date_rect = QRectF(left + 22, y + 14, max(165.0, info_w - 148.0), 32)
            date_text = QFontMetrics(font).elidedText(
                day_label, Qt.ElideRight, int(date_rect.width())
            )
            painter.drawText(date_rect, Qt.AlignLeft | Qt.AlignVCenter, date_text)
            font.setPointSize(old_size)
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor("#8fd0ff"))
            short_rect = QRectF(left + 24, y + 48, max(160.0, info_w - 160.0), 17)
            short_text = str(block.get("short_label", "")).split("→")[0].strip()
            short_text = QFontMetrics(painter.font()).elidedText(
                short_text, Qt.ElideRight, int(short_rect.width())
            )
            painter.drawText(short_rect, Qt.AlignLeft | Qt.AlignVCenter, short_text)

            moon_x = left + info_w - 150
            moon_text_x = left + info_w - 96
            self._draw_moon_icon(
                painter, QRectF(moon_x + 5, y + 18, 34, 34), moon_phase
            )
            painter.setPen(QColor("#dce9f6"))
            painter.drawText(
                QRectF(moon_text_x, y + 16, 92, 18),
                Qt.AlignLeft | Qt.AlignVCenter,
                moon_phase.split(" ")[0],
            )
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                QRectF(moon_text_x, y + 38, 92, 18),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"{moon_pct}% Moon",
            )

            condition = self._cloud_condition(metrics.get("cloud_pct"))
            self._draw_tag(
                painter,
                QRectF(left + 24, y + 68, 138, 21),
                condition,
                self._quality_color(metrics.get("cloud_quality", 0)),
            )
            # Keep the moon/date area clean; dark and Moon-up counts are shown
            # in the detailed forecast table and side panel, not under the icon.

            # Three key gauges. Cloud percentage is calculated from
            # astronomical-darkness rows whenever the record has any, so it
            # matches the score used for night imaging.
            cloud_pct = metrics.get("cloud_pct")
            has_dark = bool(metrics.get("has_dark"))
            cloud_title = "☁ Night clouds" if has_dark else "☁ Clouds"
            cloud_suffix = "night avg" if has_dark else "cover"
            cloud_text = (
                f"{cloud_pct if cloud_pct is not None else '—'}% {cloud_suffix}"
            )
            self._draw_gauge(
                painter,
                QRectF(metric_x, y + 17, metric_w - 10, 66),
                cloud_title,
                metrics.get("cloud_quality", 0),
                cloud_text,
            )
            self._draw_gauge(
                painter,
                QRectF(metric_x + metric_w, y + 17, metric_w - 10, 66),
                "≋ Seeing",
                metrics.get("seeing_quality", 0),
                str(best.get("seeing_text") or "—"),
            )
            self._draw_gauge(
                painter,
                QRectF(metric_x + metric_w * 2, y + 17, metric_w - 10, 66),
                "◉ Transparency",
                metrics.get("transparency_quality", 0),
                str(best.get("transparency_text") or "—"),
            )

            # Score block.
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#101820")))
            painter.drawRoundedRect(QRectF(score_x, y + 15, score_w, 68), 10, 10)
            score_title = "BEST SCORE" if metrics.get("has_dark") else "NO DARK"
            painter.setPen(score_color)
            painter.drawText(
                QRectF(score_x + 12, y + 20, score_w - 24, 16),
                Qt.AlignLeft | Qt.AlignVCenter,
                score_title,
            )
            score_font = painter.font()
            score_old = score_font.pointSize()
            score_font.setPointSize(max(24, score_old + 11))
            score_font.setBold(True)
            painter.setFont(score_font)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                QRectF(score_x + 12, y + 37, 54, 34),
                Qt.AlignLeft | Qt.AlignVCenter,
                str(metrics.get("score") if metrics.get("score") is not None else "—"),
            )
            score_font.setPointSize(score_old)
            score_font.setBold(False)
            painter.setFont(score_font)
            painter.setPen(QColor("#cfe4ff"))
            painter.drawText(
                QRectF(score_x + 70, y + 42, score_w - 82, 18),
                Qt.AlignLeft | Qt.AlignVCenter,
                str(metrics.get("score_label") or "—"),
            )
            painter.setPen(QColor("#91a6bb"))
            time_rect = QRectF(score_x + 70, y + 61, score_w - 82, 16)
            if metrics.get("has_dark"):
                time_label = str(best.get("local_label") or "best night hour")
            else:
                time_label = "No astro dark"
            time_text = QFontMetrics(painter.font()).elidedText(
                time_label,
                Qt.ElideRight,
                int(time_rect.width()),
            )
            painter.drawText(time_rect, Qt.AlignLeft | Qt.AlignVCenter, time_text)

            if best_index >= 0:
                self._hit_regions.append((card_rect, best_index))


class SeeingDialog(QDialog):
    """Self-contained true astronomy SEEING viewer."""

    def _prepare_window_chrome(self):
        flags = (
            self.windowFlags()
            | Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setWindowFlags(flags)

    def _center_on_screen(self):
        parent = self.parentWidget()
        screen = None
        try:
            if parent is not None and parent.screen() is not None:
                screen = parent.screen()
        except Exception:
            screen = None
        if screen is None:
            try:
                screen = self.screen()
            except Exception:
                screen = None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def __init__(self, parent=None, location: dict[str, Any] | None = None):
        super().__init__(parent)
        apply_window_defaults(self)
        self.location = dict(location or {})
        self.seeing_worker: SeeingWorker | None = None
        self.sky_quality_worker: SkyQualityFetchWorker | None = None
        self._result: dict[str, Any] = {}
        self._day_blocks: list[dict[str, Any]] = []
        self._close_after_worker = False

        self.setObjectName("seeingDialog")
        self.setWindowTitle("SEEING")
        self._prepare_window_chrome()
        self.resize(1520, 940)
        self.setMinimumSize(1220, 780)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        controls_card = QFrame()
        controls_card.setObjectName("astroLookupSettingsCard")
        controls = QGridLayout(controls_card)
        controls.setContentsMargins(8, 5, 8, 5)
        controls.setHorizontalSpacing(7)
        controls.setVerticalSpacing(2)
        controls.setColumnStretch(0, 4)
        controls.setColumnStretch(2, 3)
        controls.setColumnStretch(3, 1)

        title = QLabel("SEEING")
        title.setObjectName("astroLookupSectionTitle")
        subtitle = QLabel("Cloud + astro darkness + Moon + true seeing")
        subtitle.setObjectName("helpDialogSubtitle")
        subtitle.setWordWrap(False)

        site_caption = QLabel("Site")
        site_caption.setObjectName("toolbarCaption")
        record_caption = QLabel("Selected day")
        record_caption.setObjectName("toolbarCaption")
        altitude_caption = QLabel("Altitude (m)")
        altitude_caption.setObjectName("toolbarCaption")

        self.site_label = QLabel(self._site_text())
        self.site_label.setObjectName("astroLookupPill")
        self.site_label.setToolTip("Selected observing site used by SEEING.")

        self.site_button = QPushButton("Change site")
        self.site_button.clicked.connect(self.choose_site)

        self.day_graph_combo = QComboBox()
        self.day_graph_combo.setObjectName("astroLookupCombo")
        self.day_graph_combo.setMinimumWidth(380)
        self.day_graph_combo.setEnabled(False)
        self.day_graph_combo.currentIndexChanged.connect(self.handle_day_block_changed)

        self.altitude_spin = QDoubleSpinBox()
        self.altitude_spin.setObjectName("astroLookupSpin")
        self.altitude_spin.setRange(-500.0, 9000.0)
        self.altitude_spin.setDecimals(0)
        self.altitude_spin.setSingleStep(50.0)
        self.altitude_spin.setValue(self._location_elevation())
        self.altitude_spin.setSuffix(" m")
        self.altitude_spin.setToolTip(
            "Site elevation used for SEEING altitude correction. Set it manually or through Change site."
        )

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primaryActionButton")
        self.refresh_button.clicked.connect(self.refresh_forecast)

        controls.addWidget(title, 0, 0)
        controls.addWidget(subtitle, 0, 1, 1, 5)
        controls.addWidget(site_caption, 1, 0)
        controls.addWidget(record_caption, 1, 2)
        controls.addWidget(altitude_caption, 1, 3)
        controls.addWidget(self.site_label, 2, 0)
        controls.addWidget(self.site_button, 2, 1)
        controls.addWidget(self.day_graph_combo, 2, 2)
        controls.addWidget(self.altitude_spin, 2, 3)
        controls.addWidget(self.refresh_button, 2, 4)

        result_card = QFrame()
        result_card.setObjectName("astroLookupResultCard")
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(10, 8, 10, 8)
        result_layout.setSpacing(6)

        result_header = QHBoxLayout()
        result_title = QLabel("Astronomy seeing planner")
        result_title.setObjectName("astroLookupSectionTitle")
        self.current_period_label = QLabel(self._current_night_period_text({}))
        self.current_period_label.setObjectName("astroLookupStatusLabel")
        self.current_period_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.current_period_label.setWordWrap(False)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("astroLookupStatusLabel")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        result_header.addWidget(result_title)
        result_header.addSpacing(12)
        result_header.addWidget(self.current_period_label, 1)
        result_header.addStretch(1)
        result_header.addWidget(self.status_label)
        result_layout.addLayout(result_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("astroLookupProgress")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        result_layout.addWidget(self.progress_bar)

        self.sky_quality_card = QLabel()
        self.sky_quality_card.setObjectName("seeingSkyQualityCard")
        self.sky_quality_card.setTextFormat(Qt.RichText)
        self.sky_quality_card.setWordWrap(False)
        self.sky_quality_card.setMinimumHeight(34)
        self.sky_quality_card.setMaximumHeight(44)
        self.sky_quality_card.setText(self._sky_quality_html({}))
        result_layout.addWidget(self.sky_quality_card)

        # Kept as an internal compatibility label because existing update paths
        # already write to it, but the visible header is now one compact row.
        self.score_card = QLabel()
        self.score_card.setObjectName("seeingScoreCard")
        self.score_card.setTextFormat(Qt.RichText)
        self.score_card.setWordWrap(False)
        self.score_card.setVisible(False)

        main_split = QHBoxLayout()
        main_split.setContentsMargins(0, 0, 0, 0)
        main_split.setSpacing(8)

        left_column = QVBoxLayout()
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(6)

        planner_header = QHBoxLayout()
        planner_title = QLabel("Astro Night Planner")
        planner_title.setObjectName("astroLookupSectionTitle")
        planner_hint = QLabel(
            "Daily cards: clouds + seeing + transparency gauges · click a day for same-day hours"
        )
        planner_hint.setObjectName("astroLookupStatusLabel")
        planner_header.addWidget(planner_title)
        planner_header.addStretch(1)
        planner_header.addWidget(planner_hint)
        left_column.addLayout(planner_header)

        self.cloud_chart = CloudCoverageWidget(self)
        self.cloud_chart.hide()
        self.day_graph = Seeing24HourGraphWidget(self)
        self.day_graph.hide()
        self.night_planner = SeeingNightPlannerWidget(self)
        self.night_planner.forecast_row_selected.connect(
            self.handle_planner_row_selected
        )
        planner_scroll = QScrollArea(self)
        planner_scroll.setObjectName("seeingPlannerScroll")
        planner_scroll.setWidgetResizable(True)
        planner_scroll.setMinimumHeight(420)
        planner_scroll.setFrameShape(QFrame.NoFrame)
        planner_scroll.setWidget(self.night_planner)
        left_column.addWidget(planner_scroll, 10)

        table_panel = QFrame()
        table_panel.setObjectName("astroLookupImagePanel")
        table_layout = QVBoxLayout(table_panel)
        table_layout.setContentsMargins(9, 9, 9, 9)
        table_layout.setSpacing(6)
        table_title = QLabel("Forecast points for selected day · chronological")
        table_title.setObjectName("astroLookupSectionTitle")
        self.table = QTableWidget(0, 10)
        self.table.setObjectName("seeingForecastTable")
        self.table.setMinimumHeight(220)
        self.table.setMaximumHeight(320)
        self.table.setHorizontalHeaderLabels(
            [
                "Local",
                "Score",
                "Cloud",
                "Astro dark",
                "Moon",
                "Seeing",
                "Transparency",
                "Wind",
                "Temp",
                "Precip",
            ]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column in (0, 1, 2, 3, 4, 8, 9):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents
            )
        for column in (5, 6, 7):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.Stretch
            )
        self.table.itemSelectionChanged.connect(self.handle_selection_changed)
        table_layout.addWidget(table_title)
        table_layout.addWidget(self.table, 1)
        left_column.addWidget(table_panel, 3)

        side_column = QVBoxLayout()
        side_column.setContentsMargins(0, 0, 0, 0)
        side_column.setSpacing(8)

        detail_panel = QFrame()
        detail_panel.setObjectName("astroLookupImagePanel")
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(9, 9, 9, 9)
        detail_layout.setSpacing(6)
        detail_title = QLabel("Selected hour")
        detail_title.setObjectName("astroLookupSectionTitle")
        self.detail_browser = QTextBrowser()
        self.detail_browser.setObjectName("astroLookupResultBrowser")
        self.detail_browser.setMinimumWidth(350)
        self.detail_browser.setMinimumHeight(250)
        self.detail_browser.setHtml(self._detail_html({}))
        detail_layout.addWidget(detail_title)
        detail_layout.addWidget(self.detail_browser, 1)
        side_column.addWidget(detail_panel, 1)

        summary_panel = QFrame()
        summary_panel.setObjectName("astroLookupImagePanel")
        summary_layout = QVBoxLayout(summary_panel)
        summary_layout.setContentsMargins(9, 9, 9, 9)
        summary_layout.setSpacing(6)
        summary_title = QLabel("Dark / Moon periods")
        summary_title.setObjectName("astroLookupSectionTitle")
        self.summary_browser = QTextBrowser()
        self.summary_browser.setObjectName("astroLookupResultBrowser")
        self.summary_browser.setMinimumWidth(350)
        self.summary_browser.setMinimumHeight(250)
        self.summary_browser.setHtml(self._summary_html({}))
        summary_layout.addWidget(summary_title)
        summary_layout.addWidget(self.summary_browser, 1)
        side_column.addWidget(summary_panel, 1)

        main_split.addLayout(left_column, 7)
        main_split.addLayout(side_column, 2)
        result_layout.addLayout(main_split, 1)

        button_row = QDialogButtonBox(QDialogButtonBox.Close)
        button_row.rejected.connect(self.reject)

        root.addWidget(controls_card)
        root.addWidget(result_card, 1)
        root.addWidget(button_row)

        self.altitude_spin.editingFinished.connect(self.handle_altitude_edited)
        QTimer.singleShot(0, self._center_on_screen)
        QTimer.singleShot(80, self.refresh_forecast)
        QTimer.singleShot(950, self._ensure_auto_sky_quality)

    def _has_site_quality(self) -> bool:
        try:
            raw_sqm = self._first_float(
                self.location,
                (
                    "sqm",
                    "sqm_mag",
                    "sqm_mag_arcsec2",
                    "mag_arcsec2",
                    "sky_quality",
                    "sky_quality_mag",
                ),
            )
            if raw_sqm is not None and 0.0 < float(raw_sqm) <= 23.5:
                return True
        except Exception:
            pass
        try:
            raw_bortle = self._first_float(
                self.location, ("bortle", "bortle_class", "bortleClass")
            )
            if raw_bortle is not None and 0.0 < float(raw_bortle) <= 9.0:
                return True
        except Exception:
            pass
        return False

    def _persist_location_from_dialog(self):
        parent = self.parent()
        setter = getattr(parent, "set_current_astro_location", None)
        if callable(setter):
            try:
                setter(dict(self.location))
            except Exception:
                pass

    def _ensure_auto_sky_quality(self):
        if self._has_site_quality():
            return
        if self.sky_quality_worker is not None and self.sky_quality_worker.isRunning():
            return
        try:
            float(self.location.get("lat"))
            float(self.location.get("lon"))
        except Exception:
            return
        self.sky_quality_card.setText(
            self._sky_quality_html({"status_note": "Auto-fetching SQM/Bortle…"})
        )
        worker = SkyQualityFetchWorker(dict(self.location), timeout=28.0, parent=self)
        self.sky_quality_worker = worker
        worker.finished_quality.connect(self._handle_auto_sky_quality_finished)
        worker.error_received.connect(self._handle_auto_sky_quality_error)
        worker.finished.connect(self._handle_auto_sky_quality_worker_finished)
        worker.start()

    def _handle_auto_sky_quality_finished(
        self, result: dict, elapsed: float, success: bool
    ):
        if (
            success
            and isinstance(result, dict)
            and (result.get("sqm") or result.get("bortle"))
        ):
            for key in (
                "sqm",
                "bortle",
                "bortle_precise",
                "sky_quality_source",
                "sky_quality_fetched_at",
                "sky_quality_source_url",
            ):
                if result.get(key) is not None:
                    self.location[key] = result.get(key)
            self.site_label.setText(self._site_text())
            self._persist_location_from_dialog()
            payload = dict(self._result or {})
            payload["status_note"] = f"Auto-fetched SQM/Bortle in {float(elapsed):.1f}s"
            self.sky_quality_card.setText(self._sky_quality_html(payload))
        elif not self._has_site_quality():
            payload = dict(self._result or {})
            payload["status_note"] = "Auto SQM/Bortle unavailable"
            self.sky_quality_card.setText(self._sky_quality_html(payload))

    def _handle_auto_sky_quality_error(self, error: str):
        if not self._has_site_quality():
            payload = dict(self._result or {})
            payload["status_note"] = "Auto SQM/Bortle unavailable"
            self.sky_quality_card.setText(self._sky_quality_html(payload))

    def _handle_auto_sky_quality_worker_finished(self):
        worker = self.sender()
        if worker is getattr(self, "sky_quality_worker", None):
            self.sky_quality_worker = None
        if worker is not None:
            worker.deleteLater()

    def _location_elevation(self) -> float:
        try:
            return float(
                self.location.get("elev", self.location.get("elevation_m", 0.0)) or 0.0
            )
        except Exception:
            return 0.0

    def _sync_altitude_from_spin(self, persist: bool = False):
        try:
            self.location["elev"] = float(self.altitude_spin.value())
        except Exception:
            self.location["elev"] = self._location_elevation()
        self.site_label.setText(self._site_text())
        if persist:
            parent = self.parent()
            setter = getattr(parent, "set_current_astro_location", None)
            if callable(setter):
                try:
                    setter(dict(self.location))
                except Exception:
                    pass

    def handle_altitude_edited(self):
        if self.seeing_worker is not None and self.seeing_worker.isRunning():
            return
        self._sync_altitude_from_spin(persist=True)
        self.refresh_forecast()

    def _site_text(self) -> str:
        try:
            lat = float(self.location.get("lat", 0.0))
            lon = float(self.location.get("lon", 0.0))
            elev = float(self.location.get("elev", 0.0))
            tz = str(self.location.get("tz") or "UTC")
            extras = []
            if self.location.get("sqm"):
                extras.append(f"SQM {float(self.location['sqm']):.2f}")
            if self.location.get("bortle"):
                extras.append(f"Bortle {int(round(float(self.location['bortle'])))}")
            suffix = " · " + " · ".join(extras) if extras else ""
            return f"{lat:.5f}, {lon:.5f} · {elev:.0f} m · {tz}{suffix}"
        except Exception:
            return "Saved SITE location"

    def selected_altitude_correction(self) -> str:
        # 7Timer accepts coarse altitude-correction bands. The user controls the
        # actual site elevation; the data layer maps it to the proper 7Timer band.
        return "auto"

    def selected_provider(self) -> str:
        # SEEING is always the hybrid astronomy planner: 7Timer true seeing plus
        # FZAstro moon and astronomical-darkness context. No provider selector is
        # shown because this is the only useful production mode for the window.
        return SEEING_PROVIDER_HYBRID

    def _local_zone(self, result: dict[str, Any] | None = None):
        tz_name = str(
            (result or {}).get("tz") or self.location.get("tz") or "UTC"
        ).strip()
        try:
            return ZoneInfo(tz_name or "UTC")
        except Exception:
            try:
                return datetime.now().astimezone().tzinfo
            except Exception:
                return None

    def _now_local(self, result: dict[str, Any] | None = None) -> datetime:
        zone = self._local_zone(result)
        if zone is not None:
            try:
                return datetime.now(zone)
            except Exception:
                pass
        return datetime.now().astimezone()

    def _parse_period_dt(
        self, value: Any, result: dict[str, Any] | None = None
    ) -> datetime | None:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                zone = self._local_zone(result)
                if zone is not None:
                    dt = dt.replace(tzinfo=zone)
            return dt
        except Exception:
            return None

    def _dark_periods_for_result(
        self, result: dict[str, Any] | None = None
    ) -> list[tuple[datetime, datetime]]:
        payload = result or {}
        zone = self._local_zone(payload)
        astro_context = (
            payload.get("astro_context")
            if isinstance(payload.get("astro_context"), dict)
            else {}
        )
        periods_raw = (
            astro_context.get("dark_periods")
            if isinstance(astro_context.get("dark_periods"), list)
            else []
        )
        periods: list[tuple[datetime, datetime]] = []
        for period in periods_raw:
            if not isinstance(period, dict):
                continue
            start = self._parse_period_dt(period.get("start"), payload)
            end = self._parse_period_dt(period.get("end"), payload)
            if start is None or end is None:
                continue
            if zone is not None:
                start = start.astimezone(zone)
                end = end.astimezone(zone)
            periods.append((start, end))
        periods.sort(key=lambda item: item[0])
        return periods

    def _current_night_period_text(self, result: dict[str, Any] | None = None) -> str:
        payload = result or {}
        now = self._now_local(payload)
        now_text = now.strftime("Now %a %d %b %H:%M")
        note = str(payload.get("status_note") or "").strip()
        periods = [
            (start.astimezone(now.tzinfo), end.astimezone(now.tzinfo))
            for start, end in self._dark_periods_for_result(payload)
        ]
        for start, end in periods:
            if start <= now <= end:
                return (
                    f"{now_text} · current astro dark "
                    f"{start.strftime('%a %d %H:%M')} → {end.strftime('%a %d %H:%M')}"
                )
        for start, end in periods:
            if start > now:
                prefix = "tonight" if start.date() == now.date() else "next astro dark"
                return (
                    f"{now_text} · {prefix} "
                    f"{start.strftime('%a %d %H:%M')} → {end.strftime('%a %d %H:%M')}"
                )
        best_label = self._best_window_label(payload)
        if "—" not in best_label:
            return f"{now_text} · no astro dark · {best_label}"
        if note:
            return f"{now_text} · {note}"
        return f"{now_text} · no astro-dark period loaded"

    def _best_window_label(self, result: dict[str, Any] | None = None) -> str:
        payload = result or {}
        summary = (
            payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        )
        best_dt = self._parse_period_dt(summary.get("best_time"), payload)
        if best_dt is None:
            return "Best forecast hour —"
        zone = self._local_zone(payload)
        if zone is not None:
            best_dt = best_dt.astimezone(zone)

        period_text = ""
        for start, end in self._dark_periods_for_result(payload):
            if start <= best_dt <= end:
                period_text = (
                    f"Night {start.strftime('%a %d')}→{end.strftime('%a %d')} · "
                )
                break

        best_dark = str(summary.get("best_dark") or "").lower()
        if "astro dark" in best_dark:
            kind = "best dark"
        elif "twilight" in best_dark or "day" in best_dark:
            kind = "best twilight"
        else:
            kind = "best forecast"
        return f"{period_text}{kind} {best_dt.strftime('%a %d %H:%M')}"

    def choose_site(self):
        if self.seeing_worker is not None and self.seeing_worker.isRunning():
            return
        selected = choose_astro_location(self, self.location)
        if not selected:
            return
        self.location = dict(selected)
        try:
            self.altitude_spin.setValue(self._location_elevation())
        except Exception:
            pass
        self.site_label.setText(self._site_text())
        parent = self.parent()
        setter = getattr(parent, "set_current_astro_location", None)
        if callable(setter):
            try:
                setter(selected)
            except Exception:
                pass
        self.refresh_forecast()
        QTimer.singleShot(250, self._ensure_auto_sky_quality)

    def refresh_forecast(self):
        if self.seeing_worker is not None and self.seeing_worker.isRunning():
            return
        self._sync_altitude_from_spin(persist=False)
        self._result = {}
        self._day_blocks = []
        self.table.setRowCount(0)
        self.cloud_chart.set_rows([])
        self.day_graph_combo.blockSignals(True)
        self.day_graph_combo.clear()
        self.day_graph_combo.blockSignals(False)
        self.day_graph.set_block({})
        self.night_planner.set_blocks([])
        self.sky_quality_card.setText(
            self._sky_quality_html({"status_note": "Loading…"})
        )
        self.score_card.setText(self._score_card_html({"status_note": "Loading…"}))
        self.summary_browser.setHtml(
            self._summary_html({"status_note": "Loading forecast…"})
        )
        self.detail_browser.setHtml(self._detail_html({}))
        self.status_label.setText("Loading…")
        self.current_period_label.setText(
            self._current_night_period_text({"status_note": "Loading night period…"})
        )
        self.progress_bar.show()
        self._set_controls_enabled(False)

        worker = SeeingWorker(
            self.location,
            self.selected_altitude_correction(),
            self.selected_provider(),
        )
        self.seeing_worker = worker
        worker.finished_seeing.connect(self.handle_seeing_finished)
        worker.error_received.connect(self.handle_seeing_error)
        worker.finished.connect(self.handle_worker_finished)
        worker.start()

    def handle_seeing_finished(self, result: dict, elapsed: float, success: bool):
        self.progress_bar.hide()
        self._set_controls_enabled(True)
        self._result = dict(result or {})
        cache_text = "cached" if result.get("cache_used") else "live"
        self.status_label.setText(f"Loaded {cache_text} • {float(elapsed):.2f}s")
        self.current_period_label.setText(self._current_night_period_text(result))
        self.sky_quality_card.setText(self._sky_quality_html(result))
        self.score_card.setText(self._score_card_html(result))
        self.summary_browser.setHtml(self._summary_html(result))
        rows = result.get("rows") or []
        self.cloud_chart.set_rows(rows)
        self._day_blocks = self._build_24h_blocks(rows)
        self._populate_day_graph_combo()

    def handle_seeing_error(self, error: str):
        if self._close_after_worker:
            self.progress_bar.hide()
            self.status_label.setText("Closed")
            return
        self.progress_bar.hide()
        self._set_controls_enabled(True)
        self.status_label.setText("Failed")
        self.current_period_label.setText(
            self._current_night_period_text({"status_note": "Night period unavailable"})
        )
        self._day_blocks = []
        self.table.setRowCount(0)
        self.cloud_chart.set_rows([])
        self.day_graph_combo.blockSignals(True)
        self.day_graph_combo.clear()
        self.day_graph_combo.blockSignals(False)
        self.day_graph.set_block({})
        self.night_planner.set_blocks([])
        payload = {"status_note": f"SEEING forecast failed: {error}"}
        self.sky_quality_card.setText(self._sky_quality_html(payload))
        self.score_card.setText(self._score_card_html(payload))
        self.summary_browser.setHtml(self._summary_html(payload))
        self.detail_browser.setHtml(self._detail_html({}))
        QMessageBox.warning(self, "SEEING", str(error))

    def _score_brush(self, score: Any) -> QBrush:
        try:
            value = int(score)
        except Exception:
            value = 0
        if value >= 80:
            return QBrush(QColor("#17351f"))
        if value >= 65:
            return QBrush(QColor("#20351f"))
        if value >= 50:
            return QBrush(QColor("#3a3116"))
        if value >= 35:
            return QBrush(QColor("#3a2516"))
        return QBrush(QColor("#3a1c1c"))

    def _cloud_brush(self, pct: Any) -> QBrush:
        try:
            value = int(pct)
        except Exception:
            value = 100
        if value <= 20:
            return QBrush(QColor("#17351f"))
        if value <= 45:
            return QBrush(QColor("#353417"))
        if value <= 70:
            return QBrush(QColor("#3a2516"))
        return QBrush(QColor("#252d35"))

    def _dark_brush(self, row: dict[str, Any]) -> QBrush:
        if row.get("astro_dark") is True:
            return QBrush(QColor("#16304a"))
        if row.get("astro_dark") is False:
            return QBrush(QColor("#2a2116"))
        return QBrush(QColor("#252d35"))

    def _moon_brush(self, row: dict[str, Any]) -> QBrush:
        moon_up = row.get("moon_up")
        try:
            pct = int(row.get("moon_pct") or 0)
        except Exception:
            pct = 0
        if moon_up is False:
            return QBrush(QColor("#17351f"))
        if moon_up is True and pct >= 60:
            return QBrush(QColor("#3a2516"))
        if moon_up is True and pct >= 25:
            return QBrush(QColor("#3a3116"))
        if moon_up is True:
            return QBrush(QColor("#2d2a18"))
        return QBrush(QColor("#252d35"))

    @staticmethod
    def _row_local_dt(row: dict[str, Any]) -> datetime | None:
        try:
            return datetime.fromisoformat(
                str(row.get("local_iso")).replace("Z", "+00:00")
            )
        except Exception:
            return None

    @staticmethod
    def _record_cloud_cap(value: Any, has_dark: bool) -> int:
        try:
            pct = max(0, min(100, int(value)))
        except Exception:
            pct = 100
        if has_dark:
            if pct >= 85:
                return 25
            if pct >= 75:
                return 35
            if pct >= 65:
                return 42
            if pct >= 55:
                return 48
            if pct >= 45:
                return 60
            if pct >= 35:
                return 70
            if pct >= 25:
                return 78
            return 100
        if pct >= 85:
            return 8
        if pct >= 75:
            return 14
        if pct >= 65:
            return 22
        if pct >= 55:
            return 28
        if pct >= 45:
            return 34
        if pct >= 35:
            return 38
        if pct >= 25:
            return 42
        return 45

    def _build_24h_blocks(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Build one planner block per local calendar day.

        The table below the planner is selected by these blocks. Grouping by
        local date keeps each table view limited to the hours of that selected
        day instead of mixing a noon-to-noon 24-hour record across two dates.
        """
        dated_rows = []
        for index, row in enumerate(rows or []):
            copied = dict(row)
            copied["row_index"] = index
            dt = self._row_local_dt(copied)
            if dt is not None:
                dated_rows.append((dt, copied))
        if not dated_rows:
            return []

        dated_rows.sort(key=lambda item: item[0])
        rows_by_day: dict[Any, list[tuple[datetime, dict[str, Any]]]] = {}
        for dt, row in dated_rows:
            rows_by_day.setdefault(dt.date(), []).append((dt, row))

        blocks: list[dict[str, Any]] = []
        for block_index, day in enumerate(sorted(rows_by_day), start=1):
            day_items = sorted(rows_by_day[day], key=lambda item: item[0])
            block_rows = [row for _dt, row in day_items]
            if not block_rows:
                continue

            start = day_items[0][0].replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            dark_rows = [row for row in block_rows if row.get("astro_dark") is True]
            imaging_rows = dark_rows or block_rows
            cloud_values = [int(row.get("cloud_mid_pct") or 0) for row in imaging_rows]
            seeing_values = [int(row.get("seeing_code") or 99) for row in imaging_rows]
            dark_count = len(dark_rows)
            moon_up_count = sum(1 for row in imaging_rows if row.get("moon_up") is True)
            best = max(imaging_rows, key=lambda row: int(row.get("score") or 0))
            avg_cloud = round(sum(cloud_values) / max(1, len(cloud_values)))
            block_score = min(
                int(best.get("score") or 0),
                self._record_cloud_cap(avg_cloud, bool(dark_rows)),
            )
            moon_row = imaging_rows[len(imaging_rows) // 2]
            display_dt = start
            exact_range = (
                f"{start.strftime('%a %Y-%m-%d 00:00')} → "
                f"{end.strftime('%a 00:00')}"
            )
            blocks.append(
                {
                    "label": f"Day {block_index}: {exact_range}",
                    "short_label": f"{display_dt.strftime('%a %d %b')} · 00:00 → 23:59",
                    "day_label": display_dt.strftime("%A %d"),
                    "display_iso": display_dt.isoformat(),
                    "start_iso": start.isoformat(),
                    "end_iso": end.isoformat(),
                    "rows": block_rows,
                    "best_score": block_score,
                    "best_time": best.get("local_label"),
                    "avg_cloud": avg_cloud,
                    "avg_cloud_scope": "night" if dark_rows else "day",
                    "best_seeing_code": min(seeing_values),
                    "astro_dark_points": dark_count,
                    "moon_up_points": moon_up_count,
                    "moon_pct": moon_row.get("moon_pct"),
                    "moon_phase": moon_row.get("moon_phase"),
                }
            )
        return blocks

    def _populate_day_graph_combo(self):
        self.day_graph_combo.blockSignals(True)
        self.day_graph_combo.clear()
        for index, block in enumerate(self._day_blocks):
            score = block.get("best_score")
            cloud = block.get("avg_cloud")
            scope = str(block.get("avg_cloud_scope") or "day")
            best_label = "best score"
            cloud_label = "night cloud" if scope == "night" else "day cloud"
            self.day_graph_combo.addItem(
                f"Day {index + 1}: {block.get('short_label', f'day {index + 1}')} · {best_label} {score if score is not None else '—'} · {cloud_label} {cloud if cloud is not None else '—'}%",
                index,
            )
        self.day_graph_combo.blockSignals(False)
        self.day_graph_combo.setEnabled(bool(self._day_blocks))
        if self._day_blocks:
            start_index = self._current_or_next_dark_block_index()
            self.day_graph_combo.setCurrentIndex(start_index)
            self._apply_record_filter(start_index, select_best=True)
        else:
            self.night_planner.set_blocks([])
            self._populate_table([])

    def _current_or_next_dark_block_index(self) -> int:
        """Prefer the forecast block containing the current/next dark imaging period."""
        if not self._day_blocks:
            return 0
        now = self._now_local(self._result)
        current_block = -1
        upcoming_index = -1
        upcoming_dt: datetime | None = None
        for index, block in enumerate(self._day_blocks):
            start_dt = self._parse_period_dt(block.get("start_iso"), self._result)
            end_dt = self._parse_period_dt(block.get("end_iso"), self._result)
            if start_dt is not None and end_dt is not None:
                try:
                    start_dt = start_dt.astimezone(now.tzinfo)
                    end_dt = end_dt.astimezone(now.tzinfo)
                except Exception:
                    pass
                if start_dt <= now < end_dt:
                    current_block = index
            rows = block.get("rows") if isinstance(block.get("rows"), list) else []
            for row in rows:
                if row.get("astro_dark") is not True:
                    continue
                row_dt = self._row_local_dt(row)
                if row_dt is None:
                    continue
                try:
                    row_dt = row_dt.astimezone(now.tzinfo)
                except Exception:
                    pass
                if row_dt >= now and (upcoming_dt is None or row_dt < upcoming_dt):
                    upcoming_dt = row_dt
                    upcoming_index = index
        if upcoming_index >= 0:
            return upcoming_index
        if current_block >= 0:
            return current_block
        return self._best_block_index()

    def _best_block_index(self) -> int:
        best_index = 0
        best_score = -1
        for index, block in enumerate(self._day_blocks):
            try:
                score = int(block.get("best_score") or 0)
            except Exception:
                score = 0
            if score > best_score:
                best_score = score
                best_index = index
        return best_index

    def _current_block_index(self) -> int:
        data = self.day_graph_combo.currentData()
        if isinstance(data, int) and 0 <= data < len(self._day_blocks):
            return data
        return 0 if self._day_blocks else -1

    def _apply_record_filter(
        self, block_index: int | None = None, select_best: bool = False
    ):
        if not self._day_blocks:
            self.night_planner.set_blocks([])
            self._populate_table([])
            return
        if block_index is None:
            block_index = self._current_block_index()
        block_index = max(0, min(int(block_index), len(self._day_blocks) - 1))
        block = self._day_blocks[block_index]
        rows = block.get("rows") if isinstance(block.get("rows"), list) else []
        selected = self._selected_row_index()
        self.night_planner.set_blocks(self._day_blocks, selected)
        self._populate_table(rows)
        if self.table.rowCount() > 0:
            target = self._best_table_row() if select_best else 0
            self.table.selectRow(target if target >= 0 else 0)

    def _block_index_for_row(self, row_data: dict[str, Any]) -> int:
        row_dt = self._row_local_dt(row_data)
        if row_dt is None:
            return -1
        for index, block in enumerate(self._day_blocks):
            start_dt = Seeing24HourGraphWidget._parse_dt(block.get("start_iso"))
            end_dt = Seeing24HourGraphWidget._parse_dt(block.get("end_iso"))
            if (
                start_dt is not None
                and end_dt is not None
                and start_dt <= row_dt < end_dt
            ):
                return index
        return -1

    def handle_day_block_changed(self, index: int):
        block_index = self.day_graph_combo.itemData(index)
        if (
            not isinstance(block_index, int)
            or block_index < 0
            or block_index >= len(self._day_blocks)
        ):
            return
        self._apply_record_filter(block_index, select_best=False)

    def _is_night_row(self, row: dict[str, Any]) -> bool:
        """Return True only for astronomical darkness rows.

        Twilight/day rows can have excellent seeing and low cloud, but they are
        not useful night-imaging candidates and must not drive planner scores.
        """
        if row.get("astro_dark") is True:
            return True
        text = str(row.get("astro_dark_text", "")).lower()
        return text.startswith("astro dark")

    def _forecast_point_sort_key(self, row: dict[str, Any]) -> tuple[datetime, int]:
        """Sort selected-day forecast points chronologically.

        Day cards already surface the best imaging periods. The detailed table
        should read like a timeline for the selected local calendar day, so the
        user sees 05:00, 08:00, 11:00, 14:00, etc. in natural order instead of
        score/night buckets.
        """
        local_dt = self._row_local_dt(row) or datetime.max
        return (local_dt, self._safe_int(row.get("row_index"), 0))

    def _chronological_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            [dict(row) for row in (rows or [])], key=self._forecast_point_sort_key
        )

    def _populate_table(self, rows: list[dict[str, Any]]):
        self.table.setRowCount(0)
        display_rows = self._chronological_rows(rows)
        for index, row_data in enumerate(display_rows):
            row = self.table.rowCount()
            self.table.insertRow(row)
            cloud_pct = row_data.get("cloud_mid_pct")
            cloud_value = f"{cloud_pct if cloud_pct is not None else '—'}% · {row_data.get('cloud_text', '—')}"
            values = [
                row_data.get("local_label", "—"),
                f"{row_data.get('score', '—')} · {row_data.get('score_label', '')}",
                cloud_value,
                row_data.get("astro_dark_text", "—"),
                row_data.get("moon_text", "—"),
                row_data.get("seeing_text", "—"),
                row_data.get("transparency_text", "—"),
                row_data.get("wind_speed_text", "—"),
                self._temp_text(row_data.get("temp2m_c")),
                row_data.get("precip_text", "—"),
            ]
            row_copy = dict(row_data)
            if "row_index" not in row_copy:
                row_copy["row_index"] = index
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, row_copy)
                if column == 1:
                    item.setBackground(self._score_brush(row_data.get("score")))
                    item.setTextAlignment(Qt.AlignCenter)
                elif column == 2:
                    item.setBackground(self._cloud_brush(row_data.get("cloud_mid_pct")))
                    item.setTextAlignment(Qt.AlignCenter)
                elif column == 3:
                    item.setBackground(self._dark_brush(row_data))
                    item.setTextAlignment(Qt.AlignCenter)
                elif column == 4:
                    item.setBackground(self._moon_brush(row_data))
                    item.setTextAlignment(Qt.AlignCenter)
                elif column in {8, 9}:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)
        self.table.resizeRowsToContents()

    @staticmethod
    def _temp_text(value: Any) -> str:
        try:
            return f"{float(value):.0f}°C"
        except Exception:
            return "—"

    def handle_selection_changed(self):
        items = self.table.selectedItems()
        if not items:
            return
        row = items[0].row()
        item = self.table.item(row, 0)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if isinstance(data, dict):
            self.detail_browser.setHtml(self._detail_html(data))
            row_index = int(data.get("row_index", row))
            self.cloud_chart.set_selected_index(row_index)
            block_index = self._block_index_for_row(data)
            if block_index >= 0 and self.day_graph_combo.currentIndex() != block_index:
                self.day_graph_combo.blockSignals(True)
                self.day_graph_combo.setCurrentIndex(block_index)
                self.day_graph_combo.blockSignals(False)
            self.night_planner.set_blocks(self._day_blocks, row_index)
        else:
            self.cloud_chart.set_selected_index(row)

    def _selected_row_index(self) -> int:
        items = self.table.selectedItems()
        if not items:
            return -1
        item = self.table.item(items[0].row(), 0)
        data = item.data(Qt.UserRole) if item is not None else None
        if isinstance(data, dict):
            try:
                return int(data.get("row_index", items[0].row()))
            except Exception:
                return items[0].row()
        return items[0].row()

    def _select_table_row(self, row_index: int):
        if row_index < 0:
            return
        for table_row in range(self.table.rowCount()):
            item = self.table.item(table_row, 0)
            data = item.data(Qt.UserRole) if item is not None else None
            if isinstance(data, dict) and int(data.get("row_index", -1)) == row_index:
                self.table.selectRow(table_row)
                self.table.scrollToItem(
                    item, QAbstractItemView.ScrollHint.PositionAtCenter
                )
                return

    def _best_table_row(self) -> int:
        best_table_row = -1
        best_score = -1
        fallback_row = -1
        fallback_score = -1
        for table_row in range(self.table.rowCount()):
            item = self.table.item(table_row, 0)
            data = item.data(Qt.UserRole) if item is not None else None
            if not isinstance(data, dict):
                continue
            score = self._safe_int(data.get("score"), 0)
            if score > fallback_score:
                fallback_score = score
                fallback_row = table_row
            # Prefer the best astronomical-darkness row. If there is no dark row,
            # fall back to the best score overall.
            if self._is_night_row(data) and score > best_score:
                best_score = score
                best_table_row = table_row
        return best_table_row if best_table_row >= 0 else fallback_row

    def _block_index_for_row_index(self, row_index: int) -> int:
        for block_index, block in enumerate(self._day_blocks):
            rows = block.get("rows") if isinstance(block.get("rows"), list) else []
            for row in rows:
                try:
                    if int(row.get("row_index", -1)) == int(row_index):
                        return block_index
                except Exception:
                    continue
        return -1

    def handle_planner_row_selected(self, row_index: int):
        row_index = int(row_index)
        block_index = self._block_index_for_row_index(row_index)
        if block_index >= 0:
            self.day_graph_combo.blockSignals(True)
            self.day_graph_combo.setCurrentIndex(block_index)
            self.day_graph_combo.blockSignals(False)
            self._apply_record_filter(block_index, select_best=False)
        self._select_table_row(row_index)
        self.night_planner.set_selected_row_index(row_index)

    def _set_controls_enabled(self, enabled: bool):
        self.altitude_spin.setEnabled(bool(enabled))
        self.site_button.setEnabled(bool(enabled))
        self.refresh_button.setEnabled(bool(enabled))
        self.day_graph_combo.setEnabled(bool(enabled and self._day_blocks))

    @staticmethod
    def _bortle_from_sqm(sqm: float | None) -> int | None:
        if sqm is None:
            return None
        if sqm >= 21.75:
            return 1
        if sqm >= 21.55:
            return 2
        if sqm >= 21.30:
            return 3
        if sqm >= 20.80:
            return 4
        if sqm >= 20.30:
            return 5
        if sqm >= 19.25:
            return 6
        if sqm >= 18.50:
            return 7
        if sqm >= 18.00:
            return 8
        return 9

    @staticmethod
    def _sqm_from_bortle(bortle: int | None) -> float | None:
        mapping = {
            1: 21.90,
            2: 21.65,
            3: 21.45,
            4: 21.05,
            5: 20.55,
            6: 19.75,
            7: 18.75,
            8: 18.25,
            9: 17.75,
        }
        return mapping.get(int(bortle)) if bortle is not None else None

    @staticmethod
    def _bortle_accent(bortle: int | None) -> tuple[str, str, str]:
        """Return dark-theme-visible accent, label, and card background."""
        try:
            value = int(bortle) if bortle is not None else None
        except Exception:
            value = None
        if value is None:
            return "#91a6bb", "Not set", "#101820"
        if value >= 8:
            return "#f2f6fb", "Urban/white", "#202327"
        if value >= 6:
            return "#f2d56b", "Bright/yellow", "#211f12"
        if value >= 4:
            return "#92d7a7", "Suburban/green", "#0f1f17"
        if value >= 2:
            return "#8fd0ff", "Dark/blue", "#0e1b28"
        return "#b59cff", "Pristine/violet", "#191427"

    def _apply_sky_quality_card_style(self, accent: str, background: str) -> None:
        if not hasattr(self, "sky_quality_card"):
            return
        self.sky_quality_card.setStyleSheet(
            f"""
            background-color: {background};
            color: #e8edf2;
            border: 1px solid {accent};
            border-radius: 12px;
            padding: 8px 10px;
            """
        )

    @staticmethod
    def _sky_brightness_from_sqm(
        sqm: float | None,
    ) -> tuple[float | None, float | None]:
        if sqm is None:
            return None, None
        # Standard luminance approximation for mag/arcsec² to mcd/m².
        brightness_mcd = 108_000_000.0 * (10 ** (-0.4 * float(sqm)))
        natural_mcd = 108_000_000.0 * (10 ** (-0.4 * 21.97))
        return brightness_mcd, max(0.0, brightness_mcd - natural_mcd)

    @staticmethod
    def _first_float(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            try:
                value = data.get(key)
                if value is None or str(value).strip() == "":
                    continue
                return float(value)
            except Exception:
                continue
        return None

    def _site_quality_values(self) -> dict[str, Any]:
        sqm: float | None = None
        bortle: int | None = None
        raw_sqm = self._first_float(
            self.location,
            (
                "sqm",
                "sqm_mag",
                "sqm_mag_arcsec2",
                "mag_arcsec2",
                "sky_quality",
                "sky_quality_mag",
            ),
        )
        if raw_sqm is not None and 0.0 < raw_sqm <= 23.5:
            sqm = float(raw_sqm)
        raw_bortle = self._first_float(
            self.location, ("bortle", "bortle_class", "bortleClass")
        )
        if raw_bortle is not None and 0.0 < raw_bortle <= 9.0:
            bortle = max(1, min(9, int(round(raw_bortle))))
        source = str(self.location.get("sky_quality_source") or "SITE profile")
        if "auto estimate" in source.lower():
            sqm = None
            bortle = None
            source = "Set in Change site"
        if sqm is None and bortle is not None:
            sqm = sqm_from_bortle(bortle)
        if bortle is None and sqm is not None:
            bortle = bortle_from_sqm(sqm)
        if sqm is None and bortle is None:
            source = "Set in Change site"
        brightness_mcd, artificial_mcd = sky_brightness_from_sqm(sqm)
        return {
            "sqm": sqm,
            "bortle": bortle,
            "brightness_mcd": brightness_mcd,
            "artificial_mcd": artificial_mcd,
            "source": (
                source
                if sqm is not None or bortle is not None
                else "Set in Change site"
            ),
        }

    def _sky_quality_html(self, result: dict[str, Any]) -> str:
        quality = self._site_quality_values()
        sqm = quality.get("sqm")
        bortle = quality.get("bortle")
        brightness = quality.get("brightness_mcd")
        artificial = quality.get("artificial_mcd")
        source = html.escape(str(quality.get("source") or "Set in Change site"))
        summary = (
            result.get("summary") if isinstance(result.get("summary"), dict) else {}
        )
        generated = html.escape(str(result.get("init_utc") or "—"))
        try:
            lat = float(self.location.get("lat", result.get("lat", 0.0)))
            lon = float(self.location.get("lon", result.get("lon", 0.0)))
            elev = float(self.location.get("elev", result.get("elev", 0.0)))
            site = f"{lat:.4f}, {lon:.4f} · {elev:.0f} m"
        except Exception:
            site = "Selected SITE"

        sqm_text = f"{sqm:.2f}" if sqm is not None else "Not set"
        bortle_text = f"Class {bortle}" if bortle is not None else "Not set"
        bortle_color, bortle_band, bortle_background = self._bortle_accent(bortle)
        self._apply_sky_quality_card_style(bortle_color, bortle_background)
        brightness_text = f"{brightness:.2f}" if brightness is not None else "—"
        artificial_text = f"{artificial:.2f}" if artificial is not None else "—"
        score = summary.get("best_score")
        try:
            score_text = str(int(score))
        except Exception:
            score_text = "—"
        label = summary.get("best_score_label") or score_label(score)
        best_slot = html.escape(self._best_window_label(result))
        cloud = html.escape(
            str(summary.get("best_cloud_compact") or summary.get("best_cloud") or "—")
        )
        dark = html.escape(str(summary.get("best_dark") or "—"))
        moon = html.escape(str(summary.get("best_moon") or "—"))
        seeing = html.escape(str(summary.get("best_seeing") or "—"))
        trans = html.escape(str(summary.get("best_transparency") or "—"))
        return f"""
        <div style="font-family:'Segoe UI Variable','Segoe UI',sans-serif;color:#e8edf2;white-space:nowrap;font-size:11px;line-height:1.15;">
          <span style="color:{bortle_color};font-weight:850;">SQM</span> <b>{html.escape(sqm_text)}</b>
          <span style="color:#516171;"> | </span><span style="color:{bortle_color};font-weight:850;">Bortle</span> <b style="color:{bortle_color};">{html.escape(bortle_text)}</b> <span style="color:#91a6bb;">{html.escape(bortle_band)}</span>
          <span style="color:#516171;"> | </span><span style="color:#8fd0ff;font-weight:850;">Night window</span> <b>{best_slot}</b>
          <span style="color:#516171;"> | </span><span style="color:#8fd0ff;font-weight:850;">Score</span> <b style="font-size:16px;">{html.escape(score_text)}</b> <span style="color:#cfe4ff;">{html.escape(str(label))}</span>
          <span style="color:#516171;"> | </span><span style="color:#8fd0ff;font-weight:850;">Cloud</span> <b>{cloud}</b>
          <span style="color:#516171;"> | </span><span style="color:#3296dc;font-weight:850;">Dark</span> <b>{dark}</b>
          <span style="color:#516171;"> | </span><span style="color:#c5a149;font-weight:850;">Moon</span> <b>{moon}</b>
          <span style="color:#516171;"> | </span><span style="color:#74bf57;font-weight:850;">Seeing</span> <b>{seeing}</b>
          <span style="color:#516171;"> | </span><span style="color:#74bf57;font-weight:850;">Trans</span> <b>{trans}</b>
          <span style="color:#516171;"> | </span><span style="color:#91a6bb;">{html.escape(site)} · {source} · {generated}</span>
        </div>
        """

    def _score_card_html(self, result: dict[str, Any]) -> str:
        summary = (
            result.get("summary") if isinstance(result.get("summary"), dict) else {}
        )
        score = summary.get("best_score")
        label = summary.get("best_score_label") or score_label(score)
        time = html.escape(str(summary.get("best_time") or "—"))
        cloud = html.escape(
            str(summary.get("best_cloud_compact") or summary.get("best_cloud") or "—")
        )
        dark = html.escape(str(summary.get("best_dark") or "—"))
        moon = html.escape(str(summary.get("best_moon") or "—"))
        seeing = html.escape(str(summary.get("best_seeing") or "—"))
        trans = html.escape(str(summary.get("best_transparency") or "—"))
        status_note = html.escape(str(result.get("status_note") or ""))
        try:
            score_text = str(int(score))
        except Exception:
            score_text = "—"
            label = "Waiting"
        return f"""
        <div style="font-family:'Segoe UI Variable','Segoe UI',sans-serif;">
          <table cellspacing="0" cellpadding="0" style="width:100%;border-collapse:separate;border-spacing:4px 0;">
            <tr>
              <td style="width:20%;padding:5px 8px;background:#121d28;border:1px solid #2c3c4d;border-radius:8px;">
                <div style="font-size:8px;color:#91a6bb;font-weight:850;text-transform:uppercase;letter-spacing:.6px;">Best window</div>
                <div style="font-size:12px;color:#ffffff;font-weight:850;line-height:1.05;">{time}</div>
                <div style="font-size:9px;color:#aeb9c5;line-height:1.05;">{status_note}</div>
              </td>
              <td style="width:9%;padding:5px 8px;background:#121d28;border:1px solid #2c3c4d;border-radius:8px;">
                <div style="font-size:8px;color:#91a6bb;font-weight:850;text-transform:uppercase;letter-spacing:.6px;">Score</div>
                <div style="font-size:24px;color:#ffffff;font-weight:900;line-height:.95;">{html.escape(score_text)}</div>
                <div style="font-size:10px;color:#cfe4ff;font-weight:800;line-height:1;">{html.escape(str(label))}</div>
              </td>
              <td style="width:13%;padding:5px 8px;background:#101b25;border:1px solid #263545;border-radius:8px;"><div style="font-size:8px;color:#91a6bb;font-weight:850;text-transform:uppercase;letter-spacing:.6px;">Cloud</div><div style="font-size:13px;color:#ffffff;font-weight:900;line-height:1.1;">{cloud}</div></td>
              <td style="width:13%;padding:5px 8px;background:#101b25;border:1px solid #263545;border-radius:8px;"><div style="font-size:8px;color:#91a6bb;font-weight:850;text-transform:uppercase;letter-spacing:.6px;">Astro dark</div><div style="font-size:13px;color:#ffffff;font-weight:900;line-height:1.1;">{dark}</div></td>
              <td style="width:12%;padding:5px 8px;background:#101b25;border:1px solid #263545;border-radius:8px;"><div style="font-size:8px;color:#91a6bb;font-weight:850;text-transform:uppercase;letter-spacing:.6px;">Moon</div><div style="font-size:13px;color:#ffffff;font-weight:900;line-height:1.1;">{moon}</div></td>
              <td style="width:16%;padding:5px 8px;background:#101b25;border:1px solid #263545;border-radius:8px;"><div style="font-size:8px;color:#91a6bb;font-weight:850;text-transform:uppercase;letter-spacing:.6px;">Seeing</div><div style="font-size:11px;color:#ffffff;font-weight:850;line-height:1.1;">{seeing}</div></td>
              <td style="width:17%;padding:5px 8px;background:#101b25;border:1px solid #263545;border-radius:8px;"><div style="font-size:8px;color:#91a6bb;font-weight:850;text-transform:uppercase;letter-spacing:.6px;">Transparency</div><div style="font-size:11px;color:#ffffff;font-weight:850;line-height:1.1;">{trans}</div></td>
            </tr>
          </table>
        </div>
        """

    def _summary_html(self, result: dict[str, Any]) -> str:
        summary = (
            result.get("summary") if isinstance(result.get("summary"), dict) else {}
        )
        provider = html.escape(
            str(result.get("provider") or "7Timer ASTRO + Moon/Dark")
        )
        cache_state = "Cached fallback" if result.get("cache_used") else "Live forecast"
        dark_periods = (
            summary.get("dark_periods")
            if isinstance(summary.get("dark_periods"), list)
            else []
        )
        moon_periods = (
            summary.get("moon_periods")
            if isinstance(summary.get("moon_periods"), list)
            else []
        )
        moon_note = html.escape(str(summary.get("moon_period_note") or ""))

        def list_html(values: list[Any], empty: str) -> str:
            if not values:
                return f"<p class='note'>{html.escape(empty)}</p>"
            return "".join(
                f"<p class='line'>{html.escape(str(value))}</p>" for value in values[:6]
            )

        return f"""
        <html><head><style>
            body {{ background:#0f1318; color:#e8edf2; font-family:'Segoe UI Variable','Segoe UI',sans-serif; font-size:11px; line-height:1.22; margin:0; }}
            h1 {{ color:#fff; font-size:13px; margin:0 0 3px 0; }}
            h2 {{ color:#eef3f8; font-size:11px; margin:5px 0 2px 0; }}
            p {{ margin:2px 0; }}
            .pill {{ display:inline-block; color:#cfe4ff; background:#111a23; border:1px solid #2a3948; border-radius:7px; padding:2px 6px; font-weight:800; margin:0 0 3px 0; }}
            .note {{ color:#aeb9c5; }} .line {{ color:#e8edf2; }}
        </style></head><body>
            <h1>Dark / Moon periods</h1>
            <div class="pill">{html.escape(cache_state)}</div>
            <h2>Astronomical darkness</h2>
            {list_html(dark_periods, 'No astronomical darkness period for this record.')}
            <h2>Moon up/down</h2>
            {list_html(moon_periods, moon_note or 'Moon periods are unavailable for this record.')}
        </body></html>
        """

    def _detail_html(self, row: dict[str, Any]) -> str:
        if not row:
            return """
            <html><body style="background:#0f1318;color:#aeb9c5;font-family:'Segoe UI';font-size:11px;margin:0;">
            Select a forecast row to see details.
            </body></html>
            """
        local = html.escape(str(row.get("local_label") or "—"))
        utc = html.escape(str(row.get("utc_iso") or "—"))
        score = html.escape(str(row.get("score") or "—"))
        score_text = html.escape(str(row.get("score_label") or "—"))
        seeing = html.escape(str(row.get("seeing_text") or "—"))
        trans = html.escape(str(row.get("transparency_text") or "—"))
        cloud = html.escape(str(row.get("cloud_text") or "—"))
        cloud_pct = html.escape(
            str(
                row.get("cloud_mid_pct")
                if row.get("cloud_mid_pct") is not None
                else "—"
            )
        )
        wind = html.escape(str(row.get("wind_speed_text") or "—"))
        direction = html.escape(str(row.get("wind_direction") or "—"))
        temp = html.escape(self._temp_text(row.get("temp2m_c")))
        precip = html.escape(str(row.get("precip_text") or "—"))
        dark = html.escape(str(row.get("astro_dark_text") or "—"))
        sun_alt = html.escape(
            str(
                row.get("sun_altitude_deg")
                if row.get("sun_altitude_deg") is not None
                else "—"
            )
        )
        moon = html.escape(str(row.get("moon_text") or "—"))
        phase = html.escape(str(row.get("moon_phase") or "—"))
        return f"""
        <html><head><style>
            body {{ background:#0f1318; color:#e8edf2; font-family:'Segoe UI Variable','Segoe UI',sans-serif; font-size:11px; line-height:1.22; margin:0; }}
            h1 {{ color:#fff; font-size:14px; margin:0 0 4px 0; }}
            .sub {{ color:#93a8bd; font-size:10px; margin-bottom:6px; }}
            table {{ width:100%; border-collapse:separate; border-spacing:5px 5px; }}
            td {{ background:#111a23; border:1px solid #29394a; border-radius:7px; padding:5px 7px; vertical-align:top; }}
            .k {{ color:#93a8bd; font-size:9px; font-weight:850; text-transform:uppercase; letter-spacing:.5px; }}
            .v {{ color:#f3f7fc; font-weight:750; font-size:11px; }}
        </style></head><body>
            <h1>{local}</h1>
            <div class="sub">UTC: {utc}</div>
            <table>
              <tr><td><div class="k">Score</div><div class="v">{score} · {score_text}</div></td><td><div class="k">Cloud</div><div class="v">{cloud_pct}% · {cloud}</div></td></tr>
              <tr><td><div class="k">Astro dark</div><div class="v">{dark} · Sun {sun_alt}°</div></td><td><div class="k">Moon</div><div class="v">{moon} · {phase}</div></td></tr>
              <tr><td><div class="k">Seeing</div><div class="v">{seeing}</div></td><td><div class="k">Transparency</div><div class="v">{trans}</div></td></tr>
              <tr><td><div class="k">Wind</div><div class="v">{wind} · {direction}</div></td><td><div class="k">Temp / precip</div><div class="v">{temp} · {precip}</div></td></tr>
            </table>
        </body></html>
        """

    def handle_worker_finished(self):
        worker = self.sender()
        if worker is getattr(self, "seeing_worker", None):
            self.seeing_worker = None
        if worker is not None:
            worker.deleteLater()
        if self._close_after_worker:
            QTimer.singleShot(0, self.reject)

    def _stop_worker(self) -> bool:
        worker = getattr(self, "seeing_worker", None)
        if worker is not None and worker.isRunning():
            try:
                worker.stop()
            except Exception:
                pass
            return True
        return False

    def _sky_quality_worker_running(self) -> bool:
        worker = getattr(self, "sky_quality_worker", None)
        return bool(worker is not None and worker.isRunning())

    def reject(self):
        if self._stop_worker():
            self._close_after_worker = True
            self.status_label.setText("Stopping…")
            self._set_controls_enabled(False)
            return
        if self._sky_quality_worker_running():
            self.status_label.setText("Waiting for SQM/Bortle fetch…")
            QTimer.singleShot(800, self.reject)
            return
        super().reject()

    def closeEvent(self, event):  # noqa: N802 - Qt override
        if self._stop_worker():
            self._close_after_worker = True
            self.status_label.setText("Stopping…")
            self._set_controls_enabled(False)
            event.ignore()
            return
        if self._sky_quality_worker_running():
            self.status_label.setText("Waiting for SQM/Bortle fetch…")
            QTimer.singleShot(800, self.reject)
            event.ignore()
            return
        super().closeEvent(event)


def show_seeing_dialog(parent=None, location: dict[str, Any] | None = None):
    dialog = SeeingDialog(parent, location)
    return dialog.exec()
