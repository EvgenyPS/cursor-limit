# FILE: src/i18n.py
# PURPOSE: Локализация UI (ru / en) + перевод ответов Cursor.
# WHY: Пользователь хочет переключатель языка, а не один фиксированный.

from __future__ import annotations

import re
from typing import Literal

from .settings_store import load_lang as _load_lang
from .settings_store import save_lang as _save_lang

Lang = Literal["ru", "en"]

# Ключ → {ru, en}
_STRINGS: dict[str, dict[Lang, str]] = {
    "app_title": {"ru": "Лимиты Cursor", "en": "Cursor Limits"},
    "open_details": {"ru": "Открыть детали", "en": "Open details"},
    "refresh_now": {"ru": "Обновить сейчас", "en": "Refresh now"},
    "check_online": {"ru": "Проверить онлайн", "en": "Check online"},
    "autostart": {"ru": "Автозапуск с Windows", "en": "Start with Windows"},
    "open_dashboard": {"ru": "Открыть кабинет Cursor", "en": "Open Cursor dashboard"},
    "exit": {"ru": "Выход", "en": "Quit"},
    "language": {"ru": "Язык: Русский", "en": "Language: English"},
    "switch_to_ru": {"ru": "Русский", "en": "Russian"},
    "switch_to_en": {"ru": "English", "en": "English"},
    "refresh": {"ru": "Обновить", "en": "Refresh"},
    "online": {"ru": "Онлайн", "en": "Online"},
    "dashboard": {"ru": "Кабинет", "en": "Dashboard"},
    "install_statusbar": {
        "ru": "Установить панель Cursor",
        "en": "Install Cursor status bar",
    },
    "install_statusbar_short": {"ru": "Панель IDE", "en": "IDE bar"},
    "statusbar_title": {
        "ru": "Панель Cursor",
        "en": "Cursor status bar",
    },
    "statusbar_ok": {
        "ru": "Расширение установлено:\n{path}\n\nВ Cursor: Ctrl+Shift+P → Developer: Reload Window",
        "en": "Extension installed:\n{path}\n\nIn Cursor: Ctrl+Shift+P → Developer: Reload Window",
    },
    "statusbar_fail": {
        "ru": "Не удалось установить панель:\n{err}",
        "en": "Failed to install status bar:\n{err}",
    },
    "close": {"ru": "Закрыть", "en": "Close"},
    "loading": {"ru": "Загрузка…", "en": "Loading…"},
    "refreshing": {"ru": "Обновляю…", "en": "Refreshing…"},
    "checking_online": {"ru": "Проверяю онлайн…", "en": "Checking online…"},
    "online_check_title": {"ru": "Проверка онлайн", "en": "Online check"},
    "footer_tray": {
        "ru": "Закрытие окна не завершает программу. Выход — ПКМ по иконке в трее.",
        "en": "Closing the window keeps the tray app running. Quit via tray menu.",
    },
    "welcome": {"ru": "С возвращением.", "en": "Welcome."},
    "current_plan": {"ru": "Текущий план", "en": "Current plan"},
    "account_balance": {"ru": "Баланс аккаунта", "en": "Account balance"},
    "pct_used": {"ru": "{pct:.0f}% использовано", "en": "{pct:.0f}% used"},
    "weekly_included": {
        "ru": "Недельный included usage",
        "en": "Weekly included usage",
    },
    "monthly_included": {
        "ru": "Месячный included usage",
        "en": "Monthly included usage",
    },
    "resets_on": {"ru": "Сброс {date}", "en": "Resets {date}"},
    "used_this_month": {
        "ru": "{amount} за этот месяц",
        "en": "{amount} used this month",
    },
    "spend_period": {
        "ru": "Потрачено за период: {usd}  ·  {rub}",
        "en": "Spent this period: {usd}  ·  {rub}",
    },
    "limit_line": {
        "ru": "Лимит: {used_usd} / {limit_usd}  ·  {used_rub} / {limit_rub}",
        "en": "Limit: {used_usd} / {limit_usd}  ·  {used_rub} / {limit_rub}",
    },
    "remaining_line": {
        "ru": "Не использовано: {usd}  ·  {rub}",
        "en": "Unused: {usd}  ·  {rub}",
    },
    "credits_left": {
        "ru": "Доступно: {amount}",
        "en": "Credits available: {amount}",
    },
    "period_range": {
        "ru": "Период подписки: {start} → {end}",
        "en": "Billing period: {start} → {end}",
    },
    "api_usage": {"ru": "API (чужие модели)", "en": "API (third-party)"},
    "open_upgrade": {"ru": "Upgrade", "en": "Upgrade"},
    "activity": {"ru": "Активность", "en": "Activity"},
    "activity_local": {
        "ru": "Активность · локально",
        "en": "Activity · local",
    },
    "activity_api": {
        "ru": "Активность · токены",
        "en": "Activity · tokens",
    },
    "activity_edits": {
        "ru": "AI line edits (локально)",
        "en": "AI line edits (local)",
    },
    "tab_full": {"ru": "Полностью", "en": "Full"},
    "tab_week": {"ru": "Неделя", "en": "Week"},
    "cycle_calendar": {
        "ru": "Лимит цикла",
        "en": "Cycle limit",
    },
    "week_detail": {
        "ru": "Неделя подписки",
        "en": "Subscription week",
    },
    "most_active_month": {
        "ru": "Самый активный месяц",
        "en": "Most active month",
    },
    "mo_jan": {"ru": "янв", "en": "Jan"},
    "mo_feb": {"ru": "фев", "en": "Feb"},
    "mo_mar": {"ru": "мар", "en": "Mar"},
    "mo_apr": {"ru": "апр", "en": "Apr"},
    "mo_may": {"ru": "май", "en": "May"},
    "mo_jun": {"ru": "июн", "en": "Jun"},
    "mo_jul": {"ru": "июл", "en": "Jul"},
    "mo_aug": {"ru": "авг", "en": "Aug"},
    "mo_sep": {"ru": "сен", "en": "Sep"},
    "mo_oct": {"ru": "окт", "en": "Oct"},
    "mo_nov": {"ru": "ноя", "en": "Nov"},
    "mo_dec": {"ru": "дек", "en": "Dec"},
    "day_requests": {"ru": "Запросы", "en": "Requests"},
    "day_events": {"ru": "События", "en": "Events"},
    "day_tokens": {"ru": "Токены", "en": "Tokens"},
    "day_spend": {"ru": "Потрачено", "en": "Spend"},
    "day_today": {"ru": "сегодня", "en": "today"},
    "less": {"ru": "Меньше", "en": "Less"},
    "more": {"ru": "Больше", "en": "More"},
    "most_active_day": {
        "ru": "Самый активный день",
        "en": "Most active day",
    },
    "longest_streak": {"ru": "Рекорд серии", "en": "Longest streak"},
    "current_streak": {"ru": "Текущая серия", "en": "Current streak"},
    "days_n": {"ru": "{n} дн.", "en": "{n} days"},
    "weekly_pool": {
        "ru": "Недельный пул · Grok + Composer + Auto",
        "en": "Weekly pool · Grok + Composer + Auto",
    },
    "included_pool": {
        "ru": "Включённый пул · Grok + Composer + Auto",
        "en": "Included pool · Grok + Composer + Auto",
    },
    "used_left": {
        "ru": "{used:.0f}% использовано  ·  {left:.0f}% осталось",
        "en": "{used:.0f}% used  ·  {left:.0f}% left",
    },
    "no_money": {
        "ru": "Сумма в $ с сервера не пришла — смотри % шкалы",
        "en": "Dollar amounts missing from API — use the % bar",
    },
    "period": {"ru": "Период", "en": "Period"},
    "reset": {"ru": "сброс", "en": "resets"},
    "api_models": {
        "ru": "Чужие модели (API)",
        "en": "Third-party models (API)",
    },
    "api_hint": {
        "ru": "Отдельно от пула Grok",
        "en": "Separate from the Grok pool",
    },
    "calendar": {"ru": "Календарь", "en": "Calendar"},
    "calendar_local": {
        "ru": "Календарь · локальная активность",
        "en": "Calendar · local activity",
    },
    "calendar_api": {
        "ru": "Календарь · токены с сервера",
        "en": "Calendar · server tokens",
    },
    "hover_day": {"ru": "Наведи на день", "en": "Hover a day"},
    "no_data": {"ru": "нет данных", "en": "no data"},
    "local_day": {
        "ru": "{date}: {req} запрос(ов), {ev} событий",
        "en": "{date}: {req} request(s), {ev} events",
    },
    "tokens": {"ru": "Токены", "en": "Tokens"},
    "month": {"ru": "Месяц", "en": "Month"},
    "week": {"ru": "Неделя", "en": "Week"},
    "unused": {"ru": "Не использовано", "en": "Unused"},
    "rate_cbr": {"ru": "Курс ЦБ", "en": "CBR rate"},
    "rate_na": {"ru": "Курс ₽ недоступен", "en": "RUB rate unavailable"},
    "poll_every": {"ru": "опрос {n}с", "en": "poll {n}s"},
    "refresh_sec": {"ru": "Обновление, с", "en": "Refresh, sec"},
    "refresh_hint": {
        "ru": "60–3600 с (1 мин … 1 ч)",
        "en": "60–3600 s (1 min … 1 h)",
    },
    "online_ok": {"ru": "Онлайн: лимиты в порядке", "en": "Online: limits OK"},
    "online_partial": {
        "ru": "Онлайн: лимиты OK · дни/токены недоступны",
        "en": "Online: limits OK · day/token details unavailable",
    },
    "online_fail": {"ru": "Онлайн: нет связи", "en": "Online: no connection"},
    "wd_mon": {"ru": "Пн", "en": "Mo"},
    "wd_tue": {"ru": "Вт", "en": "Tu"},
    "wd_wed": {"ru": "Ср", "en": "We"},
    "wd_thu": {"ru": "Чт", "en": "Th"},
    "wd_fri": {"ru": "Пт", "en": "Fr"},
    "wd_sat": {"ru": "Сб", "en": "Sa"},
    "wd_sun": {"ru": "Вс", "en": "Su"},
    "lang_btn": {"ru": "EN", "en": "RU"},
}


class I18n:
    """Текущий язык + t(key)."""

    def __init__(self, lang: Lang | None = None) -> None:
        self.lang: Lang = lang or load_lang()

    def t(self, key: str, **kwargs: object) -> str:
        pair = _STRINGS.get(key) or {"ru": key, "en": key}
        text = pair.get(self.lang) or pair.get("ru") or key
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, ValueError):
                return text
        return text

    def set_lang(self, lang: Lang) -> None:
        self.lang = lang if lang in ("ru", "en") else "ru"
        save_lang(self.lang)

    def toggle(self) -> Lang:
        self.set_lang("en" if self.lang == "ru" else "ru")
        return self.lang

    def weekdays(self) -> tuple[str, ...]:
        return (
            self.t("wd_mon"),
            self.t("wd_tue"),
            self.t("wd_wed"),
            self.t("wd_thu"),
            self.t("wd_fri"),
            self.t("wd_sat"),
            self.t("wd_sun"),
        )


def load_lang() -> Lang:
    lang = _load_lang()
    return lang if lang in ("ru", "en") else "ru"  # type: ignore[return-value]


def save_lang(lang: Lang) -> None:
    _save_lang(lang if lang in ("ru", "en") else "ru")


def translate_display_message(msg: str | None, lang: Lang) -> str:
    """Переводит типовые английские фразы Cursor (или оставляет EN)."""
    if not msg:
        return ""
    m = msg.strip()
    pat = re.match(
        r"You've used\s+(\d+(?:\.\d+)?)\s*%\s+of your included\s+(.+)",
        m,
        re.IGNORECASE,
    )
    if not pat:
        return m
    pct, kind = pat.group(1), pat.group(2).lower()
    if lang == "en":
        return m
    if "api" in kind:
        return f"Использовано {pct}% включённого API-лимита"
    if "total" in kind:
        return f"Использовано {pct}% общего включённого лимита"
    return f"Использовано {pct}% включённого лимита"
