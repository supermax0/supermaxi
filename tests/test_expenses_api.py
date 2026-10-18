"""Expenses desktop API (/expenses/api/*) — same rules as the web page (one shared create function):
immediate posting of due expenses, scheduling of future ones, recurring series, treasury balance checks,
filters / totals, delete with refund, and JSON 403 (never a redirect) for users without the permission."""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PREFIX = f"test_expenses_api_{os.getpid()}"
_COUNTER = [0]
_CREATED: list[str] = []
JSON = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}


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
            db_file = ROOT / "tenants" / f"{slug}.db{suffix}"
            try:
                if db_file.exists():
                    db_file.unlink()
            except PermissionError:
                pass  # a background thread still holds it; the next run starts with fresh slugs anyway


def _seed(tenant: str) -> dict:
    from flask import g
    from werkzeug.security import generate_password_hash

    from extensions import db
    from extensions_tenant import init_tenant_db
    from models.account_transaction import AccountTransaction
    from models.employee import Employee
    from utils.branch_migration import get_default_branch

    g.tenant = tenant
    init_tenant_db(tenant)
    branch = get_default_branch()
    pw = generate_password_hash("x-pass-123")
    admin = Employee(name="Admin", username="ex_admin", password=pw, role="admin", is_active=True, branch_id=branch.id)
    cashier = Employee(name="Cashier", username="ex_cashier", password=pw, role="cashier", is_active=True,
                       branch_id=branch.id)
    db.session.add_all([admin, cashier])
    db.session.commit()
    from utils.treasury_helpers import get_default_cash_account

    cash = get_default_cash_account(branch.id)  # the company's own default cash box (created with the company)
    db.session.commit()
    db.session.add(AccountTransaction(branch_id=branch.id, type="deposit", amount=1_000_000, note="رأس مال",
                                      treasury_account_id=cash.id, created_at=datetime.now() - timedelta(days=1)))
    db.session.commit()
    return {"admin_id": admin.id, "cashier_id": cashier.id, "cash_id": cash.id}


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
    """A fresh company per test (no shared state between tests)."""
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
        sess["role"] = "admin" if who == "admin" else "cashier"
        sess["name"] = who
    return client


def _balance(ctx) -> int:
    from flask import g

    from utils.treasury_calculations import calculate_treasury_balance

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        return calculate_treasury_balance(ctx["cash_id"])


def _create(client, **body):
    payload = {"title": "إيجار المحل", "category": "rent", "amount": 50000,
               "expense_date": date.today().strftime("%Y-%m-%d"), **body}
    return client.post("/expenses/api/create", json=payload, headers=JSON)


def _page(client, **params):
    res = client.get("/expenses/api/page", query_string=params, headers=JSON)
    assert res.status_code == 200, res.get_data(as_text=True)[:500]
    return res.get_json()


def test_meta_lists_categories_and_treasury_accounts(ctx):
    body = _client(ctx).get("/expenses/api/meta", headers=JSON).get_json()
    assert body["success"] is True
    assert {"rent", "other"} <= {c["key"] for c in body["categories"]}
    assert body["treasury_accounts"][0]["name"] == "الصندوق" and body["treasury_accounts"][0]["is_default"] is True


def test_due_expense_is_posted_and_deducted_from_the_treasury(ctx):
    client = _client(ctx)
    res = _create(client, treasury_account_id=ctx["cash_id"])
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["posted_count"] == 1 and body["amount_withdrawn"] == 50000
    assert _balance(ctx) == 950_000
    page = _page(client)
    row = page["rows"][0]
    assert row["status"] == "posted" and row["category_label"] == "إيجار" and row["treasury_account_name"] == "الصندوق"
    assert page["summary"]["today_total"] == 50000 and page["summary"]["month_total"] == 50000
    assert page["counts"] == {"all": 1, "posted": 1, "scheduled": 0}


def test_future_expense_is_scheduled_without_touching_the_treasury(ctx):
    client = _client(ctx)
    future = (date.today() + timedelta(days=10)).strftime("%Y-%m-%d")
    body = _create(client, expense_date=future, amount=70000).get_json()
    assert body["scheduled_count"] == 1 and body["amount_withdrawn"] == 0
    assert _balance(ctx) == 1_000_000
    page = _page(client, tab="scheduled")
    assert page["rows"][0]["status"] == "scheduled"
    assert page["summary"]["scheduled_total"] == 70000 and page["summary"]["scheduled_count"] == 1


def test_recurring_series_posts_only_due_items(ctx):
    client = _client(ctx)
    body = _create(client, title="اشتراك إنترنت", category="internet", amount=30000, repeat_enabled=True,
                   repeat_interval=1, repeat_unit="months", repeat_count=3).get_json()
    assert body["count"] == 3 and body["posted_count"] == 1 and body["scheduled_count"] == 2
    assert _balance(ctx) == 970_000
    rows = _page(client)["rows"]
    assert {r["repeat_total"] for r in rows} == {3} and len({r["repeat_series_id"] for r in rows}) == 1
    series = client.get(f"/expenses/api/series/{rows[0]['id']}", headers=JSON).get_json()
    assert series["success"] is True and series["series"]["scheduled_count"] == 2


def test_insufficient_balance_and_invalid_input_create_nothing(ctx):
    client = _client(ctx)
    res = _create(client, amount=5_000_000)
    assert res.status_code == 409 and res.get_json()["error"]
    assert _create(client, amount=0).status_code == 400
    assert _create(client, title="  ").status_code == 400
    assert _create(client, expense_date="2026-99-01").status_code == 400
    assert _page(client)["total"] == 0 and _balance(ctx) == 1_000_000


def test_filters_totals_and_category_breakdown(ctx):
    client = _client(ctx)
    _create(client, title="فاتورة كهرباء", category="electricity", amount=40000)
    _create(client, title="إعلان فيسبوك", category="advertising", amount=25000, note="حملة رمضان")
    _create(client, title="كهرباء المولدة", category="electricity", amount=15000)
    assert [r["title"] for r in _page(client, search="رمضان")["rows"]] == ["إعلان فيسبوك"]
    elec = _page(client, category="electricity")
    assert elec["total"] == 2 and elec["summary"]["filtered_total"] == 55000
    breakdown = {c["key"]: c["amount"] for c in _page(client)["by_category"]}
    assert breakdown == {"electricity": 55000, "advertising": 25000}
    assert [r["amount"] for r in _page(client, sort="amount")["rows"]] == [40000, 25000, 15000]


def test_delete_refunds_the_treasury(ctx):
    client = _client(ctx)
    _create(client)
    expense_id = _page(client)["rows"][0]["id"]
    res = client.post(f"/expenses/delete/{expense_id}", headers=JSON)
    assert res.status_code == 200 and res.get_json()["success"] is True
    assert _balance(ctx) == 1_000_000 and _page(client)["total"] == 0


def test_users_without_the_permission_get_json_403_never_a_redirect(ctx):
    cashier = _client(ctx, "cashier")
    for method, path in (("get", "/expenses/api/page"), ("get", "/expenses/api/meta"), ("post", "/expenses/api/create")):
        res = getattr(cashier, method)(path, headers=JSON, json={} if method == "post" else None)
        assert res.status_code == 403, (path, res.status_code, res.headers.get("Location"))
        assert res.is_json and res.get_json()["success"] is False


def test_the_web_form_still_creates_expenses(ctx):
    client = _client(ctx)
    res = client.post("/expenses/", data={"title": "صيانة", "category": "maintenance", "amount": "20000",
                                          "expense_date": date.today().strftime("%Y-%m-%d"),
                                          "treasury_account_id": str(ctx["cash_id"])})
    assert res.status_code == 302
    assert _page(client)["rows"][0]["title"] == "صيانة" and _balance(ctx) == 980_000
