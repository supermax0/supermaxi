from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, session, url_for

from extensions import db
from models.customer import Customer
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.system_settings import SystemSettings
from utils.inventory_movements import validate_sale_quantity


storefront_bp = Blueprint("storefront", __name__, url_prefix="/shop")
_CART_SESSION_KEY = "storefront_cart"
_COUPON_SESSION_KEY = "storefront_coupon"
_DEFAULT_SHIPPING_BY_CITY = {
    "بغداد": 5000,
    "البصرة": 7000,
    "نينوى": 7000,
    "أربيل": 7000,
    "النجف": 6000,
    "كربلاء": 6000,
    "ذي قار": 7000,
}


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
    raw_items = meta.get("specs_items")
    if isinstance(raw_items, list):
        for row in raw_items:
            if not isinstance(row, dict):
                continue
            key = str(row.get("label") or "").strip() or "تفصيل"
            value = str(row.get("value") or "").strip()
            if value:
                specs.append({"label": key, "value": value})
    if specs:
        return specs

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


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_hex_color(value: str, default: str) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", raw):
        return raw
    return default


def _storefront_design_settings() -> dict[str, str]:
    defaults = {
        "primary_color": "#4f8cff",
        "shipping_color": "#10b981",
        "card_style": "modern",
        "preset": "custom",
    }
    try:
        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags() if settings else {}
    except Exception:
        current_app.logger.exception("failed loading storefront design settings")
        flags = {}

    card_style = str(flags.get("storefront_product_card_style") or defaults["card_style"]).strip()
    if card_style not in {"modern", "compact", "showcase", "minimal", "bordered", "overlay"}:
        card_style = defaults["card_style"]
    preset = str(flags.get("storefront_theme_preset") or defaults["preset"]).strip()
    if preset not in {"custom", "ocean", "sunset", "emerald"}:
        preset = defaults["preset"]

    return {
        "primary_color": _safe_hex_color(flags.get("storefront_primary_color"), defaults["primary_color"]),
        "shipping_color": _safe_hex_color(flags.get("storefront_shipping_color"), defaults["shipping_color"]),
        "card_style": card_style,
        "preset": preset,
        "hero_title": str(flags.get("storefront_hero_title") or "واجهة متجر احترافية").strip(),
        "hero_subtitle": str(flags.get("storefront_hero_subtitle") or "ابحث، فلتر، واختر منتجاتك بسهولة. كل عملية شراء تمر عبر سلة متكاملة ثم Checkout بالدفع عند الاستلام.").strip(),
    }


def _coupon_config() -> dict:
    try:
        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags() if settings else {}
    except Exception:
        current_app.logger.exception("failed loading storefront coupon settings")
        flags = {}
    code = str(flags.get("storefront_coupon_code") or "").strip().upper()
    ctype = str(flags.get("storefront_coupon_type") or "percent").strip().lower()
    if ctype not in {"percent", "fixed"}:
        ctype = "percent"
    value = max(0, _safe_int(flags.get("storefront_coupon_value"), 0))
    enabled = bool(code and value > 0)
    return {"enabled": enabled, "code": code, "type": ctype, "value": value}


def _coupon_get() -> dict | None:
    data = session.get(_COUPON_SESSION_KEY) or {}
    if not isinstance(data, dict):
        return None
    code = str(data.get("code") or "").strip().upper()
    if not code:
        return None
    return {"code": code}


def _coupon_set(code: str | None) -> None:
    if not code:
        session.pop(_COUPON_SESSION_KEY, None)
    else:
        session[_COUPON_SESSION_KEY] = {"code": str(code).strip().upper()}
    session.modified = True


def _discount_for_subtotal(subtotal: int) -> tuple[int, dict | None]:
    current = _coupon_get()
    conf = _coupon_config()
    if not current or not conf["enabled"] or current["code"] != conf["code"]:
        return 0, None
    if conf["type"] == "fixed":
        discount = min(subtotal, conf["value"])
    else:
        discount = min(subtotal, int(round(subtotal * (conf["value"] / 100.0))))
    return max(0, discount), conf


def _cart_raw() -> dict[str, int]:
    raw = session.get(_CART_SESSION_KEY) or {}
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, int] = {}
    for k, v in raw.items():
        pid = _safe_int(k, 0)
        qty = max(0, min(_safe_int(v, 0), 9999))
        if pid > 0 and qty > 0:
            clean[str(pid)] = qty
    return clean


def _save_cart_raw(cart: dict[str, int]) -> None:
    session[_CART_SESSION_KEY] = cart
    session.modified = True


def _cart_count() -> int:
    return sum(_cart_raw().values())


def _cart_items(shop_slug: str) -> list[dict]:
    raw = _cart_raw()
    if not raw:
        return []
    ids = [_safe_int(k, 0) for k in raw.keys()]
    products = Product.query.filter(Product.id.in_(ids)).all()
    product_by_id = {p.id: p for p in products}
    items = []
    for sid, qty in raw.items():
        pid = _safe_int(sid, 0)
        p = product_by_id.get(pid)
        if not p:
            continue
        card = _product_card(p, shop_slug)
        card["quantity"] = max(1, qty)
        card["line_total"] = card["price"] * card["quantity"]
        items.append(card)
    return items


def _normalized_city(value: str) -> str:
    return str(value or "").replace("-", " ").strip().lower()


def _shipping_config() -> tuple[dict[str, int], int]:
    city_fees = dict(_DEFAULT_SHIPPING_BY_CITY)
    default_fee = 7000
    try:
        settings = SystemSettings.get_settings()
        flags = settings.get_ui_flags() if settings else {}
        custom = flags.get("storefront_shipping_by_city")
        if isinstance(custom, dict):
            for city, fee in custom.items():
                city_name = str(city or "").strip()
                if not city_name:
                    continue
                city_fees[city_name] = max(0, _safe_int(fee, city_fees.get(city_name, default_fee)))
        default_fee = max(0, _safe_int(flags.get("storefront_shipping_default_fee"), default_fee))
    except Exception:
        current_app.logger.exception("failed loading storefront shipping settings")
    return city_fees, default_fee


def _shipping_fee_for_city(city: str) -> tuple[int, dict[str, int]]:
    city_fees, default_fee = _shipping_config()
    normalized = _normalized_city(city)
    for name, fee in city_fees.items():
        if _normalized_city(name) == normalized:
            return fee, city_fees
    return default_fee, city_fees


def _create_invoice_from_cart(cart_items: list[dict], form_data: dict, shipping_fee: int) -> tuple[bool, str, dict]:
    name = str(form_data.get("customer_name") or "").strip()
    phone = str(form_data.get("phone") or "").strip()
    city = str(form_data.get("city") or "").strip()
    address = str(form_data.get("address") or "").strip()
    notes = str(form_data.get("notes") or "").strip()

    if not name:
        return False, "يرجى إدخال الاسم الكامل.", {}
    if not phone:
        return False, "يرجى إدخال رقم الهاتف.", {}
    if len(re.sub(r"\D+", "", phone)) < 8:
        return False, "رقم الهاتف غير صحيح.", {}
    if len(city) < 2:
        return False, "يرجى إدخال المحافظة بشكل صحيح.", {}
    if not address:
        return False, "يرجى إدخال العنوان.", {}
    if len(address) < 5:
        return False, "العنوان قصير جداً.", {}
    if not cart_items:
        return False, "سلة الطلب فارغة.", {}

    for item in cart_items:
        check = validate_sale_quantity(item["id"], item["quantity"])
        if not check.get("valid"):
            return False, f"المنتج {item['name']}: {str(check.get('message') or 'الكمية غير متوفرة.')}", {}

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
        first_product = Product.query.get(cart_items[0]["id"]) if cart_items else None
        customer = Customer(
            name=name,
            phone=phone,
            city=city or None,
            address=address,
            notes=notes or None,
            tenant_id=getattr(first_product, "tenant_id", None),
        )
        db.session.add(customer)
        db.session.flush()

    subtotal = sum(int(i["line_total"]) for i in cart_items)
    discount_amount, _ = _discount_for_subtotal(subtotal)
    net_subtotal = max(0, subtotal - discount_amount)
    grand_total = net_subtotal + max(0, _safe_int(shipping_fee, 0))

    invoice = Invoice(
        customer_id=customer.id,
        customer_name=customer.name,
        employee_id=None,
        employee_name=None,
        total=grand_total,
        status="تم الطلب",
        payment_status="غير مسدد",
        note=f"طلب من متجر المنتجات | COD | city={city} | shipping={shipping_fee} | discount={discount_amount} | notes={notes}",
        created_at=datetime.utcnow(),
    )
    db.session.add(invoice)
    db.session.flush()

    for item in cart_items:
        product = Product.query.get(item["id"])
        if not product:
            db.session.rollback()
            return False, f"المنتج غير موجود: {item['name']}", {}
        check = validate_sale_quantity(product.id, item["quantity"])
        if not check.get("valid"):
            db.session.rollback()
            return False, f"المنتج {product.name}: {str(check.get('message') or 'الكمية غير متوفرة.')}", {}
        line_total = int(product.sale_price or 0) * int(item["quantity"])
        db.session.add(
            OrderItem(
                invoice_id=invoice.id,
                product_id=product.id,
                product_name=product.name,
                quantity=int(item["quantity"]),
                price=int(product.sale_price or 0),
                cost=int(product.buy_price or 0),
                total=line_total,
            )
        )
        product.quantity = int(product.quantity or 0) - int(item["quantity"])

    db.session.commit()

    return True, "تم استلام طلبك بنجاح.", {
        "invoice_id": invoice.id,
        "items_count": len(cart_items),
        "subtotal": subtotal,
        "discount_amount": discount_amount,
        "net_subtotal": net_subtotal,
        "shipping_fee": shipping_fee,
        "grand_total": grand_total,
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
        cart_count=_cart_count(),
        shop_tenant_slug=shop_slug,
        store_design=_storefront_design_settings(),
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
    q = str(request.args.get("q") or "").strip().lower()
    min_price = max(0, _safe_int(request.args.get("min_price"), 0))
    max_price = max(0, _safe_int(request.args.get("max_price"), 0))
    availability = str(request.args.get("availability") or "all").strip().lower()
    badge_filter = str(request.args.get("badge") or "").strip()
    sort = str(request.args.get("sort") or "latest").strip().lower()
    products = (
        Product.query.filter(Product.active == True)  # noqa: E712
        .order_by(Product.id.desc())
        .all()
    )
    cards = [_product_card(product, slug) for product in products]

    if q:
        cards = [c for c in cards if q in c["name"].lower() or q in c["description"].lower()]
    if min_price:
        cards = [c for c in cards if c["price"] >= min_price]
    if max_price:
        cards = [c for c in cards if c["price"] <= max_price]
    if availability == "in_stock":
        cards = [c for c in cards if c["is_available"]]
    elif availability == "out_stock":
        cards = [c for c in cards if not c["is_available"]]
    if badge_filter:
        cards = [c for c in cards if c["badge"] == badge_filter]

    if sort == "price_asc":
        cards.sort(key=lambda c: c["price"])
    elif sort == "price_desc":
        cards.sort(key=lambda c: c["price"], reverse=True)
    elif sort == "name_asc":
        cards.sort(key=lambda c: c["name"])
    else:
        cards.sort(key=lambda c: c["id"], reverse=True)

    badges = sorted({c["badge"] for c in [_product_card(p, slug) for p in products] if c["badge"]})
    featured = cards[:6]
    return render_template(
        "storefront/index.html",
        products=cards,
        featured_products=featured,
        shop_tenant_slug=slug,
        cart_count=_cart_count(),
        filters={
            "q": request.args.get("q", ""),
            "min_price": request.args.get("min_price", ""),
            "max_price": request.args.get("max_price", ""),
            "availability": availability,
            "badge": badge_filter,
            "sort": sort,
        },
        badges=badges,
        store_design=_storefront_design_settings(),
    )


@storefront_bp.route("/<tenant_slug>/product/<int:product_id>", methods=["GET"])
def product_detail(tenant_slug: str, product_id: int):
    slug = _resolved_shop_slug(tenant_slug)
    return _run_product_detail(product_id, slug)


@storefront_bp.route("/<tenant_slug>/cart")
def cart_page(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    items = _cart_items(slug)
    subtotal = sum(int(i["line_total"]) for i in items)
    discount_amount, coupon = _discount_for_subtotal(subtotal)
    net_subtotal = max(0, subtotal - discount_amount)
    return render_template(
        "storefront/cart.html",
        shop_tenant_slug=slug,
        cart_items=items,
        subtotal=subtotal,
        discount_amount=discount_amount,
        net_subtotal=net_subtotal,
        active_coupon=(coupon["code"] if coupon else ""),
        cart_count=_cart_count(),
        store_design=_storefront_design_settings(),
    )


@storefront_bp.route("/<tenant_slug>/cart/coupon", methods=["POST"])
def cart_coupon(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    action = str(request.form.get("action") or "apply").strip().lower()
    if action == "remove":
        _coupon_set(None)
        return redirect(url_for("storefront.cart_page", tenant_slug=slug))
    code = str(request.form.get("coupon_code") or "").strip().upper()
    conf = _coupon_config()
    if conf["enabled"] and code == conf["code"]:
        _coupon_set(code)
    else:
        _coupon_set(None)
    return redirect(url_for("storefront.cart_page", tenant_slug=slug))


@storefront_bp.route("/<tenant_slug>/cart/add/<int:product_id>", methods=["POST"])
def cart_add(tenant_slug: str, product_id: int):
    _resolved_shop_slug(tenant_slug)
    qty = max(1, min(_safe_int(request.form.get("quantity"), 1), 999))
    product = Product.query.get_or_404(product_id)
    if not product.active:
        return jsonify({"success": False, "error": "المنتج غير متاح"}), 400
    cart = _cart_raw()
    current_qty = _safe_int(cart.get(str(product_id)), 0)
    cart[str(product_id)] = current_qty + qty
    _save_cart_raw(cart)
    next_url = request.form.get("next") or request.referrer or url_for("storefront.store_index", tenant_slug=tenant_slug)
    return redirect(next_url)


@storefront_bp.route("/<tenant_slug>/cart/update", methods=["POST"])
def cart_update(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart_raw()
    raw_updates = request.form.to_dict(flat=False)
    for key, values in raw_updates.items():
        if not key.startswith("qty_"):
            continue
        pid = _safe_int(key.replace("qty_", ""), 0)
        if pid <= 0:
            continue
        qty = max(0, min(_safe_int(values[0] if values else 0), 999))
        if qty == 0:
            cart.pop(str(pid), None)
        else:
            cart[str(pid)] = qty
    _save_cart_raw(cart)
    return redirect(url_for("storefront.cart_page", tenant_slug=slug))


@storefront_bp.route("/<tenant_slug>/cart/remove/<int:product_id>", methods=["POST"])
def cart_remove(tenant_slug: str, product_id: int):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart_raw()
    cart.pop(str(product_id), None)
    _save_cart_raw(cart)
    return redirect(url_for("storefront.cart_page", tenant_slug=slug))


@storefront_bp.route("/<tenant_slug>/checkout", methods=["GET", "POST"])
def checkout_page(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    items = _cart_items(slug)
    subtotal = sum(int(i["line_total"]) for i in items)
    discount_amount, coupon = _discount_for_subtotal(subtotal)
    net_subtotal = max(0, subtotal - discount_amount)
    shipping_map, default_fee = _shipping_config()
    shipping_fee = default_fee
    checkout_form = {
        "customer_name": "",
        "phone": "",
        "city": "",
        "address": "",
        "notes": "",
    }
    checkout_error = ""
    checkout_success = None

    if request.method == "POST":
        checkout_form = {
            "customer_name": str(request.form.get("customer_name") or "").strip(),
            "phone": str(request.form.get("phone") or "").strip(),
            "city": str(request.form.get("city") or "").strip(),
            "address": str(request.form.get("address") or "").strip(),
            "notes": str(request.form.get("notes") or "").strip(),
        }
        shipping_fee, _ = _shipping_fee_for_city(checkout_form["city"])
        ok, msg, payload = _create_invoice_from_cart(items, checkout_form, shipping_fee)
        if ok:
            _save_cart_raw({})
            checkout_success = payload
        else:
            checkout_error = msg

    if checkout_form["city"]:
        shipping_fee, _ = _shipping_fee_for_city(checkout_form["city"])
    grand_total = net_subtotal + shipping_fee

    return render_template(
        "storefront/checkout.html",
        shop_tenant_slug=slug,
        cart_items=items,
        subtotal=subtotal,
        discount_amount=discount_amount,
        net_subtotal=net_subtotal,
        shipping_fee=shipping_fee,
        grand_total=grand_total,
        active_coupon=(coupon["code"] if coupon else ""),
        cart_count=_cart_count(),
        shipping_map=shipping_map,
        shipping_default_fee=default_fee,
        checkout_form=checkout_form,
        checkout_error=checkout_error,
        checkout_success=checkout_success,
        store_design=_storefront_design_settings(),
    )


@storefront_bp.route("/<tenant_slug>/track", methods=["GET", "POST"])
def tracking_page(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    form = {"invoice_id": "", "phone": ""}
    found = None
    error = ""
    def build_tracking_steps(invoice: Invoice | None) -> list[dict[str, str | bool]]:
        status = str(getattr(invoice, "status", "") or "").strip()
        shipping_status = str(getattr(invoice, "shipping_status", "") or "").strip()
        cancelled = any(word in status for word in ("ملغي", "إلغاء", "مرتجع"))
        delivered = any(word in f"{status} {shipping_status}" for word in ("تم التوصيل", "مكتمل", "مسلم"))
        shipping = any(word in f"{status} {shipping_status}" for word in ("شحن", "توصيل", "قيد"))
        return [
            {"label": "تم استلام الطلب", "hint": "وصلنا طلبك بنجاح", "done": bool(invoice), "active": bool(invoice) and not shipping and not delivered and not cancelled},
            {"label": "قيد التجهيز", "hint": "يتم مراجعة الطلب وتجهيزه", "done": shipping or delivered, "active": shipping and not delivered and not cancelled},
            {"label": "قيد التوصيل", "hint": shipping_status or "بانتظار شركة التوصيل", "done": delivered, "active": shipping and not delivered and not cancelled},
            {"label": "تم التوصيل", "hint": "اكتمل الطلب", "done": delivered, "active": delivered and not cancelled},
        ] if not cancelled else [
            {"label": "تم استلام الطلب", "hint": "وصلنا طلبك", "done": True, "active": False},
            {"label": "تم إلغاء الطلب", "hint": status or "الطلب ملغي", "done": True, "active": True},
        ]

    if request.method == "POST":
        form = {
            "invoice_id": str(request.form.get("invoice_id") or "").strip(),
            "phone": str(request.form.get("phone") or "").strip(),
        }
        invoice_id = _safe_int(form["invoice_id"], 0)
        if invoice_id <= 0 or not form["phone"]:
            error = "أدخل رقم طلب ورقم هاتف صحيح."
        else:
            inv = Invoice.query.get(invoice_id)
            phone = re.sub(r"\D+", "", form["phone"])
            customer_phone = re.sub(r"\D+", "", str(getattr(getattr(inv, "customer", None), "phone", "")))
            if not inv or (phone and customer_phone and phone != customer_phone):
                error = "لم يتم العثور على الطلب بهذه البيانات."
            else:
                found = inv
    return render_template(
        "storefront/tracking.html",
        shop_tenant_slug=slug,
        form=form,
        order=found,
        tracking_steps=build_tracking_steps(found),
        error=error,
        cart_count=_cart_count(),
        store_design=_storefront_design_settings(),
    )
