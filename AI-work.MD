# AI-work — Cursor Limits

## Проект

Личное Windows-приложение для отображения лимитов Cursor:

1. **Системный трей** (Python + pystray) — иконка, tooltip, окно деталей.
2. **Нижняя панель Cursor** — лёгкое расширение, читает кэш без доступа к токену.

Стек: Python 3.12, `pystray`, `Pillow`, `requests`, курс ЦБ РФ, неофициальные API Cursor (`api2.cursor.sh` + `cursor.com`).

## Решения по ТЗ

| Запрос | Реализация |
|--------|------------|
| Python | Трей и вся бизнес-логика на Python |
| Безопаснее для личного use | Токен из локальной `state.vscdb`, не храним на диске; status bar без секретов |
| `$` + курс `₽` | `GetCurrentPeriodUsage` + `cbr-xml-daily.ru` |
| Недельный и общий лимит | Месячный included `$`; weekly — если план/cycle недельный |
| Токены потрачено / не использовано | Факт токенов из `GetAggregatedUsageEvents`; «не использовано» из подписки в `$`/`₽` (у Cursor лимит в деньгах) |
| По неделям | Billing cycle режется на 7-дневные окна, агрегаты параллельно |

## Структура

```
src/           — auth, api, exchange, service, tray, models
cursor-status-bar/ — расширение нижней панели
scripts/       — run-tray.ps1, install-status-bar.ps1
docs/SETUP.md  — установка и безопасность
```

## Что сделано (2026-10-24)

- [x] Каркас Python-приложения + venv/requirements
- [x] Чтение credentials из Cursor SQLite
- [x] Usage snapshot: `$` / `₽` / токены / недели
- [x] Трей + окно деталей (tkinter)
- [x] Кэш `~/.cursor-limits/cache.json` + status bar extension
- [x] README, docs/SETUP.md, AI-work.MD
- [x] Установлен Python 3.12 через winget на машине пользователя
- [x] Фикс вылета на «Обновить» (сеть в фоне + in-place UI)
- [x] Иконка в духе Cursor (тёмная плитка + курсор + дуга %)
- [x] Polling 60с (живого stream API нет)
- [x] Автозапуск HKCU Run + сборка `CursorLimits.exe` (PyInstaller)

## Заметки

- Context7 MCP в окружении недоступен — опирались на публичные reverse-eng docs (OpenUsage, cursor-pulse, gist usage API).
- Официального «лимита токенов» у большинства планов нет: UI честно пишет, что лимит в `$`.
- API неофициальные — при поломке парсера править `src/service.py` / `src/cursor_api.py`.
- На машине пользователя `api2.cursor.sh` и часть dashboard POST отдают **403 region**. Рабочий источник `$`: `GET /api/usage-summary` (cookie из локального токена). Парсер это учитывает.
- Super (X Subscription): недельный пул **включает Grok/Composer/Auto**; поле API = чужие модели с prepaid. Подписи в UI уточнены.
- UI: заполняющиеся шкалы недели (Grok) + API; мерж period/%/summary для `$`; пересобран `dist\CursorLimits.exe`.
- Фикс вылета при закрытии окна: `withdraw()` вместо `destroy()` Tk (на Windows destroy валил весь процесс с треем).
- Календарь по дням (heatmap как в ЛК): при region-block — локальная активность из `ai-tracking`; если API доступен — токены по дням.
- Онлайн-проверка: меню/кнопка «Проверить онлайн», `python -m src --online-check`; лимиты с usage-summary; api2/dashboard часто region.
- UI: компактное горизонтальное окно + переключатель языка RU/EN (сохраняется в `~/.cursor-limits/settings.json`).
- Дизайн как dashboard ЛК: чёрный фон, карточки Current plan / Account balance, белые pill-кнопки, синий heatmap на всю ширину с фиксированным размером (без прыжков), тулбар слева + флаг языка, Online зелёный/красный.
- В карточках снова явно: лимит `$`/`₽`, потрачено за период подписки, остаток, даты цикла.
- Активность: «Полностью» = годовой contribution graph (локальные AI line edits, ~53 недели) + лимит цикла; «Неделя» = 7 компактных строк без скролла.
- UI: футер убран, окно выше, курс ЦБ в шапке, refresh 60–3600 с в `settings.json`.
- Status bar: плавный цвет ● по %, spent $/₽ без лимита, дни до сброса, токены сегодня; hover — дни недели tok/$/₽.
- Публичный git: `.gitignore` (data/dist/venv/.env), `docs/SECURITY.md`, README без локальных путей, MIT LICENSE.
- Иконка трея: `cursor-ico.svg` без чёрного фона; центральная стрелка красятся по % лимита; установка панели IDE из окна/меню.
- Pixso-макеты окна для README: `docs/images/window-full-ru.png`, `window-week-ru.png`, `window-full-en.png` (HTML→code_to_design → PNG 2×).
- README bilingual: `README.md` (RU) + `README.en.md` (EN), переключатель языка сверху/снизу, скриншоты, badges, архитектура, CLI, security.
