"""Shared backend rate policy for AI and MCP transports."""
import time
import threading
from collections import defaultdict, deque
from flask import jsonify

_windows = defaultdict(deque)
_lock = threading.Lock()


def rate_limit(context, maximum=30, seconds=60):
    now = time.monotonic()
    key = (context.tenant_slug, context.user_id)
    with _lock:
        window = _windows[key]
        while window and window[0] < now - seconds:
            window.popleft()
        if len(window) >= maximum:
            return jsonify({"success": False, "error": {"code": "RATE_LIMITED", "message": "Too many requests"}}), 429
        window.append(now)
    return None
