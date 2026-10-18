"""Customer-scoped owner inbox. Reports are notifications inside FINORA CORE, never external messages."""
from datetime import datetime

from extensions import db
from ..store import audit, emit, iso
from .observability import redact


class FcSupportIssue(db.Model):
    __tablename__ = "fc_support_issues"
    id = db.Column(db.Integer, primary_key=True)
    dedupe_key = db.Column(db.String(160), nullable=False, unique=True)
    customer_id = db.Column(db.Integer, nullable=False, index=True)
    conversation_ref = db.Column(db.String(40), nullable=False, index=True)
    tenant_slug = db.Column(db.String(100))
    kind = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    details = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    verified = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.String(120))


def dto(row, customer_name):
    return {"id": str(row.id), "customerName": customer_name, "conversationId": row.conversation_ref,
            "tenantSlug": row.tenant_slug, "kind": row.kind, "title": row.title, "details": row.details,
            "status": row.status, "verified": bool(row.verified), "at": iso(row.created_at)}


def report(s, customer, conversation_ref, *, kind, details, source, verified=False):
    key = f"{kind}:{customer.id}:{source}"[:160]
    prior = s.query(FcSupportIssue).filter_by(dedupe_key=key).first()
    if prior and (prior.status == "open" or kind != "provider_error"):
        return prior
    titles = {"bug": "العميل أبلغ عن خلل", "missing_feature": "طلب ميزة تحتاج مراجعة", "missing_template": "طلب قالب جديد لنشاط العميل", "configuration_error": "تعذر إعداد حساب العميل", "account_link": "حساب العميل يحتاج ربطاً وتحققاً"}
    titles.update({"consultation_error": "الاستشارة البرمجية تحتاج مراجعة", "project_change": "طلب تعديل مشروع متفق عليه",
                   "quote_negotiation": "العميل طلب تخفيض أو مراجعة سعر المشروع",
                   "provider_error": "مزود الذكاء يحتاج متابعة", "reply_quality": "رد العميل يحتاج مراجعة"})
    row = prior or FcSupportIssue(dedupe_key=key, customer_id=customer.id, conversation_ref=str(conversation_ref), tenant_slug=customer.tenant_slug,
                                  kind=kind, title=titles.get(kind, "متابعة حساب العميل"), details=str(redact(details))[:2000], verified=verified)
    if prior:
        row.status, row.resolved_at, row.resolved_by = "open", None, None
        row.details, row.verified, row.created_at = str(redact(details))[:2000], verified, datetime.utcnow()
    s.add(row)
    s.flush()
    audit(s, actor="FINORA CORE", actor_type="ai", category="errors", action="support.report", title=row.title,
          customer=customer.display_name, conversation_ref=str(conversation_ref), result="pending", input_summary=row.details[:300])
    emit(s, "support.issue", {"issue": dto(row, customer.display_name)})
    return row
