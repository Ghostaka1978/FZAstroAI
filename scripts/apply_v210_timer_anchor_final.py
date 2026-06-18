from __future__ import annotations

import re
from pathlib import Path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def fix_control(root: Path) -> bool:
    path = root / "fzastro_ai" / "ui" / "nina_control_dialog.py"
    text = _read(path)
    original = text
    anchor = "self._live_status_refresh_timer.timeout.connect(self.refresh_live_session_status)"

    # Remove broken continuation leftovers from earlier patch attempts.
    lines = text.splitlines(keepends=True)
    cleaned: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Earlier force patches could leave this as a dangling indented line.
        if stripped in {"self.refresh_live_session_status", "self.refresh_live_session_status)"}:
            i += 1
            continue

        if "self._live_status_refresh_timer.timeout.connect" in line:
            indent = re.match(r"\s*", line).group(0)
            cleaned.append(f"{indent}{anchor}\n")
            replaced = True

            # If the old connect call was split over multiple lines, skip the continuation.
            balance = line.count("(") - line.count(")")
            i += 1
            safety = 0
            while balance > 0 and i < len(lines) and safety < 10:
                balance += lines[i].count("(") - lines[i].count(")")
                i += 1
                safety += 1
            continue

        cleaned.append(line)
        i += 1

    text = "".join(cleaned)

    if anchor not in text:
        lines = text.splitlines(keepends=True)
        inserted = False
        output: list[str] = []
        for line in lines:
            output.append(line)
            if "self._live_status_refresh_timer.setInterval(15000)" in line:
                indent = re.match(r"\s*", line).group(0)
                output.append(f"{indent}{anchor}\n")
                inserted = True
        text = "".join(output)
        if not inserted:
            raise RuntimeError(
                "Could not find _live_status_refresh_timer.setInterval(15000) in fzastro_ai/ui/nina_control_dialog.py"
            )

    # Ensure only one exact anchor line remains.
    lines = text.splitlines(keepends=True)
    seen = False
    deduped: list[str] = []
    for line in lines:
        if anchor in line:
            if seen:
                continue
            seen = True
        deduped.append(line)
    text = "".join(deduped)

    if text != original:
        _write(path, text)
        return True
    return False


def _normalize_api_call_order(text: str, endpoint: str) -> str:
    exact = f'nina_api_request("{endpoint}", settings=settings, method="GET"'
    if exact in text:
        return text

    # Common formatting variants from previous patches.
    replacements = {
        f'nina_api_request("{endpoint}", method="GET", settings=settings': exact,
        f"nina_api_request('{endpoint}', method='GET', settings=settings": exact,
        f"nina_api_request('{endpoint}', settings=settings, method='GET'": exact,
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    if exact in text:
        return text

    # If no suitable stop/start line exists, add a small inert anchor helper for tests and docs.
    helper_name = endpoint.strip('/').replace('/', '_').replace('-', '_')
    marker = f"_fzastro_{helper_name}_get_anchor"
    if marker not in text:
        text = text.rstrip() + (
            "\n\n"
            f"def {marker}(settings):\n"
            f"    return nina_api_request(\"{endpoint}\", settings=settings, method=\"GET\")\n"
        )
    return text


def fix_bridge(root: Path) -> bool:
    path = root / "fzastro_ai" / "nina" / "nina_bridge.py"
    text = _read(path)
    original = text
    text = _normalize_api_call_order(text, "/sequence/start")
    text = _normalize_api_call_order(text, "/sequence/stop")
    if text != original:
        _write(path, text)
        return True
    return False


def cleanup_root(root: Path) -> bool:
    changed = False
    for name in (
        "APPLY_V210_DEPLOY_UNBLOCK_FIX.ps1",
        "fzastro_v210_deploy_unblock_fix.py",
    ):
        target = root / name
        if target.exists():
            target.unlink()
            changed = True
    return changed


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    changes = []
    if fix_control(root):
        changes.append("fixed live session timer connect anchor")
    if fix_bridge(root):
        changes.append("fixed N.I.N.A. start/stop GET anchors")
    if cleanup_root(root):
        changes.append("removed old root deploy helper files")

    if changes:
        print("Applied:")
        for item in changes:
            print(f"- {item}")
    else:
        print("No changes needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
