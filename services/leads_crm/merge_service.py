"""Lead merge service — preserves timeline, sources, notes, phones."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from extensions import db
from models.core.leads.models import (
    BusinessLead,
    BusinessLeadPhone,
    LeadAuditLog,
    LeadDuplicateCandidate,
    LeadFollowUp,
    LeadInteraction,
    LeadMergeLog,
    LeadNote,
    LeadSourceRecord,
)
from services.leads_crm.audit_service import log_lead_action
from utils.leads_crm.name_normalize import normalize_business_name


def _snapshot_lead(lead: BusinessLead) -> dict[str, Any]:
    return {
        "id": lead.id,
        "business_name": lead.business_name,
        "status": lead.status,
        "phones": [p.normalized_phone for p in lead.phones],
        "sources": [s.source_name for s in lead.sources],
        "full_address": lead.full_address,
        "instagram_url": lead.instagram_url,
    }


def merge_leads(
    target_id: int,
    source_id: int,
    *,
    actor_id: int | None = None,
    field_preferences: dict[str, str] | None = None,
) -> tuple[BusinessLead | None, dict[str, Any]]:
    if target_id == source_id:
        return None, {"error": "لا يمكن دمج Lead مع نفسه"}

    target = BusinessLead.query.filter_by(id=target_id, deleted_at=None).first()
    source = BusinessLead.query.filter_by(id=source_id, deleted_at=None).first()
    if not target or not source:
        return None, {"error": "Lead غير موجود"}

    prefs = field_preferences or {}
    snapshot = {
        "target": _snapshot_lead(target),
        "source": _snapshot_lead(source),
    }

    # Fill empty target fields from source
    fill_fields = [
        "owner_name", "governorate", "city", "district", "area", "full_address",
        "website", "instagram_url", "facebook_url", "tiktok_url",
        "latitude", "longitude", "preferred_contact_method", "source_primary",
    ]
    for field in fill_fields:
        if prefs.get(field) == "source":
            setattr(target, field, getattr(source, field))
        elif not getattr(target, field) and getattr(source, field):
            setattr(target, field, getattr(source, field))

    if prefs.get("business_name") == "source" and source.business_name:
        target.business_name = source.business_name
        target.normalized_business_name = normalize_business_name(source.business_name)

    # Status: keep target (older) unless explicitly overridden
    if prefs.get("status") == "source":
        target.status = source.status

    # Move phones
    for phone in list(source.phones):
        existing = BusinessLeadPhone.query.filter_by(normalized_phone=phone.normalized_phone).first()
        if existing and existing.lead_id != target.id:
            continue
        phone.lead_id = target.id
        phone.is_primary = False

    # Move sources (dedupe by name)
    existing_sources = {s.source_name for s in target.sources}
    for src in source.sources:
        if src.source_name not in existing_sources:
            db.session.add(
                LeadSourceRecord(
                    lead_id=target.id,
                    source_name=src.source_name,
                    source_detail=src.source_detail,
                    import_batch_id=src.import_batch_id,
                )
            )
            existing_sources.add(src.source_name)

    # Move notes, interactions, follow-ups
    LeadNote.query.filter_by(lead_id=source.id).update({"lead_id": target.id})
    LeadInteraction.query.filter_by(lead_id=source.id).update({"lead_id": target.id})
    LeadFollowUp.query.filter_by(lead_id=source.id).update({"lead_id": target.id})
    LeadAuditLog.query.filter_by(lead_id=source.id).update({"lead_id": target.id})

    # Mark source as merged
    source.merged_into_lead_id = target.id
    source.merged_at = datetime.utcnow()
    source.merged_by = actor_id
    source.is_active = False
    source.duplicate_status = "NONE"

    LeadDuplicateCandidate.query.filter(
        (LeadDuplicateCandidate.lead_id == source.id) | (LeadDuplicateCandidate.candidate_lead_id == source.id)
    ).update({"status": "merged"})

    db.session.add(
        LeadMergeLog(
            target_lead_id=target.id,
            source_lead_id=source.id,
            merged_by=actor_id,
            snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        )
    )
    log_lead_action(
        target.id,
        "lead_merged",
        actor_id,
        {"source_lead_id": source.id, "snapshot": snapshot},
    )
    db.session.commit()
    return target, {"ok": True, "target_id": target.id}
