"""Customer resolution (spec §34): one customer across Instagram / Messenger / phone / email / FINORA tenant.

Rules:
- A channel identity (Instagram id / Facebook PSID) maps a conversation to exactly one customer (exact match).
- A phone / email mentioned in a conversation is attached to the current customer when it is new.
- If that phone / email already belongs to ANOTHER customer, nothing is merged: a merge suggestion is created for a
  human (spec: "Do not automatically merge uncertain identities").
- Merging is an explicit, audited human action: Merge / Keep separate / Dismiss. A merge writes a ledger of exactly
  which rows moved, so it can be reverted (``unmerge``). "Keep separate" is remembered: the same pair is never
  suggested again.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .models import (
    FcConversationCustomer,
    FcCustomer,
    FcCustomerMerge,
    FcCustomerIdentity,
    FcLeadTransition,
    FcMemoryFact,
    FcMergeSuggestion,
    FcOnboardingStep,
)

CHANNEL_KIND = {"instagram": "instagram_id", "messenger": "facebook_psid", "telegram": "telegram_user_id"}


def resolve_for_conversation(s: Session, *, conversation_ref: str, channel_type: str, contact_id: str,
                             display_name: str) -> FcCustomer:
    link = s.get(FcConversationCustomer, conversation_ref)
    if link is not None:
        customer = s.get(FcCustomer, link.customer_id)
        if customer is not None:
            return _follow_merge(s, customer)
    kind = CHANNEL_KIND.get(channel_type, f"{channel_type}_id")
    identity = s.query(FcCustomerIdentity).filter_by(kind=kind, value=contact_id).first()
    if identity is not None:
        customer = _follow_merge(s, s.get(FcCustomer, identity.customer_id))
    else:
        customer = FcCustomer(display_name=(display_name or "عميل")[:150], lead_stage="new")
        s.add(customer)
        s.flush()
        s.add(FcCustomerIdentity(customer_id=customer.id, kind=kind, value=contact_id, verified=True, source="channel"))
    s.add(FcConversationCustomer(conversation_ref=conversation_ref, customer_id=customer.id))
    s.flush()
    return customer


def _follow_merge(s: Session, customer: FcCustomer) -> FcCustomer:
    seen = set()
    while customer.merged_into_id and customer.id not in seen:
        seen.add(customer.id)
        customer = s.get(FcCustomer, customer.merged_into_id)
    return customer


def attach_contact(s: Session, customer: FcCustomer, *, kind: str, value: str, source: str) -> str:
    """Returns ``attached`` | ``already`` | ``suggested_merge``."""
    existing = s.query(FcCustomerIdentity).filter_by(kind=kind, value=value).first()
    if existing is None:
        s.add(FcCustomerIdentity(customer_id=customer.id, kind=kind, value=value, verified=False, source=source))
        s.flush()
        return "attached"
    owner = _follow_merge(s, s.get(FcCustomer, existing.customer_id))
    if owner.id == customer.id:
        return "already"
    pair = {customer.id, owner.id}
    known = s.query(FcMergeSuggestion).filter(
        FcMergeSuggestion.status.in_(("pending", "separate")),
        FcMergeSuggestion.customer_id.in_(pair),
        FcMergeSuggestion.candidate_id.in_(pair),
    ).first()
    if known is None:
        s.add(FcMergeSuggestion(customer_id=customer.id, candidate_id=owner.id,
                                reason=f"same {kind} mentioned by both", confidence=0.8 if kind == "phone" else 0.7,
                                evidence_json=json.dumps([{"kind": kind, "masked": mask(kind, value),
                                                           "source": source}])))
        s.flush()
    return "suggested_merge"


# ───────────────────────────── human decisions ─────────────────────────────


def mask(kind: str, value: str) -> str:
    """Show enough to recognise an identifier, never the whole value."""
    v = value or ""
    if kind == "phone":
        return v[:4] + "*" * max(0, len(v) - 7) + v[-3:] if len(v) > 7 else "***"
    if kind == "email" and "@" in v:
        user, _, domain = v.partition("@")
        return (user[:1] + "***@" + domain[:1] + "***." + domain.rsplit(".", 1)[-1]) if "." in domain else user[:1] + "***@***"
    return ("…" + v[-4:]) if len(v) > 4 else "***"


def identifiers(s: Session, customer_id: int) -> list[dict[str, Any]]:
    rows = s.query(FcCustomerIdentity).filter_by(customer_id=customer_id).order_by(FcCustomerIdentity.id).all()
    return [{"kind": r.kind, "masked": mask(r.kind, r.value), "verified": r.verified} for r in rows]


def suggestion_dto(s: Session, r: FcMergeSuggestion) -> dict[str, Any]:
    a, b = s.get(FcCustomer, r.customer_id), s.get(FcCustomer, r.candidate_id)
    ids_a, ids_b = identifiers(s, r.customer_id), identifiers(s, r.candidate_id)
    shared = sorted({(x["kind"], x["masked"]) for x in ids_a} & {(y["kind"], y["masked"]) for y in ids_b})
    evidence = json.loads(r.evidence_json or "[]")
    return {
        "id": str(r.id), "status": r.status, "reason": r.reason, "confidence": r.confidence,
        "customer": {"id": r.customer_id, "name": a.display_name if a else None, "stage": a.lead_stage if a else None,
                     "identifiers": ids_a, "hasTenant": bool(a and a.tenant_slug)},
        "candidate": {"id": r.candidate_id, "name": b.display_name if b else None, "stage": b.lead_stage if b else None,
                      "identifiers": ids_b, "hasTenant": bool(b and b.tenant_slug)},
        "matched": [{"kind": k, "masked": m} for k, m in shared]
        or [{"kind": e.get("kind"), "masked": e.get("masked")} for e in evidence],
        "mergeId": r.merge_id, "decidedBy": r.decided_by,
    }


def keep_separate(s: Session, suggestion: FcMergeSuggestion, *, actor: str) -> None:
    _decide(suggestion, "separate", actor)


def dismiss(s: Session, suggestion: FcMergeSuggestion, *, actor: str) -> None:
    _decide(suggestion, "dismissed", actor)


def _decide(suggestion: FcMergeSuggestion, status: str, actor: str) -> None:
    if suggestion.status != "pending":
        raise ValueError("suggestion already decided")
    suggestion.status, suggestion.decided_by, suggestion.decided_at = status, actor, datetime.utcnow()


def merge(s: Session, suggestion: FcMergeSuggestion, *, actor: str) -> FcCustomer:
    """Human-confirmed merge: the newer customer is folded into the older one (which keeps its id).

    Every moved row id and every overwritten value is written to an ``FcCustomerMerge`` ledger first, so the merge
    can be reverted exactly (``unmerge``)."""
    if suggestion.status != "pending":
        raise ValueError("suggestion already decided")
    keep = s.get(FcCustomer, min(suggestion.customer_id, suggestion.candidate_id))
    gone = s.get(FcCustomer, max(suggestion.customer_id, suggestion.candidate_id))
    if keep is None or gone is None or keep.merged_into_id or gone.merged_into_id:
        raise ValueError("customer already merged")
    ids = lambda model: [r.id for r in s.query(model).filter_by(customer_id=gone.id).all()]  # noqa: E731
    snapshot: dict[str, Any] = {
        "identities": ids(FcCustomerIdentity),
        "conversations": [r.conversation_ref for r in s.query(FcConversationCustomer).filter_by(customer_id=gone.id)],
        "facts": ids(FcMemoryFact),
        "transitions": ids(FcLeadTransition),
        "onboarding_moved": [],
        "onboarding_folded": [],
        "keep_before": {"lead_id": keep.lead_id, "tenant_slug": keep.tenant_slug},
    }
    s.query(FcCustomerIdentity).filter_by(customer_id=gone.id).update({"customer_id": keep.id})
    s.query(FcConversationCustomer).filter_by(customer_id=gone.id).update({"customer_id": keep.id})
    s.query(FcMemoryFact).filter_by(customer_id=gone.id).update({"customer_id": keep.id})
    s.query(FcLeadTransition).filter_by(customer_id=gone.id).update({"customer_id": keep.id})
    for step in s.query(FcOnboardingStep).filter_by(customer_id=gone.id).all():
        twin = s.query(FcOnboardingStep).filter_by(customer_id=keep.id, step=step.step).first()
        if twin is None:
            step.customer_id = keep.id
            snapshot["onboarding_moved"].append(step.id)
        else:
            snapshot["onboarding_folded"].append({"step": step.step, "done": step.done, "evidence": step.evidence,
                                                  "twin_done_before": twin.done})
            twin.done = twin.done or step.done
            s.delete(step)
    # Two active facts for the same key would be ambiguous: the kept customer's current fact wins, the merged
    # customer's becomes history (recorded so unmerge restores it).
    snapshot["facts_superseded"] = []
    active_keep = {f.key for f in s.query(FcMemoryFact).filter(FcMemoryFact.customer_id == keep.id,
                                                                  FcMemoryFact.status == "active",
                                                                  FcMemoryFact.id.notin_(snapshot["facts"] or [0]))}
    for fact in s.query(FcMemoryFact).filter(FcMemoryFact.id.in_(snapshot["facts"] or [0]), FcMemoryFact.status == "active"):
        if fact.key in active_keep:
            fact.status, fact.superseded_at, fact.status_reason = "superseded", datetime.utcnow(), "customer merge"
            snapshot["facts_superseded"].append(fact.id)
    keep.lead_id = keep.lead_id or gone.lead_id
    keep.tenant_slug = keep.tenant_slug or gone.tenant_slug
    gone.merged_into_id = keep.id
    ledger = FcCustomerMerge(suggestion_id=suggestion.id, kept_id=keep.id, merged_id=gone.id,
                             snapshot_json=json.dumps(snapshot), status="active", actor=actor)
    s.add(ledger)
    s.flush()
    suggestion.status = "merged"
    suggestion.merge_id = ledger.id
    suggestion.decided_by = actor
    suggestion.decided_at = datetime.utcnow()
    s.flush()
    return keep


def unmerge(s: Session, merge_id: int, *, actor: str) -> FcCustomer:
    """Revert a merge from its ledger. Rows created after the merge stay with the kept customer."""
    ledger = s.get(FcCustomerMerge, merge_id)
    if ledger is None or ledger.status != "active":
        raise ValueError("merge not found or already reverted")
    snap = json.loads(ledger.snapshot_json)
    keep, gone = s.get(FcCustomer, ledger.kept_id), s.get(FcCustomer, ledger.merged_id)
    if snap["identities"]:
        s.query(FcCustomerIdentity).filter(FcCustomerIdentity.id.in_(snap["identities"])).update(
            {"customer_id": gone.id}, synchronize_session=False)
    for ref in snap["conversations"]:
        link = s.get(FcConversationCustomer, ref)
        if link is not None:
            link.customer_id = gone.id
    if snap["facts"]:
        s.query(FcMemoryFact).filter(FcMemoryFact.id.in_(snap["facts"])).update(
            {"customer_id": gone.id}, synchronize_session=False)
    for fact_id in snap.get("facts_superseded", []):
        fact = s.get(FcMemoryFact, fact_id)
        if fact is not None and fact.status_reason == "customer merge":
            fact.status, fact.superseded_at, fact.status_reason = "active", None, None
    if snap["transitions"]:
        s.query(FcLeadTransition).filter(FcLeadTransition.id.in_(snap["transitions"])).update(
            {"customer_id": gone.id}, synchronize_session=False)
    if snap["onboarding_moved"]:
        s.query(FcOnboardingStep).filter(FcOnboardingStep.id.in_(snap["onboarding_moved"])).update(
            {"customer_id": gone.id}, synchronize_session=False)
    for folded in snap["onboarding_folded"]:
        s.add(FcOnboardingStep(customer_id=gone.id, step=folded["step"], done=folded["done"],
                               evidence=folded["evidence"]))
        twin = s.query(FcOnboardingStep).filter_by(customer_id=keep.id, step=folded["step"]).first()
        if twin is not None:
            twin.done = folded["twin_done_before"]
    keep.lead_id = snap["keep_before"]["lead_id"]
    keep.tenant_slug = snap["keep_before"]["tenant_slug"]
    gone.merged_into_id = None
    ledger.status, ledger.reverted_by, ledger.reverted_at = "reverted", actor, datetime.utcnow()
    suggestion = s.get(FcMergeSuggestion, ledger.suggestion_id) if ledger.suggestion_id else None
    if suggestion is not None:
        suggestion.status = "unmerged"
    s.flush()
    return gone
