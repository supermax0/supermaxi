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

from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product

from utils.inventory_movements import get_all_products_movements_summary
from utils.assistant_analyzer import AssistantAnalyzer
from utils.order_status import RETURN_STATUSES, CANCELED_STATUSES, is_canceled, is_returned, is_completed, normalize_status


def audit_accounting_integrity(limit: int = 200) -> dict[str, Any]:
    """
    يرجع تقرير تدقيق شامل بصيغة JSON.
    limit: حد أقصى لعدد العناصر في القوائم التفصيلية لتجنب رد ضخم.
    """

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
            Invoice.payment_status.in_(["ملغي", "مرتجع", "مسدد", "جزئي"]),
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
        if p == "مرتجع" and s not in RETURN_STATUSES:
            issues.append("payment_status=مرتجع لكن status ليس ضمن حالات المرتجع")
        if s in RETURN_STATUSES and p not in {"مرتجع", "ملغي"}:
            issues.append("status مرتجع لكن payment_status ليس مرتجع/ملغي")
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
            Invoice.payment_status != "مرتجع",
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

