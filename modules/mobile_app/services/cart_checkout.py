"""Mobile cart + checkout against Finora Invoice pipeline."""
from __future__ import annotations

from datetime import datetime

from extensions import db
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from modules.mobile_app.models import (
    MobileCart,
    MobileCartItem,
    MobileOrderAttribution,
    MobileUser,
    MobileVideoProduct,
)
from modules.mobile_app.services.catalog import stock_label, to_mobile_product
from modules.storefront.services.checkout_service import StorefrontCheckoutService
from modules.storefront.services.tracking_service import build_tracking_steps


class CartError(Exception):
    def __init__(self, message: str, code: str = "cart_error"):
        super().__init__(message)
        self.message = message
        self.code = code


def _get_or_create_cart(user_id: int) -> MobileCart:
    cart = MobileCart.query.filter_by(user_id=user_id).first()
    if cart:
        return cart
    cart = MobileCart(user_id=user_id)
    db.session.add(cart)
    db.session.flush()
    return cart


def _unit_price(product: Product, *, video_id: int | None = None) -> int:
    if video_id:
        link = MobileVideoProduct.query.filter_by(
            video_id=video_id, product_id=product.id
        ).first()
        if link and link.special_price is not None:
            return int(link.special_price)
    return int(product.sale_price or 0)


def _serialize_cart(cart: MobileCart) -> dict:
    from modules.mobile_app.services import discounts as discount_service
    from modules.mobile_app.services import rewards as reward_service

    items = []
    subtotal = 0
    for row in cart.items:
        product = db.session.get(Product, row.product_id)
        if product is None:
            continue
        price = _unit_price(product, video_id=row.video_id)
        live_price = price
        qty = int(row.quantity or 0)
        line_total = live_price * qty
        subtotal += line_total
        card = to_mobile_product(product)
        items.append(
            {
                "id": row.id,
                "product_id": product.id,
                "name": product.name,
                "quantity": qty,
                "unit_price": live_price,
                "line_total": line_total,
                "image_url": card.get("image_url") or "",
                "stock_status": stock_label(
                    int(product.quantity or 0), active=bool(product.active)
                ),
                "is_available": bool(product.active and int(product.quantity or 0) >= qty),
                "available_qty": max(0, int(product.quantity or 0)),
                "video_id": row.video_id,
            }
        )

    coupon_discount = 0
    coupon_code = cart.coupon_code
    if coupon_code:
        try:
            _, coupon_discount = discount_service.validate_coupon(
                coupon_code, user_id=cart.user_id, subtotal=subtotal
            )
        except discount_service.DiscountError:
            coupon_code = None
            coupon_discount = 0

    points_to_redeem = max(0, int(getattr(cart, "points_to_redeem", 0) or 0))
    points_discount = reward_service.points_to_discount(points_to_redeem)
    # Cap points discount so coupon + points never exceed subtotal
    remaining = max(0, subtotal - coupon_discount)
    if points_discount > remaining:
        # Reduce redeemable points to what fits
        points_discount = remaining
        points_to_redeem = reward_service.discount_to_points(points_discount)

    discount_amount = coupon_discount + points_discount
    grand = max(0, subtotal - discount_amount)

    return {
        "cart_id": cart.id,
        "items": items,
        "items_count": sum(i["quantity"] for i in items),
        "subtotal": subtotal,
        "discount_amount": discount_amount,
        "coupon_discount": coupon_discount,
        "points_discount": points_discount,
        "shipping_fee": 0,
        "grand_total": grand,
        "coupon_code": coupon_code,
        "points_to_redeem": points_to_redeem,
        "source_video_id": cart.source_video_id,
    }


def get_cart(user_id: int) -> dict:
    cart = _get_or_create_cart(user_id)
    db.session.commit()
    return _serialize_cart(cart)


def add_item(
    *,
    user_id: int,
    product_id: int,
    quantity: int = 1,
    video_id: int | None = None,
) -> dict:
    product = db.session.get(Product, product_id)
    if product is None or not product.active:
        raise CartError("المنتج غير متاح", "product_unavailable")
    available = max(0, int(product.quantity or 0))
    if available <= 0:
        raise CartError("المنتج غير متوفر حالياً", "out_of_stock")

    qty = max(1, min(int(quantity or 1), 999))
    cart = _get_or_create_cart(user_id)
    if video_id:
        cart.source_video_id = video_id
    item = MobileCartItem.query.filter_by(cart_id=cart.id, product_id=product_id).first()
    current = int(item.quantity) if item else 0
    if current + qty > available:
        remaining = max(0, available - current)
        if remaining <= 0:
            raise CartError("وصلت للحد المتاح من هذا المنتج", "stock_limit")
        raise CartError(f"الكمية المتاحة للإضافة هي {remaining} فقط", "stock_limit")

    if item:
        item.quantity = current + qty
        item.unit_price_snapshot = _unit_price(product, video_id=video_id or item.video_id)
        if video_id:
            item.video_id = video_id
    else:
        item = MobileCartItem(
            cart_id=cart.id,
            product_id=product_id,
            quantity=qty,
            unit_price_snapshot=_unit_price(product, video_id=video_id),
            video_id=video_id,
        )
        db.session.add(item)
    cart.updated_at = datetime.utcnow()
    db.session.commit()
    return _serialize_cart(cart)


def update_item(*, user_id: int, item_id: int, quantity: int) -> dict:
    cart = _get_or_create_cart(user_id)
    item = MobileCartItem.query.filter_by(id=item_id, cart_id=cart.id).first()
    if item is None:
        raise CartError("عنصر السلة غير موجود", "not_found")
    qty = int(quantity or 0)
    if qty <= 0:
        db.session.delete(item)
    else:
        product = db.session.get(Product, item.product_id)
        available = max(0, int(getattr(product, "quantity", 0) or 0))
        if product is None or not product.active:
            raise CartError("المنتج غير متاح", "product_unavailable")
        if qty > available:
            raise CartError(f"المتوفر حالياً {available} فقط", "stock_limit")
        item.quantity = qty
        item.unit_price_snapshot = _unit_price(product, video_id=item.video_id)
    cart.updated_at = datetime.utcnow()
    db.session.commit()
    return _serialize_cart(cart)


def remove_item(*, user_id: int, item_id: int) -> dict:
    return update_item(user_id=user_id, item_id=item_id, quantity=0)


def clear_cart(user_id: int) -> dict:
    cart = _get_or_create_cart(user_id)
    for item in list(cart.items):
        db.session.delete(item)
    cart.coupon_code = None
    cart.points_to_redeem = 0
    cart.source_video_id = None
    db.session.commit()
    return _serialize_cart(cart)


def apply_coupon(user_id: int, code: str) -> dict:
    from modules.mobile_app.services import discounts as discount_service

    cart = _get_or_create_cart(user_id)
    data = _serialize_cart(cart)
    try:
        coupon, _ = discount_service.validate_coupon(
            code, user_id=user_id, subtotal=int(data["subtotal"])
        )
    except discount_service.DiscountError as exc:
        raise CartError(exc.message, exc.code) from exc
    cart.coupon_code = coupon.code
    cart.updated_at = datetime.utcnow()
    db.session.commit()
    return _serialize_cart(cart)


def remove_coupon(user_id: int) -> dict:
    cart = _get_or_create_cart(user_id)
    cart.coupon_code = None
    cart.updated_at = datetime.utcnow()
    db.session.commit()
    return _serialize_cart(cart)


def apply_points(user_id: int, points: int) -> dict:
    from modules.mobile_app.services import rewards as reward_service

    cart = _get_or_create_cart(user_id)
    pts = max(0, int(points or 0))
    summary = reward_service.get_rewards_summary(user_id)
    if pts > int(summary["balance"]):
        raise CartError("رصيد النقاط غير كافٍ", "insufficient_points")
    cart.points_to_redeem = pts
    cart.updated_at = datetime.utcnow()
    db.session.commit()
    return _serialize_cart(cart)


def remove_points(user_id: int) -> dict:
    cart = _get_or_create_cart(user_id)
    cart.points_to_redeem = 0
    cart.updated_at = datetime.utcnow()
    db.session.commit()
    return _serialize_cart(cart)


def validate_cart(user_id: int) -> tuple[bool, str, dict]:
    cart_data = get_cart(user_id)
    if not cart_data["items"]:
        return False, "السلة فارغة", cart_data
    for item in cart_data["items"]:
        if not item["is_available"]:
            return False, f"المنتج غير متوفر بالكمية المطلوبة: {item['name']}", cart_data
    return True, "السلة صالحة", cart_data


def checkout_preview(user_id: int, *, shipping_fee: int = 0) -> dict:
    ok, message, cart_data = validate_cart(user_id)
    shipping = max(0, int(shipping_fee or 0))
    cart_data["shipping_fee"] = shipping
    cart_data["grand_total"] = int(cart_data["subtotal"]) - int(cart_data["discount_amount"]) + shipping
    cart_data["valid"] = ok
    cart_data["message"] = message
    return cart_data


def place_order(
    *,
    user_id: int,
    customer_name: str,
    phone: str,
    city: str,
    address: str,
    notes: str = "",
    shipping_fee: int = 0,
    video_id: int | None = None,
) -> dict:
    from modules.mobile_app.services import discounts as discount_service
    from modules.mobile_app.services import rewards as reward_service

    ok, message, cart_data = validate_cart(user_id)
    if not ok:
        raise CartError(message, "cart_invalid")

    user = db.session.get(MobileUser, user_id)
    cart = _get_or_create_cart(user_id)
    attribution_video = video_id or cart.source_video_id

    checkout_items = []
    for item in cart_data["items"]:
        checkout_items.append(
            {
                "id": item["product_id"],
                "name": item["name"],
                "quantity": item["quantity"],
                "line_total": item["line_total"],
                "unit_price": item["unit_price"],
            }
        )

    form_data = {
        "customer_name": (customer_name or (user.name if user else "") or phone).strip(),
        "phone": (phone or (user.phone if user else "")).strip(),
        "city": (city or "").strip(),
        "address": (address or "").strip(),
        "notes": (notes or "").strip(),
    }

    coupon_id = None
    coupon_discount = int(cart_data.get("coupon_discount") or 0)
    points_discount = int(cart_data.get("points_discount") or 0)
    points_to_redeem = int(cart_data.get("points_to_redeem") or 0)
    discount_amount = int(cart_data.get("discount_amount") or 0)

    if cart.coupon_code:
        try:
            coupon, coupon_discount = discount_service.validate_coupon(
                cart.coupon_code, user_id=user_id, subtotal=int(cart_data["subtotal"])
            )
            coupon_id = coupon.id
        except discount_service.DiscountError as exc:
            raise CartError(exc.message, exc.code) from exc

    if points_to_redeem > 0:
        summary = reward_service.get_rewards_summary(user_id)
        if points_to_redeem > int(summary["balance"]):
            raise CartError("رصيد النقاط غير كافٍ", "insufficient_points")
        points_discount = reward_service.points_to_discount(points_to_redeem)
        discount_amount = coupon_discount + points_discount
        if discount_amount > int(cart_data["subtotal"]):
            discount_amount = int(cart_data["subtotal"])

    ok_inv, msg, payload = _create_mobile_invoice(
        checkout_items=checkout_items,
        form_data=form_data,
        shipping_fee=max(0, int(shipping_fee or 0)),
        video_id=attribution_video,
        mobile_user_id=user_id,
        discount_amount=discount_amount,
        coupon_id=coupon_id,
        points_to_redeem=points_to_redeem,
        points_discount=points_discount,
        coupon_discount=coupon_discount,
    )
    if not ok_inv:
        raise CartError(msg, "checkout_failed")

    clear_cart(user_id)
    try:
        from modules.mobile_app.services import notifications as notif_service

        invoice_id = int(payload.get("invoice_id") or 0)
        notif_service.create_user_notification(
            user_id=user_id,
            title="تم استلام طلبك",
            body=f"طلبك رقم #{invoice_id} قيد المراجعة.",
            notification_type="order_placed",
            data={"order_id": invoice_id, "screen": "order_detail"},
        )
    except Exception:
        pass
    return {
        "order": payload,
        "message": msg,
    }


def _create_mobile_invoice(
    *,
    checkout_items: list[dict],
    form_data: dict,
    shipping_fee: int,
    video_id: int | None,
    mobile_user_id: int,
    discount_amount: int = 0,
    coupon_id: int | None = None,
    points_to_redeem: int = 0,
    points_discount: int = 0,
    coupon_discount: int = 0,
) -> tuple[bool, str, dict]:
    """Create Invoice using storefront checkout after normalizing line_total to unit*qty."""
    from modules.mobile_app.services import discounts as discount_service
    from modules.mobile_app.services import rewards as reward_service

    service = StorefrontCheckoutService()
    sf_items = [
        {
            "id": i["id"],
            "name": i["name"],
            "quantity": i["quantity"],
            "line_total": int(i["unit_price"]) * int(i["quantity"]),
        }
        for i in checkout_items
    ]
    notes = form_data.get("notes") or ""
    attr = "source=mobile_app"
    if video_id:
        attr += f" | video_id={video_id}"
    if coupon_id:
        attr += f" | coupon_id={coupon_id}"
    form_data = {
        **form_data,
        "notes": f"{notes} | {attr}".strip(" |"),
    }
    ok, msg, payload = service.create_invoice_from_cart(
        sf_items,
        form_data,
        shipping_fee=shipping_fee,
        discount_amount=max(0, int(discount_amount or 0)),
    )
    if not ok:
        return False, msg, {}

    invoice_id = int(payload["invoice_id"])
    price_by_product = {int(i["id"]): int(i["unit_price"]) for i in checkout_items}
    invoice = db.session.get(Invoice, invoice_id)
    if invoice:
        new_total = 0
        for oi in OrderItem.query.filter_by(invoice_id=invoice.id).all():
            if oi.product_id in price_by_product:
                unit = price_by_product[oi.product_id]
                oi.price = unit
                oi.total = unit * int(oi.quantity or 0)
            new_total += int(oi.total or 0)
        invoice.total = new_total
        base_note = invoice.note or ""
        if "source=mobile_app" not in base_note:
            invoice.note = f"{base_note} | source=mobile_app"
        if video_id and f"video_id={video_id}" not in (invoice.note or ""):
            invoice.note = f"{invoice.note} | video_id={video_id}"
        db.session.add(
            MobileOrderAttribution(
                invoice_id=invoice.id,
                user_id=mobile_user_id,
                video_id=video_id,
                campaign_id=None,
                coupon_id=coupon_id,
                source="mobile_app",
            )
        )
        user = db.session.get(MobileUser, mobile_user_id)
        if user and not user.customer_id and invoice.customer_id:
            user.customer_id = invoice.customer_id
        db.session.commit()

        subtotal_before = sum(
            int(i["unit_price"]) * int(i["quantity"]) for i in checkout_items
        )
        if coupon_id and coupon_discount > 0:
            discount_service.record_coupon_redemption(
                coupon_id=coupon_id,
                user_id=mobile_user_id,
                invoice_id=invoice.id,
                discount_amount=coupon_discount,
            )
            db.session.commit()
        if points_to_redeem > 0 and points_discount > 0:
            reward_service.redeem_points_for_checkout(
                user_id=mobile_user_id,
                points=points_to_redeem,
                invoice_id=invoice.id,
                discount_amount=points_discount,
            )
        reward_service.queue_purchase_rewards(
            user_id=mobile_user_id,
            invoice=invoice,
            subtotal=max(0, subtotal_before - discount_amount),
        )

        payload["grand_total"] = int(invoice.total or 0)
        payload["status"] = invoice.status
        payload["attribution_video_id"] = video_id
        payload["discount_amount"] = discount_amount
        payload["coupon_id"] = coupon_id
    return True, msg, payload


def list_orders(user_id: int, *, limit: int = 30) -> list[dict]:
    user = db.session.get(MobileUser, user_id)
    if not user or not user.customer_id:
        # Also find via attribution
        attrs = (
            MobileOrderAttribution.query.filter_by(user_id=user_id)
            .order_by(MobileOrderAttribution.id.desc())
            .limit(limit)
            .all()
        )
        invoice_ids = [a.invoice_id for a in attrs]
        invoices = Invoice.query.filter(Invoice.id.in_(invoice_ids)).all() if invoice_ids else []
        by_id = {i.id: i for i in invoices}
        ordered = [by_id[i] for i in invoice_ids if i in by_id]
    else:
        ordered = (
            Invoice.query.filter_by(customer_id=user.customer_id)
            .order_by(Invoice.id.desc())
            .limit(limit)
            .all()
        )
    return [_order_summary(inv, user_id) for inv in ordered]


def get_order(user_id: int, invoice_id: int) -> dict | None:
    from modules.mobile_app.services import rewards as reward_service

    invoice = db.session.get(Invoice, invoice_id)
    if invoice is None:
        return None
    if not _user_owns_invoice(user_id, invoice):
        return None
    reward_service.sync_pending_rewards_for_user(user_id)
    return _order_detail(invoice, user_id)


def cancel_order(user_id: int, invoice_id: int) -> dict:
    from modules.mobile_app.services import rewards as reward_service

    invoice = db.session.get(Invoice, invoice_id)
    if invoice is None or not _user_owns_invoice(user_id, invoice):
        raise CartError("الطلب غير موجود", "not_found")
    status = str(invoice.status or "")
    if status not in {"تم الطلب"}:
        raise CartError("لا يمكن إلغاء الطلب في حالته الحالية", "cancel_not_allowed")
    invoice.status = "ملغي"
    db.session.commit()
    reward_service.cancel_rewards_for_invoice(invoice_id)
    return _order_detail(invoice, user_id)


def _user_owns_invoice(user_id: int, invoice: Invoice) -> bool:
    user = db.session.get(MobileUser, user_id)
    if user and user.customer_id and invoice.customer_id == user.customer_id:
        return True
    attr = MobileOrderAttribution.query.filter_by(
        invoice_id=invoice.id, user_id=user_id
    ).first()
    return attr is not None


def _order_summary(invoice: Invoice, user_id: int) -> dict:
    attr = MobileOrderAttribution.query.filter_by(invoice_id=invoice.id).first()
    return {
        "id": invoice.id,
        "status": invoice.status,
        "payment_status": invoice.payment_status,
        "total": int(invoice.total or 0),
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
        "video_id": attr.video_id if attr else None,
        "steps": build_tracking_steps(invoice),
    }


def _order_detail(invoice: Invoice, user_id: int) -> dict:
    items = []
    for oi in OrderItem.query.filter_by(invoice_id=invoice.id).all():
        items.append(
            {
                "product_id": oi.product_id,
                "name": oi.product_name,
                "quantity": int(oi.quantity or 0),
                "unit_price": int(oi.price or 0),
                "line_total": int(oi.total or 0),
            }
        )
    summary = _order_summary(invoice, user_id)
    summary["items"] = items
    summary["customer_name"] = invoice.customer_name
    summary["note"] = invoice.note
    return summary
