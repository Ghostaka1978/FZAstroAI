from __future__ import annotations

import math
from typing import Dict, Optional

from .astro_object_catalogs import ASTRO_CATALOG_ROWS

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
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


class AstroLookupDialog(QDialog):
    def __init__(
        self,
        parent=None,
        imaging: Optional[dict] = None,
        query: str = "M31",
        include_query: bool = True,
    ):
        super().__init__(parent)
        self.include_query = bool(include_query)
        self.setObjectName("astroLookupDialog")
        self.setWindowTitle(
            "Astro Lookup" if include_query else "Astro Imaging Settings"
        )
        self.resize(1080 if include_query else 540, 660 if include_query else 300)

        current = normalise_astro_imaging(imaging)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Astro Lookup" if include_query else "Astro Imaging Settings")
        title.setObjectName("helpDialogTitle")
        subtitle = QLabel(
            "Select the object and imaging geometry used for the migrated FZASTRO sky image."
            if include_query
            else "Select the default camera preset, focal length, and image rotation used by ASTRO lookups."
        )
        subtitle.setObjectName("helpDialogSubtitle")
        subtitle.setWordWrap(True)

        self.catalog_combos = []
        catalog_grid = None
        if include_query:
            catalog_title = QLabel("Migrated FZASTRO object menus")
            catalog_title.setObjectName("toolbarCaption")
            catalog_hint = QLabel(
                "Pick from the original FZASTRO catalogs, or type any object name manually below."
            )
            catalog_hint.setObjectName("helpDialogSubtitle")
            catalog_hint.setWordWrap(True)
            catalog_grid = QGridLayout()
            catalog_grid.setContentsMargins(0, 0, 0, 0)
            catalog_grid.setHorizontalSpacing(12)
            catalog_grid.setVerticalSpacing(8)
            for row_idx, row in enumerate(ASTRO_CATALOG_ROWS):
                for col_idx, menu in enumerate(row):
                    label = QLabel(str(menu.get("label") or "Catalog"))
                    label.setObjectName("toolbarCaption")
                    combo = QComboBox()
                    combo.setMinimumWidth(210)
                    combo.setMaximumWidth(260)
                    combo.addItem(str(menu.get("placeholder") or "Select object"), "")
                    for item in menu.get("items", []):
                        combo.addItem(
                            str(item.get("label") or item.get("query") or ""),
                            str(item.get("query") or ""),
                        )
                    combo.currentIndexChanged.connect(
                        lambda _index, selected_combo=combo: self.apply_catalog_selection(
                            selected_combo
                        )
                    )
                    self.catalog_combos.append(combo)

                    cell = QVBoxLayout()
                    cell.setContentsMargins(0, 0, 0, 0)
                    cell.setSpacing(3)
                    cell.addWidget(label)
                    cell.addWidget(combo)
                    catalog_grid.addLayout(cell, row_idx, col_idx)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.query_edit = QLineEdit(str(query or "M31"))
        self.query_edit.setPlaceholderText("e.g. M31, NGC 7000, IC 5146")
        if include_query:
            form.addRow("Object", self.query_edit)

        self.preset_combo = QComboBox()
        for key, info in CAMERA_PRESETS.items():
            self.preset_combo.addItem(str(info["preset_label_text"]), key)
        idx = self.preset_combo.findData(current["preset"])
        self.preset_combo.setCurrentIndex(max(0, idx))
        form.addRow("Camera preset", self.preset_combo)

        self.focal_spin = QDoubleSpinBox()
        self.focal_spin.setRange(50.0, 6000.0)
        self.focal_spin.setDecimals(1)
        self.focal_spin.setSingleStep(10.0)
        self.focal_spin.setSuffix(" mm")
        self.focal_spin.setValue(float(current["focal_mm"]))
        form.addRow("Focal length", self.focal_spin)

        self.rotation_spin = QDoubleSpinBox()
        self.rotation_spin.setRange(0.0, 360.0)
        self.rotation_spin.setDecimals(1)
        self.rotation_spin.setSingleStep(5.0)
        self.rotation_spin.setSuffix(" °")
        self.rotation_spin.setValue(float(current["rotation_angle"]))
        form.addRow("Image rotation", self.rotation_spin)

        self.fov_label = QLabel("")
        self.fov_label.setObjectName("toolbarCaption")
        self.fov_label.setWordWrap(True)
        form.addRow("Calculated FOV", self.fov_label)

        self.output_label = QLabel("")
        self.output_label.setObjectName("toolbarCaption")
        self.output_label.setWordWrap(True)
        form.addRow("Image output", self.output_label)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        quick_row = QHBoxLayout()
        quick_row.setContentsMargins(0, 0, 0, 0)
        quick_row.setSpacing(8)
        reset_button = QPushButton("Reset to IMX585 / 700 mm")
        reset_button.setToolTip("Restore the old FZASTRO default imaging setup")
        reset_button.clicked.connect(self.reset_defaults)
        quick_row.addWidget(reset_button)
        quick_row.addStretch(1)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        if include_query and catalog_grid is not None:
            layout.addWidget(catalog_title)
            layout.addWidget(catalog_hint)
            layout.addLayout(catalog_grid)
        layout.addLayout(form, 1)
        layout.addLayout(quick_row)
        layout.addWidget(button_box)

        self.preset_combo.currentIndexChanged.connect(self.refresh_summary)
        self.focal_spin.valueChanged.connect(self.refresh_summary)
        self.rotation_spin.valueChanged.connect(self.refresh_summary)
        self.refresh_summary()

    def apply_catalog_selection(self, selected_combo: QComboBox):
        if not self.include_query:
            return
        query = str(selected_combo.currentData() or "").strip()
        if not query:
            return
        self.query_edit.setText(query)
        self.query_edit.setFocus()
        for combo in getattr(self, "catalog_combos", []):
            if combo is selected_combo:
                continue
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)

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
