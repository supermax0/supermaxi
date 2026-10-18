"""Pricing engine: rules → suggested prices, price files → proposals, approval → applied + audited, promotions.

Money is whole dinars (int). Selling price before rounding = cost basis ÷ (1 − target margin). The cost basis is the
current replacement cost (latest supplier offer) or the product's registered purchase price — informational only:
inventory lots, recorded stock value and closed invoices are never read for writing nor changed here.
"""
from __future__ import annotations

import csv
import io
import json
import math
import time
from datetime import datetime
from typing import Any

from extensions import db
from modules.pricing.models import ALL_TABLES, PriceBatch, PriceHistory, PriceProposal, PriceRule, Promotion, SupplierOffer


class PricingError(Exception):
    def __init__(self, message: str, code: str = "validation", status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


def ensure_tables() -> None:
    conn = db.session.connection()
    for model in ALL_TABLES:
        model.__table__.create(bind=conn, checkfirst=True)


def _products():
    from models.product import Product

    return Product.query.execution_options(skip_branch_scope=True)


def _meta(product) -> dict:
    try:
        return json.loads(product.meta_json or "{}") or {}
    except ValueError:
        return {}


# ───────────────────────────── math ─────────────────────────────


def round_up(value: float, step: int) -> int:
    step = max(1, int(step or 1))
    return int(math.ceil(value / step) * step)


def price_for_margin(cost: int, margin_pct: float, *, extra: int = 0, step: int = 1000) -> int:
    if not 0 <= margin_pct < 90:
        raise PricingError("هامش الربح يجب أن يكون بين 0 و 90%")
    return round_up((int(cost) + int(extra or 0)) / (1 - margin_pct / 100), step)


# ───────────────────────────── rules ─────────────────────────────


def save_rule(data: dict, *, rule_id: int | None = None, by: int | None = None) -> PriceRule:
    ensure_tables()
    scope = str(data.get("scope") or "default")
    if scope not in ("default", "category", "brand", "product"):
        raise PricingError("نطاق القاعدة غير معروف")
    value = str(data.get("scope_value") or "").strip()[:120] or None
    if scope != "default" and not value:
        raise PricingError("حدد القسم أو العلامة أو المنتج")
    target, minimum = float(data.get("target_margin_pct") or 0), float(data.get("minimum_margin_pct") or 0)
    if not 0 < target < 90 or not 0 <= minimum <= target:
        raise PricingError("الهامش المستهدف بين 0 و 90%، والأدنى لا يتجاوز المستهدف")
    step = int(data.get("rounding_step") or 1000)
    if step not in (1, 250, 500, 1000, 5000, 10000):
        raise PricingError("التقريب: 250 أو 500 أو 1,000 أو 5,000 أو 10,000 دينار")
    rule = db.session.get(PriceRule, int(rule_id)) if rule_id else PriceRule(created_by_id=by)
    if rule is None:
        raise PricingError("القاعدة غير موجودة", "not_found", 404)
    clash = PriceRule.query.filter(PriceRule.scope == scope, PriceRule.scope_value == value, PriceRule.active.is_(True))
    if rule_id:
        clash = clash.filter(PriceRule.id != int(rule_id))
    if clash.first() is not None:
        raise PricingError("توجد قاعدة فعّالة لنفس النطاق", "conflict", 409)
    rule.scope, rule.scope_value, rule.target_margin_pct, rule.minimum_margin_pct = scope, value, target, minimum
    rule.extra_cost = max(0, int(data.get("extra_cost") or 0))
    rule.rounding_step = step
    rule.automatic = bool(data.get("automatic"))
    rule.max_auto_change_pct = max(0.0, min(50.0, float(data.get("max_auto_change_pct") or 10)))
    rule.approval_required = bool(data.get("approval_required", True))
    rule.active = bool(data.get("active", True))
    db.session.add(rule)
    db.session.flush()
    return rule


def rule_for(product) -> PriceRule | None:
    meta = _meta(product)
    rules = PriceRule.query.filter_by(active=True).all()
    for scope, value in (("product", str(product.id)), ("brand", str(meta.get("brand") or "").strip()),
                         ("category", str(meta.get("category") or "").strip()), ("default", None)):
        for rule in rules:
            if rule.scope == scope and (scope == "default" or (value and (rule.scope_value or "").casefold() == value.casefold())):
                return rule
    return None


def cost_basis(product) -> tuple[int | None, str]:
    offer = (SupplierOffer.query.filter_by(product_id=product.id, status="active", currency="IQD")
             .order_by(SupplierOffer.updated_at.desc()).first())
    if offer is not None:
        return int(offer.purchase_price), f"عرض المورد {offer.supplier_ref}"
    if int(product.buy_price or 0) > 0:
        return int(product.buy_price), "سعر الشراء المسجّل"
    return None, "لا توجد كلفة معروفة"


def quote(product, *, cost: int | None = None) -> dict[str, Any]:
    rule = rule_for(product)
    basis, source = (cost, "من الملف") if cost else cost_basis(product)
    out = {"product_id": product.id, "name": product.name, "current_price": int(product.sale_price or 0),
           "cost_basis": basis, "cost_source": source, "rule_id": rule.id if rule else None,
           "suggested_price": None, "minimum_price": None}
    if rule is not None and basis:
        out["suggested_price"] = price_for_margin(basis, rule.target_margin_pct, extra=rule.extra_cost, step=rule.rounding_step)
        out["minimum_price"] = price_for_margin(basis, rule.minimum_margin_pct, extra=rule.extra_cost, step=1)
    return out


# ───────────────────────────── proposals ─────────────────────────────


def _verdict(old: int, new: int | None, minimum: int | None) -> str:
    if new is None:
        return "invalid"
    if minimum is not None and new < minimum:
        return "below_minimum"
    if new > old:
        return "up"
    if new < old:
        return "down"
    return "same"


def batch_from_rules(*, product_ids: list[int] | None = None, by: int | None = None) -> PriceBatch:
    ensure_tables()
    from models.product import Product

    query = _products().filter_by(active=True)
    if product_ids:
        query = query.filter(Product.id.in_([int(i) for i in product_ids]))
    batch = PriceBatch(source="rules", label=f"اقتراحات القواعد {datetime.utcnow():%Y-%m-%d %H:%M}", created_by_id=by)
    db.session.add(batch)
    db.session.flush()
    for product in query.all():
        q = quote(product)
        if q["suggested_price"] is None or q["suggested_price"] == q["current_price"]:
            continue
        db.session.add(PriceProposal(batch_id=batch.id, product_id=product.id, row_ref=product.sku or str(product.id),
                                     old_price=q["current_price"], new_price=q["suggested_price"], cost_basis=q["cost_basis"],
                                     minimum_price=q["minimum_price"],
                                     verdict=_verdict(q["current_price"], q["suggested_price"], q["minimum_price"]),
                                     note=q["cost_source"]))
    db.session.flush()
    return batch


_REF = ("barcode", "الباركود", "ean", "sku", "الرمز", "model", "الموديل", "رقم الموديل")
_PRICE = ("price", "new price", "sale price", "سعر البيع", "السعر الجديد", "السعر")
_COST = ("cost", "purchase price", "الكلفة", "سعر الشراء", "سعر المورد")


def _find_product(ref: str):
    from models.product import Product
    from modules.catalog.service import norm_barcode, norm_key

    ref = str(ref or "").strip()
    if not ref:
        return None
    code = norm_barcode(ref)
    if len(code) >= 8:
        hit = _products().filter(Product.barcode == code, Product.active.is_(True)).first()
        if hit is not None:
            return hit
    key = norm_key(ref)
    for pid, sku in _products().filter(Product.active.is_(True), Product.sku.isnot(None)).with_entities(Product.id, Product.sku).all():
        if norm_key(sku) == key:
            return _products().get(pid)
    return None


def batch_from_file(raw: bytes, filename: str, *, supplier_ref: str = "", by: int | None = None) -> PriceBatch:
    """Price list → proposals. A cost column becomes a suggested price through the rules; a price column is taken
    as given. Nothing is applied here."""
    ensure_tables()
    if not raw or len(raw) > 5 * 1024 * 1024:
        raise PricingError("الملف فارغ أو أكبر من 5 ميغابايت")
    name = str(filename or "").lower()
    if name.endswith(".csv"):
        table = list(csv.reader(io.StringIO(raw.decode("utf-8-sig", errors="replace"))))
    elif name.endswith(".xlsx"):
        from openpyxl import load_workbook

        sheet = load_workbook(io.BytesIO(raw), read_only=True, data_only=True).worksheets[0]
        table = [["" if v is None else str(v) for v in r] for r in sheet.iter_rows(values_only=True)]
    else:
        raise PricingError("الملفات المدعومة: Excel (.xlsx) أو CSV")
    table = [r for r in table if any(str(c).strip() for c in r)]
    if len(table) < 2:
        raise PricingError("لا توجد صفوف أسعار")
    heads = [" ".join(str(h).strip().casefold().split()) for h in table[0]]
    col = lambda names: next((i for i, h in enumerate(heads) if h in names), None)  # noqa: E731
    ref_i, price_i, cost_i = col(_REF), col(_PRICE), col(_COST)
    if ref_i is None or (price_i is None and cost_i is None):
        raise PricingError("يلزم عمود للباركود/الموديل وعمود للسعر أو الكلفة")
    batch = PriceBatch(source="file", label=f"{filename}" + (f" — {supplier_ref}" if supplier_ref else ""), created_by_id=by)
    db.session.add(batch)
    db.session.flush()
    for row in table[1:2001]:
        ref = str(row[ref_i] if ref_i < len(row) else "").strip()

        def money(i):
            try:
                return int(float(str(row[i]).replace(",", ""))) if i is not None and i < len(row) and str(row[i]).strip() else None
            except ValueError:
                return -1

        explicit, cost = money(price_i), money(cost_i)
        product = _find_product(ref)
        if product is None:
            db.session.add(PriceProposal(batch_id=batch.id, row_ref=ref[:120], verdict="unmatched", note="لا يوجد منتج مطابق"))
            continue
        if (explicit is not None and explicit <= 0) or (cost is not None and cost <= 0):
            db.session.add(PriceProposal(batch_id=batch.id, product_id=product.id, row_ref=ref[:120], verdict="invalid",
                                         old_price=int(product.sale_price or 0), note="قيمة غير صحيحة"))
            continue
        q = quote(product, cost=cost)
        new = explicit if explicit is not None else q["suggested_price"]
        note = "سعر من الملف" if explicit is not None else (q["cost_source"] if new else "لا توجد قاعدة تسعير لهذا المنتج")
        db.session.add(PriceProposal(batch_id=batch.id, product_id=product.id, row_ref=ref[:120], old_price=q["current_price"],
                                     new_price=new, cost_basis=cost or q["cost_basis"], minimum_price=q["minimum_price"],
                                     verdict=_verdict(q["current_price"], new, q["minimum_price"]),
                                     note=(f"cost:{cost}|supplier:{supplier_ref or filename}" if cost else note)[:255]))
    db.session.flush()
    return batch


def batch_view(batch: PriceBatch) -> dict[str, Any]:
    from models.product import Product

    rows = PriceProposal.query.filter_by(batch_id=batch.id).order_by(PriceProposal.id).all()
    names = {p.id: p.name for p in _products().filter(
        Product.id.in_([r.product_id for r in rows if r.product_id] or [0])).all()}
    counts: dict[str, int] = {}
    impact = 0
    for r in rows:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
        if r.verdict in ("up", "down"):
            impact += int(r.new_price or 0) - int(r.old_price or 0)
    return {"id": batch.id, "label": batch.label, "source": batch.source, "status": batch.status, "counts": counts,
            "net_change_per_unit": impact,
            "rows": [{"id": r.id, "product_id": r.product_id, "name": names.get(r.product_id, ""), "ref": r.row_ref or "",
                      "old_price": r.old_price, "new_price": r.new_price, "cost_basis": r.cost_basis,
                      "minimum_price": r.minimum_price, "verdict": r.verdict,
                      "note": (r.note or "").split("|")[0] if not (r.note or "").startswith("cost:") else "كلفة من الملف",
                      "applied": r.applied} for r in rows]}


def _set_price(product, new_price: int, *, source: str, reason: str, batch_id: int | None = None,
               by: int | None = None) -> None:
    """The only writer of a selling price in this module: product price (+ an in-sync shop listing) and history."""
    old = int(product.sale_price or 0)
    if old == int(new_price):
        return
    product.sale_price = int(new_price)
    try:
        from modules.installments.models import InstallmentProduct

        listing = InstallmentProduct.query.filter_by(product_id=product.id).first()
        if listing is not None and int(listing.cash_price or 0) == old:
            listing.cash_price = int(new_price)  # the shop showed the same price: keep them in step
    except Exception:
        pass
    db.session.add(PriceHistory(product_id=product.id, old_price=old, new_price=int(new_price), source=source,
                                reason=(reason or "")[:255] or None, batch_id=batch_id, approved_by_id=by))


def approve(batch_id: int, *, by: int | None) -> dict[str, int]:
    ensure_tables()
    batch = db.session.get(PriceBatch, int(batch_id))
    if batch is None:
        raise PricingError("الدفعة غير موجودة", "not_found", 404)
    if batch.status != "draft":
        raise PricingError("قُرّرت هذه الدفعة مسبقاً", "conflict", 409)
    result = {"applied": 0, "stale": 0, "skipped": 0}
    for row in PriceProposal.query.filter_by(batch_id=batch.id).all():
        if row.verdict not in ("up", "down") or not row.product_id:
            result["skipped"] += 1
            continue
        product = _products().get(row.product_id)
        if product is None or int(product.sale_price or 0) != int(row.old_price or 0):
            result["stale"] += 1  # the price moved since the preview: never overwrite an unseen change
            continue
        _set_price(product, int(row.new_price), source="batch", reason=batch.label, batch_id=batch.id, by=by)
        if row.note and row.note.startswith("cost:"):
            parts = dict(p.split(":", 1) for p in row.note.split("|"))
            ref = parts.get("supplier", batch.label)[:120]
            offer = SupplierOffer.query.filter_by(supplier_ref=ref, product_id=product.id).first() or \
                SupplierOffer(supplier_ref=ref, product_id=product.id)
            offer.purchase_price, offer.status = int(parts["cost"]), "active"
            db.session.add(offer)
        row.applied = True
        result["applied"] += 1
    batch.status, batch.approved_by_id, batch.decided_at = "applied", by, datetime.utcnow()
    db.session.flush()
    return result


def reject(batch_id: int, *, by: int | None) -> None:
    batch = db.session.get(PriceBatch, int(batch_id))
    if batch is None or batch.status != "draft":
        raise PricingError("لا توجد دفعة مسودة بهذا الرقم", "conflict", 409)
    batch.status, batch.approved_by_id, batch.decided_at = "rejected", by, datetime.utcnow()


def run_automatic(*, by: int | None = None) -> dict[str, int]:
    """Rules marked automatic and not needing approval: apply changes within their maximum step, propose the rest."""
    ensure_tables()
    applied = proposed = 0
    for product in _products().filter_by(active=True).all():
        rule = rule_for(product)
        if rule is None or not rule.automatic:
            continue
        q = quote(product)
        new, old = q["suggested_price"], q["current_price"]
        if not new or new == old or (q["minimum_price"] and new < q["minimum_price"]):
            continue
        change = abs(new - old) / old * 100 if old else 100
        if not rule.approval_required and change <= rule.max_auto_change_pct:
            _set_price(product, new, source="auto_rule", reason=f"قاعدة تسعير #{rule.id}", by=by)
            applied += 1
        else:
            proposed += 1
    db.session.flush()
    return {"applied": applied, "needs_approval": proposed}


# ───────────────────────────── promotions ─────────────────────────────


def create_promotion(data: dict, *, by: int | None) -> Promotion:
    ensure_tables()
    product = _products().get(int(data.get("product_id") or 0))
    if product is None:
        raise PricingError("المنتج غير موجود", "not_found", 404)
    try:
        start = datetime.fromisoformat(str(data.get("starts_at")))
        end = datetime.fromisoformat(str(data.get("ends_at")))
    except ValueError:
        raise PricingError("حدد بداية ونهاية العرض") from None
    price = int(data.get("promo_price") or 0)
    if end <= start:
        raise PricingError("نهاية العرض يجب أن تكون بعد بدايته")
    if not 0 < price < int(product.sale_price or 0):
        raise PricingError("سعر العرض يجب أن يكون أقل من السعر الحالي (خصم حقيقي)")
    q = quote(product)
    if q["minimum_price"] and price < q["minimum_price"]:
        raise PricingError(f"سعر العرض أقل من الحد الآمن ({q['minimum_price']:,} د.ع)", "below_minimum", 409)
    overlap = Promotion.query.filter(Promotion.product_id == product.id, Promotion.status.in_(("scheduled", "running")),
                                     Promotion.starts_at < end, Promotion.ends_at > start).first()
    if overlap is not None:
        raise PricingError("يوجد عرض آخر لنفس المنتج في هذه الفترة", "conflict", 409)
    promo = Promotion(product_id=product.id, promo_price=price, starts_at=start, ends_at=end, created_by_id=by,
                      note=str(data.get("note") or "")[:255] or None)
    db.session.add(promo)
    db.session.flush()
    return promo


def _set_old_price(product, value: int | None) -> None:
    meta = _meta(product)
    if value:
        meta["old_price"] = int(value)
    else:
        meta.pop("old_price", None)
    product.meta_json = json.dumps(meta, ensure_ascii=False)


def _end(promo: Promotion, product, *, cancelled: bool = False) -> None:
    if promo.status == "running":
        if int(product.sale_price or 0) == int(promo.promo_price):
            _set_price(product, int(promo.regular_price), source="promotion_end", reason=f"نهاية العرض #{promo.id}")
            _set_old_price(product, None)
        else:
            promo.status = "conflict"  # someone changed the price during the promotion: never overwrite it
            return
    promo.status = "cancelled" if cancelled else "ended"


def run_due(now: datetime | None = None) -> dict[str, int]:
    ensure_tables()
    now = now or datetime.utcnow()
    started = ended = 0
    for promo in Promotion.query.filter(Promotion.status == "running", Promotion.ends_at <= now).all():
        product = _products().get(promo.product_id)
        if product is not None:
            _end(promo, product)
            ended += 1
    for promo in Promotion.query.filter(Promotion.status == "scheduled", Promotion.starts_at <= now).all():
        product = _products().get(promo.product_id)
        if product is None:
            promo.status = "cancelled"
            continue
        if promo.ends_at <= now:
            promo.status = "ended"
            continue
        promo.regular_price = int(product.sale_price or 0)
        _set_price(product, int(promo.promo_price), source="promotion_start", reason=f"بداية العرض #{promo.id}")
        _set_old_price(product, promo.regular_price)  # the shop now shows a real, dated discount
        promo.status = "running"
        started += 1
    db.session.flush()
    return {"started": started, "ended": ended}


def cancel_promotion(promo_id: int) -> Promotion:
    promo = db.session.get(Promotion, int(promo_id))
    if promo is None or promo.status not in ("scheduled", "running"):
        raise PricingError("لا يوجد عرض فعّال بهذا الرقم", "conflict", 409)
    product = _products().get(promo.product_id)
    _end(promo, product, cancelled=True)
    return promo


_LAST_RUN: dict[str, float] = {}


def run_due_throttled(tenant: str) -> None:
    """Called from busy paths (shop pages): at most once a minute per company, and never raises."""
    now = time.monotonic()
    if _LAST_RUN.get(tenant, 0) > now:
        return
    _LAST_RUN[tenant] = now + 60
    try:
        from sqlalchemy import inspect

        if not inspect(db.session.connection()).has_table(Promotion.__tablename__):
            return
        if Promotion.query.filter(Promotion.status.in_(("scheduled", "running"))).first() is None:
            return
        run_due()
        db.session.commit()
    except Exception:
        db.session.rollback()
