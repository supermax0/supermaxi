"""
تدقيق سلامة النظام المحاسبي (Accounting Integrity Audit)

مخرجات هذا التدقيق:
- كشف اختلافات المخزون (calculated vs actual)
- كشف عدم اتساق حالات الطلب/الدفع (Cancelled/Returned/Paid)
- كشف فواتير بمجموع عناصر لا يساوي الإجمالي
- كشف عناصر بيع بهامش سلبي (cost > price) للطلبات غير الملغاة/غير المرتجعة

لا يغيّر أي بيانات. يرجع JSON فقط.
"""

from __future__ import annotations

from typing import Any

from extensions import db
from sqlalchemy import func, and_, or_
from sqlalchemy import inspect, text

from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product

from utils.inventory_movements import get_all_products_movements_summary
from utils.assistant_analyzer import AssistantAnalyzer
from utils.order_status import RETURN_STATUSES, CANCELED_STATUSES, is_canceled, is_returned, is_completed, normalize_status
from utils.branch_migration import ensure_branch_schema
from utils.product_schema_guard import ensure_product_schema


def _current_engine():
    try:
        from flask import g

        tenant_slug = getattr(g, "tenant", None)
        if tenant_slug:
            from extensions_tenant import get_tenant_engine

            return get_tenant_engine(tenant_slug)
    except Exception:
        pass
    return db.session.get_bind() or db.engine


def _add_column_if_missing(engine, table: str, column: str, ddl: str) -> None:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    cols = {col["name"] for col in inspector.get_columns(table)}
    if column in cols:
        return
    with engine.begin() as conn:
        conn.execute(text(ddl))


def _ensure_audit_schema() -> None:
    ensure_product_schema()
    engine = _current_engine()
    datetime_type = "TIMESTAMP" if engine.dialect.name == "postgresql" else "DATETIME"

    invoice_additions = {
        "tenant_id": "ALTER TABLE invoice ADD COLUMN tenant_id INTEGER",
        "branch_id": "ALTER TABLE invoice ADD COLUMN branch_id INTEGER",
        "paid_amount": "ALTER TABLE invoice ADD COLUMN paid_amount INTEGER DEFAULT 0",
        "delivery_agent_id": "ALTER TABLE invoice ADD COLUMN delivery_agent_id INTEGER",
        "page_id": "ALTER TABLE invoice ADD COLUMN page_id INTEGER",
        "page_name": "ALTER TABLE invoice ADD COLUMN page_name VARCHAR(150)",
        "barcode": "ALTER TABLE invoice ADD COLUMN barcode VARCHAR(100)",
        "shipping_barcode": "ALTER TABLE invoice ADD COLUMN shipping_barcode VARCHAR(100)",
        "order_video_path": "ALTER TABLE invoice ADD COLUMN order_video_path VARCHAR(255)",
        "order_video_original_name": "ALTER TABLE invoice ADD COLUMN order_video_original_name VARCHAR(255)",
        "order_video_thumbnail_path": "ALTER TABLE invoice ADD COLUMN order_video_thumbnail_path VARCHAR(255)",
        "order_video_size_mb": "ALTER TABLE invoice ADD COLUMN order_video_size_mb FLOAT",
        "order_video_duration_sec": "ALTER TABLE invoice ADD COLUMN order_video_duration_sec FLOAT",
        "order_video_recorded_at": f"ALTER TABLE invoice ADD COLUMN order_video_recorded_at {datetime_type}",
        "employee_commission_settled_at": f"ALTER TABLE invoice ADD COLUMN employee_commission_settled_at {datetime_type}",
        "scheduled_date": f"ALTER TABLE invoice ADD COLUMN scheduled_date {datetime_type}",
    }
    for column, ddl in invoice_additions.items():
        _add_column_if_missing(engine, "invoice", column, ddl)

    ensure_branch_schema()


def audit_accounting_integrity(limit: int = 200) -> dict[str, Any]:
    """
    يرجع تقرير تدقيق شامل بصيغة JSON.
    limit: حد أقصى لعدد العناصر في القوائم التفصيلية لتجنب رد ضخم.
    """

    _ensure_audit_schema()

    report: dict[str, Any] = {
        "summary": {},
        "status_inconsistencies": [],
        "stock_imbalances": [],
        "invoice_total_mismatches": [],
        "negative_margin_items": [],
    }

    # -----------------------
    # 1) اختلافات المخزون
    # -----------------------
    summaries = get_all_products_movements_summary()
    imbalanced = [s for s in summaries if not s.get("is_balanced")]
    imbalanced.sort(key=lambda x: abs(int(x.get("difference") or 0)), reverse=True)
    report["stock_imbalances"] = imbalanced[:limit]

    # -----------------------
    # 2) عدم اتساق الحالات
    # -----------------------
    # أمثلة: ملغي لكن مسدد/جزئي، مرتجع لكن status ليس راجع/مرتجع، مسدد لكن status ما زال تم الطلب
    suspicious = Invoice.query.filter(
        or_(
            Invoice.status.in_(list(CANCELED_STATUSES)),
            Invoice.payment_status.in_(["ملغي", "مسدد", "جزئي"] + list(RETURN_STATUSES)),
            Invoice.status.in_(list(RETURN_STATUSES)),
        )
    ).order_by(Invoice.created_at.desc()).limit(5000).all()

    inconsistencies = []
    for inv in suspicious:
        s = normalize_status(getattr(inv, "status", None))
        p = normalize_status(getattr(inv, "payment_status", None))
        paid_amount = int(getattr(inv, "paid_amount", 0) or 0)

        issues = []
        if is_canceled(s, p) and (p in {"مسدد", "جزئي"} or paid_amount > 0):
            issues.append("ملغي لكن الدفع مسدد/جزئي أو يوجد مبلغ مدفوع")
        if p in RETURN_STATUSES and s not in RETURN_STATUSES:
            issues.append("payment_status راجع لكن status ليس ضمن حالات الراجع")
        if s in RETURN_STATUSES and p not in RETURN_STATUSES.union({"ملغي"}):
            issues.append("status راجع لكن payment_status ليس راجع/ملغي")
        if p == "مسدد" and s in {"تم الطلب", "جاري الشحن"}:
            issues.append("الدفع مسدد لكن حالة الطلب ما زالت غير مكتملة")
        if is_completed(s, p) and p == "غير مسدد":
            issues.append("حالة مكتملة لكن الدفع غير مسدد")

        if issues:
            inconsistencies.append(
                {
                    "invoice_id": inv.id,
                    "status": s,
                    "payment_status": p,
                    "total": int(getattr(inv, "total", 0) or 0),
                    "paid_amount": paid_amount,
                    "created_at": inv.created_at.isoformat() if getattr(inv, "created_at", None) else None,
                    "issues": issues,
                }
            )
        if len(inconsistencies) >= limit:
            break

    report["status_inconsistencies"] = inconsistencies

    # -----------------------
    # 3) اختلاف مجموع الفاتورة
    # -----------------------
    try:
        mismatches = AssistantAnalyzer.analyze_financial_errors()
    except Exception:
        mismatches = []
    report["invoice_total_mismatches"] = mismatches[:limit]

    # -----------------------
    # 4) هامش سلبي (cost > price) للطلبات غير الملغاة/غير المرتجعة
    # -----------------------
    negative_rows = (
        db.session.query(
            OrderItem.id,
            OrderItem.invoice_id,
            OrderItem.product_name,
            OrderItem.quantity,
            OrderItem.price,
            OrderItem.cost,
            (OrderItem.cost - OrderItem.price).label("loss_per_unit"),
        )
        .join(Invoice, Invoice.id == OrderItem.invoice_id)
        .filter(
            Invoice.status.notin_(list(CANCELED_STATUSES) + list(RETURN_STATUSES)),
            Invoice.payment_status.notin_(list(RETURN_STATUSES)),
            OrderItem.cost > OrderItem.price,
        )
        .order_by((OrderItem.cost - OrderItem.price).desc())
        .limit(limit)
        .all()
    )

    report["negative_margin_items"] = [
        {
            "order_item_id": r.id,
            "invoice_id": r.invoice_id,
            "product_name": r.product_name,
            "quantity": int(r.quantity or 0),
            "price": int(r.price or 0),
            "cost": int(r.cost or 0),
            "loss_per_unit": int(r.loss_per_unit or 0),
        }
        for r in negative_rows
    ]

    # -----------------------
    # Summary
    # -----------------------
    report["summary"] = {
        "products_total": Product.query.count(),
        "stock_imbalances_count": len(imbalanced),
        "status_inconsistencies_count": len(inconsistencies),
        "invoice_total_mismatches_count": len(mismatches),
        "negative_margin_items_count": len(report["negative_margin_items"]),
    }

    return report

