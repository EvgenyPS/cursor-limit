# Безопасность

Проект для личного мониторинга лимитов Cursor. Ниже — что хранится, куда ходит трафик и чего **нельзя** класть в git.

## Авторизация

| Способ | Где секрет | В git? |
|--------|------------|--------|
| **Основной** | `accessToken` из локальной SQLite Cursor (`%APPDATA%\Cursor\User\globalStorage\state.vscdb`) | Нет — только чтение на машине |
| Fallback | `.env` (`CURSOR_SESSION_TOKEN` / `CURSOR_ACCESS_TOKEN`) | **Нет** (`.env` в `.gitignore`) |

- Токен **не пишется** в `cache.json`, логи или status bar.
- Cookie `WorkosCursorSessionToken` собирается **в памяти** процесса на время HTTP-запроса.
- Расширение `cursor-status-bar` **не знает** токен и **не ходит** в сеть — только читает JSON-кэш.

## Куда ходят запросы

1. `cursor.com` / `api2.cursor.sh` — usage / billing (с cookie сессии Cursor).
2. `cbr-xml-daily.ru` — курс USD→RUB (без авторизации).

Неофициальные API Cursor могут меняться или отвечать 403 по региону.

## Что в кэше (`~/.cursor-limits/cache.json`)

Только цифры usage: план, %, $, ₽, токены, календарь активности.  
**Не** access token, **не** cookie, **не** пароль.

Папка `data/` в репозитории в git не попадает (см. `.gitignore`).

## Перед публичным push

1. Убедись, что нет `.env` с реальными токенами.
2. `git status` — не должно быть `data/cache.json`, `dist/`, `.venv/`.
3. Не коммить скриншоты ЛК с email/именем, если не хочешь светить аккаунт.
4. Fallback-токены в `.env.example` только как закомментированные плейсхолдеры.

## Рекомендации

- Не запускай чужие форки с доступом к `%APPDATA%\Cursor` без ревью `auth.py`.
- Для CI/чужих машин не прокидывай `CURSOR_ACCESS_TOKEN` в логи.
- При утечке токена — перелогинься в Cursor (токен инвалидируется).
