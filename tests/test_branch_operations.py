"""Branch operations (spec phase 10): a sale always names ONE operating branch.

«All branches» is a view scope only. In a company with several branches a general admin's sale without a
branch used to be booked, silently, on the company default branch; the server now refuses it. Companies with a
single branch, and every non-admin, behave exactly as before."""
from __future__ import annotations

import pytest

from tests.test_branch_management_api import API as BRANCH_API
from tests.test_branch_management_api import _client, _json, _make_ctx, app  # noqa: F401

POS = "/pos/create-order"


@pytest.fixture()
def ctx(app):  # noqa: F811
    ids = _make_ctx(app)
    admin = _client(ids)
    _json(admin.post(f"{BRANCH_API}/feature", json={"enabled": True}))
    second = _json(admin.post(BRANCH_API, json={"code": "MNS", "name": "فرع المنصور"}))["branch"]
    return {**ids, "second": second["id"]}


def _resolve(ctx, who, requested, strict=True):
    """resolve_checkout_branch for the seeded admin / clerk, inside a real request context."""
    from flask import g, session

    from models.employee import Employee
    from services.pos_checkout import resolve_checkout_branch
    from utils.branch_context import init_branch_context

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        session.update(user_id=ctx[f"{who}_id"], role="admin" if who == "admin" else "sales",
                       tenant_slug=ctx["tenant"])
        init_branch_context()
        employee = Employee.query.execution_options(skip_branch_scope=True).get(ctx[f"{who}_id"])
        return resolve_checkout_branch(employee, requested, require_explicit_branch=strict)


def test_admin_sale_without_a_branch_is_refused_when_the_company_has_several(ctx):
    from services.pos_checkout import PosCheckoutError

    with pytest.raises(PosCheckoutError) as refused:
        _resolve(ctx, "admin", None)
    assert refused.value.payload.get("code") == "BRANCH_REQUIRED" and refused.value.status_code == 400
    assert "فرعاً تشغيلياً" in refused.value.payload.get("error", "")
    with pytest.raises(PosCheckoutError):
        _resolve(ctx, "admin", "all")  # «all» is a view, never an operating branch
    assert _resolve(ctx, "admin", ctx["second"]) == ctx["second"]  # an explicit branch is honoured
    assert _resolve(ctx, "admin", str(ctx["main"])) == ctx["main"]
    # machine integrations (API key stations) keep the company-default behaviour they were built against
    assert _resolve(ctx, "admin", None, strict=False) == ctx["main"]


def test_staff_and_single_branch_companies_are_unchanged(ctx, app):  # noqa: F811
    from services.pos_checkout import PosCheckoutError

    assert _resolve(ctx, "clerk", None) == ctx["main"]  # a cashier always sells from his own branch
    with pytest.raises(PosCheckoutError) as other:
        _resolve(ctx, "clerk", ctx["second"])
    assert other.value.payload.get("code") == "BRANCH_NOT_ALLOWED"

    single = _make_ctx(app)  # one branch only: the old behaviour, no new question for the admin
    assert _resolve(single, "admin", None) == single["main"]


def test_the_checkout_endpoint_reports_the_missing_branch_before_touching_anything(ctx):
    admin = _client(ctx)
    res = admin.post(POS, json={"customer_id": 1, "items": [{"product_id": 1, "quantity": 1, "price": 1000}]})
    assert res.status_code == 400
    assert res.get_json().get("code") == "BRANCH_REQUIRED"
    from flask import g

    from models.invoice import Invoice

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        assert Invoice.query.execution_options(skip_branch_scope=True).count() == 1  # only the seeded sale


def test_availability_in_other_branches_follows_the_company_policy(ctx):
    from flask import g

    from extensions import db
    from models.product import Product
    from utils.branch_sales import set_sell_from_all_branches

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        product_id = Product.query.execution_options(skip_branch_scope=True).first().id
    path = f"{BRANCH_API}/availability?product_id={product_id}"
    admin, clerk = _client(ctx), _client(ctx, "clerk")

    seen = _json(admin.get(path))
    by_branch = {r["id"]: r["quantity"] for r in seen["rows"]}
    assert by_branch[ctx["main"]] == 7 and by_branch[ctx["second"]] == 0 and seen["total"] == 7
    assert clerk.get(path).status_code == 403  # other branches' stock is not a cashier's business…

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        set_sell_from_all_branches(True)  # …unless the company sells from other branches' stock
        db.session.commit()
    assert {r["id"] for r in _json(clerk.get(path))["rows"]} == {ctx["main"], ctx["second"]}
    assert admin.get(f"{BRANCH_API}/availability").status_code == 400
