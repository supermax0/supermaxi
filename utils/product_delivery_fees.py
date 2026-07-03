"""Per-product delivery fees by province with global fallback."""

from __future__ import annotations

import json
from typing import Any

from models.product import Product


def _safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalized_province(value: str) -> str:
    return str(value or "").replace("-", " ").strip().lower()


def load_product_meta(product: Product | None) -> dict:
    if not product:
        return {}
    raw = (getattr(product, "meta_json", None) or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def product_delivery_config(product: Product | None) -> dict[str, Any]:
    meta = load_product_meta(product)
    by_province = meta.get("delivery_by_province")
    if not isinstance(by_province, dict):
        by_province = {}
    clean_by_province: dict[str, int] = {}
    for name, fee in by_province.items():
        province = str(name or "").strip()
        if not province:
            continue
        clean_by_province[province] = max(0, _safe_int(fee, 0))
    default_raw = meta.get("delivery_default_fee")
    if default_raw is None or str(default_raw).strip() == "":
        default_fee = max(0, _safe_int(getattr(product, "shipping_cost", 0), 0))
    else:
        default_fee = max(0, _safe_int(default_raw, 0))
    return {
        "delivery_by_province": clean_by_province,
        "delivery_default_fee": default_fee,
    }


def global_fallback_fee(province: str) -> int:
    try:
        from modules.storefront.services.settings_service import StorefrontSettingsService

        fee, _ = StorefrontSettingsService().shipping_fee_for_city(province)
        return max(0, _safe_int(fee, 0))
    except Exception:
        return 0


def fee_for_product(product: Product | None, province: str) -> int:
    if not product:
        return global_fallback_fee(province)

    config = product_delivery_config(product)
    by_province = config["delivery_by_province"]
    normalized = normalized_province(province)

    for name, fee in by_province.items():
        if normalized_province(name) == normalized:
            return max(0, _safe_int(fee, 0))

    default_fee = max(0, _safe_int(config.get("delivery_default_fee"), 0))
    if default_fee > 0:
        return default_fee

    return global_fallback_fee(province)


def fee_for_cart_items(
    items: list[dict],
    province: str,
    products_by_id: dict[int, Product] | None = None,
) -> tuple[int, list[dict]]:
    total = 0
    breakdown: list[dict] = []
    for item in items or []:
        product_id = _safe_int(item.get("product_id"), 0)
        qty = max(1, _safe_int(item.get("qty"), 1))
        if product_id <= 0:
            continue
        product = (products_by_id or {}).get(product_id)
        if product is None:
            product = Product.query.get(product_id)
        unit_fee = fee_for_product(product, province)
        line_fee = unit_fee * qty
        total += line_fee
        breakdown.append(
            {
                "product_id": product_id,
                "product_name": getattr(product, "name", None) or "",
                "unit_fee": unit_fee,
                "qty": qty,
                "line_fee": line_fee,
            }
        )
    return total, breakdown


def delivery_fees_from_form(form, province_names: list[str] | None = None) -> tuple[dict[str, int], int]:
    names = form.getlist("delivery_province_name")
    fees = form.getlist("delivery_province_fee")
    default_fee = max(0, _safe_int(form.get("delivery_default_fee"), 0))
    by_province: dict[str, int] = {}
    for idx, raw_name in enumerate(names):
        province = str(raw_name or "").strip()
        if not province:
            continue
        raw_fee = fees[idx] if idx < len(fees) else ""
        if str(raw_fee).strip() == "":
            by_province[province] = default_fee
        else:
            by_province[province] = max(0, _safe_int(raw_fee, 0))

    if province_names:
        for province in province_names:
            clean = str(province or "").strip()
            if clean and clean not in by_province:
                by_province[clean] = default_fee

    return by_province, default_fee


def apply_delivery_fees_to_meta(meta: dict, by_province: dict[str, int], default_fee: int) -> dict:
    meta = dict(meta or {})
    if by_province:
        meta["delivery_by_province"] = {
            str(name).strip(): max(0, _safe_int(fee, 0))
            for name, fee in by_province.items()
            if str(name).strip()
        }
    else:
        meta.pop("delivery_by_province", None)
    meta["delivery_default_fee"] = max(0, _safe_int(default_fee, 0))
    if meta["delivery_default_fee"] <= 0:
        meta.pop("delivery_default_fee", None)
    return meta
