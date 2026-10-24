# Установка и безопасность — Cursor Limits

## Требования

- Windows 11
- Python 3.12+
- Залогиненный Cursor IDE на этой машине (нужен локальный `accessToken`)

## Установка

### Программа (.exe)

1. `powershell -ExecutionPolicy Bypass -File .\scripts\build-exe.ps1`
2. Запусти `dist\CursorLimits.exe`
3. В трее включи **«Автозапуск с Windows»**
4. Status bar: `scripts\install-status-bar.ps1` → Reload Window в Cursor

### Dev (из исходников)

1. `python -m venv .venv` → `pip install -r requirements.txt`
2. `pythonw .\run_tray.py` (или `python -m src`)
3. Автозапуск: ПКМ по трею или `python -m src --install-autostart`

## Где что лежит

| Путь | Содержимое |
|------|------------|
| `%APPDATA%\Cursor\User\globalStorage\state.vscdb` | Источник `accessToken` (только чтение) |
| `%USERPROFILE%\.cursor-limits\cache.json` | Кэш для status bar (без секретов) |
| `data\cache.json` | Копия кэша в репозитории |
| `.env` | Опциональный fallback-токен (в `.gitignore`) |

## Безопасность

См. полный чеклист: [SECURITY.md](SECURITY.md).

1. **Основной режим:** credentials только из локальной БД Cursor, в RAM процесса.
2. Приложение **не пишет** accessToken на диск.
3. Расширение status bar **не ходит в сеть** и не знает токен — только читает JSON.
4. Курс валют — публичный JSON ЦБ (`cbr-xml-daily.ru`).
5. Не коммить `.env`, `data/cache.json`, скрины DevTools с cookie.

### Fallback `.env`

Если локальная БД недоступна (редкий случай):

```env
CURSOR_USER_ID=user_...
CURSOR_ACCESS_TOKEN=eyJ...
```

или полный `CURSOR_SESSION_TOKEN=user_...::eyJ...`.

## Troubleshooting

| Симптом | Что делать |
|---------|------------|
| «Не удалось получить credentials» | Открой Cursor, убедись что залогинен, перезапусти трей |
| «Сессия истекла» | Logout/Login в Cursor IDE |
| Status bar «нет кэша» | Сначала запусти трей хотя бы раз (`--once` тоже пишет кэш) |
| Курс «—» | Проверь доступ к `https://www.cbr-xml-daily.ru/daily_json.js` |
| Иконки нет в трее | Win11: «Переполнение» панели задач → закрепить иконку |
| Токены / недели = 0, но $ есть | В части регионов `api2` и dashboard POST отдают 403. `$`/`₽` берутся из `usage-summary` — это ок |
| План Free в stripe, Super в summary | Берём `membershipType` из usage-summary |

## Отладка API

```powershell
.\.venv\Scripts\python.exe -m src --once
```

В JSON смотри `used` / `limit` / `remaining` / `month_tokens` / `weeks`.  
Поле `auth_source` покажет, откуда взяли credentials (`local:state.vscdb` — идеально).

## Интервал обновления

В окне деталей (шапка): spinbox **60–3600 секунд**. Пишется в  
`%USERPROFILE%\.cursor-limits\settings.json`.  
Либо env: `CURSOR_LIMITS_REFRESH_SEC=120`.
