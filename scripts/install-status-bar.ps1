# FILE: scripts/install-status-bar.ps1
# PURPOSE: Copy status-bar extension into ~/.cursor/extensions

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Src = Join-Path $Root "cursor-status-bar"
$DstRoot = Join-Path $env:USERPROFILE ".cursor\extensions"
$Dst = Join-Path $DstRoot "local.cursor-limits-status-bar-0.1.0"

if (-not (Test-Path $Src)) {
    throw "Source folder not found: $Src"
}

New-Item -ItemType Directory -Force -Path $DstRoot | Out-Null
if (Test-Path $Dst) {
    Remove-Item -Recurse -Force $Dst
}
Copy-Item -Recurse -Force $Src $Dst

Write-Host "Extension installed:"
Write-Host "  $Dst"
Write-Host ""
Write-Host "Next: in Cursor press Ctrl+Shift+P -> Developer: Reload Window"
Write-Host "Tray app writes cache to %USERPROFILE%\.cursor-limits\cache.json"
