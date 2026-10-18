"""Deduplication engine for Leads CRM."""
from __future__ import annotations

from dataclasses import dataclass

from models.core.leads.models import BusinessLead, BusinessLeadPhone
from utils.leads_crm.name_normalize import name_similarity_score, normalize_business_name
from utils.leads_crm.phone_normalize import normalize_iraq_phone


@dataclass
class DuplicateMatch:
    level: str  # EXACT | STRONG | POSSIBLE | NONE
    lead_id: int | None
    score: float
    reason: str


def find_phone_owner(normalized_phone: str) -> BusinessLeadPhone | None:
    if not normalized_phone:
        return None
    return BusinessLeadPhone.query.filter_by(normalized_phone=normalized_phone).first()


def detect_duplicate(
    *,
    business_name: str,
    phone: str | None = None,
    governorate: str | None = None,
    district: str | None = None,
    full_address: str | None = None,
    exclude_lead_id: int | None = None,
) -> DuplicateMatch:
    normalized_phone = normalize_iraq_phone(phone)
    if normalized_phone:
        phone_row = find_phone_owner(normalized_phone)
        if phone_row and phone_row.lead_id != exclude_lead_id:
            lead = BusinessLead.query.get(phone_row.lead_id)
            if lead and not lead.deleted_at and not lead.merged_into_lead_id:
                return DuplicateMatch(
                    level="EXACT",
                    lead_id=lead.id,
                    score=100.0,
                    reason="نفس رقم الهاتف",
                )

    norm_name = normalize_business_name(business_name)
    if not norm_name:
        return DuplicateMatch(level="NONE", lead_id=None, score=0.0, reason="")

    q = BusinessLead.query.filter(
        BusinessLead.deleted_at.is_(None),
        BusinessLead.merged_into_lead_id.is_(None),
        BusinessLead.normalized_business_name == norm_name,
    )
    if exclude_lead_id:
        q = q.filter(BusinessLead.id != exclude_lead_id)
    if governorate:
        q = q.filter(BusinessLead.governorate == governorate)

    exact_name = q.first()
    if exact_name:
        return DuplicateMatch(
            level="STRONG",
            lead_id=exact_name.id,
            score=95.0,
            reason="اسم مطابق + نفس المحافظة",
        )

    candidates = BusinessLead.query.filter(
        BusinessLead.deleted_at.is_(None),
        BusinessLead.merged_into_lead_id.is_(None),
    )
    if exclude_lead_id:
        candidates = candidates.filter(BusinessLead.id != exclude_lead_id)
    if governorate:
        candidates = candidates.filter(BusinessLead.governorate == governorate)

    best: DuplicateMatch | None = None
    for lead in candidates.limit(500).all():
        sim = name_similarity_score(business_name, lead.business_name)
        if sim < 0.7:
            continue
        score = sim * 100
        reasons = [f"اسم مشابه {score:.0f}%"]
        if governorate and lead.governorate == governorate:
            reasons.append("نفس المحافظة")
        if district and lead.district and district in (lead.district or ""):
            score = min(score + 5, 99)
            reasons.append("منطقة قريبة")
        if full_address and lead.full_address and normalize_business_name(full_address) in normalize_business_name(lead.full_address):
            score = min(score + 5, 99)
            reasons.append("عنوان قريب")

        level = "STRONG" if score >= 90 else "POSSIBLE"
        if best is None or score > best.score:
            best = DuplicateMatch(
                level=level,
                lead_id=lead.id,
                score=score,
                reason=" — ".join(reasons),
            )

    return best or DuplicateMatch(level="NONE", lead_id=None, score=0.0, reason="")
