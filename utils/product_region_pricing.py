"""Baghdad (primary) vs other-provinces selling price for inventory products."""

from __future__ import annotations

import json

from models.product import Product
from utils.tenant_provinces import DEFAULT_PRIMARY, get_tenant_provinces_config


META_FLAG = "dual_region_pricing"


def _load_meta(product: Product | None) -> dict:
    if not product:
        return {}
    raw = (getattr(product, "meta_json", None) or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def product_has_dual_region_pricing(product: Product | None) -> bool:
    return bool(_load_meta(product).get(META_FLAG))


def set_dual_region_pricing_flag(meta: dict | None, enabled: bool) -> dict:
    out = dict(meta or {})
    if enabled:
        out[META_FLAG] = True
    else:
        out.pop(META_FLAG, None)
    return out


def primary_province_name() -> str:
    from utils.card_batch import current

    batch = current()
    if batch and batch.get("province"):
        return batch["province"]
    try:
        return (get_tenant_provinces_config().get("primary") or DEFAULT_PRIMARY).strip() or DEFAULT_PRIMARY
    except Exception:
        return DEFAULT_PRIMARY


def _norm(value: str | None) -> str:
    return str(value or "").replace("-", " ").strip().casefold()


def is_primary_province(city: str | None) -> bool:
    """True when the customer is in Baghdad (primary) or city is empty (default)."""
    city_clean = (city or "").strip()
    if not city_clean:
        return True
    primary = primary_province_name()
    if _norm(city_clean) == _norm(primary):
        return True
    # Legacy / UI group label must not count as primary.
    try:
        group_label = (get_tenant_provinces_config().get("group_label") or "").strip()
        if group_label and _norm(city_clean) == _norm(group_label):
            return False
    except Exception:
        pass
    return False


def product_governorate_sale_price(product: Product | None) -> int | None:
    if not product:
        return None
    raw = getattr(product, "governorate_sale_price", None)
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def resolve_region_sale_price(
    product: Product | None,
    city: str | None = None,
    *,
    color_name: str | None = None,
    bagdad_price: int | None = None,
    governorate_price: int | None = None,
) -> int:
    """Pick Baghdad vs governorates sale price for a product (optional color)."""
    if product is None:
        return max(0, int(bagdad_price or 0))

    primary_price = bagdad_price
    gov_price = governorate_price

    if color_name:
        from utils.product_color_service import (
            effective_color_governorate_sale_price,
            effective_color_sale_price,
        )

        if primary_price is None:
            primary_price = effective_color_sale_price(product, color_name)
        if gov_price is None and product_has_dual_region_pricing(product):
            gov_price = effective_color_governorate_sale_price(product, color_name)
    else:
        if primary_price is None:
            primary_price = int(getattr(product, "sale_price", 0) or 0)
        if gov_price is None:
            gov_price = product_governorate_sale_price(product)

    primary_price = max(0, int(primary_price or 0))
    if not product_has_dual_region_pricing(product):
        return primary_price
    if is_primary_province(city):
        return primary_price
    gov = max(0, int(gov_price or 0)) if gov_price is not None else 0
    return gov if gov > 0 else primary_price


def region_pricing_payload(product: Product | None) -> dict:
    """Fields for POS / quick-sale product bootstrap."""
    enabled = product_has_dual_region_pricing(product)
    gov = product_governorate_sale_price(product) if enabled else None
    return {
        "dual_region_pricing": enabled,
        "governorate_sale_price": gov,
        "primary_province": primary_province_name(),
    }
