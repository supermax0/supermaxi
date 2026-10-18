"""Agent observability (Phase 9 / Priority 8): operational traces, never hidden reasoning.

A trace records WHAT happened in a run — model, prompt version, knowledge version, intents and confidence, proposed
actions, policy verdicts, executed tools and their verification, approvals, result, latency, token usage and an
estimated cost. Free text that may carry personal data or secrets is redacted before it is stored.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from sqlalchemy.orm import Session

from ..store import get_setting

KNOWLEDGE_VERSION_KEY = "knowledge_version"

# USD per 1M tokens (input, output). Override / extend with FINORA_CORE_MODEL_PRICES='{"model": [in, out]}'.
# Unknown models get no estimate (``None``) rather than a guessed number.
DEFAULT_MODEL_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
}

_PATTERNS = [
    (re.compile(r"\+?\d[\d\s-]{7,}\d"), "[phone]"),
    (re.compile(r"[^@\s]{1,64}@[^@\s]{1,180}\.[A-Za-z]{2,24}"), "[email]"),
    (re.compile(r"\b(?:sk|pk|rk|EAA[A-Za-z0-9]*)[-_][A-Za-z0-9_-]{8,}|\bEAA[A-Za-z0-9]{20,}"), "[token]"),
    (re.compile(r"(?i)(password|passwd|كلمة\s*المرور|token|secret|api[_ -]?key)\s*[:=]\s*\S+"), r"\1=[redacted]"),
]
_SECRET_KEYS = re.compile(r"(?i)pass|secret|token|api_?key|credential")


def redact(value: Any) -> Any:
    """Recursively mask phones, emails, tokens and secret-named fields."""
    if isinstance(value, dict):
        return {k: ("[redacted]" if _SECRET_KEYS.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        out = value
        for pattern, repl in _PATTERNS:
            out = pattern.sub(repl, out)
        return out
    return value


def model_prices() -> dict[str, tuple[float, float]]:
    prices = dict(DEFAULT_MODEL_PRICES)
    raw = os.environ.get("FINORA_CORE_MODEL_PRICES")
    if raw:
        try:
            prices.update({k: (float(v[0]), float(v[1])) for k, v in json.loads(raw).items()})
        except (ValueError, TypeError, IndexError, AttributeError):
            pass
    return prices


def estimate_cost(model: str | None, input_tokens: int, output_tokens: int) -> float | None:
    if not input_tokens and not output_tokens:
        return 0.0  # rules planner / no model call
    if not model:
        return None
    prices = model_prices()
    price = prices.get(model) or next((p for name, p in prices.items() if model.startswith(name + "-")), None)
    if price is None:
        return None
    return round((input_tokens * price[0] + output_tokens * price[1]) / 1_000_000, 6)


def knowledge_version(s: Session) -> int:
    raw = get_setting(s, KNOWLEDGE_VERSION_KEY, "0") or "0"
    return int(raw) if raw.isdigit() else 0


def run_dto(run) -> dict[str, Any]:
    from ..store import iso

    return {
        "id": run.id, "conversationId": run.conversation_ref, "customerId": run.customer_id, "mode": run.mode,
        "status": run.status, "result": run.outcome, "model": run.model, "promptVersion": run.prompt_version,
        "knowledgeVersion": run.knowledge_version, "intents": json.loads(run.intents_json or "[]"),
        "confidence": run.confidence, "latencyMs": run.latency_ms,
        "tokens": {"input": run.input_tokens, "output": run.output_tokens}, "estimatedCostUsd": run.cost_usd,
        "trace": json.loads(run.trace_json or "{}"), "correlationId": run.correlation_id,
        "startedAt": iso(run.started_at), "finishedAt": iso(run.finished_at),
    }
