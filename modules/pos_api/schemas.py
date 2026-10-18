"""JSON helpers for the POS machine API."""
from __future__ import annotations

from typing import Any

from flask import jsonify

from services.pos_checkout import PosCheckoutError


def api_error(message: str, status: int = 400, *, code: str | None = None, extra: dict | None = None) -> tuple:
    payload: dict[str, Any] = {"ok": False, "error": message}
    if code:
        payload["code"] = code
    if extra:
        payload.update(extra)
    return jsonify(payload), status


def api_ok(data: dict[str, Any] | None = None, status: int = 200) -> tuple:
    payload: dict[str, Any] = {"ok": True}
    if data:
        payload.update(data)
    return jsonify(payload), status


def checkout_error_response(exc: PosCheckoutError) -> tuple:
    extra = {k: v for k, v in (exc.payload or {}).items() if k not in {"success", "error", "code"}}
    return api_error(exc.message, exc.status_code, code=exc.code, extra=extra or None)


def require_json_fields(body: dict | None, *fields: str) -> str | None:
    if not isinstance(body, dict):
        return "JSON body required"
    for field in fields:
        value = body.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            return f"Missing field: {field}"
    return None
