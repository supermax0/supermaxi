"""FINORA CORE Shadow Mode (Phase 9 / Priority 2).

When ``AI_SHADOW_MODE`` is on, every real customer message in the house tenant goes through the full brain pipeline
(resolve customer → safe memory → intents → knowledge → plan → policy verdicts → approvals it *would* request) and the
result is stored as an ``FcShadowProposal``. Nothing is sent, no FINORA tool runs, no tenant is created, no discount
or subscription changes. Humans keep answering; their reply is recorded next to the proposal (accepted / edited /
ignored + similarity) and operators can review the escalation call.

Shadow Mode is independent of the kill switch: it never sends anything, so it keeps learning while automation is
paused, and it overrides live auto-replies while on.
"""
from __future__ import annotations

import difflib
import logging
import time
from datetime import datetime
from typing import Any

from flask import current_app

from extensions import db

from ..store import audit, core_session, emit
from . import policy
from .extract import normalize
from .models import FcShadowProposal

logger = logging.getLogger(__name__)

MAX_BURST = 10


def shadow_enabled() -> bool:
    try:
        with core_session() as s:
            return policy.flag(s, "AI_SHADOW_MODE") == "on"
    except Exception:
        logger.exception("shadow mode flag unreadable; treated as off")
        return False


def _burst_for(inbound) -> list:
    """Customer messages since the last business reply (read-only — statuses stay as humans need them)."""
    from modules.ai_sales.models import AISalesMessage

    last_out = (
        db.session.query(db.func.max(AISalesMessage.id))
        .filter(AISalesMessage.conversation_id == inbound.conversation_id, AISalesMessage.direction == "outbound")
        .scalar()
    ) or 0
    rows = (
        AISalesMessage.query.filter(
            AISalesMessage.conversation_id == inbound.conversation_id,
            AISalesMessage.direction == "inbound",
            AISalesMessage.id > last_out,
            AISalesMessage.id <= inbound.id,
        )
        .order_by(AISalesMessage.id.desc())
        .limit(MAX_BURST)
        .all()
    )
    return list(reversed(rows)) or [inbound]


def _newer_inbound_exists(inbound) -> bool:
    from modules.ai_sales.models import AISalesMessage

    return AISalesMessage.query.filter(
        AISalesMessage.conversation_id == inbound.conversation_id,
        AISalesMessage.direction == "inbound",
        AISalesMessage.id > inbound.id,
    ).first() is not None


def shadow_house_message(inbound, *, wait_for_burst: bool = True) -> None:
    """Think about a house message without acting. Never raises into the Meta pipeline."""
    from modules.ai_sales import engine

    from .runtime import handle_house_message

    try:
        if wait_for_burst and inbound.message_type in engine._BATCHABLE_MESSAGE_TYPES:
            time.sleep(engine._BURST_WAIT_SECONDS)
            db.session.expire_all()
        if _newer_inbound_exists(inbound):
            return None  # the newest message of the burst owns the proposal
        handle_house_message(inbound, _burst_for(inbound), send_external=False, mode="shadow")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("finora_core shadow run failed for message %s", inbound.id)
    return None


# ───────────────────────────── human side ─────────────────────────────


def similarity(a: str, b: str) -> float:
    return round(difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio(), 3)


def record_human_reply(*, conversation_ref: str, message_id: int, text: str, actor: str,
                       proposal_id: str | None = None, used_proposal: bool = False) -> FcShadowProposal | None:
    """Attach the reply a human actually sent to the open proposal of that conversation."""
    with core_session() as s:
        q = s.query(FcShadowProposal).filter_by(conversation_ref=str(conversation_ref), status="pending")
        if proposal_id and str(proposal_id).isdigit():
            q = q.filter_by(id=int(proposal_id))
        proposal = q.order_by(FcShadowProposal.id.desc()).first()
        if proposal is None:
            return None
        _attach(proposal, message_id=message_id, text=text, actor=actor, used=bool(used_proposal and proposal_id))
        audit(s, actor=actor, actor_type="human", category="ai", action="shadow.human_reply",
              title="رد بشري مقابل اقتراح وضع الظل", conversation_ref=str(conversation_ref),
              input_summary=("accepted" if proposal.accepted else "edited" if proposal.edited else "own reply")
              + f" similarity={proposal.similarity}")
        from .runtime import proposal_dto

        emit(s, "shadow.proposal", {"proposal": proposal_dto(proposal)})
        s.commit()
        return proposal


def _attach(proposal: FcShadowProposal, *, message_id: int, text: str, actor: str, used: bool) -> None:
    same = normalize(text) == normalize(proposal.proposed_reply)
    proposal.status = "answered"
    proposal.human_message_id = message_id
    proposal.human_reply = text[:2000]
    proposal.human_actor = actor[:120]
    proposal.human_replied_at = datetime.utcnow()
    proposal.operator_used = used
    proposal.accepted = bool(used and same)
    proposal.edited = bool(used and not same)
    proposal.similarity = similarity(text, proposal.proposed_reply)


def reconcile(conversation_ref: str | None = None) -> int:
    """Pick up human replies sent outside the desktop (Meta inbox, web inbox) for still-pending proposals."""
    from modules.ai_sales.models import AISalesMessage

    from ..store import use_house

    done = 0
    with core_session() as s:
        q = s.query(FcShadowProposal).filter_by(status="pending")
        if conversation_ref:
            q = q.filter_by(conversation_ref=str(conversation_ref))
        pending = q.order_by(FcShadowProposal.id.asc()).limit(200).all()
        if not pending:
            return 0
        with use_house():
            for proposal in pending:
                if not proposal.conversation_ref.isdigit():
                    continue
                reply = (
                    AISalesMessage.query.filter(
                        AISalesMessage.conversation_id == int(proposal.conversation_ref),
                        AISalesMessage.direction == "outbound",
                        AISalesMessage.sender_type != "ai",
                        AISalesMessage.id > proposal.trigger_message_id,
                    )
                    .order_by(AISalesMessage.id.asc())
                    .first()
                )
                if reply is not None and (reply.text_content or "").strip():
                    _attach(proposal, message_id=reply.id, text=reply.text_content, actor=reply.sender_type or "human",
                            used=False)
                    done += 1
        if done:
            s.commit()
    return done


def review(proposal_id: int, *, escalation_decision: str, actor: str) -> FcShadowProposal:
    if escalation_decision not in {"agree", "disagree"}:
        raise ValueError("escalation decision must be agree | disagree")
    with core_session() as s:
        proposal = s.get(FcShadowProposal, proposal_id)
        if proposal is None:
            raise LookupError("proposal not found")
        proposal.escalation_decision = escalation_decision
        proposal.reviewed_by = actor[:120]
        audit(s, actor=actor, actor_type="human", category="ai", action="shadow.review",
              title="مراجعة قرار التصعيد في وضع الظل", conversation_ref=proposal.conversation_ref,
              input_summary=f"proposed={proposal.proposed_escalation} decision={escalation_decision}")
        s.commit()
        s.refresh(proposal)
        s.expunge(proposal)
        return proposal


def stats() -> dict[str, Any]:
    with core_session() as s:
        rows = s.query(FcShadowProposal).all()
        answered = [r for r in rows if r.status == "answered"]
        reviewed = [r for r in rows if r.escalation_decision]
        return {
            "proposals": len(rows),
            "pending": sum(1 for r in rows if r.status == "pending"),
            "answered": len(answered),
            "accepted": sum(1 for r in answered if r.accepted),
            "edited": sum(1 for r in answered if r.edited),
            "ownReply": sum(1 for r in answered if not r.operator_used),
            "avgSimilarity": round(sum(r.similarity or 0 for r in answered) / len(answered), 3) if answered else None,
            "escalationAgreement": round(sum(1 for r in reviewed if r.escalation_decision == "agree") / len(reviewed), 3)
            if reviewed else None,
        }
