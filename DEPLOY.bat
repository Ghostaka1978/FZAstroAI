@echo off
setlocal
cd /d "%~dp0"

echo FZAstro AI deploy
echo Project: %CD%
echo.
echo This runs the full deploy workflow, validation, and local Git release tag.
echo Add -GitPush after DEPLOY.bat if you also want to push the branch and tag.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\deploy.ps1" -RunValidation -GitRelease %*
set DEPLOY_EXIT=%ERRORLEVEL%

echo.
if not "%DEPLOY_EXIT%"=="0" (
    echo Deploy failed with exit code %DEPLOY_EXIT%.
) else (
    echo Deploy complete.
)
pause
exit /b %DEPLOY_EXIT%
