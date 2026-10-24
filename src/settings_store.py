# FILE: src/settings_store.py
# PURPOSE: Локальные настройки UI (~/.cursor-limits/settings.json).
# WHY: Язык и интервал опроса не должны жить в .env и не попадают в git.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SETTINGS = Path.home() / ".cursor-limits" / "settings.json"

# Допустимый диапазон polling (сек): 1 мин … 1 час
REFRESH_MIN = 60
REFRESH_MAX = 3600
REFRESH_DEFAULT = 60


def _read() -> dict[str, Any]:
    try:
        if _SETTINGS.is_file():
            data = json.loads(_SETTINGS.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {}


def _write(data: dict[str, Any]) -> None:
    try:
        _SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def load_lang() -> str:
    lang = _read().get("lang", "ru")
    return lang if lang in ("ru", "en") else "ru"


def save_lang(lang: str) -> None:
    data = _read()
    data["lang"] = lang if lang in ("ru", "en") else "ru"
    _write(data)


def clamp_refresh(sec: int | float | str) -> int:
    try:
        n = int(sec)
    except (TypeError, ValueError):
        n = REFRESH_DEFAULT
    return max(REFRESH_MIN, min(REFRESH_MAX, n))


def load_refresh_interval_sec(default: int = REFRESH_DEFAULT) -> int:
    raw = _read().get("refresh_interval_sec", default)
    return clamp_refresh(raw if raw is not None else default)


def save_refresh_interval_sec(sec: int) -> int:
    value = clamp_refresh(sec)
    data = _read()
    data["refresh_interval_sec"] = value
    _write(data)
    return value
