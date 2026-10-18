"""Shipping & Logistics Center desktop API (/api/v1/desktop/shipping-center/*).

The settlement manifest is FINORA's own ShippingReport executed by execute_shipping_report: this suite checks the
analyzer rules (other carrier, already paid, duplicates, «مشكلة» rows), that approval is admin-only and refuses any
received amount that differs from the expected net (collections − per-order courier fee), and that approval moves
exactly that net into the treasury, registers returns awaiting receipt, resets postponed orders and locks the manifest."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PREFIX = f"test_shipping_center_{os.getpid()}"
API = "/api/v1/desktop/shipping-center"
_COUNTER = [0]
_CREATED: list[str] = []


def _wipe(slugs) -> None:
    try:
        from extensions import db
        from extensions_tenant import clear_tenant_engine

        db.session.remove()
        for slug in slugs:
            clear_tenant_engine(slug)
    except Exception:
        pass
    for slug in slugs:
        for suffix in ("", "-wal", "-shm"):
            try:
                (ROOT / "tenants" / f"{slug}.db{suffix}").unlink(missing_ok=True)
            except PermissionError:
                pass


def _seed(tenant: str) -> dict:
    from flask import g
    from werkzeug.security import generate_password_hash

    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.account_transaction import AccountTransaction
    from models.customer import Customer
    from models.employee import Employee
    from models.invoice import Invoice
    from models.role import Permission, Role
    from models.shipping import ShippingCompany
    from utils.branch_migration import get_default_branch
    from utils.order_shipping import add_shipping_line_item
    from utils.treasury_helpers import get_default_cash_account

    g.tenant = tenant
    init_tenant_db(tenant)
    branch = get_default_branch()
    pw = generate_password_hash("x-pass-123")
    admin = Employee(name="Admin", username="sc_admin", password=pw, role="admin", is_active=True, branch_id=branch.id)
    clerk = Employee(name="Clerk", username="sc_clerk", password=pw, role="sales", is_active=True, branch_id=branch.id)
    viewer = Employee(name="Viewer", username="sc_viewer", password=pw, role="sales", is_active=True, branch_id=branch.id)
    db.session.add_all([admin, clerk, viewer])
    db.session.flush()
    role = Role(name="shipping-clerk")
    for name in ("view_shipping", "manage_shipping"):
        role.permissions.append(Permission.query.filter_by(name=name).first() or Permission(name=name, description=name))
    clerk.roles.append(role)
    barq = ShippingCompany(name="شركة البرق", phone="0770", price=5000, branch_id=branch.id)
    najm = ShippingCompany(name="شركة النجم", phone="0780", price=4000, branch_id=branch.id)
    customer = Customer(name="أحمد علي", phone="07701112233", city="بغداد", branch_id=branch.id)
    db.session.add_all([barq, najm, customer])
    db.session.flush()

    def order(total, status, payment, carrier, *, paid=0, waybill=None, fee=5000):
        inv = Invoice(customer_id=customer.id, customer_name=customer.name, branch_id=branch.id, employee_id=admin.id,
                      employee_name=admin.name, total=total, paid_amount=paid, status=status, payment_status=payment,
                      shipping_status=status, shipping_company_id=carrier.id, shipping_barcode=waybill,
                      stock_is_deducted=False, sale_type="credit", created_at=datetime.now() - timedelta(days=2))
        db.session.add(inv)
        db.session.flush()
        if fee:
            add_shipping_line_item(inv, fee)  # FINORA's own way of recording the courier fee on an order
        return inv.id

    ids = {
        "a": order(225000, "جاري الشحن", "غير مسدد", barq, waybill="BRQ-1001"),
        "b": order(350000, "جاري الشحن", "غير مسدد", barq, waybill="BRQ-1002"),
        "c": order(180000, "جاري الشحن", "غير مسدد", barq),
        "d": order(420000, "جاري الشحن", "غير مسدد", barq),
        "paid": order(100000, "تم التوصيل", "مسدد", barq, paid=100000),
        "other": order(90000, "جاري الشحن", "غير مسدد", najm, fee=4000),
    }
    db.session.commit()
    cash = get_default_cash_account(branch.id)
    db.session.add(AccountTransaction(branch_id=branch.id, type="deposit", amount=1_000_000, note="رأس مال",
                                      treasury_account_id=cash.id, created_at=datetime.now() - timedelta(days=3)))
    db.session.commit()
    return {"admin_id": admin.id, "clerk_id": clerk.id, "viewer_id": viewer.id, "barq": barq.id, "najm": najm.id,
            "cash_id": cash.id, "orders": ids}


@pytest.fixture(scope="module")
def app():
    previous = os.environ.get("FINORA_LOCAL_WORKSPACE")
    os.environ["FINORA_LOCAL_WORKSPACE"] = "1"
    from app import app as flask_app

    flask_app.config["TESTING"] = True
    yield flask_app
    if previous is None:
        os.environ.pop("FINORA_LOCAL_WORKSPACE", None)
    else:
        os.environ["FINORA_LOCAL_WORKSPACE"] = previous
    _wipe(_CREATED)


@pytest.fixture()
def ctx(app):
    from extensions import db

    _COUNTER[0] += 1
    tenant = f"{PREFIX}_{_COUNTER[0]}"
    _CREATED.append(tenant)
    with app.app_context():
        ids = _seed(tenant)
        db.session.remove()
    return {"app": app, "tenant": tenant, **ids}


def _client(ctx, who="admin"):
    client = ctx["app"].test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = ctx[f"{who}_id"]
        sess["tenant_slug"] = ctx["tenant"]
        sess["role"] = "admin" if who == "admin" else "sales"
        sess["name"] = who
    return client


def _json(res, status=200):
    assert res.status_code == status, (res.status_code, res.get_data(as_text=True)[:600])
    return res.get_json()


def _order(ctx, key):
    from flask import g

    from models.invoice import Invoice

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        inv = Invoice.query.get(ctx["orders"][key])
        return {"status": inv.status, "payment_status": inv.payment_status, "paid": int(inv.paid_amount or 0)}


def _balance(ctx) -> int:
    from flask import g

    from utils.treasury_calculations import calculate_treasury_balance

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        return calculate_treasury_balance(ctx["cash_id"])


def _manifest(client, ctx, codes):
    body = _json(client.post(f"{API}/manifests", json={"carrier_id": ctx["barq"], "reference": "BRQ-STMT-77"}))
    mid = body["manifest"]["id"]
    added = _json(client.post(f"{API}/manifests/{mid}/rows", json={"codes": codes}))
    return mid, added


def test_overview_carriers_and_lookup_by_number_or_waybill(ctx):
    client = _client(ctx)
    cards = _json(client.get(f"{API}/overview"))["cards"]
    assert cards["in_transit"]["count"] == 5 and cards["carriers_due"]["amount"] == 225000 + 350000 + 180000 + 420000 + 90000
    carriers = {c["name"]: c for c in _json(client.get(f"{API}/carriers"))["rows"]}
    assert carriers["شركة البرق"]["stats"]["transit"]["count"] == 4
    found = _json(client.post(f"{API}/lookup", json={"codes": [str(ctx["orders"]["a"]), "BRQ-1002", "XYZ-404"]}))
    assert [r["id"] for r in found["found"]] == [ctx["orders"]["a"], ctx["orders"]["b"]]
    assert found["found"][1]["waybills"] == ["BRQ-1002"] and found["found"][0]["fee"] == 5000
    assert found["missing"] == ["XYZ-404"]


def test_settlement_manifest_full_cycle_posts_exactly_the_net(ctx):
    admin = _client(ctx)
    o = ctx["orders"]
    mid, added = _manifest(admin, ctx, [str(o["a"]), "BRQ-1002", str(o["c"]), str(o["d"]), str(o["a"]), "nope"])
    assert added["added"] == [o["a"], o["b"], o["c"], o["d"]]
    assert added["duplicates"] == [str(o["a"])] and added["missing"] == ["nope"]
    selections = {str(o["a"]): "واصل", str(o["b"]): "واصل", str(o["c"]): "راجع", str(o["d"]): "مؤجل"}
    manifest = _json(admin.post(f"{API}/manifests/{mid}/selections", json={"selections": selections}))["manifest"]
    totals = manifest["totals"]
    assert totals["delivered"] == {"count": 2, "amount": 575000, "fee": 10000}
    assert totals["returned"]["count"] == 1 and totals["postponed"]["count"] == 1
    assert manifest["expected_net"] == 565000 and manifest["ready"] is True
    before = _balance(ctx)

    # wrong amount → refused, nothing posted
    res = admin.post(f"{API}/manifests/{mid}/approve", json={"received_amount": 560000})
    assert res.status_code == 409 and "لا يطابق" in res.get_json()["error"]
    assert _order(ctx, "a")["payment_status"] == "غير مسدد" and _balance(ctx) == before

    result = _json(admin.post(f"{API}/manifests/{mid}/approve",
                              json={"received_amount": 565000, "treasury_account_id": ctx["cash_id"]}))
    assert result["manifest"]["executed"] is True
    assert _order(ctx, "a") == {"status": "تم التوصيل", "payment_status": "مسدد", "paid": 225000}
    assert _order(ctx, "b")["payment_status"] == "مسدد"
    # returned: registered as a return awaiting receipt — stock / sale reversal only after inspection (phase 2)
    assert _order(ctx, "c")["status"] == "جاري الشحن"
    returns = _json(admin.get(f"{API}/returns"))["rows"]
    assert [(r["order_id"], r["state"]) for r in returns] == [(o["c"], "awaiting")]
    assert _order(ctx, "d") == {"status": "تم الطلب", "payment_status": "غير مسدد", "paid": 0}
    assert _balance(ctx) - before == 565000  # collections − courier fees, exactly what was received

    # approved manifests are locked (corrections go through a new manifest)
    assert admin.post(f"{API}/manifests/{mid}/rows", json={"codes": [str(o["d"])]}).status_code == 409
    assert admin.post(f"{API}/manifests/{mid}/approve", json={"received_amount": 565000}).status_code == 409


def test_analyzer_blocks_other_carrier_already_paid_and_problem_rows(ctx):
    admin = _client(ctx)
    o = ctx["orders"]
    mid, _ = _manifest(admin, ctx, [str(o["other"]), str(o["paid"]), str(o["a"])])
    manifest = _json(admin.post(f"{API}/manifests/{mid}/selections", json={"selections": {
        str(o["other"]): "واصل", str(o["paid"]): "واصل", str(o["a"]): "مشكلة"}}))["manifest"]
    codes = {i["code"] for i in manifest["blocking"]}
    assert {"other_carrier", "already_paid", "problem_rows"} <= codes and manifest["ready"] is False
    res = admin.post(f"{API}/manifests/{mid}/approve", json={"received_amount": manifest["expected_net"]})
    assert res.status_code == 409
    assert _order(ctx, "other")["payment_status"] == "غير مسدد"
    assert admin.post(f"{API}/manifests/{mid}/selections", json={"selections": {str(o["a"]): "مسدد؟"}}).status_code == 400


def test_only_admins_approve_and_permissions_are_json(ctx):
    clerk = _client(ctx, "clerk")
    o = ctx["orders"]
    mid, _ = _manifest(clerk, ctx, [str(o["a"])])
    _json(clerk.post(f"{API}/manifests/{mid}/selections", json={"selections": {str(o["a"]): "واصل"}}))
    res = clerk.post(f"{API}/manifests/{mid}/approve", json={"received_amount": 220000})
    assert res.status_code == 403 and res.is_json
    viewer = _client(ctx, "viewer")
    for method, path in (("get", f"{API}/overview"), ("get", f"{API}/carriers"), ("post", f"{API}/manifests")):
        res = getattr(viewer, method)(path, json={} if method == "post" else None)
        assert res.status_code == 403 and res.is_json, path


def test_removing_a_row_drops_its_selection(ctx):
    admin = _client(ctx)
    o = ctx["orders"]
    mid, _ = _manifest(admin, ctx, [str(o["a"]), str(o["b"])])
    _json(admin.post(f"{API}/manifests/{mid}/selections", json={"selections": {str(o["a"]): "واصل"}}))
    manifest = _json(admin.post(f"{API}/manifests/{mid}/rows/{o['a']}/remove"))["manifest"]
    assert [r["id"] for r in manifest["rows"]] == [o["b"]] and manifest["selections"] == {}


def test_handover_manifest_dispatches_orders_to_the_carrier(ctx):
    from flask import g

    from models.invoice import Invoice
    from models.order_item import OrderItem
    from models.shipping_report import ShippingReport

    admin = _client(ctx)
    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        from extensions import db

        inv = Invoice.query.get(ctx["orders"]["other"])
        new = Invoice(customer_id=inv.customer_id, customer_name=inv.customer_name, branch_id=inv.branch_id,
                      employee_id=inv.employee_id, employee_name=inv.employee_name, total=50000, paid_amount=0,
                      status="معباة", payment_status="غير مسدد", stock_is_deducted=False, sale_type="credit")
        db.session.add(new)
        db.session.commit()
        new_id = new.id
        assert OrderItem.query.filter_by(invoice_id=new_id).count() == 0
    body = _json(admin.post(f"{API}/handover", json={"carrier_id": ctx["barq"], "order_ids": [new_id]}))
    assert body["report_number"].startswith("KSH-")
    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        assert Invoice.query.get(new_id).shipping_company_id == ctx["barq"]
        assert ShippingReport.query.filter_by(report_number=body["report_number"]).count() == 1
    kinds = {m["kind"] for m in _json(admin.get(f"{API}/manifests"))["rows"]}
    assert "handover" in kinds
