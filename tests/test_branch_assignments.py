"""Multi-branch employee (spec phases 13/16): extra branches and home moves with history."""
from __future__ import annotations

import pytest

from tests.test_branch_management_api import API as BRANCH_API
from tests.test_branch_management_api import _client, _json, _make_ctx, app  # noqa: F401


@pytest.fixture()
def ctx(app):  # noqa: F811
    from flask import g

    from extensions import db
    from models.employee import Employee
    from werkzeug.security import generate_password_hash

    ids = _make_ctx(app)
    admin = _client(ids)
    _json(admin.post(f"{BRANCH_API}/feature", json={"enabled": True}))
    second = _json(admin.post(BRANCH_API, json={"code": "MNS", "name": "فرع المنصور"}))["branch"]
    third = _json(admin.post(BRANCH_API, json={"code": "KRD", "name": "فرع الكرادة"}))["branch"]
    with app.test_request_context():
        g.tenant = ids["tenant"]
        worker = Employee(name="Worker", username="bc_worker", password=generate_password_hash("x-pass-123"),
                          role="sales", is_active=True, branch_id=ids["main"])
        db.session.add(worker)
        db.session.commit()
        ids["worker_id"] = worker.id
    return {**ids, "second": second["id"], "third": third["id"]}


def _as(ctx, who):
    client = ctx["app"].test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = ctx[f"{who}_id"]
        sess["tenant_slug"] = ctx["tenant"]
        sess["role"] = "admin" if who == "admin" else "sales"
        sess["name"] = who
    return client


def _assign(ctx, mode, branch, who="worker"):
    return _as(ctx, "admin").post(f"{BRANCH_API}/people/{ctx[who + '_id']}/assign",
                                  json={"branch_id": branch, "mode": mode})


def _switch(ctx, branch, who="worker"):
    return _as(ctx, who).post(f"{BRANCH_API}/switch", json={"branch_id": branch})


def test_unassigned_cannot_switch_and_people_is_admin_only(ctx):
    assert _switch(ctx, ctx["second"]).status_code == 403
    assert _as(ctx, "worker").get(f"{BRANCH_API}/people").status_code in (401, 403)
    rows = _json(_as(ctx, "admin").get(f"{BRANCH_API}/people"))["rows"]
    worker = next(r for r in rows if r["id"] == ctx["worker_id"])
    assert worker["home_branch_id"] == ctx["main"] and worker["extras"] == []


def test_extra_assignment_enables_switch_then_unassign_removes(ctx):
    assert _assign(ctx, "extra", ctx["second"]).status_code == 200
    assert _switch(ctx, ctx["second"]).status_code == 200
    assert _switch(ctx, ctx["third"]).status_code == 403  # still not assigned
    assert _assign(ctx, "extra", ctx["second"]).status_code == 409  # already assigned
    out = _as(ctx, "admin").post(f"{BRANCH_API}/people/{ctx['worker_id']}/unassign",
                                 json={"branch_id": ctx["second"]})
    assert out.status_code == 200
    assert _switch(ctx, ctx["second"]).status_code == 403


def test_move_home_keeps_history_and_admin_is_refused(ctx):
    assert _assign(ctx, "move", ctx["second"]).status_code == 200
    rows = _json(_as(ctx, "admin").get(f"{BRANCH_API}/people/{ctx['worker_id']}/history"))["rows"]
    kinds = [(r["branch_id"], r["kind"], r["active"]) for r in rows]
    assert (ctx["second"], "home", True) in kinds and (ctx["main"], "home", False) in kinds
    assert _assign(ctx, "extra", ctx["third"], who="admin").status_code in (400, 404)


def test_view_all_is_admin_only(ctx):
    _assign(ctx, "extra", ctx["second"])
    res = _as(ctx, "worker").post(f"{BRANCH_API}/switch", json={"view_all": True})
    assert res.status_code == 403
