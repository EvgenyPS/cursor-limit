# FILE: src/cursor_api.py
# PURPOSE: Клиент неофициальных API Cursor (dashboard + api2 RPC).
# WHY: Те же эндпоинты, что рисует веб-дашборд / IDE. Могут поменяться — парсим мягко.
#
# JUNIOR NOTE:
# - api2.cursor.sh → Authorization: Bearer <accessToken>
# - cursor.com/api/* → Cookie WorkosCursorSessionToken + Origin для POST

from __future__ import annotations

from typing import Any

import requests

from .auth import CursorCredentials
from .config import AppConfig

API2 = "https://api2.cursor.sh"
WEB = "https://cursor.com"

# Браузерный UA — часть edge/WAF дружелюбнее к нему, чем к кастомному боту
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class CursorApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        status: int | None = None,
        *,
        region_blocked: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.region_blocked = region_blocked


def _looks_region_blocked(status: int, body: str) -> bool:
    if status != 403:
        return False
    low = body.lower()
    return "not available in your region" in low or "region" in low


class CursorApiClient:
    """Тонкая обёртка над HTTPS. Ничего не кэширует — кэш в service-слое."""

    def __init__(self, creds: CursorCredentials, cfg: AppConfig) -> None:
        self._creds = creds
        self._cfg = cfg
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": UA,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def close(self) -> None:
        self._session.close()

    # --- api2 (Bearer) -----------------------------------------------------

    def _rpc(self, method: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{API2}/aiserver.v1.DashboardService/{method}"
        headers = {
            "Authorization": f"Bearer {self._creds.access_token}",
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
        }
        resp = self._session.post(
            url,
            headers=headers,
            json=body or {},
            timeout=self._cfg.http_timeout_sec,
        )
        if resp.status_code == 401:
            raise CursorApiError(
                "Сессия Cursor истекла — перелогинься в IDE",
                status=resp.status_code,
            )
        if _looks_region_blocked(resp.status_code, resp.text):
            raise CursorApiError(
                "api2 недоступен в регионе — используем web usage-summary",
                status=resp.status_code,
                region_blocked=True,
            )
        if resp.status_code < 200 or resp.status_code >= 300:
            raise CursorApiError(
                f"{method}: HTTP {resp.status_code}: {resp.text[:200]}",
                status=resp.status_code,
            )
        if not resp.content:
            return {}
        data = resp.json()
        if not isinstance(data, dict):
            return {"_raw": data}
        return data

    def get_current_period_usage(self) -> dict[str, Any]:
        return self._rpc("GetCurrentPeriodUsage", {})

    def get_plan_info(self) -> dict[str, Any]:
        return self._rpc("GetPlanInfo", {})

    def get_aggregated_usage_events(
        self,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"teamId": 0, "userId": 0}
        if start_ms is not None:
            body["startDate"] = int(start_ms)
        if end_ms is not None:
            body["endDate"] = int(end_ms)
        return self._rpc("GetAggregatedUsageEvents", body)

    # --- cursor.com (Cookie) -----------------------------------------------

    def _web_headers(self, post: bool = False) -> dict[str, str]:
        headers = {"Cookie": self._creds.cookie_header()}
        if post:
            # CSRF: без Origin POST на cursor.com отваливается
            headers["Origin"] = "https://cursor.com"
            headers["Referer"] = "https://cursor.com/dashboard"
            headers["Content-Type"] = "application/json"
        return headers

    def get_usage_summary(self) -> dict[str, Any]:
        resp = self._session.get(
            f"{WEB}/api/usage-summary",
            headers=self._web_headers(False),
            timeout=self._cfg.http_timeout_sec,
        )
        if resp.status_code == 401:
            raise CursorApiError(
                "Cookie/сессия отклонена (401) — перелогинься в Cursor",
                status=resp.status_code,
            )
        if _looks_region_blocked(resp.status_code, resp.text):
            raise CursorApiError(
                "usage-summary недоступен в регионе",
                status=resp.status_code,
                region_blocked=True,
            )
        if resp.status_code < 200 or resp.status_code >= 300:
            raise CursorApiError(
                f"usage-summary: HTTP {resp.status_code}",
                status=resp.status_code,
            )
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def web_get_aggregated_usage_events(
        self,
        start_ms: int,
        end_ms: int,
    ) -> dict[str, Any]:
        """Агрегаты токенов через cursor.com (если api2 режет по региону)."""
        resp = self._session.post(
            f"{WEB}/api/dashboard/get-aggregated-usage-events",
            headers=self._web_headers(True),
            json={
                "teamId": 0,
                "userId": 0,
                "startDate": int(start_ms),
                "endDate": int(end_ms),
            },
            timeout=self._cfg.http_timeout_sec,
        )
        if resp.status_code >= 400:
            return {}
        try:
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    def get_stripe(self) -> dict[str, Any]:
        resp = self._session.get(
            f"{WEB}/api/auth/stripe",
            headers=self._web_headers(False),
            timeout=self._cfg.http_timeout_sec,
        )
        if resp.status_code >= 400:
            return {}
        try:
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    def web_get_current_period_usage(self) -> dict[str, Any]:
        """REST-форма периода (полезна для weekly Premium)."""
        resp = self._session.post(
            f"{WEB}/api/dashboard/get-current-period-usage",
            headers=self._web_headers(True),
            json={},
            timeout=self._cfg.http_timeout_sec,
        )
        if resp.status_code >= 400:
            return {}
        try:
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    def web_get_plan_info(self) -> dict[str, Any]:
        resp = self._session.post(
            f"{WEB}/api/dashboard/get-plan-info",
            headers=self._web_headers(True),
            json={},
            timeout=self._cfg.http_timeout_sec,
        )
        if resp.status_code >= 400:
            return {}
        try:
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}
