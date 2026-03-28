from __future__ import annotations

import json
from datetime import datetime

from flask import Blueprint, abort, current_app, g, redirect, render_template, request, url_for

from extensions import db
from models.customer import Customer
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from utils.inventory_movements import validate_sale_quantity


storefront_bp = Blueprint("storefront", __name__, url_prefix="/shop")


@storefront_bp.before_request
def _storefront_bind_tenant():
    """ربط قاعدة بيانات المستأجر عندما يكون slug في المسار (زيارة بدون تسجيل دخول)."""
    va = getattr(request, "view_args", None) or {}
    slug = va.get("tenant_slug")
    if slug is None:
        return
    slug = str(slug).strip()
    if not slug:
        abort(404)
    g.tenant = slug


def _product_meta(product: Product) -> dict:
    raw = (product.meta_json or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _unique_strings(values: list[str]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        s = str(value or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        items.append(s)
    return items


def _product_gallery(product: Product, meta: dict) -> list[str]:
    gallery: list[str] = []
    if product.image_url:
        gallery.append(str(product.image_url))
    for key in ("gallery", "images", "photos"):
        value = meta.get(key)
        if isinstance(value, list):
            gallery.extend(str(item or "").strip() for item in value)
    return _unique_strings(gallery)


def _product_specs(meta: dict) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    specs_text = str(meta.get("specs_text") or "").strip()
    if specs_text:
        for line in specs_text.splitlines():
            row = line.strip(" -\t\r\n")
            if not row:
                continue
            if ":" in row:
                key, value = row.split(":", 1)
            elif " - " in row:
                key, value = row.split(" - ", 1)
            else:
                key, value = "تفصيل", row
            key = key.strip()
            value = value.strip()
            if value:
                specs.append({"label": key or "تفصيل", "value": value})

    if specs:
        return specs

    for key, label in (
        ("brand", "العلامة"),
        ("category", "الصنف"),
        ("subcategory", "التصنيف الفرعي"),
        ("unit", "الوحدة"),
        ("warranty", "الضمان"),
        ("weight", "الوزن"),
        ("color", "اللون"),
        ("size", "القياس"),
        ("model", "الموديل"),
    ):
        value = str(meta.get(key) or "").strip()
        if value:
            specs.append({"label": label, "value": value})
    return specs


def _product_card(product: Product, shop_slug: str) -> dict:
    meta = _product_meta(product)
    gallery = _product_gallery(product, meta)
    book_suffix = "?book=1#booking-form"
    if shop_slug:
        detail = url_for("storefront.product_detail", tenant_slug=shop_slug, product_id=product.id)
    else:
        detail = url_for("storefront.product_detail_legacy", product_id=product.id)
    return {
        "id": product.id,
        "name": product.name,
        "price": int(product.sale_price or 0),
        "description": str(product.description or "").strip(),
        "image_url": gallery[0] if gallery else "",
        "gallery": gallery,
        "video_url": str(meta.get("video_url") or "").strip(),
        "specs": _product_specs(meta),
        "short_specs": " | ".join(
            f"{item['label']}: {item['value']}" for item in _product_specs(meta)[:3]
        ),
        "badge": str(meta.get("store_badge") or meta.get("category") or "").strip(),
        "stock": int(product.quantity or 0),
        "is_available": bool(product.active and int(product.quantity or 0) > 0),
        "book_url": detail + book_suffix,
        "url": detail,
    }


def _save_storefront_booking(product: Product, form_data: dict) -> tuple[bool, str, dict]:
    name = str(form_data.get("customer_name") or "").strip()
    phone = str(form_data.get("phone") or "").strip()
    city = str(form_data.get("city") or "").strip()
    address = str(form_data.get("address") or "").strip()
    notes = str(form_data.get("notes") or "").strip()

    try:
        quantity = int(form_data.get("quantity") or 1)
    except (TypeError, ValueError):
        quantity = 1
    quantity = max(1, min(quantity, 99999))

    if not name:
        return False, "يرجى إدخال الاسم الكامل.", {}
    if not phone:
        return False, "يرجى إدخال رقم الهاتف.", {}
    if not address:
        return False, "يرجى إدخال العنوان.", {}

    stock_check = validate_sale_quantity(product.id, quantity)
    if not stock_check.get("valid"):
        return False, str(stock_check.get("message") or "الكمية المطلوبة غير متوفرة حالياً."), {}

    customer = Customer.query.filter_by(phone=phone).first()
    if customer:
        customer.name = name
        if city:
            customer.city = city
        if address:
            customer.address = address
        if notes:
            customer.notes = notes
    else:
        customer = Customer(
            name=name,
            phone=phone,
            city=city or None,
            address=address,
            notes=notes or None,
            tenant_id=getattr(product, "tenant_id", None),
        )
        db.session.add(customer)
        db.session.flush()

    invoice = Invoice(
        customer_id=customer.id,
        customer_name=customer.name,
        employee_id=None,
        employee_name=None,
        total=0,
        status="حجز",
        payment_status="غير مسدد",
        note=f"طلب من متجر المنتجات | product_id={product.id}",
        created_at=datetime.utcnow(),
    )
    db.session.add(invoice)
    db.session.flush()

    total = int(product.sale_price or 0) * quantity
    item = OrderItem(
        invoice_id=invoice.id,
        product_id=product.id,
        product_name=product.name,
        quantity=quantity,
        price=int(product.sale_price or 0),
        cost=int(product.buy_price or 0),
        total=total,
    )
    db.session.add(item)
    product.quantity = int(product.quantity or 0) - quantity
    invoice.total = total
    db.session.commit()

    return True, "تم استلام طلبك بنجاح.", {
        "invoice_id": invoice.id,
        "quantity": quantity,
        "customer_name": customer.name,
    }


def _resolved_shop_slug(tenant_slug_from_url: str | None) -> str:
    s = (tenant_slug_from_url or "").strip()
    if s:
        return s
    return (current_app.config.get("STOREFRONT_DEFAULT_TENANT_SLUG") or "").strip()


def _run_product_detail(product_id: int, shop_slug: str):
    product = Product.query.get_or_404(product_id)
    if not product.active:
        abort(404)

    booking_error = ""
    booking_success = None
    booking_form = {
        "customer_name": "",
        "phone": "",
        "city": "",
        "address": "",
        "quantity": "1",
        "notes": "",
    }

    if request.method == "POST":
        booking_form = {
            "customer_name": str(request.form.get("customer_name") or "").strip(),
            "phone": str(request.form.get("phone") or "").strip(),
            "city": str(request.form.get("city") or "").strip(),
            "address": str(request.form.get("address") or "").strip(),
            "quantity": str(request.form.get("quantity") or "1").strip(),
            "notes": str(request.form.get("notes") or "").strip(),
        }
        ok, msg, payload = _save_storefront_booking(product, booking_form)
        if ok:
            booking_success = {
                "message": msg,
                "invoice_id": payload.get("invoice_id"),
            }
            booking_form["quantity"] = "1"
            booking_form["notes"] = ""
        else:
            booking_error = msg

    card = _product_card(product, shop_slug)
    related = (
        Product.query.filter(Product.active == True, Product.id != product.id)  # noqa: E712
        .order_by(Product.id.desc())
        .limit(4)
        .all()
    )
    related_cards = [_product_card(item, shop_slug) for item in related]
    return render_template(
        "storefront/product_detail.html",
        product=card,
        related_products=related_cards,
        booking_form=booking_form,
        booking_error=booking_error,
        booking_success=booking_success,
        shop_tenant_slug=shop_slug,
    )


# يُسجَّل قبل /<tenant_slug>/product/ حتى لا يُفسَّر "product" كاسم مستأجر.
@storefront_bp.route("/product/<int:product_id>", methods=["GET", "POST"])
def product_detail_legacy(product_id: int):
    slug = (current_app.config.get("STOREFRONT_DEFAULT_TENANT_SLUG") or "").strip()
    if not slug:
        abort(404)
    g.tenant = slug
    return _run_product_detail(product_id, slug)


@storefront_bp.route("/")
def shop_root():
    slug = (current_app.config.get("STOREFRONT_DEFAULT_TENANT_SLUG") or "").strip()
    if not slug:
        abort(404)
    return redirect(url_for("storefront.store_index", tenant_slug=slug))


@storefront_bp.route("/<tenant_slug>/")
def store_index(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    products = (
        Product.query.filter(Product.active == True)  # noqa: E712
        .order_by(Product.id.desc())
        .all()
    )
    cards = [_product_card(product, slug) for product in products]
    return render_template("storefront/index.html", products=cards, shop_tenant_slug=slug)


@storefront_bp.route("/<tenant_slug>/product/<int:product_id>", methods=["GET", "POST"])
def product_detail(tenant_slug: str, product_id: int):
    slug = _resolved_shop_slug(tenant_slug)
    return _run_product_detail(product_id, slug)
