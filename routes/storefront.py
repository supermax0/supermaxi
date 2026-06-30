from __future__ import annotations

import re

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, url_for

from models.invoice import Invoice
from models.product import Product
from modules.storefront.services.cart_service import StorefrontCartService
from modules.storefront.services.catalog_service import StorefrontCatalogService
from modules.storefront.services.checkout_service import StorefrontCheckoutService
from modules.storefront.services.product_presenter import product_card
from modules.storefront.services.settings_service import StorefrontSettingsService, safe_int
from modules.storefront.template_utils import storefront_template
from routes.orders import build_public_order_view_token
from utils.product_schema_guard import ensure_product_schema


storefront_bp = Blueprint("storefront", __name__, url_prefix="/shop")
_settings = StorefrontSettingsService()
_catalog = StorefrontCatalogService()
_checkout = StorefrontCheckoutService()


@storefront_bp.before_request
def _storefront_bind_tenant():
    va = getattr(request, "view_args", None) or {}
    slug = va.get("tenant_slug")
    if slug is None:
        return
    slug = str(slug).strip()
    if not slug:
        abort(404)
    g.tenant = slug
    ensure_product_schema()


def _resolved_shop_slug(tenant_slug_from_url: str | None) -> str:
    s = (tenant_slug_from_url or "").strip()
    if s:
        return s
    return (current_app.config.get("STOREFRONT_DEFAULT_TENANT_SLUG") or "").strip()


def _cart(tenant_slug: str) -> StorefrontCartService:
    return StorefrontCartService(_resolved_shop_slug(tenant_slug))


def _store_context(shop_slug: str, cart: StorefrontCartService) -> dict:
    return {
        "shop_tenant_slug": shop_slug,
        "cart_count": cart.count(),
        "store_design": _settings.design_settings(),
    }


def _preserve_dev_query(endpoint: str, **kwargs):
    args = dict(kwargs)
    if request.args.get("dev") == "1":
        return redirect(url_for(endpoint, **args, dev=1))
    return redirect(url_for(endpoint, **args))


def _run_product_detail(product_id: int, shop_slug: str):
    product = Product.query.get_or_404(product_id)
    if not product.active:
        abort(404)

    cart = _cart(shop_slug)
    card = product_card(product, shop_slug)
    related_cards = _catalog.related_products(product_id, shop_slug)
    return render_template(
        storefront_template("product_detail.html"),
        product=card,
        related_products=related_cards,
        **_store_context(shop_slug, cart),
    )


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
    if request.args.get("dev") == "1":
        return redirect(url_for("storefront.store_index", tenant_slug=slug, dev=1))
    return redirect(url_for("storefront.store_index", tenant_slug=slug))


@storefront_bp.route("/<tenant_slug>/")
def store_index(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    availability = str(request.args.get("availability") or "all").strip().lower()
    cards, badges = _catalog.list_products(
        slug,
        q=str(request.args.get("q") or ""),
        min_price=max(0, safe_int(request.args.get("min_price"), 0)),
        max_price=max(0, safe_int(request.args.get("max_price"), 0)),
        availability=availability,
        badge_filter=str(request.args.get("badge") or "").strip(),
        sort=str(request.args.get("sort") or "latest").strip().lower(),
    )
    return render_template(
        storefront_template("index.html"),
        products=cards,
        featured_products=_catalog.featured_products(cards),
        filters={
            "q": request.args.get("q", ""),
            "min_price": request.args.get("min_price", ""),
            "max_price": request.args.get("max_price", ""),
            "availability": availability,
            "badge": request.args.get("badge", ""),
            "sort": request.args.get("sort", "latest"),
        },
        badges=badges,
        **_store_context(slug, cart),
    )


@storefront_bp.route("/<tenant_slug>/product/<int:product_id>", methods=["GET"])
def product_detail(tenant_slug: str, product_id: int):
    slug = _resolved_shop_slug(tenant_slug)
    return _run_product_detail(product_id, slug)


@storefront_bp.route("/<tenant_slug>/cart")
def cart_page(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    totals = cart.totals()
    coupon_error = request.args.get("coupon_error", "")
    coupon_success = request.args.get("coupon_success", "")
    return render_template(
        storefront_template("cart.html"),
        cart_items=totals["items"],
        subtotal=totals["subtotal"],
        discount_amount=totals["discount_amount"],
        net_subtotal=totals["net_subtotal"],
        active_coupon=totals["active_coupon"],
        coupon_error=coupon_error,
        coupon_success=coupon_success,
        **_store_context(slug, cart),
    )


@storefront_bp.route("/<tenant_slug>/cart/coupon", methods=["POST"])
def cart_coupon(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    action = str(request.form.get("action") or "apply").strip().lower()
    if action == "remove":
        cart.remove_coupon()
        return _preserve_dev_query("storefront.cart_page", tenant_slug=slug)
    ok, msg = cart.apply_coupon(str(request.form.get("coupon_code") or ""))
    if ok:
        return _preserve_dev_query("storefront.cart_page", tenant_slug=slug, coupon_success=msg)
    return _preserve_dev_query("storefront.cart_page", tenant_slug=slug, coupon_error=msg)


@storefront_bp.route("/<tenant_slug>/cart/add/<int:product_id>", methods=["POST"])
def cart_add(tenant_slug: str, product_id: int):
    slug = _resolved_shop_slug(tenant_slug)
    qty = max(1, min(safe_int(request.form.get("quantity"), 1), 999))
    product = Product.query.get_or_404(product_id)
    if not product.active:
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": "المنتج غير متاح"}), 400
        abort(400)
    cart = _cart(slug)
    ok, msg = cart.try_add(product_id, qty)
    if not ok:
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": msg, "cart": cart.summary()}), 400
        return _preserve_dev_query("storefront.cart_page", tenant_slug=slug, coupon_error=msg)
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "message": msg, "cart": cart.summary()})
    next_url = request.form.get("next") or request.referrer or url_for("storefront.store_index", tenant_slug=slug)
    return redirect(next_url)


@storefront_bp.route("/<tenant_slug>/cart/update", methods=["POST"])
def cart_update(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    raw_updates = request.form.to_dict(flat=False)
    updates: dict[int, int] = {}
    for key, values in raw_updates.items():
        if not key.startswith("qty_"):
            continue
        pid = safe_int(key.replace("qty_", ""), 0)
        if pid <= 0:
            continue
        updates[pid] = max(0, min(safe_int(values[0] if values else 0), 999))
    ok, msg = cart.try_update_quantities(updates)
    if not ok:
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": msg, "cart": cart.summary()}), 400
        return _preserve_dev_query("storefront.cart_page", tenant_slug=slug, coupon_error=msg)
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "message": msg, "cart": cart.summary()})
    return _preserve_dev_query("storefront.cart_page", tenant_slug=slug)


@storefront_bp.route("/<tenant_slug>/cart/remove/<int:product_id>", methods=["POST"])
def cart_remove(tenant_slug: str, product_id: int):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    cart.remove(product_id)
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "cart": cart.summary()})
    return _preserve_dev_query("storefront.cart_page", tenant_slug=slug)


@storefront_bp.route("/<tenant_slug>/api/cart", methods=["GET"])
def api_cart_summary(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    return jsonify({"success": True, "cart": cart.summary()})


@storefront_bp.route("/<tenant_slug>/api/cart/add", methods=["POST"])
def api_cart_add(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    data = request.get_json(silent=True) or {}
    product_id = safe_int(data.get("product_id") or request.form.get("product_id"), 0)
    qty = max(1, min(safe_int(data.get("quantity") or request.form.get("quantity"), 1), 999))
    if product_id <= 0:
        return jsonify({"success": False, "error": "معرّف المنتج غير صالح"}), 400
    product = Product.query.get(product_id)
    if not product or not product.active:
        return jsonify({"success": False, "error": "المنتج غير متاح"}), 400
    cart = _cart(slug)
    ok, msg = cart.try_add(product_id, qty)
    if not ok:
        return jsonify({"success": False, "error": msg, "cart": cart.summary()}), 400
    return jsonify({"success": True, "message": msg, "cart": cart.summary()})


@storefront_bp.route("/<tenant_slug>/api/cart/update", methods=["POST"])
def api_cart_update(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    data = request.get_json(silent=True) or {}
    product_id = safe_int(data.get("product_id"), 0)
    qty = safe_int(data.get("quantity"), 0)
    if product_id <= 0:
        return jsonify({"success": False, "error": "معرّف المنتج غير صالح"}), 400
    cart = _cart(slug)
    ok, msg = cart.try_update_quantities({product_id: qty})
    if not ok:
        return jsonify({"success": False, "error": msg, "cart": cart.summary()}), 400
    return jsonify({"success": True, "message": msg, "cart": cart.summary()})


@storefront_bp.route("/<tenant_slug>/api/coupon", methods=["POST"])
def api_cart_coupon(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    data = request.get_json(silent=True) or {}
    action = str(data.get("action") or request.form.get("action") or "apply").strip().lower()
    if action == "remove":
        cart.remove_coupon()
        return jsonify({"success": True, "message": "تم إزالة الكوبون", "cart": cart.summary()})
    ok, msg = cart.apply_coupon(str(data.get("coupon_code") or request.form.get("coupon_code") or ""))
    return jsonify({"success": ok, "message": msg, "cart": cart.summary()}), (200 if ok else 400)


@storefront_bp.route("/<tenant_slug>/checkout", methods=["GET", "POST"])
def checkout_page(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    shipping_map, default_fee = _settings.shipping_config()
    checkout_form = {
        "customer_name": "",
        "phone": "",
        "city": "",
        "address": "",
        "notes": "",
    }
    checkout_error = ""
    shipping_fee = default_fee

    if request.method == "POST":
        checkout_form = {
            "customer_name": str(request.form.get("customer_name") or "").strip(),
            "phone": str(request.form.get("phone") or "").strip(),
            "city": str(request.form.get("city") or "").strip(),
            "address": str(request.form.get("address") or "").strip(),
            "notes": str(request.form.get("notes") or "").strip(),
        }
        items = cart.items()
        shipping_fee, _ = _settings.shipping_fee_for_city(checkout_form["city"])
        discount_amount, _ = cart.discount_for_subtotal(sum(int(i["line_total"]) for i in items))
        ok, msg, payload = _checkout.create_invoice_from_cart(items, checkout_form, shipping_fee, discount_amount)
        if ok:
            cart.clear()
            dev_mode = request.args.get("dev") == "1" or request.form.get("dev") == "1"
            if dev_mode:
                return redirect(
                    url_for(
                        "storefront.order_success",
                        tenant_slug=slug,
                        invoice_id=payload["invoice_id"],
                        dev=1,
                    )
                )
            return redirect(
                url_for("storefront.order_success", tenant_slug=slug, invoice_id=payload["invoice_id"])
            )
        checkout_error = msg

    if checkout_form["city"]:
        shipping_fee, _ = _settings.shipping_fee_for_city(checkout_form["city"])
    totals = cart.totals(shipping_fee)

    return render_template(
        storefront_template("checkout.html"),
        cart_items=totals["items"],
        subtotal=totals["subtotal"],
        discount_amount=totals["discount_amount"],
        net_subtotal=totals["net_subtotal"],
        shipping_fee=totals["shipping_fee"],
        grand_total=totals["grand_total"],
        active_coupon=totals["active_coupon"],
        shipping_map=shipping_map,
        shipping_default_fee=default_fee,
        checkout_form=checkout_form,
        checkout_error=checkout_error,
        **_store_context(slug, cart),
    )


@storefront_bp.route("/<tenant_slug>/order-success/<int:invoice_id>")
def order_success(tenant_slug: str, invoice_id: int):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    inv = Invoice.query.get_or_404(invoice_id)
    track_url = ""
    try:
        token = build_public_order_view_token(invoice_id)
        track_url = url_for("orders.public_order_view", token=token)
    except Exception:
        current_app.logger.exception("storefront order_success track url failed")
    return render_template(
        storefront_template("order_success.html"),
        order={
            "invoice_id": inv.id,
            "grand_total": int(inv.total or 0),
            "customer_name": inv.customer_name,
        },
        track_url=track_url,
        **_store_context(slug, cart),
    )


@storefront_bp.route("/<tenant_slug>/track", methods=["GET", "POST"])
def tracking_page(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    form = {"invoice_id": "", "phone": ""}
    found = None
    error = ""

    if request.method == "POST":
        form = {
            "invoice_id": str(request.form.get("invoice_id") or "").strip(),
            "phone": str(request.form.get("phone") or "").strip(),
        }
        invoice_id = safe_int(form["invoice_id"], 0)
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

    public_track_url = ""
    if found:
        try:
            token = build_public_order_view_token(found.id)
            public_track_url = url_for("orders.public_order_view", token=token)
        except Exception:
            pass

    return render_template(
        storefront_template("tracking.html"),
        form=form,
        order=found,
        tracking_steps=build_tracking_steps(found),
        error=error,
        public_track_url=public_track_url,
        **_store_context(slug, cart),
    )
