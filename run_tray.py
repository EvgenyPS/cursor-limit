# FILE: run_tray.py
# PURPOSE: Точка входа для .exe / автозапуска (без -m и без зависимости от cwd).
# WHY: HKCU\\...\\Run и PyInstaller любят один конкретный файл.

from src.main import main

if __name__ == "__main__":
    raise SystemExit(main())
