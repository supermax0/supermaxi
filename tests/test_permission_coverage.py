"""Whole-application permission coverage: walks every route and checks who can reach it.

Guards against the bug class found on 2026-10-16: the login gate exempted every path that merely STARTED with a
public prefix ("/c" for the patient portal opened /customers, /cash, /clinics … to anonymous callers).
"""
from __future__ import annotations

import pytest

from tests.permission_probe import SURFACES, is_success, walk
from tests.test_branch_management_api import _client, _make_ctx, app  # noqa: F401

# Public by design (landing, shop, payment gateway callbacks, bot/webhook receivers, signed public links).
PUBLIC_PREFIXES = (
    "/", "/shop", "/payment", "/payments", "/payment_failed", "/telegram", "/webhook", "/webhooks", "/unsubscribe",
    "/signup", "/landing", "/super-max", "/supermax", "/terms", "/privacy", "/pricing", "/robots.txt",
    "/sitemap.xml", "/favicon.ico", "/mcp/health", "/messages/unread-count", "/employee-desk", "/api/landing",
    "/upgrade", "/data-deletion", "/webhook-ui",
)
# Endpoints any signed-in employee may call (they only describe himself).
OPEN_FOR_ANY_EMPLOYEE = {
    "GET /api/v1/desktop/permissions/me",
    "GET /api/v1/desktop/branches/meta",  # the scope selector every employee needs (names only)
    # the lists below answer with names only (figures are withheld without view_branch_reports — tested separately)
    "GET /api/v1/desktop/branches",
    "GET /api/v1/desktop/branches/<int:branch_id>",
}


def _is_public(rule: str) -> bool:
    path = "/" + rule.split(" ", 1)[1].lstrip("/")
    return path == "/" or any(path == p or path.startswith(p + "/") for p in PUBLIC_PREFIXES if p != "/")


@pytest.fixture()
def world(app, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")  # the dev auto-login would hide every gap
    ids = _make_ctx(app)

    def client(user_id=None, role="sales"):
        c = app.test_client()
        with c.session_transaction() as sess:
            sess["tenant_slug"] = ids["tenant"]
            if user_id:
                sess["user_id"], sess["role"], sess["name"] = user_id, role, "walker"
        return c

    return {"app": app, "tenant": ids["tenant"], "clerk_id": ids["clerk_id"], "anon": lambda: client(), "powerless": lambda: client(ids["clerk_id"]),
            "admin": lambda: client(ids["admin_id"], "admin")}


def test_anonymous_callers_reach_only_the_public_routes(world):
    results = walk(world["app"], world["anon"], surfaces=("/",))
    leaked = sorted(k for k, (s, _) in results.items() if is_success(s) and not _is_public(k))
    assert leaked == [], f"reachable without signing in: {leaked}"


@pytest.mark.parametrize("path", ["/customers/", "/customers/export", "/customers/blacklist", "/cash/",
                                  "/cash/api/movements", "/clinics/", "/clinics/api/bootstrap", "/pos/last-orders",
                                  "/pos/search-customer?q=a", "/pos/search-product?q=a"])
def test_previously_exposed_paths_now_refuse_anonymous(world, path):
    res = world["anon"]().get(path)
    assert not is_success(res.status_code), (path, res.status_code)


def test_an_employee_without_any_right_reaches_no_desktop_surface(world):
    results = walk(world["app"], world["powerless"], surfaces=SURFACES)
    open_ones = sorted(k for k, (s, _) in results.items() if is_success(s) and k not in OPEN_FOR_ANY_EMPLOYEE)
    assert open_ones == [], f"reachable by an employee holding no permission: {open_ones}"
    assert not [k for k, (s, _) in results.items() if s >= 500], "a route crashed for a powerless caller"


def test_the_walk_is_meaningful_the_admin_reaches_most_of_it(world):
    results = walk(world["app"], world["admin"], surfaces=SURFACES)
    ok = [k for k, (s, _) in results.items() if is_success(s)]
    assert len(ok) > 40, f"control failed: the admin reached only {len(ok)} of {len(results)} routes"


def _grant_everything(world, effect):
    """Override EVERY grantable permission of the powerless employee with ``effect`` (grant / deny)."""
    from flask import g

    from extensions import db
    from models.employee_permission import EmployeePermissionOverride
    from utils import permission_admin, permission_overrides

    with world["app"].test_request_context():
        g.tenant = world["tenant"]
        permission_overrides.ensure_table()
        for name in sorted(permission_admin.grantable_names()):
            db.session.add(EmployeePermissionOverride(employee_id=world["clerk_id"], permission=name, effect=effect))
        db.session.commit()


def test_granting_everything_unlocks_all_but_the_admin_only_actions(world):
    admin = walk(world["app"], world["admin"], surfaces=SURFACES)
    _grant_everything(world, "grant")
    powered = walk(world["app"], world["powerless"], surfaces=SURFACES)
    admin_ok = {k for k, (s, _) in admin.items() if is_success(s)}
    powered_ok = {k for k, (s, _) in powered.items() if is_success(s)}
    only_admin = sorted(admin_ok - powered_ok)
    print("ADMIN_ONLY", only_admin)
    assert only_admin == EXPECTED_ADMIN_ONLY


def test_denying_everything_locks_the_employee_out_of_every_desktop_surface(world):
    _grant_everything(world, "deny")
    results = walk(world["app"], world["powerless"], surfaces=SURFACES)
    open_ones = sorted(k for k, (s, _) in results.items() if is_success(s) and k not in OPEN_FOR_ANY_EMPLOYEE)
    assert open_ones == []


# Actions only a general admin may do even when every permission is granted: administering permissions itself
# (granting power is never delegable). Anything else appearing here is an accidental admin-only endpoint.
EXPECTED_ADMIN_ONLY: list[str] = [
    "GET /api/v1/desktop/catalog/settings",  # switching the master-catalogue layer on/off is a company decision
    "GET /api/v1/desktop/permissions/audit",
    "GET /api/v1/desktop/permissions/catalog",
    "GET /api/v1/desktop/permissions/employees",
    "GET /api/v1/desktop/permissions/employees/<int:employee_id>",
    "GET /api/v1/desktop/permissions/role-templates",
    "GET /api/v1/desktop/permissions/roles",
    "GET /api/v1/desktop/store-analytics/settings",  # the online store's design switch and policy texts
    "POST /api/v1/desktop/catalog/settings",
    "POST /api/v1/desktop/permissions/roles/<int:role_id>/delete",
    "POST /api/v1/desktop/store-analytics/settings",
]
