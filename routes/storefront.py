from __future__ import annotations

import re
import threading
import time
from datetime import date, datetime

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models.customer import Customer
from models.invoice import Invoice
from models.product import Product
from modules.installments.models import InstallmentApplication, InstallmentCustomerAccount
from modules.installments.schema import ensure_installment_schema
from modules.installments.services import InstallmentError, find_customer_by_phone, normalize_phone
from modules.phone_app.services.rate_limit import allow_request
from modules.storefront.services.ai_assistant_service import StorefrontAIAssistantService
from modules.storefront.services.cart_service import StorefrontCartService
from modules.storefront.services.catalog_service import StorefrontCatalogService
from modules.storefront.services.catalog_service import (
    cash_store_product_is_visible,
    published_installment_item,
)
from modules.storefront.services.checkout_service import StorefrontCheckoutService
from modules.storefront.services.category_assets import category_image_path
from modules.storefront.services import catalog_service as _catalog_page
from modules.storefront.services.product_presenter import product_card, build_hero_slides
from modules.storefront.services.store_layout_service import build_store_sections
from modules.storefront.services.settings_service import StorefrontSettingsService, safe_int
from modules.storefront.services.tracking_service import build_tracking_steps, lookup_order
from modules.storefront.template_utils import storefront_base, storefront_template, v2_enabled
from routes.orders import build_public_order_view_token
from utils.product_schema_guard import ensure_product_schema
from utils.invoice_schema_guard import ensure_invoice_schema
from utils.order_item_schema_guard import ensure_order_item_schema
from utils.order_stock_policy import ensure_policy_initialized
from utils.branch_context import init_public_default_branch


storefront_bp = Blueprint("storefront", __name__, url_prefix="/shop")
_settings = StorefrontSettingsService()
_catalog = StorefrontCatalogService()
_checkout = StorefrontCheckoutService()
_ai_assistant = StorefrontAIAssistantService()


_AREA_KEY = "sm_delivery_area"


def _delivery_area() -> str:
    return str(session.get(_AREA_KEY) or "")[:40]


def _with_catalog() -> bool:
    """Master-catalogue models offered on request are shown only in the V2 design and only when the company
    enabled the catalogue layer — every other shop renders exactly as before."""
    if not v2_enabled():
        return False
    from modules.catalog import service as catalog

    return catalog.enabled()


@storefront_bp.context_processor
def _storefront_shell():
    """Which page shell the shop pages extend (V2 only when the company enabled it or the owner previews it)."""
    try:
        return {"storefront_base": storefront_base(), "sf_v2": v2_enabled()}
    except Exception:
        return {"storefront_base": "storefront/base.html", "sf_v2": False}


_SCHEMA_READY: set[str] = set()
_DEFAULT_BRANCH_CACHE: dict[str, tuple[float, int | None]] = {}
_DEFAULT_BRANCH_SECONDS = 60


def reset_schema_ready() -> None:
    """Forget which companies were already checked (tests that rebuild a tenant database call this)."""
    _SCHEMA_READY.clear()
    _DEFAULT_BRANCH_CACHE.clear()


def _bind_default_branch_fast(slug: str) -> None:
    """Public traffic is locked to the default branch; its id is cached for a minute per company because
    ``get_default_branch`` re-runs the whole branch schema guard on every call."""
    import time

    from utils.branch_migration import get_default_branch

    g.branch_scope_ready = False
    cached = _DEFAULT_BRANCH_CACHE.get(slug)
    if cached is None or cached[0] < time.monotonic():
        branch = get_default_branch()
        cached = (time.monotonic() + _DEFAULT_BRANCH_SECONDS, int(branch.id) if branch else None)
        _DEFAULT_BRANCH_CACHE[slug] = cached
    g.public_branch_id = cached[1]
    g.branch_scope_ready = True


@storefront_bp.before_request
def _storefront_timer_start():
    from modules.store_analytics import perf

    g._sf_started = perf.start()
    g._settings_memo = {}  # SystemSettings.get_settings reuses the row within this store request


@storefront_bp.after_request
def _storefront_timer_stop(response):
    started = getattr(g, "_sf_started", None)
    if started is not None:
        from modules.store_analytics import perf

        ms = perf.stop(str(getattr(g, "tenant", "") or ""), request.endpoint or "", started)
        response.headers["Server-Timing"] = f"app;dur={ms:.1f}"
    return response


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
    from modules.pricing.service import run_due_throttled

    run_due_throttled(slug)  # dated promotions start / end on time (at most one check a minute)
    if slug in _SCHEMA_READY:
        # The schema guards below inspect every table (≈140 introspection queries) — once per process and company
        # is enough; only the cheap per-request branch lookup remains.
        _bind_default_branch_fast(slug)
        return
    ensure_product_schema()
    ensure_invoice_schema()
    ensure_order_item_schema()
    ensure_policy_initialized()
    init_public_default_branch()
    _SCHEMA_READY.add(slug)


def _resolved_shop_slug(tenant_slug_from_url: str | None) -> str:
    s = (tenant_slug_from_url or "").strip()
    if s:
        return s
    return (current_app.config.get("STOREFRONT_DEFAULT_TENANT_SLUG") or "").strip()


def _cart(tenant_slug: str) -> StorefrontCartService:
    return StorefrontCartService(_resolved_shop_slug(tenant_slug))


def _store_tenant_id() -> int:
    contextual_id = getattr(g, "installment_tenant_id", None) or session.get("tenant_id")
    if contextual_id:
        return int(contextual_id)
    tenant_id = db.session.query(Product.tenant_id).filter(Product.tenant_id.isnot(None)).limit(1).scalar()
    if tenant_id:
        return int(tenant_id)
    from models.tenant import Tenant

    tenant = Tenant.query.order_by(Tenant.id.asc()).first()
    if not tenant:
        raise InstallmentError("لا توجد شركة مهيأة في قاعدة البيانات الحالية")
    return int(tenant.id)


def _account_session_key(tenant_slug: str) -> str:
    # This is intentionally identical to the installment store key. A customer
    # signs in once and the two storefronts share the same account.
    return f"installment_customer_account:{str(tenant_slug or '').strip()}"


def _current_store_account(tenant_slug: str) -> InstallmentCustomerAccount | None:
    cached = getattr(g, "cash_store_customer_account", None)
    if cached is not None:
        return cached
    key = _account_session_key(tenant_slug)
    account_id = session.get(key)
    if not account_id:
        return None
    try:
        account_id = int(account_id)
    except (TypeError, ValueError):
        session.pop(key, None)
        session.modified = True
        return None
    account = InstallmentCustomerAccount.query.filter_by(
        id=account_id,
        tenant_id=_store_tenant_id(),
        is_active=True,
    ).first()
    if not account:
        session.pop(key, None)
        session.modified = True
        return None
    g.cash_store_customer_account = account
    return account


def _favorite_session_key(tenant_slug: str) -> str:
    return f"storefront_favorites:{str(tenant_slug or '').strip().lower()}"


def _favorite_ids(tenant_slug: str) -> list[int]:
    raw = session.get(_favorite_session_key(tenant_slug), [])
    if not isinstance(raw, list):
        return []
    ids: list[int] = []
    for value in raw:
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            continue
        if product_id > 0 and product_id not in ids:
            ids.append(product_id)
        if len(ids) >= 100:
            break
    return ids


def _store_context(
    shop_slug: str,
    cart: StorefrontCartService,
    *,
    sale_products: list[dict] | None = None,
) -> dict:
    # Only the products actually rendered on the page are embedded (the add-to-cart script needs their colour /
    # exchange options). Pages that render none pass nothing; the script then asks /api/product/<id>/options.
    sale_products = sale_products or []
    favorite_ids = _favorite_ids(shop_slug)
    return {
        "shop_tenant_slug": shop_slug,
        "cart_count": cart.count(),
        "store_account": _current_store_account(shop_slug),
        "favorite_ids": favorite_ids,
        "favorite_count": len(favorite_ids),
        "store_design": _settings.design_settings(),
        "store_sale_products": sale_products,
        "current_year": date.today().year,
        "store_provinces": sorted(_settings.shipping_config()[0]),
        "store_badges": _catalog_page.badges(shop_slug, include_catalog=_with_catalog()) if v2_enabled() else [],
        "delivery_area": _delivery_area(),
        "personalize_enabled": _personalize_enabled(shop_slug),
    }


def _personalize_enabled(shop_slug: str) -> bool:
    if not v2_enabled():
        return False
    from modules.personalization import service as personalization

    return personalization.enabled(shop_slug)


def _preserve_dev_query(endpoint: str, **kwargs):
    args = dict(kwargs)
    if request.args.get("dev") == "1":
        return redirect(url_for(endpoint, **args, dev=1))
    return redirect(url_for(endpoint, **args))


CASH_ORDER_STATUS_LABELS = {
    "تم الطلب": "تم استلام الطلب",
    "قيد التجهيز": "قيد التجهيز",
    "قيد الشحن": "قيد الشحن",
    "تم التوصيل": "تم التوصيل",
    "مكتمل": "مكتمل",
    "ملغي": "ملغي",
}

INSTALLMENT_STATUS_LABELS = {
    "new": "تم استلام الطلب",
    "under_review": "قيد المراجعة",
    "documents_required": "مطلوب استكمال مستندات",
    "waiting_approval": "بانتظار الموافقة",
    "approved": "تمت الموافقة",
    "contract_pending": "بانتظار إنشاء العقد",
    "contract_signed": "تم توقيع العقد",
    "ready_for_fulfillment": "جاهز للتجهيز",
    "delivered": "تم التسليم",
    "active": "عقد فعّال",
    "completed": "مكتمل",
    "rejected": "مرفوض",
    "cancelled": "ملغي",
}


def _run_product_detail(product_id: int, shop_slug: str):
    product = Product.query.get_or_404(product_id)
    if not cash_store_product_is_visible(product):
        abort(404)

    cart = _cart(shop_slug)
    catalog_item = published_installment_item(product.id)
    card = product_card(product, shop_slug, catalog_item=catalog_item)
    delivery_plan = None
    recs = None
    if v2_enabled():
        from modules.fulfillment import service as fulfillment

        _signal(shop_slug, "view", product_id=product.id)
        delivery_plan = fulfillment.product_availability(product.id, _delivery_area())
        if _in_holdout(shop_slug):
            recs = None  # experiment control group: the page as it was before recommendations
        else:
            recs = _product_recommendations(shop_slug, product.id, cart)
        if recs:
            shown_recs = [k for k in ("accessories", "bought_together", "upgrades", "similar", "bundles") if recs.get(k)]
            if shown_recs:
                _signal(shop_slug, "rec_view", product_id=product.id, section=",".join(shown_recs))
    if recs and recs["similar"]:
        related_cards = recs["similar"]
    else:
        related_cards = _catalog_page.related_page(product_id, shop_slug)
    extra = [c for key in ("accessories", "bought_together", "upgrades") for c in (recs or {}).get(key, [])]
    return render_template(
        storefront_template("product_detail.html"),
        product=card,
        related_products=related_cards,
        recommendations=recs,
        delivery_plan=delivery_plan,
        **_store_context(shop_slug, cart, sale_products=[card, *related_cards, *extra]),
    )


def _in_holdout(shop_slug: str) -> bool:
    try:
        from modules.personalization import service as personalization

        return personalization.in_holdout(shop_slug)
    except Exception:
        return False


def _signal(shop_slug: str, event_type: str, **kwargs) -> None:
    """A shopping signal for the personalisation engine (V2 stores only). Never breaks the request."""
    if not v2_enabled():
        return
    try:
        from modules.personalization import service as personalization

        personalization.record(shop_slug, event_type, **kwargs)
    except Exception:
        current_app.logger.exception("storefront signal %s failed", event_type)
        db.session.rollback()


def _bundle_cards(shop_slug: str, bundles: list[dict]) -> list[dict]:
    """Bundles with the cards of their products (available first) — only bundles a shopper can buy something of."""
    wanted = list(dict.fromkeys(i for b in bundles for i in b["product_ids"]))
    cards = {c["id"]: c for c in _catalog_page.cards_for_ids(shop_slug, wanted)} if wanted else {}
    out = []
    for b in bundles:
        if not b["available_ids"]:
            continue
        available = set(b["available_ids"])
        items = [cards[i] for i in b["product_ids"] if i in cards]
        items.sort(key=lambda c: c["id"] not in available)
        out.append({**b, "cards": items, "missing": len(b["product_ids"]) - len(available)})
    return out


def _home_bundles(shop_slug: str) -> list[dict]:
    try:
        from modules.recommendations import service as recommendations

        return _bundle_cards(shop_slug, recommendations.bundles(shop_slug))[:3]
    except Exception:
        current_app.logger.exception("storefront home bundles failed")
        db.session.rollback()
        return []


@storefront_bp.post("/<tenant_slug>/api/cart/add-bundle")
def api_cart_add_bundle(tenant_slug: str):
    """Put every product of a bundle that can be bought now into the cart (one of each). Products that cannot
    (sold out, or needing a colour choice) are listed back to the shopper — never silently dropped."""
    slug = _resolved_shop_slug(tenant_slug)
    if not v2_enabled():
        return jsonify({"success": False, "error": "غير متاح"}), 404
    data = request.get_json(silent=True) or {}
    bundle_id = safe_int(data.get("bundle_id"), 0)
    from modules.recommendations import service as recommendations

    bundle = next((b for b in recommendations.bundles(slug) if b["id"] == bundle_id), None)
    if bundle is None:
        return jsonify({"success": False, "error": "الباقة غير متاحة"}), 404
    cart = _cart(slug)
    names = {c["id"]: c.get("name") or "" for c in _catalog_page.cards_for_ids(slug, bundle["product_ids"])}
    added, skipped = [], []
    available = set(bundle["available_ids"])
    for pid in bundle["product_ids"]:
        if pid not in available:
            skipped.append({"id": pid, "name": names.get(pid, ""), "reason": "غير متوفر حالياً"})
            continue
        product = Product.query.get(pid)
        if not cash_store_product_is_visible(product):
            skipped.append({"id": pid, "name": names.get(pid, ""), "reason": "غير متاح"})
            continue
        ok, msg = cart.try_add(pid, 1)
        if ok:
            added.append(pid)
            _signal(slug, "cart", product_id=pid)
        else:
            skipped.append({"id": pid, "name": names.get(pid, ""), "reason": msg})
    for pid in added:  # each product counts as a click in «الباقات», so its order is attributed to bundles
        _signal(slug, "rec_click", product_id=pid, section="bundles")
    status = 200 if added else 400
    message = (f"أُضيف {len(added)} من منتجات الباقة إلى السلة" if added else "لم يُضف شيء من الباقة")
    return jsonify({"success": bool(added), "message": message, "added": added, "skipped": skipped,
                    "cart": cart.summary()}), status


def _product_recommendations(shop_slug: str, product_id: int, cart: StorefrontCartService) -> dict | None:
    """Cards for the product page sections; one card query for all of them. A failure never breaks the page."""
    try:
        from modules.recommendations import service as recommendations

        in_cart = {int(cart._parse_line_key(k)[0]) for k in (cart.cart_raw() or {})}
        recs = recommendations.for_product(shop_slug, product_id, in_cart=in_cart)
        ids = ([a["id"] for a in recs["accessories"]] + recs["bought_together"] + [u["id"] for u in recs["upgrades"]]
               + recs["similar"])
        cards = {c["id"]: c for c in _catalog_page.cards_for_ids(shop_slug, ids)}
        notes = {a["id"]: a["note"] for a in recs["accessories"]}
        accessories = [{**cards[a["id"]], "rec_note": notes.get(a["id"]) or ""} for a in recs["accessories"] if a["id"] in cards]
        upgrades = [{**cards[u["id"]], "rec_benefits": u["benefits"], "rec_difference": u["price_difference"]}
                    for u in recs["upgrades"] if u["id"] in cards]
        bundles = _bundle_cards(shop_slug, [b for b in recommendations.bundles(shop_slug) if product_id in b["product_ids"]][:2])
        return {"accessories": accessories, "bought_together": [cards[i] for i in recs["bought_together"] if i in cards],
                "upgrades": upgrades, "similar": [cards[i] for i in recs["similar"] if i in cards], "bundles": bundles}
    except Exception:
        current_app.logger.exception("storefront recommendations failed for product %s", product_id)
        db.session.rollback()
        return None


@storefront_bp.route("/<tenant_slug>/api/ai-chat", methods=["POST"])
def api_ai_chat(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    try:
        from ai import ai_utils

        ip = request.remote_addr or "anon"
        ok, err = ai_utils.check_rate_limit(f"storefront_ai_chat:{ip}")
        if not ok:
            return jsonify({"success": False, "error": err}), 429
    except Exception:
        pass

    data = request.get_json(silent=True) or {}
    message = str(data.get("message") or "").strip()
    history = data.get("history") or []
    track = data.get("track") if isinstance(data.get("track"), dict) else None
    if not message:
        return jsonify({"success": False, "error": "الرسالة فارغة."}), 400

    cart = _cart(slug)
    store_design = _settings.design_settings()
    if not store_design.get("ai_assistant_enabled"):
        return jsonify({"success": False, "error": "مساعد المتجر غير مفعّل."}), 403

    result = _ai_assistant.chat(
        message=message,
        history=history if isinstance(history, list) else [],
        shop_slug=slug,
        cart=cart,
        store_design=store_design,
        track=track,
    )
    status = 200 if result.get("success") else 400
    return jsonify(result), status


@storefront_bp.route("/<tenant_slug>/api/ai-chat/track", methods=["POST"])
def api_ai_chat_track(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    try:
        from ai import ai_utils

        ip = request.remote_addr or "anon"
        ok, err = ai_utils.check_rate_limit(f"storefront_ai_chat:{ip}")
        if not ok:
            return jsonify({"success": False, "error": err}), 429
    except Exception:
        pass

    store_design = _settings.design_settings()
    if not store_design.get("ai_assistant_enabled"):
        return jsonify({"success": False, "error": "مساعد المتجر غير مفعّل."}), 403

    data = request.get_json(silent=True) or {}
    invoice_id = str(data.get("invoice_id") or "").strip()
    phone = str(data.get("phone") or "").strip()
    track = lookup_order(invoice_id, phone)
    reply = ""
    if track.get("found"):
        reply = (
            f"تم العثور على طلبك رقم {track.get('invoice_id')}. "
            f"الحالة الحالية: {track.get('status')}."
        )
    else:
        reply = str(track.get("error") or "لم يتم العثور على الطلب.")

    return jsonify(
        {
            "success": True,
            "reply": reply,
            "track": track,
            "cart": _cart(slug).summary(),
        }
    )


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


_STORE_PAGE_SIZE = 15


def _safe_page(value) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _page_window(page: int, pages: int) -> list[int | None]:
    if pages <= 7:
        return list(range(1, pages + 1))
    wanted = {1, pages, page - 1, page, page + 1}
    if page <= 4:
        wanted.update(range(1, 6))
    if page >= pages - 3:
        wanted.update(range(max(1, pages - 4), pages + 1))
    ordered = sorted(number for number in wanted if 1 <= number <= pages)
    window: list[int | None] = []
    previous = 0
    for number in ordered:
        if previous and number - previous > 1:
            window.append(None)
        window.append(number)
        previous = number
    return window


def _store_page_url(slug: str, page: int) -> str:
    params: dict = {"tenant_slug": slug}
    for key in ("q", "min_price", "max_price", "badge", "sort", "availability", "dev"):
        value = str(request.args.get(key) or "").strip()
        if not value:
            continue
        if key == "availability" and value.lower() == "all":
            continue
        if key == "sort" and value.lower() == "latest":
            continue
        params[key] = value
    if page > 1:
        params["page"] = page
    return url_for("storefront.store_index", **params) + "#products"


def _pagination(slug: str, total: int, page: int, pages: int, per_page: int) -> dict:
    start = (page - 1) * per_page
    end = min(start + per_page, total)
    window = []
    for item in _page_window(page, pages):
        if item is None:
            window.append({"ellipsis": True})
            continue
        window.append({"ellipsis": False, "page": item, "current": item == page,
                       "href": _store_page_url(slug, item)})
    return {
        "page": page, "pages": pages, "per_page": per_page, "total": total,
        "from": (start + 1) if total else 0, "to": end, "has_prev": page > 1, "has_next": page < pages,
        "prev_href": _store_page_url(slug, page - 1) if page > 1 else "",
        "next_href": _store_page_url(slug, page + 1) if page < pages else "",
        "window": window,
    }


def _paginate_products(cards: list[dict], slug: str, requested_page) -> tuple[list[dict], dict]:
    total = len(cards)
    pages = max(1, (total + _STORE_PAGE_SIZE - 1) // _STORE_PAGE_SIZE) if total else 1
    page = min(_safe_page(requested_page), pages)
    start = (page - 1) * _STORE_PAGE_SIZE
    end = min(start + _STORE_PAGE_SIZE, total)
    window = []
    for item in _page_window(page, pages):
        if item is None:
            window.append({"ellipsis": True})
            continue
        window.append({
            "ellipsis": False,
            "page": item,
            "current": item == page,
            "href": _store_page_url(slug, item),
        })
    return cards[start:end], {
        "page": page,
        "pages": pages,
        "per_page": _STORE_PAGE_SIZE,
        "total": total,
        "from": (start + 1) if total else 0,
        "to": end,
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev_href": _store_page_url(slug, page - 1) if page > 1 else "",
        "next_href": _store_page_url(slug, page + 1) if page < pages else "",
        "window": window,
    }


_PAGE_CACHE: dict[tuple, tuple[float, bytes]] = {}
_PAGE_CACHE_SECONDS = 30
_PAGE_CACHE_MAX = 500
_PAGE_LOCKS: dict[tuple, "threading.Lock"] = {}


def _anonymous_page_key(slug: str) -> tuple | None:
    """Cache key for a page every first-time visitor sees identically, else None.

    Only the new design, only the home / category pages without a search (searches record analytics events),
    and only for a visitor with an empty session — no cart, favourites, interests, account or chosen area. The
    page is then the same for all such visitors; it is kept 30 s, so price / stock edits show within 30 s."""
    if not v2_enabled() or request.method != "GET" or session.keys():
        return None
    if str(request.args.get("q") or "").strip() or request.args.get("dev"):
        return None
    return (slug, request.full_path, request.headers.get("Sec-GPC") == "1")


@storefront_bp.route("/<tenant_slug>/")
def store_index(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    key = _anonymous_page_key(slug)
    if key is None:
        return _render_store_index(slug)
    hit = _PAGE_CACHE.get(key)
    if hit and hit[0] > time.monotonic():
        return current_app.response_class(hit[1], mimetype="text/html")
    # Expired or missing: ONE request re-renders; the others meanwhile get the previous copy (no burst of
    # identical renders fighting for the CPU when the entry expires under load).
    lock = _PAGE_LOCKS.setdefault(key, threading.Lock())
    if hit and not lock.acquire(blocking=False):
        return current_app.response_class(hit[1], mimetype="text/html")
    if not hit:
        lock.acquire()
        fresh = _PAGE_CACHE.get(key)
        if fresh and fresh[0] > time.monotonic():
            lock.release()
            return current_app.response_class(fresh[1], mimetype="text/html")
    try:
        html = _render_store_index(slug)
        if not session.keys():  # rendering did not personalise anything
            if len(_PAGE_CACHE) >= _PAGE_CACHE_MAX:
                _PAGE_CACHE.clear()
                _PAGE_LOCKS.clear()
            _PAGE_CACHE[key] = (time.monotonic() + _PAGE_CACHE_SECONDS, html.encode("utf-8"))
        return html
    finally:
        lock.release()


def _render_store_index(slug: str) -> str:
    cart = _cart(slug)
    availability = str(request.args.get("availability") or "all").strip().lower()
    criteria = dict(
        q=str(request.args.get("q") or ""),
        min_price=max(0, safe_int(request.args.get("min_price"), 0)),
        max_price=max(0, safe_int(request.args.get("max_price"), 0)),
        availability=availability,
        badge=str(request.args.get("badge") or "").strip(),
        sort=str(request.args.get("sort") or "latest").strip().lower(),
    )
    # One page of cards for the grid + a small bounded pool (first POOL_SIZE) for hero / curated sections.
    page_result = _catalog_page.list_page(slug, page=_safe_page(request.args.get("page")),
                                          per_page=_STORE_PAGE_SIZE, include_catalog=_with_catalog(),
                                          smart=v2_enabled(), province=_delivery_area(), **criteria)
    filtering = bool(criteria["q"].strip() or criteria["min_price"] or criteria["max_price"] or criteria["badge"]
                     or availability != "all" or criteria["sort"] != "latest")
    if v2_enabled() and filtering:
        # the new design shows only the results grid while filtering — no second catalogue pass for a hidden pool
        pool_result = {"cards": page_result["cards"]}
    else:
        pool_result = _catalog_page.list_page(slug, page=1, per_page=_catalog_page.POOL_SIZE, **criteria)
    page_products = page_result["cards"]
    cards = pool_result["cards"]
    badges = _catalog_page.badges(slug, include_catalog=_with_catalog())
    overview = {row["name"]: row["preview"] for row in _catalog_page.category_overview(slug)}
    hero_products = []
    hero_categories: set[str] = set()
    image_cards = [p for p in cards if p.get("image_url")]
    for card in image_cards:
        category = str(card.get("category") or card.get("badge") or "").strip()
        category_key = category.lower()
        if category_key and category_key in hero_categories:
            continue
        hero_products.append(card)
        if category_key:
            hero_categories.add(category_key)
        if len(hero_products) >= 3:
            break
    for card in image_cards:
        if len(hero_products) >= 3:
            break
        if card not in hero_products:
            hero_products.append(card)
    store_design = _settings.design_settings()
    hero_slides = build_hero_slides(cards, store_design)
    flags = _settings.ui_flags()
    product_sections = build_store_sections(cards, flags, store_design.get("card_style") or "classic")
    pagination = _pagination(slug, page_result["total"], page_result["page"], page_result["pages"],
                             page_result["per_page"])
    v2_sections: dict = {}
    personal: dict = {}
    if v2_enabled():
        if criteria["q"].strip() and _safe_page(request.args.get("page")) == 1:
            _signal(slug, "search", query=criteria["q"])
            if not page_result["total"]:
                _signal(slug, "search_none", query=criteria["q"])
    if v2_enabled() and not filtering:  # these sections are shown on the unfiltered home page only
        best = _catalog_page.cards_for_ids(slug, _catalog_page.top_selling_ids(slug, limit=12))
        v2_sections = {
            "best_sellers": [c for c in best if c.get("is_available")][:8],
            "offers": [c for c in cards if int(c.get("old_price") or 0) > int(c.get("price") or 0)][:8],
            "newest": _catalog_page.list_page(slug, sort="id_desc", per_page=8)["cards"],
        }
        personal = {} if _in_holdout(slug) else _personal_sections(slug)
        bundles = [] if _in_holdout(slug) else _home_bundles(slug)
        for key in ("for_you", "after_purchase", "budget"):
            v2_sections[key] = personal.get(key) or []
        v2_sections["bundles"] = bundles
        shown_recs = [key for key in ("for_you", "after_purchase", "budget", "bundles") if v2_sections[key]]
        if shown_recs:
            _signal(slug, "rec_view", section=",".join(shown_recs))
    shown: dict[int, dict] = {}
    section_cards = [c for key, rows in v2_sections.items() if key != "bundles" for c in rows]
    section_cards += [c for b in v2_sections.get("bundles") or [] for c in b["cards"]]
    for card in [*cards, *page_products, *section_cards]:
        if card.get("kind") != "catalog":  # on-request models are not added to a cart
            shown.setdefault(int(card["id"]), card)
    return render_template(
        storefront_template("index.html"),
        products=cards,
        total_products=page_result["total"],
        search_info=page_result.get("search"),
        category_previews=overview,
        category_art={b: category_image_path(b) for b in badges if category_image_path(b)},
        page_products=page_products,
        pagination=pagination,
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
        hero_products=hero_products,
        hero_slides=hero_slides,
        product_sections=product_sections,
        v2_sections=v2_sections,
        personal=personal,
        **_store_context(slug, cart, sale_products=list(shown.values())),
    )


def _personal_sections(slug: str) -> dict:
    """Cards for «مقترح لك» / «مكمّلات لمشترياتك» / «ضمن ميزانيتك» — {} without data, consent or on error."""
    try:
        from modules.personalization import service as personalization

        ids = personalization.home_sections(slug)
        wanted = list(dict.fromkeys(ids["for_you"] + ids["after_purchase"] + ids["budget"]))
        cards = {c["id"]: c for c in _catalog_page.cards_for_ids(slug, wanted)} if wanted else {}
        return {"for_you": [cards[i] for i in ids["for_you"] if i in cards],
                "for_you_category": ids["for_you_category"],
                "after_purchase": [cards[i] for i in ids["after_purchase"] if i in cards],
                "budget": [cards[i] for i in ids["budget"] if i in cards],
                "budget_limit": ids["budget_limit"], "continue": ids["continue"],
                "enabled": personalization.enabled(slug)}
    except Exception:
        current_app.logger.exception("storefront personal sections failed")
        db.session.rollback()
        return {}


@storefront_bp.post("/<tenant_slug>/api/events")
def api_events(tenant_slug: str):
    """Browser-side signals the server cannot see by itself: comparing and recommendation clicks."""
    slug = _resolved_shop_slug(tenant_slug)
    data = request.get_json(silent=True) or {}
    kind = str(data.get("type") or "")
    if kind not in ("compare", "rec_click"):
        return jsonify({"success": False, "error": "نوع غير معروف"}), 400
    if not allow_request("storefront_events", limit=120, window_seconds=60):
        return jsonify({"success": False}), 429
    product_id = safe_int(data.get("product_id"), 0) or None
    _signal(slug, kind, product_id=product_id, section=str(data.get("section") or "")[:40])
    return jsonify({"success": True})


SITEMAP_CHUNK = 10_000


def _xml(body: str):
    from flask import Response

    resp = Response('<?xml version="1.0" encoding="UTF-8"?>\n' + body, mimetype="application/xml")
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


def _sitemap_product_ids(slug: str) -> list[int]:
    from modules.search import engine

    return sorted(d.id for d in engine.documents(slug))


@storefront_bp.get("/<tenant_slug>/sitemap.xml")
def sitemap_index(tenant_slug: str):
    """Sitemap index for this store: one file of pages / categories + product files of ≤10,000 URLs each.
    Submit this URL in Google Search Console for the store."""
    from xml.sax.saxutils import escape

    slug = _resolved_shop_slug(tenant_slug)
    chunks = max(1, -(-len(_sitemap_product_ids(slug)) // SITEMAP_CHUNK))
    urls = [url_for("storefront.sitemap_pages", tenant_slug=slug, _external=True)]
    urls += [url_for("storefront.sitemap_products", tenant_slug=slug, n=i, _external=True) for i in range(1, chunks + 1)]
    items = "".join(f"<sitemap><loc>{escape(u)}</loc></sitemap>" for u in urls)
    return _xml(f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</sitemapindex>')


@storefront_bp.get("/<tenant_slug>/sitemap-pages.xml")
def sitemap_pages(tenant_slug: str):
    from xml.sax.saxutils import escape

    slug = _resolved_shop_slug(tenant_slug)
    urls = [url_for("storefront.store_index", tenant_slug=slug, _external=True)]
    urls += [url_for("storefront.store_index", tenant_slug=slug, badge=b, _external=True)
             for b in _catalog_page.badges(slug, include_catalog=False)]
    for endpoint in ("categories_page", "offers_page", "about_page", "contact_page", "faq_page", "terms_page"):
        urls.append(url_for(f"storefront.{endpoint}", tenant_slug=slug, _external=True))
    items = "".join(f"<url><loc>{escape(u)}</loc></url>" for u in urls)
    return _xml(f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>')


@storefront_bp.get("/<tenant_slug>/sitemap-products-<int:n>.xml")
def sitemap_products(tenant_slug: str, n: int):
    from xml.sax.saxutils import escape

    slug = _resolved_shop_slug(tenant_slug)
    ids = _sitemap_product_ids(slug)[(n - 1) * SITEMAP_CHUNK: n * SITEMAP_CHUNK] if n >= 1 else []
    if not ids and n != 1:
        abort(404)
    items = "".join(f"<url><loc>{escape(url_for('storefront.product_detail', tenant_slug=slug, product_id=i, _external=True))}</loc></url>"
                    for i in ids)
    return _xml(f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>')


_VITAL_PAGES = {"home", "category", "search", "product", "cart", "checkout", "compare", "other"}


@storefront_bp.post("/<tenant_slug>/api/vitals")
def api_vitals(tenant_slug: str):
    """Core Web Vitals of one real page load (LCP / CLS / INP). Anonymous; out-of-range values are dropped."""
    slug = _resolved_shop_slug(tenant_slug)
    if not v2_enabled():
        return jsonify({"success": False}), 404
    if not allow_request("storefront_vitals", limit=60, window_seconds=60):
        return jsonify({"success": False}), 429
    data = request.get_json(silent=True) or {}

    def num(key, high):
        try:
            v = float(data.get(key))
        except (TypeError, ValueError):
            return None
        return v if 0 <= v <= high else None

    lcp, cls, inp = num("lcp", 60000), num("cls", 10), num("inp", 30000)
    if lcp is None and cls is None and inp is None:
        return jsonify({"success": False}), 400
    page = str(data.get("page") or "other")
    from modules.store_analytics.service import save_vital

    save_vital(page if page in _VITAL_PAGES else "other", lcp, cls, inp, bool(data.get("mobile")))
    return jsonify({"success": True, "shop": slug})


@storefront_bp.route("/<tenant_slug>/personalization", methods=["GET", "POST"])
def personalization_page(tenant_slug: str):
    """«لماذا أرى هذا؟»: what the shop inferred, a switch to turn it off and a button to forget it."""
    slug = _resolved_shop_slug(tenant_slug)
    from modules.personalization import service as personalization

    if request.method == "POST":
        action = str(request.form.get("action") or (request.get_json(silent=True) or {}).get("action") or "")
        if action == "off":
            personalization.set_enabled(slug, False)
        elif action == "on":
            personalization.set_enabled(slug, True)
        elif action == "clear":
            personalization.clear(slug)
        else:
            return jsonify({"success": False, "error": "إجراء غير معروف"}), 400
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, **personalization.summary(slug)})
        return redirect(url_for("storefront.personalization_page", tenant_slug=slug, done=action))
    return render_template(
        "storefront_v2/personalization.html",
        info=personalization.summary(slug),
        done=str(request.args.get("done") or ""),
        **_store_context(slug, _cart(slug)),
    )


@storefront_bp.get("/<tenant_slug>/api/products")
def api_products(tenant_slug: str):
    """JSON page of product cards: the search / filter / "load more" endpoint of the storefront script."""
    slug = _resolved_shop_slug(tenant_slug)
    result = _catalog_page.list_page(
        slug,
        q=str(request.args.get("q") or "")[:80],
        min_price=max(0, safe_int(request.args.get("min_price"), 0)),
        max_price=max(0, safe_int(request.args.get("max_price"), 0)),
        availability=str(request.args.get("availability") or "all").strip().lower(),
        badge=str(request.args.get("badge") or "").strip(),
        sort=str(request.args.get("sort") or "latest").strip().lower(),
        page=_safe_page(request.args.get("page")),
        per_page=min(safe_int(request.args.get("per_page"), _STORE_PAGE_SIZE), _catalog_page.MAX_PAGE_SIZE),
        include_catalog=_with_catalog(),
        smart=v2_enabled(),
        province=_delivery_area(),
    )
    response = jsonify({"success": True, "products": result["cards"], "total": result["total"],
                        "search": result.get("search"),
                        "page": result["page"], "pages": result["pages"], "per_page": result["per_page"]})
    response.headers["Cache-Control"] = "no-store"
    return response


@storefront_bp.route("/<tenant_slug>/catalog/<int:entry_id>", methods=["GET", "POST"])
def catalog_detail(tenant_slug: str, entry_id: int):
    """A model the company does not stock yet: specs and photos, and a request-availability form (no order)."""
    from modules.catalog import service as catalog
    from modules.catalog.models import CatalogProduct

    slug = _resolved_shop_slug(tenant_slug)
    if not _with_catalog():
        abort(404)
    entry = db.session.get(CatalogProduct, entry_id)
    rows = [e for e in catalog.published_catalog_only() if e.id == entry_id] if entry else []
    if not rows:
        abort(404)
    sent, error = False, ""
    if request.method == "POST":
        try:
            catalog.request_availability(entry_id, request.form)
            db.session.commit()
            sent = True
        except catalog.CatalogError as exc:
            db.session.rollback()
            error = str(exc)
    return render_template(
        "storefront_v2/catalog_detail.html",
        product=catalog.card(entry, slug), sent=sent, error=error, form=request.form,
        **_store_context(slug, _cart(slug)),
    )


@storefront_bp.post("/<tenant_slug>/api/delivery-area")
def api_delivery_area(tenant_slug: str):
    """The shopper's province (kept in his session) — used for availability, fees and ranking. No exact location."""
    province = str((request.get_json(silent=True) or {}).get("province") or "").strip()[:40]
    known = set(_settings.shipping_config()[0])
    if province and province not in known:
        return jsonify({"success": False, "error": "محافظة غير معروفة"}), 400
    session[_AREA_KEY] = province or None
    session.modified = True
    return jsonify({"success": True, "province": province})


@storefront_bp.get("/<tenant_slug>/api/delivery-quote")
def api_delivery_quote(tenant_slug: str):
    """Where a product (or the cart) would be prepared from for the shopper's province, and the fee."""
    from modules.fulfillment import service as fulfillment

    slug = _resolved_shop_slug(tenant_slug)
    province = str(request.args.get("province") or _delivery_area())[:40]
    if request.args.get("cart") == "1":
        items = [{"product_id": i["id"], "quantity": i["quantity"], "color": i.get("color") or None}
                 for i in _cart(slug).items()]
        return jsonify({"success": True, "province": province, "plan": fulfillment.plan(items, province) if items else None})
    product_id = request.args.get("product_id", type=int)
    product = Product.query.get(product_id) if product_id else None
    if product is None or not cash_store_product_is_visible(product):
        return jsonify({"success": False, "error": "المنتج غير متاح"}), 404
    return jsonify({"success": True, "province": province,
                    "plan": fulfillment.product_availability(product.id, province, request.args.get("color") or None)})


@storefront_bp.get("/<tenant_slug>/api/product/<int:product_id>/options")
def api_product_options(tenant_slug: str, product_id: int):
    """Colour / exchange options of ONE product, for the add-to-cart script when its card was not in the page."""
    slug = _resolved_shop_slug(tenant_slug)
    cards = _catalog_page.cards_for_ids(slug, [product_id])
    if not cards:
        return jsonify({"success": False, "error": "المنتج غير متاح"}), 404
    return jsonify({"success": True, "product": cards[0]})


@storefront_bp.get("/<tenant_slug>/categories")
def categories_page(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    overview = _catalog_page.category_overview(slug)
    categories = [
        {
            "name": row["name"],
            "count": row["count"],
            "preview": row["preview"] or {},
            "category_image": category_image_path(row["name"]),
        }
        for row in overview
    ]
    return render_template(
        storefront_template("categories.html"),
        categories=categories,
        **_store_context(slug, cart, sale_products=[row["preview"] for row in overview if row["preview"]]),
    )


@storefront_bp.get("/<tenant_slug>/offers")
def offers_page(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    cards = _catalog_page.list_page(slug, sort="latest", page=1, per_page=_catalog_page.POOL_SIZE)["cards"]
    offers = [card for card in cards if card.get("featured") or card.get("is_new")]
    if not offers:
        offers = cards[:12]
    return render_template(
        storefront_template("catalog_page.html"),
        page_title="العروض والمنتجات المميزة",
        page_eyebrow="اختيارات المتجر",
        page_description="منتجات مختارة بأسعار نقدية واضحة، مع تحديث التوفر والسعر مباشرة من كتالوج الأقساط.",
        empty_title="لا توجد عروض منشورة حالياً",
        products=offers,
        **_store_context(slug, cart, sale_products=offers),
    )


@storefront_bp.get("/<tenant_slug>/favorites")
def favorites_page(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    favorites = _catalog_page.cards_for_ids(slug, _favorite_ids(slug))
    return render_template(
        storefront_template("catalog_page.html"),
        page_title="قائمة المفضلة",
        page_eyebrow="اختياراتك المحفوظة",
        page_description="احفظ المنتجات التي تريد الرجوع إليها، ثم أضفها إلى السلة عندما تكون جاهزاً للطلب.",
        empty_title="لم تضف منتجات إلى المفضلة بعد",
        products=favorites,
        **_store_context(slug, cart, sale_products=favorites),
    )


@storefront_bp.post("/<tenant_slug>/favorites/<int:product_id>/toggle")
def favorite_toggle(tenant_slug: str, product_id: int):
    slug = _resolved_shop_slug(tenant_slug)
    product = Product.query.get(product_id)
    if not cash_store_product_is_visible(product):
        return jsonify({"success": False, "error": "المنتج غير متاح"}), 404
    ids = _favorite_ids(slug)
    added = product_id not in ids
    if added:
        ids.insert(0, product_id)
    else:
        ids.remove(product_id)
    session[_favorite_session_key(slug)] = ids[:100]
    session.modified = True
    if added:
        _signal(slug, "favorite", product_id=product_id)
    return jsonify({"success": True, "added": added, "count": len(ids)})


@storefront_bp.get("/<tenant_slug>/account")
def account_page(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    ensure_installment_schema()
    cart = _cart(slug)
    account = _current_store_account(slug)
    cash_orders: list[Invoice] = []
    installment_orders: list[InstallmentApplication] = []
    if account:
        cash_orders = (
            Invoice.query.filter_by(customer_id=account.customer_id)
            .order_by(Invoice.created_at.desc(), Invoice.id.desc())
            .limit(100)
            .all()
        )
        installment_orders = (
            InstallmentApplication.query.filter_by(
                tenant_id=_store_tenant_id(), customer_id=account.customer_id
            )
            .order_by(InstallmentApplication.created_at.desc())
            .limit(100)
            .all()
        )
    return render_template(
        storefront_template("account.html"),
        account=account,
        customer=account.customer if account else None,
        cash_orders=cash_orders,
        cash_total=sum(int(order.total or 0) for order in cash_orders),
        installment_orders=installment_orders,
        cash_status_labels=CASH_ORDER_STATUS_LABELS,
        installment_status_labels=INSTALLMENT_STATUS_LABELS,
        track_urls=_order_track_urls(cash_orders) if v2_enabled() else {},
        mode=str(request.args.get("mode") or "login"),
        error=str(request.args.get("error") or "").strip(),
        **_store_context(slug, cart),
    )


def _order_track_urls(orders) -> dict[int, str]:
    """A public «تتبع الطلب» link per order (same signed token the order-success page uses)."""
    out: dict[int, str] = {}
    for order in orders[:30]:
        try:
            out[order.id] = url_for("orders.public_order_view", token=build_public_order_view_token(order.id))
        except Exception:
            continue
    return out


def _account_error(slug: str, message: str, *, mode: str = "login"):
    if request.is_json:
        return jsonify({"success": False, "error": message}), 400
    return redirect(url_for("storefront.account_page", tenant_slug=slug, mode=mode, error=message))


@storefront_bp.post("/<tenant_slug>/account/register")
def account_register(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    ensure_installment_schema()
    if not allow_request("cash_store_account_register", limit=5, window_seconds=60):
        return _account_error(slug, "محاولات كثيرة، حاول بعد دقيقة", mode="register")
    data = request.get_json(silent=True) or request.form.to_dict()
    name = " ".join(str(data.get("name") or "").split())
    password = str(data.get("password") or "")
    try:
        phone = normalize_phone(data.get("phone"))
    except InstallmentError as exc:
        return _account_error(slug, str(exc), mode="register")
    if len(name.split()) < 4 or len(name) > 150:
        return _account_error(slug, "يرجى إدخال الاسم الرباعي كاملاً", mode="register")
    if len(password) < 8 or len(password) > 128:
        return _account_error(slug, "كلمة المرور يجب أن تكون بين 8 و128 حرفاً", mode="register")
    tenant_id = _store_tenant_id()
    if InstallmentCustomerAccount.query.filter_by(tenant_id=tenant_id, phone=phone).first():
        return _account_error(slug, "يوجد حساب بهذا الرقم؛ سجّل الدخول بدلاً من إنشاء حساب جديد")
    customer = find_customer_by_phone(tenant_id, phone)
    if not customer:
        customer = Customer(tenant_id=tenant_id, name=name, phone=phone)
        db.session.add(customer)
        db.session.flush()
    else:
        customer.name = name
        customer.phone = phone
    account = InstallmentCustomerAccount(
        tenant_id=tenant_id,
        customer_id=customer.id,
        phone=phone,
        password_hash=generate_password_hash(password),
        last_login_at=datetime.utcnow(),
    )
    db.session.add(account)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _account_error(slug, "تعذر إنشاء الحساب؛ تحقق من الرقم وحاول مرة أخرى", mode="register")
    session[_account_session_key(slug)] = account.id
    session.modified = True
    if request.is_json:
        return jsonify({"success": True, "customer_id": customer.id}), 201
    return redirect(url_for("storefront.account_page", tenant_slug=slug, welcome=1))


@storefront_bp.post("/<tenant_slug>/account/login")
def account_login(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    ensure_installment_schema()
    if not allow_request("cash_store_account_login", limit=10, window_seconds=60):
        return _account_error(slug, "محاولات كثيرة، حاول بعد دقيقة")
    data = request.get_json(silent=True) or request.form.to_dict()
    try:
        phone = normalize_phone(data.get("phone"))
    except InstallmentError:
        phone = ""
    account = (
        InstallmentCustomerAccount.query.filter_by(
            tenant_id=_store_tenant_id(), phone=phone, is_active=True
        ).first()
        if phone
        else None
    )
    password = str(data.get("password") or "")
    try:
        valid = bool(account and check_password_hash(account.password_hash, password))
    except (TypeError, ValueError):
        valid = False
    if not valid:
        return _account_error(slug, "رقم الهاتف أو كلمة المرور غير صحيحة")
    account.last_login_at = datetime.utcnow()
    db.session.commit()
    session[_account_session_key(slug)] = account.id
    session.modified = True
    if request.is_json:
        return jsonify({"success": True})
    return redirect(url_for("storefront.account_page", tenant_slug=slug))


@storefront_bp.post("/<tenant_slug>/account/logout")
def account_logout(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    session.pop(_account_session_key(slug), None)
    session.modified = True
    if request.is_json:
        return jsonify({"success": True})
    return redirect(url_for("storefront.account_page", tenant_slug=slug))


@storefront_bp.get("/<tenant_slug>/shopping-benefits")
def shopping_benefits_page(tenant_slug: str):
    return _render_info_page(tenant_slug, "benefits")


@storefront_bp.get("/<tenant_slug>/about")
def about_page(tenant_slug: str):
    return _render_info_page(tenant_slug, "about")


@storefront_bp.get("/<tenant_slug>/contact")
def contact_page(tenant_slug: str):
    return _render_info_page(tenant_slug, "contact")


@storefront_bp.get("/<tenant_slug>/faq")
def faq_page(tenant_slug: str):
    return _render_info_page(tenant_slug, "faq")


@storefront_bp.get("/<tenant_slug>/terms")
def terms_page(tenant_slug: str):
    return _render_info_page(tenant_slug, "terms")


def _render_info_page(tenant_slug: str, page_key: str):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    flags = _settings.ui_flags()
    # Optional texts the owner writes (about the shop, return policy); sensible defaults are used when empty —
    # never a promise (like a number of return days) the owner did not make.
    store_texts = {"about": str(flags.get("storefront_about_text") or "").strip()[:1500],
                   "returns": str(flags.get("storefront_returns_policy") or "").strip()[:2000]}
    return render_template(
        storefront_template("info_page.html"),
        page_key=page_key,
        store_texts=store_texts,
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
        delivery_plan=_cart_plan(totals["items"]),
        cart_suggestions=_cart_suggestions(slug, totals["items"]),
        **_store_context(slug, cart),
    )


def _cart_suggestions(shop_slug: str, items: list[dict]) -> list[dict]:
    """«قد تحتاج أيضاً»: verified accessories / bought-together for the cart — shown, never added by themselves."""
    if not v2_enabled() or not items or _in_holdout(shop_slug):
        return []
    try:
        from modules.recommendations import service as recommendations

        picks = recommendations.for_cart(shop_slug, [int(i["id"]) for i in items])
        cards = {c["id"]: c for c in _catalog_page.cards_for_ids(shop_slug, [p["id"] for p in picks])}
        out = [{**cards[p["id"]], "rec_note": p["why"]} for p in picks if p["id"] in cards]
        if out:
            _signal(shop_slug, "rec_view", section="cart")
        return out
    except Exception:
        current_app.logger.exception("storefront cart suggestions failed")
        db.session.rollback()
        return []


@storefront_bp.get("/<tenant_slug>/compare")
def compare_page(tenant_slug: str):
    """Side-by-side comparison of 2–4 products (ids in the query string, chosen by the shopper)."""
    slug = _resolved_shop_slug(tenant_slug)
    from modules.recommendations import service as recommendations

    ids = [safe_int(x, 0) for x in str(request.args.get("ids") or "").split(",") if x.strip()]
    ids = [i for i in ids if i > 0][:4]
    data, error = None, ""
    try:
        data = recommendations.compare(slug, ids)
    except ValueError as exc:
        error = str(exc)
    return render_template(
        "storefront_v2/compare.html",
        comparison=data,
        compare_error=error,
        **_store_context(slug, _cart(slug), sale_products=(data or {}).get("products") or []),
    )


@storefront_bp.get("/<tenant_slug>/api/cards")
def api_cards(tenant_slug: str):
    """Light cards for ids the browser remembers (recently viewed / compare tray). Max 12, visible products only."""
    slug = _resolved_shop_slug(tenant_slug)
    ids = [safe_int(x, 0) for x in str(request.args.get("ids") or "").split(",") if x.strip()]
    ids = list(dict.fromkeys(i for i in ids if i > 0))[:12]
    keep = ("id", "name", "price", "currency_label", "image_url", "url", "is_available", "is_reservation", "brand")
    rows = [{k: c.get(k) for k in keep} for c in _catalog_page.cards_for_ids(slug, ids)]
    return jsonify({"success": True, "rows": rows})


def _cart_plan(items: list[dict]):
    if not v2_enabled() or not items:
        return None
    from modules.fulfillment import service as fulfillment

    return fulfillment.plan([{"product_id": i["id"], "quantity": i["quantity"], "color": i.get("color") or None}
                             for i in items], _delivery_area())


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
    qty = max(1, min(safe_int(request.form.get("quantity"), 1), 9999))
    product = Product.query.get_or_404(product_id)
    if not cash_store_product_is_visible(product):
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": "المنتج غير متاح"}), 400
        abort(400)
    cart = _cart(slug)
    source = request.get_json(silent=True) if request.is_json else request.form
    source = source or {}
    ok, msg = cart.try_add(
        product_id,
        qty,
        color=str(source.get("color") or ""),
        sale_mode=str(source.get("sale_mode") or "normal"),
        source_product_id=safe_int(source.get("trade_in_source_product_id"), 0) or None,
    )
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
    line_keys = request.form.getlist("line_key[]")
    line_qtys = request.form.getlist("line_qty[]")
    updates = {
        key: max(0, min(safe_int(qty, 0), 9999))
        for key, qty in zip(line_keys, line_qtys)
        if key
    }
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
    qty = max(1, min(safe_int(data.get("quantity") or request.form.get("quantity"), 1), 9999))
    if product_id <= 0:
        return jsonify({"success": False, "error": "معرّف المنتج غير صالح"}), 400
    product = Product.query.get(product_id)
    if not cash_store_product_is_visible(product):
        return jsonify({"success": False, "error": "المنتج غير متاح"}), 400
    cart = _cart(slug)
    ok, msg = cart.try_add(
        product_id,
        qty,
        color=str(data.get("color") or request.form.get("color") or ""),
        sale_mode=str(data.get("sale_mode") or request.form.get("sale_mode") or "normal"),
        source_product_id=(
            safe_int(
                data.get("trade_in_source_product_id")
                or request.form.get("trade_in_source_product_id"),
                0,
            )
            or None
        ),
    )
    if not ok:
        return jsonify({"success": False, "error": msg, "cart": cart.summary()}), 400
    _signal(slug, "cart", product_id=product_id)
    return jsonify({"success": True, "message": msg, "cart": cart.summary()})


@storefront_bp.route("/<tenant_slug>/api/cart/update", methods=["POST"])
def api_cart_update(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    data = request.get_json(silent=True) or {}
    product_id = safe_int(data.get("product_id"), 0)
    line_key = str(data.get("line_key") or "")
    qty = safe_int(data.get("quantity"), 0)
    if product_id <= 0 and not line_key:
        return jsonify({"success": False, "error": "معرّف المنتج غير صالح"}), 400
    cart = _cart(slug)
    ok, msg = cart.try_update_quantities({line_key or product_id: qty})
    if not ok:
        return jsonify({"success": False, "error": msg, "cart": cart.summary()}), 400
    if qty <= 0:
        _signal(slug, "cart_remove", product_id=product_id or None)
    return jsonify({"success": True, "message": msg, "cart": cart.summary()})


@storefront_bp.route("/<tenant_slug>/api/shipping-quote", methods=["POST"])
def api_shipping_quote(tenant_slug: str):
    slug = _resolved_shop_slug(tenant_slug)
    cart = _cart(slug)
    data = request.get_json(silent=True) or {}
    city = str(data.get("city") or "").strip()
    if not city:
        return jsonify({"success": False, "error": "المحافظة مطلوبة"}), 400
    fee, breakdown = _settings.shipping_fee_for_cart(city, cart.items())
    return jsonify({"success": True, "fee": fee, "breakdown": breakdown, "city": city})


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
    account = _current_store_account(slug)
    shipping_map, default_fee = _settings.shipping_config()
    checkout_form = {
        "customer_name": account.customer.name if account and account.customer else "",
        "phone": account.phone if account else "",
        "city": account.customer.city if account and account.customer and account.customer.city else "",
        "address": account.customer.address if account and account.customer and account.customer.address else "",
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
        if account and account.customer:
            checkout_form["customer_name"] = account.customer.name
            checkout_form["phone"] = account.phone
        items = cart.items()
        shipping_fee, _ = _settings.shipping_fee_for_cart(checkout_form["city"], items)
        discount_amount, _ = cart.discount_for_subtotal(sum(int(i["line_total"]) for i in items))
        ok, msg, payload = _checkout.create_invoice_from_cart(items, checkout_form, shipping_fee, discount_amount)
        if ok:
            cart.clear()
            order_ref = f"inv:{payload['invoice_id']}"
            _signal(slug, "order", value=order_ref)
            for item in items:
                _signal(slug, "purchase", product_id=int(item["id"]), value=order_ref)
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
        shipping_fee, _ = _settings.shipping_fee_for_cart(checkout_form["city"], cart.items())
    else:
        shipping_fee, _ = _settings.shipping_fee_for_city(checkout_form["city"])
    totals = cart.totals(shipping_fee)
    if request.method == "GET" and totals["items"]:
        _signal(slug, "checkout")

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
