"""Page strength score. Weights live here so settings can override them later."""
from __future__ import annotations

STRENGTH_WEIGHTS = {
    "orders": 0.35,
    "conversion": 0.25,
    "sales": 0.20,
    "response": 0.10,
    "quality": 0.10,
}

SLA_RESPONSE_SECONDS = 180


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def response_score(avg_response_seconds: float | None) -> float:
    if avg_response_seconds is None:
        return 50.0
    return _clamp(100.0 - (float(avg_response_seconds) / SLA_RESPONSE_SECONDS) * 100.0)


def quality_score(orders: int, returns: int) -> float:
    if orders <= 0:
        return 100.0 if returns <= 0 else 0.0
    return _clamp(100.0 - (returns / orders) * 100.0)


def relative_score(value: float, maximum: float) -> float:
    if maximum <= 0:
        return 0.0
    return _clamp((value / maximum) * 100.0)


def conversion_score(rate_percent: float) -> float:
    """20% conversion is a full score. Higher rates stay at 100."""
    if rate_percent <= 0:
        return 0.0
    return _clamp((rate_percent / 20.0) * 100.0)


def page_strength_score(
    *,
    orders: int,
    max_orders: int,
    conversion_rate: float,
    sales: float,
    max_sales: float,
    avg_response_seconds: float | None,
    returns: int,
    weights: dict | None = None,
) -> int:
    used = dict(STRENGTH_WEIGHTS)
    if weights:
        used.update({key: float(value) for key, value in weights.items() if key in used})
    if orders <= 0 and sales <= 0 and conversion_rate <= 0 and avg_response_seconds is None and returns <= 0:
        return 0
    total_weight = sum(used.values()) or 1.0
    raw = (
        relative_score(orders, max_orders) * used["orders"]
        + conversion_score(conversion_rate) * used["conversion"]
        + relative_score(sales, max_sales) * used["sales"]
        + response_score(avg_response_seconds) * used["response"]
        + quality_score(orders, returns) * used["quality"]
    )
    return int(round(_clamp(raw / total_weight)))


def score_tone(score: int) -> str:
    if score >= 90:
        return "success"
    if score >= 75:
        return "good"
    if score >= 60:
        return "warning"
    return "danger"
