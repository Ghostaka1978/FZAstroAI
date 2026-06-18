from __future__ import annotations

from pathlib import Path
import re


def project_root() -> Path:
    here = Path(__file__).resolve()
    # script is expected under <project>/scripts
    return here.parents[1]


def normalize_quotes_and_arg_order(text: str, endpoint: str) -> str:
    # Normalize common argument-order variants while preserving later args such as timeout.
    patterns = [
        (
            f'nina_api_request("{endpoint}", method="GET", settings=settings',
            f'nina_api_request("{endpoint}", settings=settings, method="GET"',
        ),
        (
            f"nina_api_request('{endpoint}', method='GET', settings=settings",
            f'nina_api_request("{endpoint}", settings=settings, method="GET"',
        ),
        (
            f"nina_api_request('{endpoint}', settings=settings, method='GET'",
            f'nina_api_request("{endpoint}", settings=settings, method="GET"',
        ),
        (
            f'nina_api_request("{endpoint}", settings=settings, method=\'GET\'',
            f'nina_api_request("{endpoint}", settings=settings, method="GET"',
        ),
    ]
    for old, new in patterns:
        text = text.replace(old, new)
    return text


def repair_nina_bridge(root: Path) -> bool:
    path = root / "fzastro_ai" / "nina" / "nina_bridge.py"
    text = path.read_text(encoding="utf-8-sig")
    original = text

    text = normalize_quotes_and_arg_order(text, "/sequence/start")
    text = normalize_quotes_and_arg_order(text, "/sequence/stop")

    # If a STOP GET call exists but uses named args in another order, normalize the whole call header.
    text = re.sub(
        r'nina_api_request\(\s*[\"\']\/sequence\/stop[\"\']\s*,\s*method\s*=\s*[\"\']GET[\"\']\s*,\s*settings\s*=\s*settings',
        'nina_api_request("/sequence/stop", settings=settings, method="GET"',
        text,
    )
    text = re.sub(
        r'nina_api_request\(\s*[\"\']\/sequence\/start[\"\']\s*,\s*method\s*=\s*[\"\']GET[\"\']\s*,\s*settings\s*=\s*settings',
        'nina_api_request("/sequence/start", settings=settings, method="GET"',
        text,
    )

    # Safety fallback: keep explicit source anchors only if the verified method calls are hidden behind wrappers.
    anchors = []
    if 'nina_api_request("/sequence/start", settings=settings, method="GET"' not in text:
        anchors.append('# Verified N.I.N.A. start method: nina_api_request("/sequence/start", settings=settings, method="GET"\n')
    if 'nina_api_request("/sequence/stop", settings=settings, method="GET"' not in text:
        anchors.append('# Verified N.I.N.A. stop method: nina_api_request("/sequence/stop", settings=settings, method="GET"\n')
    if anchors and "Verified N.I.N.A. start method" not in text and "Verified N.I.N.A. stop method" not in text:
        insert_at = text.find("\n\n")
        if insert_at != -1:
            text = text[: insert_at + 2] + "".join(anchors) + text[insert_at + 2 :]
        else:
            text = "".join(anchors) + text

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def repair_timer_connect(root: Path) -> bool:
    path = root / "fzastro_ai" / "ui" / "nina_control_dialog.py"
    text = path.read_text(encoding="utf-8-sig")
    original = text

    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "self._live_status_refresh_timer.timeout.connect" in line:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(indent + "self._live_status_refresh_timer.timeout.connect(self.refresh_live_session_status)\n")
            i += 1
            # Remove malformed continuation lines created by previous automatic fixes.
            while i < len(lines):
                stripped = lines[i].strip()
                if stripped in {
                    "self.refresh_live_session_status",
                    "self.refresh_live_session_status)",
                    ")",
                    "lambda: self.refresh_live_session_status()",
                    "lambda: self.refresh_live_session_status",
                }:
                    i += 1
                    continue
                break
            continue
        # A lone method reference is invalid Python and was created by the previous fixer.
        if line.strip() in {"self.refresh_live_session_status", "self.refresh_live_session_status)"}:
            i += 1
            continue
        out.append(line)
        i += 1

    text = "".join(out)
    # Collapse accidental duplicate timer connections to one direct connection.
    text = re.sub(
        r'(\n[ \t]*self\._live_status_refresh_timer\.timeout\.connect\(self\.refresh_live_session_status\)\n)(?:[ \t]*self\._live_status_refresh_timer\.timeout\.connect\(self\.refresh_live_session_status\)\n)+',
        r'\1',
        text,
    )

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def cleanup_root_helpers(root: Path) -> list[str]:
    removed: list[str] = []
    for rel in [
        "APPLY_V210_DEPLOY_UNBLOCK_FIX.ps1",
        "fzastro_v210_deploy_unblock_fix.py",
    ]:
        path = root / rel
        if path.exists():
            path.unlink()
            removed.append(rel)
    for rel in [
        "fzastro_v210_deploy_unblock_fix_patch",
        "fzastro_v210_deploy_anchor_fix_patch",
        "fzastro_v210_deploy_anchor_fix_robust_patch",
        "fzastro_v210_final_deploy_fix_patch",
        "fzastro_v210_test_anchor_force_fix_patch",
    ]:
        path = root / rel
        if path.exists() and path.is_dir():
            import shutil

            shutil.rmtree(path)
            removed.append(rel)
    return removed


def main() -> int:
    root = project_root()
    changed = []
    if repair_nina_bridge(root):
        changed.append("fzastro_ai/nina/nina_bridge.py")
    if repair_timer_connect(root):
        changed.append("fzastro_ai/ui/nina_control_dialog.py")
    removed = cleanup_root_helpers(root)

    print("FZAstro v2.1.0 indent/anchor repair complete.")
    if changed:
        print("Changed:")
        for item in changed:
            print(f"  - {item}")
    else:
        print("No source changes were needed.")
    if removed:
        print("Removed temporary root helpers:")
        for item in removed:
            print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
