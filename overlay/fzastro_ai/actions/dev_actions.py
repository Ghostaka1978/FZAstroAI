from __future__ import annotations

from ..ui.dev_workbench_dialog import open_dev_workbench_dialog


class DevActionsMixin:
    """Main-window action hooks for the AI Developer Workbench."""

    def open_dev_workbench(self):
        open_dev_workbench_dialog(self)
