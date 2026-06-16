from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class PatchSnapshot:
    id: str
    root: str
    directory: str
    changed_paths: tuple[str, ...]
    patch_file: str
    manifest_file: str


@dataclass(frozen=True)
class PatchApplyResult:
    ok: bool
    message: str
    snapshot: PatchSnapshot | None = None
    stdout: str = ""
    stderr: str = ""


def changed_paths_from_patch(patch_text: str) -> tuple[str, ...]:
    """Extract changed project-relative paths from a unified diff."""

    paths: list[str] = []
    for line in str(patch_text or "").splitlines():
        if not (line.startswith("--- ") or line.startswith("+++ ")):
            continue
        raw = line[4:].strip().split("\t", 1)[0]
        if raw == "/dev/null":
            continue
        if raw.startswith("a/") or raw.startswith("b/"):
            raw = raw[2:]
        raw = raw.replace("\\", "/")
        if raw and raw not in paths:
            paths.append(raw)
    return tuple(paths)


def _safe_snapshot_id(label: str | None = None) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "" if not label else "_" + "".join(ch if ch.isalnum() else "_" for ch in label.lower())[:36]
    return stamp + suffix


def create_patch_snapshot(
    root: Path | str,
    changed_paths: tuple[str, ...],
    *,
    patch_text: str = "",
    label: str | None = None,
) -> PatchSnapshot:
    """Create a rollback snapshot before a patch is applied."""

    root_path = Path(root).resolve()
    snapshot_id = _safe_snapshot_id(label)
    snapshot_dir = root_path / ".fzastro_ai_patches" / snapshot_id
    backups_dir = snapshot_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    for relative in changed_paths:
        source = root_path / relative
        target = backups_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists() and source.is_file():
            shutil.copy2(source, target)

    patch_file = snapshot_dir / "patch.diff"
    patch_file.write_text(patch_text or "", encoding="utf-8")

    manifest = {
        "id": snapshot_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(root_path),
        "changed_paths": list(changed_paths),
        "patch_file": str(patch_file),
        "backups_dir": str(backups_dir),
    }
    manifest_file = snapshot_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return PatchSnapshot(
        id=snapshot_id,
        root=str(root_path),
        directory=str(snapshot_dir),
        changed_paths=changed_paths,
        patch_file=str(patch_file),
        manifest_file=str(manifest_file),
    )


def apply_patch_with_git(
    root: Path | str,
    patch_text: str,
    *,
    label: str | None = None,
    timeout_seconds: int = 60,
) -> PatchApplyResult:
    """Apply a unified diff through git after creating a rollback snapshot.

    This deliberately requires `git apply --check` to pass before changing files.
    """

    root_path = Path(root).resolve()
    changed_paths = changed_paths_from_patch(patch_text)
    if not changed_paths:
        return PatchApplyResult(False, "No changed paths found in patch.")

    snapshot = create_patch_snapshot(
        root_path,
        changed_paths,
        patch_text=patch_text,
        label=label,
    )

    check = subprocess.run(
        ["git", "apply", "--check", snapshot.patch_file],
        cwd=root_path,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    if check.returncode != 0:
        return PatchApplyResult(
            False,
            "Patch validation failed; no files were changed.",
            snapshot=snapshot,
            stdout=check.stdout,
            stderr=check.stderr,
        )

    apply = subprocess.run(
        ["git", "apply", snapshot.patch_file],
        cwd=root_path,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    return PatchApplyResult(
        apply.returncode == 0,
        "Patch applied." if apply.returncode == 0 else "Patch apply failed.",
        snapshot=snapshot,
        stdout=apply.stdout,
        stderr=apply.stderr,
    )


def snapshot_to_dict(snapshot: PatchSnapshot) -> dict[str, object]:
    return asdict(snapshot)
