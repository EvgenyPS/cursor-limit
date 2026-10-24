# FILE: src/auth.py
# PURPOSE: Безопасное получение credentials Cursor ТОЛЬКО с этой машины.
# WHY: Для личного использования самый безопасный вариант — не копировать cookie
#      из браузера и не хранить секрет в .env, а читать accessToken из локальной
#      SQLite Cursor (state.vscdb), куда IDE уже положила OAuth после логина.
#
# SECURITY:
# - Токен не логируем и не пишем на диск этим приложением.
# - Fallback: CURSOR_SESSION_TOKEN / CURSOR_ACCESS_TOKEN в .env (опционально).
# - Cookie собираем в памяти: WorkosCursorSessionToken=userId%3A%3AaccessToken

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .platform_paths import cursor_state_db_path, cursor_user_data_dir


@dataclass(slots=True)
class CursorCredentials:
    """Учётные данные для запросов к Cursor (живут только в RAM процесса)."""

    user_id: str
    access_token: str
    source: str  # откуда взяли — для отладки UI, не секрет

    def session_cookie_value(self) -> str:
        """Значение cookie WorkosCursorSessionToken (url-encoded ::)."""
        # Важно: кодируем только разделитель :: → %3A%3A.
        # JWT трогать quote() нельзя — иначе api/web могут не принять cookie.
        return f"{self.user_id}%3A%3A{self.access_token}"

    def cookie_header(self) -> str:
        return f"WorkosCursorSessionToken={self.session_cookie_value()}"


def state_db_path() -> Path:
    """Путь к state.vscdb Cursor (Windows / macOS / Linux)."""
    return cursor_state_db_path()


def _read_access_token_from_db(db_path: Path) -> str | None:
    """Читает cursorAuth/accessToken из ItemTable. Только SELECT, без записи."""
    if not db_path.is_file():
        return None
    # URI read-only — меньше шансов словить lock от работающего Cursor
    uri = db_path.resolve().as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.Error:
        # Fallback: обычное открытие (иногда URI mode недоступен)
        try:
            conn = sqlite3.connect(str(db_path), timeout=5.0)
        except sqlite3.Error:
            return None
    try:
        cur = conn.execute(
            "SELECT value FROM ItemTable WHERE key = ? LIMIT 1",
            ("cursorAuth/accessToken",),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            return None
        token = str(row[0]).strip()
        return token or None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


_USER_ID_RE = re.compile(r"user_[a-zA-Z0-9]{16,}")


def _extract_user_id_from_text(text: str) -> str | None:
    m = _USER_ID_RE.search(text)
    return m.group(0) if m else None


def _extract_user_id_from_oauth(oauth_id: str) -> str | None:
    # Иногда лежит как "auth0|user_xxx" или просто user_xxx
    if "|" in oauth_id:
        for part in oauth_id.split("|"):
            if part.startswith("user_"):
                return part
    if oauth_id.startswith("user_"):
        return oauth_id
    return _extract_user_id_from_text(oauth_id)


def _find_user_id_in_obj(obj: object) -> str | None:
    if isinstance(obj, str):
        if obj.startswith("user_") and len(obj) > 20:
            return obj
        return _extract_user_id_from_oauth(obj)
    if isinstance(obj, dict):
        # Приоритетные ключи
        for key in ("id", "userId", "user_id", "did"):
            if key in obj and isinstance(obj[key], str):
                found = _extract_user_id_from_oauth(obj[key])
                if found:
                    return found
        for value in obj.values():
            found = _find_user_id_in_obj(value)
            if found:
                return found
    if isinstance(obj, list):
        for item in obj:
            found = _find_user_id_in_obj(item)
            if found:
                return found
    return None


def _candidate_user_id_files() -> list[Path]:
    base = cursor_user_data_dir()
    return [
        base / "sentry" / "scope_v3.json",
        base / "sentry" / "session.json",
        base / "User" / "globalStorage" / "storage.json",
        base / "storage.json",
    ]


def _read_user_id_from_files() -> str | None:
    for path in _candidate_user_id_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        try:
            data = json.loads(text)
            # Типичный путь Sentry: scope.user.id
            scope_user = (
                data.get("scope", {}).get("user", {}).get("id")
                if isinstance(data, dict)
                else None
            )
            if isinstance(scope_user, str):
                found = _extract_user_id_from_oauth(scope_user)
                if found:
                    return found
            found = _find_user_id_in_obj(data)
            if found:
                return found
        except json.JSONDecodeError:
            found = _extract_user_id_from_text(text)
            if found:
                return found
    return None


def _read_user_id_from_db(db_path: Path) -> str | None:
    """Ищем user_id в соседних ключах auth, если JSON-файлы пусты."""
    if not db_path.is_file():
        return None
    keys = (
        "cursorAuth/cachedEmail",
        "cursorAuth/cachedSignInMethod",
        "cursorAuth/userId",
        "cursorAuth/stripeMembershipType",
    )
    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
    except sqlite3.Error:
        return None
    try:
        for key in keys:
            cur = conn.execute(
                "SELECT value FROM ItemTable WHERE key = ? LIMIT 1", (key,)
            )
            row = cur.fetchone()
            if row and row[0]:
                found = _extract_user_id_from_text(str(row[0]))
                if found:
                    return found
        # Последний шанс — пройтись по ключам cursorAuth/*
        cur = conn.execute(
            "SELECT value FROM ItemTable WHERE key LIKE 'cursorAuth/%' LIMIT 50"
        )
        for (value,) in cur.fetchall():
            if value:
                found = _extract_user_id_from_text(str(value))
                if found:
                    return found
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return None


def _creds_from_env() -> CursorCredentials | None:
    """Fallback: полный cookie или пара user+token из .env (только для отладки)."""
    full = os.getenv("CURSOR_SESSION_TOKEN", "").strip()
    if full:
        # Можно передать уже готовое значение cookie (user%3A%3Atoken или user::token)
        decoded = full.replace("%3A%3A", "::").replace("%3a%3a", "::")
        if "::" in decoded:
            user_id, token = decoded.split("::", 1)
            if user_id.startswith("user_") and token:
                return CursorCredentials(user_id, token, source="env:CURSOR_SESSION_TOKEN")
        # Иногда кладут только JWT — без user_id cookie для cursor.com не собрать
    token = os.getenv("CURSOR_ACCESS_TOKEN", "").strip()
    user_id = os.getenv("CURSOR_USER_ID", "").strip()
    if token and user_id.startswith("user_"):
        return CursorCredentials(user_id, token, source="env:CURSOR_ACCESS_TOKEN")
    return None


def load_credentials() -> CursorCredentials:
    """Главная точка: локальная БД Cursor → иначе .env → иначе ошибка."""
    env_creds = _creds_from_env()
    # Предпочитаем локальную БД: она обновляется самим Cursor при логине
    db = state_db_path()
    token = _read_access_token_from_db(db)
    user_id = _read_user_id_from_files() or _read_user_id_from_db(db)

    if token and user_id:
        return CursorCredentials(user_id, token, source=f"local:{db.name}")

    if env_creds:
        return env_creds

    missing = []
    if not token:
        missing.append("accessToken (войди в Cursor IDE)")
    if not user_id:
        missing.append("user_id (файлы sentry/storage)")
    raise RuntimeError(
        "Не удалось получить credentials Cursor: " + ", ".join(missing)
    )
