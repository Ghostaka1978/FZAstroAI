from pathlib import Path


def test_deploy_activates_project_virtual_environment():
    project_root = Path(__file__).resolve().parents[1]
    deploy_script = (project_root / "scripts" / "deploy.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "Invoke-FZAstroVirtualEnvironmentActivation" in deploy_script
    assert "Scripts\\Activate.ps1" in deploy_script
    assert ". $ActivateScript" in deploy_script
    assert "Set-FZAstroBuildEnvironment -PythonPath $ResolvedPython" in deploy_script
    assert deploy_script.index(
        "Set-FZAstroBuildEnvironment -PythonPath $ResolvedPython"
    ) < deploy_script.index(
        "Invoke-FZAstroVirtualEnvironmentActivation -PythonPath $ResolvedPython"
    )
