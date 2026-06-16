from __future__ import annotations

import html
import math
import re
from pathlib import Path
from typing import Dict, Optional

from .astro_object_catalogs import ASTRO_CATALOG_ROWS

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
)


CAMERA_PRESETS: Dict[str, Dict[str, float | int | str]] = {
    "aps": {
        "name": "IMX571",
        "label": "IMX571 (APS-C, 6248 × 4176)",
        "preset_label_text": "IMX571 (2.337°, 6248 × 4176)",
        "sensor_width_mm": 23.5,
        "native_width": 6248,
        "native_height": 4176,
        "output_width": 1536,
        "output_height": 1024,
    },
    "533": {
        "name": "IMX533",
        "label": "IMX533 (square, 3008 × 3008)",
        "preset_label_text": "IMX533 (1.12°, 3008 × 3008)",
        "sensor_width_mm": 11.3,
        "native_width": 3008,
        "native_height": 3008,
        "output_width": 1024,
        "output_height": 1024,
    },
    "585": {
        "name": "IMX585",
        "label": "IMX585 (4K, 3840 × 2160)",
        "preset_label_text": "IMX585 (1.33°, 3840 × 2160)",
        "sensor_width_mm": 11.2,
        "native_width": 3840,
        "native_height": 2160,
        "output_width": 1536,
        "output_height": 864,
    },
}

DEFAULT_ASTRO_IMAGING = {
    "preset": "585",
    "focal_mm": 700.0,
    "rotation_angle": 0.0,
}


def normalise_astro_imaging(value: Optional[dict]) -> dict:
    data = dict(DEFAULT_ASTRO_IMAGING)
    if isinstance(value, dict):
        data.update(value)

    preset = str(data.get("preset") or DEFAULT_ASTRO_IMAGING["preset"]).strip()
    if preset not in CAMERA_PRESETS:
        preset = DEFAULT_ASTRO_IMAGING["preset"]

    try:
        focal_mm = float(data.get("focal_mm", DEFAULT_ASTRO_IMAGING["focal_mm"]))
    except Exception:
        focal_mm = float(DEFAULT_ASTRO_IMAGING["focal_mm"])
    focal_mm = max(50.0, min(6000.0, focal_mm))

    try:
        rotation = float(
            data.get("rotation_angle", DEFAULT_ASTRO_IMAGING["rotation_angle"])
        )
    except Exception:
        rotation = float(DEFAULT_ASTRO_IMAGING["rotation_angle"])
    rotation = max(0.0, min(360.0, rotation))

    preset_info = CAMERA_PRESETS[preset]
    fov_x = fov_from_focal(preset, focal_mm)
    width = int(preset_info["output_width"])
    height = int(preset_info["output_height"])
    fov_y = fov_x * height / max(1, width)

    return {
        "preset": preset,
        "preset_name": str(preset_info["name"]),
        "preset_label": str(preset_info["preset_label_text"]),
        "focal_mm": float(focal_mm),
        "rotation_angle": float(rotation),
        "fov_deg": float(fov_x),
        "fov_y_deg": float(fov_y),
        "width": width,
        "height": height,
        "native_width": int(preset_info["native_width"]),
        "native_height": int(preset_info["native_height"]),
        "sensor_width_mm": float(preset_info["sensor_width_mm"]),
    }


def fov_from_focal(preset: str, focal_mm: float) -> float:
    info = CAMERA_PRESETS.get(
        str(preset), CAMERA_PRESETS[DEFAULT_ASTRO_IMAGING["preset"]]
    )
    sensor_width = float(info["sensor_width_mm"])
    focal = max(1.0, float(focal_mm))
    fov = 2.0 * math.atan((sensor_width / 2.0) / focal) * 180.0 / math.pi
    return min(10.0, max(0.1, fov))


def astro_imaging_summary(value: Optional[dict]) -> str:
    data = normalise_astro_imaging(value)
    return (
        f"{data['preset_name']} · {data['focal_mm']:.0f} mm · "
        f"{data['fov_deg']:.3f}° × {data['fov_y_deg']:.3f}° · rot {data['rotation_angle']:.0f}°"
    )


def _lookup_params_from_dialog_data(data: dict) -> dict:
    normalised = normalise_astro_imaging(data)
    return {
        "query": str(data.get("query") or "").strip(),
        "with_image": True,
        "fov_deg": float(normalised["fov_deg"]),
        "width": int(normalised["width"]),
        "height": int(normalised["height"]),
        "rotation_angle": float(normalised["rotation_angle"]),
        "camera_preset": str(normalised["preset"]),
        "camera_name": str(normalised["preset_name"]),
        "preset_label": str(normalised["preset_label"]),
        "focal_mm": float(normalised["focal_mm"]),
        "fov_y_deg": float(normalised["fov_y_deg"]),
    }


def _looks_like_html(text: str) -> bool:
    clean = str(text or "").lstrip().lower()
    return clean.startswith(
        ("<div", "<table", "<section", "<article", "<!doctype", "<html")
    )


def _markdown_to_html(text: str) -> str:
    try:
        import markdown

        return markdown.markdown(
            str(text or ""),
            extensions=["fenced_code", "tables", "sane_lists"],
            output_format="html5",
        )
    except Exception:
        escaped = html.escape(str(text or ""))
        return "<pre>" + escaped + "</pre>"


def _extract_legacy_lookup_payload(text: str) -> str:
    """Return legacy [ SECTION ] lookup text from raw or fenced markdown output."""
    body = str(text or "").strip()
    fence = re.search(
        r"```(?:text)?\s*\n(.*?)\n```", body, flags=re.IGNORECASE | re.DOTALL
    )
    payload = fence.group(1).strip() if fence else body
    if re.search(r"^\s*\[\s*[A-Z0-9 /_-]+\s*\]\s*$", payload, flags=re.MULTILINE):
        return payload
    return ""


def _legacy_lookup_sections(payload: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for raw_line in str(payload or "").splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        match = re.match(r"^\[\s*(.+?)\s*\]$", line)
        if match:
            current = re.sub(r"\s+", " ", match.group(1).strip()).upper()
            sections.setdefault(current, [])
            continue
        if current:
            sections.setdefault(current, []).append(line)
    return sections


def _legacy_lookup_items(lines: list[str]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for raw_line in lines:
        line = re.sub(r"\s+", " ", str(raw_line or "").strip())
        if not line:
            continue
        if ":" in line:
            label, value = line.split(":", 1)
            items.append((label.strip(), value.strip() or "—"))
        elif items:
            label, value = items[-1]
            items[-1] = (label, f"{value} {line}".strip())
        else:
            items.append(("", line))
    return [(label, value) for label, value in items if value]


def _legacy_lookup_items_html(items: list[tuple[str, str]]) -> str:
    bits: list[str] = []
    for label, value in items:
        safe_value = html.escape(str(value))
        if label:
            bits.append(
                '<span style="white-space:nowrap;margin-right:10px;display:inline-block;">'
                f'<span style="color:#9fb2c8;font-size:11px;font-weight:850;">{html.escape(str(label).rstrip(":"))}:</span> '
                f'<span style="color:#f3f7fc;font-size:11px;font-weight:650;">{safe_value}</span>'
                "</span>"
            )
        else:
            bits.append(
                f'<span style="color:#f3f7fc;font-size:11px;">{safe_value}</span>'
            )
    if not bits:
        return ""
    return (
        '<div style="font-size:11px;line-height:1.35;color:#d8e3ef;">'
        + " &nbsp; ".join(bits)
        + "</div>"
    )


def _legacy_lookup_panel(title: str, inner_html: str) -> str:
    if not inner_html:
        return ""
    return (
        '<div style="margin:5px 0 0 0;padding:5px 0 0 0;border-top:1px solid #202a34;color:#e9eef5;">'
        f'<div style="color:#eaf3ff;font-size:12px;font-weight:900;margin:0 0 4px 0;">{html.escape(str(title))}</div>'
        f"{inner_html}"
        "</div>"
    )


def _legacy_lookup_to_html(text: str) -> str:
    payload = _extract_legacy_lookup_payload(text)
    if not payload:
        return ""
    sections = _legacy_lookup_sections(payload)
    if not sections:
        return ""

    object_items = dict(_legacy_lookup_items(sections.get("OBJECT", [])))
    display_name = str(
        object_items.get("Main ID") or object_items.get("Name") or "Object"
    ).strip()
    object_type = str(object_items.get("Type") or "Object").strip()
    parts = [
        '<div style="margin:0 0 5px 0;padding:4px 0 2px 0;color:#e9eef5;">'
        f'<div style="font-size:16px;font-weight:900;color:#ffffff;line-height:1.15;margin:0 0 3px 0;">{html.escape(display_name)}</div>'
        '<div style="color:#d4deea;font-size:11px;line-height:1.3;">'
        f'<span style="color:#9fb2c8;font-size:11px;font-weight:850;">Type:</span> {html.escape(object_type)}'
        "</div></div>"
    ]
    for section_name, title in (
        ("POSITION", "Position"),
        ("DISTANCE", "Distance"),
        ("PHOTOMETRY", "Photometry"),
        ("MORPHOLOGY", "Morphology"),
        ("EPHEMERIS DATA", "Ephemeris data"),
    ):
        parts.append(
            _legacy_lookup_panel(
                title,
                _legacy_lookup_items_html(
                    _legacy_lookup_items(sections.get(section_name, []))
                ),
            )
        )

    aliases = [line for line in sections.get("ALIASES", []) if str(line).strip()]
    if aliases:
        alias_bits = [
            f'<span style="color:#dce7f4;font-size:11px;white-space:nowrap;">{html.escape(alias)}</span>'
            for alias in aliases[:8]
        ]
        if len(aliases) > 8:
            alias_bits.append(
                f'<span style="color:#9fc7ff;font-size:11px;font-weight:850;">+{len(aliases)-8} more</span>'
            )
        parts.append(
            _legacy_lookup_panel(
                "Aliases",
                '<div style="font-size:11px;line-height:1.35;color:#dce7f4;">'
                + '<span style="color:#5f7489;">&nbsp;·&nbsp;</span>'.join(alias_bits)
                + "</div>",
            )
        )

    known = {
        "OBJECT",
        "POSITION",
        "DISTANCE",
        "PHOTOMETRY",
        "MORPHOLOGY",
        "EPHEMERIS DATA",
        "ALIASES",
    }
    for section_name, lines in sections.items():
        if section_name in known:
            continue
        parts.append(
            _legacy_lookup_panel(
                section_name.title(),
                _legacy_lookup_items_html(_legacy_lookup_items(lines)),
            )
        )
    return "\n".join(part for part in parts if part).strip()


class FloatingSkyPreviewDialog(QDialog):
    """Resizable non-modal sky image preview window."""

    def __init__(
        self,
        parent=None,
        title: str = "Sky preview",
        pixmap: QPixmap | None = None,
    ):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self.setObjectName("astroLookupDialog")
        self.setWindowTitle(str(title or "Sky preview"))
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
        )
        self.resize(920, 620)
        self.setMinimumSize(520, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.image_label = QLabel("No sky image loaded.")
        self.image_label.setObjectName("astroLookupImagePreview")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setWordWrap(True)
        self.image_label.setMinimumSize(480, 300)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.image_label, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if pixmap is not None:
            self.set_pixmap(pixmap, title=title)

    def set_pixmap(self, pixmap: QPixmap, title: str = "Sky preview"):
        self.setWindowTitle(str(title or "Sky preview"))
        if pixmap is None or pixmap.isNull():
            self._pixmap = None
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("No sky image loaded.")
            return
        self._pixmap = pixmap
        self.image_label.setText("")
        self._rescale_pixmap()

    def _rescale_pixmap(self):
        if self._pixmap is None or self._pixmap.isNull():
            return
        target = self.image_label.size()
        if target.width() <= 4 or target.height() <= 4:
            return
        self.image_label.setPixmap(
            self._pixmap.scaled(
                target,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._rescale_pixmap)


class AstroLookupDialog(QDialog):
    def __init__(
        self,
        parent=None,
        imaging: Optional[dict] = None,
        query: str = "M31",
        include_query: bool = True,
    ):
        super().__init__(parent)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
        )
        self.include_query = bool(include_query)
        self.lookup_worker = None
        self._last_lookup_files: list[str] = []
        self._preview_pixmap: QPixmap | None = None
        self._floating_preview_dialog: FloatingSkyPreviewDialog | None = None
        self.catalog_menus = [menu for row in ASTRO_CATALOG_ROWS for menu in row]
        self.catalog_combos = []
        self.setObjectName("astroLookupDialog")
        self.setWindowTitle(
            "Astro Lookup" if include_query else "Astro Imaging Settings"
        )
        self.resize(1120 if include_query else 540, 700 if include_query else 300)
        if include_query:
            self.setMinimumSize(880, 600)

        current = normalise_astro_imaging(imaging)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(9)

        header_card = QFrame()
        header_card.setObjectName("astroLookupHeaderCard")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(12, 9, 12, 9)
        header_layout.setSpacing(2)

        title = QLabel("Astro Lookup" if include_query else "Astro Imaging Settings")
        title.setObjectName("helpDialogTitle")
        subtitle = QLabel(
            "Pick an object, run LOOKUP, then review object data and sky preview in this same window."
            if include_query
            else "Select the default camera preset, focal length, and image rotation used by ASTRO lookups."
        )
        subtitle.setObjectName("helpDialogSubtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)

        settings_card = QFrame()
        settings_card.setObjectName("astroLookupSettingsCard")
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(12, 10, 12, 10)
        settings_layout.setSpacing(8)

        control_grid = QGridLayout()
        control_grid.setContentsMargins(0, 0, 0, 0)
        control_grid.setHorizontalSpacing(10)
        control_grid.setVerticalSpacing(7)
        for column in range(4):
            control_grid.setColumnStretch(column, 1)

        def add_field(
            row: int, column: int, caption: str, widget, column_span: int = 1
        ):
            label = QLabel(caption)
            label.setObjectName("toolbarCaption")
            cell = QVBoxLayout()
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(3)
            cell.addWidget(label)
            cell.addWidget(widget)
            control_grid.addLayout(cell, row, column, 1, column_span)

        def add_layout_field(
            row: int, column: int, caption: str, field_layout, column_span: int = 1
        ):
            label = QLabel(caption)
            label.setObjectName("toolbarCaption")
            cell = QVBoxLayout()
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(3)
            cell.addWidget(label)
            cell.addLayout(field_layout)
            control_grid.addLayout(cell, row, column, 1, column_span)

        if include_query:
            self.catalog_combo = QComboBox()
            self.catalog_combo.setObjectName("astroLookupCombo")
            self.catalog_combo.setMinimumWidth(180)
            for menu_index, menu in enumerate(self.catalog_menus):
                self.catalog_combo.addItem(
                    str(menu.get("label") or "Catalog"),
                    menu_index,
                )

            self.catalog_object_combo = QComboBox()
            self.catalog_object_combo.setObjectName("astroLookupCombo")
            self.catalog_object_combo.setMinimumWidth(220)
            self.catalog_combo.currentIndexChanged.connect(self.refresh_catalog_items)
            self.catalog_object_combo.currentIndexChanged.connect(
                self.apply_catalog_selection
            )
            self.catalog_combos = [self.catalog_combo, self.catalog_object_combo]

            add_field(0, 0, "Catalog", self.catalog_combo, 1)
            add_field(0, 1, "Catalog object", self.catalog_object_combo, 3)
            self.refresh_catalog_items()

            self.query_edit = QLineEdit(str(query or "M31"))
            self.query_edit.setObjectName("astroLookupField")
            self.query_edit.setPlaceholderText(
                "Type any object: M31, NGC 7000, IC 5146…"
            )
            self.query_edit.returnPressed.connect(self.run_lookup)

            self.lookup_button = QPushButton("Run LOOKUP")
            self.lookup_button.setObjectName("primaryActionButton")
            self.lookup_button.setMinimumWidth(120)
            self.lookup_button.clicked.connect(self.run_lookup)

            object_row = QHBoxLayout()
            object_row.setContentsMargins(0, 0, 0, 0)
            object_row.setSpacing(8)
            object_row.addWidget(self.query_edit, 1)
            object_row.addWidget(self.lookup_button)
            add_layout_field(1, 0, "Object", object_row, 4)
            camera_row = 2
        else:
            self.catalog_combo = None
            self.catalog_object_combo = None
            self.query_edit = QLineEdit(str(query or "M31"))
            self.lookup_button = None
            camera_row = 0

        self.preset_combo = QComboBox()
        self.preset_combo.setObjectName("astroLookupCombo")
        for key, info in CAMERA_PRESETS.items():
            self.preset_combo.addItem(str(info["preset_label_text"]), key)
        idx = self.preset_combo.findData(current["preset"])
        self.preset_combo.setCurrentIndex(max(0, idx))
        add_field(camera_row, 0, "Camera preset", self.preset_combo, 2)

        self.focal_spin = QDoubleSpinBox()
        self.focal_spin.setObjectName("astroLookupSpin")
        self.focal_spin.setRange(50.0, 6000.0)
        self.focal_spin.setDecimals(1)
        self.focal_spin.setSingleStep(10.0)
        self.focal_spin.setSuffix(" mm")
        self.focal_spin.setValue(float(current["focal_mm"]))
        add_field(camera_row, 2, "Focal length", self.focal_spin, 1)

        self.rotation_spin = QDoubleSpinBox()
        self.rotation_spin.setObjectName("astroLookupSpin")
        self.rotation_spin.setRange(0.0, 360.0)
        self.rotation_spin.setDecimals(1)
        self.rotation_spin.setSingleStep(5.0)
        self.rotation_spin.setSuffix(" °")
        self.rotation_spin.setValue(float(current["rotation_angle"]))
        add_field(camera_row, 3, "Rotation", self.rotation_spin, 1)

        summary_row = camera_row + 1
        self.fov_label = QLabel("")
        self.fov_label.setObjectName("astroLookupPill")
        self.fov_label.setWordWrap(True)
        add_field(summary_row, 0, "Calculated FOV", self.fov_label, 2)

        self.output_label = QLabel("")
        self.output_label.setObjectName("astroLookupPill")
        self.output_label.setWordWrap(True)
        add_field(summary_row, 2, "Image output", self.output_label, 2)

        settings_layout.addLayout(control_grid)

        quick_row = QHBoxLayout()
        quick_row.setContentsMargins(0, 0, 0, 0)
        quick_row.setSpacing(8)
        reset_button = QPushButton("Reset IMX585 / 700 mm")
        reset_button.setToolTip("Restore the old FZASTRO default imaging setup")
        reset_button.clicked.connect(self.reset_defaults)
        quick_row.addWidget(reset_button)
        quick_row.addStretch(1)
        settings_layout.addLayout(quick_row)

        self.result_card = QFrame()
        self.result_card.setObjectName("astroLookupResultCard")
        result_layout = QVBoxLayout(self.result_card)
        result_layout.setContentsMargins(12, 12, 12, 12)
        result_layout.setSpacing(8)

        result_header = QHBoxLayout()
        result_header.setContentsMargins(0, 0, 0, 0)
        result_title = QLabel("LOOKUP result")
        result_title.setObjectName("astroLookupSectionTitle")
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("astroLookupStatusLabel")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        result_header.addWidget(result_title)
        result_header.addStretch(1)
        result_header.addWidget(self.status_label)
        result_layout.addLayout(result_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("astroLookupProgress")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        result_layout.addWidget(self.progress_bar)

        split_row = QHBoxLayout()
        split_row.setContentsMargins(0, 0, 0, 0)
        split_row.setSpacing(10)

        self.result_browser = QTextBrowser()
        self.result_browser.setObjectName("astroLookupResultBrowser")
        self.result_browser.setOpenExternalLinks(True)
        self.result_browser.setMinimumHeight(220)
        self.result_browser.setMinimumWidth(260)
        self.result_browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.result_browser.setHtml(self._empty_result_html())
        split_row.addWidget(self.result_browser, 1)

        image_panel = QFrame()
        image_panel.setObjectName("astroLookupImagePanel")
        image_layout = QVBoxLayout(image_panel)
        image_layout.setContentsMargins(9, 9, 9, 9)
        image_layout.setSpacing(6)
        image_header = QHBoxLayout()
        image_header.setContentsMargins(0, 0, 0, 0)
        image_title = QLabel("Sky preview")
        image_title.setObjectName("astroLookupSectionTitle")
        self.open_image_button = QPushButton("Open image")
        self.open_image_button.setEnabled(False)
        self.open_image_button.clicked.connect(self.open_floating_preview)
        image_header.addWidget(image_title)
        image_header.addStretch(1)
        image_header.addWidget(self.open_image_button)
        self.image_label = QLabel("Run LOOKUP to generate a sky image preview.")
        self.image_label.setObjectName("astroLookupImagePreview")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setWordWrap(True)
        self.image_label.setMinimumSize(520, 300)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_path_label = QLabel("")
        self.image_path_label.setObjectName("helpDialogSubtitle")
        self.image_path_label.setWordWrap(True)
        self.image_path_label.hide()
        image_layout.addLayout(image_header)
        image_layout.addWidget(self.image_label, 1)
        image_layout.addWidget(self.image_path_label)
        split_row.addWidget(image_panel, 3)
        result_layout.addLayout(split_row, 1)

        button_row = QDialogButtonBox()
        self.close_button = button_row.addButton("Close", QDialogButtonBox.AcceptRole)
        cancel_button = button_row.addButton(QDialogButtonBox.Cancel)
        button_row.accepted.connect(self.accept)
        button_row.rejected.connect(self.reject)
        self._cancel_button = cancel_button

        layout.addWidget(header_card)
        layout.addWidget(settings_card)
        if include_query:
            layout.addWidget(self.result_card, 1)
        layout.addWidget(button_row)

        self.preset_combo.currentIndexChanged.connect(self.refresh_summary)
        self.focal_spin.valueChanged.connect(self.refresh_summary)
        self.rotation_spin.valueChanged.connect(self.refresh_summary)
        self.refresh_summary()

        if not include_query:
            self.result_card.hide()

    def _empty_result_html(self) -> str:
        return self._wrap_result_html(
            """
            <div class="empty">
                <div class="empty-title">No lookup has been run yet.</div>
                <div class="empty-subtitle">Enter an object name and press <b>Run LOOKUP</b>. The result stays in this window instead of being lost in the main chat.</div>
            </div>
            """
        )

    def _wrap_result_html(self, body: str) -> str:
        return f"""
        <html>
        <head>
            <style>
                body {{
                    background: #0f1318;
                    color: #e8edf2;
                    font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif;
                    font-size: 10px;
                    line-height: 1.18;
                    margin: 0;
                }}
                a {{ color: #8fc7ff; }}
                h1 {{ font-size: 15px; margin: 0 0 4px 0; }}
                h2 {{ font-size: 12px; margin: 7px 0 3px 0; }}
                h3 {{ font-size: 11px; margin: 6px 0 2px 0; }}
                p {{ margin: 2px 0; }}
                ul, ol {{ margin: 2px 0 4px 15px; padding: 0; }}
                li {{ margin: 1px 0; }}
                strong, b {{ color: #cfe4ff; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #2c3743; padding: 2px 4px; }}
                th {{ background: #151d26; color: #f2f6fb; }}
                pre, code {{
                    background: #0a0e12;
                    color: #dfe7ef;
                    border: 1px solid #26313c;
                    border-radius: 7px;
                    font-family: 'Cascadia Code', Consolas, monospace;
                }}
                pre {{ padding: 5px; white-space: pre-wrap; }}
                .empty {{
                    border: 1px dashed #33404d;
                    border-radius: 12px;
                    padding: 8px;
                    background: #10161d;
                    color: #a8b3bf;
                }}
                .empty-title {{ color: #f0f4f8; font-size: 12px; font-weight: 800; margin-bottom: 3px; }}
                .empty-subtitle {{ color: #9ba7b4; }}
                .status-card {{
                    border: 1px solid #303b47;
                    border-radius: 12px;
                    padding: 8px;
                    background: #111820;
                }}
                .status-title {{ color: #f0f4f8; font-size: 12px; font-weight: 800; margin-bottom: 3px; }}
                .status-body {{ color: #aab5c1; }}
            </style>
        </head>
        <body>{body}</body>
        </html>
        """

    def _status_html(self, title: str, body: str = "") -> str:
        return self._wrap_result_html(
            '<div class="status-card">'
            f'<div class="status-title">{html.escape(str(title))}</div>'
            f'<div class="status-body">{html.escape(str(body))}</div>'
            "</div>"
        )

    def refresh_catalog_items(self, _index: int | None = None):
        if not self.include_query:
            return
        menu_combo = getattr(self, "catalog_combo", None)
        object_combo = getattr(self, "catalog_object_combo", None)
        if menu_combo is None or object_combo is None:
            return

        menu_index = int(menu_combo.currentIndex())
        if menu_index < 0 or menu_index >= len(self.catalog_menus):
            return

        menu = self.catalog_menus[menu_index]
        object_combo.blockSignals(True)
        object_combo.clear()
        object_combo.addItem(str(menu.get("placeholder") or "Select object"), "")
        for item in menu.get("items", []):
            object_combo.addItem(
                str(item.get("label") or item.get("query") or ""),
                str(item.get("query") or ""),
            )
        object_combo.blockSignals(False)

    def apply_catalog_selection(self, _index: int | None = None):
        if not self.include_query:
            return
        object_combo = getattr(self, "catalog_object_combo", None)
        if object_combo is None:
            return
        query = str(object_combo.currentData() or "").strip()
        if not query:
            return
        self.query_edit.setText(query)
        self.query_edit.setFocus()

    def reset_defaults(self):
        idx = self.preset_combo.findData(DEFAULT_ASTRO_IMAGING["preset"])
        self.preset_combo.setCurrentIndex(max(0, idx))
        self.focal_spin.setValue(float(DEFAULT_ASTRO_IMAGING["focal_mm"]))
        self.rotation_spin.setValue(float(DEFAULT_ASTRO_IMAGING["rotation_angle"]))
        self.refresh_summary()

    def refresh_summary(self):
        data = self.result_data(include_query=False)
        self.fov_label.setText(f"{data['fov_deg']:.3f}° × {data['fov_y_deg']:.3f}°")
        self.output_label.setText(
            f"{data['width']} × {data['height']} preview from {data['native_width']} × {data['native_height']} sensor"
        )

    def result_data(self, include_query: bool = True) -> dict:
        preset = str(self.preset_combo.currentData() or DEFAULT_ASTRO_IMAGING["preset"])
        data = normalise_astro_imaging(
            {
                "preset": preset,
                "focal_mm": float(self.focal_spin.value()),
                "rotation_angle": float(self.rotation_spin.value()),
            }
        )
        if include_query and self.include_query:
            data["query"] = self.query_edit.text().strip()
        return data

    def run_lookup(self):
        if not self.include_query:
            return
        if self.lookup_worker is not None and self.lookup_worker.isRunning():
            return

        data = self.result_data(include_query=True)
        clean_query = str(data.get("query") or "").strip()
        if not clean_query:
            QMessageBox.warning(self, "Astro Lookup", "Enter an object name first.")
            self.query_edit.setFocus()
            return

        self._last_lookup_files = []
        self._preview_pixmap = None
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText(
            "Sky image preview will appear after the lookup returns coordinates."
        )
        self.image_label.setToolTip("")
        self.open_image_button.setEnabled(False)
        self.image_path_label.setText("")
        self.image_path_label.hide()
        self.status_label.setText(f"Running {clean_query}…")
        self.result_browser.setHtml(
            self._status_html(
                f"Looking up {clean_query}",
                "Resolving object data and generating the preview in this window.",
            )
        )
        self.progress_bar.show()
        self._set_lookup_controls_enabled(False)

        from ..workers import AstroWorker

        worker = AstroWorker("lookup", _lookup_params_from_dialog_data(data))
        self.lookup_worker = worker
        worker.finished_astro.connect(self.handle_lookup_finished)
        worker.stopped_astro.connect(self.handle_lookup_stopped)
        worker.error_received.connect(self.handle_lookup_error)
        worker.finished.connect(self.handle_lookup_worker_finished)
        worker.start()

    def _set_lookup_controls_enabled(self, enabled: bool):
        widgets = [
            self.query_edit,
            self.preset_combo,
            self.focal_spin,
            self.rotation_spin,
            getattr(self, "lookup_button", None),
            getattr(self, "close_button", None),
        ]
        for widget in widgets:
            if widget is not None:
                widget.setEnabled(bool(enabled))
        for combo in getattr(self, "catalog_combos", []):
            combo.setEnabled(bool(enabled))

    def handle_lookup_finished(self, text, source, files, elapsed, success):
        self.progress_bar.hide()
        self._set_lookup_controls_enabled(True)
        clean_text = str(text or "").strip()
        self._last_lookup_files = [str(path) for path in list(files or [])]

        if not clean_text:
            clean_text = "Astro lookup finished with no output."

        if success:
            self.status_label.setText(f"Finished • {float(elapsed):.2f}s")
            self.result_browser.setHtml(self._render_result_text(clean_text))
        else:
            self.status_label.setText(f"Problem • {float(elapsed):.2f}s")
            self.result_browser.setHtml(
                self._status_html("Astro lookup problem", clean_text)
            )

        self._show_first_image_file(self._last_lookup_files)

    def _render_result_text(self, text: str) -> str:
        body = str(text or "").strip()
        if not body:
            return self._status_html("No data returned")
        if _looks_like_html(body):
            return self._wrap_result_html(body)
        legacy_html = _legacy_lookup_to_html(body)
        if legacy_html:
            return self._wrap_result_html(legacy_html)
        return self._wrap_result_html(_markdown_to_html(body))

    def _show_first_image_file(self, files: list[str]):
        image_path = None
        for candidate in files:
            path = Path(str(candidate))
            if path.exists() and path.suffix.lower() in {
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".bmp",
            }:
                image_path = path
                break

        if image_path is None:
            self._preview_pixmap = None
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("No sky image file was returned for this object.")
            self.image_path_label.setText("")
            self.image_path_label.hide()
            self.image_label.setToolTip("")
            return

        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            self._preview_pixmap = None
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(
                f"Image returned, but Qt could not load it:\n{image_path}"
            )
            self.image_path_label.setText("")
            self.image_path_label.hide()
            self.image_label.setToolTip("")
            return

        self._preview_pixmap = pixmap
        self.image_label.setText("")
        self.image_label.setToolTip(str(image_path))
        self.image_path_label.setText(str(image_path))
        self.image_path_label.hide()
        self.open_image_button.setEnabled(True)
        self._rescale_preview_pixmap()
        self._update_open_floating_preview()

    def open_floating_preview(self):
        if self._preview_pixmap is None or self._preview_pixmap.isNull():
            return
        title = f"Sky preview - {self.query_edit.text().strip() or 'LOOKUP'}"
        if self._floating_preview_dialog is None:
            dialog = FloatingSkyPreviewDialog(
                self, title=title, pixmap=self._preview_pixmap
            )
            dialog.destroyed.connect(
                lambda *_: setattr(self, "_floating_preview_dialog", None)
            )
            self._floating_preview_dialog = dialog
        else:
            self._floating_preview_dialog.set_pixmap(self._preview_pixmap, title=title)
        self._floating_preview_dialog.show()
        self._floating_preview_dialog.raise_()
        self._floating_preview_dialog.activateWindow()

    def _update_open_floating_preview(self):
        dialog = self._floating_preview_dialog
        if dialog is None or not dialog.isVisible():
            return
        if self._preview_pixmap is None or self._preview_pixmap.isNull():
            return
        title = f"Sky preview - {self.query_edit.text().strip() or 'LOOKUP'}"
        dialog.set_pixmap(self._preview_pixmap, title=title)

    def _rescale_preview_pixmap(self):
        if self._preview_pixmap is None or self._preview_pixmap.isNull():
            return
        target = self.image_label.size()
        if target.width() <= 4 or target.height() <= 4:
            return
        self.image_label.setPixmap(
            self._preview_pixmap.scaled(
                target,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._rescale_preview_pixmap)

    def handle_lookup_stopped(self, elapsed):
        self.progress_bar.hide()
        self._set_lookup_controls_enabled(True)
        self.status_label.setText(f"Stopped • {float(elapsed):.2f}s")
        self.result_browser.setHtml(self._status_html("Astro lookup stopped"))

    def handle_lookup_error(self, error):
        self.progress_bar.hide()
        self._set_lookup_controls_enabled(True)
        self.status_label.setText("Failed")
        self.result_browser.setHtml(
            self._status_html("Astro lookup failed", str(error))
        )

    def handle_lookup_worker_finished(self):
        worker = self.sender()
        if worker is getattr(self, "lookup_worker", None):
            self.lookup_worker = None
        if worker is not None:
            worker.deleteLater()

    def _stop_lookup_worker(self):
        worker = getattr(self, "lookup_worker", None)
        if worker is not None and worker.isRunning():
            try:
                worker.stop()
            except Exception:
                pass

    def reject(self):
        self._stop_lookup_worker()
        super().reject()

    def closeEvent(self, event):
        self._stop_lookup_worker()
        super().closeEvent(event)


def choose_astro_lookup_settings(
    parent, imaging: Optional[dict] = None, query: str = "M31"
) -> Optional[dict]:
    dialog = AstroLookupDialog(parent, imaging=imaging, query=query, include_query=True)
    if dialog.exec() != QDialog.Accepted:
        return None
    data = dialog.result_data(include_query=True)
    if not str(data.get("query") or "").strip():
        return None
    return data


def choose_astro_imaging_settings(
    parent, imaging: Optional[dict] = None
) -> Optional[dict]:
    dialog = AstroLookupDialog(parent, imaging=imaging, include_query=False)
    if dialog.exec() != QDialog.Accepted:
        return None
    return dialog.result_data(include_query=False)
