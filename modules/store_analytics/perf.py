"""Server response times of storefront endpoints, kept in memory (per process and company, last 500 per endpoint).

Cheap enough to stay on in production: one perf_counter pair and a deque append per request. Every storefront
response also carries a ``Server-Timing: app;dur=…`` header so slow pages can be seen from the browser."""
from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque

_SAMPLES: dict[tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=500))
_LOCK = threading.Lock()
_STARTED = time.time()


def start() -> float:
    return time.perf_counter()


def stop(tenant: str, endpoint: str, started: float) -> float:
    ms = (time.perf_counter() - started) * 1000
    with _LOCK:
        _SAMPLES[(tenant or "", endpoint or "?")].append(ms)
    return ms


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1))]


def snapshot(tenant: str) -> dict:
    with _LOCK:
        data = {endpoint: list(v) for (t, endpoint), v in _SAMPLES.items() if t == (tenant or "")}
    rows = [{"endpoint": k, "count": len(v), "p50_ms": round(percentile(v, 50), 1), "p95_ms": round(percentile(v, 95), 1),
             "max_ms": round(max(v), 1)} for k, v in data.items() if v]
    rows.sort(key=lambda r: -r["p95_ms"])
    return {"since": _STARTED, "rows": rows}


def reset() -> None:
    with _LOCK:
        _SAMPLES.clear()
