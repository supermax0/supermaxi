"""Structured customer memory (spec §15, §80).

- Only whitelisted keys with validated values are stored.
- Each fact carries value, confidence, source and timestamps.
- Conflicts are never silently overwritten: newer evidence of at least similar confidence supersedes the old fact
  (kept as history with ``superseded_at``); weaker evidence is stored as ``conflict`` and the active fact stays;
  evidence observed before the current fact is stored as history only.
- Every row keeps value, normalized value, confidence, certainty (tentative | stated | verified), source, source
  message, observed / created / superseded timestamps and status. Operators correct, verify or retract facts.
- Facts below DISPLAY_CONFIDENCE are never shown or acted upon as known.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from .models import FcMemoryFact

DISPLAY_CONFIDENCE = 0.6
SUPERSEDE_MARGIN = 0.1  # new evidence may be slightly less confident than the old and still win (it is newer)

BUSINESS_TYPES = {
    "clinic", "beauty_center", "food_wholesale_retail", "wholesale", "commerce", "restaurant", "pharmacy", "general",
    "hr_management", "starter_business",
}
SPECIALTIES = {"dentistry", "dermatology", "gynecology", "pediatrics", "cardiology", "internal_medicine", "general"}


def _int_range(lo: int, hi: int) -> Callable[[Any], Any]:
    def check(v: Any) -> Any:
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError(f"expected integer {lo}..{hi}")
        return v

    return check


def _text(max_len: int) -> Callable[[Any], Any]:
    def check(v: Any) -> Any:
        if not isinstance(v, str) or not v.strip() or len(v) > max_len:
            raise ValueError("expected short text")
        return v.strip()

    return check


def _enum(values: set[str]) -> Callable[[Any], Any]:
    def check(v: Any) -> Any:
        if v not in values:
            raise ValueError(f"unknown value {v!r}")
        return v

    return check


def _str_list(max_items: int, max_len: int) -> Callable[[Any], Any]:
    def check(v: Any) -> Any:
        if not isinstance(v, list) or len(v) > max_items or not all(isinstance(x, str) and 0 < len(x) <= max_len for x in v):
            raise ValueError("expected list of short strings")
        return [x.strip() for x in v]

    return check


def _phone(v: Any) -> Any:
    if not isinstance(v, str) or not re.fullmatch(r"\+\d{8,15}", v):
        raise ValueError("expected E.164 phone")
    return v


def _email(v: Any) -> Any:
    if not isinstance(v, str) or not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,180}\.[A-Za-z]{2,24}", v):
        raise ValueError("expected email")
    return v.lower()


# key → (memory type, validator)
FACT_SCHEMA: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "businessType": ("organization", _enum(BUSINESS_TYPES)),
    "businessProfile": ("organization", _enum({"flowers"})),
    "specialty": ("organization", _enum(SPECIALTIES)),
    "businessName": ("organization", _text(150)),
    "doctors": ("organization", _int_range(1, 500)),
    "employees": ("organization", _int_range(0, 5000)),
    "branches": ("organization", _int_range(1, 200)),
    "country": ("organization", _text(60)),
    "city": ("organization", _text(60)),
    "contactName": ("profile", _text(120)),
    "phone": ("profile", _phone),
    "email": ("profile", _email),
    "language": ("profile", _enum({"ar-iq", "ar", "en", "ku"})),
    "interests": ("sales_state", _str_list(12, 60)),
    "pendingQuestions": ("unresolved", _str_list(10, 200)),
    "commitments": ("commitments", _str_list(10, 200)),
    "recommendedPlan": ("configuration", _text(50)),
    "summary": ("summary", _text(1200)),
}


CERTAINTY_RANK = {"tentative": 0, "stated": 1, "verified": 2}
TRUSTED_SOURCES = {"human", "tool", "channel"}  # operator-confirmed or produced by FINORA itself


@dataclass
class FactResult:
    key: str
    outcome: str  # created | confirmed | superseded | conflict | historical | rejected
    detail: str = ""
    fact_id: int | None = None


def validate(key: str, value: Any) -> Any:
    if key not in FACT_SCHEMA:
        raise ValueError(f"unknown fact key {key!r}")
    return FACT_SCHEMA[key][1](value)


def normalized(key: str, clean: Any) -> str:
    """Canonical comparison form: same meaning -> same string (case, Arabic letter variants, digits)."""
    from .extract import normalize

    def norm(v: Any) -> Any:
        if isinstance(v, str):
            return normalize(v)
        if isinstance(v, list):
            return [norm(x) for x in v]
        return v

    return json.dumps(norm(clean), ensure_ascii=False, sort_keys=True)


def _certainty(source: str, confidence: float) -> str:
    if source in TRUSTED_SOURCES:
        return "verified"
    if source == "ai_inference" or confidence < DISPLAY_CONFIDENCE:
        return "tentative"
    return "stated"


def _norm_of(row: FcMemoryFact) -> str:
    return row.value_normalized or normalized(row.key, row.value)


def remember(s: Session, customer_id: int, key: str, value: Any, *, confidence: float, source: str,
             source_ref: str | None = None, source_message_id: str | None = None,
             observed_at: datetime | None = None, actor: str | None = None, reason: str | None = None) -> FactResult:
    """Append evidence for one fact. Never overwrites: every value ever observed stays as a row."""
    try:
        clean = validate(key, value)
    except ValueError as exc:
        return FactResult(key, "rejected", str(exc))
    confidence = max(0.0, min(1.0, float(confidence)))
    now = datetime.utcnow()
    observed_at = observed_at or now
    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True)
    norm = normalized(key, clean)
    certainty = _certainty(source, confidence)
    current = s.query(FcMemoryFact).filter_by(customer_id=customer_id, key=key, status="active").first()
    if current is not None and _norm_of(current) == norm:
        current.confidence = max(current.confidence, confidence)
        if CERTAINTY_RANK[certainty] > CERTAINTY_RANK.get(current.certainty or "stated", 1):
            current.certainty = certainty
            current.changed_by = actor or current.changed_by
        current.source_ref = source_ref or current.source_ref
        return FactResult(key, "confirmed", fact_id=current.id)
    row = FcMemoryFact(customer_id=customer_id, key=key, value_json=encoded, value_normalized=norm,
                       confidence=confidence, certainty=certainty, source=source, source_ref=source_ref,
                       source_message_id=source_message_id, observed_at=observed_at, status="active",
                       changed_by=actor, status_reason=reason[:200] if reason else None)
    if current is None:
        s.add(row)
        s.flush()
        return FactResult(key, "created", fact_id=row.id)
    if current.observed_at and observed_at < current.observed_at and source != "human":
        # Evidence older than the current fact (late delivery / backfill): history, never the current value.
        row.status, row.superseded_by, row.superseded_at = "superseded", current.id, now
        row.status_reason = "observed before the current fact"
        s.add(row)
        s.flush()
        return FactResult(key, "historical", f"current stays {current.value_json}", fact_id=row.id)
    human_wins = current.source == "human" and source != "human"
    if not human_wins and confidence >= current.confidence - SUPERSEDE_MARGIN:
        s.add(row)
        s.flush()
        current.status, current.superseded_by, current.superseded_at = "superseded", row.id, now
        return FactResult(key, "superseded", f"was {current.value_json}", fact_id=row.id)
    row.status = "conflict"
    row.status_reason = "contradicts a human-confirmed fact" if human_wins else "weaker than the current fact"
    s.add(row)
    s.flush()
    return FactResult(key, "conflict", f"kept {current.value_json}", fact_id=row.id)


def correct(s: Session, customer_id: int, key: str, value: Any, *, actor: str, reason: str) -> FactResult:
    """Manual correction by an operator: a verified human fact that becomes current (old value kept as history)."""
    if not (reason or "").strip():
        return FactResult(key, "rejected", "a correction needs a reason")
    return remember(s, customer_id, key, value, confidence=1.0, source="human", source_ref=f"operator:{actor}"[:80],
                    actor=actor, reason=reason)


def verify(s: Session, customer_id: int, fact_id: int, *, actor: str) -> FcMemoryFact:
    row = s.get(FcMemoryFact, fact_id)
    if row is None or row.customer_id != customer_id or row.status != "active":
        raise LookupError("fact not found")
    row.certainty, row.changed_by = "verified", actor
    row.confidence = max(row.confidence, DISPLAY_CONFIDENCE)
    return row


def retract(s: Session, customer_id: int, fact_id: int, *, actor: str, reason: str) -> FcMemoryFact:
    """An operator marks a fact as wrong. It stays as evidence; the key becomes unknown (no silent fallback)."""
    row = s.get(FcMemoryFact, fact_id)
    if row is None or row.customer_id != customer_id or row.status not in {"active", "conflict"}:
        raise LookupError("fact not found")
    if not (reason or "").strip():
        raise ValueError("a retraction needs a reason")
    row.status, row.superseded_at, row.changed_by = "retracted", datetime.utcnow(), actor
    row.status_reason = reason[:200]
    return row


def history(s: Session, customer_id: int, key: str | None = None) -> list[dict[str, Any]]:
    q = s.query(FcMemoryFact).filter_by(customer_id=customer_id)
    if key:
        q = q.filter_by(key=key)
    return [fact_dto(r) for r in q.order_by(FcMemoryFact.key, FcMemoryFact.id).all()]


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() + "Z" if v else None


def fact_dto(r: FcMemoryFact) -> dict[str, Any]:
    return {
        "id": r.id, "key": r.key, "value": r.value, "normalized": json.loads(_norm_of(r)),
        "confidence": round(r.confidence, 2), "certainty": r.certainty or "stated", "source": r.source,
        "sourceMessageId": r.source_message_id, "status": r.status, "statusReason": r.status_reason,
        "changedBy": r.changed_by, "supersededBy": r.superseded_by, "observedAt": _iso(r.observed_at),
        "createdAt": _iso(r.created_at), "supersededAt": _iso(r.superseded_at),
    }


def active_facts(s: Session, customer_id: int, *, min_confidence: float = DISPLAY_CONFIDENCE) -> dict[str, dict[str, Any]]:
    rows = s.query(FcMemoryFact).filter_by(customer_id=customer_id, status="active").all()
    return {
        r.key: {"value": r.value, "confidence": round(r.confidence, 2), "source": r.source,
                "certainty": r.certainty or "stated"}
        for r in rows
        if r.confidence >= min_confidence
    }


def qualification_missing(facts: dict[str, Any]) -> list[str]:
    """Qualified = we know what the business is and how big it is (location is nice-to-have, not a gate)."""
    return [k for k in missing_profile(facts) if k != "city"]


def missing_profile(facts: dict[str, Any]) -> list[str]:
    """What the sales flow still needs, in the order it should be asked (one question at a time)."""
    order = ["businessType", "specialty", "doctors", "employees", "branches", "city"]
    needed = []
    for key in order:
        if key == "specialty" and (facts.get("businessType") or {}).get("value") != "clinic":
            continue
        if key == "doctors" and (facts.get("businessType") or {}).get("value") != "clinic":
            continue
        if key not in facts:
            needed.append(key)
    return needed
