# FILE: src/daily_usage.py
# PURPOSE: Календарь usage по дням — как в ЛК Cursor.
# WHY: Dashboard API с токенами по дням часто 403 (region). Тогда берём
#      локальную активность из ~/.cursor/ai-tracking (запросы/события).
#      Когда API доступен — реальные токены из GetAggregatedUsageEvents.

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .auth import CursorCredentials
from .config import AppConfig
from .cursor_api import CursorApiClient, CursorApiError
from .models import DayBucket, TokenStats


def _sum_agg(data: dict[str, Any]) -> tuple[TokenStats, int]:
    tokens = TokenStats()
    total_cents = 0
    aggs = data.get("aggregations") or []
    if not isinstance(aggs, list):
        aggs = []
    if data.get("totalInputTokens") is not None or data.get("totalOutputTokens") is not None:
        tokens.input_tokens = int(float(data.get("totalInputTokens") or 0))
        tokens.output_tokens = int(float(data.get("totalOutputTokens") or 0))
        tokens.cache_write_tokens = int(float(data.get("totalCacheWriteTokens") or 0))
        tokens.cache_read_tokens = int(float(data.get("totalCacheReadTokens") or 0))
        if data.get("totalCostCents") is not None:
            total_cents = int(float(data["totalCostCents"]))
    need = tokens.total_billable_ish == 0
    for row in aggs:
        if not isinstance(row, dict):
            continue
        if need:
            tokens.input_tokens += int(float(row.get("inputTokens") or 0))
            tokens.output_tokens += int(float(row.get("outputTokens") or 0))
            tokens.cache_write_tokens += int(float(row.get("cacheWriteTokens") or 0))
            tokens.cache_read_tokens += int(float(row.get("cacheReadTokens") or 0))
        cents = row.get("totalCents")
        if cents is not None:
            total_cents += int(round(float(cents)))
    return tokens, total_cents


def _daterange(start: date, end: date) -> list[date]:
    """Inclusive start, exclusive end (как python range)."""
    out: list[date] = []
    cur = start
    while cur < end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def load_local_activity(days: list[date]) -> dict[str, tuple[int, int]]:
    """Из ai-code-tracking.db: date -> (distinct requests, hash events)."""
    db = Path.home() / ".cursor" / "ai-tracking" / "ai-code-tracking.db"
    result = {d.isoformat(): (0, 0) for d in days}
    if not db.is_file() or not days:
        return result
    start_ms = int(
        datetime(days[0].year, days[0].month, days[0].day, tzinfo=timezone.utc).timestamp()
        * 1000
    )
    end_ms = int(
        datetime(
            days[-1].year, days[-1].month, days[-1].day, tzinfo=timezone.utc
        ).timestamp()
        * 1000
    ) + 86_400_000
    try:
        conn = sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return result
    try:
        rows = conn.execute(
            """
            SELECT date(createdAt/1000, 'unixepoch') AS d,
                   COUNT(DISTINCT requestId) AS reqs,
                   COUNT(*) AS ev
            FROM ai_code_hashes
            WHERE createdAt >= ? AND createdAt < ?
            GROUP BY d
            """,
            (start_ms, end_ms),
        ).fetchall()
        for d, reqs, ev in rows:
            if d in result:
                result[d] = (int(reqs or 0), int(ev or 0))
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return result


def fetch_api_day_tokens(
    client: CursorApiClient,
    cfg: AppConfig,
    day: date,
) -> tuple[TokenStats, int] | None:
    """Токены за один UTC-день. None = API недоступен."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    s = int(start.timestamp() * 1000)
    e = int(end.timestamp() * 1000) - 1
    try:
        data = client.get_aggregated_usage_events(s, e)
    except CursorApiError as exc:
        if exc.region_blocked:
            return None
        data = client.web_get_aggregated_usage_events(s, e)
        if not data:
            return None
    if not data:
        # web fallback
        data = client.web_get_aggregated_usage_events(s, e)
        if not data:
            return None
    return _sum_agg(data)


def build_day_calendar(
    client: CursorApiClient,
    cfg: AppConfig,
    creds: CursorCredentials,
    *,
    cycle_start: datetime | None,
    cycle_end: datetime | None,
    prefer_days: int = 40,
    full_cycle: bool = True,
) -> tuple[list[DayBucket], str]:
    """Собирает дни для UI-календаря. Возвращает (days, source).

    full_cycle=True — окно = billing cycle из кабинета Cursor (с потолком prefer_days).
    """
    today = datetime.now(timezone.utc).date()
    # Окно: текущий billing cycle из ЛК, иначе последние prefer_days
    if cycle_start and cycle_end:
        start_d = cycle_start.astimezone(timezone.utc).date()
        end_d = cycle_end.astimezone(timezone.utc).date()
        if end_d > today + timedelta(days=1):
            end_d = today + timedelta(days=1)
        span = (end_d - start_d).days
        # Полный цикл кабинета; режем только если цикл аномально длинный
        if (not full_cycle or span > prefer_days) and span > prefer_days:
            start_d = max(start_d, today - timedelta(days=prefer_days - 1))
    else:
        end_d = today + timedelta(days=1)
        start_d = today - timedelta(days=prefer_days - 1)

    day_list = _daterange(start_d, end_d)
    if not day_list:
        return [], "none"

    local = load_local_activity(day_list)

    # Пробуем API на одном дне — если region block, не долбим остальные
    api_ok = False
    api_map: dict[str, tuple[TokenStats, int]] = {}
    probe = fetch_api_day_tokens(client, cfg, day_list[-1])
    if probe is not None:
        api_ok = True
        api_map[day_list[-1].isoformat()] = probe

        def _one(d: date) -> tuple[str, tuple[TokenStats, int] | None]:
            if d == day_list[-1]:
                return d.isoformat(), probe
            local_client = CursorApiClient(creds, cfg)
            try:
                return d.isoformat(), fetch_api_day_tokens(local_client, cfg, d)
            finally:
                local_client.close()

        with ThreadPoolExecutor(max_workers=min(6, len(day_list))) as pool:
            futs = [pool.submit(_one, d) for d in day_list[:-1]]
            for fut in as_completed(futs):
                key, val = fut.result()
                if val is not None:
                    api_map[key] = val

    buckets: list[DayBucket] = []
    for d in day_list:
        key = d.isoformat()
        reqs, ev = local.get(key, (0, 0))
        tok = TokenStats()
        cents = 0
        if key in api_map:
            tok, cents = api_map[key]
            source = "mixed" if (reqs or ev) else "api"
        else:
            source = "local"
        buckets.append(
            DayBucket(
                date=key,
                tokens=tok,
                spend_cents=cents,
                local_requests=reqs,
                local_events=ev,
                source=source,
                is_today=(d == today),
            )
        )

    if api_ok and any(b.tokens.total_billable_ish for b in buckets):
        src = "api"
    elif any(b.local_requests or b.local_events for b in buckets):
        src = "local"
    else:
        src = "none"
    return buckets, src


def build_year_local_calendar(weeks: int = 53) -> list[DayBucket]:
    """Годовой heatmap как в ЛК: только локальная активность (быстро, без API).

    weeks колонок × 7 дней — contribution graph за ~год.
    """
    today = datetime.now(timezone.utc).date()
    # Старт — понедельник недели (weeks-1) назад
    this_monday = today - timedelta(days=today.weekday())
    start_d = this_monday - timedelta(weeks=max(1, weeks) - 1)
    end_d = today + timedelta(days=1)
    day_list = _daterange(start_d, end_d)
    if not day_list:
        return []

    local = load_local_activity(day_list)
    buckets: list[DayBucket] = []
    for d in day_list:
        key = d.isoformat()
        reqs, ev = local.get(key, (0, 0))
        buckets.append(
            DayBucket(
                date=key,
                local_requests=reqs,
                local_events=ev,
                source="local",
                is_today=(d == today),
            )
        )
    return buckets
