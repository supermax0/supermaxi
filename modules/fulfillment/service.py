"""Fulfilment planning from real data only.

* availability per branch = FINORA branch stock (the same figure the order screens use), never an estimate;
* a branch is preferred when it can prepare the WHOLE order — even if it is farther — then the one in the
  shopper's province; only when no branch has everything is the order split (and the shopper is told);
* the delivery fee is the company's configured fee for the province;
* a delivery time is shown only when the company configured one for that province — otherwise nothing is promised.
"""
from __future__ import annotations

from typing import Any

from modules.search.lexicon import normalize


def _settings():
    from modules.storefront.services.settings_service import StorefrontSettingsService

    return StorefrontSettingsService()


def delivery_fee(province: str) -> int | None:
    if not province:
        return None
    fees, default = _settings().shipping_config()
    for city, fee in fees.items():
        if normalize(city) == normalize(province):
            return int(fee)
    return int(default)


def delivery_days(province: str) -> str | None:
    """Company-stated delivery time for a province («1-2») — None when nothing was configured."""
    if not province:
        return None
    raw = _settings().ui_flags().get("storefront_delivery_days") or {}
    if not isinstance(raw, dict):
        return None
    for city, days in raw.items():
        if normalize(city) == normalize(province) and str(days).strip():
            return str(days).strip()[:20]
    return None


def _branches() -> list[dict[str, Any]]:
    from models.branch import Branch

    rows = Branch.query.filter_by(is_active=True).order_by(Branch.is_default.desc(), Branch.id).all()
    profiles: dict[int, str] = {}
    try:
        from models.branch_profile import BranchProfile

        profiles = {p.branch_id: p.governorate or "" for p in BranchProfile.query.all()}
    except Exception:
        pass
    return [{"id": b.id, "name": b.name, "default": bool(b.is_default), "governorate": profiles.get(b.id, "")} for b in rows]


def _allowed_branches() -> list[dict[str, Any]]:
    """Every branch when the company sells from all branches' stock; otherwise the shop's own (default) branch."""
    from utils.branch_sales import is_sell_from_all_branches_enabled

    branches = _branches()
    if is_sell_from_all_branches_enabled():
        return branches
    return [b for b in branches if b["default"]][:1] or branches[:1]


def _qty(branch_id: int, product_id: int, color: str | None) -> int:
    from utils.branch_sales import available_fulfillment_qty

    try:
        return int(available_fulfillment_qty(int(branch_id), int(product_id), color) or 0)
    except Exception:
        return 0


def plan(items: list[dict[str, Any]], province: str = "") -> dict[str, Any]:
    """items: [{product_id, quantity, color?}] → where it can be prepared, the fee, and a promise only if stated."""
    branches = _allowed_branches()
    wanted = [(int(i["product_id"]), max(1, int(i.get("quantity") or 1)), i.get("color") or None) for i in items]
    stock = {(b["id"], pid, color): _qty(b["id"], pid, color) for b in branches for pid, _, color in wanted}
    local = lambda b: bool(province) and normalize(b["governorate"]) == normalize(province)  # noqa: E731
    full = [b for b in branches if all(stock[(b["id"], pid, c)] >= q for pid, q, c in wanted)]
    fee, days = delivery_fee(province), delivery_days(province)
    if full:
        best = sorted(full, key=lambda b: (not local(b), not b["default"], b["id"]))[0]
        return {"mode": "single", "branch": {"id": best["id"], "name": best["name"], "local": local(best)},
                # a stated delivery time holds for the shop's usual dispatch point or a branch in the province
                "fee": fee, "days": days if (local(best) or best["default"]) else None, "missing": [], "parts": []}
    parts, missing = [], []
    for pid, q, c in wanted:
        options = sorted((b for b in branches if stock[(b["id"], pid, c)] >= q),
                         key=lambda b: (not local(b), not b["default"], b["id"]))
        if options:
            parts.append({"product_id": pid, "branch_id": options[0]["id"], "branch": options[0]["name"]})
        else:
            missing.append(pid)
    if not parts:
        return {"mode": "unavailable", "branch": None, "fee": fee, "days": None, "missing": missing, "parts": []}
    # a split order may arrive in more than one shipment: no single delivery time is promised
    return {"mode": "split", "branch": None, "fee": fee, "days": None, "missing": missing, "parts": parts}


def product_availability(product_id: int, province: str = "", color: str | None = None) -> dict[str, Any]:
    out = plan([{"product_id": product_id, "quantity": 1, "color": color}], province)
    out["branches_with_stock"] = sum(1 for b in _allowed_branches() if _qty(b["id"], product_id, color) > 0)
    return out


def governorate_stock_index() -> dict[int, set[str]]:
    """{product id (shop copy): {normalised governorates that hold stock}} for the search delivery weight.

    One query over branch stock; product copies of other branches are folded onto the shop's product through
    their catalogue group, exactly as FINORA links per-branch copies."""
    from extensions import db
    from models.branch import BranchStock
    from models.product import Product

    gov = {b["id"]: normalize(b["governorate"]) for b in _allowed_branches() if b["governorate"]}
    if not gov:
        return {}
    rows = (db.session.query(Product.catalog_group_id, BranchStock.branch_id)
            .join(BranchStock, BranchStock.product_id == Product.id)
            .execution_options(skip_branch_scope=True)
            .filter(BranchStock.quantity > 0, BranchStock.branch_id.in_(list(gov))).all())
    by_group: dict[str, set[str]] = {}
    for group, branch_id in rows:
        by_group.setdefault(str(group), set()).add(gov[int(branch_id)])
    shop_rows = (Product.query.execution_options(skip_branch_scope=True)
                 .with_entities(Product.id, Product.catalog_group_id).filter(Product.active.is_(True)).all())
    return {int(pid): by_group[str(group)] for pid, group in shop_rows if str(group) in by_group}
