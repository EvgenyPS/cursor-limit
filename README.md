<p align="center">
  <img src="cursor-ico.svg" width="72" height="72" alt="Cursor Limits">
</p>

<h1 align="center">Cursor Limits</h1>

<p align="center">
  <strong>Лимиты Cursor в системном трее Windows и в status bar IDE</strong><br>
  <sub>$ · ₽ (ЦБ РФ) · недельный пул · heatmap активности · RU / EN</sub>
</p>

<p align="center">
  <a href="./README.md"><strong>🇷🇺 Русский</strong></a>
  ·
  <a href="./README.en.md">🇬🇧 English</a>
</p>

<p align="center">
  <a href="https://github.com/EvgenyPS/cursor-limit"><img alt="GitHub" src="https://img.shields.io/badge/GitHub-EvgenyPS%2Fcursor--limit-181717?style=flat-square&logo=github"></a>
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4?style=flat-square&logo=windows&logoColor=white">
  <img alt="Python" src="https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/license-PolyForm%20Noncommercial-blue?style=flat-square">
  <img alt="UI" src="https://img.shields.io/badge/UI-RU%20%7C%20EN-111111?style=flat-square">
</p>

---

> [!IMPORTANT]
> Проект использует **неофициальные** API Cursor и **не связан** с Cursor Inc.  
> Эндпоинты и ответы могут меняться; в отдельных регионах часть API отдаёт `403`.

## Возможности

| | |
|---|---|
| **Трей + кабинет** | Иконка в области уведомлений, окно в стиле ЛК Cursor: план, баланс, прогресс |
| **Двойная валюта** | Лимиты и траты в **$** и **₽** по курсу ЦБ РФ |
| **Цикл и неделя** | Included / weekly usage, остаток, дни до сброса |
| **Активность** | Годовой heatmap (локальные AI line edits) и компактная неделя по дням |
| **Status bar IDE** | Строка в нижней панели Cursor без токена и без сети |
| **Локализация** | RU / EN, флаг в шапке, настройки в `settings.json` |
| **Поллинг** | Интервал обновления **60–3600 с**, автозапуск с Windows |

## Скриншоты

Демо-макеты интерфейса (цифры условные, не из реального аккаунта).

<table>
  <tr>
    <td align="center" width="33%">
      <a href="docs/images/window-full-ru.png">
        <img src="docs/images/window-full-ru.png" alt="Кабинет — Полностью (RU)" width="100%">
      </a>
      <br><sub><b>Кабинет · Полностью</b> · RU · ~12%</sub>
    </td>
    <td align="center" width="33%">
      <a href="docs/images/window-week-ru.png">
        <img src="docs/images/window-week-ru.png" alt="Кабинет — Неделя (RU)" width="100%">
      </a>
      <br><sub><b>Кабинет · Неделя</b> · RU · ~48%</sub>
    </td>
    <td align="center" width="33%">
      <a href="docs/images/window-full-en.png">
        <img src="docs/images/window-full-en.png" alt="Dashboard — Full (EN)" width="100%">
      </a>
      <br><sub><b>Dashboard · Full</b> · EN · ~78%</sub>
    </td>
  </tr>
</table>

<details>
<summary>Открыть скриншоты крупнее</summary>

#### Кабинет · вкладка «Полностью» (RU)

![Кабинет Полностью RU](docs/images/window-full-ru.png)

#### Кабинет · вкладка «Неделя» (RU)

![Кабинет Неделя RU](docs/images/window-week-ru.png)

#### Dashboard · Full (EN), высокая загрузка

![Dashboard Full EN](docs/images/window-full-en.png)

</details>

## Скачать

<p>
  <a href="https://github.com/EvgenyPS/cursor-limit/releases/latest">
    <img alt="Latest release" src="https://img.shields.io/github/v/release/EvgenyPS/cursor-limit?style=for-the-badge&label=Download">
  </a>
</p>

Готовая сборка Windows (без установки Python):

1. Открой [Releases](https://github.com/EvgenyPS/cursor-limit/releases/latest)
2. Скачай `CursorLimits-v*-windows-x64.exe`
3. Запусти (Windows может спросить разрешение — SmartScreen для неподписанных приложений нормален)
4. Нужен залогиненный **Cursor IDE** на этой машине
5. Опционально: в трее → **Автозапуск с Windows**; кнопка **«Панель IDE»** для status bar

SHA256 (`v1.0.0`): `3168FE615C341E8502E79849E31B6DDD591AB2CB89F6D972C54D5FAA9D371977`

## Архитектура

```text
┌─────────────────────┐     accessToken (RAM)     ┌──────────────────────┐
│  Cursor IDE         │ ─────────────────────────►│  Cursor Limits (tray) │
│  state.vscdb        │                           │  Python · pystray     │
└─────────────────────┘                           └──────────┬───────────┘
                                                             │
                    ┌────────────────────────────────────────┼────────────────┐
                    ▼                                        ▼                ▼
           cursor.com / api2                    cbr-xml-daily.ru     ~/.cursor-limits/
           (usage / billing)                    (USD → RUB)          cache.json
                                                                             │
                                                                             ▼
                                                                  cursor-status-bar
                                                                  (только чтение кэша)
```

**Принцип безопасности:** токен сессии читается из локальной SQLite Cursor и **не сохраняется** приложением на диск. В кэш и расширение попадают только агрегаты usage. Подробнее — [docs/SECURITY.md](docs/SECURITY.md).

## Быстрый старт

### Требования

- Windows 10 / 11  
- Python **3.12+**  
- Установленный и **залогиненный** Cursor IDE на этой машине  

### Установка из исходников

```powershell
git clone https://github.com/EvgenyPS/cursor-limit.git
cd cursor-limit

python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python.exe -m src
```

После запуска иконка появляется в системном трее. ЛКМ / ПКМ — кабинет и меню.

### Сборка `.exe`

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-exe.ps1
.\dist\CursorLimits.exe
```

Автозапуск: ПКМ по иконке → **Автозапуск с Windows** (HKCU `\Software\Microsoft\Windows\CurrentVersion\Run`).

## Status bar в Cursor

Расширение копируется в `%USERPROFILE%\.cursor\extensions\` и читает  
`%USERPROFILE%\.cursor-limits\cache.json` — **без токена, без сети**.

| Способ | Команда / действие |
|--------|--------------------|
| Из UI | Кнопка **«Панель IDE»** в кабинете или пункт меню трея |
| CLI | `python -m src --install-statusbar` |
| Скрипт | `powershell -ExecutionPolicy Bypass -File .\scripts\install-status-bar.ps1` |

Затем в Cursor: `Ctrl+Shift+P` → **Developer: Reload Window**.

**Формат строки:**

```text
● 12% · $12.66 · 1 020 ₽ · 3д · сегодня 1.2K
```

| Элемент | Смысл |
|---------|--------|
| `●` | Цвет по % недели: green → yellow → red (≈ 0–50 / 50–85 / 85–100) |
| `%` / `$` / `₽` | Использование и траты текущего цикла |
| `Nд` | Дней до сброса |
| `сегодня` | Токены / активность за сегодня |
| hover | Дни недели: `№ · день · токены · $ · ₽` |

## Настройки

| Параметр | Где |
|----------|-----|
| Язык RU / EN | Флаг в шапке окна или меню трея |
| Интервал опроса 60–3600 с | Spinbox в шапке |
| Настройки | `%USERPROFILE%\.cursor-limits\settings.json` |
| Кэш usage | `%USERPROFILE%\.cursor-limits\cache.json` |

Опциональный fallback-токен (не рекомендуется): скопируйте `.env.example` → `.env`.  
Основной и рекомендуемый путь — сессия из Cursor IDE.

## CLI

```powershell
python -m src                      # трей (основной режим)
python -m src --once               # один снимок → кэш
python -m src --status-bar         # строка для панели
python -m src --print-cache        # содержимое кэша
python -m src --online-check       # проверка эндпоинтов
python -m src --install-statusbar  # установить расширение
python -m src --install-autostart  # автозапуск Windows
python -m src --uninstall-autostart
```

## Структура репозитория

```text
cursor-limits-app/
├── src/                  # auth, API, сервис, трей, i18n, иконка
├── cursor-status-bar/    # расширение нижней панели Cursor
├── scripts/              # build-exe.ps1, install-status-bar.ps1
├── docs/
│   ├── images/           # скриншоты для README
│   ├── SETUP.md          # установка и troubleshooting
│   └── SECURITY.md       # модель угроз и чеклист перед push
├── cursor-ico.svg        # иконка трея (исходник)
├── README.md             # эта страница (RU)
├── README.en.md          # English
└── LICENSE               # PolyForm Noncommercial 1.0.0
```

## Документация

| Документ | Содержание |
|----------|------------|
| [docs/SETUP.md](docs/SETUP.md) | Установка, пути, troubleshooting |
| [docs/SECURITY.md](docs/SECURITY.md) | Авторизация, кэш, что не коммитить |
| [AI-work.MD](AI-work.MD) | Журнал решений и изменений |
| [README.en.md](README.en.md) | English version |

## Ограничения и дисклеймер

- API Cursor неофициальные: могут сломаться или отдавать `403` по региону.  
  Рабочий источник `$` / `₽` — `usage-summary`; часть `api2` / dashboard POST в РФ часто недоступна.  
- При region-block календарь активности строится из **локального** `ai-tracking`.  
- Не публикуйте `.env`, `cache.json` и скриншоты с персональными данными аккаунта.  
- Используйте на свой риск; авторы не несут ответственности за блокировку аккаунта или изменения API.

## Лицензия

[PolyForm Noncommercial License 1.0.0](LICENSE) © 2026 [EvgenyPS](https://github.com/EvgenyPS)

Это **открытый исходный код для некоммерческого использования** (не OSI “Open Source” — коммерция ограничена).

| Разрешено | Не разрешено |
|-----------|--------------|
| Личное / учебное / некоммерческое использование | Продавать программу или продукты на её основе |
| Изучать, менять, форкать для некоммерческих целей | Платные SaaS, платные сборки, коммерческая перепродажа |
| Распространять с сохранением лицензии и указания автора | Убирать copyright / `Required Notice` |

**Обязательная атрибуция:** при распространении или производных работах нужно сохранять уведомление:

`Required Notice: Copyright (c) 2026 EvgenyPS — https://github.com/EvgenyPS/cursor-limit`

Полный текст: [LICENSE](LICENSE) · [polyformproject.org](https://polyformproject.org/licenses/noncommercial/1.0.0/)

---

<p align="center">
  <a href="./README.md"><strong>🇷🇺 Русский</strong></a>
  ·
  <a href="./README.en.md">🇬🇧 English</a>
</p>
