# FILE: src/config.py
# PURPOSE: Конфигурация приложения (пути, интервалы, пороги цветов).
# WHY: Все «магические числа» в одном месте — проще крутить под себя.

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .settings_store import REFRESH_DEFAULT, load_refresh_interval_sec


def _resolve_root() -> Path:
    """Корень данных: рядом с .exe (frozen) или репозиторий (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


# Корень репозитория / папка рядом с CursorLimits.exe
ROOT_DIR = _resolve_root()

# Локальный кэш:
# 1) в ROOT_DIR/data — удобно смотреть глазами
# 2) в профиле пользователя — status bar Cursor находит кэш из ЛЮБОГО проекта
DATA_DIR = ROOT_DIR / "data"
CACHE_FILE = DATA_DIR / "cache.json"
USER_CACHE_DIR = Path.home() / ".cursor-limits"
USER_CACHE_FILE = USER_CACHE_DIR / "cache.json"

# Опциональный .env (fallback-токен, не основной способ)
load_dotenv(ROOT_DIR / ".env")
load_dotenv(USER_CACHE_DIR / ".env")


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Настройки рантайма. Меняй через .env или правь дефолты ниже."""

    # Как часто опрашивать Cursor (секунды).
    # Живого websocket у Cursor нет — только polling. 60с ≈ «почти live» без долбёжки.
    refresh_interval_sec: int = REFRESH_DEFAULT

    # Пороги «светофора» по % использования included-пула (неделя)
    caution_percent: float = 50.0
    warning_percent: float = 85.0

    # Таймаут HTTP (секунды)
    http_timeout_sec: float = 20.0

    # Курс USD→RUB: ЦБ РФ (JSON). Кэш курса на диск, чтобы не дёргать ЦБ каждый раз.
    cbr_url: str = "https://www.cbr-xml-daily.ru/daily_json.js"
    fx_cache_ttl_sec: int = 3600

    # Показывать ли окно деталей при старте (обычно нет — только трей)
    show_popup_on_start: bool = False


def load_config() -> AppConfig:
    """Читает переопределения из переменных окружения, если заданы."""

    def _int(name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None or raw.strip() == "":
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def _float(name: str, default: float) -> float:
        raw = os.getenv(name)
        if raw is None or raw.strip() == "":
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    # Приоритет: env → settings.json → дефолт
    env_refresh = os.getenv("CURSOR_LIMITS_REFRESH_SEC")
    if env_refresh and env_refresh.strip():
        refresh = _int("CURSOR_LIMITS_REFRESH_SEC", REFRESH_DEFAULT)
    else:
        refresh = load_refresh_interval_sec(REFRESH_DEFAULT)

    return AppConfig(
        refresh_interval_sec=refresh,
        caution_percent=_float("CURSOR_LIMITS_CAUTION_PCT", 50.0),
        warning_percent=_float("CURSOR_LIMITS_WARNING_PCT", 85.0),
        http_timeout_sec=_float("CURSOR_LIMITS_HTTP_TIMEOUT", 20.0),
        fx_cache_ttl_sec=_int("CURSOR_LIMITS_FX_TTL_SEC", 3600),
        show_popup_on_start=os.getenv("CURSOR_LIMITS_SHOW_POPUP", "").lower()
        in {"1", "true", "yes"},
    )


def ensure_data_dir() -> Path:
    """Создаёт data/, если её ещё нет."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
