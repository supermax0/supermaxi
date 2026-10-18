"""Product search for in-call tools."""

from __future__ import annotations

from flask import request

from models.product import Product
from modules.phone_app.api.v1.routes import phone_api_v1_bp, require_phone_auth
from modules.phone_app.schemas import api_ok


@phone_api_v1_bp.get("/products/search")
@require_phone_auth
def products_search():
    q = (request.args.get("q") or "").strip()
    query = Product.query
    if hasattr(Product, "active"):
        query = query.filter(Product.active == True)  # noqa: E712
    if q:
        filters = [Product.name.contains(q)]
        if hasattr(Product, "sku"):
            filters.append(Product.sku.contains(q))
        if hasattr(Product, "barcode"):
            filters.append(Product.barcode.contains(q))
        from sqlalchemy import or_

        query = query.filter(or_(*filters))
    rows = query.order_by(Product.name).limit(30).all()
    products = []
    for p in rows:
        qty = getattr(p, "quantity", None)
        threshold = getattr(p, "low_stock_threshold", None)
        try:
            qty_n = float(qty) if qty is not None else None
        except (TypeError, ValueError):
            qty_n = None
        try:
            thr_n = int(threshold) if threshold is not None else 5
        except (TypeError, ValueError):
            thr_n = 5
        low = qty_n is not None and qty_n <= thr_n
        out_of_stock = qty_n is not None and qty_n <= 0
        products.append(
            {
                "id": p.id,
                "name": p.name,
                "sku": getattr(p, "sku", None) or "",
                "barcode": getattr(p, "barcode", None) or "",
                "sale_price": getattr(p, "sale_price", None),
                "quantity": qty,
                "low_stock_threshold": thr_n,
                "low_stock": low,
                "out_of_stock": out_of_stock,
                "image_url": getattr(p, "image_url", None) or "",
            }
        )
    return api_ok({"products": products})
