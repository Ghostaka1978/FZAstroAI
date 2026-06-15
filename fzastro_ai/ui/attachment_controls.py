"""Attachment row UI helpers for FZAstro AI.

Extracted from MainLayoutMixin without behavior changes. The mixin expects the
main window to provide attached_files, attachment_layout, and
attachment_row_container.
"""

from PySide6.QtWidgets import QFileDialog

from .message_widgets import AttachmentChip


class AttachmentControlsMixin:

    def attach_files(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Attach files",
            "",
            "Supported Files (*.jpg *.jpeg *.png *.webp *.pdf *.txt *.md *.csv *.json *.xml *.docx *.xlsx *.pptx *.py);;All Files (*)",
        )

        self.add_files(file_paths)

    def add_files(self, file_paths):
        for file_path in file_paths:
            if file_path not in self.attached_files:
                self.attached_files.append(file_path)

        self.render_attachments()

    def render_attachments(self):
        while self.attachment_layout.count() > 0:
            item = self.attachment_layout.takeAt(0)
            widget = item.widget()

            if widget:
                widget.deleteLater()

        has_attachments = bool(self.attached_files)
        self.attachment_row_container.setVisible(has_attachments)

        for file_path in self.attached_files:
            chip = AttachmentChip(file_path)
            chip.remove_requested.connect(self.remove_attachment)
            self.attachment_layout.addWidget(chip)

        self.attachment_layout.addStretch()

    def remove_attachment(self, file_path):
        self.attached_files = [
            path for path in self.attached_files if path != file_path
        ]
        self.render_attachments()
