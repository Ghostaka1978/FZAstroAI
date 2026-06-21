from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from .safety import DEFAULT_MUTATION_BLOCKED_DIRS
from .subprocess_utils import hidden_subprocess_kwargs
from .types import PatchProposal, RiskLevel


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
    applied_paths: tuple[str, ...] = ()
    skipped_paths: tuple[str, ...] = ()
    failed_paths: tuple[str, ...] = ()


class PatchPathError(ValueError):
    """Raised when a patch references a path outside the project tree."""


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _normalize_patch_relative_path(raw_path: str) -> str:
    raw = str(raw_path or "").strip().split("\t", 1)[0]

    if raw == "/dev/null":
        return ""

    if raw.startswith("a/") or raw.startswith("b/"):
        raw = raw[2:]

    raw = raw.replace("\\", "/")
    path = PurePosixPath(raw)
    parts = path.parts

    if (
        not raw
        or raw.startswith("/")
        or ":" in raw
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise PatchPathError(f"Unsafe patch path: {raw_path!r}")

    return path.as_posix()


def changed_paths_from_patch(patch_text: str) -> tuple[str, ...]:
    """Extract changed project-relative paths from a unified diff."""

    paths: list[str] = []
    for line in str(patch_text or "").splitlines():
        if not (line.startswith("--- ") or line.startswith("+++ ")):
            continue
        raw = _normalize_patch_relative_path(line[4:])
        if not raw:
            continue
        if raw and raw not in paths:
            paths.append(raw)
    return tuple(paths)


def _patch_section_target_path(section: str) -> str:
    """Return the destination path for a single unified-diff file section."""

    for line in str(section or "").splitlines():
        if line.startswith("+++ "):
            return _normalize_patch_relative_path(line[4:])
    return ""


def split_patch_sections(patch_text: str) -> tuple[str, ...]:
    """Split a unified diff into independent per-file sections.

    Git can apply a normal multi-file diff in one pass. For user-reviewed AI
    patches, though, a proposal may become partially stale after a previous
    retry: an implementation hunk can already be applied while a new test-file
    hunk still needs to be created. Splitting lets us preflight each file and
    safely skip sections that are already applied while still applying the
    remaining valid sections.
    """

    sections: list[list[str]] = []
    current: list[str] = []
    pending_header: list[str] = []
    lines = str(patch_text or "").splitlines()
    index = 0

    while index < len(lines):
        line = lines[index]
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        starts_file_section = line.startswith("--- ") and next_line.startswith("+++ ")

        if starts_file_section:
            if current:
                sections.append(current)
            current = []
            if pending_header:
                current.extend(pending_header)
                pending_header = []
            current.append(line)
        elif current:
            current.append(line)
        else:
            # Preserve optional `diff --git`, `index`, or file-mode headers with
            # the following file section. They are harmless for git apply and
            # useful when present in model-generated diffs.
            pending_header.append(line)
        index += 1

    if current:
        sections.append(current)

    return tuple("\n".join(section).rstrip() + "\n" for section in sections)


def _run_git_apply_check(
    root_path: Path,
    patch_file: Path,
    *,
    timeout_seconds: int,
    reverse: bool = False,
) -> subprocess.CompletedProcess[str]:
    args = ["git", "apply", "--check"]
    if reverse:
        args.append("--reverse")
    args.append(str(patch_file))
    return subprocess.run(
        args,
        cwd=root_path,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        **hidden_subprocess_kwargs(),
    )


def _run_git_apply(
    root_path: Path,
    patch_file: Path,
    *,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "apply", str(patch_file)],
        cwd=root_path,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        **hidden_subprocess_kwargs(),
    )


def _format_patch_check_failure(
    stderr: str,
    *,
    failed_paths: tuple[str, ...] = (),
) -> str:
    text = str(stderr or "").strip()
    path_text = ""
    if failed_paths:
        path_text = " Failed path(s): " + ", ".join(failed_paths) + "."
    if not text:
        return "Patch validation failed; no files were changed." + path_text
    return "Patch validation failed; no files were changed." + path_text + "\n\n" + text


def _validate_changed_paths(
    root_path: Path,
    changed_paths: tuple[str, ...],
    *,
    allow_blocked: bool = False,
) -> tuple[str, ...]:
    safe_paths: list[str] = []

    for relative in changed_paths:
        safe_relative = _normalize_patch_relative_path(relative)
        if not safe_relative:
            continue

        source = (root_path / Path(*safe_relative.split("/"))).resolve()
        if not _is_relative_to(source, root_path):
            raise PatchPathError(f"Patch path escapes project root: {relative!r}")

        first_part = PurePosixPath(safe_relative).parts[0]
        if not allow_blocked and first_part in DEFAULT_MUTATION_BLOCKED_DIRS:
            raise PatchPathError(f"Patch targets blocked project area: {first_part}")

        if safe_relative not in safe_paths:
            safe_paths.append(safe_relative)

    return tuple(safe_paths)


def _safe_snapshot_id(label: str | None = None) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = (
        ""
        if not label
        else "_" + "".join(ch if ch.isalnum() else "_" for ch in label.lower())[:36]
    )
    return stamp + suffix


def create_patch_snapshot(
    root: Path | str,
    changed_paths: tuple[str, ...],
    *,
    patch_text: str = "",
    label: str | None = None,
    allow_blocked: bool = False,
) -> PatchSnapshot:
    """Create a rollback snapshot before a patch is applied."""

    root_path = Path(root).resolve()
    changed_paths = _validate_changed_paths(
        root_path, changed_paths, allow_blocked=allow_blocked
    )
    snapshot_id = _safe_snapshot_id(label)
    snapshot_dir = root_path / ".fzastro_ai_patches" / snapshot_id
    backups_dir = snapshot_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    for relative in changed_paths:
        source = root_path / Path(*relative.split("/"))
        target = backups_dir / Path(*relative.split("/"))
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


def preflight_patch_with_git(
    root: Path | str,
    patch_text: str,
    *,
    timeout_seconds: int = 60,
    allow_blocked: bool = False,
) -> PatchApplyResult:
    """Validate a unified diff without creating backups or editing files."""

    root_path = Path(root).resolve()
    try:
        changed_paths = changed_paths_from_patch(patch_text)
        _validate_changed_paths(root_path, changed_paths, allow_blocked=allow_blocked)
    except PatchPathError as exc:
        return PatchApplyResult(False, str(exc))

    if not changed_paths:
        return PatchApplyResult(False, "No changed paths found in patch.")

    with tempfile.TemporaryDirectory(prefix="fzastro_patch_preflight_") as temp_dir:
        patch_file = Path(temp_dir) / "proposal.diff"
        patch_file.write_text(patch_text or "", encoding="utf-8")
        check = _run_git_apply_check(
            root_path,
            patch_file,
            timeout_seconds=timeout_seconds,
        )
        if check.returncode == 0:
            return PatchApplyResult(
                True,
                "Patch preflight passed.",
                stdout=check.stdout,
                stderr=check.stderr,
                applied_paths=changed_paths,
            )

        sections = split_patch_sections(patch_text)
        if not sections:
            return PatchApplyResult(
                False,
                _format_patch_check_failure(check.stderr),
                stdout=check.stdout,
                stderr=check.stderr,
                failed_paths=changed_paths,
            )

        applicable_paths: list[str] = []
        skipped_paths: list[str] = []
        failed_paths: list[str] = []
        failure_details: list[str] = []
        section_dir = Path(temp_dir) / "sections"
        section_dir.mkdir(parents=True, exist_ok=True)

        for index, section in enumerate(sections, start=1):
            try:
                section_paths = changed_paths_from_patch(section)
                _validate_changed_paths(
                    root_path, section_paths, allow_blocked=allow_blocked
                )
            except PatchPathError as exc:
                failed_paths.append(f"section-{index}")
                failure_details.append(str(exc))
                continue
            if not section_paths:
                continue
            target_path = _patch_section_target_path(section) or section_paths[-1]
            section_file = section_dir / f"section_{index:03d}.diff"
            section_file.write_text(section, encoding="utf-8")
            section_check = _run_git_apply_check(
                root_path,
                section_file,
                timeout_seconds=timeout_seconds,
            )
            if section_check.returncode == 0:
                applicable_paths.append(target_path)
                continue
            reverse_check = _run_git_apply_check(
                root_path,
                section_file,
                timeout_seconds=timeout_seconds,
                reverse=True,
            )
            if reverse_check.returncode == 0:
                skipped_paths.append(target_path)
                continue
            failed_paths.append(target_path)
            detail = (
                section_check.stderr or section_check.stdout or "section did not apply"
            ).strip()
            if detail:
                failure_details.append(f"{target_path}: {detail}")

        if failed_paths:
            return PatchApplyResult(
                False,
                _format_patch_check_failure(
                    "\n".join(failure_details),
                    failed_paths=tuple(dict.fromkeys(failed_paths)),
                ),
                stdout=check.stdout,
                stderr="\n".join(failure_details) or check.stderr,
                applied_paths=tuple(dict.fromkeys(applicable_paths)),
                skipped_paths=tuple(dict.fromkeys(skipped_paths)),
                failed_paths=tuple(dict.fromkeys(failed_paths)),
            )

        if applicable_paths or skipped_paths:
            message = "Patch preflight passed."
            if skipped_paths:
                message += (
                    " Already-applied section(s) will be skipped: "
                    + ", ".join(dict.fromkeys(skipped_paths))
                    + "."
                )
            return PatchApplyResult(
                True,
                message,
                stdout=check.stdout,
                stderr=check.stderr,
                applied_paths=tuple(dict.fromkeys(applicable_paths)),
                skipped_paths=tuple(dict.fromkeys(skipped_paths)),
            )

        return PatchApplyResult(
            False,
            _format_patch_check_failure(check.stderr),
            stdout=check.stdout,
            stderr=check.stderr,
            failed_paths=changed_paths,
        )


def apply_patch_with_git(
    root: Path | str,
    patch_text: str,
    *,
    label: str | None = None,
    timeout_seconds: int = 60,
    allow_blocked: bool = False,
) -> PatchApplyResult:
    """Apply a unified diff after creating a rollback snapshot.

    The primary path is an atomic `git apply --check` followed by `git apply`.
    If the full patch fails validation, the patch is preflighted per file. This
    lets the app safely handle a common agent workflow case: part of a proposal
    is already applied from an earlier attempt, while a new-file test hunk still
    needs to be created. A section is skipped only when `git apply --reverse
    --check` proves it is already applied; otherwise no files are changed.
    """

    root_path = Path(root).resolve()
    try:
        changed_paths = changed_paths_from_patch(patch_text)
    except PatchPathError as exc:
        return PatchApplyResult(False, str(exc))

    if not changed_paths:
        return PatchApplyResult(False, "No changed paths found in patch.")

    try:
        snapshot = create_patch_snapshot(
            root_path,
            changed_paths,
            patch_text=patch_text,
            label=label,
            allow_blocked=allow_blocked,
        )
    except PatchPathError as exc:
        return PatchApplyResult(False, str(exc))

    check = _run_git_apply_check(
        root_path,
        Path(snapshot.patch_file),
        timeout_seconds=timeout_seconds,
    )
    if check.returncode == 0:
        apply = _run_git_apply(
            root_path,
            Path(snapshot.patch_file),
            timeout_seconds=timeout_seconds,
        )
        return PatchApplyResult(
            apply.returncode == 0,
            "Patch applied." if apply.returncode == 0 else "Patch apply failed.",
            snapshot=snapshot,
            stdout=apply.stdout,
            stderr=apply.stderr,
            applied_paths=changed_paths if apply.returncode == 0 else (),
            failed_paths=() if apply.returncode == 0 else changed_paths,
        )

    # Full-patch validation failed. Try a conservative per-file preflight so
    # already-applied sections can be skipped but unrelated failures still block.
    sections = split_patch_sections(patch_text)
    if not sections:
        return PatchApplyResult(
            False,
            _format_patch_check_failure(check.stderr),
            snapshot=snapshot,
            stdout=check.stdout,
            stderr=check.stderr,
            failed_paths=changed_paths,
        )

    applicable_sections: list[tuple[str, str]] = []
    skipped_paths: list[str] = []
    failed_paths: list[str] = []
    failure_details: list[str] = []

    section_dir = Path(snapshot.directory) / "sections"
    section_dir.mkdir(parents=True, exist_ok=True)

    for index, section in enumerate(sections, start=1):
        try:
            section_paths = changed_paths_from_patch(section)
        except PatchPathError as exc:
            failed_paths.append(f"section-{index}")
            failure_details.append(str(exc))
            continue

        if not section_paths:
            continue

        try:
            _validate_changed_paths(
                root_path, section_paths, allow_blocked=allow_blocked
            )
        except PatchPathError as exc:
            failed_paths.extend(section_paths)
            failure_details.append(str(exc))
            continue

        section_file = section_dir / f"section_{index:03d}.diff"
        section_file.write_text(section, encoding="utf-8")
        target_path = _patch_section_target_path(section) or section_paths[-1]
        section_check = _run_git_apply_check(
            root_path,
            section_file,
            timeout_seconds=timeout_seconds,
        )
        if section_check.returncode == 0:
            applicable_sections.append((target_path, str(section_file)))
            continue

        reverse_check = _run_git_apply_check(
            root_path,
            section_file,
            timeout_seconds=timeout_seconds,
            reverse=True,
        )
        if reverse_check.returncode == 0:
            skipped_paths.append(target_path)
            continue

        failed_paths.append(target_path)
        detail = (
            section_check.stderr or section_check.stdout or "section did not apply"
        ).strip()
        if detail:
            failure_details.append(f"{target_path}: {detail}")

    if failed_paths:
        message = _format_patch_check_failure(
            "\n".join(failure_details),
            failed_paths=tuple(dict.fromkeys(failed_paths)),
        )
        return PatchApplyResult(
            False,
            message,
            snapshot=snapshot,
            stdout=check.stdout,
            stderr="\n".join(failure_details) or check.stderr,
            skipped_paths=tuple(dict.fromkeys(skipped_paths)),
            failed_paths=tuple(dict.fromkeys(failed_paths)),
        )

    applied_paths: list[str] = []
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    for target_path, section_file_text in applicable_sections:
        apply = _run_git_apply(
            root_path,
            Path(section_file_text),
            timeout_seconds=timeout_seconds,
        )
        stdout_parts.append(apply.stdout or "")
        stderr_parts.append(apply.stderr or "")
        if apply.returncode != 0:
            return PatchApplyResult(
                False,
                "Patch apply failed after validation. Rollback snapshot was created; inspect files before retrying.",
                snapshot=snapshot,
                stdout="\n".join(stdout_parts).strip(),
                stderr="\n".join(stderr_parts).strip(),
                applied_paths=tuple(dict.fromkeys(applied_paths)),
                skipped_paths=tuple(dict.fromkeys(skipped_paths)),
                failed_paths=(target_path,),
            )
        applied_paths.append(target_path)

    if applied_paths:
        message = "Patch applied."
        if skipped_paths:
            message += (
                " Already-applied section(s) skipped: "
                + ", ".join(dict.fromkeys(skipped_paths))
                + "."
            )
        return PatchApplyResult(
            True,
            message,
            snapshot=snapshot,
            stdout="\n".join(stdout_parts).strip(),
            stderr="\n".join(stderr_parts).strip(),
            applied_paths=tuple(dict.fromkeys(applied_paths)),
            skipped_paths=tuple(dict.fromkeys(skipped_paths)),
        )

    if skipped_paths:
        return PatchApplyResult(
            True,
            "Patch already applied; no file edits were needed.",
            snapshot=snapshot,
            skipped_paths=tuple(dict.fromkeys(skipped_paths)),
        )

    return PatchApplyResult(
        False,
        _format_patch_check_failure(check.stderr),
        snapshot=snapshot,
        stdout=check.stdout,
        stderr=check.stderr,
        failed_paths=changed_paths,
    )


def snapshot_to_dict(snapshot: PatchSnapshot) -> dict[str, object]:
    return asdict(snapshot)


def make_patch_proposal(
    unified_diff: str,
    *,
    reason: str,
    risk_level: RiskLevel | str = RiskLevel.MEDIUM,
    suggested_tests: tuple[str, ...] = (),
    allow_blocked: bool = False,
) -> PatchProposal:
    """Create a reviewable patch proposal from unified diff text."""

    paths = changed_paths_from_patch(unified_diff)
    if not allow_blocked:
        for path in paths:
            first_part = PurePosixPath(path).parts[0]
            if first_part in DEFAULT_MUTATION_BLOCKED_DIRS:
                raise PatchPathError(
                    f"Patch targets blocked project area: {first_part}"
                )
    return PatchProposal(
        target_files=paths,
        unified_diff=unified_diff,
        reason=reason,
        risk_level=RiskLevel(risk_level),
        suggested_tests=suggested_tests,
    )


def apply_patch_proposal(
    root: Path | str,
    proposal: PatchProposal,
    *,
    approved: bool = False,
    label: str | None = None,
    timeout_seconds: int = 60,
    allow_blocked: bool = False,
) -> PatchApplyResult:
    """Apply a proposal only after explicit approval."""

    if not approved:
        return PatchApplyResult(False, "Patch proposal requires approval before apply.")
    return apply_patch_with_git(
        root,
        proposal.unified_diff,
        label=label or proposal.reason,
        timeout_seconds=timeout_seconds,
        allow_blocked=allow_blocked,
    )


def save_patch_exports(
    root: Path | str,
    proposal: PatchProposal,
    *,
    output_dir: Path | str | None = None,
    label: str | None = None,
) -> dict[str, str]:
    """Save raw patch, manifest, and ZIP export for review/handoff."""

    root_path = Path(root).resolve()
    export_id = _safe_snapshot_id(label or "proposal")
    target_dir = (
        Path(output_dir).resolve()
        if output_dir
        else root_path / ".fzastro_ai_patches" / export_id
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    raw_patch = target_dir / "proposal.diff"
    raw_patch.write_text(proposal.unified_diff, encoding="utf-8")
    manifest = {
        "id": export_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "target_files": list(proposal.target_files),
        "reason": proposal.reason,
        "risk_level": proposal.risk_level.value,
        "suggested_tests": list(proposal.suggested_tests),
    }
    manifest_file = target_dir / "proposal_manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    zip_file = target_dir / "patch_proposal.zip"
    with zipfile.ZipFile(zip_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(raw_patch, "proposal.diff")
        archive.write(manifest_file, "proposal_manifest.json")
    return {
        "raw_patch": str(raw_patch),
        "manifest": str(manifest_file),
        "zip": str(zip_file),
    }
