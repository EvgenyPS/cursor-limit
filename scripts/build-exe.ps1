# FILE: scripts/build-exe.ps1
# PURPOSE: Build CursorLimits.exe (windowed, one-file) via PyInstaller

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    # CI / система без локального venv
    $Python = (Get-Command python -ErrorAction Stop).Source
    Write-Host "Using system Python: $Python"
}

& $Python -m pip install -q pyinstaller
# Вшиваем расширение status bar + SVG иконки трея
$StatusBar = Join-Path $Root "cursor-status-bar"
$IcoSvg = Join-Path $Root "cursor-ico.svg"
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name CursorLimits `
    --paths $Root `
    --add-data "$StatusBar;cursor-status-bar" `
    --add-data "$IcoSvg;." `
    --hidden-import pystray._win32 `
    --hidden-import PIL._tkinter_finder `
    --collect-all pystray `
    "$Root\run_tray.py"

$Exe = Join-Path $Root "dist\CursorLimits.exe"
if (-not (Test-Path $Exe)) {
    throw "Build failed: $Exe not found"
}

Write-Host "OK: $Exe"
Write-Host "Autostart: right-click tray -> Autostart with Windows"
Write-Host "Or: $Exe --install-autostart"
