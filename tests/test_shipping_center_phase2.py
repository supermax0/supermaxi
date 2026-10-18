"""Shipping & Logistics Center — phase 2: partial settlements with allocation, receipt vouchers, account
statement, return fee, returns receipt + inspection (stock back / damaged write-off) and agent portal settlements.

Reuses the phase 1 tenant seed (tests/test_shipping_center_api.py)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from tests.test_shipping_center_api import API, _balance, _client, _json, _order, _seed, app  # noqa: F401
from tests import test_shipping_center_api as base


@pytest.fixture()
def ctx(app):  # noqa: F811
    from flask import g

    from extensions import db

    base._COUNTER[0] += 1
    tenant = f"{base.PREFIX}_p2_{base._COUNTER[0]}"
    base._CREATED.append(tenant)
    with app.app_context():
        ids = _seed(tenant)
        g.tenant = tenant
        ids.update(_seed_phase2(ids))
        db.session.remove()
    return {"app": app, "tenant": tenant, **ids}


def _seed_phase2(ids: dict) -> dict:
    """A stock-tracked order (product line with FIFO lots) and a delivery agent with a portal report."""
    from extensions import db
    from models.branch import BranchStock
    from models.delivery_agent import DeliveryAgent
    from models.inventory_lot import InventoryLot
    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.product import Product
    from models.shipping_report import ShippingReport
    from utils.branch_migration import get_default_branch

    branch = get_default_branch()
    first = Invoice.query.get(ids["orders"]["a"])
    product = Product(name="سماعة لاسلكية", sku="SC-P2", branch_id=branch.id, quantity=6, buy_price=20000,
                      sale_price=60000, active=True, low_stock_threshold=1, catalog_group_id=uuid4().hex)
    db.session.add(product)
    db.session.flush()
    db.session.add(BranchStock(branch_id=branch.id, product_id=product.id, quantity=6, opening_stock=6))
    db.session.add(InventoryLot(product_id=product.id, branch_id=branch.id, quantity=6, remaining_quantity=6,
                                unit_cost=20000, created_at=datetime.utcnow() - timedelta(days=5)))

    def order(total, *, carrier=None, agent=None):
        inv = Invoice(customer_id=first.customer_id, customer_name=first.customer_name, branch_id=branch.id,
                      employee_id=first.employee_id, employee_name=first.employee_name, total=total, paid_amount=0,
                      status="جاري الشحن", payment_status="غير مسدد", shipping_status="جاري الشحن",
                      shipping_company_id=carrier, delivery_agent_id=agent, stock_is_deducted=False,
                      sale_type="credit", created_at=datetime.now() - timedelta(days=1))
        db.session.add(inv)
        db.session.flush()
        return inv

    goods = order(120000, carrier=ids["barq"])
    db.session.add(OrderItem(invoice_id=goods.id, product_id=product.id, product_name=product.name, price=60000,
                             quantity=2, cost=20000, total=120000, fulfillment_branch_id=branch.id))
    agent = DeliveryAgent(name="مندوب حسين", phone="0771", is_active=True, username="sc_agent", branch_id=branch.id)
    db.session.add(agent)
    db.session.flush()
    f1, f2, f3 = order(80000, agent=agent.id), order(60000, agent=agent.id), order(45000, agent=agent.id)
    rows = [{"id": o.id, "customer_name": o.customer_name, "total": o.total, "remaining": o.total} for o in (f1, f2, f3)]
    db.session.add(ShippingReport(report_number=f"AGT-{agent.id}-20261014-0001", shipping_company_name=agent.name,
                                  orders_data=json.dumps(rows), orders_count=3, total_amount=185000,
                                  order_status_selections=json.dumps({str(f1.id): "واصل", str(f2.id): "واصل",
                                                                      str(f3.id): "ملغي"}),
                                  created_by="بوابة المندوب"))
    db.session.commit()
    return {"product": product.id, "branch": branch.id, "agent": agent.id,
            "goods": goods.id, "f1": f1.id, "f2": f2.id, "f3": f3.id}


def _settlement(client, ctx, codes, selections, **body):
    created = _json(client.post(f"{API}/manifests", json={"carrier_id": ctx["barq"], "reference": "R-1", **body}))
    mid = created["manifest"]["id"]
    _json(client.post(f"{API}/manifests/{mid}/rows", json={"codes": [str(c) for c in codes]}))
    manifest = _json(client.post(f"{API}/manifests/{mid}/selections",
                                 json={"selections": {str(k): v for k, v in selections.items()}}))["manifest"]
    return mid, manifest


def _stock(ctx) -> int:
    from flask import g

    from models.branch import BranchStock

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        return int(BranchStock.query.filter_by(branch_id=ctx["branch"], product_id=ctx["product"]).one().quantity)


def test_partial_settlement_allocates_per_order_and_keeps_the_rest_owed(ctx):
    admin = _client(ctx)
    o = ctx["orders"]
    _json(admin.post(f"{API}/carriers/{ctx['barq']}/settings", json={"return_fee": 3000, "price": 5000}))
    mid, manifest = _settlement(admin, ctx, [o["a"], o["b"], o["c"]], {o["a"]: "واصل", o["b"]: "واصل", o["c"]: "راجع"})
    assert manifest["totals"]["returned"]["fee"] == 3000
    assert manifest["expected_net"] == 575000 - 10000 - 3000
    before = _balance(ctx)

    allocations = {str(o["a"]): 225000, str(o["b"]): 100000}
    res = admin.post(f"{API}/manifests/{mid}/approve", json={"received_amount": 320000, "allocations": allocations})
    assert res.status_code == 409 and "312,000" in res.get_json()["error"]
    res = admin.post(f"{API}/manifests/{mid}/approve",
                     json={"received_amount": 1, "allocations": {str(o["a"]): 999999}})
    assert res.status_code == 400
    assert _balance(ctx) == before

    approved = _json(admin.post(f"{API}/manifests/{mid}/approve", json={
        "received_amount": 312000, "allocations": allocations, "treasury_account_id": ctx["cash_id"]}))["manifest"]
    assert approved["settlement_state"] == "partial"
    assert approved["meta"]["ledger"]["outstanding"] == 250000
    assert _order(ctx, "a")["payment_status"] == "مسدد"
    assert _order(ctx, "b") == {"status": "جاري الشحن", "payment_status": "جزئي", "paid": 100000}
    assert _balance(ctx) - before == 312000  # 325,000 collected − 10,000 courier fees − 3,000 return fee

    receipts = _json(admin.get(f"{API}/receipts?party_type=carrier&party_id={ctx['barq']}"))["rows"]
    assert len(receipts) == 1 and receipts[0]["amount"] == 312000
    assert {a["order_id"]: a["amount"] for a in receipts[0]["allocations"]} == {o["a"]: 225000, o["b"]: 100000}
    printed = admin.get(f"{API}/receipts/{receipts[0]['id']}/print")
    assert printed.status_code == 200 and "سند قبض" in printed.get_data(as_text=True)

    statement = _json(admin.get(f"{API}/carriers/{ctx['barq']}/statement"))
    assert (statement["debit"], statement["credit"], statement["balance"]) == (575000, 325000, 250000)

    # The rest of order b arrives later: debited once, fee not deducted a second time.
    mid2, manifest2 = _settlement(admin, ctx, [o["b"]], {o["b"]: "واصل"})
    assert manifest2["expected_net"] == 250000 and manifest2["rows"][0]["fee_due"] == 0
    _json(admin.post(f"{API}/manifests/{mid2}/approve", json={"received_amount": 250000}))
    assert _order(ctx, "b") == {"status": "تم التوصيل", "payment_status": "مسدد", "paid": 350000}
    assert _json(admin.get(f"{API}/carriers/{ctx['barq']}/statement"))["balance"] == 0
    assert _json(admin.get(f"{API}/carriers/{ctx['barq']}"))["balance"] == 0


def test_returns_wait_for_receipt_then_inspection_restocks_and_writes_off_damage(ctx):
    admin = _client(ctx)
    goods = ctx["goods"]
    mid, _ = _settlement(admin, ctx, [goods], {goods: "راجع"})
    _json(admin.post(f"{API}/manifests/{mid}/approve", json={"received_amount": 0}))
    assert _stock(ctx) == 6
    rows = _json(admin.get(f"{API}/returns"))["rows"]
    ret = rows[0]
    assert ret["order_id"] == goods and ret["state"] == "awaiting"

    # cannot inspect before receiving; a second manifest cannot register the same return again
    res = admin.post(f"{API}/returns/{ret['id']}/close", json={"branch_id": ctx["branch"], "lines": []})
    assert res.status_code == 409
    _, again = _settlement(admin, ctx, [goods], {goods: "راجع"})
    assert "return_pending" in {i["code"] for i in again["blocking"]}

    received = _json(admin.post(f"{API}/returns/receive", json={"code": str(goods)}))["item"]
    assert received["state"] == "received" and received["items"][0]["quantity"] == 2

    clerk = _client(ctx, "clerk")
    line = {"item_id": received["items"][0]["item_id"], "damaged": 1}
    res = clerk.post(f"{API}/returns/{ret['id']}/close", json={"branch_id": ctx["branch"], "lines": [line]})
    assert res.status_code == 403  # damaged goods need the write-off permissions
    assert admin.post(f"{API}/returns/{ret['id']}/close",
                      json={"branch_id": ctx["branch"], "lines": [{**line, "damaged": 5}]}).status_code == 400

    closed = _json(admin.post(f"{API}/returns/{ret['id']}/close", json={
        "branch_id": ctx["branch"], "packaging_ok": False, "note": "العلبة ممزقة", "lines": [line]}))["item"]
    assert closed["state"] == "closed" and len(closed["writeoffs"]) == 1
    assert closed["inspection"][0]["sellable"] == 1 and closed["inspection"][0]["damaged"] == 1
    from flask import g

    from models.invoice import Invoice

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        assert Invoice.query.get(goods).status == "راجع"  # FINORA's own return path
    assert _stock(ctx) == 5  # never deducted in this seed: −1 damaged written off
    assert admin.post(f"{API}/returns/{ret['id']}/close", json={"branch_id": ctx["branch"]}).status_code == 409


def test_agent_settlement_from_portal_claims_compares_and_detaches(ctx):
    admin = _client(ctx)
    agent = ctx["agent"]
    portal = _json(admin.get(f"{API}/agents/{agent}/portal"))
    assert portal["count"] == 3 and portal["counts"] == {"واصل": 2, "راجع": 1}
    details = _json(admin.get(f"{API}/agents/{agent}"))
    assert details["custody"]["claimed_amount"] == 140000 and details["custody"]["in_custody"] == 140000

    manifest = _json(admin.post(f"{API}/manifests", json={"agent_id": agent, "from_portal": True}))["manifest"]
    assert manifest["agent_id"] == agent and len(manifest["rows"]) == 3
    assert manifest["selections"] == {str(ctx["f1"]): "واصل", str(ctx["f2"]): "واصل", str(ctx["f3"]): "راجع"}
    assert not [i for i in manifest["issues"] if i["code"] == "open_elsewhere"]
    mid = manifest["id"]
    changed = _json(admin.post(f"{API}/manifests/{mid}/selections",
                               json={"selections": {str(ctx["f2"]): "مؤجل"}}))["manifest"]
    assert any(i["code"] == "agent_claim" and i["order_id"] == ctx["f2"] for i in changed["issues"])
    assert changed["expected_net"] == 80000

    _json(admin.post(f"{API}/manifests/{mid}/approve", json={"received_amount": 80000}))
    from flask import g

    from models.invoice import Invoice
    from models.shipping_report import ShippingReport

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        assert Invoice.query.get(ctx["f1"]).payment_status == "مسدد"
        portal_report = ShippingReport.query.filter(ShippingReport.report_number.like(f"AGT-{agent}-%")).one()
        assert json.loads(portal_report.orders_data) == []  # delivered, returned and postponed leave custody
        postponed = Invoice.query.get(ctx["f2"])
        assert (postponed.status, postponed.shipping_status, postponed.payment_status) == (
            "تم الطلب", "تم الطلب", "غير مسدد")
    receipts = _json(admin.get(f"{API}/receipts?party_type=agent&party_id={agent}"))["rows"]
    assert receipts[0]["amount"] == 80000 and receipts[0]["party_type"] == "agent"
    custody = _json(admin.get(f"{API}/agents/{agent}"))["custody"]
    assert custody["claimed_amount"] == 0 and custody["received_total"] == 80000


def test_postponed_only_manifest_restores_dispatched_stock_once_without_collection(ctx):
    from flask import g

    from extensions import db
    from models.invoice import Invoice
    from models.receipt import Receipt
    from utils.order_stock_policy import prepare_order_for_dispatch

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        order = Invoice.query.get(ctx["goods"])
        prepare_order_for_dispatch(order)
        db.session.commit()
    assert _stock(ctx) == 4

    admin = _client(ctx)
    mid, draft = _settlement(admin, ctx, [ctx["goods"]], {ctx["goods"]: "مؤجل"})
    assert draft["expected_net"] == 0
    assert draft["rows"][0]["status"] == "جاري الشحن"  # draft is classification only
    before = _balance(ctx)

    result = _json(admin.post(f"{API}/manifests/{mid}/approve", json={"received_amount": 0}))
    approved = result["manifest"]
    assert approved["executed"] is True
    assert result["result"]["delayed_count"] == 1
    assert approved["rows"][0]["status"] == "تم الطلب"
    assert approved["selections"] == {str(ctx["goods"]): "مؤجل"}
    assert approved["meta"]["ledger"]["allocations"] == {}
    assert _stock(ctx) == 6
    assert _balance(ctx) == before
    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        order = Invoice.query.get(ctx["goods"])
        assert (order.status, order.shipping_status, order.payment_status, order.paid_amount) == (
            "تم الطلب", "تم الطلب", "غير مسدد", 0)
        assert order.stock_is_deducted is False
        assert Receipt.query.count() == 0

    # A retry must not restore a second time, including through a fresh report.
    assert admin.post(f"{API}/manifests/{mid}/approve", json={"received_amount": 0}).status_code == 409
    retry, _ = _settlement(admin, ctx, [ctx["goods"]], {ctx["goods"]: "مؤجل"})
    _json(admin.post(f"{API}/manifests/{retry}/approve", json={"received_amount": 0}))
    assert _stock(ctx) == 6
    assert _balance(ctx) == before


def test_postponement_failure_rolls_back_delivered_money_and_can_retry(ctx, monkeypatch):
    from flask import g

    from extensions import db
    from models.invoice import Invoice
    from models.receipt import Receipt
    from models.shipping_report import ShippingReport
    from utils.order_stock_policy import prepare_order_for_dispatch
    from utils import shipping_report_execute as executor

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        prepare_order_for_dispatch(Invoice.query.get(ctx["goods"]))
        db.session.commit()
    admin = _client(ctx)
    mid, _ = _settlement(admin, ctx, [ctx["orders"]["a"], ctx["goods"]],
                         {ctx["orders"]["a"]: "واصل", ctx["goods"]: "مؤجل"})
    before = _balance(ctx)
    with monkeypatch.context() as patch:
        def fail_restore(*args, **kwargs):
            raise ValueError("restoration failed")
        patch.setattr(executor, "restore_order_stock_once", fail_restore)
        assert admin.post(f"{API}/manifests/{mid}/approve", json={"received_amount": 220000}).status_code == 409
    assert _balance(ctx) == before
    assert _stock(ctx) == 4
    assert _order(ctx, "a")["paid"] == 0
    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        assert ShippingReport.query.get(mid).is_executed is False
        assert Invoice.query.get(ctx["goods"]).status == "جاري الشحن"
        assert Receipt.query.count() == 0
    _json(admin.post(f"{API}/manifests/{mid}/approve", json={"received_amount": 220000}))
    assert _stock(ctx) == 6
    assert _balance(ctx) == before + 220000
    assert _order(ctx, "a")["paid"] == 225000


def test_settings_validation_and_permissions(ctx):
    viewer = _client(ctx, "viewer")
    assert viewer.post(f"{API}/carriers/{ctx['barq']}/settings", json={"return_fee": 1}).status_code == 403
    clerk = _client(ctx, "clerk")
    assert clerk.post(f"{API}/carriers/{ctx['barq']}/settings", json={"return_fee": -5}).status_code == 400
    saved = _json(clerk.post(f"{API}/carriers/{ctx['barq']}/settings", json={
        "return_fee": 2500, "price": 6000, "settlement_cycle": "weekly", "payment_method": "bank"}))["settings"]
    assert saved["return_fee"] == 2500 and saved["price"] == 6000 and saved["settlement_cycle"] == "weekly"


def test_missing_orders_and_overdue_follow_up(ctx):
    admin = _client(ctx)
    o = ctx["orders"]
    mid, _ = _settlement(admin, ctx, [o["a"]], {o["a"]: "واصل"})
    missing = _json(admin.get(f"{API}/manifests/{mid}/missing"))
    ids = [r["id"] for r in missing["rows"]]
    assert {o["b"], o["c"], o["d"], ctx["goods"]} <= set(ids)
    assert o["a"] not in ids and o["paid"] not in ids and o["other"] not in ids  # in it / paid / other carrier
    assert {r["id"]: r["days_out"] for r in missing["rows"]}[o["b"]] >= 1  # seeded two days ago
    assert [r["days_out"] for r in missing["rows"]] == sorted((r["days_out"] for r in missing["rows"]), reverse=True)
    assert missing["amount"] == sum(r["remaining"] for r in missing["rows"])
    # an order already sitting in another open settlement is shown with that manifest's number
    mid2, _ = _settlement(admin, ctx, [o["b"]], {})
    flagged = {r["id"]: r["in_manifest"] for r in _json(admin.get(f"{API}/manifests/{mid}/missing"))["rows"]}
    assert flagged[o["b"]].startswith("STL-")

    late = _json(admin.get(f"{API}/overdue?days=1"))
    assert {o["a"], o["d"]} <= {p["id"] for p in late["parcels"]}
    assert late["counts"]["parcels"] == len(late["parcels"])
    assert _json(admin.get(f"{API}/overdue?days=30"))["counts"]["parcels"] == 0


def test_agent_manifest_from_desktop_links_orders_and_refuses_duplicates(ctx):
    from flask import g

    from models.invoice import Invoice
    from models.shipping_report import ShippingReport

    clerk = _client(ctx, "clerk")
    o = ctx["orders"]
    body = _json(clerk.post(f"{API}/agent-report", json={"agent_id": ctx["agent"], "order_ids": [o["c"], o["d"]]}))
    assert body["report_number"].startswith(f"AGT-{ctx['agent']}-")
    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        assert {Invoice.query.get(o[k]).delivery_agent_id for k in ("c", "d")} == {ctx["agent"]}
        assert ShippingReport.query.filter_by(report_number=body["report_number"]).count() == 1
    again = clerk.post(f"{API}/agent-report", json={"agent_id": ctx["agent"], "order_ids": [o["c"], o["b"]]})
    assert again.status_code == 409 and "مكرر" in again.get_json()["error"]
    assert clerk.post(f"{API}/agent-report", json={"agent_id": 0, "order_ids": [o["b"]]}).status_code == 400
    assert _client(ctx, "viewer").post(f"{API}/agent-report", json={"agent_id": ctx["agent"], "order_ids": [o["b"]]}).status_code == 403


def test_duplicate_agent_records_show_as_one_agent(ctx):
    """FINORA can hold the same agent twice (e.g. per branch): one row, one profile, both records' orders."""
    from flask import g

    from extensions import db
    from models.delivery_agent import DeliveryAgent
    from models.invoice import Invoice

    admin = _client(ctx)
    o = ctx["orders"]
    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        first = DeliveryAgent.query.get(ctx["agent"])
        copy = DeliveryAgent(name=f" {first.name} ", phone=first.phone, is_active=True, branch_id=first.branch_id)
        db.session.add(copy)
        db.session.flush()
        Invoice.query.get(o["d"]).delivery_agent_id = copy.id
        db.session.commit()
        copy_id = copy.id
    rows = [r for r in _json(admin.get(f"{API}/agents"))["rows"] if r["name"].strip() == "مندوب حسين"]
    assert len(rows) == 1 and set(rows[0]["merged_ids"]) == {ctx["agent"], copy_id}
    assert rows[0]["id"] == ctx["agent"]  # the record with the portal login represents the agent
    assert rows[0]["stats"]["transit"]["count"] == 4  # three portal orders + the copy's order
    assert len([a for a in _json(admin.get(f"{API}/meta"))["agents"] if a["name"].strip() == "مندوب حسين"]) == 1
    orders = _json(admin.get(f"{API}/agents/{copy_id}/orders"))
    assert o["d"] in [r["id"] for r in orders["rows"]] and orders["total"] == 4
