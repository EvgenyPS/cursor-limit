# FILE: src/online_check.py
# PURPOSE: Явная проверка онлайн-эндпоинтов Cursor (что доступно с этой сети).
# WHY: Часть API (usage-summary) работает, часть (api2/dashboard) может резать region.
#      Пользователю нужна честная картина «онлайн жив / что именно отвалилось».

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import requests

from .auth import CursorCredentials, load_credentials
from .config import AppConfig, load_config

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class EndpointResult:
    name: str
    ok: bool
    status: int | None = None
    detail: str = ""


@dataclass(slots=True)
class OnlineCheckReport:
    ok_count: int = 0
    fail_count: int = 0
    results: list[EndpointResult] = field(default_factory=list)
    # Кратко для UI / трея
    summary_line: str = ""
    # usage-summary доступен → основные $/% можно показывать онлайн
    usage_online: bool = False
    # детальные токены/календарь с сервера
    details_online: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok_count": self.ok_count,
            "fail_count": self.fail_count,
            "usage_online": self.usage_online,
            "details_online": self.details_online,
            "summary_line": self.summary_line,
            "results": [asdict(r) for r in self.results],
        }


def _probe(
    session: requests.Session,
    name: str,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 15.0,
) -> EndpointResult:
    try:
        if method == "GET":
            resp = session.get(url, headers=headers or {}, timeout=timeout)
        else:
            resp = session.post(
                url, headers=headers or {}, json=json_body if json_body is not None else {}, timeout=timeout
            )
    except requests.RequestException as exc:
        return EndpointResult(name=name, ok=False, detail=str(exc)[:160])

    text = (resp.text or "")[:160].replace("\n", " ")
    ok = 200 <= resp.status_code < 300
    # region / auth — отдельно помечаем
    detail = text
    low = text.lower()
    if resp.status_code in (401, 403):
        if "region" in low:
            detail = "region blocked"
        elif "not_authenticated" in low or "unauthenticated" in low:
            detail = "not authenticated"
        else:
            detail = f"HTTP {resp.status_code}: {text[:100]}"
    elif not ok:
        detail = f"HTTP {resp.status_code}: {text[:100]}"
    else:
        detail = "OK"
    return EndpointResult(name=name, ok=ok, status=resp.status_code, detail=detail)


def run_online_check(
    creds: CursorCredentials | None = None,
    cfg: AppConfig | None = None,
) -> OnlineCheckReport:
    """Гоняет набор эндпоинтов и собирает отчёт."""
    cfg = cfg or load_config()
    creds = creds or load_credentials()
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": BROWSER_UA,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    cookie = creds.cookie_header()
    bearer = {"Authorization": f"Bearer {creds.access_token}", "Connect-Protocol-Version": "1"}

    checks: list[EndpointResult] = []
    checks.append(
        _probe(
            session,
            "usage-summary",
            "GET",
            "https://cursor.com/api/usage-summary",
            headers={"Cookie": cookie},
            timeout=cfg.http_timeout_sec,
        )
    )
    checks.append(
        _probe(
            session,
            "auth/me",
            "GET",
            "https://cursor.com/api/auth/me",
            headers={"Cookie": cookie},
            timeout=cfg.http_timeout_sec,
        )
    )
    checks.append(
        _probe(
            session,
            "auth/stripe",
            "GET",
            "https://cursor.com/api/auth/stripe",
            headers={"Cookie": cookie},
            timeout=cfg.http_timeout_sec,
        )
    )
    checks.append(
        _probe(
            session,
            "api2/GetCurrentPeriodUsage",
            "POST",
            "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage",
            headers={**bearer, "Content-Type": "application/json", "Origin": "https://cursor.com"},
            json_body={},
            timeout=cfg.http_timeout_sec,
        )
    )
    checks.append(
        _probe(
            session,
            "api2/GetAggregatedUsageEvents",
            "POST",
            "https://api2.cursor.sh/aiserver.v1.DashboardService/GetAggregatedUsageEvents",
            headers={**bearer, "Content-Type": "application/json", "Origin": "https://cursor.com"},
            json_body={"teamId": 0, "userId": 0},
            timeout=cfg.http_timeout_sec,
        )
    )
    checks.append(
        _probe(
            session,
            "dashboard/get-aggregated-usage-events",
            "POST",
            "https://cursor.com/api/dashboard/get-aggregated-usage-events",
            headers={
                "Cookie": cookie,
                "Origin": "https://cursor.com",
                "Referer": "https://cursor.com/dashboard/usage",
                "Content-Type": "application/json",
            },
            json_body={"teamId": 0, "userId": 0},
            timeout=cfg.http_timeout_sec,
        )
    )
    session.close()

    report = OnlineCheckReport(results=checks)
    report.ok_count = sum(1 for r in checks if r.ok)
    report.fail_count = len(checks) - report.ok_count
    by_name = {r.name: r for r in checks}
    report.usage_online = bool(by_name.get("usage-summary") and by_name["usage-summary"].ok)
    report.details_online = bool(
        (by_name.get("api2/GetAggregatedUsageEvents") and by_name["api2/GetAggregatedUsageEvents"].ok)
        or (
            by_name.get("dashboard/get-aggregated-usage-events")
            and by_name["dashboard/get-aggregated-usage-events"].ok
        )
    )

    marks = []
    for r in checks:
        marks.append(f"{'✓' if r.ok else '✗'} {r.name}")
    report.summary_line = (
        f"Online {report.ok_count}/{len(checks)} · "
        + ("limits OK" if report.usage_online else "limits FAIL")
        + " · "
        + ("tokens/days OK" if report.details_online else "tokens/days N/A")
    )
    # полный список — в details окна
    report.summary_line = report.summary_line[:120]
    return report


def format_report_text(report: OnlineCheckReport) -> str:
    lines = [report.summary_line, ""]
    for r in report.results:
        st = r.status if r.status is not None else "—"
        lines.append(f"{'✓' if r.ok else '✗'} {r.name}: {st} · {r.detail}")
    if report.usage_online and not report.details_online:
        lines.append("")
        lines.append(
            "Лимиты ($/%) читаются онлайн. Детальный календарь токенов "
            "сервер режет (часто region) — тогда дни из локального трекинга."
        )
    return "\n".join(lines)
