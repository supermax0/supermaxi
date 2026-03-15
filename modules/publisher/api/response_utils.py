"""
response_utils.py
-----------------
Unified API response envelope helpers with backward-compatibility keys.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from flask import jsonify


def ok_response(
    *,
    data: Any = None,
    message: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    legacy: Optional[Dict[str, Any]] = None,
    status_code: int = 200,
):
    payload: Dict[str, Any] = {"success": True}
    if data is not None:
        payload["data"] = data
    if message:
        payload["message"] = message
    if meta is not None:
        payload["meta"] = meta
    if legacy:
        payload.update(legacy)
    return jsonify(payload), status_code


def error_response(
    *,
    code: str,
    message: str,
    status_code: int = 400,
    fields: Optional[Dict[str, str]] = None,
    details: Any = None,
    legacy: Optional[Dict[str, Any]] = None,
):
    payload: Dict[str, Any] = {
        "success": False,
        "message": message,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if fields:
        payload["error"]["fields"] = fields
    if details is not None:
        payload["error"]["details"] = details
    if legacy:
        payload.update(legacy)
    return jsonify(payload), status_code
