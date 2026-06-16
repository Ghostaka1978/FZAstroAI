from __future__ import annotations

import sys


def _run_web_companion() -> int:
    """Run the packaged Web Companion server from the PyInstaller EXE."""
    try:
        sys.argv.remove("--web-companion")
    except ValueError:
        pass

    from fzastro_ai.web_companion.__main__ import main as web_main

    return int(web_main() or 0)


def _run_desktop_app() -> int:
    from fzastro_ai.app import main as desktop_main

    return int(desktop_main() or 0)


if __name__ == "__main__":
    if "--web-companion" in sys.argv:
        raise SystemExit(_run_web_companion())

    raise SystemExit(_run_desktop_app())
