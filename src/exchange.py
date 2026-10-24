# FILE: src/exchange.py
# PURPOSE: Курс USD → RUB через JSON ЦБ РФ (+ локальный кэш).
# WHY: Для личного использования официальный курс ЦБ — предсказуемо и бесплатно.

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import DATA_DIR, AppConfig, ensure_data_dir


@dataclass(slots=True)
class FxRate:
    usd_rub: float
    as_of: str  # дата курса от ЦБ, напр. "24.10.2026"
    source: str


_FX_CACHE_FILE = DATA_DIR / "fx_cache.json"


def _read_cache(max_age_sec: int) -> FxRate | None:
    if not _FX_CACHE_FILE.is_file():
        return None
    try:
        raw = json.loads(_FX_CACHE_FILE.read_text(encoding="utf-8"))
        if time.time() - float(raw.get("fetched_at", 0)) > max_age_sec:
            return None
        return FxRate(
            usd_rub=float(raw["usd_rub"]),
            as_of=str(raw.get("as_of", "")),
            source=str(raw.get("source", "cache")),
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def _write_cache(rate: FxRate) -> None:
    ensure_data_dir()
    payload = {
        "fetched_at": time.time(),
        "usd_rub": rate.usd_rub,
        "as_of": rate.as_of,
        "source": rate.source,
    }
    _FX_CACHE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_usd_rub(cfg: AppConfig) -> FxRate:
    """Тянет курс доллара с cbr-xml-daily.ru (обёртка над ЦБ)."""
    cached = _read_cache(cfg.fx_cache_ttl_sec)
    if cached:
        return cached

    resp = requests.get(cfg.cbr_url, timeout=cfg.http_timeout_sec)
    resp.raise_for_status()
    data = resp.json()
    # Valute.USD.Value — курс за 1 USD в рублях
    usd = data["Valute"]["USD"]
    rate = FxRate(
        usd_rub=float(usd["Value"]) / float(usd.get("Nominal", 1)),
        as_of=str(data.get("Date", "")[:10]),
        source="cbr-xml-daily.ru",
    )
    _write_cache(rate)
    return rate


def money_rub(usd: float, rate: float | None) -> float | None:
    if rate is None:
        return None
    return usd * rate
