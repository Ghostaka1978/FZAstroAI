# Run from the project root, for example: D:\Dropbox\AI
# Keeps the real package in .\fzastro_ai and removes duplicated root modules/folders.

$ErrorActionPreference = "Stop"

$duplicateFolders = @(
  "actions", "astro_tools", "benchmarks", "controllers", "resources", "routing", "ui", "workers", "release"
)

$duplicateFiles = @(
  "__init__.py", "app.py", "astro_worker.py", "calibration_profiles.py", "chat_blocks.py",
  "chat_worker.py", "composer_actions.py", "composer_tools.py", "config.py",
  "document_import_worker.py", "document_maintenance_worker.py", "file_tools.py",
  "gpu_monitor_worker.py", "history_store.py", "knowledge_library.py", "logging_utils.py",
  "market_sources.py", "memory_extraction_worker.py", "memory_store.py", "model_controls.py",
  "model_discovery_worker.py", "network_utils.py", "news_tools.py", "persona_routing.py",
  "prompts.py", "python_execution_worker.py", "runtime.py", "seeing_worker.py",
  "shutdown_controller.py", "skill_registry.py", "solar_map_worker.py", "sun_now_worker.py",
  "tool_manifest.py", "web_decision_worker.py", "web_search_worker.py", "web_tools.py",
  "seeing_dialog.py.orig"
)

foreach ($folder in $duplicateFolders) {
  if (Test-Path -LiteralPath $folder) {
    Remove-Item -LiteralPath $folder -Recurse -Force
  }
}

foreach ($file in $duplicateFiles) {
  if (Test-Path -LiteralPath $file) {
    Remove-Item -LiteralPath $file -Force
  }
}

Get-ChildItem -Path . -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Get-ChildItem -Path . -Recurse -File -Include *.pyc,*.pyo | Remove-Item -Force

Write-Host "Cleaned duplicate root modules/folders. Keep main.py at root; it launches fzastro_ai.app."
