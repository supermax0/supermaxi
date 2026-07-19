"""Mobile catalog over Finora Product (single source of truth)."""
from __future__ import annotations

from flask import g, request
from sqlalchemy import func, or_

from extensions import db
from models.product import Product
from modules.mobile_app.models import MobileFavorite, MobileVideo, MobileVideoProduct
from modules.storefront.services.product_presenter import product_card


def _abs_url(url: str | None) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/"):
        root = (request.url_root or "").rstrip("/")
        return f"{root}{value}"
    return value


def stock_label(qty: int, *, active: bool) -> str:
    if not active:
        return "غير متوفر"
    if qty <= 0:
        return "نفد من المخزون"
    if qty <= 5:
        return "كمية محدودة"
    return "متوفر"


def to_mobile_product(product: Product, *, favorited: bool = False) -> dict:
    slug = getattr(g, "tenant", None) or ""
    card = product_card(product, slug)
    qty = int(product.quantity or 0)
    gallery = [_abs_url(u) for u in (card.get("gallery") or []) if u]
    image = _abs_url(card.get("image_url"))
    return {
        "id": product.id,
        "name": card.get("name") or product.name,
        "description": card.get("description") or "",
        "price": int(card.get("price") or 0),
        "old_price": int(card.get("old_price") or 0),
        "discount_percent": int(card.get("discount_percent") or 0),
        "category": card.get("category") or "",
        "brand": card.get("brand") or "",
        "sku": card.get("sku") or "",
        "badge": card.get("badge") or "",
        "is_new": bool(card.get("is_new")),
        "image_url": image,
        "gallery": gallery,
        "video_url": str(card.get("video_url") or "").strip(),
        "specs": card.get("specs") or [],
        "stock_status": stock_label(qty, active=bool(product.active)),
        "is_available": bool(product.active and qty > 0),
        "favorited": favorited,
    }


def list_categories() -> list[dict]:
    rows = (
        db.session.query(
            Product.catalog_category,
            func.count(Product.id),
        )
        .filter(Product.active == True)  # noqa: E712
        .group_by(Product.catalog_category)
        .all()
    )
    counts = {
        (str(category or "").strip() or "أخرى"): int(count or 0)
        for category, count in rows
    }
    return [
        {"name": name, "products_count": count}
        for name, count in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    ]


def list_products(
    *,
    q: str = "",
    category: str = "",
    sort: str = "latest",
    availability: str = "all",
    limit: int = 40,
    offset: int = 0,
    user_id: int | None = None,
) -> list[dict]:
    query = Product.query.filter(Product.active == True)  # noqa: E712
    if availability == "in_stock":
        query = query.filter(Product.quantity > 0)
    elif availability == "out_stock":
        query = query.filter(Product.quantity <= 0)

    q_norm = (q or "").strip()
    if q_norm:
        like = f"%{q_norm}%"
        query = query.filter(or_(Product.name.ilike(like), Product.description.ilike(like)))

    if category:
        query = query.filter(Product.catalog_category == category.strip())

    if sort == "price_asc":
        query = query.order_by(Product.sale_price.asc(), Product.id.desc())
    elif sort == "price_desc":
        query = query.order_by(Product.sale_price.desc(), Product.id.desc())
    elif sort == "name_asc":
        query = query.order_by(Product.name.asc(), Product.id.desc())
    else:
        query = query.order_by(Product.id.desc())

    products = query.offset(max(0, offset)).limit(min(100, max(1, limit))).all()

    fav_ids: set[int] = set()
    if user_id and products:
        fav_ids = {
            row.product_id
            for row in MobileFavorite.query.filter(
                MobileFavorite.user_id == user_id,
                MobileFavorite.product_id.in_([p.id for p in products]),
            ).all()
        }
    return [to_mobile_product(p, favorited=p.id in fav_ids) for p in products]


def get_product(product_id: int, *, user_id: int | None = None) -> dict | None:
    product = db.session.get(Product, product_id)
    if product is None or not product.active:
        return None
    favorited = False
    if user_id:
        favorited = (
            MobileFavorite.query.filter_by(user_id=user_id, product_id=product.id).first()
            is not None
        )
    data = to_mobile_product(product, favorited=favorited)
    # linked videos
    links = (
        MobileVideoProduct.query.filter_by(product_id=product.id)
        .order_by(MobileVideoProduct.display_order.asc())
        .all()
    )
    video_ids = [link.video_id for link in links]
    videos = []
    if video_ids:
        rows = MobileVideo.query.filter(
            MobileVideo.id.in_(video_ids),
            MobileVideo.deleted_at.is_(None),
            MobileVideo.processing_status == "ready",
            MobileVideo.status.in_(["published", "ready"]),
        ).all()
        by_id = {v.id: v for v in rows}
        for link in links:
            video = by_id.get(link.video_id)
            if not video:
                continue
            videos.append(
                {
                    "id": video.id,
                    "title": video.title,
                    "thumbnail_url": video.thumbnail_url,
                    "playback_url": video.playback_hls_url or video.original_asset_url,
                }
            )
    data["videos"] = videos
    return data


def list_offers(*, user_id: int | None = None, limit: int = 30) -> list[dict]:
    products = (
        Product.query.filter(Product.active == True, Product.quantity > 0)  # noqa: E712
        .order_by(Product.id.desc())
        .limit(200)
        .all()
    )
    offers = []
    for p in products:
        item = to_mobile_product(p)
        if int(item.get("discount_percent") or 0) > 0 or int(item.get("old_price") or 0) > item["price"]:
            offers.append(item)
        if len(offers) >= limit:
            break
    if user_id and offers:
        fav_ids = {
            row.product_id
            for row in MobileFavorite.query.filter(
                MobileFavorite.user_id == user_id,
                MobileFavorite.product_id.in_([o["id"] for o in offers]),
            ).all()
        }
        for o in offers:
            o["favorited"] = o["id"] in fav_ids
    return offers


def search_products(q: str, *, user_id: int | None = None, limit: int = 40) -> list[dict]:
    return list_products(q=q, limit=limit, user_id=user_id)


def toggle_favorite(*, user_id: int, product_id: int) -> tuple[bool, dict | None]:
    product = db.session.get(Product, product_id)
    if product is None or not product.active:
        return False, None
    existing = MobileFavorite.query.filter_by(user_id=user_id, product_id=product_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return False, to_mobile_product(product, favorited=False)
    db.session.add(MobileFavorite(user_id=user_id, product_id=product_id))
    db.session.commit()
    return True, to_mobile_product(product, favorited=True)


def list_favorites(*, user_id: int) -> list[dict]:
    rows = (
        MobileFavorite.query.filter_by(user_id=user_id)
        .order_by(MobileFavorite.id.desc())
        .all()
    )
    result = []
    for row in rows:
        product = db.session.get(Product, row.product_id)
        if product and product.active:
            result.append(to_mobile_product(product, favorited=True))
    return result


def products_for_video(video_id: int, *, user_id: int | None = None) -> list[dict]:
    links = (
        MobileVideoProduct.query.filter_by(video_id=video_id)
        .order_by(MobileVideoProduct.display_order.asc())
        .all()
    )
    result = []
    for link in links:
        product = db.session.get(Product, link.product_id)
        if product is None or not product.active:
            continue
        favorited = False
        if user_id:
            favorited = (
                MobileFavorite.query.filter_by(user_id=user_id, product_id=product.id).first()
                is not None
            )
        item = to_mobile_product(product, favorited=favorited)
        if link.special_price is not None:
            item["special_price"] = int(link.special_price)
        if link.custom_title:
            item["custom_title"] = link.custom_title
        if link.custom_cta:
            item["custom_cta"] = link.custom_cta
        result.append(item)
    return result


def link_product_to_video(
    *,
    video_id: int,
    product_id: int,
    display_order: int = 0,
    special_price: int | None = None,
    custom_title: str | None = None,
    custom_cta: str | None = None,
) -> MobileVideoProduct:
    video = db.session.get(MobileVideo, video_id)
    product = db.session.get(Product, product_id)
    if video is None or video.deleted_at is not None:
        raise ValueError("الفيديو غير موجود")
    if product is None:
        raise ValueError("المنتج غير موجود")
    existing = MobileVideoProduct.query.filter_by(
        video_id=video_id, product_id=product_id
    ).first()
    if existing:
        existing.display_order = display_order
        existing.special_price = special_price
        existing.custom_title = custom_title
        existing.custom_cta = custom_cta
        db.session.commit()
        return existing
    row = MobileVideoProduct(
        video_id=video_id,
        product_id=product_id,
        display_order=display_order,
        special_price=special_price,
        custom_title=custom_title,
        custom_cta=custom_cta,
    )
    db.session.add(row)
    db.session.commit()
    return row
