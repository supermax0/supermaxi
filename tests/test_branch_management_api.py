"""Multi-branch management (spec sprints 1–2): feature flag, branch create / edit / archive, isolation.

The invariants under test are the spec's hard rules: turning the feature on or creating an empty branch must
not move a single dinar, unit or invoice; only a general admin manages branches (enforced by the server);
a company never sees another company's branches."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PREFIX = f"test_branch_mgmt_{os.getpid()}"
API = "/api/v1/desktop/branches"
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
    from uuid import uuid4

    from flask import g
    from werkzeug.security import generate_password_hash

    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.account_transaction import AccountTransaction
    from models.branch import BranchStock
    from models.customer import Customer
    from models.employee import Employee
    from models.inventory_lot import InventoryLot
    from models.invoice import Invoice
    from models.product import Product
    from utils.branch_migration import get_default_branch
    from utils.treasury_helpers import get_default_cash_account

    g.tenant = tenant
    init_tenant_db(tenant)
    branch = get_default_branch()
    pw = generate_password_hash("x-pass-123")
    admin = Employee(name="Admin", username="bm_admin", password=pw, role="admin", is_active=True, branch_id=branch.id)
    clerk = Employee(name="Clerk", username="bm_clerk", password=pw, role="sales", is_active=True, branch_id=branch.id)
    db.session.add_all([admin, clerk])
    db.session.flush()
    customer = Customer(name="عميل", phone="0770", city="بغداد", branch_id=branch.id)
    db.session.add(customer)
    product = Product(name="شاشة", sku=f"BM-{uuid4().hex[:6]}", branch_id=branch.id, quantity=7, buy_price=100000,
                      sale_price=150000, active=True, low_stock_threshold=1, catalog_group_id=uuid4().hex)
    db.session.add(product)
    db.session.flush()
    db.session.add(BranchStock(branch_id=branch.id, product_id=product.id, quantity=7, opening_stock=7))
    db.session.add(InventoryLot(product_id=product.id, branch_id=branch.id, quantity=7, remaining_quantity=7,
                                unit_cost=100000, created_at=datetime.utcnow() - timedelta(days=9)))
    db.session.add(Invoice(customer_id=customer.id, customer_name=customer.name, branch_id=branch.id,
                           employee_id=admin.id, employee_name=admin.name, total=450000, paid_amount=450000,
                           status="تم التوصيل", payment_status="مسدد", sale_type="cash", stock_is_deducted=False,
                           created_at=datetime.utcnow() - timedelta(days=2)))
    cash = get_default_cash_account(branch.id)
    db.session.add(AccountTransaction(branch_id=branch.id, type="deposit", amount=2_000_000, note="رأس مال",
                                      treasury_account_id=cash.id, created_at=datetime.utcnow() - timedelta(days=3)))
    db.session.commit()
    return {"admin_id": admin.id, "clerk_id": clerk.id, "main": branch.id, "cash_id": cash.id}


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


def _make_ctx(app):
    from extensions import db

    _COUNTER[0] += 1
    tenant = f"{PREFIX}_{_COUNTER[0]}"
    _CREATED.append(tenant)
    with app.app_context():
        ids = _seed(tenant)
        db.session.remove()
    return {"app": app, "tenant": tenant, **ids}


@pytest.fixture()
def ctx(app):
    return _make_ctx(app)


def _client(ctx, who="admin"):
    client = ctx["app"].test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = ctx[f"{who}_id"]
        sess["tenant_slug"] = ctx["tenant"]
        sess["role"] = "admin" if who == "admin" else "sales"
        sess["name"] = who
    return client


def _json(res, status=200):
    assert res.status_code == status, (res.status_code, res.get_data(as_text=True)[:500])
    return res.get_json()


def _totals(ctx) -> dict:
    """The books' figures that must not change by turning the feature on or creating an empty branch."""
    from flask import g
    from sqlalchemy import func

    from extensions import db
    from models.account_transaction import AccountTransaction
    from models.branch import BranchStock
    from models.inventory_lot import InventoryLot
    from models.invoice import Invoice
    from models.stock_movement import StockMovement
    from utils.treasury_calculations import calculate_treasury_balance

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        skip = {"skip_branch_scope": True}
        return {
            "sales": int(Invoice.query.execution_options(**skip).with_entities(func.coalesce(func.sum(Invoice.total), 0)).scalar()),
            "invoices": Invoice.query.execution_options(**skip).count(),
            "stock": int(db.session.query(func.coalesce(func.sum(BranchStock.quantity), 0)).scalar()),
            "stock_value": int(db.session.query(func.coalesce(func.sum(InventoryLot.remaining_quantity * InventoryLot.unit_cost), 0)).scalar()),
            "cash_main": calculate_treasury_balance(ctx["cash_id"]),
            "movements": AccountTransaction.query.execution_options(**skip).count(),
            "stock_movements": StockMovement.query.execution_options(**skip).count(),
        }


def test_single_branch_company_stays_simple_and_has_a_primary_branch(ctx):
    admin = _client(ctx)
    meta = _json(admin.get(f"{API}/meta"))
    assert meta["multi_branch"] == {"enabled": False, "explicit": False, "active_branches": 1}
    assert meta["primary_branch_id"] == ctx["main"] and meta["can_manage"] is True
    assert {t["id"] for t in meta["types"]} >= {"sales", "warehouse", "hq"}
    rows = _json(admin.get(API))["rows"]
    assert [r["id"] for r in rows] == [ctx["main"]] and rows[0]["is_default"] is True
    assert rows[0]["stats"]["sales_total"] == 450000 and rows[0]["stats"]["stock_value"] == 700000
    assert rows[0]["stats"]["cash"] == 2_000_000 + 450000
    # creating a branch is refused until the company turns multi-branch on (server-side, not just hidden UI)
    res = admin.post(API, json={"code": "KRD", "name": "فرع الكرادة"})
    assert res.status_code == 409 and "تعدد الفروع" in res.get_json()["error"]


def test_enabling_and_creating_an_empty_branch_moves_nothing(ctx):
    admin = _client(ctx)
    before = _totals(ctx)
    state = _json(admin.post(f"{API}/feature", json={"enabled": True}))["multi_branch"]
    assert state["enabled"] is True and state["explicit"] is True
    assert _totals(ctx) == before  # the flag alone creates no profit / expense / liability

    created = _json(admin.post(API, json={
        "code": "krd", "name": "فرع الكرادة", "branch_type": "showroom", "governorate": "بغداد", "city": "الكرادة",
        "manager_name": "علي", "phone": "07701234567", "opened_on": "2026-10-01"}))["branch"]
    assert created["code"] == "KRD" and created["branch_type_label"] == "معرض" and created["is_default"] is False
    assert created["stats"] == {"sales_total": 0, "orders": 0, "open_orders": 0, "stock_value": 0,
                                "in_transit_value": 0, "cash": 0, "last_activity": ""}
    assert created["default_cash_account_id"]
    after = _totals(ctx)
    assert after == before, (before, after)  # a new empty branch: no movements, balances, stock or revenue

    # idempotent reads: profiles are not duplicated
    for _ in range(2):
        assert len(_json(admin.get(API))["rows"]) == 2
    from flask import g

    from models.branch_profile import BranchProfile

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        assert BranchProfile.query.count() == 2


def test_validation_archive_and_disable_rules(ctx):
    admin = _client(ctx)
    _json(admin.post(f"{API}/feature", json={"enabled": True}))
    new = _json(admin.post(API, json={"code": "MNS", "name": "فرع المنصور"}))["branch"]
    assert admin.post(API, json={"code": "mns", "name": "تكرار"}).status_code == 409
    assert admin.post(API, json={"code": "", "name": "بلا كود"}).status_code == 400
    assert admin.post(API, json={"code": "BAD", "name": "x", "branch_type": "spaceship"}).status_code == 400
    assert admin.post(f"{API}/{new['id']}/update", json={"latitude": 123}).status_code == 400

    # with two active branches the feature cannot be switched off
    res = admin.post(f"{API}/feature", json={"enabled": False})
    assert res.status_code == 409 and "أرشف" in res.get_json()["error"]
    # the primary branch cannot be archived
    assert admin.post(f"{API}/{ctx['main']}/archive", json={}).status_code == 409
    # an empty branch can: archived, hidden from the default list, restorable
    archived = _json(admin.post(f"{API}/{new['id']}/archive", json={"reason": "إغلاق"}))["branch"]
    assert archived["is_active"] is False and archived["archive_reason"] == "إغلاق"
    assert [r["id"] for r in _json(admin.get(API))["rows"]] == [ctx["main"]]
    assert len(_json(admin.get(f"{API}?archived=1"))["rows"]) == 2
    assert _json(admin.post(f"{API}/feature", json={"enabled": False}))["multi_branch"]["enabled"] is False
    assert _json(admin.post(f"{API}/{new['id']}/archive", json={"restore": True}))["branch"]["is_active"] is True
    # derived mode: a company that already has two active branches is shown as multi-branch
    assert _json(admin.get(f"{API}/meta"))["multi_branch"]["active_branches"] == 2


def test_branch_holding_stock_cannot_be_archived(ctx):
    admin = _client(ctx)
    _json(admin.post(f"{API}/feature", json={"enabled": True}))
    new = _json(admin.post(API, json={"code": "BSR", "name": "فرع البصرة"}))["branch"]
    from flask import g

    from extensions import db
    from models.branch import BranchStock
    from models.product import Product

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        product = Product.query.execution_options(skip_branch_scope=True).first()
        db.session.add(BranchStock(branch_id=new["id"], product_id=product.id, quantity=3, opening_stock=0))
        db.session.commit()
    res = admin.post(f"{API}/{new['id']}/archive", json={})
    assert res.status_code == 409 and "مخزون" in res.get_json()["error"]
    detail = _json(admin.get(f"{API}/{new['id']}"))
    assert any("مخزون" in b for b in detail["blockers"])


def test_only_general_admin_manages_and_others_see_only_their_branch(ctx, monkeypatch):
    admin = _client(ctx)
    _json(admin.post(f"{API}/feature", json={"enabled": True}))
    _json(admin.post(API, json={"code": "KRD", "name": "فرع الكرادة"}))
    clerk = _client(ctx, "clerk")
    for method, path, body in (("post", API, {"code": "X1", "name": "x"}),
                               ("post", f"{API}/feature", {"enabled": False}),
                               ("post", f"{API}/{ctx['main']}/update", {"name": "اختراق"}),
                               ("post", f"{API}/{ctx['main']}/archive", {})):
        res = getattr(clerk, method)(path, json=body)
        assert res.status_code == 403 and res.is_json, path
    rows = _json(clerk.get(API))["rows"]
    assert [r["id"] for r in rows] == [ctx["main"]]  # only the branch they are assigned to
    assert _json(clerk.get(API))["rows"][0]["name"] != "اختراق"
    # a branch outside their scope looks like it does not exist
    other = [r for r in _json(admin.get(API))["rows"] if r["id"] != ctx["main"]][0]
    assert clerk.get(f"{API}/{other['id']}").status_code == 404
    # no session at all (the dev-only loopback auto-login is switched off for this request, as in production)
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")
    anonymous = ctx["app"].test_client()
    for path in (API, f"{API}/meta", f"{API}/{ctx['main']}"):
        res = anonymous.get(path)
        assert res.status_code in (301, 302, 401, 403), (path, res.status_code)
        assert "KRD" not in res.get_data(as_text=True)
    assert anonymous.post(API, json={"code": "HACK", "name": "x"}).status_code in (301, 302, 401, 403)


def test_companies_are_isolated(app):
    one, two = _make_ctx(app), _make_ctx(app)
    a, b = _client(one), _client(two)
    _json(a.post(f"{API}/feature", json={"enabled": True}))
    made = _json(a.post(API, json={"code": "ONLY1", "name": "فرع الشركة الأولى"}))["branch"]
    codes_b = {r["code"] for r in _json(b.get(API))["rows"]}
    assert "ONLY1" not in codes_b and len(codes_b) == 1
    assert b.get(f"{API}/{made['id']}").status_code in (404, 200) and \
        "ONLY1" not in str(b.get(f"{API}/{made['id']}").get_json())
    assert _json(b.get(f"{API}/meta"))["multi_branch"]["enabled"] is False


def test_scope_switch_is_server_side_and_admin_only(ctx):
    admin = _client(ctx)
    _json(admin.post(f"{API}/feature", json={"enabled": True}))
    other = _json(admin.post(API, json={"code": "KRD", "name": "فرع الكرادة"}))["branch"]
    meta = _json(admin.get(f"{API}/meta"))
    assert meta["scope"]["can_switch"] is True
    assert {b["id"] for b in meta["scope"]["branches"]} == {ctx["main"], other["id"]}

    _json(admin.post(f"{API}/switch", json={"branch_id": other["id"]}))
    after = _json(admin.get(f"{API}/meta"))
    assert after["current_branch_id"] == other["id"] and after["scope"]["view_all"] is False
    _json(admin.post(f"{API}/switch", json={"view_all": True}))
    assert _json(admin.get(f"{API}/meta"))["scope"]["view_all"] is True
    assert admin.post(f"{API}/switch", json={"branch_id": 999999}).status_code == 404

    clerk = _client(ctx, "clerk")
    assert _json(clerk.get(f"{API}/meta"))["scope"]["can_switch"] is False
    res = clerk.post(f"{API}/switch", json={"branch_id": other["id"]})
    assert res.status_code == 403
    assert _json(clerk.get(f"{API}/meta"))["current_branch_id"] == ctx["main"]  # the attempt changed nothing


def test_transfer_policy_is_admin_only_and_in_transit_value_stays_with_the_sender(ctx):
    from flask import g

    from extensions import db
    from models.branch import StockTransfer, StockTransferLine
    from models.inventory_lot import InventoryLot
    from models.product import Product
    from models.stock_operations import StockTransferCostLayer

    admin = _client(ctx)
    _json(admin.post(f"{API}/feature", json={"enabled": True}))
    other = _json(admin.post(API, json={"code": "KRD", "name": "فرع الكرادة"}))["branch"]
    assert _json(admin.get(f"{API}/meta"))["transfer_policy"] == {"approval_required": False}
    assert _json(admin.post(f"{API}/transfer-policy", json={"approval_required": True}))["transfer_policy"] == \
        {"approval_required": True}
    assert _json(admin.get(f"{API}/meta"))["transfer_policy"]["approval_required"] is True
    assert _client(ctx, "clerk").post(f"{API}/transfer-policy", json={"approval_required": False}).status_code == 403

    # a sent, not yet received transfer: 3 units @ 100,000 leave the main branch and stay its property in transit
    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        product = Product.query.execution_options(skip_branch_scope=True).first()
        lot = InventoryLot.query.filter_by(product_id=product.id).first()
        transfer = StockTransfer(transfer_no="TR-T1", from_branch_id=ctx["main"], to_branch_id=other["id"], status="sent")
        db.session.add(transfer)
        db.session.flush()
        line = StockTransferLine(transfer_id=transfer.id, product_id=product.id, quantity=3)
        db.session.add(line)
        db.session.flush()
        db.session.add(StockTransferCostLayer(transfer_kind="branch", transfer_id=transfer.id, line_id=line.id,
                                              phase="send", sequence=0, branch_id=ctx["main"], product_id=product.id,
                                              lot_id=lot.id, quantity=3, unit_cost=100000))
        db.session.commit()
    rows = {r["id"]: r for r in _json(admin.get(API))["rows"]}
    assert rows[ctx["main"]]["stats"]["in_transit_value"] == 300000
    assert rows[other["id"]]["stats"]["in_transit_value"] == 0


def test_a_general_manager_role_with_view_all_branches_sees_every_branch(ctx):
    """«عرض كل الفروع» granted to a non-admin (e.g. a general-manager role) gives the same view scope as the admin:
    the switch, every branch in the list and the aggregated «جميع الفروع» view."""
    from flask import g

    from extensions import db
    from models.employee_permission import EmployeePermissionOverride
    from utils import permission_overrides

    admin = _client(ctx)
    _json(admin.post(f"{API}/feature", json={"enabled": True}))
    other = _json(admin.post(API, json={"code": "KRD", "name": "فرع الكرادة"}))["branch"]
    clerk = _client(ctx, "clerk")
    assert _json(clerk.get(f"{API}/meta"))["scope"]["can_switch"] is False  # without the permission: one branch
    assert clerk.post(f"{API}/switch", json={"view_all": True}).status_code == 403
    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        permission_overrides.ensure_table()
        db.session.add(EmployeePermissionOverride(employee_id=ctx["clerk_id"], permission="view_all_branches",
                                                  effect="grant"))
        db.session.commit()
    manager = _client(ctx, "clerk")
    meta = _json(manager.get(f"{API}/meta"))
    assert meta["scope"]["can_switch"] is True and meta["scope"]["shared"] is False
    assert {b["id"] for b in meta["scope"]["branches"]} == {ctx["main"], other["id"]}
    _json(manager.post(f"{API}/switch", json={"view_all": True}))
    assert _json(manager.get(f"{API}/meta"))["scope"]["view_all"] is True
    _json(manager.post(f"{API}/switch", json={"branch_id": other["id"]}))
    assert _json(manager.get(f"{API}/meta"))["current_branch_id"] == other["id"]
