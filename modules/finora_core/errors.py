"""Classified API errors (spec §35). ``message`` is user-safe Arabic; details go to logs only."""
from __future__ import annotations

from flask import jsonify


class CoreApiError(Exception):
    def __init__(self, code: str, message: str, status: int, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable

    def response(self):
        body = {"error": {"code": self.code, "message": self.message, "retryable": self.retryable}}
        return jsonify(body), self.status


def auth_error(message: str = "انتهت الجلسة، سجّل الدخول مجدداً") -> CoreApiError:
    return CoreApiError("AUTH_ERROR", message, 401)


def permission_error() -> CoreApiError:
    return CoreApiError("PERMISSION_ERROR", "لا تملك صلاحية لهذا الإجراء", 403)


def validation_error(message: str) -> CoreApiError:
    return CoreApiError("VALIDATION_ERROR", message, 400)


def not_found(message: str = "العنصر غير موجود") -> CoreApiError:
    return CoreApiError("NOT_FOUND", message, 404)


def conflict(message: str) -> CoreApiError:
    return CoreApiError("CONFLICT", message, 409)


def house_not_configured() -> CoreApiError:
    return CoreApiError("HOUSE_NOT_CONFIGURED", "قنوات FINORA غير مهيأة على الخادم", 503)
