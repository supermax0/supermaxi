"""Automatic HTTP activity logging middleware."""
from __future__ import annotations

from flask import request, session

from utils.activity_logger import (
    capture_request_body,
    infer_category_from_path,
    log_activity,
    method_to_action,
)

_SKIP_PREFIXES = (
    "/static/",
    "/favicon",
    "/activity/api/",
    "/workspace/sessions/",
    "/messages/api/unread",
    "/messages/api/typing",
    "/messages/api/poll",
    "/api/index/alerts",
    "/health",
)

_SKIP_EXACT = {
    "/activity",
    "/activity/",
}

_SKIP_EXTENSIONS = (".js", ".css", ".map", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2")


def should_skip_request(path: str, method: str) -> bool:
    if not path:
        return True
    if path in _SKIP_EXACT:
        return True
    if path.startswith("/activity") and path != "/activity":
        return True
    for prefix in _SKIP_PREFIXES:
        if path.startswith(prefix):
            return True
    if any(path.endswith(ext) for ext in _SKIP_EXTENSIONS):
        return True
    if "stream" in path and method == "GET":
        return True
    return False


def register_activity_middleware(app):
    @app.after_request
    def _log_http_activity(response):
        try:
            if "user_id" not in session:
                return response
            path = request.path or ""
            method = request.method or "GET"
            if should_skip_request(path, method):
                return response
            if response.status_code >= 400 and method == "GET":
                return response

            category = infer_category_from_path(path)
            action = method_to_action(method)
            summary = f"{action} {path}"
            if method != "GET":
                body = capture_request_body()
            else:
                body = {}

            payload = {"query": dict(request.args), "body": body}
            log_activity(
                action,
                category,
                summary,
                payload=payload,
                status_code=response.status_code,
                commit=True,
            )
        except Exception:
            pass
        return response
