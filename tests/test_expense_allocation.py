"""Expense kinds and allocation (spec phase 13): a reporting overlay — total expense never changes."""
from __future__ import annotations

from datetime import date

import pytest

from tests.test_branch_management_api import API as BRANCH_API
from tests.test_branch_management_api import _client, _json, _make_ctx, app  # noqa: F401

ALLOC = f"{BRANCH_API}/expense-allocation"
DAY = "2026-10-10"


@pytest.fixture()
def ctx(app):  # noqa: F811
    from flask import g

    from extensions import db
    from models.expense import Expense

    ids = _make_ctx(app)
    admin = _client(ids)
    _json(admin.post(f"{BRANCH_API}/feature", json={"enabled": True}))
    second = _json(admin.post(BRANCH_API, json={"code": "MNS", "name": "فرع المنصور"}))["branch"]
    with app.test_request_context():
        g.tenant = ids["tenant"]
        rows = [Expense(title="إيجار مشترك", amount=1001, branch_id=ids["main"], expense_date=date(2026, 10, 10)),
                Expense(title="إدارة", amount=500, branch_id=ids["main"], expense_date=date(2026, 10, 10)),
                Expense(title="كهرباء", amount=300, branch_id=second["id"], expense_date=date(2026, 10, 10)),
                Expense(title="بلا فرع", amount=40, branch_id=None, expense_date=date(2026, 10, 10))]
        db.session.add_all(rows)
        db.session.commit()
        exp = [r.id for r in rows]
    return {**ids, "admin": admin, "second": second["id"], "exp": exp}


def _report(ctx):
    return _json(ctx["admin"].get(f"{ALLOC}/report?from=2026-10-01&to=2026-10-31"))


def test_report_without_allocations_is_the_plain_direct_view(ctx):
    r = _report(ctx)
    by = {b["branch_id"]: b["amount"] for b in r["branches"]}
    assert by == {ctx["main"]: 1501, ctx["second"]: 300}
    assert r["unassigned"] == 40 and r["central"] == 0 and r["company_total"] == 1841


def test_preview_fixed_split_adds_up_and_stores_nothing(ctx):
    out = _json(ctx["admin"].post(f"{ALLOC}/preview", json={
        "amount": 1001, "rule": "fixed", "weights": {str(ctx["main"]): 1, str(ctx["second"]): 2}}))
    assert sum(ln["amount"] for ln in out["lines"]) == 1001
    assert _report(ctx)["company_total"] == 1841
    assert _report(ctx)["central"] == 0


def test_shared_and_central_move_attribution_but_not_the_total(ctx):
    shared, central = ctx["exp"][0], ctx["exp"][1]
    res = ctx["admin"].post(f"{ALLOC}/{shared}", json={
        "kind": "shared", "rule": "fixed", "weights": {str(ctx["main"]): 50, str(ctx["second"]): 50}})
    assert res.status_code == 200
    assert ctx["admin"].post(f"{ALLOC}/{central}", json={"kind": "central"}).status_code == 200
    r = _report(ctx)
    by = {b["branch_id"]: b["amount"] for b in r["branches"]}
    assert by == {ctx["main"]: 501, ctx["second"]: 800}  # 1001 splits 501/500; the 300 direct is added
    assert r["central"] == 500 and r["unassigned"] == 40
    assert sum(by.values()) + r["central"] + r["unassigned"] == r["company_total"] == 1841
    # back to a plain branch expense: the overlay disappears
    assert ctx["admin"].post(f"{ALLOC}/{shared}", json={"kind": "branch"}).status_code == 200
    assert {b["branch_id"]: b["amount"] for b in _report(ctx)["branches"]}[ctx["main"]] == 1001


def test_manual_must_match_amount_and_non_admin_is_refused(ctx):
    bad = ctx["admin"].post(f"{ALLOC}/preview", json={
        "amount": 1001, "rule": "manual", "weights": {str(ctx["main"]): 500, str(ctx["second"]): 400}})
    assert bad.status_code == 400
    clerk = ctx["app"].test_client()
    with clerk.session_transaction() as sess:
        sess["user_id"], sess["tenant_slug"], sess["role"] = ctx["clerk_id"], ctx["tenant"], "sales"
    assert clerk.post(f"{ALLOC}/{ctx['exp'][0]}", json={"kind": "central"}).status_code in (401, 403)


def test_assignments_lists_only_central_and_shared_of_the_period(ctx):
    ctx["admin"].post(f"{ALLOC}/{ctx['exp'][1]}", json={"kind": "central"})
    ctx["admin"].post(f"{ALLOC}/{ctx['exp'][0]}", json={
        "kind": "shared", "rule": "fixed", "weights": {str(ctx["main"]): 1, str(ctx["second"]): 1}})
    rows = _json(ctx["admin"].get(f"{ALLOC}/assignments?from=2026-10-01&to=2026-10-31"))["rows"]
    assert rows[str(ctx["exp"][1])]["kind"] == "central"
    assert rows[str(ctx["exp"][0])]["kind"] == "shared" and len(rows[str(ctx["exp"][0])]["lines"]) == 2
    assert str(ctx["exp"][2]) not in rows  # a plain branch expense carries no overlay
