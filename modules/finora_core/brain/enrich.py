"""Overlay brain state (lead stage, pending approvals) on conversation DTOs built from ai_sales rows."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import FcApproval, FcConversationCustomer, FcCustomer


def enrich_conversations(s: Session, dtos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = [d["id"] for d in dtos]
    if not refs:
        return dtos
    links = {l.conversation_ref: l.customer_id for l in s.query(FcConversationCustomer).filter(
        FcConversationCustomer.conversation_ref.in_(refs)).all()}
    customers = {c.id: c for c in s.query(FcCustomer).filter(FcCustomer.id.in_(set(links.values()) or {0})).all()}
    pending = dict(
        s.query(FcApproval.conversation_ref, func.count(FcApproval.id))
        .filter(FcApproval.status == "pending", FcApproval.conversation_ref.in_(refs))
        .group_by(FcApproval.conversation_ref)
        .all()
    )
    for d in dtos:
        customer = customers.get(links.get(d["id"], -1))
        if customer is not None:
            d["leadStage"] = customer.lead_stage
            d["customerId"] = f"fc{customer.id}"
        d["pendingApprovals"] = int(pending.get(d["id"], 0))
    return dtos
