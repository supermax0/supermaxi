from __future__ import annotations

import re
from typing import Any

from flask import url_for

from models.invoice import Invoice
from routes.orders import build_public_order_view_token


def build_tracking_steps(invoice: Invoice | None) -> list[dict]:
    status = str(getattr(invoice, "status", "") or "").strip()
    shipping_status = str(getattr(invoice, "shipping_status", "") or "").strip()
    cancelled = any(word in status for word in ("ملغي", "إلغاء", "مرتجع"))
    delivered = any(word in f"{status} {shipping_status}" for word in ("تم التوصيل", "مكتمل", "مسلم"))
    shipping = any(word in f"{status} {shipping_status}" for word in ("شحن", "توصيل", "قيد"))
    if cancelled:
        return [
            {"label": "تم استلام الطلب", "hint": "وصلنا طلبك", "done": True, "active": False},
            {"label": "تم إلغاء الطلب", "hint": status or "الطلب ملغي", "done": True, "active": True},
        ]
    return [
        {
            "label": "تم استلام الطلب",
            "hint": "وصلنا طلبك بنجاح",
            "done": bool(invoice),
            "active": bool(invoice) and not shipping and not delivered and not cancelled,
        },
        {
            "label": "قيد التجهيز",
            "hint": "يتم مراجعة الطلب وتجهيزه",
            "done": shipping or delivered,
            "active": shipping and not delivered and not cancelled,
        },
        {
            "label": "قيد التوصيل",
            "hint": shipping_status or "بانتظار شركة التوصيل",
            "done": delivered,
            "active": shipping and not delivered and not cancelled,
        },
        {
            "label": "تم التوصيل",
            "hint": "اكتمل الطلب",
            "done": delivered,
            "active": delivered and not cancelled,
        },
    ]


def lookup_order(invoice_id_raw: str, phone_raw: str) -> dict[str, Any]:
    try:
        invoice_id = int(str(invoice_id_raw or "").strip())
    except (TypeError, ValueError):
        invoice_id = 0
    phone = re.sub(r"\D+", "", str(phone_raw or ""))
    if invoice_id <= 0 or not phone:
        return {
            "found": False,
            "error": "أدخل رقم طلب ورقم هاتف صحيح.",
            "steps": [],
            "public_url": "",
            "status": "",
        }

    invoice = Invoice.query.get(invoice_id)
    customer_phone = re.sub(r"\D+", "", str(getattr(getattr(invoice, "customer", None), "phone", "")))
    if not invoice or (phone and customer_phone and phone != customer_phone):
        return {
            "found": False,
            "error": "لم يتم العثور على الطلب بهذه البيانات.",
            "steps": [],
            "public_url": "",
            "status": "",
        }

    public_url = ""
    try:
        token = build_public_order_view_token(invoice.id)
        public_url = url_for("orders.public_order_view", token=token)
    except Exception:
        public_url = ""

    status = str(getattr(invoice, "status", "") or "").strip()
    shipping_status = str(getattr(invoice, "shipping_status", "") or "").strip()
    return {
        "found": True,
        "error": "",
        "invoice_id": invoice.id,
        "status": status or shipping_status or "قيد المعالجة",
        "steps": build_tracking_steps(invoice),
        "public_url": public_url,
        "grand_total": int(invoice.total or 0),
        "customer_name": str(getattr(invoice, "customer_name", "") or ""),
    }
