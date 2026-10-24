# FILE: src/service.py
# PURPOSE: Собирает UsageSnapshot: $ / ₽ / токены / недели billing cycle.
# WHY: Трей и кэш status bar должны получать одну готовую картину, а не сырой JSON.
#
# Важно про «лимит токенов»:
# Cursor на Pro/Ultra считает included usage в ДОЛЛАРАХ, не в токенах.
# Мы показываем факт токенов (месяц / текущая неделя / по неделям) и «неиспользовано»
# из подписки в $ и ₽. Если сервер когда-нибудь пришлёт token limit — тоже покажем.

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

from .auth import CursorCredentials, load_credentials
from .config import (
    CACHE_FILE,
    USER_CACHE_DIR,
    USER_CACHE_FILE,
    AppConfig,
    ensure_data_dir,
    load_config,
)
from .cursor_api import CursorApiClient, CursorApiError
from .exchange import FxRate, fetch_usd_rub
from .models import Money, TokenStats, UsageSnapshot, WeekBucket, parse_ms_datetime


def _as_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_percent_from_message(msg: str) -> float | None:
    """Достаёт 7 из 'You've used 7% of your included usage'."""
    import re

    m = re.search(r"(\d+(?:\.\d+)?)\s*%", msg or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _cents_money(cents: Any, rate: float | None) -> Money:
    return Money(cents=_as_int(cents), usd_rub_rate=rate)


def _sum_aggregations(data: dict[str, Any]) -> tuple[TokenStats, int]:
    """Суммирует aggregations[] → токены + total cents."""
    tokens = TokenStats()
    total_cents = 0
    # Иногда totals лежат на корне
    if any(
        k in data
        for k in (
            "totalInputTokens",
            "total_output_tokens",
            "totalOutputTokens",
        )
    ):
        tokens.input_tokens = _as_int(
            data.get("totalInputTokens") or data.get("total_input_tokens")
        )
        tokens.output_tokens = _as_int(
            data.get("totalOutputTokens") or data.get("total_output_tokens")
        )
        tokens.cache_write_tokens = _as_int(
            data.get("totalCacheWriteTokens") or data.get("total_cache_write_tokens")
        )
        tokens.cache_read_tokens = _as_int(
            data.get("totalCacheReadTokens") or data.get("total_cache_read_tokens")
        )
        root_cents = data.get("totalCostCents")
        if root_cents is not None:
            total_cents = _as_int(root_cents)

    aggs = data.get("aggregations") or []
    if not isinstance(aggs, list):
        return tokens, total_cents

    # Если корневых тоталов нет — суммируем по моделям
    need_sum_tokens = tokens.total_billable_ish == 0
    for row in aggs:
        if not isinstance(row, dict):
            continue
        if need_sum_tokens:
            tokens.input_tokens += _as_int(row.get("inputTokens") or row.get("input_tokens"))
            tokens.output_tokens += _as_int(
                row.get("outputTokens") or row.get("output_tokens")
            )
            tokens.cache_write_tokens += _as_int(
                row.get("cacheWriteTokens") or row.get("cache_write_tokens")
            )
            tokens.cache_read_tokens += _as_int(
                row.get("cacheReadTokens") or row.get("cache_read_tokens")
            )
        cents = row.get("totalCents")
        if cents is None:
            cents = row.get("total_cents")
        total_cents += _as_int(round(float(cents or 0)))
    return tokens, total_cents


def _week_bounds(cycle_start: datetime, cycle_end: datetime) -> list[tuple[datetime, datetime]]:
    """Режем billing cycle на окна по 7 дней (последнее может быть короче)."""
    windows: list[tuple[datetime, datetime]] = []
    cursor = cycle_start
    while cursor < cycle_end:
        end = min(cursor + timedelta(days=7), cycle_end)
        windows.append((cursor, end))
        cursor = end
    return windows


def _is_weekly_plan(plan_info: dict[str, Any]) -> bool:
    info = plan_info.get("planInfo") or plan_info
    if not isinstance(info, dict):
        return False
    period = info.get("includedUsagePeriod") or info.get("included_usage_period")
    if period == 2 or period == "INCLUDED_USAGE_PERIOD_WEEKLY" or period == "weekly":
        return True
    # Эвристика: cycle ровно 7 дней обработаем отдельно по датам
    return False


def _apply_rate_to_snapshot(snap: UsageSnapshot, rate: float | None) -> None:
    snap.usd_rub_rate = rate
    for money in (
        snap.used,
        snap.limit,
        snap.remaining,
        snap.weekly_used,
        snap.weekly_limit,
        snap.weekly_remaining,
    ):
        money.usd_rub_rate = rate
    for week in snap.weeks:
        week.spend.usd_rub_rate = rate


def _apply_plan_dollars(
    snap: UsageSnapshot,
    *,
    used_cents: Any,
    limit_cents: Any,
    remaining_cents: Any,
    pct: float | None,
    auto_pct: float | None,
    api_pct: float | None,
    rate: float | None,
) -> None:
    """Заполняет money-поля снимка (центы → Money)."""
    limit_i = _as_int(limit_cents)
    used_i = _as_int(used_cents)
    if remaining_cents is None and limit_i:
        remaining_i = max(0, limit_i - used_i)
    else:
        remaining_i = _as_int(remaining_cents)
    if pct is None and limit_i > 0:
        pct = min(100.0, max(0.0, used_i / limit_i * 100.0))
    snap.total_percent = float(pct or 0.0)
    snap.auto_percent = auto_pct
    snap.api_percent = api_pct
    snap.used = _cents_money(used_i, rate)
    snap.limit = _cents_money(limit_i, rate)
    snap.remaining = _cents_money(remaining_i, rate)


def build_snapshot(
    client: CursorApiClient,
    fx: FxRate,
    cfg: AppConfig,
    creds: CursorCredentials,
) -> UsageSnapshot:
    rate = fx.usd_rub
    snap = UsageSnapshot(usd_rub_rate=rate)
    api2_blocked = False

    # 1) usage-summary (cookie) — часто единственный рабочий источник в RU/регионах
    summary: dict[str, Any] = {}
    try:
        summary = client.get_usage_summary()
    except CursorApiError as exc:
        if exc.region_blocked:
            snap.notes.append("usage-summary недоступен в регионе")
        else:
            snap.notes.append(str(exc))

    # 2) api2 period (Bearer) — богаче, но часто 403 by region
    period: dict[str, Any] = {}
    plan_info: dict[str, Any] = {}
    stripe: dict[str, Any] = {}
    web_period: dict[str, Any] = {}
    web_plan: dict[str, Any] = {}

    try:
        period = client.get_current_period_usage()
    except CursorApiError as exc:
        api2_blocked = api2_blocked or exc.region_blocked
        web_period = client.web_get_current_period_usage()
        period = web_period

    try:
        plan_info = client.get_plan_info()
    except CursorApiError as exc:
        api2_blocked = api2_blocked or exc.region_blocked
        plan_info = client.web_get_plan_info()

    try:
        stripe = client.get_stripe()
    except CursorApiError:
        stripe = {}

    if not web_period:
        web_period = client.web_get_current_period_usage()
    if not web_plan:
        web_plan = client.web_get_plan_info()

    if api2_blocked:
        snap.notes.append(
            "api2.cursor.sh недоступен в регионе — $ берём из usage-summary; "
            "детальные токены/недели могут быть пустыми"
        )

    # Имя плана: summary.membershipType важнее stripe.free (бывает рассинхрон)
    pi = (plan_info.get("planInfo") or web_plan.get("planInfo") or {})
    if isinstance(pi, dict) and pi.get("planName"):
        snap.plan_name = str(pi["planName"])
    elif summary.get("membershipType"):
        snap.plan_name = str(summary["membershipType"]).replace("_", " ").title()
    elif stripe:
        snap.plan_name = str(
            stripe.get("membershipType")
            or stripe.get("individualMembershipType")
            or "Cursor"
        ).replace("_", " ").title()
    snap.membership = str(
        summary.get("membershipType")
        or stripe.get("membershipType")
        or stripe.get("individualMembershipType")
        or ""
    )

    # --- доллары/% : мержим period + usage-summary (у Super часто % в одном, $ в другом)
    pu = period.get("planUsage") or web_period.get("planUsage") or {}
    if not isinstance(pu, dict):
        pu = {}

    ind_plan = (summary.get("individualUsage") or {}).get("plan") or {}
    if not isinstance(ind_plan, dict):
        ind_plan = {}

    limit_cents = _as_int(pu.get("limit")) or _as_int(ind_plan.get("limit"))
    if limit_cents <= 0 and isinstance(pi, dict):
        limit_cents = _as_int(pi.get("includedAmountCents"))

    remaining_cents = pu.get("remaining")
    if remaining_cents is None:
        remaining_cents = ind_plan.get("remaining")

    used_cents = pu.get("used")
    if used_cents is None:
        used_cents = ind_plan.get("used")
    total_spend = pu.get("totalSpend")
    included_spend = pu.get("includedSpend")

    pct = _as_float(pu.get("totalPercentUsed"))
    if pct is None:
        pct = _as_float(ind_plan.get("totalPercentUsed"))
    # Иногда % только в тексте: "You've used 7% of your included usage"
    if pct is None:
        pct = _parse_percent_from_message(
            str(
                period.get("displayMessage")
                or summary.get("autoModelSelectedDisplayMessage")
                or ""
            )
        )

    auto_pct = _as_float(pu.get("autoPercentUsed"))
    if auto_pct is None:
        auto_pct = _as_float(ind_plan.get("autoPercentUsed"))
    api_pct = _as_float(pu.get("apiPercentUsed"))
    if api_pct is None:
        api_pct = _as_float(ind_plan.get("apiPercentUsed"))
    # Для Super главный индикатор пула — Auto (Grok/Composer), не «средний» total
    if auto_pct is not None and (pct is None or pct == 0):
        pct = auto_pct

    if used_cents is None:
        if total_spend is not None:
            used_cents = total_spend
        elif included_spend is not None:
            used_cents = included_spend
        elif remaining_cents is not None and limit_cents:
            used_cents = limit_cents - _as_int(remaining_cents)
        elif pct is not None and limit_cents:
            used_cents = int(round(limit_cents * pct / 100.0))
        else:
            used_cents = 0

    # Если limit есть в summary, а period отдал used=0 при ненулевом % — пересчитаем
    used_i = _as_int(used_cents)
    if used_i == 0 and pct and pct > 0 and limit_cents > 0:
        used_cents = int(round(limit_cents * pct / 100.0))
        remaining_cents = max(0, limit_cents - _as_int(used_cents))

    if pu or ind_plan or pct is not None:
        _apply_plan_dollars(
            snap,
            used_cents=used_cents,
            limit_cents=limit_cents,
            remaining_cents=remaining_cents,
            pct=pct,
            auto_pct=auto_pct,
            api_pct=api_pct,
            rate=rate,
        )

    snap.cycle_start = parse_ms_datetime(
        period.get("billingCycleStart")
        or web_period.get("billingCycleStart")
        or summary.get("billingCycleStart")
    )
    snap.cycle_end = parse_ms_datetime(
        period.get("billingCycleEnd")
        or web_period.get("billingCycleEnd")
        or summary.get("billingCycleEnd")
    )
    snap.display_message = str(
        period.get("displayMessage")
        or web_period.get("displayMessage")
        or summary.get("autoModelSelectedDisplayMessage")
        or ""
    )

    # Weekly: Super/X Subscription всегда недельный пул; плюс эвристика по датам
    membership_l = snap.membership.lower()
    weekly = (
        _is_weekly_plan(plan_info)
        or _is_weekly_plan(web_plan)
        or membership_l in {"super", "premium", "plus", "ultra"}
    )
    if snap.cycle_start and snap.cycle_end:
        delta = snap.cycle_end - snap.cycle_start
        if timedelta(days=6) <= delta <= timedelta(days=8):
            weekly = True

    if weekly:
        snap.weekly_enabled = True
        # Для шкалы недели берём Auto% (Grok/Composer), иначе total
        snap.weekly_percent = (
            snap.auto_percent
            if snap.auto_percent is not None
            else snap.total_percent
        )
        snap.weekly_used = snap.used
        snap.weekly_limit = snap.limit
        snap.weekly_remaining = snap.remaining
        resets = None
        if isinstance(pi, dict):
            resets = parse_ms_datetime(
                pi.get("includedUsageResetsAt") or pi.get("billingCycleEnd")
            )
        snap.weekly_resets_at = resets or snap.cycle_end

    # 3) Токены за месяц (агрегаты: api2 → fallback web)
    start_ms = int(snap.cycle_start.timestamp() * 1000) if snap.cycle_start else None
    end_ms = int(
        (snap.cycle_end or datetime.now(timezone.utc)).timestamp() * 1000
    )
    now = datetime.now(timezone.utc)
    tokens_ok = False

    def _load_agg(start: int | None, end: int | None) -> dict[str, Any]:
        if start is None or end is None:
            return {}
        try:
            return client.get_aggregated_usage_events(start, end)
        except CursorApiError:
            return client.web_get_aggregated_usage_events(start, end)

    month_agg = _load_agg(start_ms, end_ms)
    if month_agg:
        month_tokens, month_cents_from_agg = _sum_aggregations(month_agg)
        snap.month_tokens = month_tokens
        tokens_ok = month_tokens.total_billable_ish > 0 or month_cents_from_agg > 0
        if snap.used.cents == 0 and month_cents_from_agg > 0:
            snap.used = _cents_money(month_cents_from_agg, rate)
            if snap.limit.cents:
                snap.remaining = _cents_money(
                    max(0, snap.limit.cents - month_cents_from_agg), rate
                )

    # 4) Недельные бакеты (только если агрегаты хоть как-то доступны)
    if snap.cycle_start and snap.cycle_end and (tokens_ok or not api2_blocked):
        windows = _week_bounds(snap.cycle_start, snap.cycle_end)

        def _fetch_week(idx_start_end: tuple[int, datetime, datetime]) -> WeekBucket:
            idx, w_start, w_end = idx_start_end
            is_current = w_start <= now < w_end or (
                idx == len(windows) and w_start <= now <= w_end
            )
            bucket = WeekBucket(
                index=idx,
                start=w_start,
                end=w_end,
                is_current=is_current,
            )
            local = CursorApiClient(creds, cfg)
            try:
                try:
                    agg = local.get_aggregated_usage_events(
                        int(w_start.timestamp() * 1000),
                        int(w_end.timestamp() * 1000),
                    )
                except CursorApiError:
                    agg = local.web_get_aggregated_usage_events(
                        int(w_start.timestamp() * 1000),
                        int(w_end.timestamp() * 1000),
                    )
                tok, cents = _sum_aggregations(agg)
                bucket.tokens = tok
                bucket.spend = _cents_money(cents, rate)
            finally:
                local.close()
            return bucket

        jobs = [
            (idx, w_start, w_end)
            for idx, (w_start, w_end) in enumerate(windows, start=1)
        ]
        weeks: list[WeekBucket] = []
        with ThreadPoolExecutor(max_workers=min(5, max(1, len(jobs)))) as pool:
            futures = [pool.submit(_fetch_week, job) for job in jobs]
            for fut in as_completed(futures):
                weeks.append(fut.result())
        weeks.sort(key=lambda w: w.index)
        for w in weeks:
            if w.is_current:
                snap.week_tokens = w.tokens
        snap.weeks = weeks
    elif snap.cycle_start and snap.cycle_end:
        # Хотя бы пустые бакеты с датами — чтобы UI не был «дырявым»
        windows = _week_bounds(snap.cycle_start, snap.cycle_end)
        snap.weeks = [
            WeekBucket(
                index=idx,
                start=w_start,
                end=w_end,
                is_current=(w_start <= now < w_end)
                or (idx == len(windows) and w_start <= now <= w_end),
            )
            for idx, (w_start, w_end) in enumerate(windows, start=1)
        ]
        snap.notes.append(
            "Детализация токенов по неделям недоступна (API режет регион). "
            "Смотри $ / ₽ по подписке выше."
        )

    # 5) Календарь по дням (как в ЛК): API-токены или локальная активность
    try:
        from .daily_usage import build_day_calendar

        days, days_src = build_day_calendar(
            client,
            cfg,
            creds,
            cycle_start=snap.cycle_start,
            cycle_end=snap.cycle_end,
            prefer_days=40,
            full_cycle=True,
        )
        snap.days = days
        snap.days_source = days_src
        if days_src == "local":
            snap.notes.append(
                "Календарь: токены по дням с сервера недоступны — "
                "локальная активность Cursor (запросы/события)."
            )
        elif days_src == "api":
            snap.notes.append("Календарь: токены по дням онлайн с API Cursor.")
    except Exception as exc:  # noqa: BLE001
        snap.notes.append(f"Календарь по дням не собран: {exc}")

    # Годовой heatmap (как AI line edits в ЛК) — локально, без долбёжки API
    try:
        from .daily_usage import build_year_local_calendar

        snap.year_days = build_year_local_calendar(weeks=53)
    except Exception as exc:  # noqa: BLE001
        snap.notes.append(f"Годовой календарь не собран: {exc}")

    # Статус онлайна из того, что уже дернули (без лишних 6 запросов каждый раз)
    snap.online_usage_ok = bool(summary) and not snap.error
    snap.online_details_ok = (snap.days_source == "api") or (
        snap.month_tokens.total_billable_ish > 0 and not api2_blocked
    )
    if snap.online_usage_ok and snap.online_details_ok:
        snap.online_line = "Онлайн: лимиты + токены/дни OK"
    elif snap.online_usage_ok:
        snap.online_line = "Онлайн: лимиты OK · токены/дни недоступны (region/API)"
    else:
        snap.online_line = "Онлайн: нет связи с usage-summary"
    snap.notes.insert(0, snap.online_line)

    snap.notes.append(
        "Лимит подписки у Cursor в долларах; отдельного «лимита токенов» API обычно не даёт."
    )
    _apply_rate_to_snapshot(snap, rate)
    return snap


def save_cache(snap: UsageSnapshot) -> None:
    """Пишем кэш для нижней панели Cursor (расширение читает этот файл)."""
    ensure_data_dir()
    payload = json.dumps(snap.to_cache_dict(), ensure_ascii=False, indent=2)
    CACHE_FILE.write_text(payload, encoding="utf-8")
    # Дублируем в профиль — чтобы status bar работал, даже если открыт другой workspace
    try:
        USER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        USER_CACHE_FILE.write_text(payload, encoding="utf-8")
    except OSError:
        pass


def refresh_usage(cfg: AppConfig | None = None) -> tuple[UsageSnapshot, CursorCredentials]:
    """Полный цикл: credentials → FX → API → snapshot → cache."""
    cfg = cfg or load_config()
    creds = load_credentials()
    try:
        fx = fetch_usd_rub(cfg)
    except Exception:
        # Без курса всё равно покажем доллары
        fx = FxRate(usd_rub=0.0, as_of="", source="unavailable")
        rate_ok = False
    else:
        rate_ok = True

    client = CursorApiClient(creds, cfg)
    try:
        snap = build_snapshot(client, fx, cfg, creds)
        if not rate_ok:
            snap.usd_rub_rate = None
            _apply_rate_to_snapshot(snap, None)
    except CursorApiError as exc:
        snap = UsageSnapshot(error=str(exc), plan_name="Cursor")
    except Exception as exc:  # noqa: BLE001 — трею нужен любой текст ошибки
        snap = UsageSnapshot(error=f"Ошибка: {exc}", plan_name="Cursor")
    finally:
        client.close()

    save_cache(snap)
    return snap, creds
