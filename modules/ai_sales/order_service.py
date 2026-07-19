"""Create tenant orders from confirmed Sales AI conversations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import re

from extensions import db
from models.invoice import Invoice
from models.order_item import OrderItem
from models.page import Page
from models.product import Product
from utils.branch_migration import get_default_branch
from utils.order_stock_lock import (
    apply_stock_actions,
    check_stock_rows,
    clear_order_stock_lock,
    mark_order_stock_locked,
)
from utils.order_stock_policy import deferred_stock_enabled


_DIGIT_TRANSLATION = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)
_QUANTITY_WORDS = {
    "واحد": 1,
    "واحده": 1,
    "وحده": 1,
    "اثنين": 2,
    "اثنان": 2,
    "ثنين": 2,
    "وحدتين": 2,
    "ثلاثه": 3,
    "ثلاث": 3,
    "اربعه": 4,
    "اربع": 4,
    "خمسه": 5,
    "خمس": 5,
    "سته": 6,
    "ست": 6,
    "سبعه": 7,
    "سبع": 7,
    "ثمانيه": 8,
    "ثمان": 8,
    "تسعه": 9,
    "تسع": 9,
    "عشره": 10,
    "عشر": 10,
}


@dataclass
class AIOrderResult:
    status: str
    invoice: Invoice | None = None
    message: str = ""
    pending_order: dict[str, Any] | None = None


def _format_price(value: Any) -> str:
    return f"{int(value or 0):,} د.ع"


def _normalize_confirmation(value: str) -> str:
    value = (value or "").translate(_DIGIT_TRANSLATION).strip().lower()
    value = value.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه"}))
    return re.sub(r"[^\w\s]", " ", value).strip()


def is_explicit_order_confirmation(value: str) -> bool:
    normalized = _normalize_confirmation(value)
    exact = {
        "اي", "نعم", "تمام", "اكد", "ثبت", "موافق",
        "اي اكد", "اي ثبت", "نعم اكد", "تمام اكد", "تمام ثبت",
        "اكد الطلب", "ثبت الطلب", "موافق اكد الطلب",
    }
    return normalized in exact


def is_order_revision_or_cancellation(value: str) -> bool:
    normalized = _normalize_confirmation(value)
    if normalized in {"لا", "كلا", "الغي", "الغيه", "الغاء", "مو صحيح"}:
        return True
    return any(phrase in normalized for phrase in ("الغي الطلب", "غير الطلب", "عدل الطلب", "غير المنتج"))


def extract_order_quantity(value: str) -> int | None:
    """Read an explicitly requested item count without mistaking size or phone numbers."""
    normalized = re.sub(r"\s+", " ", _normalize_confirmation(value))
    quantity_token = r"(\d{1,2}|" + "|".join(_QUANTITY_WORDS) + r")"
    patterns = (
        rf"(?:العدد|عدد|الكميه|كميه)\s*(?:يصير|يكون|خليه|خليها|هو)?\s*{quantity_token}",
        rf"(?:اريد|خلي|عدل|غير)\s+(?:لي\s+)?{quantity_token}\s*(?:قطع|قطعه|حبات|حبه|وحدات|وحده)",
        rf"{quantity_token}\s*(?:قطع|قطعه|حبات|حبه|وحدات|وحده)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        token = next((part for part in match.groups() if part), "")
        quantity = int(token) if token.isdigit() else _QUANTITY_WORDS.get(token)
        if quantity and 1 <= quantity <= 99:
            return quantity
    return None


def is_order_summary_request(value: str) -> bool:
    normalized = _normalize_confirmation(value)
    return "ملخص" in normalized or normalized in {"اعرض الطلب", "وريني الطلب", "عرض الطلب"}


def order_data_complete(order_data: dict[str, Any]) -> bool:
    has_address = bool(
        str(order_data.get("location_url") or "").strip()
        or str(order_data.get("area") or "").strip()
        or str(order_data.get("city") or "").strip()
    )
    return bool(
        str(order_data.get("name") or "").strip()
        and str(order_data.get("phone") or "").strip()
        and has_address
    )


def build_pending_order(
    product: dict[str, Any],
    order_data: dict[str, Any],
    *,
    message_id: int,
    selection_message_id: int,
    quantity: int = 1,
) -> dict[str, Any]:
    quantity = max(int(quantity or 1), 1)
    unit_price = int(product.get("price") or 0)
    return {
        "product_id": int(product.get("product_id") or 0),
        "product_name": str(product.get("official_name") or product.get("name") or "المنتج")[:150],
        "quantity": quantity,
        "unit_price": unit_price,
        "total": unit_price * quantity,
        "customer_data": {
            key: order_data.get(key)
            for key in ("name", "phone", "city", "area", "landmark", "location_url")
            if order_data.get(key)
        },
        "prepared_from_message_id": int(message_id),
        "selection_message_id": int(selection_message_id),
        "selection_product_id": int(product.get("product_id") or 0),
        "prepared_at": datetime.utcnow().isoformat(),
    }


def refresh_pending_order(pending: dict[str, Any], product: dict[str, Any]) -> dict[str, Any]:
    """Refresh a pending order from live product data while preserving its selection proof."""
    refreshed = dict(pending)
    quantity = max(int(refreshed.get("quantity") or 1), 1)
    unit_price = int(product.get("price") or refreshed.get("unit_price") or 0)
    refreshed.update({
        "product_id": int(product.get("product_id") or refreshed.get("product_id") or 0),
        "product_name": str(
            product.get("official_name") or product.get("name") or refreshed.get("product_name") or "المنتج"
        )[:150],
        "quantity": quantity,
        "unit_price": unit_price,
        "total": unit_price * quantity,
        "refreshed_at": datetime.utcnow().isoformat(),
    })
    return refreshed


def update_pending_order_quantity(pending: dict[str, Any], quantity: int) -> dict[str, Any]:
    updated = dict(pending)
    updated["quantity"] = max(min(int(quantity or 1), 99), 1)
    updated["total"] = int(updated.get("unit_price") or 0) * updated["quantity"]
    updated["updated_at"] = datetime.utcnow().isoformat()
    return updated


def pending_order_summary(pending: dict[str, Any], *, price_changed: bool = False) -> str:
    customer = pending.get("customer_data") or {}
    address = " / ".join(
        str(customer.get(key) or "").strip()
        for key in ("city", "area", "landmark")
        if str(customer.get(key) or "").strip()
    )
    location_url = str(customer.get("location_url") or "").strip()
    delivery = address or location_url or "مسجل بالمحادثة"
    heading = "تغير سعر المنتج، وهذا الملخص المحدث:" if price_changed else "أأكد وياك ملخص الطلب:"
    return (
        f"{heading}\n\n"
        f"• المنتج: {pending.get('product_name') or 'المنتج'}\n"
        f"• العدد: {int(pending.get('quantity') or 1)}\n"
        f"• سعر الوحدة: {_format_price(pending.get('unit_price'))}\n"
        f"• المجموع: {_format_price(pending.get('total'))}\n"
        f"• الاسم: {customer.get('name') or '—'}\n"
        f"• الهاتف: {customer.get('phone') or '—'}\n"
        f"• عنوان التوصيل: {delivery}\n\n"
        "إذا كل البيانات صحيحة، اكتب: أكد الطلب."
    )


def _order_page(channel) -> Page | None:
    name = str(getattr(channel, "name", "") or "").strip()[:150]
    if not name:
        return None
    wanted = name.casefold()
    page = next((row for row in Page.query.all() if (row.name or "").strip().casefold() == wanted), None)
    if page:
        return page
    page = Page(name=name)
    db.session.add(page)
    db.session.flush()
    return page


def _source_marker(conversation_id: int) -> str:
    return f"[AI-SALES-CONVERSATION:{int(conversation_id)}]"


def _booking_marker(conversation_id: int, pending: dict[str, Any]) -> str:
    prepared_message_id = int(pending.get("prepared_from_message_id") or 0)
    return f"[AI-SALES-BOOKING:{int(conversation_id)}:{prepared_message_id}]"


def find_existing_ai_order(conversation_id: int, pending: dict[str, Any] | None = None) -> Invoice | None:
    marker = _booking_marker(conversation_id, pending) if pending else _source_marker(conversation_id)
    return Invoice.query.filter(Invoice.note.contains(marker)).order_by(Invoice.id.desc()).first()


def create_confirmed_order(conversation, customer, pending: dict[str, Any]) -> AIOrderResult:
    product_id = int(pending.get("product_id") or 0)
    selection_product_id = int(pending.get("selection_product_id") or 0)
    selection_message_id = int(pending.get("selection_message_id") or 0)
    if not selection_message_id or selection_product_id != product_id:
        return AIOrderResult(
            status="invalid_selection",
            message="قبل ما أثبت الطلب، اختار المنتج المطلوب بشكل صريح حتى ما أسجل لك منتج غيره.",
        )

    existing = find_existing_ai_order(conversation.id, pending)
    if existing:
        return AIOrderResult(status="already_created", invoice=existing)

    quantity = max(int(pending.get("quantity") or 1), 1)
    product = Product.query.get(product_id)
    if not product or not product.active:
        return AIOrderResult(status="unavailable", message="المنتج لم يعد متاحاً للحجز. راح أراجعلك بديل مناسب.")

    current_price = int(product.sale_price or 0)
    if current_price <= 0:
        return AIOrderResult(status="unavailable", message="سعر المنتج يحتاج مراجعة من الموظف قبل تثبيت الطلب.")
    if current_price != int(pending.get("unit_price") or 0):
        refreshed = dict(pending)
        refreshed.update({
            "product_name": product.name,
            "unit_price": current_price,
            "total": current_price * quantity,
            "prepared_at": datetime.utcnow().isoformat(),
        })
        return AIOrderResult(
            status="reconfirm",
            message=pending_order_summary(refreshed, price_changed=True),
            pending_order=refreshed,
        )

    if not customer:
        return AIOrderResult(status="invalid_customer", message="بقي عندي رقم الهاتف والاسم حتى أثبت الطلب بشكل صحيح.")

    default_branch = get_default_branch()
    preferred_branch_id = default_branch.id if default_branch else None
    stock_rows = [{"product": product, "product_id": product.id, "quantity": quantity}]
    defer_stock = deferred_stock_enabled()
    stock_check = None if defer_stock else check_stock_rows(stock_rows, preferred_branch_id=preferred_branch_id)
    page = _order_page(conversation.channel)
    customer_data = pending.get("customer_data") or {}
    source_details = " | ".join(
        part for part in (
            "طلب من Finora Sales AI",
            _source_marker(conversation.id),
            _booking_marker(conversation.id, pending),
            f"channel={conversation.channel.channel_type}",
            f"page={conversation.channel.name}",
            f"contact={conversation.external_contact_id}",
            f"location={customer_data.get('location_url')}" if customer_data.get("location_url") else "",
        )
        if part
    )
    invoice = Invoice(
        customer_id=customer.id,
        customer_name=customer.name,
        employee_id=None,
        employee_name="Finora Sales AI",
        tenant_id=getattr(product, "tenant_id", None),
        branch_id=preferred_branch_id,
        total=current_price * quantity,
        status="تم الطلب",
        payment_status="غير مسدد",
        note=source_details,
        page_id=page.id if page else None,
        page_name=page.name if page else conversation.channel.name,
        created_at=datetime.utcnow(),
        stock_is_deducted=False,
    )
    db.session.add(invoice)
    db.session.flush()

    fulfillment_branch_id = None
    if stock_check and stock_check.can_fulfill and stock_check.actions:
        fulfillment_branch_id = stock_check.actions[0].fulfillment_branch_id
        if fulfillment_branch_id:
            invoice.branch_id = fulfillment_branch_id
    db.session.add(
        OrderItem(
            invoice_id=invoice.id,
            product_id=product.id,
            product_name=product.name,
            quantity=quantity,
            price=current_price,
            cost=int(product.buy_price or 0),
            total=current_price * quantity,
            fulfillment_branch_id=fulfillment_branch_id,
        )
    )
    db.session.flush()

    if defer_stock:
        clear_order_stock_lock(invoice)
    elif stock_check and stock_check.can_fulfill:
        apply_stock_actions(stock_check.actions, invoice=invoice)
        invoice.stock_is_deducted = True
        invoice.stock_deducted_at = datetime.utcnow()
    else:
        mark_order_stock_locked(invoice, stock_check.reason_text if stock_check else "")

    db.session.flush()
    return AIOrderResult(status="created", invoice=invoice)
