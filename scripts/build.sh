#!/usr/bin/env bash
# FILE: scripts/build.sh
# PURPOSE: Сборка бинарника CursorLimits через PyInstaller (Linux / macOS).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

"$PYTHON" -m pip install -q pyinstaller
# macOS: pystray нужен pyobjc
if [[ "$(uname -s)" == "Darwin" ]]; then
  "$PYTHON" -m pip install -q pyobjc-framework-Cocoa pyobjc-framework-Quartz
fi

SEP=":"
STATUS_BAR="$ROOT/cursor-status-bar"
ICO_SVG="$ROOT/cursor-ico.svg"
OUT_NAME="${OUT_NAME:-CursorLimits}"

"$PYTHON" -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --windowed \
  --name "$OUT_NAME" \
  --paths "$ROOT" \
  --add-data "${STATUS_BAR}${SEP}cursor-status-bar" \
  --add-data "${ICO_SVG}${SEP}." \
  --hidden-import PIL._tkinter_finder \
  --collect-all pystray \
  "$ROOT/run_tray.py"

EXE="$ROOT/dist/$OUT_NAME"
if [[ ! -f "$EXE" ]]; then
  # macOS иногда кладёт .app — ищем бинарь
  if [[ -f "$ROOT/dist/$OUT_NAME.app/Contents/MacOS/$OUT_NAME" ]]; then
    EXE="$ROOT/dist/$OUT_NAME.app/Contents/MacOS/$OUT_NAME"
  else
    echo "Build failed: binary not found in dist/" >&2
    exit 1
  fi
fi

chmod +x "$EXE"
echo "OK: $EXE"
