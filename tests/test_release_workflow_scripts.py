from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_clean_build_starts_build_script_after_cleaning():
    script = (PROJECT_ROOT / "scripts" / "clean_build.ps1").read_text(encoding="utf-8")

    assert "Starting build_exe.ps1 automatically" in script
    assert "$BuildParams = @{" in script
    assert "& $BuildScript @BuildParams" in script
    assert "-ProjectRoot" not in script
    assert "CleanOnly" in script


def test_build_script_prompts_for_validation_after_success():
    script = (PROJECT_ROOT / "scripts" / "build_exe.ps1").read_text(encoding="utf-8")

    assert "Run release validation now?" in script
    assert "Read-Host" in script
    assert "validate_release.ps1" in script
    assert "SkipValidationPrompt" in script
    assert "RunValidation" in script


def test_release_docs_describe_clean_build_validation_chain():
    docs = "\n".join(
        (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for name in ["README.md", "RELEASE_VALIDATION.md"]
    )

    assert "scripts/clean_build.ps1" in docs
    assert "starts `build_exe.ps1` automatically" in docs
    assert "validation prompt" in docs


def test_memory_extraction_worker_export_is_not_broken():
    worker_path = (
        PROJECT_ROOT / "fzastro_ai" / "workers" / "memory_extraction_worker.py"
    )
    init_path = PROJECT_ROOT / "fzastro_ai" / "workers" / "__init__.py"

    worker_source = worker_path.read_text(encoding="utf-8")
    init_source = init_path.read_text(encoding="utf-8")

    assert "class MemoryExtractionWorker" in worker_source
    assert "from .memory_extraction_worker import MemoryExtractionWorker" in init_source
    assert '"MemoryExtractionWorker"' in init_source


def test_deploy_script_is_single_command_wrapper():
    script = (PROJECT_ROOT / "scripts" / "deploy.ps1").read_text(encoding="utf-8")

    assert "FZAstro AI deploy workflow" in script
    assert "clean_build.ps1" in script
    assert "$CleanParams = @{" in script
    assert "& $CleanScript @CleanParams" in script
    assert "RunValidation" in script
    assert "SkipValidationPrompt" in script
    assert '"-ProjectRoot"' not in script


def test_activate_venv_script_sets_runtime_python_and_build_environment():
    script = (PROJECT_ROOT / "scripts" / "activate_venv.ps1").read_text(
        encoding="utf-8"
    )

    assert "Activate.ps1" in script
    assert "FZASTRO_PYTHON" in script
    assert "FZASTRO_BUILD_ROOT" in script
    assert "FZASTRO_PROJECT_ROOT" in script
    assert "VIRTUAL_ENV" in script
    assert "Scripts\\python.exe" in script
    assert ". $ActivateScript" in script


def test_release_docs_describe_deploy_and_venv_activation():
    docs = "\n".join(
        (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for name in ["README.md", "RELEASE_VALIDATION.md"]
    )

    assert "scripts/deploy.ps1" in docs
    assert "single release workflow command" in docs or "one-command workflow" in docs
    assert "scripts/activate_venv.ps1" in docs
    assert ". .\\scripts\\activate_venv.ps1" in docs


def test_deploy_build_validation_use_quiet_progress_workflow():
    scripts = "\n".join(
        (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for name in [
            "scripts/deploy.ps1",
            "scripts/clean_build.ps1",
            "scripts/build_exe.ps1",
            "scripts/validate_release.ps1",
        ]
    )

    assert "Write-Progress" in scripts
    assert "Show-StageStep" in scripts
    assert "VerboseOutput" in scripts
    assert "Invoke-LoggedCommand" in scripts
    assert "FZAstroAI_BUILD" in scripts
    assert "Resolve-BuildRootPath" in scripts
    assert "Set-FZAstroBuildEnvironment" in scripts
    assert "FZASTRO_BUILD_ROOT" in scripts
    assert "logs" in scripts


def test_release_docs_describe_quiet_progress_logs():
    docs = "\n".join(
        (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for name in ["README.md", "RELEASE_VALIDATION.md"]
    )

    assert "progress bar" in docs
    assert (
        "cleanup, build, and validation" in docs or "cleanup/build/validation" in docs
    )
    assert "VerboseOutput" in docs
    assert "..\\FZAstroAI_BUILD\\logs" in docs
    assert "%TEMP%" not in docs


def test_build_script_keeps_log_directory_available_after_prepare_step():
    script = (PROJECT_ROOT / "scripts" / "build_exe.ps1").read_text(encoding="utf-8")

    assert "New-Item -ItemType Directory -Force -Path $logDirectory" in script
    assert "Remove-Item -Recurse -Force $BuildRoot" not in script
    assert "Remove-Item -Recurse -Force $DistDir" in script
    assert "Remove-Item -Recurse -Force $WorkDir" in script
    assert "Remove-Item -Recurse -Force $SpecDir" in script
    assert "Remove-Item -Recurse -Force $ReleaseDir" in script
    assert "New-Item -ItemType Directory -Force -Path $LogDir" in script


def test_quiet_logging_avoids_native_stream_redirection_noise():
    scripts = "\n".join(
        (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for name in [
            "scripts/deploy.ps1",
            "scripts/clean_build.ps1",
            "scripts/build_exe.ps1",
            "scripts/validate_release.ps1",
        ]
    )

    assert "*>>" not in scripts
    assert "Start-Process" in scripts
    assert "RedirectStandardOutput" in scripts
    assert "RedirectStandardError" in scripts
    assert "Invoke-NativeCommand" in scripts


def test_build_root_defaults_to_sibling_folder_not_temp():
    scripts = "\n".join(
        (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for name in [
            "scripts/deploy.ps1",
            "scripts/clean_build.ps1",
            "scripts/build_exe.ps1",
            "scripts/validate_release.ps1",
            "scripts/activate_venv.ps1",
        ]
    )

    assert (
        'Join-Path ([System.IO.Path]::GetTempPath()) "FZAstroAI_BUILD"' not in scripts
    )
    assert 'Join-Path $ParentRoot "FZAstroAI_BUILD"' in scripts
    assert (
        "Resolve-BuildRootPath -RequestedBuildRoot $BuildRoot -Root $ProjectRoot"
        in scripts
    )


def test_release_docs_describe_sibling_build_folder_and_env_vars():
    docs = "\n".join(
        (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for name in ["README.md", "RELEASE_VALIDATION.md"]
    )

    assert "one folder above the project root" in docs
    assert "..\\FZAstroAI_BUILD" in docs
    assert "FZASTRO_PROJECT_ROOT" in docs
    assert "FZASTRO_BUILD_ROOT" in docs
    assert "FZASTRO_PYTHON" in docs
    assert "%TEMP%" not in docs


def test_reset_venv_script_recreates_python_311_environment():
    script = (PROJECT_ROOT / "scripts" / "reset_venv.ps1").read_text(encoding="utf-8")

    assert "Find-Python311" in script
    assert "py" in script and "-3.11" in script
    assert "-m" in script and "venv" in script
    assert "requirements.txt" in script
    assert "FZASTRO_PYTHON" in script
    assert "FZASTRO_BUILD_ROOT" in script
    assert "Python 3.11 virtual environment is ready" in script


def test_release_scripts_enforce_python_311():
    scripts = "\n".join(
        (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for name in [
            "scripts/activate_venv.ps1",
            "scripts/deploy.ps1",
            "scripts/clean_build.ps1",
            "scripts/build_exe.ps1",
            "scripts/validate_release.ps1",
        ]
    )

    assert "Assert-Python311" in scripts
    assert "Get-PythonVersionInfo" in scripts
    assert "Python 3.11" in scripts
    assert "reset_venv.ps1" in scripts
    assert "python3.11" in scripts
    assert "Python 3.14" in (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")


def test_release_docs_describe_reset_venv_and_python_311_enforcement():
    docs = "\n".join(
        (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for name in ["README.md", "RELEASE_VALIDATION.md"]
    )

    assert "scripts/reset_venv.ps1" in docs
    assert "Python 3.11" in docs
    assert "Python 3.14" in docs
    assert "py -3.11 -m venv .venv" in docs
    assert "FZASTRO_PYTHON" in docs


def test_reset_venv_refuses_to_delete_active_environment(project_root):
    text = (project_root / "scripts" / "reset_venv.ps1").read_text(encoding="utf-8")
    assert "Cannot reset .venv while it is active" in text
    assert "Assert-VenvNotActive" in text
    assert "Remove-VenvSafely" in text


def test_repair_startup_import_script_exists(project_root):
    text = (project_root / "scripts" / "repair_startup_import.ps1").read_text(
        encoding="utf-8"
    )
    assert r"fzastro_ai\__init__.py" in text
    assert "from .config import APP_VERSION as __version__" in text


def test_validate_release_checks_release_artifact_hygiene():
    script = (PROJECT_ROOT / "scripts" / "validate_release.ps1").read_text(
        encoding="utf-8"
    )

    assert "Assert-ReleaseArtifactHygiene" in script
    assert "Check release artifact hygiene" in script
    assert "Release folder contains development/repair artifacts" in script
    assert "*.bak" in script
    assert "*.patch" in script
    assert "repair_*.ps1" in script
    assert "-TotalSteps 13" in script


def test_release_docs_describe_artifact_hygiene_check():
    docs = "\n".join(
        (PROJECT_ROOT / name).read_text(encoding="utf-8")
        for name in ["README.md", "RELEASE_VALIDATION.md"]
    )

    assert "development/repair artifacts" in docs
    assert ".bak" in docs
    assert ".patch" in docs
    assert "repair_*.ps1" in docs


def test_validate_release_requires_manifest_resource_check_and_isolated_smoke_appdata(
    project_root,
):
    script = (project_root / "scripts" / "validate_release.ps1").read_text(
        encoding="utf-8"
    )

    assert "Assert-ReleaseManifest" in script
    assert "Assert-PyInstallerResourceConfiguration" in script
    assert "Check release manifest and required files" in script
    assert "Check PyInstaller resource configuration" in script
    assert "release_manifest.txt" in script
    assert "smoke_appdata" in script
    assert "FZASTRO_APP_DIR" in script
    assert "-TotalSteps 13" in script


def test_release_docs_describe_manifest_resource_and_gui_smoke_checks(project_root):
    docs = "\n".join(
        (project_root / name).read_text(encoding="utf-8")
        for name in ["README.md", "RELEASE_VALIDATION.md"]
    )

    assert "release manifest" in docs.lower()
    assert "PyInstaller resource" in docs
    assert "smoke_appdata" in docs
    assert "GUI smoke" in docs or "GUI startup" in docs


def test_release_package_includes_validation_documentation():
    build_script = (PROJECT_ROOT / "scripts" / "build_exe.ps1").read_text(
        encoding="utf-8"
    )
    validation_script = (PROJECT_ROOT / "scripts" / "validate_release.ps1").read_text(
        encoding="utf-8"
    )

    assert "RELEASE_VALIDATION.md" in build_script
    assert "RELEASE_VALIDATION.md" in validation_script
    assert "fzastro_ai.ui.llm_benchmark_dialog" in validation_script


def test_powershell_scripts_live_under_scripts_folder():
    scripts_dir = PROJECT_ROOT / "scripts"
    assert scripts_dir.exists()
    assert not list(PROJECT_ROOT.glob("*.ps1"))
    for name in [
        "activate_venv.ps1",
        "build_exe.ps1",
        "clean_build.ps1",
        "deploy.ps1",
        "format_code.ps1",
        "install_offline_voice.ps1",
        "repair_startup_import.ps1",
        "reset_venv.ps1",
        "run_web_companion.ps1",
        "validate_release.ps1",
    ]:
        assert (scripts_dir / name).exists(), name
