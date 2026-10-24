# FILE: src/platform_paths.py
# PURPOSE: Пути к данным Cursor и профиля на Windows / macOS / Linux.
# WHY: state.vscdb лежит в разных каталогах — без этого Mac/Linux не авторизуются.

from __future__ import annotations

import os
import platform
from pathlib import Path


def cursor_user_data_dir() -> Path:
    """Каталог пользовательских данных Cursor IDE (не путать с ~/.cursor)."""
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Cursor"
        return Path.home() / "AppData" / "Roaming" / "Cursor"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Cursor"
    # Linux / BSD: XDG или ~/.config
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "Cursor"
    return Path.home() / ".config" / "Cursor"


def cursor_state_db_path() -> Path:
    return cursor_user_data_dir() / "User" / "globalStorage" / "state.vscdb"


def platform_slug() -> str:
    """Короткое имя платформы для артефактов релиза."""
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows":
        return "windows-x64"
    if system == "Darwin":
        if machine in {"arm64", "aarch64"}:
            return "macos-arm64"
        return "macos-x64"
    if machine in {"aarch64", "arm64"}:
        return "linux-arm64"
    return "linux-x64"
