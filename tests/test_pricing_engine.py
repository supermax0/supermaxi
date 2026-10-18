"""Smart Commerce Sprint 5: selling prices change through previewed, approved, audited proposals — never the stock
valuation, the recorded purchase cost or a closed invoice."""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta

import pytest

from tests.test_branch_management_api import _client, _json, _make_ctx, app  # noqa: F401

API = "/api/v1/desktop/pricing"


@pytest.fixture()
def shop(app, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")
    from flask import g

    from extensions import db
    from models.product import Product
    from utils.branch_migration import get_default_branch

    ids = _make_ctx(app)
    with app.test_request_context():
        g.tenant = ids["tenant"]
        branch = get_default_branch().id
        rows = [
            Product(name="شاشة LG 55", sku="55UR80", barcode="8806091111111", buy_price=450_000, sale_price=500_000,
                    quantity=3, active=True, branch_id=branch, meta_json=json.dumps({"category": "شاشات", "brand": "LG"})),
            Product(name="غسالة سامسونج", sku="WW90", barcode="8806092222222", buy_price=300_000, sale_price=420_000,
                    quantity=2, active=True, branch_id=branch, meta_json=json.dumps({"category": "غسالات", "brand": "Samsung"})),
        ]
        db.session.add_all(rows)
        db.session.commit()
        ids.update(tv=rows[0].id, washer=rows[1].id)
    return {**ids, "admin": _client(ids), "app": app}


def _db(shop):
    from flask import g

    ctx = shop["app"].test_request_context()
    ctx.push()
    g.tenant = shop["tenant"]
    return ctx


def _price(shop, pid):
    from models.product import Product

    ctx = _db(shop)
    try:
        p = Product.query.execution_options(skip_branch_scope=True).get(pid)
        return int(p.sale_price), int(p.buy_price), json.loads(p.meta_json or "{}")
    finally:
        ctx.pop()


def test_margin_formula_rounding_and_rule_precedence(shop):
    from modules.pricing.service import price_for_margin

    p = price_for_margin(450_000, 20, step=1000)
    assert p == 563_000 and (p - 450_000) / p >= 0.20  # cost ÷ (1 − margin), rounded UP: the margin is kept
    assert price_for_margin(450_000, 20, step=5000) == 565_000
    _json(shop["admin"].post(f"{API}/rules", json={"scope": "default", "target_margin_pct": 10, "minimum_margin_pct": 5}))
    _json(shop["admin"].post(f"{API}/rules", json={"scope": "category", "scope_value": "شاشات", "target_margin_pct": 15}))
    _json(shop["admin"].post(f"{API}/rules", json={"scope": "brand", "scope_value": "lg", "target_margin_pct": 20}))
    tv = _json(shop["admin"].get(f"{API}/quote/{shop['tv']}"))["quote"]
    assert tv["suggested_price"] == 563_000  # brand (LG) beats category beats default
    washer = _json(shop["admin"].get(f"{API}/quote/{shop['washer']}"))["quote"]
    assert washer["suggested_price"] == 334_000  # only the default 10% applies
    dup = shop["admin"].post(f"{API}/rules", json={"scope": "brand", "scope_value": "lg", "target_margin_pct": 30})
    assert dup.status_code == 409
    assert shop["admin"].post(f"{API}/rules", json={"scope": "default", "target_margin_pct": 95}).status_code == 400


def test_rules_propose_preview_only_then_approval_applies_once_with_history(shop):
    from models.inventory_lot import InventoryLot

    _json(shop["admin"].post(f"{API}/rules", json={"scope": "brand", "scope_value": "LG", "target_margin_pct": 20,
                                                    "minimum_margin_pct": 5}))
    ctx = _db(shop)
    try:
        lots_before = [(lot.id, lot.unit_cost, lot.remaining_quantity) for lot in InventoryLot.query.all()]
    finally:
        ctx.pop()
    batch = _json(shop["admin"].post(f"{API}/batches/from-rules", json={}))["batch"]
    row = next(r for r in batch["rows"] if r["product_id"] == shop["tv"])
    assert (row["old_price"], row["new_price"], row["verdict"]) == (500_000, 563_000, "up")
    assert _price(shop, shop["tv"])[0] == 500_000  # a proposal changes nothing
    result = _json(shop["admin"].post(f"{API}/batches/{batch['id']}/approve"))["result"]
    assert result["applied"] == 1
    price, cost, _ = _price(shop, shop["tv"])
    assert price == 563_000 and cost == 450_000  # the selling price moved; the purchase cost did not
    ctx = _db(shop)
    try:
        assert [(lot.id, lot.unit_cost, lot.remaining_quantity) for lot in InventoryLot.query.all()] == lots_before
    finally:
        ctx.pop()
    history = _json(shop["admin"].get(f"{API}/history?product_id={shop['tv']}"))["rows"]
    assert history[0]["old_price"] == 500_000 and history[0]["new_price"] == 563_000 and history[0]["approved_by_id"]
    assert shop["admin"].post(f"{API}/batches/{batch['id']}/approve").status_code == 409


def test_a_price_changed_after_the_preview_is_never_overwritten(shop):
    _json(shop["admin"].post(f"{API}/rules", json={"scope": "default", "target_margin_pct": 20}))
    batch = _json(shop["admin"].post(f"{API}/batches/from-rules", json={}))["batch"]
    from extensions import db
    from models.product import Product

    ctx = _db(shop)
    try:
        Product.query.execution_options(skip_branch_scope=True).get(shop["tv"]).sale_price = 777_000
        db.session.commit()
    finally:
        ctx.pop()
    result = _json(shop["admin"].post(f"{API}/batches/{batch['id']}/approve"))["result"]
    assert result["stale"] >= 1 and _price(shop, shop["tv"])[0] == 777_000


def _file(shop, body: str, name="prices.csv", supplier="مورد بغداد"):
    return shop["admin"].post(f"{API}/batches/from-file", data={"file": (io.BytesIO(body.encode()), name), "supplier": supplier},
                              content_type="multipart/form-data")


def test_price_file_preview_flags_unmatched_invalid_and_below_minimum_and_saves_offers_only_on_approval(shop):
    from modules.pricing.models import SupplierOffer

    _json(shop["admin"].post(f"{API}/rules", json={"scope": "default", "target_margin_pct": 20, "minimum_margin_pct": 10}))
    body = ("الباركود,سعر الشراء,سعر البيع\n"
            "8806091111111,460000,\n"        # cost → suggested by the rule
            "WW90,,320000\n"                 # explicit price below the safe minimum (300000 / 0.9 ≈ 333334)
            "0000000000001,100000,\n"        # no such product
            "8806092222222,abc,\n")          # unreadable value
    batch = _json(_file(shop, body))["batch"]
    by_ref = {r["ref"]: r for r in batch["rows"]}
    assert by_ref["8806091111111"]["new_price"] == 575_000 and by_ref["8806091111111"]["verdict"] == "up"
    assert by_ref["WW90"]["verdict"] == "below_minimum"
    assert by_ref["0000000000001"]["verdict"] == "unmatched"
    assert by_ref["8806092222222"]["verdict"] == "invalid"
    ctx = _db(shop)
    try:
        assert SupplierOffer.query.count() == 0  # nothing stored before approval
    finally:
        ctx.pop()
    result = _json(shop["admin"].post(f"{API}/batches/{batch['id']}/approve"))["result"]
    assert result["applied"] == 1 and _price(shop, shop["washer"])[0] == 420_000  # below-minimum row not applied
    ctx = _db(shop)
    try:
        offer = SupplierOffer.query.one()
        assert offer.purchase_price == 460_000 and offer.supplier_ref == "مورد بغداد"
    finally:
        ctx.pop()
    quote = _json(shop["admin"].get(f"{API}/quote/{shop['tv']}"))["quote"]
    assert quote["cost_basis"] == 460_000 and "مورد بغداد" in quote["cost_source"]  # replacement cost now known
    assert _price(shop, shop["tv"])[1] == 450_000  # …while the recorded purchase price is untouched


def test_permissions_split_proposing_from_approving(shop):
    from flask import g

    from extensions import db
    from models.employee import Employee
    from models.employee_permission import EmployeePermissionOverride
    from utils import permission_overrides

    clerk = _client(shop, "clerk")
    assert clerk.get(f"{API}/rules").status_code == 403
    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        permission_overrides.ensure_table()
        for name in ("pricing.view", "pricing.manage"):
            db.session.add(EmployeePermissionOverride(employee_id=shop["clerk_id"], permission=name, effect="grant"))
        db.session.commit()
    assert clerk.post(f"{API}/rules", json={"scope": "default", "target_margin_pct": 20}).status_code == 200
    batch = _json(clerk.post(f"{API}/batches/from-rules", json={}))["batch"]
    assert clerk.post(f"{API}/batches/{batch['id']}/approve").status_code == 403  # proposing ≠ approving
    assert clerk.post(f"{API}/promotions", json={}).status_code == 403
    assert Employee  # noqa: B018


def test_promotion_is_a_real_dated_discount_that_restores_or_flags_a_conflict(shop):
    now = datetime.utcnow()
    bad = shop["admin"].post(f"{API}/promotions", json={"product_id": shop["tv"], "promo_price": 600_000,
                                                         "starts_at": now.isoformat(), "ends_at": (now + timedelta(days=1)).isoformat()})
    assert bad.status_code == 400  # not lower than the current price → not a discount
    promo = _json(shop["admin"].post(f"{API}/promotions", json={
        "product_id": shop["tv"], "promo_price": 470_000, "starts_at": (now - timedelta(minutes=1)).isoformat(),
        "ends_at": (now + timedelta(days=2)).isoformat()}))
    assert promo["status"] == "running"
    price, _, meta = _price(shop, shop["tv"])
    assert price == 470_000 and meta["old_price"] == 500_000  # checkout, POS and shop all see the same price
    overlap = shop["admin"].post(f"{API}/promotions", json={
        "product_id": shop["tv"], "promo_price": 460_000, "starts_at": now.isoformat(),
        "ends_at": (now + timedelta(days=1)).isoformat()})
    assert overlap.status_code == 409
    from modules.pricing import service

    ctx = _db(shop)
    try:
        service.run_due(now + timedelta(days=3))
        from extensions import db

        db.session.commit()
    finally:
        ctx.pop()
    price, _, meta = _price(shop, shop["tv"])
    assert price == 500_000 and "old_price" not in meta  # back to the regular price, no stale "discount"

    second = _json(shop["admin"].post(f"{API}/promotions", json={
        "product_id": shop["washer"], "promo_price": 400_000, "starts_at": (now - timedelta(minutes=1)).isoformat(),
        "ends_at": (now + timedelta(days=1)).isoformat()}))
    ctx = _db(shop)
    try:
        from extensions import db
        from models.product import Product

        Product.query.execution_options(skip_branch_scope=True).get(shop["washer"]).sale_price = 390_000  # manual change
        db.session.commit()
        service.run_due(now + timedelta(days=2))
        db.session.commit()
        from modules.pricing.models import Promotion

        assert db.session.get(Promotion, second["id"]).status == "conflict"
    finally:
        ctx.pop()
    assert _price(shop, shop["washer"])[0] == 390_000  # the manual price is not overwritten


def test_closed_invoices_keep_their_prices(shop):
    from flask import g

    from extensions import db
    from models.customer import Customer
    from models.invoice import Invoice

    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        customer = Customer.query.execution_options(skip_branch_scope=True).first()
        inv = Invoice(customer_id=customer.id, customer_name=customer.name, employee_id=shop["admin_id"],
                      employee_name="admin", total=500_000, paid_amount=500_000, status="تم التوصيل",
                      payment_status="مسدد", sale_type="cash", stock_is_deducted=False)
        db.session.add(inv)
        db.session.commit()
        invoice_id = inv.id
    _json(shop["admin"].post(f"{API}/rules", json={"scope": "default", "target_margin_pct": 30}))
    batch = _json(shop["admin"].post(f"{API}/batches/from-rules", json={}))["batch"]
    _json(shop["admin"].post(f"{API}/batches/{batch['id']}/approve"))
    with shop["app"].test_request_context():
        g.tenant = shop["tenant"]
        assert db.session.get(Invoice, invoice_id).total == 500_000


def test_automatic_rules_apply_small_changes_and_leave_big_ones_for_approval(shop):
    _json(shop["admin"].post(f"{API}/rules", json={"scope": "brand", "scope_value": "LG", "target_margin_pct": 12,
                                                    "automatic": True, "approval_required": False,
                                                    "max_auto_change_pct": 5, "rounding_step": 1000}))
    _json(shop["admin"].post(f"{API}/rules", json={"scope": "brand", "scope_value": "Samsung", "target_margin_pct": 40,
                                                    "automatic": True, "approval_required": False,
                                                    "max_auto_change_pct": 5}))
    result = _json(shop["admin"].post(f"{API}/automatic/run"))["result"]
    assert result == {"applied": 1, "needs_approval": 1}
    assert _price(shop, shop["tv"])[0] == 512_000  # 450000 / 0.88 = 511364 → 512000 (+2.4%)
    assert _price(shop, shop["washer"])[0] == 420_000  # +19% exceeds the automatic limit
