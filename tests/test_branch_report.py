"""Branch comparison report (spec phase 15): sourced figures only, totals add up, admin only."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from tests.test_branch_management_api import API as BRANCH_API
from tests.test_branch_management_api import _client, _json, _make_ctx, app  # noqa: F401


@pytest.fixture()
def ctx(app):  # noqa: F811
    from flask import g

    from extensions import db
    from models.customer import Customer
    from models.expense import Expense
    from models.invoice import Invoice

    ids = _make_ctx(app)
    admin = _client(ids)
    _json(admin.post(f"{BRANCH_API}/feature", json={"enabled": True}))
    second = _json(admin.post(BRANCH_API, json={"code": "MNS", "name": "فرع المنصور"}))["branch"]
    with app.test_request_context():
        g.tenant = ids["tenant"]
        customer = Customer.query.execution_options(skip_branch_scope=True).first()
        day = datetime.utcnow() - timedelta(days=1)

        def invoice(branch, total, status):
            return Invoice(customer_id=customer.id, customer_name=customer.name, branch_id=branch,
                           employee_id=ids["admin_id"], employee_name="admin", total=total, paid_amount=total,
                           status=status, payment_status="مسدد", sale_type="cash", stock_is_deducted=False,
                           created_at=day)

        db.session.add_all([invoice(second["id"], 200000, "تم التوصيل"), invoice(second["id"], 50000, "ملغي"),
                            Expense(title="إيجار", amount=70000, branch_id=second["id"],
                                    expense_date=date.today())])
        db.session.commit()
    return {**ids, "admin": admin, "second": second["id"]}


def _report(ctx, **extra):
    start = (date.today() - timedelta(days=30)).isoformat()
    query = f"from={start}&to={date.today().isoformat()}" + "".join(f"&{k}={v}" for k, v in extra.items())
    return ctx["admin"].get(f"{BRANCH_API}/report?{query}")


def test_report_has_per_branch_figures_and_consistent_totals(ctx):
    data = _json(_report(ctx))
    by = {b["branch_id"]: b for b in data["branches"]}
    assert by[ctx["main"]]["sales"] == 450000 and by[ctx["main"]]["orders"] == 1
    assert by[ctx["second"]]["sales"] == 200000 and by[ctx["second"]]["canceled"] == 1  # canceled is not a sale
    assert by[ctx["second"]]["expenses"] == 70000
    assert data["totals"]["sales"] == 650000 and data["totals"]["expenses"] == 70000
    assert data["totals"]["stock_value"] == sum(b["stock_value"] for b in data["branches"])
    assert "net_profit" not in data["totals"] and data["notes"]  # unsourced figures are not shown


def test_branch_filter_period_validation_and_permission(ctx):
    only = _json(_report(ctx, branch_ids=ctx["second"]))
    assert [b["branch_id"] for b in only["branches"]] == [ctx["second"]]
    assert ctx["admin"].get(f"{BRANCH_API}/report?from=2026-10-10&to=2026-10-01").status_code == 400
    clerk = ctx["app"].test_client()
    with clerk.session_transaction() as sess:
        sess["user_id"], sess["tenant_slug"], sess["role"] = ctx["clerk_id"], ctx["tenant"], "sales"
    assert clerk.get(f"{BRANCH_API}/report?from=2026-10-01&to=2026-10-10").status_code in (401, 403)


def test_report_permission_limits_a_non_admin_to_his_assigned_branches(ctx):
    from flask import g

    from extensions import db
    from models.employee import Employee
    from models.role import Permission, Role

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        perm = Permission.query.filter_by(name="view_branch_reports").first() or Permission(
            name="view_branch_reports", description="view_branch_reports")
        role = Role(name="branch-reporter")
        role.permissions.append(perm)
        clerk_row = Employee.query.get(ctx["clerk_id"])
        clerk_row.roles.append(role)
        db.session.commit()
    clerk = ctx["app"].test_client()
    with clerk.session_transaction() as sess:
        sess["user_id"], sess["tenant_slug"], sess["role"] = ctx["clerk_id"], ctx["tenant"], "sales"
    start = (date.today() - timedelta(days=30)).isoformat()
    url = f"{BRANCH_API}/report?from={start}&to={date.today().isoformat()}"
    res = clerk.get(url)
    assert res.status_code == 200, res.get_json()
    data = res.get_json()
    assert [b["branch_id"] for b in data["branches"]] == [ctx["main"]]  # only his own branch
    assert data["central_expenses"] == 0 and data["unassigned_expenses"] == 0
    # asking for a branch that is not his does not widen the scope
    other = clerk.get(url + f"&branch_ids={ctx['second']}")
    assert other.status_code == 403
    # once assigned, the second branch is included
    assert ctx["admin"].post(f"{BRANCH_API}/people/{ctx['clerk_id']}/assign",
                             json={"branch_id": ctx["second"], "mode": "extra"}).status_code == 200
    assert {b["branch_id"] for b in clerk.get(url).get_json()["branches"]} == {ctx["main"], ctx["second"]}
