"""Delivery fee quote API for POS, quick sale, and other channels."""

from flask import Blueprint, jsonify, request, session

from models.product import Product
from utils.product_delivery_fees import fee_for_cart_items

delivery_fee_api_bp = Blueprint("delivery_fee_api", __name__, url_prefix="/api/delivery-fee")


@delivery_fee_api_bp.before_request
def _guard():
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "غير مصرح"}), 401
    return None


@delivery_fee_api_bp.route("/quote", methods=["POST"])
def quote():
    data = request.get_json(silent=True) or {}
    province = str(data.get("city") or data.get("province") or "").strip()
    if not province:
        return jsonify({"ok": False, "error": "المحافظة مطلوبة"}), 400

    raw_items = data.get("items") or []
    if not isinstance(raw_items, list) or not raw_items:
        return jsonify({"ok": False, "error": "لا توجد منتجات"}), 400

    clean_items = []
    product_ids = []
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        try:
            product_id = int(row.get("product_id") or 0)
        except (TypeError, ValueError):
            continue
        try:
            qty = int(row.get("qty") or 1)
        except (TypeError, ValueError):
            qty = 1
        if product_id <= 0:
            continue
        clean_items.append({"product_id": product_id, "qty": max(1, qty)})
        product_ids.append(product_id)

    if not clean_items:
        return jsonify({"ok": False, "error": "لا توجد منتجات صالحة"}), 400

    products = Product.query.filter(Product.id.in_(product_ids)).all()
    products_by_id = {p.id: p for p in products}
    fee, breakdown = fee_for_cart_items(clean_items, province, products_by_id)
    return jsonify({"ok": True, "fee": fee, "breakdown": breakdown, "province": province})
