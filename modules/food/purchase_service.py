"""Food purchase list, detail, payments and management APIs.

Extends the shared Purchase / PurchaseItem tables with source_module='food'.
Stock, average cost and snapshots remain handled by service.create_purchase /
service.reverse_purchase.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_

from extensions import db
from models.branch import Branch
from models.employee import Employee
from models.product import Product
from models.purchase import Purchase
from models.purchase_item import PurchaseItem
from models.supplier import Supplier
from models.supplier_payment import SupplierPayment
from modules.food.models import (
    FoodExpiryBatch,
    FoodInventoryMovement,
    FoodProductBarcode,
    FoodProductProfile,
    FoodProductVariant,
    FoodPurchaseItemSnapshot,
    FoodPurchaseReturn,
    FoodPurchaseReturnLine,
)
from modules.food.service import (
    FoodError,
    as_int,
    reverse_purchase,
    _adjust_warehouse_stock,
    _ensure_legacy_warehouse_stock,
    _previous_window,
    _pct_change,
    _report_window,
    _variant,
    _warehouse_stock,
)

PAYMENT_LABELS = {
    "cash": "نقدي",
    "credit": "آجل",
    "partial": "جزئي",
    "mixed": "مختلط",
    "card": "بطاقة",
    "transfer": "تحويل",
}

STATUS_LABELS = {
    "draft": "مسودة",
    "confirmed": "معتمدة",
    "paid": "مدفوعة",
    "partial": "مدفوعة جزئياً",
    "credit": "آجلة",
    "cancelled": "ملغاة",
}


def _purchase_display_status(purchase: Purchase) -> tuple[str, str]:
    status = str(purchase.status or "").strip().lower()
    if status in {"cancelled", "canceled", "ملغاة", "void"} or bool(purchase.deleted_at):
        return "cancelled", STATUS_LABELS["cancelled"]
    if bool(purchase.is_draft) or status == "draft":
        return "draft", STATUS_LABELS["draft"]
    grand = int(purchase.grand_total or purchase.total or 0)
    paid = int(purchase.paid_total or 0)
    remaining = int(purchase.remaining_total if purchase.remaining_total is not None else max(0, grand - paid))
    if grand > 0 and remaining <= 0 and paid > 0:
        return "paid", STATUS_LABELS["paid"]
    if paid > 0 and remaining > 0:
        return "partial", STATUS_LABELS["partial"]
    if remaining > 0 and paid <= 0:
        return "credit", STATUS_LABELS["credit"]
    return "confirmed", STATUS_LABELS["confirmed"]


def _payment_label(mode: str | None, remaining: int, paid: int) -> str:
    key = str(mode or "").strip().lower()
    if key in PAYMENT_LABELS:
        return PAYMENT_LABELS[key]
    if remaining <= 0 and paid > 0:
        return PAYMENT_LABELS["cash"]
    if paid > 0 and remaining > 0:
        return PAYMENT_LABELS["partial"]
    if remaining > 0:
        return PAYMENT_LABELS["credit"]
    return PAYMENT_LABELS.get(key, key or "—")


def _warehouse_name(warehouse_id: int | None) -> str | None:
    if not warehouse_id:
        return None
    branch = db.session.get(Branch, int(warehouse_id))
    return branch.name if branch else None


def _serialize_purchase_row(purchase: Purchase, *, item_count: int = 0) -> dict:
    supplier = db.session.get(Supplier, purchase.supplier_id) if purchase.supplier_id else None
    grand = int(purchase.grand_total or purchase.total or 0)
    paid = int(purchase.paid_total or 0)
    remaining = int(
        purchase.remaining_total if purchase.remaining_total is not None else max(0, grand - paid)
    )
    status_key, status_label = _purchase_display_status(purchase)
    warehouse_id = purchase.warehouse_id or purchase.branch_id
    return {
        "id": purchase.id,
        "invoice_no": purchase.invoice_no,
        "supplier_invoice_no": purchase.supplier_invoice_no,
        "purchase_date": purchase.purchase_date.isoformat() if purchase.purchase_date else None,
        "created_at": purchase.created_at.isoformat() if purchase.created_at else None,
        "supplier_id": purchase.supplier_id,
        "supplier_name": supplier.name if supplier else "—",
        "supplier_phone": supplier.phone if supplier else None,
        "branch_id": purchase.branch_id,
        "warehouse_id": warehouse_id,
        "warehouse_name": _warehouse_name(warehouse_id) or "المخزون العام",
        "payment_mode": str(purchase.purchase_mode or "").lower(),
        "payment_method": _payment_label(purchase.purchase_mode, remaining, paid),
        "item_count": item_count,
        "sub_total": int(purchase.sub_total or 0),
        "discount_value": int(purchase.discount_value or 0),
        "shipping_extra": int(purchase.shipping_extra or 0),
        "customs_extra": int(getattr(purchase, "customs_extra", 0) or 0),
        "other_extra": int(getattr(purchase, "other_extra", 0) or 0),
        "total": grand,
        "paid": paid,
        "remaining": remaining,
        "status": status_key,
        "status_label": status_label,
        "stock_applied": bool(purchase.stock_applied),
        "is_draft": bool(purchase.is_draft) or status_key == "draft",
        "notes": purchase.notes,
    }


def _base_query(tenant_id: int, filters: dict):
    query = Purchase.query.outerjoin(Supplier, Supplier.id == Purchase.supplier_id).filter(
        Purchase.source_module == "food",
        Purchase.deleted_at.is_(None),
    )

    start_day = filters.get("start")
    end_day = filters.get("end")
    start_dt = filters.get("start_dt")
    end_dt = filters.get("end_dt")
    if start_day is not None and end_day is not None and start_dt is not None and end_dt is not None:
        query = query.filter(
            or_(
                Purchase.purchase_date.between(start_day, end_day),
                db.and_(
                    Purchase.purchase_date.is_(None),
                    Purchase.created_at >= start_dt,
                    Purchase.created_at < end_dt,
                ),
            )
        )

    supplier_id = as_int(filters.get("supplier_id"), 0) or None
    if supplier_id:
        query = query.filter(Purchase.supplier_id == supplier_id)

    warehouse_id = as_int(filters.get("warehouse_id") or filters.get("branch_id"), 0) or None
    if warehouse_id:
        query = query.filter(
            or_(Purchase.warehouse_id == warehouse_id, Purchase.branch_id == warehouse_id)
        )

    payment_method = str(filters.get("payment_method") or "").strip().lower()
    if payment_method and payment_method not in {"", "all", "الكل"}:
        query = query.filter(func.lower(Purchase.purchase_mode) == payment_method)

    term = str(filters.get("q") or "").strip()
    if term:
        like = f"%{term}%"
        product_match = (
            db.session.query(PurchaseItem.purchase_id)
            .join(FoodPurchaseItemSnapshot, FoodPurchaseItemSnapshot.purchase_item_id == PurchaseItem.id)
            .outerjoin(FoodProductVariant, FoodProductVariant.id == FoodPurchaseItemSnapshot.variant_id)
            .outerjoin(FoodProductProfile, FoodProductProfile.id == FoodProductVariant.profile_id)
            .outerjoin(Product, Product.id == FoodProductProfile.product_id)
            .outerjoin(FoodProductBarcode, FoodProductBarcode.unit_id == FoodPurchaseItemSnapshot.unit_id)
            .outerjoin(
                FoodExpiryBatch,
                FoodExpiryBatch.purchase_id == PurchaseItem.purchase_id,
            )
            .filter(
                FoodPurchaseItemSnapshot.tenant_id == tenant_id,
                or_(
                    FoodPurchaseItemSnapshot.barcode_snapshot == term,
                    FoodProductBarcode.barcode == term,
                    FoodPurchaseItemSnapshot.variant_name_snapshot.ilike(like),
                    Product.name.ilike(like),
                    FoodProductVariant.sku.ilike(like),
                    FoodExpiryBatch.batch_number.ilike(like),
                ),
            )
        )
        query = query.filter(
            or_(
                Purchase.invoice_no == term,
                Purchase.invoice_no.ilike(like),
                Purchase.supplier_invoice_no == term,
                Purchase.supplier_invoice_no.ilike(like),
                Supplier.name.ilike(like),
                Supplier.phone.ilike(like),
                Purchase.id.in_(product_match),
            )
        )
    return query


def _apply_status_tab(query, filters: dict):
    status_tab = str(filters.get("status_tab") or filters.get("status") or "all").strip().lower()
    purchase_status = str(filters.get("purchase_status") or filters.get("invoice_status") or "").strip().lower()

    if status_tab in {"cancelled", "void", "ملغاة"} or purchase_status in {"cancelled", "void"}:
        return query.filter(
            or_(
                func.lower(Purchase.status).in_(("cancelled", "canceled", "ملغاة", "void")),
                Purchase.deleted_at.isnot(None),
            )
        )

    query = query.filter(
        ~func.lower(Purchase.status).in_(("cancelled", "canceled", "ملغاة", "void")),
        Purchase.deleted_at.is_(None),
    )

    if status_tab in {"draft", "مسودة"} or purchase_status == "draft":
        return query.filter(or_(Purchase.is_draft.is_(True), func.lower(Purchase.status) == "draft"))

    if status_tab in {"confirmed", "معتمدة"} or purchase_status == "confirmed":
        return query.filter(
            or_(Purchase.is_draft.is_(False), Purchase.is_draft.is_(None)),
            func.lower(Purchase.status) != "draft",
            Purchase.stock_applied.is_(True),
        )

    if status_tab in {"due", "credit", "مستحقة", "آجلة"} or purchase_status in {"due", "credit"}:
        return query.filter(
            or_(Purchase.is_draft.is_(False), Purchase.is_draft.is_(None)),
            Purchase.remaining_total > 0,
        )

    if status_tab in {"paid", "مدفوعة"} or purchase_status == "paid":
        return query.filter(
            Purchase.remaining_total <= 0,
            Purchase.paid_total > 0,
            or_(Purchase.is_draft.is_(False), Purchase.is_draft.is_(None)),
        )

    if status_tab in {"partial", "مدفوعة جزئياً"} or purchase_status == "partial":
        return query.filter(Purchase.paid_total > 0, Purchase.remaining_total > 0)

    if status_tab in {"returns", "مرتجعات"} or purchase_status in {"returns", "return"}:
        tenant_id = as_int(filters.get("tenant_id"), 0)
        returned_ids = db.session.query(FoodPurchaseReturn.purchase_id)
        if tenant_id:
            returned_ids = returned_ids.filter(FoodPurchaseReturn.tenant_id == tenant_id)
        return query.filter(Purchase.id.in_(returned_ids.distinct()))

    if purchase_status == "cancelled":
        return query.filter(func.lower(Purchase.status).in_(("cancelled", "canceled", "ملغاة", "void")))

    return query


def _returned_qty_by_item(tenant_id: int, purchase_item_ids: list[int]) -> dict[int, int]:
    if not purchase_item_ids:
        return {}
    rows = (
        db.session.query(
            FoodPurchaseReturnLine.purchase_item_id,
            func.coalesce(func.sum(FoodPurchaseReturnLine.quantity), 0),
        )
        .filter(
            FoodPurchaseReturnLine.tenant_id == tenant_id,
            FoodPurchaseReturnLine.purchase_item_id.in_(purchase_item_ids),
        )
        .group_by(FoodPurchaseReturnLine.purchase_item_id)
        .all()
    )
    return {int(pid): int(qty or 0) for pid, qty in rows}


def _purchase_return_total(tenant_id: int, purchase_id: int) -> int:
    return int(
        db.session.query(func.coalesce(func.sum(FoodPurchaseReturn.total), 0))
        .filter(
            FoodPurchaseReturn.tenant_id == tenant_id,
            FoodPurchaseReturn.purchase_id == purchase_id,
        )
        .scalar()
        or 0
    )


def _returns_in_window(tenant_id: int, start_dt, end_dt) -> tuple[int, int]:
    rows = FoodPurchaseReturn.query.filter(
        FoodPurchaseReturn.tenant_id == tenant_id,
        FoodPurchaseReturn.created_at >= start_dt,
        FoodPurchaseReturn.created_at < end_dt,
    ).all()
    return sum(int(r.total or 0) for r in rows), len(rows)


def _prepare_filters(filters: dict | None) -> dict:
    filters = dict(filters or {})
    key, start, end, start_dt, end_dt = _report_window(
        filters.get("range") or "today",
        filters.get("start"),
        filters.get("end"),
    )
    filters["range_key"] = key
    filters["start"] = start
    filters["end"] = end
    filters["start_dt"] = start_dt
    filters["end_dt"] = end_dt
    return filters


def _item_counts(purchase_ids: list[int]) -> dict[int, int]:
    if not purchase_ids:
        return {}
    rows = (
        db.session.query(PurchaseItem.purchase_id, func.count(PurchaseItem.id))
        .filter(PurchaseItem.purchase_id.in_(purchase_ids))
        .group_by(PurchaseItem.purchase_id)
        .all()
    )
    return {int(pid): int(count) for pid, count in rows}


def _kpi_block(value: int | float, previous: int | float, *, money: bool = True) -> dict:
    return {
        "value": int(value),
        "previous": int(previous),
        "change": _pct_change(float(value), float(previous)),
        "money": money,
    }


def _aggregate_kpis(tenant_id: int, filters: dict) -> dict:
    query = _apply_status_tab(_base_query(tenant_id, filters), {**filters, "status_tab": "all"})
    rows = query.all()
    active = [r for r in rows if _purchase_display_status(r)[0] != "cancelled"]
    drafts = [r for r in rows if _purchase_display_status(r)[0] == "draft"]
    confirmed = [r for r in active if _purchase_display_status(r)[0] != "draft"]
    total = sum(int(r.grand_total or r.total or 0) for r in confirmed)
    paid = sum(int(r.paid_total or 0) for r in confirmed)
    remaining = sum(int(r.remaining_total or 0) for r in confirmed)
    count = len(confirmed)
    average = (total // count) if count else 0
    return {
        "purchases": _kpi_block(total, 0),
        "invoices": _kpi_block(count, 0, money=False),
        "paid": _kpi_block(paid, 0),
        "remaining": _kpi_block(remaining, 0),
        "returns": _kpi_block(0, 0),
        "average": _kpi_block(average, 0),
        "drafts": len(drafts),
    }


def list_purchases(tenant_id: int, filters: dict | None = None) -> dict:
    filters = _prepare_filters(filters)
    filters["tenant_id"] = tenant_id
    page = max(1, as_int(filters.get("page"), 1, minimum=1))
    page_size = min(100, max(1, as_int(filters.get("page_size"), 20, minimum=1)))

    base = _base_query(tenant_id, filters)
    tab_query = _apply_status_tab(base, filters)

    # Tab counters (same window, ignore status tab)
    counter_base = _base_query(tenant_id, filters)
    all_rows = counter_base.filter(
        ~func.lower(Purchase.status).in_(("cancelled", "canceled", "ملغاة", "void")),
        Purchase.deleted_at.is_(None),
    ).all()
    cancelled_count = counter_base.filter(
        or_(
            func.lower(Purchase.status).in_(("cancelled", "canceled", "ملغاة", "void")),
            Purchase.deleted_at.isnot(None),
        )
    ).count()
    returned_purchase_ids = {
        int(pid)
        for (pid,) in db.session.query(FoodPurchaseReturn.purchase_id)
        .filter(FoodPurchaseReturn.tenant_id == tenant_id)
        .distinct()
        .all()
    }
    returns_total, returns_count = _returns_in_window(
        tenant_id, filters["start_dt"], filters["end_dt"]
    )
    counters = {
        "all": len(all_rows),
        "confirmed": sum(1 for r in all_rows if _purchase_display_status(r)[0] not in {"draft", "cancelled"}),
        "draft": sum(1 for r in all_rows if _purchase_display_status(r)[0] == "draft"),
        "due": sum(1 for r in all_rows if int(r.remaining_total or 0) > 0 and _purchase_display_status(r)[0] != "draft"),
        "returns": sum(1 for r in all_rows if r.id in returned_purchase_ids),
        "paid": sum(1 for r in all_rows if _purchase_display_status(r)[0] == "paid"),
        "cancelled": cancelled_count,
    }

    total_count = tab_query.count()
    purchases = (
        tab_query.order_by(Purchase.created_at.desc(), Purchase.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    counts = _item_counts([p.id for p in purchases])

    # KPI with previous period comparison
    kpis = _aggregate_kpis(tenant_id, {**filters, "status_tab": "all"})
    kpis["returns"] = _kpi_block(returns_total, 0)
    prev_start, prev_end = _previous_window(filters["start"], filters["end"])
    prev_start_dt, prev_end_dt = __import__(
        "modules.food.service", fromlist=["_local_date_bounds"]
    )._local_date_bounds(prev_start, prev_end)
    prev_filters = {
        **filters,
        "start": prev_start,
        "end": prev_end,
        "start_dt": prev_start_dt,
        "end_dt": prev_end_dt,
        "status_tab": "all",
    }
    prev = _aggregate_kpis(tenant_id, prev_filters)
    prev_returns_total, _ = _returns_in_window(tenant_id, prev_start_dt, prev_end_dt)
    for key in ("purchases", "invoices", "paid", "remaining", "average"):
        kpis[key] = _kpi_block(
            kpis[key]["value"],
            prev[key]["value"],
            money=kpis[key].get("money", True),
        )
    kpis["returns"] = _kpi_block(returns_total, prev_returns_total)

    return {
        "range": {
            "key": filters["range_key"],
            "start": filters["start"].isoformat(),
            "end": filters["end"].isoformat(),
        },
        "kpis": kpis,
        "counters": counters,
        "page": page,
        "page_size": page_size,
        "total": total_count,
        "pages": max(1, (total_count + page_size - 1) // page_size),
        "rows": [
            _serialize_purchase_row(row, item_count=counts.get(row.id, 0))
            for row in purchases
        ],
    }


def purchase_filter_options(tenant_id: int) -> dict:
    warehouses = (
        Branch.query.filter(or_(Branch.is_active.is_(True), Branch.is_active.is_(None)))
        .order_by(Branch.name)
        .all()
    )
    suppliers = Supplier.query.order_by(Supplier.name).limit(500).all()
    return {
        "warehouses": [
            {"id": row.id, "name": row.name, "is_default": bool(getattr(row, "is_default", False))}
            for row in warehouses
        ],
        "suppliers": [
            {
                "id": row.id,
                "name": row.name,
                "phone": row.phone,
                "debt": max(0, int(row.total_debt or 0) - int(row.total_paid or 0)),
            }
            for row in suppliers
        ],
        "payment_methods": [
            {"id": key, "label": label} for key, label in PAYMENT_LABELS.items()
        ],
        "statuses": [
            {"id": key, "label": label} for key, label in STATUS_LABELS.items()
        ],
    }


def get_purchase_detail(tenant_id: int, purchase_id: int, *, view_cost: bool = True) -> dict:
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase or str(purchase.source_module or "").lower() != "food":
        raise FoodError("فاتورة الشراء غير موجودة")
    if purchase.deleted_at:
        raise FoodError("فاتورة الشراء محذوفة")

    # Tenant check via snapshot or allow empty draft
    snapshots = (
        FoodPurchaseItemSnapshot.query.join(
            PurchaseItem, PurchaseItem.id == FoodPurchaseItemSnapshot.purchase_item_id
        )
        .filter(PurchaseItem.purchase_id == purchase_id)
        .order_by(FoodPurchaseItemSnapshot.id)
        .all()
    )
    if snapshots and any(int(s.tenant_id) != int(tenant_id) for s in snapshots):
        raise FoodError("فاتورة الشراء غير موجودة")

    items = PurchaseItem.query.filter_by(purchase_id=purchase_id).order_by(PurchaseItem.id).all()
    snap_by_item = {int(s.purchase_item_id): s for s in snapshots}
    returned_map = _returned_qty_by_item(tenant_id, [int(i.id) for i in items])
    line_rows = []
    for item in items:
        snap = snap_by_item.get(int(item.id))
        product = db.session.get(Product, item.product_id) if item.product_id else None
        qty = int(item.quantity or 0)
        returned_qty = returned_map.get(int(item.id), 0)
        line = {
            "id": item.id,
            "snapshot_id": snap.id if snap else None,
            "product_id": item.product_id,
            "product_name": product.name if product else "—",
            "variant_id": snap.variant_id if snap else None,
            "variant_name": snap.variant_name_snapshot if snap else None,
            "unit_id": snap.unit_id if snap else None,
            "unit_name": snap.unit_name_snapshot if snap else None,
            "unit_factor": int(snap.unit_factor_snapshot or 1) if snap else 1,
            "barcode": snap.barcode_snapshot if snap else None,
            "quantity": qty,
            "bonus": int(snap.bonus_quantity or 0) if snap else 0,
            "returned_quantity": returned_qty,
            "returnable_quantity": max(0, qty - returned_qty),
            "quantity_base": int(snap.quantity_base or 0) if snap else int(item.quantity or 0),
            "unit_cost": int(item.unit_cost_before_discount or 0),
            "discount": int(item.discount_value or 0),
            "final_unit_cost": int(item.final_unit_cost or 0),
            "line_total": int(item.line_total or 0),
            "warehouse_id": snap.warehouse_id if snap else purchase.warehouse_id,
            "warehouse_name": _warehouse_name(
                snap.warehouse_id if snap else purchase.warehouse_id
            ),
            "expiry_date": snap.expiry_date.isoformat() if snap and snap.expiry_date else None,
            "batch_number": None,
            "batch_id": None,
            "batches": [],
        }
        if snap:
            batches = FoodExpiryBatch.query.filter_by(
                purchase_id=purchase.id, variant_id=snap.variant_id
            ).order_by(FoodExpiryBatch.id.desc()).all()
            line["batches"] = [
                {
                    "id": b.id,
                    "batch_number": b.batch_number,
                    "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
                    "quantity_base": int(b.quantity_base or 0),
                }
                for b in batches
                if int(b.quantity_base or 0) > 0
            ]
            if batches:
                line["batch_number"] = batches[0].batch_number
                line["batch_id"] = batches[0].id
                if batches[0].production_date:
                    line["production_date"] = batches[0].production_date.isoformat()
        if not view_cost:
            line["unit_cost"] = None
            line["final_unit_cost"] = None
            line["discount"] = None
        line_rows.append(line)

    payments = (
        SupplierPayment.query.filter_by(
            tenant_id=tenant_id,
            supplier_id=purchase.supplier_id,
            source_module="food",
        )
        .filter(SupplierPayment.deleted_at.is_(None))
        .filter(
            or_(
                SupplierPayment.note == f"دفعة فاتورة {purchase.invoice_no}",
                SupplierPayment.note.ilike(f"%{purchase.invoice_no}%"),
            )
        )
        .order_by(SupplierPayment.created_at.desc())
        .all()
    )
    payment_rows = [
        {
            "id": row.id,
            "amount": int(row.amount or 0),
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "method": "cash",
        }
        for row in payments
    ]

    returns = (
        FoodPurchaseReturn.query.filter_by(tenant_id=tenant_id, purchase_id=purchase.id)
        .order_by(FoodPurchaseReturn.created_at.desc())
        .all()
    )
    return_rows = [
        {
            "id": row.id,
            "return_no": row.return_no,
            "total": int(row.total or 0),
            "reason": row.reason,
            "settlement": row.settlement,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in returns
    ]

    supplier = db.session.get(Supplier, purchase.supplier_id) if purchase.supplier_id else None
    creator = (
        db.session.get(Employee, purchase.created_by_employee_id)
        if purchase.created_by_employee_id
        else None
    )
    header = _serialize_purchase_row(purchase, item_count=len(line_rows))
    header.update({
        "supplier_debt": max(0, int(supplier.total_debt or 0) - int(supplier.total_paid or 0)) if supplier else 0,
        "created_by": getattr(creator, "name", None) if creator else None,
        "currency": purchase.currency or "IQD",
        "return_total": _purchase_return_total(tenant_id, purchase.id),
        "items": line_rows,
        "payments": payment_rows,
        "returns": return_rows,
        "extras": {
            "shipping": int(purchase.shipping_extra or 0),
            "customs": int(getattr(purchase, "customs_extra", 0) or 0),
            "other": int(getattr(purchase, "other_extra", 0) or 0),
        },
    })
    return header


def register_purchase_payment(
    tenant_id: int, purchase_id: int, payload: dict, employee_id: int | None = None
) -> dict:
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase or str(purchase.source_module or "").lower() != "food":
        raise FoodError("فاتورة الشراء غير موجودة")
    status_key, _ = _purchase_display_status(purchase)
    if status_key in {"cancelled", "draft"}:
        raise FoodError("لا يمكن تسديد فاتورة مسودة أو ملغاة")
    remaining = int(purchase.remaining_total or 0)
    if remaining <= 0:
        raise FoodError("الفاتورة مسددة بالكامل")
    amount = as_int(payload.get("amount") or payload.get("paid_amount"), 0, minimum=1)
    if amount > remaining:
        raise FoodError(f"المبلغ أكبر من المتبقي ({remaining:,})")
    note = str(payload.get("note") or "").strip() or f"دفعة فاتورة {purchase.invoice_no}"
    purchase.paid_total = int(purchase.paid_total or 0) + amount
    purchase.remaining_total = max(0, int(purchase.grand_total or 0) - int(purchase.paid_total or 0))
    if purchase.remaining_total <= 0 and purchase.purchase_mode in {"credit", "partial"}:
        purchase.purchase_mode = "cash"
    supplier = db.session.get(Supplier, purchase.supplier_id)
    if supplier:
        supplier.total_paid = int(supplier.total_paid or 0) + amount
    payment = SupplierPayment(
        supplier_id=purchase.supplier_id,
        tenant_id=tenant_id,
        amount=amount,
        source_module="food",
        note=note,
    )
    db.session.add(payment)
    db.session.flush()
    return {
        "id": purchase.id,
        "paid": int(purchase.paid_total or 0),
        "remaining": int(purchase.remaining_total or 0),
        "status": _purchase_display_status(purchase)[0],
    }


def cancel_purchase(
    tenant_id: int, purchase_id: int, reason: str = "", *, hard_delete: bool = False
) -> dict:
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase or str(purchase.source_module or "").lower() != "food":
        raise FoodError("فاتورة الشراء غير موجودة")
    # Soft-tenant check
    snap = (
        FoodPurchaseItemSnapshot.query.join(
            PurchaseItem, PurchaseItem.id == FoodPurchaseItemSnapshot.purchase_item_id
        )
        .filter(PurchaseItem.purchase_id == purchase_id)
        .first()
    )
    if snap and int(snap.tenant_id) != int(tenant_id):
        raise FoodError("فاتورة الشراء غير موجودة")

    reason = str(reason or "").strip() or "إلغاء فاتورة شراء"
    if bool(purchase.is_draft) or str(purchase.status or "").lower() == "draft":
        purchase.status = "cancelled"
        purchase.is_draft = False
        purchase.stock_applied = False
        if hard_delete:
            purchase.deleted_at = datetime.utcnow()
        db.session.flush()
        return {"id": purchase.id, "status": "cancelled"}

    reverse_purchase(purchase, reason, hard_delete=hard_delete)
    purchase.status = "cancelled"
    if hard_delete:
        purchase.deleted_at = datetime.utcnow()
    db.session.flush()
    return {"id": purchase.id, "status": "cancelled"}


def export_purchases_rows(tenant_id: int, filters: dict | None = None) -> list[dict]:
    filters = _prepare_filters(filters)
    query = _apply_status_tab(_base_query(tenant_id, filters), filters)
    purchases = query.order_by(Purchase.created_at.desc()).limit(5000).all()
    counts = _item_counts([p.id for p in purchases])
    rows = []
    for purchase in purchases:
        data = _serialize_purchase_row(purchase, item_count=counts.get(purchase.id, 0))
        rows.append({
            "invoice_no": data["invoice_no"],
            "purchase_date": data["purchase_date"],
            "supplier_invoice_no": data["supplier_invoice_no"],
            "supplier": data["supplier_name"],
            "warehouse": data["warehouse_name"],
            "total": data["total"],
            "paid": data["paid"],
            "remaining": data["remaining"],
            "payment_method": data["payment_method"],
            "status": data["status_label"],
        })
    return rows


def check_duplicate_supplier_invoice(
    tenant_id: int, supplier_id: int, supplier_invoice_no: str, *, exclude_id: int | None = None
) -> dict | None:
    number = str(supplier_invoice_no or "").strip()
    if not number or not supplier_id:
        return None
    query = Purchase.query.filter(
        Purchase.source_module == "food",
        Purchase.supplier_id == int(supplier_id),
        Purchase.supplier_invoice_no == number,
        Purchase.deleted_at.is_(None),
        ~func.lower(Purchase.status).in_(("cancelled", "canceled", "ملغاة", "void")),
    )
    if exclude_id:
        query = query.filter(Purchase.id != int(exclude_id))
    # Prefer purchases that belong to this tenant via snapshots; also allow headers without snaps.
    existing = query.order_by(Purchase.id.desc()).first()
    if not existing:
        return None
    snap = (
        FoodPurchaseItemSnapshot.query.join(
            PurchaseItem, PurchaseItem.id == FoodPurchaseItemSnapshot.purchase_item_id
        )
        .filter(PurchaseItem.purchase_id == existing.id)
        .first()
    )
    if snap and int(snap.tenant_id) != int(tenant_id):
        return None
    return {
        "id": existing.id,
        "invoice_no": existing.invoice_no,
        "supplier_invoice_no": existing.supplier_invoice_no,
    }


def supplier_summary(tenant_id: int, supplier_id: int) -> dict:
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier:
        raise FoodError("المورد غير موجود")
    last = (
        Purchase.query.filter_by(supplier_id=supplier_id, source_module="food")
        .filter(Purchase.deleted_at.is_(None))
        .order_by(Purchase.created_at.desc())
        .first()
    )
    return {
        "id": supplier.id,
        "name": supplier.name,
        "phone": supplier.phone,
        "address": getattr(supplier, "address", None),
        "debt": max(0, int(supplier.total_debt or 0) - int(supplier.total_paid or 0)),
        "total_purchases": int(supplier.total_debt or 0),
        "total_paid": int(supplier.total_paid or 0),
        "last_purchase_total": int(last.grand_total or last.total or 0) if last else 0,
        "last_purchase_date": last.purchase_date.isoformat() if last and last.purchase_date else (
            last.created_at.isoformat() if last and last.created_at else None
        ),
        "last_invoice_no": last.invoice_no if last else None,
    }


RETURN_REASONS = (
    "تالف",
    "منتهي",
    "قريب انتهاء",
    "غير مطابق",
    "زيادة بالكمية",
    "استبدال",
    "سبب آخر",
)


def confirm_purchase(tenant_id: int, purchase_id: int, employee_id: int | None = None) -> dict:
    """Confirm a draft food purchase and apply stock / AP / payments."""
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase or str(purchase.source_module or "").lower() != "food":
        raise FoodError("فاتورة الشراء غير موجودة")
    status_key, _ = _purchase_display_status(purchase)
    if status_key == "cancelled":
        raise FoodError("لا يمكن اعتماد فاتورة ملغاة")
    if purchase.stock_applied and status_key != "draft":
        raise FoodError("الفاتورة معتمدة مسبقاً")
    if not (bool(purchase.is_draft) or status_key == "draft" or not purchase.stock_applied):
        raise FoodError("الفاتورة ليست مسودة")

    snapshots = (
        FoodPurchaseItemSnapshot.query.join(
            PurchaseItem, PurchaseItem.id == FoodPurchaseItemSnapshot.purchase_item_id
        )
        .filter(PurchaseItem.purchase_id == purchase.id)
        .order_by(FoodPurchaseItemSnapshot.id)
        .all()
    )
    if not snapshots:
        raise FoodError("لا توجد مواد في المسودة")
    if any(int(s.tenant_id) != int(tenant_id) for s in snapshots):
        raise FoodError("فاتورة الشراء غير موجودة")

    supplier = db.session.get(Supplier, purchase.supplier_id)
    if not supplier:
        raise FoodError("المورد غير موجود")

    # Recompute landed shares for average cost from header extras.
    items = {int(i.id): i for i in PurchaseItem.query.filter_by(purchase_id=purchase.id).all()}
    subtotal = sum(int(i.line_total or 0) for i in items.values()) or 1
    extras = (
        int(purchase.shipping_extra or 0)
        + int(getattr(purchase, "customs_extra", 0) or 0)
        + int(getattr(purchase, "other_extra", 0) or 0)
    )

    allocated = 0
    snap_list = list(snapshots)
    for idx, snapshot in enumerate(snap_list):
        item = items.get(int(snapshot.purchase_item_id))
        if not item:
            continue
        variant = _variant(tenant_id, int(snapshot.variant_id), lock=True)
        if variant.profile.track_expiry and not snapshot.expiry_date:
            raise FoodError(f"أدخل تاريخ الصلاحية لـ {variant.variant_name} قبل الاعتماد")
        quantity = int(item.quantity or 0)
        bonus = int(snapshot.bonus_quantity or 0)
        quantity_base = int(snapshot.quantity_base or 0)
        unit_cost = int(snapshot.unit_price_snapshot or item.unit_cost_before_discount or 0)
        line_total = int(item.line_total or 0)
        share = (
            extras - allocated
            if idx == len(snap_list) - 1
            else int(round(extras * (line_total / subtotal))) if extras and subtotal else 0
        )
        if idx < len(snap_list) - 1:
            allocated += share
        landed_line = line_total + share
        if quantity > 0:
            item.final_unit_cost = int(round(landed_line / quantity))

        line_warehouse_id = snapshot.warehouse_id or purchase.warehouse_id
        before = int(variant.stock_base or 0)
        if variant.profile.track_stock:
            after = before + quantity_base
            old_value = before * int(variant.average_cost or 0)
            incoming_base_cost = landed_line // max(1, quantity_base)
            variant.average_cost = (old_value + quantity_base * incoming_base_cost) // max(1, after)
            _ensure_legacy_warehouse_stock(variant, line_warehouse_id)
            _adjust_warehouse_stock(variant, line_warehouse_id, quantity_base)
            after = int(variant.stock_base or 0)
            db.session.add(FoodInventoryMovement(
                tenant_id=tenant_id,
                variant_id=variant.id,
                unit_id=snapshot.unit_id,
                warehouse_id=line_warehouse_id,
                movement_type="purchase",
                quantity_base=quantity_base,
                quantity_before=before,
                quantity_after=after,
                reference_type="purchase",
                reference_id=purchase.id,
                employee_id=employee_id,
            ))
            if snapshot.expiry_date:
                db.session.add(FoodExpiryBatch(
                    tenant_id=tenant_id,
                    variant_id=variant.id,
                    warehouse_id=line_warehouse_id,
                    received_unit_id=snapshot.unit_id,
                    batch_number=None,
                    production_date=None,
                    expiry_date=snapshot.expiry_date,
                    quantity_base=quantity_base,
                    received_quantity=quantity + bonus,
                    unit_factor_snapshot=int(snapshot.unit_factor_snapshot or 1),
                    unit_cost_snapshot=int(item.final_unit_cost or unit_cost),
                    supplier_id=supplier.id,
                    purchase_id=purchase.id,
                    status="sellable",
                ))

    purchase.is_draft = False
    purchase.status = "confirmed"
    purchase.stock_applied = True
    supplier.total_debt = int(supplier.total_debt or 0) + int(purchase.grand_total or 0)
    supplier.total_paid = int(supplier.total_paid or 0) + int(purchase.paid_total or 0)
    if int(purchase.paid_total or 0):
        db.session.add(SupplierPayment(
            supplier_id=supplier.id,
            tenant_id=tenant_id,
            amount=int(purchase.paid_total or 0),
            source_module="food",
            note=f"دفعة فاتورة {purchase.invoice_no}",
            payment_method=str(purchase.purchase_mode or "cash"),
        ))
    db.session.flush()
    return {
        "id": purchase.id,
        "invoice_no": purchase.invoice_no,
        "status": "confirmed",
        "stock_applied": True,
        "total": int(purchase.grand_total or 0),
    }


def create_purchase_return(
    tenant_id: int, purchase_id: int, payload: dict, employee_id: int | None = None
) -> dict:
    """Partial/full supplier return against an existing food purchase."""
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase or str(purchase.source_module or "").lower() != "food":
        raise FoodError("فاتورة الشراء غير موجودة")
    status_key, _ = _purchase_display_status(purchase)
    if status_key in {"draft", "cancelled"}:
        raise FoodError("لا يمكن عمل مرتجع على مسودة أو فاتورة ملغاة")
    if not purchase.stock_applied:
        raise FoodError("الفاتورة غير مستلمة في المخزون")

    lines = payload.get("items") or []
    if not lines:
        raise FoodError("اختر مادة واحدةً على الأقل للمرتجع")
    reason = str(payload.get("reason") or "").strip() or "سبب آخر"
    if reason not in RETURN_REASONS:
        reason = "سبب آخر"
    settlement = str(payload.get("settlement") or "credit").strip().lower()
    if settlement not in {"credit", "cash"}:
        settlement = "credit"
    note = str(payload.get("note") or "").strip() or None

    snapshots = {
        int(s.purchase_item_id): s
        for s in FoodPurchaseItemSnapshot.query.join(
            PurchaseItem, PurchaseItem.id == FoodPurchaseItemSnapshot.purchase_item_id
        ).filter(PurchaseItem.purchase_id == purchase.id).all()
    }
    if snapshots and any(int(s.tenant_id) != int(tenant_id) for s in snapshots.values()):
        raise FoodError("فاتورة الشراء غير موجودة")

    item_ids = [int(s.purchase_item_id) for s in snapshots.values()]
    returned_map = _returned_qty_by_item(tenant_id, item_ids)

    purchase_return = FoodPurchaseReturn(
        tenant_id=tenant_id,
        return_no=f"FPR-{datetime.utcnow():%Y%m%d%H%M%S%f}",
        purchase_id=purchase.id,
        supplier_id=purchase.supplier_id,
        warehouse_id=purchase.warehouse_id,
        employee_id=employee_id,
        reason=reason,
        note=note,
        settlement=settlement,
        total=0,
    )
    db.session.add(purchase_return)
    db.session.flush()

    total = 0
    for raw in lines:
        item_id = as_int(raw.get("purchase_item_id") or raw.get("item_id"), 0)
        snapshot = snapshots.get(item_id)
        item = db.session.get(PurchaseItem, item_id)
        if not snapshot or not item or int(item.purchase_id) != int(purchase.id):
            raise FoodError("سطر المرتجع لا ينتمي إلى الفاتورة")
        quantity = as_int(raw.get("quantity"), 0, minimum=1)
        already = returned_map.get(item_id, 0)
        original = int(item.quantity or 0)
        if already + quantity > original:
            raise FoodError(
                f"كمية المرتجع أكبر من المتبقي ({max(0, original - already)})"
            )
        factor = max(1, int(snapshot.unit_factor_snapshot or 1))
        # Return paid units only; base qty scales without re-adding bonus.
        quantity_base = quantity * factor
        amount = int(round(int(item.line_total or 0) * quantity / max(1, original)))
        batch_id = as_int(raw.get("batch_id"), 0) or None

        variant = _variant(tenant_id, int(snapshot.variant_id), lock=True)
        warehouse_id = snapshot.warehouse_id or purchase.warehouse_id
        if variant.profile.track_stock:
            before = int(variant.stock_base or 0)
            available = before
            if warehouse_id is not None:
                available = int(
                    _warehouse_stock(tenant_id, variant.id, warehouse_id, lock=True).stock_base or 0
                )
            if available < quantity_base:
                raise FoodError(
                    f"المخزون غير كافٍ لمرتجع {variant.variant_name} (متاح {available})"
                )

            # Prefer explicit batch; else purchase batches for this variant.
            batches = []
            if batch_id:
                batch = db.session.get(FoodExpiryBatch, batch_id)
                if not batch or int(batch.purchase_id or 0) != int(purchase.id):
                    raise FoodError("الدفعة المحددة لا تنتمي لفاتورة الشراء")
                if int(batch.variant_id) != int(variant.id):
                    raise FoodError("الدفعة لا تطابق المادة")
                batches = [batch]
            elif snapshot.expiry_date or variant.profile.track_batches:
                batches = (
                    FoodExpiryBatch.query.filter(
                        FoodExpiryBatch.tenant_id == tenant_id,
                        FoodExpiryBatch.variant_id == variant.id,
                        FoodExpiryBatch.purchase_id == purchase.id,
                        FoodExpiryBatch.quantity_base > 0,
                    )
                    .order_by(FoodExpiryBatch.id.desc())
                    .with_for_update()
                    .all()
                )
                if not batches and variant.profile.track_expiry:
                    raise FoodError(f"حدد دفعة الصلاحية لمرتجع {variant.variant_name}")

            if batches:
                available_batch = sum(int(b.quantity_base or 0) for b in batches)
                if available_batch < quantity_base:
                    raise FoodError(
                        f"كمية الدفعة غير كافية لمرتجع {variant.variant_name}"
                    )
                remaining = quantity_base
                used_batch_id = None
                for batch in batches:
                    reduced = min(remaining, int(batch.quantity_base or 0))
                    batch.quantity_base = int(batch.quantity_base or 0) - reduced
                    remaining -= reduced
                    used_batch_id = batch.id
                    if remaining <= 0:
                        break
                batch_id = used_batch_id

            base_cost = int(item.final_unit_cost or 0) // factor
            remaining_value = max(0, before * int(variant.average_cost or 0) - quantity_base * base_cost)
            _adjust_warehouse_stock(variant, warehouse_id, -quantity_base)
            after = int(variant.stock_base or 0)
            variant.average_cost = remaining_value // after if after else 0
            db.session.add(FoodInventoryMovement(
                tenant_id=tenant_id,
                variant_id=variant.id,
                unit_id=snapshot.unit_id,
                warehouse_id=warehouse_id,
                batch_id=batch_id,
                movement_type="purchase_return",
                quantity_base=-quantity_base,
                quantity_before=before,
                quantity_after=after,
                reference_type="food_purchase_return",
                reference_id=purchase_return.id,
                note=reason,
                employee_id=employee_id,
            ))

        db.session.add(FoodPurchaseReturnLine(
            tenant_id=tenant_id,
            return_id=purchase_return.id,
            purchase_item_id=item_id,
            snapshot_id=snapshot.id,
            batch_id=batch_id,
            quantity=quantity,
            quantity_base=quantity_base,
            amount=amount,
        ))
        returned_map[item_id] = already + quantity
        total += amount

    purchase_return.total = total

    supplier = db.session.get(Supplier, purchase.supplier_id)
    if supplier and total:
        supplier.total_debt = max(0, int(supplier.total_debt or 0) - total)
        reduce_remaining = min(int(purchase.remaining_total or 0), total)
        purchase.remaining_total = max(0, int(purchase.remaining_total or 0) - reduce_remaining)
        leftover = total - reduce_remaining
        if leftover:
            purchase.paid_total = max(0, int(purchase.paid_total or 0) - leftover)
            supplier.total_paid = max(0, int(supplier.total_paid or 0) - leftover)

    db.session.flush()
    return {
        "id": purchase_return.id,
        "return_no": purchase_return.return_no,
        "purchase_id": purchase.id,
        "total": total,
        "reason": reason,
        "settlement": settlement,
    }
