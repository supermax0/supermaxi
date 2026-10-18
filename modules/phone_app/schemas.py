"""JSON helpers for phone API."""

from __future__ import annotations

from typing import Any

from flask import jsonify


def api_error(message: str, status: int = 400, *, code: str | None = None) -> tuple:
    payload: dict[str, Any] = {"ok": False, "error": message}
    if code:
        payload["code"] = code
    return jsonify(payload), status


def api_ok(data: dict[str, Any] | None = None, status: int = 200) -> tuple:
    payload: dict[str, Any] = {"ok": True}
    if data:
        payload.update(data)
    return jsonify(payload), status


def require_json_fields(body: dict | None, *fields: str) -> str | None:
    if not isinstance(body, dict):
        return "JSON body required"
    for field in fields:
        value = body.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            return f"Missing field: {field}"
    return None
