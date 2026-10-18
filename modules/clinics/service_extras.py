"""Expenses, refunds, attachments, consent, cash sessions, specialty packs, OTP, QR."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from datetime import date, datetime, timedelta
from urllib.parse import quote

from flask import current_app
from werkzeug.utils import secure_filename
from sqlalchemy import or_

from extensions import db
from modules.clinics.models import (
    ClinicAttachment,
    ClinicBookingOtp,
    ClinicCashSession,
    ClinicConsent,
    ClinicExpense,
    ClinicInvoice,
    ClinicLabTest,
    ClinicPayment,
    ClinicProcedure,
    ClinicRefund,
    ClinicPurchase,
    ClinicPurchasePayment,
    ClinicDoctorSettlement,
    ClinicService,
    ClinicPatient,
    ClinicVisit,
)
from modules.clinics.service import (
    _audit,
    _money,
    _parse_date,
    _today,
    get_or_create_settings,
    invoice_dict,
)

ATTACHMENT_CATEGORIES = (
    ("lab", "تحليل"),
    ("radiology", "أشعة"),
    ("prescription", "وصفة"),
    ("medical_report", "تقرير طبي"),
    ("referral", "إحالة"),
    ("id", "هوية / مستمسكات"),
    ("medical_image", "صورة طبية"),
    ("consent", "موافقة"),
    ("pdf", "مستند PDF"),
    ("other", "أخرى"),
)

ATTACHMENT_TYPES = dict(ATTACHMENT_CATEGORIES)
ALLOWED_ATTACHMENT_MIMES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024

SPECIALTY_PACKS = {
    "dental": {
        "services": [
            ("كشف أسنان", "كشف", 15, 25000),
            ("حشو", "علاج", 30, 50000),
            ("تنظيف لثة", "وقاية", 30, 40000),
            ("خلع سن", "جراحة", 20, 35000),
        ],
        "procedures": [("تركيب حشوة مؤقتة", 20000), ("تلميع أسنان", 15000)],
    },
    "dermatology": {
        "services": [
            ("كشف جلدية", "كشف", 15, 30000),
            ("جلسة ليزر", "تجميل", 45, 120000),
            ("علاج حب الشباب", "علاج", 20, 45000),
        ],
        "procedures": [("تقشير كيميائي خفيف", 80000)],
    },
    "pediatrics": {
        "services": [
            ("كشف أطفال", "كشف", 15, 25000),
            ("تطعيم", "وقاية", 10, 15000),
            ("متابعة نمو", "متابعة", 15, 20000),
        ],
        "procedures": [],
    },
    "ophthalmology": {
        "services": [
            ("كشف عيون", "كشف", 20, 30000),
            ("فحص نظر", "تشخيص", 15, 20000),
            ("قياس ضغط العين", "تشخيص", 10, 15000),
        ],
        "procedures": [],
    },
    "cosmetic": {
        "services": [
            ("استشارة تجميل", "كشف", 20, 40000),
            ("جلسة فيلر", "تجميل", 45, 250000),
            ("بوتوكس", "تجميل", 30, 200000),
        ],
        "procedures": [],
    },
    "general_practice": {
        "services": [
            ("كشف عام", "كشف", 15, 20000),
            ("متابعة", "متابعة", 10, 15000),
            ("حقنة عضل", "إجراء", 5, 5000),
        ],
        "procedures": [("ضماد جرح", 10000)],
        "labs": [("CBC", "دم", 15000), ("سكر صائم", "دم", 8000)],
    },
}


def expense_dict(row: ClinicExpense) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "category": row.category,
        "amount": row.amount,
        "expense_date": row.expense_date.isoformat() if row.expense_date else "",
        "payment_method": row.payment_method,
        "notes": row.notes or "",
    }


def list_expenses(tenant_id: int, day: date | None = None) -> list[dict]:
    query = ClinicExpense.query.filter_by(tenant_id=tenant_id)
    if day:
        query = query.filter_by(expense_date=day)
    return [expense_dict(r) for r in query.order_by(ClinicExpense.id.desc()).limit(200).all()]


def create_expense(tenant_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    title = str(payload.get("title") or "").strip()
    amount = _money(payload.get("amount"))
    if not title or amount <= 0:
        raise ValueError("عنوان ومبلغ المصروف مطلوبان")
    row = ClinicExpense(
        tenant_id=tenant_id,
        branch_id=branch_id,
        title=title,
        category=str(payload.get("category") or "تشغيل").strip() or "تشغيل",
        amount=amount,
        expense_date=_parse_date(payload.get("expense_date") or _today().isoformat(), "تاريخ المصروف"),
        payment_method=str(payload.get("payment_method") or "cash").strip() or "cash",
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    ClinicAccountingPostingService.post_clinic_expense(row.id, tenant_id, actor_id)
    _audit(tenant_id, actor_id, "expense", row.id, "create", title, branch_id=branch_id)
    return expense_dict(row)


def refund_invoice(tenant_id: int, invoice_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    inv = ClinicInvoice.query.filter_by(tenant_id=tenant_id, id=invoice_id).first()
    if not inv:
        raise ValueError("الفاتورة غير موجودة")
    amount = _money(payload.get("amount") or inv.paid)
    if amount <= 0:
        raise ValueError("مبلغ الاسترجاع غير صالح")
    if amount > inv.paid:
        raise ValueError("لا يمكن استرجاع أكثر من المدفوع")
    row = ClinicRefund(
        tenant_id=tenant_id,
        branch_id=branch_id or inv.branch_id,
        invoice_id=inv.id,
        patient_id=inv.patient_id,
        amount=amount,
        reason=str(payload.get("reason") or "").strip() or None,
        method=str(payload.get("method") or "cash").strip() or "cash",
        created_by=actor_id,
    )
    db.session.add(row)
    inv.paid = max(0, inv.paid - amount)
    inv.balance = max(0, inv.total - inv.paid)
    if inv.paid == 0 and amount:
        inv.status = "refunded" if inv.balance == inv.total else "open"
    elif inv.balance == 0:
        inv.status = "paid"
    else:
        inv.status = "partial"
    inv.updated_by = actor_id
    inv.updated_at = datetime.utcnow()
    db.session.flush()
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    ClinicAccountingPostingService.post_clinic_refund(row.id, tenant_id, actor_id)
    _audit(tenant_id, actor_id, "refund", row.id, "create", f"استرجاع {amount}", branch_id=branch_id)
    return {"refund_id": row.id, "invoice": invoice_dict(inv)}


def _uploads_dir(tenant_id: int) -> str:
    root = current_app.root_path
    path = os.path.join(root, "uploads", "clinics", str(tenant_id))
    os.makedirs(path, exist_ok=True)
    return path


def _attachment_actor_name(actor_id) -> str:
    if not actor_id:
        return ""
    try:
        from models.employee import Employee
        actor = db.session.get(Employee, actor_id)
        return str(getattr(actor, "name", None) or getattr(actor, "full_name", None) or "")
    except Exception:
        return ""


def attachment_dict(row: ClinicAttachment) -> dict:
    patient = ClinicPatient.query.filter_by(tenant_id=row.tenant_id, id=row.patient_id).first()
    visit = ClinicVisit.query.filter_by(tenant_id=row.tenant_id, id=row.visit_id).first() if row.visit_id else None
    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "visit_id": row.visit_id,
        "category": row.category,
        "category_label": ATTACHMENT_TYPES.get(row.category, ATTACHMENT_TYPES["other"]),
        "file_name": row.file_name,
        "mime_type": row.mime_type or "",
        "size_bytes": row.size_bytes,
        "patient_name": patient.full_name if patient else "",
        "patient_file": patient.file_number if patient else "",
        "patient_phone": patient.phone if patient else "",
        "visit_date": visit.visit_date.isoformat() if visit and visit.visit_date else "",
        "document_date": row.document_date.isoformat() if row.document_date else "",
        "notes": row.notes or "",
        "uploaded_by": row.uploaded_by,
        "uploaded_by_name": _attachment_actor_name(row.uploaded_by),
        "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else "",
        "url": f"/clinics/api/attachments/{row.id}/download",
        "preview_url": f"/clinics/api/attachments/{row.id}/preview",
    }


def list_attachments(tenant_id: int, params: dict | None = None) -> dict:
    from sqlalchemy import func, or_
    params = params or {}
    query = ClinicAttachment.query.filter_by(tenant_id=tenant_id)
    patient_id = params.get("patient_id")
    visit_id = params.get("visit_id")
    if patient_id:
        query = query.filter_by(patient_id=int(patient_id))
    if visit_id:
        query = query.filter_by(visit_id=int(visit_id))
    term = str(params.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        query = query.join(ClinicPatient, ClinicPatient.id == ClinicAttachment.patient_id).filter(
            or_(ClinicAttachment.file_name.ilike(like), ClinicPatient.full_name.ilike(like),
                ClinicPatient.file_number.ilike(like), ClinicPatient.phone.ilike(like))
        )
    category = str(params.get("category") or "").strip()
    if category:
        query = query.filter(ClinicAttachment.category == category)
    linked = str(params.get("linked") or "").strip()
    if linked == "yes": query = query.filter(ClinicAttachment.visit_id.isnot(None))
    elif linked == "no": query = query.filter(ClinicAttachment.visit_id.is_(None))
    mime_group = str(params.get("mime_group") or "").strip()
    if mime_group == "pdf": query = query.filter(ClinicAttachment.mime_type == "application/pdf")
    elif mime_group == "image": query = query.filter(ClinicAttachment.mime_type.like("image/%"))
    elif mime_group == "document": query = query.filter(ClinicAttachment.mime_type.like("application/%"))
    date_from = params.get("date_from")
    if date_from:
        query = query.filter(ClinicAttachment.uploaded_at >= _parse_date(date_from, "من تاريخ"))
    uploaded_by = params.get("uploaded_by")
    if uploaded_by: query = query.filter(ClinicAttachment.uploaded_by == int(uploaded_by))
    page = max(1, int(params.get("page") or 1))
    per_page = min(100, max(1, int(params.get("per_page") or 25)))
    total = query.count()
    rows = query.order_by(ClinicAttachment.uploaded_at.desc(), ClinicAttachment.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    base = ClinicAttachment.query.filter_by(tenant_id=tenant_id)
    month_start = date.today().replace(day=1)
    category_counts = dict(db.session.query(ClinicAttachment.category, func.count(ClinicAttachment.id)).filter(ClinicAttachment.tenant_id == tenant_id).group_by(ClinicAttachment.category).all())
    stats = {"total": base.count(), "lab": category_counts.get("lab", 0), "radiology": category_counts.get("radiology", 0), "medical_report": category_counts.get("medical_report", 0), "this_month": base.filter(ClinicAttachment.uploaded_at >= month_start).count()}
    return {"items": [attachment_dict(r) for r in rows], "page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page), "stats": stats, "categories": [{"key": k, "label": v} for k, v in ATTACHMENT_CATEGORIES]}


def _detected_mime(stream) -> str:
    head = stream.read(16)
    stream.seek(0)
    if head.startswith(b"%PDF-"): return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"): return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"): return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP": return "image/webp"
    if head.startswith(b"PK\x03\x04"): return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return ""


def save_attachment(tenant_id: int, patient_id: int, file_storage, payload: dict, actor_id=None) -> dict:
    if not file_storage or not getattr(file_storage, "filename", None):
        raise ValueError("الملف مطلوب")
    patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=int(patient_id)).first()
    if not patient: raise ValueError("المريض غير موجود")
    visit_id = int(payload["visit_id"]) if payload.get("visit_id") else None
    if visit_id and not ClinicVisit.query.filter_by(tenant_id=tenant_id, id=visit_id, patient_id=int(patient_id)).first():
        raise ValueError("الزيارة لا تخص المريض المحدد")
    original = secure_filename(file_storage.filename) or "file"
    detected = _detected_mime(file_storage.stream)
    if detected not in ALLOWED_ATTACHMENT_MIMES: raise ValueError("نوع الملف غير مسموح أو لا يطابق محتواه")
    supplied_ext = os.path.splitext(original)[1].lower()
    valid_exts = {".jpg", ".jpeg"} if detected == "image/jpeg" else {ALLOWED_ATTACHMENT_MIMES[detected]}
    if supplied_ext not in valid_exts: raise ValueError("امتداد الملف لا يطابق محتواه")
    stored = f"{uuid.uuid4().hex}{ALLOWED_ATTACHMENT_MIMES[detected]}"
    dest = os.path.join(_uploads_dir(tenant_id), stored)
    file_storage.save(dest)
    size = os.path.getsize(dest)
    if size <= 0 or size > MAX_ATTACHMENT_BYTES:
        try: os.remove(dest)
        except OSError: pass
        raise ValueError("حجم الملف يجب ألا يتجاوز 25 MB")
    category = str(payload.get("category") or "other").strip()
    if category not in ATTACHMENT_TYPES: category = "other"
    row = ClinicAttachment(
        tenant_id=tenant_id,
        patient_id=int(patient_id),
        visit_id=visit_id,
        category=category,
        file_name=original,
        stored_name=stored,
        mime_type=detected,
        size_bytes=size,
        document_date=_parse_date(payload.get("document_date"), "تاريخ المستند") if payload.get("document_date") else None,
        notes=str(payload.get("notes") or "").strip() or None,
        uploaded_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(tenant_id, actor_id, "attachment", row.id, "create", original)
    return attachment_dict(row)


def attachment_path(tenant_id: int, attachment_id: int) -> tuple[ClinicAttachment, str]:
    row = ClinicAttachment.query.filter_by(tenant_id=tenant_id, id=attachment_id).first()
    if not row:
        raise ValueError("المرفق غير موجود")
    path = os.path.join(_uploads_dir(tenant_id), row.stored_name)
    if not os.path.isfile(path):
        raise ValueError("ملف المرفق مفقود")
    return row, path


def consent_dict(row: ClinicConsent) -> dict:
    return {
        "id": row.id,
        "patient_id": row.patient_id,
        "visit_id": row.visit_id,
        "consent_type": row.consent_type,
        "title": row.title,
        "body": row.body or "",
        "signed_name": row.signed_name or "",
        "signed_at": row.signed_at.isoformat() if row.signed_at else "",
        "status": row.status,
    }


def list_consents(tenant_id: int, patient_id: int | None = None) -> list[dict]:
    query = ClinicConsent.query.filter_by(tenant_id=tenant_id)
    if patient_id:
        query = query.filter_by(patient_id=int(patient_id))
    return [consent_dict(r) for r in query.order_by(ClinicConsent.id.desc()).limit(100).all()]


def create_consent(tenant_id: int, payload: dict, actor_id=None) -> dict:
    patient_id = int(payload.get("patient_id") or 0)
    title = str(payload.get("title") or "").strip()
    if not patient_id or not title:
        raise ValueError("المريض وعنوان الموافقة مطلوبان")
    row = ClinicConsent(
        tenant_id=tenant_id,
        patient_id=patient_id,
        visit_id=int(payload["visit_id"]) if payload.get("visit_id") else None,
        consent_type=str(payload.get("consent_type") or "treatment").strip() or "treatment",
        title=title,
        body=str(payload.get("body") or "").strip() or None,
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    return consent_dict(row)


def sign_consent(tenant_id: int, consent_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicConsent.query.filter_by(tenant_id=tenant_id, id=consent_id).first()
    if not row:
        raise ValueError("الموافقة غير موجودة")
    name = str(payload.get("signed_name") or "").strip()
    if not name:
        raise ValueError("اسم الموقّع مطلوب")
    row.signed_name = name
    row.signed_at = datetime.utcnow()
    row.status = "signed"
    return consent_dict(row)


def cash_session_dict(row: ClinicCashSession) -> dict:
    return {
        "id": row.id,
        "business_date": row.business_date.isoformat() if row.business_date else "",
        "opening_cash": row.opening_cash,
        "closing_cash": row.closing_cash,
        "expected_cash": row.expected_cash,
        "cash_collections": row.cash_collections,
        "cash_refunds": row.cash_refunds,
        "cash_expenses": row.cash_expenses,
        "supplier_payments": row.supplier_payments,
        "doctor_payments": row.doctor_payments,
        "other_cash_in": row.other_cash_in,
        "other_cash_out": row.other_cash_out,
        "difference": row.difference,
        "status": row.status,
        "notes": row.notes or "",
        "opened_at": row.opened_at.isoformat() if row.opened_at else "",
        "closed_at": row.closed_at.isoformat() if row.closed_at else "",
    }


def list_cash_sessions(tenant_id: int) -> list[dict]:
    rows = ClinicCashSession.query.filter_by(tenant_id=tenant_id).order_by(ClinicCashSession.id.desc()).limit(50).all()
    return [cash_session_dict(r) for r in rows]


def open_cash_session(tenant_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    open_row = ClinicCashSession.query.filter_by(tenant_id=tenant_id, status="open").first()
    if open_row:
        raise ValueError("هناك جلسة صندوق مفتوحة بالفعل")
    day = _parse_date(payload.get("business_date") or _today().isoformat(), "تاريخ الجلسة")
    row = ClinicCashSession(
        tenant_id=tenant_id,
        branch_id=branch_id,
        business_date=day,
        opening_cash=_money(payload.get("opening_cash")),
        status="open",
        notes=str(payload.get("notes") or "").strip() or None,
        opened_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    return cash_session_dict(row)


def get_clinic_cash_movements(
    tenant_id: int,
    opened_at: datetime,
    closed_at: datetime | None = None,
    *,
    opening_cash: int = 0,
    branch_id=None,
) -> dict:
    """Return the single authoritative clinic cash-drawer breakdown."""
    closed_at = closed_at or datetime.utcnow()
    day_from, day_to = opened_at.date(), closed_at.date()
    branch_payment = [] if branch_id is None else [or_(ClinicPayment.branch_id == branch_id, ClinicPayment.branch_id.is_(None))]
    branch_expense = [] if branch_id is None else [or_(ClinicExpense.branch_id == branch_id, ClinicExpense.branch_id.is_(None))]
    branch_refund = [] if branch_id is None else [or_(ClinicRefund.branch_id == branch_id, ClinicRefund.branch_id.is_(None))]

    collections = db.session.query(db.func.coalesce(db.func.sum(ClinicPayment.amount), 0)).filter(
        ClinicPayment.tenant_id == tenant_id,
        ClinicPayment.method == "cash",
        ClinicPayment.paid_at >= opened_at,
        ClinicPayment.paid_at <= closed_at,
        *branch_payment,
    ).scalar()
    refunds = db.session.query(db.func.coalesce(db.func.sum(ClinicRefund.amount), 0)).filter(
        ClinicRefund.tenant_id == tenant_id,
        ClinicRefund.method == "cash",
        ClinicRefund.refunded_at >= opened_at,
        ClinicRefund.refunded_at <= closed_at,
        *branch_refund,
    ).scalar()
    expenses = db.session.query(db.func.coalesce(db.func.sum(ClinicExpense.amount), 0)).filter(
        ClinicExpense.tenant_id == tenant_id,
        ClinicExpense.payment_method == "cash",
        ClinicExpense.expense_date >= day_from,
        ClinicExpense.expense_date <= day_to,
        *branch_expense,
    ).scalar()
    supplier_filters = [
        ClinicPurchasePayment.tenant_id == tenant_id,
        ClinicPurchasePayment.payment_method == "cash",
        ClinicPurchasePayment.payment_date >= day_from,
        ClinicPurchasePayment.payment_date <= day_to,
    ]
    supplier_query = db.session.query(db.func.coalesce(db.func.sum(ClinicPurchasePayment.amount), 0))
    if branch_id is not None:
        supplier_query = supplier_query.join(ClinicPurchase, ClinicPurchase.id == ClinicPurchasePayment.purchase_id)
        supplier_filters.extend((
            ClinicPurchase.tenant_id == tenant_id,
            or_(ClinicPurchase.branch_id == branch_id, ClinicPurchase.branch_id.is_(None)),
        ))
    supplier_payments = supplier_query.filter(*supplier_filters).scalar()
    doctor_payments = db.session.query(db.func.coalesce(db.func.sum(ClinicDoctorSettlement.paid_amount), 0)).filter(
        ClinicDoctorSettlement.tenant_id == tenant_id,
        ClinicDoctorSettlement.payment_method == "cash",
        ClinicDoctorSettlement.created_at >= opened_at,
        ClinicDoctorSettlement.created_at <= closed_at,
    ).scalar()
    values = {
        "opening_cash": int(opening_cash or 0),
        "patient_cash_collections": int(collections or 0),
        "patient_cash_refunds": int(refunds or 0),
        "cash_expenses": int(expenses or 0),
        "supplier_cash_payments": int(supplier_payments or 0),
        "doctor_cash_payments": int(doctor_payments or 0),
        "other_cash_in": 0,
        "other_cash_out": 0,
    }
    values["expected_cash"] = (
        values["opening_cash"] + values["patient_cash_collections"] + values["other_cash_in"]
        - values["patient_cash_refunds"] - values["cash_expenses"]
        - values["supplier_cash_payments"] - values["doctor_cash_payments"] - values["other_cash_out"]
    )
    return values


def close_cash_session(tenant_id: int, session_id: int, payload: dict, actor_id=None) -> dict:
    row = ClinicCashSession.query.filter_by(tenant_id=tenant_id, id=session_id, status="open").first()
    if not row:
        raise ValueError("جلسة الصندوق غير موجودة أو مغلقة")
    closed_at = datetime.utcnow()
    movements = get_clinic_cash_movements(
        tenant_id, row.opened_at, closed_at,
        opening_cash=row.opening_cash, branch_id=row.branch_id,
    )
    expected = movements["expected_cash"]
    row.expected_cash = expected
    row.closing_cash = _money(payload.get("closing_cash") if payload.get("closing_cash") is not None else expected)
    row.cash_collections = movements["patient_cash_collections"]
    row.cash_refunds = movements["patient_cash_refunds"]
    row.cash_expenses = movements["cash_expenses"]
    row.supplier_payments = movements["supplier_cash_payments"]
    row.doctor_payments = movements["doctor_cash_payments"]
    row.other_cash_in = movements["other_cash_in"]
    row.other_cash_out = movements["other_cash_out"]
    row.difference = int(row.closing_cash or 0) - expected
    row.status = "closed"
    row.closed_at = closed_at
    row.closed_by = actor_id
    row.notes = str(payload.get("notes") or row.notes or "").strip() or None
    return cash_session_dict(row)


def seed_specialty_pack(tenant_id: int, clinic_type: str | None = None, actor_id=None) -> dict:
    """Legacy service/procedure/lab seed packs. Does not change organization_mode.

    Prefer ClinicSpecialty + /api/specialty/seed for new tenants. clinic_type here
    is only a pack key (dental, pediatrics, …), never facility shape.
    """
    settings = get_or_create_settings(tenant_id, actor_id)
    legacy_org = {"single_doctor", "multi_doctor", "medical_center"}
    ctype = str(clinic_type or settings.clinic_type or "general_practice").strip()
    if ctype in legacy_org or ctype not in SPECIALTY_PACKS:
        ctype = "general_practice"
    pack = SPECIALTY_PACKS.get(ctype) or SPECIALTY_PACKS["general_practice"]
    created = {"services": 0, "procedures": 0, "labs": 0}
    for name, category, duration, price in pack.get("services", []):
        exists = ClinicService.query.filter_by(tenant_id=tenant_id, name=name).first()
        if exists:
            continue
        db.session.add(
            ClinicService(
                tenant_id=tenant_id,
                name=name,
                category=category,
                duration_minutes=duration,
                price=price,
                active=True,
                created_by=actor_id,
            )
        )
        created["services"] += 1
    for name, price in pack.get("procedures", []):
        if ClinicProcedure.query.filter_by(tenant_id=tenant_id, name=name).first():
            continue
        db.session.add(
            ClinicProcedure(tenant_id=tenant_id, name=name, price=price, active=True, created_by=actor_id)
        )
        created["procedures"] += 1
    for name, category, price in pack.get("labs", []):
        if ClinicLabTest.query.filter_by(tenant_id=tenant_id, name=name).first():
            continue
        db.session.add(
            ClinicLabTest(
                tenant_id=tenant_id,
                name=name,
                category=category,
                price=price,
                active=True,
                created_by=actor_id,
            )
        )
        created["labs"] += 1
    # Store pack hint only when it is a specialty-like key; never overwrite org mode.
    if ctype not in legacy_org:
        settings.clinic_type = ctype
    settings.specialty_pack_seeded = True
    db.session.flush()
    return {"clinic_type": ctype, "created": created, "organization_mode": getattr(settings, "organization_mode", "solo_clinic")}


def _otp_secret() -> str:
    return str(current_app.config.get("SECRET_KEY") or "finora-clinics")


def _hash_otp(phone: str, code: str) -> str:
    raw = f"{phone}:{code}".encode("utf-8")
    return hmac.new(_otp_secret().encode("utf-8"), raw, hashlib.sha256).hexdigest()


def request_booking_otp(tenant_id: int, phone: str) -> dict:
    settings = get_or_create_settings(tenant_id)
    if not settings.booking_otp_enabled:
        return {"required": False}
    phone = str(phone or "").strip()
    if len(phone) < 8:
        raise ValueError("رقم الهاتف غير صالح")
    code = f"{secrets.randbelow(1000000):06d}"
    row = ClinicBookingOtp(
        tenant_id=tenant_id,
        phone=phone,
        code_hash=_hash_otp(phone, code),
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    )
    db.session.add(row)
    db.session.flush()
    # Prefer WhatsApp delivery when enabled; always return masked hint.
    delivered = False
    try:
        if settings.whatsapp_notifications_enabled:
            from modules.clinics.service_comms import send_whatsapp

            send_whatsapp(
                tenant_id,
                phone,
                f"رمز التحقق لحجز موعدك في العيادة: {code}",
                template_key="booking_otp",
            )
            delivered = True
    except Exception:
        delivered = False
    result = {"required": True, "expires_in_seconds": 600, "delivered": delivered}
    # In non-production or when WhatsApp unavailable, expose code for testing via debug flag only
    if current_app.debug or not delivered:
        result["debug_code"] = code
    return result


def verify_booking_otp(tenant_id: int, phone: str, code: str) -> bool:
    settings = get_or_create_settings(tenant_id)
    if not settings.booking_otp_enabled:
        return True
    phone = str(phone or "").strip()
    code = str(code or "").strip()
    row = (
        ClinicBookingOtp.query.filter_by(tenant_id=tenant_id, phone=phone)
        .order_by(ClinicBookingOtp.id.desc())
        .first()
    )
    if not row or row.expires_at < datetime.utcnow():
        raise ValueError("رمز التحقق منتهي أو غير موجود")
    if row.attempts >= 5:
        raise ValueError("تم تجاوز محاولات التحقق")
    row.attempts += 1
    if not hmac.compare_digest(row.code_hash, _hash_otp(phone, code)):
        raise ValueError("رمز التحقق غير صحيح")
    row.verified_at = datetime.utcnow()
    return True


def booking_qr_payload(tenant_slug: str, base_url: str = "", doctor_id=None, service_id=None) -> dict:
    path = f"/c/{tenant_slug}"
    params = []
    if doctor_id:
        params.append(f"doctor={int(doctor_id)}")
    if service_id:
        params.append(f"service={int(service_id)}")
    if params:
        path = f"{path}?{'&'.join(params)}"
    url = f"{base_url.rstrip('/')}{path}" if base_url else path
    # External QR image API keeps dependency surface zero; URL remains primary.
    qr_image = f"https://api.qrserver.com/v1/create-qr-code/?size=240x240&data={quote(url, safe='')}"
    return {"url": url, "path": path, "qr_image": qr_image}
