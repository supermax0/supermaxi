"""Purchase requests, returns, attachments, and reports for clinic purchasing."""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, or_
from werkzeug.utils import secure_filename

from extensions import db
from models.employee import Employee
from modules.clinics.models import (
    ClinicInventoryBatch,
    ClinicInventoryItem,
    ClinicInventoryMovement,
    ClinicPurchase,
    ClinicPurchaseAttachment,
    ClinicPurchaseItem,
    ClinicPurchaseRequest,
    ClinicPurchaseRequestItem,
    ClinicPurchaseReturn,
    ClinicPurchaseReturnItem,
)
from modules.clinics.service import _audit, _money, _parse_date, _today
from modules.clinics.service_ops import stock_out_fefo
from modules.clinics.service_suppliers import _employee_name, _qty, create_purchase, purchase_dict

RETURN_REASONS = {
    "expiring": "منتهي أو قريب الانتهاء",
    "damaged": "تالف",
    "mismatch": "غير مطابق",
    "excess": "كمية زائدة",
    "order_error": "خطأ في الطلب",
    "batch_issue": "مشكلة في Batch",
    "other": "أخرى",
}

REQUEST_STATUSES = {
    "draft": "مسودة",
    "pending": "بانتظار الموافقة",
    "approved": "معتمد",
    "rejected": "مرفوض",
    "converted": "تم التحويل إلى شراء",
}

PRIORITY_LABELS = {"low": "منخفضة", "normal": "عادية", "high": "عالية", "urgent": "عاجلة"}

ALLOWED_PURCHASE_MIMES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_PURCHASE_ATTACHMENT_BYTES = 25 * 1024 * 1024
ATTACHMENT_CATEGORIES = ("invoice", "delivery_note", "credit_note", "receipt", "other")


def _uploads_dir(tenant_id: int) -> str:
    from flask import current_app

    base = os.path.join(current_app.instance_path, "clinic_uploads", str(tenant_id), "purchases")
    os.makedirs(base, exist_ok=True)
    return base


def _next_request_number(tenant_id: int) -> str:
    year = _today().year
    count = ClinicPurchaseRequest.query.filter_by(tenant_id=tenant_id).count() + 1
    return f"PRQ-{year}-{count:04d}"


def _next_return_number(tenant_id: int) -> str:
    count = ClinicPurchaseReturn.query.filter_by(tenant_id=tenant_id).count() + 1
    return f"RET-{count:05d}"


def _request_item_dict(row: ClinicPurchaseRequestItem, tenant_id: int) -> dict:
    item = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=row.item_id).first()
    return {
        "id": row.id,
        "item_id": row.item_id,
        "item_name": item.name if item else "",
        "unit": item.unit if item else "",
        "quantity": float(row.quantity or 0),
        "reason": row.reason or "",
        "notes": row.notes or "",
        "current_stock": float(item.current_stock or 0) if item else 0,
        "minimum_stock": float(item.minimum_stock or 0) if item else 0,
        "suggested_reorder_qty": float(item.suggested_reorder_qty or 0) if item else 0,
        "default_supplier_id": item.default_supplier_id if item else None,
    }


def request_dict(row: ClinicPurchaseRequest, tenant_id: int) -> dict:
    items = ClinicPurchaseRequestItem.query.filter_by(tenant_id=tenant_id, request_id=row.id).all()
    return {
        "id": row.id,
        "request_number": row.request_number,
        "status": row.status,
        "status_label": REQUEST_STATUSES.get(row.status, row.status),
        "priority": row.priority,
        "priority_label": PRIORITY_LABELS.get(row.priority, row.priority),
        "notes": row.notes or "",
        "purchase_id": row.purchase_id,
        "created_by": row.created_by,
        "created_by_name": _employee_name(row.created_by),
        "approved_by_name": _employee_name(row.approved_by),
        "approved_at": row.approved_at.isoformat() if row.approved_at else "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "items": [_request_item_dict(it, tenant_id) for it in items],
    }


def list_purchase_requests(tenant_id: int, args: dict | None = None) -> list[dict]:
    args = args or {}
    query = ClinicPurchaseRequest.query.filter_by(tenant_id=tenant_id)
    status = args.get("status")
    if status:
        query = query.filter(ClinicPurchaseRequest.status == status)
    rows = query.order_by(ClinicPurchaseRequest.id.desc()).limit(100).all()
    return [request_dict(r, tenant_id) for r in rows]


def create_purchase_request(tenant_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    items = payload.get("items") or []
    if not items:
        raise ValueError("أضف صنفاً واحداً على الأقل")
    status = str(payload.get("status") or "pending").strip()
    if status not in REQUEST_STATUSES:
        status = "pending"
    row = ClinicPurchaseRequest(
        tenant_id=tenant_id,
        branch_id=branch_id,
        request_number=_next_request_number(tenant_id),
        status=status,
        priority=str(payload.get("priority") or "normal"),
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    added = 0
    for line in items:
        item_id = int(line.get("item_id") or 0)
        qty = float(line.get("quantity") or 0)
        if qty <= 0:
            continue
        if not ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=item_id).first():
            raise ValueError("صنف المخزون غير موجود")
        db.session.add(
            ClinicPurchaseRequestItem(
                tenant_id=tenant_id,
                request_id=row.id,
                item_id=item_id,
                quantity=qty,
                reason=str(line.get("reason") or "").strip() or None,
                notes=str(line.get("notes") or "").strip() or None,
            )
        )
        added += 1
    if not added:
        raise ValueError("لا توجد بنود صالحة")
    _audit(tenant_id, actor_id, "purchase_request", row.id, "create", f"طلب شراء {row.request_number}", branch_id=branch_id)
    return request_dict(row, tenant_id)


def update_purchase_request_status(
    tenant_id: int, request_id: int, status: str, actor_id=None, *, reject_reason: str = ""
) -> dict:
    row = ClinicPurchaseRequest.query.filter_by(tenant_id=tenant_id, id=request_id).with_for_update().first()
    if not row:
        raise ValueError("طلب الشراء غير موجود")
    status = str(status or "").strip()
    if status not in ("approved", "rejected", "pending"):
        raise ValueError("حالة غير صالحة")
    if row.status in ("converted", "rejected"):
        raise ValueError("لا يمكن تعديل هذا الطلب")
    row.status = status
    row.updated_at = datetime.utcnow()
    if status == "approved":
        row.approved_by = actor_id
        row.approved_at = datetime.utcnow()
    if status == "rejected" and reject_reason:
        row.notes = ((row.notes or "") + f"\nسبب الرفض: {reject_reason}").strip()
    _audit(tenant_id, actor_id, "purchase_request", row.id, status, f"تحديث طلب {row.request_number}")
    db.session.flush()
    return request_dict(row, tenant_id)


def convert_request_to_purchase(tenant_id: int, request_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    row = ClinicPurchaseRequest.query.filter_by(tenant_id=tenant_id, id=request_id).with_for_update().first()
    if not row:
        raise ValueError("طلب الشراء غير موجود")
    if row.status not in ("approved", "pending"):
        raise ValueError("يجب اعتماد الطلب قبل التحويل")
    if row.purchase_id:
        raise ValueError("تم تحويل هذا الطلب مسبقاً")
    supplier_id = int(payload.get("supplier_id") or 0)
    if not supplier_id:
        raise ValueError("المورد مطلوب للتحويل")
    items = ClinicPurchaseRequestItem.query.filter_by(tenant_id=tenant_id, request_id=row.id).all()
    purchase_items = []
    for it in items:
        inv = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=it.item_id).first()
        purchase_items.append({
            "item_id": it.item_id,
            "quantity": float(it.quantity or 0),
            "unit_cost": inv.last_purchase_cost or inv.average_cost or inv.purchase_price or 0 if inv else 0,
        })
    purchase = create_purchase(
        tenant_id,
        {
            "supplier_id": supplier_id,
            "purchase_date": payload.get("purchase_date") or _today().isoformat(),
            "notes": f"من طلب شراء {row.request_number}",
            "items": purchase_items,
            "invoice_status": "approved",
        },
        actor_id,
        branch_id,
    )
    row.status = "converted"
    row.purchase_id = purchase["id"]
    row.updated_at = datetime.utcnow()
    _audit(tenant_id, actor_id, "purchase_request", row.id, "convert", f"تحويل إلى {purchase['purchase_number']}")
    db.session.flush()
    return {"request": request_dict(row, tenant_id), "purchase": purchase}


def reorder_suggestions(tenant_id: int) -> list[dict]:
    rows = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, active=True).all()
    result = []
    for item in rows:
        available = float(item.current_stock or 0)
        reorder = float(item.reorder_point or item.minimum_stock or 0)
        if reorder <= 0:
            continue
        if available > reorder:
            continue
        suggested = float(item.suggested_reorder_qty or 0)
        if suggested <= 0:
            suggested = max(reorder * 2 - available, reorder)
        result.append({
            "item_id": item.id,
            "item_name": item.name,
            "unit": item.unit,
            "current_stock": available,
            "reorder_point": reorder,
            "suggested_qty": suggested,
            "default_supplier_id": item.default_supplier_id,
            "last_purchase_cost": item.last_purchase_cost or item.average_cost or 0,
        })
    return sorted(result, key=lambda x: x["current_stock"] - x["reorder_point"])


def _return_dict(row: ClinicPurchaseReturn, tenant_id: int) -> dict:
    items = ClinicPurchaseReturnItem.query.filter_by(tenant_id=tenant_id, return_id=row.id).all()
    item_rows = []
    for it in items:
        inv = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=it.item_id).first()
        item_rows.append({
            "id": it.id,
            "item_id": it.item_id,
            "item_name": inv.name if inv else "",
            "batch_number": it.batch_number or "",
            "quantity": float(it.quantity or 0),
            "unit_cost": it.unit_cost,
            "line_total": it.line_total,
            "reason": it.reason or "",
            "reason_label": RETURN_REASONS.get(it.reason or "", it.reason or ""),
        })
    return {
        "id": row.id,
        "return_number": row.return_number,
        "purchase_id": row.purchase_id,
        "supplier_id": row.supplier_id,
        "return_date": row.return_date.isoformat(),
        "status": row.status,
        "total_value": row.total_value,
        "notes": row.notes or "",
        "created_by_name": _employee_name(row.created_by),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "items": item_rows,
    }


def list_purchase_returns(tenant_id: int, purchase_id: int) -> list[dict]:
    rows = (
        ClinicPurchaseReturn.query.filter_by(tenant_id=tenant_id, purchase_id=purchase_id)
        .order_by(ClinicPurchaseReturn.id.desc())
        .all()
    )
    return [_return_dict(r, tenant_id) for r in rows]


def create_purchase_return(tenant_id: int, purchase_id: int, payload: dict, actor_id=None, branch_id=None) -> dict:
    purchase = ClinicPurchase.query.filter_by(tenant_id=tenant_id, id=purchase_id).with_for_update().first()
    if not purchase:
        raise ValueError("فاتورة الشراء غير موجودة")
    if purchase.invoice_status == "cancelled":
        raise ValueError("لا يمكن إرجاع فاتورة ملغاة")
    lines = payload.get("items") or []
    if not lines:
        raise ValueError("أضف بنود المرتجع")

    purchase_items = {
        row.id: row
        for row in ClinicPurchaseItem.query.filter_by(tenant_id=tenant_id, purchase_id=purchase.id).with_for_update().all()
    }
    ret = ClinicPurchaseReturn(
        tenant_id=tenant_id,
        branch_id=branch_id,
        purchase_id=purchase.id,
        supplier_id=purchase.supplier_id,
        return_number=_next_return_number(tenant_id),
        return_date=_parse_date(payload.get("return_date") or _today().isoformat(), "تاريخ المرتجع"),
        notes=str(payload.get("notes") or "").strip() or None,
        created_by=actor_id,
    )
    db.session.add(ret)
    db.session.flush()
    total_value = 0
    returned_any = False

    for raw in lines:
        purchase_item = purchase_items.get(int(raw.get("purchase_item_id") or 0))
        if not purchase_item:
            raise ValueError("بند الشراء غير صالح")
        qty = _qty(raw.get("quantity"))
        if qty <= 0:
            continue
        received = _qty(purchase_item.received_quantity)
        already_returned = _qty(purchase_item.returned_quantity)
        max_return = received - already_returned
        if qty > max_return:
            raise ValueError("كمية المرتجع أكبر من المستلم غير المرتجع")
        unit_cost = int(raw.get("unit_cost") or purchase_item.unit_cost or 0)
        line_total = int(round(float(qty) * unit_cost))
        reason = str(raw.get("reason") or "other").strip()
        if reason not in RETURN_REASONS:
            reason = "other"
        batch_number = str(raw.get("batch_number") or "").strip() or None
        batch_id = int(raw.get("batch_id") or 0) or None

        stock_out_fefo(
            tenant_id,
            purchase_item.item_id,
            qty,
            reference_type="purchase_return",
            reference_id=ret.id,
            actor_id=actor_id,
            notes=f"مرتجع {ret.return_number} — {RETURN_REASONS.get(reason, reason)}",
        )
        purchase_item.returned_quantity = already_returned + qty
        db.session.add(
            ClinicPurchaseReturnItem(
                tenant_id=tenant_id,
                return_id=ret.id,
                purchase_item_id=purchase_item.id,
                item_id=purchase_item.item_id,
                batch_id=batch_id,
                batch_number=batch_number,
                quantity=qty,
                unit_cost=unit_cost,
                line_total=line_total,
                reason=reason,
            )
        )
        total_value += line_total
        returned_any = True

    if not returned_any:
        raise ValueError("لا توجد كمية صالحة للمرتجع")

    ret.total_value = total_value
    purchase.return_total = int(purchase.return_total or 0) + total_value
    purchase.balance = max(0, int(purchase.balance or 0) - total_value)
    purchase.total = max(0, int(purchase.total or 0) - total_value)
    purchase.updated_at = datetime.utcnow()
    try:
        from flask import request

        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    except RuntimeError:
        ip = ""
    _audit(
        tenant_id,
        actor_id,
        "purchase_return",
        ret.id,
        "create",
        f"مرتجع {ret.return_number}",
        meta={"purchase_id": purchase_id, "ip": ip, "new_values": {"total_value": total_value}},
        branch_id=branch_id,
    )
    db.session.flush()
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    ClinicAccountingPostingService.post_clinic_purchase_return(ret.id, tenant_id, actor_id)
    return _return_dict(ret, tenant_id)


def attachment_dict(row: ClinicPurchaseAttachment) -> dict:
    return {
        "id": row.id,
        "purchase_id": row.purchase_id,
        "category": row.category,
        "file_name": row.file_name,
        "mime_type": row.mime_type or "",
        "size_bytes": row.size_bytes,
        "notes": row.notes or "",
        "uploaded_by_name": _employee_name(row.uploaded_by),
        "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else "",
    }


def list_purchase_attachments(tenant_id: int, purchase_id: int) -> list[dict]:
    rows = (
        ClinicPurchaseAttachment.query.filter_by(tenant_id=tenant_id, purchase_id=purchase_id)
        .order_by(ClinicPurchaseAttachment.id.desc())
        .all()
    )
    return [attachment_dict(r) for r in rows]


def save_purchase_attachment(tenant_id: int, purchase_id: int, file_storage, payload: dict, actor_id=None) -> dict:
    purchase = ClinicPurchase.query.filter_by(tenant_id=tenant_id, id=purchase_id).first()
    if not purchase:
        raise ValueError("فاتورة الشراء غير موجودة")
    if not file_storage or not getattr(file_storage, "filename", None):
        raise ValueError("الملف مطلوب")
    original = secure_filename(file_storage.filename) or "file"
    ext = os.path.splitext(original)[1].lower()
    mime = None
    for candidate, suffix in ALLOWED_PURCHASE_MIMES.items():
        if ext == suffix or (ext == ".jpeg" and suffix == ".jpg"):
            mime = candidate
            break
    if not mime:
        raise ValueError("نوع الملف غير مسموح (PDF أو صورة)")
    stored = f"{uuid.uuid4().hex}{ALLOWED_PURCHASE_MIMES[mime]}"
    dest = os.path.join(_uploads_dir(tenant_id), stored)
    file_storage.save(dest)
    size = os.path.getsize(dest)
    if size <= 0 or size > MAX_PURCHASE_ATTACHMENT_BYTES:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise ValueError("حجم الملف يجب ألا يتجاوز 25 MB")
    category = str(payload.get("category") or "invoice").strip()
    if category not in ATTACHMENT_CATEGORIES:
        category = "other"
    row = ClinicPurchaseAttachment(
        tenant_id=tenant_id,
        purchase_id=purchase_id,
        category=category,
        file_name=original,
        stored_name=stored,
        mime_type=mime,
        size_bytes=size,
        notes=str(payload.get("notes") or "").strip() or None,
        uploaded_by=actor_id,
    )
    db.session.add(row)
    db.session.flush()
    _audit(tenant_id, actor_id, "purchase_attachment", row.id, "create", original)
    return attachment_dict(row)


def purchase_attachment_path(tenant_id: int, attachment_id: int) -> tuple[ClinicPurchaseAttachment, str]:
    row = ClinicPurchaseAttachment.query.filter_by(tenant_id=tenant_id, id=attachment_id).first()
    if not row:
        raise ValueError("المرفق غير موجود")
    path = os.path.join(_uploads_dir(tenant_id), row.stored_name)
    if not os.path.isfile(path):
        raise ValueError("ملف المرفق مفقود")
    return row, path


def list_purchase_movements(tenant_id: int, purchase_id: int) -> list[dict]:
    from modules.clinics.models import ClinicPurchaseReceipt

    receipt_ids = [r.id for r in ClinicPurchaseReceipt.query.filter_by(tenant_id=tenant_id, purchase_id=purchase_id).all()]
    return_ids = [r.id for r in ClinicPurchaseReturn.query.filter_by(tenant_id=tenant_id, purchase_id=purchase_id).all()]
    filters = []
    if receipt_ids:
        filters.append(
            (ClinicInventoryMovement.reference_type == "purchase_receipt") & (ClinicInventoryMovement.reference_id.in_(receipt_ids))
        )
    if return_ids:
        filters.append(
            (ClinicInventoryMovement.reference_type == "purchase_return") & (ClinicInventoryMovement.reference_id.in_(return_ids))
        )
    item_ids = [pi.item_id for pi in ClinicPurchaseItem.query.filter_by(tenant_id=tenant_id, purchase_id=purchase_id).all()]
    if item_ids:
        filters.append(
            (ClinicInventoryMovement.reference_type == "purchase") & (ClinicInventoryMovement.item_id.in_(item_ids))
        )
    if not filters:
        return []
    rows = (
        ClinicInventoryMovement.query.filter_by(tenant_id=tenant_id)
        .filter(or_(*filters))
        .order_by(ClinicInventoryMovement.id.desc())
        .limit(100)
        .all()
    )
    result = []
    for row in rows:
        item = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=row.item_id).first()
        result.append({
            "id": row.id,
            "item_name": item.name if item else "",
            "movement_type": row.movement_type,
            "quantity": float(row.quantity or 0),
            "unit_cost": row.unit_cost,
            "reason": row.reason or "",
            "reference_type": row.reference_type or "",
            "notes": row.notes or "",
            "created_at": row.created_at.isoformat() if row.created_at else "",
        })
    return result


def purchase_report_summary(tenant_id: int, args: dict | None = None) -> dict:
    args = args or {}
    today = _today()
    month_start = today.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    base = ClinicPurchase.query.filter_by(tenant_id=tenant_id).filter(ClinicPurchase.invoice_status != "cancelled")
    month_purchases = base.filter(ClinicPurchase.purchase_date >= month_start).all()
    last_month_purchases = base.filter(
        ClinicPurchase.purchase_date >= last_month_start,
        ClinicPurchase.purchase_date <= last_month_end,
    ).all()

    month_total = sum(p.total or 0 for p in month_purchases)
    last_month_total = sum(p.total or 0 for p in last_month_purchases)

    supplier_totals: dict[int, int] = {}
    item_totals: dict[int, int] = {}
    for p in month_purchases:
        supplier_totals[p.supplier_id] = supplier_totals.get(p.supplier_id, 0) + int(p.total or 0)
        for it in ClinicPurchaseItem.query.filter_by(tenant_id=tenant_id, purchase_id=p.id).all():
            item_totals[it.item_id] = item_totals.get(it.item_id, 0) + int(it.line_total or 0)

    from modules.clinics.models import ClinicSupplier

    top_supplier = None
    if supplier_totals:
        sid = max(supplier_totals, key=supplier_totals.get)
        sup = ClinicSupplier.query.filter_by(tenant_id=tenant_id, id=sid).first()
        top_supplier = {"id": sid, "name": sup.name if sup else "", "total": supplier_totals[sid]}

    top_item = None
    if item_totals:
        iid = max(item_totals, key=item_totals.get)
        inv = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=iid).first()
        top_item = {"id": iid, "name": inv.name if inv else "", "total": item_totals[iid]}

    open_balance = sum(p.balance or 0 for p in base.all())
    pending_receipt = base.filter(ClinicPurchase.receipt_status == "pending").count()

    return {
        "month_total": month_total,
        "last_month_total": last_month_total,
        "month_change_pct": round(((month_total - last_month_total) / last_month_total) * 100, 1) if last_month_total else None,
        "top_supplier": top_supplier,
        "top_item": top_item,
        "supplier_payable": open_balance,
        "pending_receipt_count": pending_receipt,
        "purchase_count_month": len(month_purchases),
    }


def enrich_purchase_detail(tenant_id: int, data: dict) -> dict:
    purchase_id = data["id"]
    data["returns"] = list_purchase_returns(tenant_id, purchase_id)
    data["attachments"] = list_purchase_attachments(tenant_id, purchase_id)
    data["movements"] = list_purchase_movements(tenant_id, purchase_id)
    data["return_total"] = data.get("return_total", 0)
    return data


def _purchase_settings(tenant_id: int) -> dict:
    from modules.clinics.models import ClinicSettings

    row = ClinicSettings.query.filter_by(tenant_id=tenant_id).first()
    return {
        "warn_expiry_days": int(getattr(row, "purchase_warn_expiry_days", None) or 90),
        "price_warn_pct": int(getattr(row, "purchase_price_warn_pct", None) or 20),
        "approval_limit": int(getattr(row, "purchase_approval_limit", None) or 500000),
        "owner_approval_limit": int(getattr(row, "purchase_owner_approval_limit", None) or 5000000),
    }


def item_purchase_price_history(tenant_id: int, item_id: int | None = None, limit: int = 30) -> list[dict]:
    from modules.clinics.models import ClinicPurchase, ClinicSupplier

    query = (
        db.session.query(ClinicPurchaseItem, ClinicPurchase)
        .join(ClinicPurchase, ClinicPurchase.id == ClinicPurchaseItem.purchase_id)
        .filter(ClinicPurchaseItem.tenant_id == tenant_id, ClinicPurchase.invoice_status != "cancelled")
    )
    if item_id:
        query = query.filter(ClinicPurchaseItem.item_id == int(item_id))
    rows = query.order_by(ClinicPurchase.purchase_date.desc(), ClinicPurchase.id.desc()).limit(limit).all()
    result = []
    for pit, pur in rows:
        inv = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=pit.item_id).first()
        sup = ClinicSupplier.query.filter_by(tenant_id=tenant_id, id=pur.supplier_id).first()
        result.append({
            "purchase_id": pur.id,
            "purchase_number": pur.purchase_number,
            "purchase_date": pur.purchase_date.isoformat(),
            "item_id": pit.item_id,
            "item_name": inv.name if inv else "",
            "supplier_id": pur.supplier_id,
            "supplier_name": sup.name if sup else "",
            "quantity": float(pit.quantity or 0),
            "unit_cost": pit.unit_cost,
            "line_total": pit.line_total,
        })
    return result


def check_price_warnings(tenant_id: int, items: list[dict]) -> list[dict]:
    settings = _purchase_settings(tenant_id)
    threshold_pct = settings["price_warn_pct"]
    warnings = []
    for line in items:
        item_id = int(line.get("item_id") or 0)
        new_cost = int(line.get("unit_cost") or 0)
        if not item_id or new_cost <= 0:
            continue
        inv = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=item_id).first()
        last_cost = int(inv.last_purchase_cost or inv.average_cost or 0) if inv else 0
        if not last_cost:
            hist = item_purchase_price_history(tenant_id, item_id, limit=1)
            if hist:
                last_cost = int(hist[0]["unit_cost"] or 0)
        if last_cost <= 0 or new_cost <= last_cost:
            continue
        pct = round(((new_cost - last_cost) / last_cost) * 100, 1)
        if pct >= threshold_pct:
            warnings.append({
                "item_id": item_id,
                "item_name": inv.name if inv else "",
                "last_cost": last_cost,
                "new_cost": new_cost,
                "increase_pct": pct,
                "message": f"سعر {inv.name if inv else 'الصنف'} أعلى بـ{pct}% من آخر شراء ({last_cost:,} → {new_cost:,} د.ع)",
            })
    return warnings


def validate_receive_expiry(tenant_id: int, items: list[dict]) -> dict:
    settings = _purchase_settings(tenant_id)
    warn_days = settings["warn_expiry_days"]
    warnings = []
    blocked = []
    today = _today()
    for line in items:
        expiry_raw = line.get("expiry_date")
        if not expiry_raw:
            continue
        try:
            expiry = _parse_date(expiry_raw, "تاريخ الانتهاء")
        except ValueError:
            continue
        item_id = int(line.get("item_id") or 0)
        inv = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=item_id).first() if item_id else None
        name = inv.name if inv else "صنف"
        days_left = (expiry - today).days
        if days_left < 0:
            blocked.append({"item_id": item_id, "item_name": name, "days_left": days_left, "message": f"لا يمكن استلام دفعة منتهية: {name}"})
        elif days_left <= warn_days:
            warnings.append({"item_id": item_id, "item_name": name, "days_left": days_left, "message": f"{name} ينتهي خلال {days_left} يوماً"})
    return {"warnings": warnings, "blocked": blocked, "warn_days": warn_days}


def purchase_reports_by_supplier(tenant_id: int, args: dict | None = None) -> list[dict]:
    from modules.clinics.models import ClinicSupplier
    from datetime import timedelta

    args = args or {}
    today = _today()
    start = _parse_date(args.get("date_from"), "من") if args.get("date_from") else today.replace(day=1)
    end = _parse_date(args.get("date_to"), "إلى") if args.get("date_to") else today
    rows = (
        ClinicPurchase.query.filter_by(tenant_id=tenant_id)
        .filter(ClinicPurchase.invoice_status != "cancelled")
        .filter(ClinicPurchase.purchase_date >= start, ClinicPurchase.purchase_date <= end)
        .all()
    )
    totals: dict[int, dict] = {}
    for p in rows:
        bucket = totals.setdefault(p.supplier_id, {"total": 0, "count": 0, "balance": 0})
        bucket["total"] += int(p.total or 0)
        bucket["count"] += 1
        bucket["balance"] += int(p.balance or 0)
    result = []
    for sid, agg in sorted(totals.items(), key=lambda x: x[1]["total"], reverse=True):
        sup = ClinicSupplier.query.filter_by(tenant_id=tenant_id, id=sid).first()
        result.append({"supplier_id": sid, "supplier_name": sup.name if sup else "", **agg})
    return result


def purchase_reports_unpaid(tenant_id: int) -> list[dict]:
    from modules.clinics.models import ClinicSupplier

    rows = (
        ClinicPurchase.query.filter_by(tenant_id=tenant_id)
        .filter(ClinicPurchase.invoice_status != "cancelled")
        .filter(ClinicPurchase.balance > 0)
        .order_by(ClinicPurchase.id.desc())
        .all()
    )
    rows.sort(key=lambda p: (p.due_date or date.max, -p.id))
    result = []
    for p in rows:
        sup = ClinicSupplier.query.filter_by(tenant_id=tenant_id, id=p.supplier_id).first()
        result.append({
            "id": p.id,
            "purchase_number": p.purchase_number,
            "supplier_name": sup.name if sup else "",
            "purchase_date": p.purchase_date.isoformat(),
            "due_date": p.due_date.isoformat() if p.due_date else "",
            "total": p.total,
            "paid": p.paid,
            "balance": p.balance,
            "payment_status": p.payment_status,
        })
    return result


def get_purchase_return_print(tenant_id: int, purchase_id: int, return_id: int) -> dict:
    row = ClinicPurchaseReturn.query.filter_by(
        tenant_id=tenant_id, purchase_id=purchase_id, id=return_id
    ).first()
    if not row:
        raise ValueError("سند المرتجع غير موجود")
    data = _return_dict(row, tenant_id)
    from modules.clinics.service_suppliers import get_purchase

    purchase = get_purchase(tenant_id, purchase_id)
    data["purchase_number"] = purchase["purchase_number"]
    data["supplier_name"] = purchase["supplier_name"]
    data["supplier_invoice_no"] = purchase.get("supplier_invoice_no") or ""
    return data


def purchase_reports_by_item(tenant_id: int, args: dict | None = None) -> list[dict]:
    from modules.clinics.models import ClinicPurchase

    args = args or {}
    today = _today()
    start = _parse_date(args.get("date_from"), "من") if args.get("date_from") else today.replace(day=1)
    end = _parse_date(args.get("date_to"), "إلى") if args.get("date_to") else today
    totals: dict[int, dict] = {}
    purchases = (
        ClinicPurchase.query.filter_by(tenant_id=tenant_id)
        .filter(ClinicPurchase.invoice_status != "cancelled")
        .filter(ClinicPurchase.purchase_date >= start, ClinicPurchase.purchase_date <= end)
        .all()
    )
    for p in purchases:
        for pit in ClinicPurchaseItem.query.filter_by(tenant_id=tenant_id, purchase_id=p.id).all():
            bucket = totals.setdefault(pit.item_id, {"quantity": 0.0, "total": 0})
            bucket["quantity"] += float(pit.quantity or 0)
            bucket["total"] += int(pit.line_total or 0)
    result = []
    for iid, agg in sorted(totals.items(), key=lambda x: x[1]["total"], reverse=True):
        inv = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=iid).first()
        result.append({
            "item_id": iid,
            "item_name": inv.name if inv else "",
            "category": inv.category if inv else "",
            "quantity": agg["quantity"],
            "total": agg["total"],
        })
    return result


def purchase_reports_by_category(tenant_id: int, args: dict | None = None) -> list[dict]:
    by_item = purchase_reports_by_item(tenant_id, args)
    totals: dict[str, dict] = {}
    for row in by_item:
        cat = row.get("category") or "غير مصنف"
        bucket = totals.setdefault(cat, {"total": 0, "items": 0})
        bucket["total"] += row["total"]
        bucket["items"] += 1
    return [{"category": k, **v} for k, v in sorted(totals.items(), key=lambda x: x[1]["total"], reverse=True)]


def purchase_reports_pending_receipt(tenant_id: int) -> list[dict]:
    from modules.clinics.models import ClinicPurchase, ClinicSupplier

    rows = (
        ClinicPurchase.query.filter_by(tenant_id=tenant_id)
        .filter(ClinicPurchase.invoice_status != "cancelled")
        .filter(ClinicPurchase.receipt_status.in_(["pending", "partial"]))
        .order_by(ClinicPurchase.id.desc())
        .all()
    )
    result = []
    for p in rows:
        sup = ClinicSupplier.query.filter_by(tenant_id=tenant_id, id=p.supplier_id).first()
        result.append({
            "id": p.id,
            "purchase_number": p.purchase_number,
            "supplier_name": sup.name if sup else "",
            "purchase_date": p.purchase_date.isoformat(),
            "receipt_status": p.receipt_status,
            "total": p.total,
        })
    return result


def purchase_reports_returns(tenant_id: int, args: dict | None = None) -> list[dict]:
    from modules.clinics.models import ClinicSupplier

    args = args or {}
    today = _today()
    start = _parse_date(args.get("date_from"), "من") if args.get("date_from") else today.replace(day=1)
    end = _parse_date(args.get("date_to"), "إلى") if args.get("date_to") else today
    rows = (
        ClinicPurchaseReturn.query.filter_by(tenant_id=tenant_id)
        .filter(ClinicPurchaseReturn.return_date >= start, ClinicPurchaseReturn.return_date <= end)
        .order_by(ClinicPurchaseReturn.id.desc())
        .all()
    )
    result = []
    for r in rows:
        sup = ClinicSupplier.query.filter_by(tenant_id=tenant_id, id=r.supplier_id).first()
        result.append({
            "id": r.id,
            "purchase_id": r.purchase_id,
            "return_number": r.return_number,
            "return_date": r.return_date.isoformat(),
            "supplier_name": sup.name if sup else "",
            "total_value": r.total_value,
        })
    return result


def purchase_reports_price_changes(tenant_id: int, args: dict | None = None) -> list[dict]:
    args = args or {}
    limit = int(args.get("limit") or 50)
    history = item_purchase_price_history(tenant_id, None, limit=limit * 3)
    by_item: dict[int, list] = {}
    for row in history:
        by_item.setdefault(row["item_id"], []).append(row)
    changes = []
    for item_id, rows in by_item.items():
        if len(rows) < 2:
            continue
        latest, prev = rows[0], rows[1]
        if latest["unit_cost"] == prev["unit_cost"]:
            continue
        pct = round(((latest["unit_cost"] - prev["unit_cost"]) / prev["unit_cost"]) * 100, 1) if prev["unit_cost"] else None
        changes.append({
            "item_id": item_id,
            "item_name": latest["item_name"],
            "old_cost": prev["unit_cost"],
            "new_cost": latest["unit_cost"],
            "change_pct": pct,
            "purchase_date": latest["purchase_date"],
            "supplier_name": latest["supplier_name"],
        })
    return sorted(changes, key=lambda x: abs(x.get("change_pct") or 0), reverse=True)[:limit]
