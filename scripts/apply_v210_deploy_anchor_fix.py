from __future__ import annotations

import re
import sys
from pathlib import Path


def _project_root() -> Path:
    here = Path(__file__).resolve()
    if here.parent.name.lower() == "scripts":
        return here.parent.parent
    return Path.cwd().resolve()


def _write_if_changed(path: Path, before: str, after: str) -> bool:
    if before == after:
        return False
    path.write_text(after, encoding="utf-8")
    return True


def fix_nina_bridge(root: Path) -> bool:
    path = root / "fzastro_ai" / "nina" / "nina_bridge.py"
    text = path.read_text(encoding="utf-8")
    original = text

    # Normalize known formatting/order variants first.
    replacements = {
        'nina_api_request("/sequence/start", method="GET", settings=settings': 'nina_api_request("/sequence/start", settings=settings, method="GET"',
        "nina_api_request('/sequence/start', method='GET', settings=settings": 'nina_api_request("/sequence/start", settings=settings, method="GET"',
        "nina_api_request('/sequence/start', settings=settings, method='GET'": 'nina_api_request("/sequence/start", settings=settings, method="GET"',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    required = 'nina_api_request("/sequence/start", settings=settings, method="GET"'
    if required not in text:
        # Replace the body of start_sequence_via_api with a stable source anchor.
        pattern = re.compile(
            r"(def\s+start_sequence_via_api\s*\([^\)]*\)\s*->\s*NinaApiResponse:\n"
            r"(?:    .*\n)*?"  # docstring/body intro
            r")(?=\n\ndef\s+stop_sequence_via_api)",
            re.MULTILINE,
        )
        match = pattern.search(text)
        if not match:
            raise RuntimeError("Could not find start_sequence_via_api in fzastro_ai/nina/nina_bridge.py")

        header_and_doc = match.group(1)
        # Preserve the function docstring if present, but replace all executable body lines
        # after the final triple quote. If no docstring is present, keep only the def line.
        if '"""' in header_and_doc:
            last_doc = header_and_doc.rfind('"""')
            header_and_doc = header_and_doc[: last_doc + 3] + "\n\n"
        else:
            header_and_doc = header_and_doc.splitlines()[0] + "\n"
        replacement = header_and_doc + '    return nina_api_request("/sequence/start", settings=settings, method="GET", timeout=10.0)\n'
        text = text[: match.start()] + replacement + text[match.end() :]

    if required not in text:
        raise RuntimeError("START VIA API anchor is still missing after patch.")

    return _write_if_changed(path, original, text)


def fix_control_dialog(root: Path) -> bool:
    path = root / "fzastro_ai" / "ui" / "nina_control_dialog.py"
    text = path.read_text(encoding="utf-8")
    original = text

    required = "self._live_status_refresh_timer.timeout.connect(self.refresh_live_session_status)"
    if required not in text:
        # One-line connect variants, including lambda/wrapper calls.
        text = re.sub(
            r"self\._live_status_refresh_timer\.timeout\.connect\([^\r\n]*\)",
            required,
            text,
            count=1,
        )

    if required not in text:
        raise RuntimeError("LIVE SESSION STATUS timer anchor is still missing after patch.")

    # Keep the intended slower refresh cadence.
    text = text.replace("self._live_status_refresh_timer.setInterval(5000)", "self._live_status_refresh_timer.setInterval(15000)")

    return _write_if_changed(path, original, text)


def main() -> int:
    root = _project_root()
    if not (root / "fzastro_ai").exists():
        print(f"ERROR: Could not find fzastro_ai under project root: {root}", file=sys.stderr)
        return 2

    changed = []
    if fix_nina_bridge(root):
        changed.append("fzastro_ai/nina/nina_bridge.py")
    if fix_control_dialog(root):
        changed.append("fzastro_ai/ui/nina_control_dialog.py")

    if changed:
        print("Patched:")
        for item in changed:
            print(f"- {item}")
    else:
        print("Already patched. No file changes needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
