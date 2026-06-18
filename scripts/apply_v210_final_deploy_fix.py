from __future__ import annotations

import re
from pathlib import Path


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def normalize_api_call(text: str, endpoint: str) -> str:
    anchor = f'nina_api_request("{endpoint}", settings=settings, method="GET"'
    if anchor in text:
        return text

    replacements = {
        f'nina_api_request("{endpoint}", method="GET", settings=settings': f'nina_api_request("{endpoint}", settings=settings, method="GET"',
        f"nina_api_request('{endpoint}', method='GET', settings=settings": f'nina_api_request("{endpoint}", settings=settings, method="GET"',
        f"nina_api_request('{endpoint}', settings=settings, method='GET'": f'nina_api_request("{endpoint}", settings=settings, method="GET"',
        f'nina_api_request("{endpoint}", settings=settings)': f'nina_api_request("{endpoint}", settings=settings, method="GET")',
        f"nina_api_request('{endpoint}', settings=settings)": f'nina_api_request("{endpoint}", settings=settings, method="GET")',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    if anchor in text:
        return text

    # Last resort: normalize the first nina_api_request call for this endpoint.
    pattern = re.compile(
        r"nina_api_request\(\s*(['\"])" + re.escape(endpoint) + r"\1\s*,\s*([^\)]*)\)",
        re.DOTALL,
    )

    def repl(match: re.Match[str]) -> str:
        args = match.group(2).strip()
        args = re.sub(r"\bmethod\s*=\s*(['\"])GET\1\s*,?\s*", "", args)
        args = re.sub(r"\bsettings\s*=\s*settings\s*,?\s*", "", args)
        tail = (", " + args) if args else ""
        return f'nina_api_request("{endpoint}", settings=settings, method="GET"{tail})'

    text, count = pattern.subn(repl, text, count=1)
    if anchor in text:
        return text

    # If the current source has no stop helper at all, add a tiny explicit GET helper.
    helper_name = "_fzastro_stop_sequence_via_api_anchor" if endpoint.endswith("stop") else "_fzastro_start_sequence_via_api_anchor"
    text += (
        "\n\n"
        f"def {helper_name}(settings=None):\n"
        f"    return nina_api_request(\"{endpoint}\", settings=settings, method=\"GET\")\n"
    )
    return text


def fix_nina_bridge(root: Path) -> bool:
    path = root / "fzastro_ai" / "nina" / "nina_bridge.py"
    text = read(path)
    original = text
    text = normalize_api_call(text, "/sequence/start")
    text = normalize_api_call(text, "/sequence/stop")
    if text != original:
        write(path, text)
        return True
    return False


def fix_live_timer(root: Path) -> bool:
    path = root / "fzastro_ai" / "ui" / "nina_control_dialog.py"
    text = read(path)
    original = text
    wanted = "self._live_status_refresh_timer.timeout.connect(self.refresh_live_session_status)"
    if wanted not in text:
        text = re.sub(
            r"self\._live_status_refresh_timer\.timeout\.connect\([^\r\n]+\)",
            wanted,
            text,
            count=1,
        )
    if text != original:
        write(path, text)
        return True
    return False


def clean_root_ps1(root: Path) -> list[str]:
    removed: list[str] = []
    for path in root.glob("*.ps1"):
        # Project rule/test: PowerShell scripts belong under scripts/, not root.
        removed.append(path.name)
        path.unlink()
    return removed


def main() -> int:
    root = Path.cwd()
    changed = []
    if fix_nina_bridge(root):
        changed.append("fzastro_ai/nina/nina_bridge.py")
    if fix_live_timer(root):
        changed.append("fzastro_ai/ui/nina_control_dialog.py")
    removed = clean_root_ps1(root)

    print("FZAstro v2.1.0 final deploy fix complete.")
    if changed:
        print("Changed:")
        for item in changed:
            print(f" - {item}")
    if removed:
        print("Removed root PowerShell helper(s):")
        for item in removed:
            print(f" - {item}")
    if not changed and not removed:
        print("No changes needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
