"""Shared route-walker for the permission-coverage tests.

Hits every GET/POST route of the surfaces the desktop client uses, as (a) an anonymous caller and (b) an active
employee that has NO role and NO override, and classifies the responses. A route that answers such a caller with
a success is a permission gap (or an intentionally open endpoint that must be listed in OPEN_FOR_ANY_EMPLOYEE).
"""
from __future__ import annotations

import re
from typing import Any

SURFACES = (
    "/api/v1/desktop", "/expenses", "/hr", "/inventory", "/orders", "/pos", "/api/finance", "/api/branch",
    "/api/delivery-fee", "/shipping", "/customers", "/suppliers", "/purchases", "/reports", "/cash", "/accounts",
)
SKIP = re.compile(r"(^/static)|(/logout)|(/login)|(^/pos/login)|(<path:)")
CONVERT = {"int": "1", "string": "x", "path": "x", "float": "1", "uuid": "00000000-0000-0000-0000-000000000000"}


def concrete(rule) -> str:
    url = rule.rule
    for arg, conv in rule._converters.items():  # noqa: SLF001
        name = type(conv).__name__.replace("Converter", "").lower()
        url = re.sub(rf"<[^>]*{re.escape(arg)}>", CONVERT.get(name, "1"), url)
    return url


def walk(app, make_client, surfaces=None) -> dict[str, tuple[int, str]]:
    """{ 'METHOD /rule': (status, location_or_empty) } for every surfaced route."""
    out: dict[str, tuple[int, str]] = {}
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if not rule.rule.startswith(surfaces or SURFACES) or SKIP.search(rule.rule):
            continue
        for method in sorted(rule.methods & {"GET", "POST"}):
            url = concrete(rule)
            client = make_client()  # a fresh session per call: one route may end the session (plan gate, logout…)
            try:
                if method == "GET":
                    res = client.get(url)
                else:
                    res = client.post(url, json={})
                out[f"{method} {rule.rule}"] = (res.status_code, res.headers.get("Location", ""))
            except Exception as exc:  # noqa: BLE001 — a crash is itself a finding
                out[f"{method} {rule.rule}"] = (599, type(exc).__name__)
    return out


def is_success(status: int) -> bool:
    return 200 <= status < 300


def is_denied(status: int, location: str) -> bool:
    if status in (401, 403):
        return True
    return status in (301, 302, 303, 307, 308) and any(k in location for k in ("login", "denied", "forbidden", "/"))


def summarize(results: dict[str, tuple[int, str]]) -> dict[str, Any]:
    return {
        "total": len(results),
        "success": sorted(k for k, (s, _) in results.items() if is_success(s)),
        "server_error": sorted(k for k, (s, _) in results.items() if s >= 500),
    }
