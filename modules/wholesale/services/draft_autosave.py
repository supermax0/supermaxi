"""Autosave drafts for Operations Center tabs."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import or_

from extensions import db
from modules.wholesale.models.draft import WholesaleDraft
from modules.wholesale.services.helpers import WholesaleError


def list_drafts(tenant_id: int | None, employee_id: int | None = None, op_type: str | None = None):
    q = WholesaleDraft.query.filter(WholesaleDraft.deleted_at.is_(None))
    if tenant_id is not None:
        q = q.filter(or_(WholesaleDraft.tenant_id == tenant_id, WholesaleDraft.tenant_id.is_(None)))
    if employee_id:
        q = q.filter(WholesaleDraft.employee_id == employee_id)
    if op_type:
        q = q.filter(WholesaleDraft.op_type == op_type)
    return q.order_by(WholesaleDraft.updated_at.desc()).all()


def save_draft(
    tenant_id: int | None,
    *,
    employee_id: int | None,
    op_type: str,
    payload: dict,
    draft_id: int | None = None,
    title: str | None = None,
) -> WholesaleDraft:
    if op_type not in ("sale", "receipt", "purchase", "payment"):
        raise WholesaleError("نوع المسودة غير صالح")
    body = json.dumps(payload or {}, ensure_ascii=False)
    if draft_id:
        draft = WholesaleDraft.query.get(draft_id)
        if not draft or draft.deleted_at:
            raise WholesaleError("المسودة غير موجودة")
        if tenant_id is not None and draft.tenant_id not in (tenant_id, None):
            raise WholesaleError("المسودة غير موجودة")
        draft.payload_json = body
        draft.title = title or draft.title
        draft.op_type = op_type
        draft.updated_at = datetime.utcnow()
        db.session.flush()
        return draft
    draft = WholesaleDraft(
        tenant_id=tenant_id,
        employee_id=employee_id,
        op_type=op_type,
        title=title or op_type,
        payload_json=body,
    )
    db.session.add(draft)
    db.session.flush()
    return draft


def delete_draft(tenant_id: int | None, draft_id: int) -> None:
    draft = WholesaleDraft.query.get(draft_id)
    if not draft:
        return
    if tenant_id is not None and draft.tenant_id not in (tenant_id, None):
        raise WholesaleError("المسودة غير موجودة")
    draft.deleted_at = datetime.utcnow()
    db.session.flush()


def draft_to_dict(draft: WholesaleDraft) -> dict:
    try:
        payload = json.loads(draft.payload_json or "{}")
    except Exception:
        payload = {}
    return {
        "id": draft.id,
        "op_type": draft.op_type,
        "title": draft.title,
        "payload": payload,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }
