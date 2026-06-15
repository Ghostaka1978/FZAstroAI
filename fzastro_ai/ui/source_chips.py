from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..routing.source_tags import (
    SOURCE_TAG_LABELS,
    SOURCE_TAG_TOOLTIPS,
    normalize_response_source_tags,
    source_tags_tooltip,
)


def add_source_header_widget(message_widget):
    """Add provenance chips to an assistant message widget."""
    if message_widget.is_user_message:
        return

    tags = normalize_response_source_tags(message_widget.source_tags)

    if not tags:
        return

    header = QWidget()
    header.setObjectName("sourceHeader")
    header.setToolTip(source_tags_tooltip(tags))

    header_layout = QHBoxLayout(header)
    header_layout.setContentsMargins(0, 0, 0, 6)
    header_layout.setSpacing(6)

    label = QLabel("Source")
    label.setObjectName("sourceHeaderLabel")
    header_layout.addWidget(label)

    for tag in tags[:5]:
        chip = QLabel(SOURCE_TAG_LABELS.get(tag, tag))
        chip.setObjectName("sourceChip")
        chip.setProperty("sourceType", tag)
        chip.setAlignment(Qt.AlignCenter)
        chip.setToolTip(SOURCE_TAG_TOOLTIPS.get(tag, ""))
        header_layout.addWidget(chip)

    if len(tags) > 5:
        more_chip = QLabel(f"+{len(tags) - 5}")
        more_chip.setObjectName("sourceChip")
        more_chip.setProperty("sourceType", "app")
        more_chip.setAlignment(Qt.AlignCenter)
        more_chip.setToolTip(source_tags_tooltip(tags[5:]))
        header_layout.addWidget(more_chip)

    header_layout.addStretch()
    message_widget.response_layout.addWidget(header)

    if not message_widget.streaming:
        message_widget._fade_in_child_widget(header, duration=170, start_opacity=0.0)
