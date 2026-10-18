"""Draft → confirmed orders/invoices for Finora Phone (no accidental final postings)."""

from __future__ import annotations

import json
from datetime import datetime

from flask import g, request
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.customer import Customer
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from modules.phone_app.api.v1.routes import phone_api_v1_bp, require_phone_auth
from modules.phone_app.models import PhoneAuditLog, PhoneOrderDraft
from modules.phone_app.schemas import api_error, api_ok, require_json_fields


def _serialize_draft(d: PhoneOrderDraft) -> dict:
    return {
        "id": d.id,
        "client_id": d.client_id,
        "idempotency_key": d.idempotency_key,
        "customer_id": d.customer_id,
        "status": d.status,
        "invoice_id": d.invoice_id,
        "payload": json.loads(d.payload_json or "{}"),
        "created_at": d.created_at.isoformat() + "Z" if d.created_at else None,
        "confirmed_at": d.confirmed_at.isoformat() + "Z" if d.confirmed_at else None,
    }


def _build_lines(items: list) -> tuple[float, list[str], list[dict]]:
    total = 0.0
    summaries: list[str] = []
    normalized: list[dict] = []
    for raw in items:
        product_id = raw.get("product_id")
        qty = int(raw.get("qty") or raw.get("quantity") or 0)
        if not product_id or qty <= 0:
            continue
        product = db.session.get(Product, int(product_id))
        if not product:
            raise ValueError(f"منتج غير موجود: {product_id}")
        price = raw.get("price")
        if price is None:
            price = getattr(product, "sale_price", None) or getattr(product, "price", 0) or 0
        price = float(price)
        total += price * qty
        summaries.append(f"{product.name} x{qty}")
        normalized.append(
            {
                "product_id": int(product_id),
                "qty": qty,
                "price": price,
                "name": product.name,
            }
        )
    if not summaries:
        raise ValueError("لا توجد منتجات صالحة")
    return total, summaries, normalized


@phone_api_v1_bp.post("/orders")
@require_phone_auth
def orders_create():
    """Phase 1 in-call path: create DRAFT only (no stock / no final invoice)."""
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "customer_id", "items", "client_id")
    if missing:
        return api_error(missing, 400, code="validation_error")

    client_id = str(body.get("client_id") or "").strip()
    idem = str(
        body.get("idempotency_key")
        or request.headers.get("Idempotency-Key")
        or client_id
    ).strip()

    existing = PhoneOrderDraft.query.filter(
        (PhoneOrderDraft.client_id == client_id)
        | (PhoneOrderDraft.idempotency_key == idem)
    ).first()
    if existing:
        return api_ok(
            {
                "created": False,
                "duplicate": True,
                "draft": _serialize_draft(existing),
                "status": existing.status,
                "invoice_id": existing.invoice_id,
            }
        )

    customer = db.session.get(Customer, int(body["customer_id"]))
    if not customer:
        return api_error("الزبون غير موجود", 404, code="not_found")
    if getattr(customer, "is_blacklisted", False):
        return api_error(
            "هذا الزبون في القائمة السوداء",
            400,
            code="blacklisted",
        )

    items = body.get("items") or []
    if not isinstance(items, list) or not items:
        return api_error("لا توجد منتجات", 400, code="validation_error")

    try:
        total, summaries, normalized = _build_lines(items)
    except ValueError as exc:
        return api_error(str(exc), 400, code="validation_error")

    payload = {
        "customer_id": customer.id,
        "items": normalized,
        "total": total,
        "note": str(body.get("note") or "").strip(),
        "items_summary": summaries,
    }
    draft = PhoneOrderDraft(
        employee_id=g.phone_employee.id,
        customer_id=customer.id,
        client_id=client_id,
        idempotency_key=idem[:128],
        status="draft",
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.session.add(draft)
    db.session.add(
        PhoneAuditLog(
            employee_id=g.phone_employee.id,
            action="create_order_draft",
            detail=f"client_id={client_id}; total={total}",
        )
    )
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        again = PhoneOrderDraft.query.filter_by(idempotency_key=idem).first()
        if again:
            return api_ok(
                {
                    "created": False,
                    "duplicate": True,
                    "draft": _serialize_draft(again),
                    "status": again.status,
                }
            )
        return api_error("Conflict", 409, code="conflict")
    except Exception as exc:
        db.session.rollback()
        return api_error(f"فشل إنشاء المسودة: {exc}", 500, code="create_failed")

    return api_ok(
        {
            "created": True,
            "status": "draft",
            "draft": _serialize_draft(draft),
            "total": total,
            "client_id": client_id,
            "items_summary": summaries,
            "message": "مسودة فقط — يلزم التأكيد لإنشاء فاتورة/قيد محاسبي",
        },
        status=201,
    )


@phone_api_v1_bp.post("/orders/<int:draft_id>/confirm")
@require_phone_auth
def orders_confirm(draft_id: int):
    """Confirm draft → final Invoice (uses existing Finora permissions via employee)."""
    draft = db.session.get(PhoneOrderDraft, draft_id)
    if not draft or draft.employee_id != g.phone_employee.id:
        return api_error("Draft not found", 404, code="not_found")
    if draft.status == "confirmed" and draft.invoice_id:
        return api_ok(
            {
                "created": False,
                "duplicate": True,
                "status": "confirmed",
                "invoice_id": draft.invoice_id,
                "draft": _serialize_draft(draft),
            }
        )
    if draft.status != "draft":
        return api_error("Draft is not confirmable", 400, code="invalid_status")

    payload = json.loads(draft.payload_json or "{}")
    items = payload.get("items") or []
    customer = db.session.get(Customer, draft.customer_id)
    if not customer:
        return api_error("الزبون غير موجود", 404, code="not_found")

    emp = g.phone_employee
    total = float(payload.get("total") or 0)
    line_summaries = list(payload.get("items_summary") or [])

    # Validate the whole order before mutating stock.
    resolved_items: list[tuple[Product, int, float]] = []
    for raw in items:
        product = db.session.get(Product, int(raw["product_id"]))
        qty = int(raw.get("qty") or 0)
        if not product or qty <= 0:
            return api_error("أحد عناصر الطلب غير صالح", 400, code="invalid_item")
        price = float(raw.get("price") or 0)
        if hasattr(product, "quantity") and product.quantity is not None:
            if int(product.quantity) < qty:
                return api_error(
                    f"الكمية غير كافية للمنتج {product.name}",
                    400,
                    code="insufficient_stock",
                )
        resolved_items.append((product, qty, price))

    marker = f"[phone_client:{draft.client_id}]"
    existing_inv = (
        Invoice.query.filter(Invoice.note.contains(marker))
        .order_by(Invoice.id.desc())
        .first()
    )
    if existing_inv:
        draft.status = "confirmed"
        draft.invoice_id = existing_inv.id
        draft.confirmed_at = datetime.utcnow()
        db.session.commit()
        return api_ok(
            {
                "created": False,
                "duplicate": True,
                "status": "confirmed",
                "invoice_id": existing_inv.id,
                "draft": _serialize_draft(draft),
            }
        )

    user_note = str(payload.get("note") or "").strip()
    note = f"{marker} {user_note}".strip()
    invoice_kwargs = {
        "customer_id": customer.id,
        "customer_name": customer.name,
        "employee_id": emp.id,
        "employee_name": emp.name,
        "total": total,
        "note": note,
        "payment_status": "غير مسدد",
        # A pending phone order does not own physical stock until the shared
        # order policy explicitly claims it below.
        "stock_is_deducted": False,
    }
    for attr, value in (
        # The Orders page filters the persisted Arabic status, while
        # "ordered" is only its route/page key.
        ("status", "تم الطلب"),
        ("branch_id", emp.branch_id),
    ):
        if hasattr(Invoice, attr):
            invoice_kwargs[attr] = value

    invoice = Invoice(**invoice_kwargs)
    db.session.add(invoice)
    db.session.flush()

    # Persist product lines so the order is complete on the main Orders page.
    for product, qty, price in resolved_items:
        unit_price = int(round(price))
        line_total = unit_price * qty
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=qty,
                price=unit_price,
                cost=int(getattr(product, "buy_price", 0) or 0),
                total=line_total,
                fulfillment_branch_id=emp.branch_id,
                sale_mode="normal",
            )
        )

    db.session.flush()
    # Keep phone orders on the same inventory path as POS/web orders.  In the
    # normal deferred policy a pending order does not touch stock.  Tenants
    # that deliberately disabled deferral still receive an atomic branch-aware
    # deduction with an immutable movement record.
    from utils.order_stock_policy import deduct_order_stock, deferred_stock_enabled

    if not deferred_stock_enabled():
        try:
            deduct_order_stock(invoice)
        except Exception as exc:
            db.session.rollback()
            return api_error(str(exc), 409, code="insufficient_stock")

    draft.status = "confirmed"
    draft.invoice_id = invoice.id
    draft.confirmed_at = datetime.utcnow()
    db.session.add(
        PhoneAuditLog(
            employee_id=emp.id,
            action="confirm_order_draft",
            detail=f"draft_id={draft.id}; invoice_id={invoice.id}",
        )
    )
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return api_error(f"فشل تأكيد الطلب: {exc}", 500, code="confirm_failed")

    return api_ok(
        {
            "created": True,
            "status": "confirmed",
            "invoice_id": invoice.id,
            "total": total,
            "draft": _serialize_draft(draft),
            "items_summary": line_summaries,
        },
        status=201,
    )


@phone_api_v1_bp.get("/orders/drafts")
@require_phone_auth
def orders_list_drafts():
    rows = (
        PhoneOrderDraft.query.filter_by(employee_id=g.phone_employee.id)
        .order_by(PhoneOrderDraft.id.desc())
        .limit(100)
        .all()
    )
    return api_ok({"drafts": [_serialize_draft(d) for d in rows]})


@phone_api_v1_bp.post("/invoices")
@require_phone_auth
def invoices_create():
    """In-call invoice path also creates draft only (confirm separately)."""
    return orders_create()
