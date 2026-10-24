# FILE: src/autostart.py
# PURPOSE: Автозапуск CursorLimits при входе в систему (Windows / macOS / Linux).
# WHY: На Windows — HKCU Run; на macOS — LaunchAgent; на Linux — .desktop в autostart.

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

# Идентификаторы — не менять без миграции
RUN_VALUE_NAME = "CursorLimits"
MAC_LABEL = "com.evgenyps.cursor-limits"
LINUX_DESKTOP_NAME = "cursor-limits.desktop"


def _executable_and_args() -> tuple[str, list[str]]:
    """Путь к бинарнику/интерпретатору и аргументы для автозапуска."""
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve()), []
    root = Path(__file__).resolve().parent.parent
    script = root / "run_tray.py"
    if platform.system() == "Windows":
        pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
        python = root / ".venv" / "Scripts" / "python.exe"
        exe = pythonw if pythonw.is_file() else (python if python.is_file() else Path(sys.executable))
    else:
        venv_py = root / ".venv" / "bin" / "python"
        exe = venv_py if venv_py.is_file() else Path(sys.executable)
    return str(exe.resolve()), [str(script.resolve())]


def _windows_command() -> str:
    exe, args = _executable_and_args()
    if args:
        return f'"{exe}" "{args[0]}"'
    return f'"{exe}"'


def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"


def _linux_desktop_path() -> Path:
    return Path.home() / ".config" / "autostart" / LINUX_DESKTOP_NAME


def _write_mac_plist() -> Path:
    exe, args = _executable_and_args()
    # ProgramArguments: exe + опциональный скрипт
    arg_xml = "\n".join(f"    <string>{a}</string>" for a in [exe, *args])
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{MAC_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{arg_xml}
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <false/>
</dict>
</plist>
"""
    path = _mac_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_linux_desktop() -> Path:
    exe, args = _executable_and_args()
    cmd = exe if not args else f"{exe} {args[0]}"
    content = f"""[Desktop Entry]
Type=Application
Version=1.0
Name=Cursor Limits
Comment=Cursor usage limits in the system tray
Exec={cmd}
Terminal=false
X-GNOME-Autostart-enabled=true
"""
    path = _linux_desktop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def is_enabled() -> bool:
    system = platform.system()
    if system == "Windows":
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
    if system == "Darwin":
        return _mac_plist_path().is_file()
    return _linux_desktop_path().is_file()


def enable() -> str:
    """Включает автозапуск. Возвращает путь/команду для отладки."""
    system = platform.system()
    if system == "Windows":
        import winreg

        cmd = _windows_command()
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, cmd)
        return cmd
    if system == "Darwin":
        return str(_write_mac_plist())
    return str(_write_linux_desktop())


def disable() -> None:
    system = platform.system()
    if system == "Windows":
        try:
            import winreg
        except ImportError:
            return
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
        except (FileNotFoundError, OSError):
            pass
        return
    if system == "Darwin":
        path = _mac_plist_path()
        if path.is_file():
            path.unlink()
        return
    path = _linux_desktop_path()
    if path.is_file():
        path.unlink()


def toggle() -> bool:
    """Переключает автозапуск. True = теперь включён."""
    if is_enabled():
        disable()
        return False
    enable()
    return True


def supported() -> bool:
    """Автозапуск реализован на всех трёх десктопных ОС."""
    return platform.system() in {"Windows", "Darwin", "Linux"}
