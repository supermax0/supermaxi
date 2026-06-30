from __future__ import annotations

from sqlalchemy import or_

from models.product import Product
from modules.storefront.services.product_presenter import product_badge, product_card, product_meta


class StorefrontCatalogService:
    def list_products(
        self,
        shop_slug: str,
        *,
        q: str = "",
        min_price: int = 0,
        max_price: int = 0,
        availability: str = "all",
        badge_filter: str = "",
        sort: str = "latest",
    ) -> tuple[list[dict], list[str]]:
        query = Product.query.filter(Product.active == True)  # noqa: E712

        if min_price > 0:
            query = query.filter(Product.sale_price >= min_price)
        if max_price > 0:
            query = query.filter(Product.sale_price <= max_price)
        if availability == "in_stock":
            query = query.filter(Product.quantity > 0)
        elif availability == "out_stock":
            query = query.filter(Product.quantity <= 0)

        q_norm = str(q or "").strip().lower()
        if q_norm:
            like = f"%{q_norm}%"
            query = query.filter(or_(Product.name.ilike(like), Product.description.ilike(like)))

        if sort == "price_asc":
            query = query.order_by(Product.sale_price.asc(), Product.id.desc())
        elif sort == "price_desc":
            query = query.order_by(Product.sale_price.desc(), Product.id.desc())
        elif sort == "name_asc":
            query = query.order_by(Product.name.asc(), Product.id.desc())
        else:
            query = query.order_by(Product.id.desc())

        products = query.all()
        cards = [product_card(p, shop_slug) for p in products]

        if badge_filter:
            cards = [c for c in cards if c["badge"] == badge_filter]

        badges = sorted({product_badge(product_meta(p)) for p in products if product_badge(product_meta(p))})
        return cards, badges

    def featured_products(self, cards: list[dict], limit: int = 6) -> list[dict]:
        return cards[:limit]

    def related_products(self, product_id: int, shop_slug: str, limit: int = 4) -> list[dict]:
        related = (
            Product.query.filter(Product.active == True, Product.id != product_id)  # noqa: E712
            .order_by(Product.id.desc())
            .limit(limit)
            .all()
        )
        return [product_card(item, shop_slug) for item in related]
