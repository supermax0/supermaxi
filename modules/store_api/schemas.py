"""JSON helpers for the store catalog API."""

from __future__ import annotations

from typing import Any

from flask import jsonify


def api_error(message: str, status: int = 400, *, code: str | None = None) -> tuple:
    payload: dict[str, Any] = {"ok": False, "error": message}
    if code:
        payload["code"] = code
    response, status_code = jsonify(payload), status
    response.headers["Cache-Control"] = "no-store"
    return response, status_code


def api_ok(data: dict[str, Any] | None = None, status: int = 200) -> tuple:
    payload: dict[str, Any] = {"ok": True}
    if data:
        payload.update(data)
    response, status_code = jsonify(payload), status
    response.headers["Cache-Control"] = "no-store"
    return response, status_code
