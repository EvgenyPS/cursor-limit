# FILE: scripts/run-tray.ps1
# PURPOSE: Start Cursor Limits tray (creates venv on first run)
#
# Если ExecutionPolicy блокирует .ps1:
#   powershell -ExecutionPolicy Bypass -File .\scripts\run-tray.ps1
# или без скрипта:
#   .\.venv\Scripts\python.exe -m src

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating .venv and installing deps..."
    python -m venv .venv
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r requirements.txt
}

Write-Host "Starting Cursor Limits tray..."
& $VenvPython -m src
