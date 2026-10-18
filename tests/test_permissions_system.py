"""Professional permissions system: roles + per-employee exceptions, enforced by the server.

Effective permission of a non-admin = DENY exception > GRANT exception > assigned roles. A general admin is never
restricted. Every delegable admin action of the desktop API is checked end-to-end: no right → 403, right (by
role or by exception) → allowed, deny exception beats the role, and an unrelated employee is never affected."""
from __future__ import annotations

import pytest

from tests.test_branch_management_api import API as BRANCH_API
from tests.test_branch_management_api import _client, _json, _make_ctx, app  # noqa: F401

PERM = "/api/v1/desktop/permissions"
SHIP = "/api/v1/desktop/shipping-center"


@pytest.fixture()
def ctx(app, monkeypatch):  # noqa: F811
    from flask import g

    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")  # the dev auto-login must not hide anonymous behaviour

    from extensions import db
    from models.employee import Employee
    from werkzeug.security import generate_password_hash

    ids = _make_ctx(app)
    admin = _client(ids)
    _json(admin.post(f"{BRANCH_API}/feature", json={"enabled": True}))
    with app.test_request_context():
        g.tenant = ids["tenant"]
        other = Employee(name="Other", username="pm_other", password=generate_password_hash("x-pass-123"),
                         role="sales", is_active=True, branch_id=ids["main"])
        db.session.add(other)
        db.session.commit()
        ids["other_id"] = other.id
    return {**ids, "admin": admin}


def _as(ctx, who):
    client = ctx["app"].test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = ctx[f"{who}_id"]
        sess["tenant_slug"] = ctx["tenant"]
        sess["role"] = "admin" if who == "admin" else "sales"
        sess["name"] = who
    return client


def _override(ctx, who, changes):
    return ctx["admin"].post(f"{PERM}/employees/{ctx[who + '_id']}/overrides", json={"changes": changes})


def _make_role(ctx, name, permissions):
    out = _json(ctx["admin"].post(f"{PERM}/roles", json={"name": name, "permissions": permissions}))
    return next(r["id"] for r in out["rows"] if r["name"] == name)


def _assign_role(ctx, who, role_id):
    return ctx["admin"].post(f"{PERM}/employees/{ctx[who + '_id']}/roles", json={"role_ids": [role_id]})


def _can(ctx, who, name):
    from flask import g

    from models.employee import Employee
    from utils.permission_checks import employee_can

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        return employee_can(Employee.query.execution_options(skip_branch_scope=True).get(ctx[f"{who}_id"]), name)


# ───────────────────────────── catalog & access ─────────────────────────────


def test_catalog_is_complete_unique_and_hides_the_intrinsic_admin_right(ctx):
    groups = _json(ctx["admin"].get(f"{PERM}/catalog"))["groups"]
    names = [p["name"] for g in groups for p in g["permissions"]]
    assert len(names) == len(set(names)) > 60  # every permission exactly once
    assert "view_all_branches" not in names
    for needed in ("manage_branches", "view_branch_reports", "manage_branch_staff", "run_branch_distribution",
                   "allocate_branch_expenses", "merge_delivery_agents", "view_pos", "delete_orders"):
        assert needed in names
    flagged = {p["name"] for g in groups for p in g["permissions"] if p["sensitive"]}
    assert {"delete_orders", "manage_branches", "view_financial"} <= flagged


@pytest.mark.parametrize("method,path", [
    ("get", "/catalog"), ("get", "/employees"), ("get", "/roles"), ("get", "/audit"),
    ("post", "/roles"), ("post", "/employees/1/overrides"), ("post", "/employees/1/roles"),
])
def test_only_a_general_admin_can_administer_permissions(ctx, method, path):
    clerk = _as(ctx, "clerk")
    res = getattr(clerk, method)(PERM + path, **({"json": {}} if method == "post" else {}))
    assert res.status_code == 403
    anon = ctx["app"].test_client()
    assert getattr(anon, method)(PERM + path, **({"json": {}} if method == "post" else {})).status_code in (401, 403)


def test_a_non_admin_can_delegate_nothing_to_himself_even_with_manage_employees(ctx):
    role = _make_role(ctx, "hr", ["manage_employees", "manage_settings"])
    _assign_role(ctx, "clerk", role)
    assert _as(ctx, "clerk").post(f"{PERM}/employees/{ctx['clerk_id']}/overrides",
                                  json={"changes": {"view_financial": "grant"}}).status_code == 403


# ───────────────────────────── the override semantics ─────────────────────────────


def test_deny_beats_role_grant_beats_nothing_and_removal_restores_the_role(ctx):
    assert _can(ctx, "clerk", "view_fixed_assets") is False
    assert _override(ctx, "clerk", {"view_fixed_assets": "grant"}).status_code == 200
    assert _can(ctx, "clerk", "view_fixed_assets") is True  # an exception alone suffices
    role = _make_role(ctx, "reporter", ["view_fixed_assets"])
    _assign_role(ctx, "clerk", role)
    _override(ctx, "clerk", {"view_fixed_assets": None})
    assert _can(ctx, "clerk", "view_fixed_assets") is True  # now by the role
    _override(ctx, "clerk", {"view_fixed_assets": "deny"})
    assert _can(ctx, "clerk", "view_fixed_assets") is False  # deny beats the role
    _override(ctx, "clerk", {"view_fixed_assets": None})
    assert _can(ctx, "clerk", "view_fixed_assets") is True  # removing the exception: the role decides again


def test_exceptions_are_per_employee_and_never_touch_the_admin(ctx):
    _override(ctx, "clerk", {"view_fixed_assets": "grant"})
    assert _can(ctx, "clerk", "view_fixed_assets") is True and _can(ctx, "other", "view_fixed_assets") is False
    assert _can(ctx, "admin", "view_fixed_assets") is True
    refused = _override(ctx, "admin", {"view_fixed_assets": "deny"})
    assert refused.status_code == 400  # an admin cannot be restricted by a row
    assert _can(ctx, "admin", "view_fixed_assets") is True


def test_a_deny_exception_also_removes_the_cashier_builtin_defaults(ctx):
    from flask import g

    from extensions import db
    from models.employee import Employee

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        Employee.query.execution_options(skip_branch_scope=True).get(ctx["other_id"]).role = "cashier"
        db.session.commit()
    assert _can(ctx, "other", "print_pos_invoice") is True  # built-in cashier duty
    _override(ctx, "other", {"print_pos_invoice": "deny"})
    assert _can(ctx, "other", "print_pos_invoice") is False


def test_an_inactive_employee_has_nothing_even_with_a_grant(ctx):
    from flask import g

    from extensions import db
    from models.employee import Employee

    _override(ctx, "other", {"view_fixed_assets": "grant"})
    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        Employee.query.execution_options(skip_branch_scope=True).get(ctx["other_id"]).is_active = False
        db.session.commit()
    assert _can(ctx, "other", "view_fixed_assets") is False


def test_validation_unknown_permission_bad_effect_empty_and_replace(ctx):
    assert _override(ctx, "clerk", {"no_such_permission": "grant"}).status_code == 400
    assert _override(ctx, "clerk", {"view_fixed_assets": "maybe"}).status_code == 400
    assert _override(ctx, "clerk", {}).status_code == 400
    assert ctx["admin"].post(f"{PERM}/employees/999999/overrides", json={"changes": {"view_fixed_assets": "grant"}}).status_code == 404
    _override(ctx, "clerk", {"view_fixed_assets": "grant"})
    _override(ctx, "clerk", {"view_fixed_assets": "deny"})  # one row per permission: the last word wins
    detail = _json(ctx["admin"].get(f"{PERM}/employees/{ctx['clerk_id']}"))
    row = next(p for p in detail["permissions"] if p["name"] == "view_fixed_assets")
    assert row["override"] == "deny" and row["allowed"] is False and row["source"] == "deny"


def test_detail_explains_where_each_permission_comes_from(ctx):
    role = _make_role(ctx, "sellers", ["view_pos", "edit_price"])
    _assign_role(ctx, "clerk", role)
    _override(ctx, "clerk", {"edit_price": "deny", "view_fixed_assets": "grant"})
    detail = _json(ctx["admin"].get(f"{PERM}/employees/{ctx['clerk_id']}"))
    by = {p["name"]: p for p in detail["permissions"]}
    assert by["view_pos"]["source"] == "role" and by["view_pos"]["roles"] == ["sellers"] and by["view_pos"]["allowed"]
    assert by["edit_price"]["source"] == "deny" and not by["edit_price"]["allowed"]
    assert by["view_fixed_assets"]["source"] == "grant" and by["view_fixed_assets"]["allowed"]
    assert by["delete_orders"]["source"] == "none" and not by["delete_orders"]["allowed"]
    admin_detail = _json(ctx["admin"].get(f"{PERM}/employees/{ctx['admin_id']}"))
    assert all(p["allowed"] and p["source"] == "admin" for p in admin_detail["permissions"])


def test_me_reports_the_signed_in_employees_effective_permissions(ctx):
    _override(ctx, "clerk", {"view_fixed_assets": "grant"})
    me = _json(_as(ctx, "clerk").get(f"{PERM}/me"))
    assert "view_fixed_assets" in me["allowed"] and "delete_orders" not in me["allowed"] and me["is_admin"] is False
    full = _json(ctx["admin"].get(f"{PERM}/me"))
    assert full["is_admin"] is True and "delete_orders" in full["allowed"]


def test_permission_check_survives_a_missing_overrides_table(ctx):
    from flask import g

    from extensions import db

    role = _make_role(ctx, "viewer", ["view_fixed_assets"])
    _assign_role(ctx, "clerk", role)
    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        db.session.execute(db.text("DROP TABLE IF EXISTS employee_permission_override"))
        db.session.commit()
    assert _can(ctx, "clerk", "view_fixed_assets") is True  # an older tenant without the table behaves as before


# ───────────────────────────── roles ─────────────────────────────


def test_roles_crud_rules(ctx):
    role = _make_role(ctx, "accountant", ["view_accounts", "view_expenses"])
    dup = ctx["admin"].post(f"{PERM}/roles", json={"name": "accountant", "permissions": []})
    assert dup.status_code == 409
    assert ctx["admin"].post(f"{PERM}/roles", json={"name": "x2", "permissions": ["nope"]}).status_code == 400
    assert ctx["admin"].post(f"{PERM}/roles", json={"name": " ", "permissions": []}).status_code == 400
    upd = _json(ctx["admin"].post(f"{PERM}/roles/{role}", json={"name": "accountant", "permissions": ["view_accounts"]}))
    assert next(r for r in upd["rows"] if r["id"] == role)["permissions"] == ["view_accounts"]
    _assign_role(ctx, "clerk", role)
    assert _can(ctx, "clerk", "view_accounts") is True and _can(ctx, "clerk", "view_expenses") is False
    assert ctx["admin"].post(f"{PERM}/roles/{role}/delete", json={}).status_code == 409  # still assigned
    ctx["admin"].post(f"{PERM}/employees/{ctx['clerk_id']}/roles", json={"role_ids": []})
    assert _can(ctx, "clerk", "view_accounts") is False
    assert ctx["admin"].post(f"{PERM}/roles/{role}/delete", json={}).status_code == 200
    assert ctx["admin"].post(f"{PERM}/employees/{ctx['clerk_id']}/roles", json={"role_ids": [987654]}).status_code == 404


def test_every_change_is_written_to_the_audit_log(ctx):
    role = _make_role(ctx, "auditme", ["view_fixed_assets"])
    _assign_role(ctx, "clerk", role)
    _override(ctx, "clerk", {"delete_orders": "deny"})
    rows = _json(ctx["admin"].get(f"{PERM}/audit"))["rows"]
    actions = {r["action"] for r in rows}
    assert {"save_role", "assign_roles", "set_overrides"} <= actions
    ov = next(r for r in rows if r["action"] == "set_overrides")
    assert ov["by"] and ov["payload"]["after"] == {"delete_orders": "deny"}


# ───────────────────────────── enforcement of every delegable action ─────────────────────────────

# (method, path, body, permission) — each is an admin-only action that a named permission can delegate.
ACTIONS = [
    ("get", f"{BRANCH_API}/report?from=2026-10-01&to=2026-10-31", None, "view_branch_reports"),
    ("post", BRANCH_API, {"code": "ZZ1", "name": "فرع جديد"}, "manage_branches"),
    ("post", f"{BRANCH_API}/feature", {"enabled": True}, "manage_branches"),
    ("post", f"{BRANCH_API}/transfer-policy", {"approval_required": False}, "manage_branches"),
    ("get", f"{BRANCH_API}/people", None, "manage_branch_staff"),
    ("get", f"{BRANCH_API}/people/1/history", None, "manage_branch_staff"),
    ("post", f"{BRANCH_API}/people/999999/assign", {"branch_id": 1, "mode": "extra"}, "manage_branch_staff"),
    ("post", f"{BRANCH_API}/people/999999/unassign", {"branch_id": 1}, "manage_branch_staff"),
    ("get", f"{BRANCH_API}/distribution", None, "run_branch_distribution"),
    ("post", f"{BRANCH_API}/distribution", {"title": "جلسة", "items": []}, "run_branch_distribution"),
    ("get", f"{BRANCH_API}/distribution/999999", None, "run_branch_distribution"),
    ("post", f"{BRANCH_API}/distribution/999999/approve", {}, "run_branch_distribution"),
    ("post", f"{BRANCH_API}/expense-allocation/preview", {"amount": 100, "rule": "fixed"}, "allocate_branch_expenses"),
    ("post", f"{BRANCH_API}/expense-allocation/999999", {"kind": "central"}, "allocate_branch_expenses"),
    ("get", f"{BRANCH_API}/expense-allocation/assignments?from=2026-10-01&to=2026-10-31", None, "allocate_branch_expenses"),
    ("get", f"{BRANCH_API}/expense-allocation/report?from=2026-10-01&to=2026-10-31", None, "allocate_branch_expenses"),
    ("get", f"{SHIP}/agents/duplicates", None, "merge_delivery_agents"),
    ("post", f"{SHIP}/agents/merge", {"primary_id": 1, "duplicate_ids": []}, "merge_delivery_agents"),
]
# The shipping center first requires access to the center itself; the merge right comes on top of it.
BASE_RIGHT = {"merge_delivery_agents": "view_shipping"}


def _call(client, method, path, body):
    return getattr(client, method)(path, **({"json": body} if body is not None else {}))


@pytest.mark.parametrize("method,path,body,permission", ACTIONS)
def test_delegable_action_is_enforced_by_role_exception_and_deny(ctx, method, path, body, permission):
    clerk = _as(ctx, "clerk")
    base = BASE_RIGHT.get(permission)
    # admin passes the gate (the action itself may still answer 400/404/409 for the dummy ids)
    assert _call(ctx["admin"], method, path, body).status_code not in (401, 403)
    # no right → refused by the server
    assert _call(clerk, method, path, body).status_code == 403
    if base:  # the base access alone is not enough
        _override(ctx, "clerk", {base: "grant"})
        _override(ctx, "other", {base: "grant"})
        assert _call(clerk, method, path, body).status_code == 403
    # an individual grant opens exactly this action
    _override(ctx, "clerk", {permission: "grant"})
    assert _call(clerk, method, path, body).status_code not in (401, 403)
    # …and an unrelated employee stays locked out
    assert _call(_as(ctx, "other"), method, path, body).status_code == 403
    # a deny exception shuts it again, even though a role grants it
    role = _make_role(ctx, f"r-{permission}", [permission])
    _assign_role(ctx, "clerk", role)
    _override(ctx, "clerk", {permission: "deny"})
    assert _call(clerk, method, path, body).status_code == 403
    # removing the exception: the role alone is enough
    _override(ctx, "clerk", {permission: None})
    assert _call(clerk, method, path, body).status_code not in (401, 403)


def test_branch_figures_are_withheld_until_the_report_right_is_given(ctx):
    clerk = _as(ctx, "clerk")
    rows = _json(clerk.get(BRANCH_API))["rows"]
    assert rows and all(r["stats"] is None for r in rows)  # names only: no sales / stock value / cash
    detail = _json(clerk.get(f"{BRANCH_API}/{rows[0]['id']}"))
    assert detail["branch"]["stats"] is None and detail["blockers"] == []
    _override(ctx, "clerk", {"view_branch_reports": "grant"})
    assert all(r["stats"] is not None for r in _json(clerk.get(BRANCH_API))["rows"])
    meta = _json(clerk.get(f"{BRANCH_API}/meta"))
    assert meta["can_report"] is True and meta["can_manage"] is False
    _override(ctx, "clerk", {"manage_branches": "grant"})
    assert _json(clerk.get(f"{BRANCH_API}/meta"))["can_manage"] is True


# ───────────────────────────── ready-made roles ─────────────────────────────


def _install(ctx, keys):
    return ctx["admin"].post(f"{PERM}/role-templates/install", json={"keys": keys})


def test_templates_are_listed_and_every_permission_in_them_exists(ctx):
    rows = _json(ctx["admin"].get(f"{PERM}/role-templates"))["rows"]
    assert {r["name"] for r in rows} >= {"كاشير", "محاسب", "متابعة الطلبات", "مسؤول مخزون", "مسؤول شحن", "مدير فرع"}
    assert not any(r["installed"] for r in rows)
    out = _json(_install(ctx, [r["key"] for r in rows]))
    assert len(out["created"]) == len(rows) and out["skipped"] == []
    installed = {r["name"]: r for r in out["rows"]}
    for tpl in rows:  # a permission name that does not exist in the catalog would be silently dropped
        assert sorted(installed[tpl["name"]]["permissions"]) == sorted(set(tpl["permissions"])), tpl["name"]


def test_install_never_overwrites_and_is_repeatable(ctx):
    _install(ctx, ["cashier"])
    cashier = next(r for r in _json(ctx["admin"].get(f"{PERM}/roles"))["rows"] if r["name"] == "كاشير")
    ctx["admin"].post(f"{PERM}/roles/{cashier['id']}", json={"name": "كاشير", "permissions": ["view_pos"]})
    again = _json(_install(ctx, ["cashier", "accountant"]))
    assert again["created"] == ["محاسب"] and again["skipped"] == ["كاشير"]
    kept = next(r for r in again["rows"] if r["name"] == "كاشير")
    assert kept["permissions"] == ["view_pos"]  # the customised role was not reset


def test_installed_roles_give_exactly_their_rights(ctx):
    out = _json(_install(ctx, ["cashier", "accountant"]))
    ids = {r["name"]: r["id"] for r in out["rows"]}
    _assign_role(ctx, "clerk", ids["كاشير"])
    assert _can(ctx, "clerk", "view_pos") and _can(ctx, "clerk", "print_pos_invoice")
    assert not _can(ctx, "clerk", "delete_orders") and not _can(ctx, "clerk", "view_accounts")
    _assign_role(ctx, "clerk", ids["محاسب"])
    assert _can(ctx, "clerk", "view_accounts") and _can(ctx, "clerk", "finance.ledger")
    assert not _can(ctx, "clerk", "manage_branches") and not _can(ctx, "clerk", "edit_price")
    assert not _can(ctx, "clerk", "finance.settings") and not _can(ctx, "clerk", "finance.reverse")


def test_template_install_validation_and_access(ctx):
    assert _install(ctx, ["nope"]).status_code == 400
    assert _install(ctx, []).status_code == 400
    assert _as(ctx, "clerk").post(f"{PERM}/role-templates/install", json={"keys": ["cashier"]}).status_code == 403
    assert _as(ctx, "clerk").get(f"{PERM}/role-templates").status_code == 403
