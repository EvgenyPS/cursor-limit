# FILE: src/status_bar_install.py
# PURPOSE: Установка расширения status bar в ~/.cursor/extensions из UI/CLI.
# WHY: Чтобы не гонять руками PowerShell — кнопка в окне трея.

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .config import ROOT_DIR

EXT_FOLDER_NAME = "local.cursor-limits-status-bar-0.1.0"


def extension_source_dir() -> Path | None:
    """Где лежит исходник cursor-status-bar (dev / рядом с exe / внутри onefile)."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "cursor-status-bar")
        candidates.append(Path(sys.executable).resolve().parent / "cursor-status-bar")
    candidates.append(ROOT_DIR / "cursor-status-bar")
    for path in candidates:
        if (path / "package.json").is_file() and (path / "extension.js").is_file():
            return path
    return None


def extension_dest_dir() -> Path:
    return Path.home() / ".cursor" / "extensions" / EXT_FOLDER_NAME


def is_status_bar_installed() -> bool:
    dst = extension_dest_dir()
    return (dst / "package.json").is_file() and (dst / "extension.js").is_file()


def install_status_bar() -> Path:
    """Копирует расширение в ~/.cursor/extensions. Raises RuntimeError при ошибке."""
    src = extension_source_dir()
    if src is None:
        raise RuntimeError(
            "Папка cursor-status-bar не найдена. "
            "Собери exe скриптом build-exe.ps1 или запускай из репозитория."
        )
    dst = extension_dest_dir()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst
