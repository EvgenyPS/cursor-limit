# FILE: src/main.py
# PURPOSE: Точка входа CLI: трей / одноразовый снимок / печать status bar.
# WHY: Удобно гонять `python -m src` и `python -m src --once` для отладки.

from __future__ import annotations

import argparse
import json
import sys

from .config import CACHE_FILE, load_config
from .service import refresh_usage
from .tray_app import run_tray


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cursor-limits",
        description="Лимиты Cursor в трее Windows + кэш для нижней панели IDE",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Один раз обновить usage, напечатать JSON и выйти (без трея)",
    )
    p.add_argument(
        "--status-bar",
        action="store_true",
        help="Обновить и напечатать только строку для status bar",
    )
    p.add_argument(
        "--print-cache",
        action="store_true",
        help="Напечатать текущий data/cache.json без запроса к API",
    )
    p.add_argument(
        "--install-autostart",
        action="store_true",
        help="Включить автозапуск с Windows (HKCU Run) и выйти",
    )
    p.add_argument(
        "--uninstall-autostart",
        action="store_true",
        help="Выключить автозапуск и выйти",
    )
    p.add_argument(
        "--online-check",
        action="store_true",
        help="Проверить онлайн-эндпоинты Cursor и выйти",
    )
    p.add_argument(
        "--install-statusbar",
        action="store_true",
        help="Установить расширение нижней панели в ~/.cursor/extensions",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config()

    if args.install_statusbar:
        from .status_bar_install import install_status_bar

        try:
            dst = install_status_bar()
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"OK: {dst}")
        print("В Cursor: Ctrl+Shift+P → Developer: Reload Window")
        return 0

    if args.online_check:
        from .online_check import format_report_text, run_online_check

        report = run_online_check(cfg=cfg)
        print(format_report_text(report))
        return 0 if report.usage_online else 1

    if args.install_autostart or args.uninstall_autostart:
        from . import autostart

        if args.uninstall_autostart:
            autostart.disable()
            print("Автозапуск выключен")
            return 0
        cmd = autostart.enable()
        print("Автозапуск включён:")
        print(cmd)
        return 0

    if args.print_cache:
        if not CACHE_FILE.is_file():
            print("Кэш пуст. Сначала запусти без флагов или с --once.", file=sys.stderr)
            return 1
        print(CACHE_FILE.read_text(encoding="utf-8"))
        return 0

    if args.once or args.status_bar:
        snap, creds = refresh_usage(cfg)
        # Не светим токен — только источник credentials
        if args.status_bar:
            print(snap.status_bar_text())
        else:
            payload = snap.to_cache_dict()
            payload["auth_source"] = creds.source
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1 if snap.error else 0

    # Режим трея (по умолчанию)
    run_tray(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
