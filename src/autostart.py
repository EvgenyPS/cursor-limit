# FILE: src/autostart.py
# PURPOSE: Автозапуск CursorLimits при входе в Windows (HKCU Run).
# WHY: Пользователь хочет «программу», а не руками класть ярлык в Startup.

from __future__ import annotations

import sys
from pathlib import Path

# Имя значения в реестре — не менять без миграции
RUN_VALUE_NAME = "CursorLimits"


def _run_command() -> str:
    """Команда, которую Windows выполнит при логине."""
    if getattr(sys, "frozen", False):
        # Собранный .exe (PyInstaller) — без консоли
        return f'"{Path(sys.executable).resolve()}"'
    # Dev-режим: pythonw + run_tray.py (cwd не важен — путь абсолютный)
    root = Path(__file__).resolve().parent.parent
    script = root / "run_tray.py"
    pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    python = root / ".venv" / "Scripts" / "python.exe"
    exe = pythonw if pythonw.is_file() else (python if python.is_file() else Path(sys.executable))
    return f'"{exe.resolve()}" "{script.resolve()}"'


def is_enabled() -> bool:
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        ) as key:
            winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return True
    except OSError:
        return False


def enable() -> str:
    """Включает автозапуск. Возвращает записанную команду."""
    import winreg

    cmd = _run_command()
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, cmd)
    return cmd


def disable() -> None:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, RUN_VALUE_NAME)
    except FileNotFoundError:
        pass
    except OSError:
        # Значения могло не быть
        pass


def toggle() -> bool:
    """Переключает автозапуск. True = теперь включён."""
    if is_enabled():
        disable()
        return False
    enable()
    return True
