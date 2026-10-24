# FILE: src/models.py
# PURPOSE: Модели снимка usage (месяц / неделя / токены / FX).
# WHY: UI и API не должны тащить «сырой» JSON — работаем с понятными dataclass.

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Money:
    """Сумма в центах USD + конвертация в рубли по курсу ЦБ."""

    cents: int = 0
    usd_rub_rate: float | None = None

    @property
    def usd(self) -> float:
        return self.cents / 100.0

    @property
    def rub(self) -> float | None:
        if self.usd_rub_rate is None:
            return None
        return self.usd * self.usd_rub_rate

    def format_usd(self) -> str:
        return f"${self.usd:,.2f}"

    def format_rub(self) -> str:
        if self.rub is None:
            return "—"
        # Без копеек в UI — для лимитов удобнее целые рубли
        return f"{self.rub:,.0f} ₽".replace(",", " ")


@dataclass(slots=True)
class TokenStats:
    """Суммарные токены за период (факт из агрегатов Cursor)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_billable_ish(self) -> int:
        """Грубая «сумма» для отображения: in+out+cache_write.

        Cache-read обычно дешевле и огромный — в общий счётчик не мешаем,
        чтобы не пугать космическими миллионами. Отдельно всё равно видно.
        """
        return self.input_tokens + self.output_tokens + self.cache_write_tokens

    def format_short(self) -> str:
        return _human_int(self.total_billable_ish)


@dataclass(slots=True)
class WeekBucket:
    """Одна календарная неделя внутри billing cycle."""

    index: int
    start: datetime
    end: datetime
    spend: Money = field(default_factory=Money)
    tokens: TokenStats = field(default_factory=TokenStats)
    is_current: bool = False

    def label(self) -> str:
        # Локально читаемая метка: «Нед. 2 · 06–12 окт»
        a = self.start.strftime("%d.%m")
        b = self.end.strftime("%d.%m")
        mark = " ●" if self.is_current else ""
        return f"Нед. {self.index} · {a}–{b}{mark}"


@dataclass(slots=True)
class DayBucket:
    """Один день — для календаря как в ЛК Cursor."""

    date: str  # YYYY-MM-DD
    tokens: TokenStats = field(default_factory=TokenStats)
    spend_cents: int = 0
    # Локальная активность (когда API токенов по дням недоступен)
    local_requests: int = 0
    local_events: int = 0
    source: str = "none"  # api | local | mixed
    is_today: bool = False

    @property
    def intensity(self) -> float:
        """0..1 для заливки ячейки календаря."""
        if self.tokens.total_billable_ish > 0:
            # нормируем снаружи по max дня
            return float(self.tokens.total_billable_ish)
        return float(self.local_requests or self.local_events)


@dataclass(slots=True)
class UsageSnapshot:
    """Полный снимок для трея / попапа / кэша status bar."""

    fetched_at: str = field(default_factory=_utc_now_iso)
    plan_name: str = "Cursor"
    membership: str = ""
    error: str | None = None

    # Месячный (billing cycle) лимит в $
    cycle_start: datetime | None = None
    cycle_end: datetime | None = None
    used: Money = field(default_factory=Money)
    limit: Money = field(default_factory=Money)
    remaining: Money = field(default_factory=Money)
    total_percent: float = 0.0
    auto_percent: float | None = None
    api_percent: float | None = None

    # Недельный лимит (если план weekly — Premium и т.п.)
    weekly_enabled: bool = False
    weekly_percent: float | None = None
    weekly_used: Money = field(default_factory=Money)
    weekly_limit: Money = field(default_factory=Money)
    weekly_remaining: Money = field(default_factory=Money)
    weekly_resets_at: datetime | None = None

    # Токены: месяц и текущая неделя
    month_tokens: TokenStats = field(default_factory=TokenStats)
    week_tokens: TokenStats = field(default_factory=TokenStats)
    # Cursor редко даёт «лимит токенов» числом — обычно лимит в $.
    # Если сервер прислал — покажем; иначе None.
    month_token_limit: int | None = None
    week_token_limit: int | None = None

    weeks: list[WeekBucket] = field(default_factory=list)
    # Календарь по дням текущего billing cycle (лимиты / неделя)
    days: list[DayBucket] = field(default_factory=list)
    days_source: str = "none"  # api | local | mixed
    # Год локальной активности — как «AI line edits» в ЛК (heatmap Полностью)
    year_days: list[DayBucket] = field(default_factory=list)
    usd_rub_rate: float | None = None
    display_message: str = ""
    # Пояснения для UI (регион, отсутствие token-limit и т.п.)
    notes: list[str] = field(default_factory=list)
    # Результат онлайн-проверки эндпоинтов
    online_line: str = ""
    online_usage_ok: bool = False
    online_details_ok: bool = False

    def usage_percent(self) -> float:
        """% недельного пула (или общего included) для светофора."""
        if self.weekly_enabled and self.weekly_percent is not None:
            return float(self.weekly_percent)
        return float(self.total_percent or 0.0)

    @property
    def level(self) -> str:
        """ok | caution | warning | error — 0–50 / 50–85 / 85–100."""
        if self.error:
            return "error"
        pct = self.usage_percent()
        if pct >= 85:
            return "warning"
        if pct >= 50:
            return "caution"
        return "ok"

    def status_bar_color(self) -> str:
        """Плавный цвет индикатора: зелёный→жёлтый (0–50)→красный (50–100)."""
        from .traffic_color import smooth_traffic_hex

        return smooth_traffic_hex(self.usage_percent())

    def days_until_reset(self) -> int | None:
        reset_at = self.weekly_resets_at or self.cycle_end
        if reset_at is None:
            return None
        now = datetime.now(timezone.utc)
        if reset_at.tzinfo is None:
            reset_at = reset_at.replace(tzinfo=timezone.utc)
        sec = (reset_at - now).total_seconds()
        return max(0, int(sec // 86400))

    def today_tokens(self) -> int:
        for d in self.days:
            if d.is_today:
                if d.tokens.total_billable_ish:
                    return d.tokens.total_billable_ish
                return int(d.local_events or d.local_requests)
        for d in self.year_days:
            if d.is_today:
                return int(d.local_events or d.local_requests)
        return 0

    def tray_title(self) -> str:
        """Короткий текст для tooltip иконки (лимит Windows ~128 символов)."""
        if self.error:
            return f"Cursor Limits: {self.error[:100]}"
        used = self.used.format_usd()
        lim = self.limit.format_usd()
        rub = self.remaining.format_rub()
        line = f"{self.plan_name}: {used}/{lim} ({self.total_percent:.0f}%) · ост. {rub}"
        if self.weekly_enabled and self.weekly_percent is not None:
            line += f" · нед. {self.weekly_percent:.0f}%"
        return line[:127]

    def status_bar_text(self) -> str:
        """Строка status bar: ●% · spent $ · ₽ · дни до сброса · токены сегодня."""
        if self.error:
            return f"⚠ {self.error[:40]}"
        pct = self.usage_percent()
        # Потрачено без «/ лимит» — только факт
        spent_m = (
            self.weekly_used
            if self.weekly_enabled and self.weekly_used.cents
            else self.used
        )
        days = self.days_until_reset()
        days_s = f"{days}д" if days is not None else "—д"
        today = self.today_tokens()
        return (
            f"● {pct:.0f}% · {spent_m.format_usd()} · {spent_m.format_rub()} "
            f"· {days_s} · сегодня {_human_int(today)}"
        )

    def status_bar_tooltip(self) -> str:
        """Hover: по дням недели — № · день · токены · $ · ₽."""
        if self.error:
            return self.error
        lines = [
            f"{self.plan_name} · неделя {self.usage_percent():.0f}%",
            f"Потрачено: {self.used.format_usd()} · {self.used.format_rub()}",
        ]
        days_left = self.days_until_reset()
        if days_left is not None:
            lines.append(f"До сброса: {days_left} дн.")
        lines.append("")
        lines.append("Неделя (день · токены · $ · ₽):")
        wd = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
        week_days = _week_days_for_tooltip(self)
        if not week_days:
            lines.append("нет данных по дням")
        else:
            for idx, d in enumerate(week_days, start=1):
                try:
                    dt = datetime.fromisoformat(d.date).date()
                    day_label = f"{wd[dt.weekday()]} {dt.strftime('%d.%m')}"
                except ValueError:
                    day_label = d.date
                tok = d.tokens.total_billable_ish or (d.local_events or d.local_requests)
                spend = Money(cents=d.spend_cents, usd_rub_rate=self.usd_rub_rate)
                # Если API не дал $ по дню — пропорционально от недельного spend
                if spend.cents <= 0 and tok and self.week_tokens.total_billable_ish:
                    week_tok = self.week_tokens.total_billable_ish
                    base = self.weekly_used if self.weekly_used.cents else self.used
                    if week_tok > 0 and base.cents > 0:
                        spend = Money(
                            cents=int(round(base.cents * (tok / week_tok))),
                            usd_rub_rate=self.usd_rub_rate,
                        )
                lines.append(
                    f"{idx} · {day_label} · {_human_int(int(tok))} · "
                    f"{spend.format_usd()} · {spend.format_rub()}"
                )
        return "\n".join(lines)

    def to_cache_dict(self) -> dict[str, Any]:
        """Сериализация в JSON-кэш (без сырых токенов авторизации)."""
        data = asdict(self)
        # datetime → iso
        for key in ("cycle_start", "cycle_end", "weekly_resets_at"):
            val = getattr(self, key)
            data[key] = val.isoformat() if isinstance(val, datetime) else None
        weeks_out = []
        for w in self.weeks:
            weeks_out.append(
                {
                    "index": w.index,
                    "start": w.start.isoformat(),
                    "end": w.end.isoformat(),
                    "is_current": w.is_current,
                    "spend_usd": w.spend.usd,
                    "spend_rub": w.spend.rub,
                    "tokens": asdict(w.tokens),
                    "label": w.label(),
                }
            )
        data["weeks"] = weeks_out
        data["days"] = [
            {
                "date": d.date,
                "tokens": asdict(d.tokens),
                "spend_cents": d.spend_cents,
                "local_requests": d.local_requests,
                "local_events": d.local_events,
                "source": d.source,
                "is_today": d.is_today,
            }
            for d in self.days
        ]
        data["days_source"] = self.days_source
        # Год — укороченно (для status bar / отладки), без тяжёлых tokens
        data["year_days"] = [
            {
                "date": d.date,
                "local_requests": d.local_requests,
                "local_events": d.local_events,
                "is_today": d.is_today,
            }
            for d in self.year_days
        ]
        data["status_bar_text"] = self.status_bar_text()
        data["status_bar_tooltip"] = self.status_bar_tooltip()
        data["status_bar_color"] = self.status_bar_color()
        data["status_bar_percent"] = self.usage_percent()
        data["tray_title"] = self.tray_title()
        data["level"] = self.level
        return data


def _week_days_for_tooltip(snap: UsageSnapshot) -> list[DayBucket]:
    """7 дней текущей недели для hover status bar."""
    from datetime import date, timedelta

    today = date.today()
    if snap.weekly_enabled and snap.cycle_start:
        start = snap.cycle_start.astimezone(timezone.utc).date()
        if (today - start).days > 7 or (today - start).days < 0:
            start = today - timedelta(days=today.weekday())
    else:
        start = today - timedelta(days=today.weekday())

    by_date = {d.date: d for d in snap.year_days}
    for d in snap.days:
        by_date[d.date] = d
    out: list[DayBucket] = []
    for i in range(7):
        key = (start + timedelta(days=i)).isoformat()
        out.append(by_date.get(key) or DayBucket(date=key))
    return out


def _human_int(n: int) -> str:
    """1234567 → 1.2M, 15400 → 15.4K."""
    abs_n = abs(n)
    if abs_n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if abs_n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def parse_ms_datetime(value: Any) -> datetime | None:
    """Парсит ISO-строку или unix-ms (str/int) в aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, (int, float)):
        # секунды vs миллисекунды
        ms = int(value)
        if ms < 10_000_000_000:
            ms *= 1000
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return parse_ms_datetime(int(s))
        try:
            # 2026-04-02T14:11:55.000Z
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None
