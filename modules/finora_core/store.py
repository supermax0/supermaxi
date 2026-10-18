"""Explicit sessions for the two databases FINORA CORE touches.

Finora routes ``db.session`` by ``g.tenant``. FINORA CORE requests read the house tenant (ai_sales tables) AND
the Core DB (fc_* tables) in the same request, so Core access never goes through ``db.session``: it uses a
dedicated Session bound to the Core engine. House access uses ``db.session`` inside ``use_house()`` so the
existing ai_sales services keep working unchanged.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from flask import g, has_app_context
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from extensions import db

from .errors import house_not_configured
from .models import FcAuditLog, FcEvent, FcSetting

logger = logging.getLogger(__name__)

_HOUSE_SCHEMA_READY: set[str] = set()


@contextmanager
def core_session() -> Iterator[Session]:
    session = Session(bind=db.engine, expire_on_commit=False)
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def house_slug() -> str | None:
    """The tenant whose ai_sales channels are FINORA's own Instagram / Facebook pages."""
    from extensions_tenant import is_valid_tenant_slug

    slug = (os.environ.get("FINORA_CORE_HOUSE_TENANT") or "").strip().lower()
    if not slug:
        if not has_app_context():
            return None
        try:
            with core_session() as s:
                slug = (get_setting(s, "house_tenant", "") or "").strip().lower()
        except (OperationalError, ProgrammingError) as exc:
            # Older deployments/test apps may not have installed the optional Core module yet.
            if "no such table" in str(exc).lower() or "does not exist" in str(exc).lower():
                return None
            raise  # DB outages must not turn a configured house tenant into an unprotected customer tenant.
        if not slug:
            return None
    if not is_valid_tenant_slug(slug):
        logger.error("FINORA_CORE_HOUSE_TENANT is not a valid tenant slug")
        return None
    return slug


@contextmanager
def use_house() -> Iterator[str]:
    from extensions_tenant import get_tenant_db_path

    slug = house_slug()
    if not slug:
        raise house_not_configured()
    if not os.path.exists(get_tenant_db_path(slug)):
        # Never create an empty house database implicitly: it must be a provisioned tenant.
        logger.error("FINORA CORE house tenant %s has no database", slug)
        raise house_not_configured()
    previous = getattr(g, "tenant", None)
    if previous == slug:
        # Already inside the house context (e.g. a brain run calling a helper): never tear down the caller's session.
        yield slug
        return
    g.tenant = slug
    try:
        if slug not in _HOUSE_SCHEMA_READY:
            from modules.ai_sales.schema import ensure_ai_sales_schema

            ensure_ai_sales_schema()
            _HOUSE_SCHEMA_READY.add(slug)
        yield slug
    finally:
        db.session.remove()
        if previous is None:
            g.pop("tenant", None)
        else:
            g.tenant = previous


def environment() -> str:
    env = (os.environ.get("FINORA_ENV") or os.environ.get("FLASK_ENV") or "development").strip().lower()
    return env if env in {"development", "staging", "production"} else "production"


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:16]


# ───────────────────────────── settings ─────────────────────────────


def get_setting(s: Session, key: str, default: str | None = None) -> str | None:
    row = s.get(FcSetting, key)
    return row.value if row else default


def set_setting(s: Session, key: str, value: str, actor: str | None) -> None:
    row = s.get(FcSetting, key)
    if row:
        row.value = value
        row.updated_by = actor
        row.updated_at = datetime.utcnow()
    else:
        s.add(FcSetting(key=key, value=value, updated_by=actor))


KILL_SWITCH_KEY = "automation_paused"


def automation_paused(s: Session) -> bool:
    return get_setting(s, KILL_SWITCH_KEY, "0") == "1"


# ───────────────────────────── events + audit ─────────────────────────────


def emit(s: Session, type_: str, payload: dict[str, Any], *, dedupe_key: str | None = None) -> None:
    """Add an outbox event in the caller's transaction. With ``dedupe_key`` duplicates are skipped."""
    if dedupe_key and s.query(FcEvent.seq).filter_by(dedupe_key=dedupe_key).first():
        return
    s.add(FcEvent(type=type_, payload_json=json.dumps(payload, ensure_ascii=False), dedupe_key=dedupe_key))


def audit(
    s: Session,
    *,
    actor: str,
    actor_type: str,
    category: str,
    action: str,
    title: str,
    customer: str | None = None,
    conversation_ref: str | None = None,
    input_summary: str | None = None,
    result: str = "ok",
    correlation_id: str | None = None,
    dedupe_key: str | None = None,
    created_at: datetime | None = None,
    approval_id: str | None = None,
) -> FcAuditLog | None:
    if dedupe_key and s.query(FcAuditLog.id).filter_by(dedupe_key=dedupe_key).first():
        return None
    row = FcAuditLog(
        actor=actor[:120],
        actor_type=actor_type,
        category=category,
        action=action,
        title=title[:200],
        customer=(customer or None) and customer[:150],
        conversation_ref=conversation_ref,
        tenant_ref=house_slug(),
        input_summary=(input_summary or None) and input_summary[:500],
        result=result,
        correlation_id=correlation_id or new_correlation_id(),
        dedupe_key=dedupe_key,
        created_at=created_at or datetime.utcnow(),
        approval_id=approval_id,
    )
    s.add(row)
    s.flush()
    emit(s, "activity", {"event": activity_dto(row)})
    return row


def activity_dto(row: FcAuditLog) -> dict[str, Any]:
    return {
        "id": f"a{row.id}",
        "at": iso(row.created_at),
        "category": row.category,
        "title": row.title,
        "detail": row.input_summary,
        "customerName": row.customer,
        "result": row.result,
        "correlationId": row.correlation_id,
    }


def house_tag() -> str:
    import hashlib

    return hashlib.sha1((house_slug() or "").encode("utf-8")).hexdigest()[:10]


def msg_ref(message_id: Any, created_iso: str) -> str:
    """Stable identity of a house message for dedupe keys. Message ids alone repeat when the house DB is recreated or
    restored, so the house tag and the creation time are part of the key (events / audit rows are never lost)."""
    return f"{house_tag()}:{message_id}:{created_iso}"


def iso(value: datetime | None) -> str:
    """Naive UTC datetimes → RFC 3339 with offset (the desktop schema requires an offset)."""
    return (value or datetime.utcnow()).replace(microsecond=0).isoformat() + "Z"
