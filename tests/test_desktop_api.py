"""FINORA Management Desktop — JSON sign-in / session probe / sign-out.

The desktop client must get exactly the web staff session (shared
services.staff_auth), never a half-open session for one-time passwords, and a
JSON 401 instead of a login-page redirect.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from flask import Flask, g, session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SLUG = "desktoptest"
NEW_PASSWORD = "Desk-Strong-Pass-42"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import models  # noqa: F401
    import models.core.leads.models  # noqa: F401
    import models.core.tenant  # noqa: F401
    import models.delivery_agent  # noqa: F401
    import extensions_tenant
    from extensions import db
    from models.core.subscription_plan import SubscriptionPlan
    from modules.pos_api.services import rate_limit
    from services import tenant_provisioning
    from utils import email_helper

    monkeypatch.setattr(extensions_tenant, "_tenant_engines", {})
    monkeypatch.setattr(tenant_provisioning, "_POLICY_COLUMN_ENSURED", set())
    monkeypatch.setattr(rate_limit, "_buckets", rate_limit.defaultdict(rate_limit.deque))
    import routes.employees as employees_routes

    monkeypatch.setattr(employees_routes, "_EMPLOYEE_PROFILE_SCHEMA_ENSURED", set())
    monkeypatch.setattr(email_helper, "send_email", lambda **kw: True)

    app = Flask(__name__, root_path=str(tmp_path), template_folder=str(ROOT / "templates"),
                static_folder=str(ROOT / "static"))
    app.config.update(SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'core.db'}", SECRET_KEY="test-secret",
                      TESTING=True)
    db.init_app(app)

    @app.before_request
    def _bind_tenant():  # what app.require_login does for logged-in tenant users
        if session.get("tenant_slug"):
            g.tenant = session["tenant_slug"]

    from modules.desktop_api import init_desktop_api
    from routes.index import index_bp
    from routes.superadmin import superadmin_bp

    app.register_blueprint(index_bp)
    app.register_blueprint(superadmin_bp)
    init_desktop_api(app)
    with app.app_context():
        db.Model.metadata.create_all(db.engine)
        db.session.add(SubscriptionPlan(plan_key="basic", name="الأساسية", price_monthly=25000, price_yearly=250000,
                                        max_users=3))
        db.session.commit()

    operator = app.test_client()
    with operator.session_transaction() as sess:
        sess["is_superadmin"] = True
        sess["superadmin_id"] = 1
    created = operator.post("/superadmin/tenants/create", data={
        "name": "Desktop Test Co", "slug": SLUG, "owner_name": "Owner", "business_type": "general",
        "trial_days": "14", "owner_email": "owner@example.test",
    })
    match = re.search(r'id="once-pass">([^<]+)<', created.get_data(as_text=True))
    assert match, "tenant provisioning must show the one-time password"
    return {"app": app, "one_time_password": match.group(1)}


def _desktop_login(client, password, *, slug=SLUG, username="admin"):
    return client.post("/api/v1/desktop/auth/login",
                       json={"tenant_slug": slug, "username": username, "password": password})


def _replace_one_time_password(env) -> None:
    web = env["app"].test_client()
    web.post("/login", data={"tenant_slug": SLUG, "username": "admin", "password": env["one_time_password"]})
    res = web.post("/account/change-password", data={
        "current_password": env["one_time_password"], "new_password": NEW_PASSWORD,
        "confirm_password": NEW_PASSWORD,
    })
    assert res.status_code == 302


def test_session_probe_without_sign_in_is_json_401(env):
    res = env["app"].test_client().get("/api/v1/desktop/auth/session")
    assert res.status_code == 401
    assert res.get_json() == {"ok": False, "error": "انتهت الجلسة، سجّل الدخول من جديد", "code": "unauthenticated"}
    assert res.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("payload,status,code", [
    ({"tenant_slug": SLUG, "username": "admin"}, 400, "validation_error"),
    ({"tenant_slug": "missing-co", "username": "admin", "password": "x"}, 404, "tenant_not_found"),
    ({"tenant_slug": SLUG, "username": "admin", "password": "wrong-password"}, 401, "invalid_credentials"),
])
def test_sign_in_rejections_are_typed(env, payload, status, code):
    res = env["app"].test_client().post("/api/v1/desktop/auth/login", json=payload)
    assert res.status_code == status
    assert res.get_json()["code"] == code


def test_one_time_password_never_opens_a_desktop_session(env):
    client = env["app"].test_client()
    res = _desktop_login(client, env["one_time_password"])
    assert res.status_code == 403 and res.get_json()["code"] == "password_change_required"
    with client.session_transaction() as sess:
        assert "user_id" not in sess
    assert client.get("/api/v1/desktop/auth/session").status_code == 401


def test_sign_in_establishes_the_web_staff_session_and_reports_permissions(env):
    _replace_one_time_password(env)
    client = env["app"].test_client()
    res = _desktop_login(client, NEW_PASSWORD, username="ADMIN")  # username is case-insensitive like the web
    assert res.status_code == 200, res.get_data(as_text=True)
    body = res.get_json()
    assert body["ok"] is True
    info = body["session"]
    assert info["user"]["username"] == "admin" and info["user"]["role"] == "admin"
    assert info["tenant"]["slug"] == SLUG and info["tenant"]["name"]
    assert "admin" in info["roles"]
    assert {"can_see_orders", "manage_orders", "can_manage_inventory", "edit_price"} <= set(info["permissions"])
    assert info["session_max_age_seconds"] > 0
    assert NEW_PASSWORD not in res.get_data(as_text=True)

    with client.session_transaction() as sess:
        assert sess["tenant_slug"] == SLUG and sess["role"] == "admin" and sess.permanent is True
        assert sess["business_type"] == "general"

    probe = client.get("/api/v1/desktop/auth/session")
    assert probe.status_code == 200 and probe.get_json()["session"]["user"]["id"] == info["user"]["id"]

    out = client.post("/api/v1/desktop/auth/logout")
    assert out.status_code == 200 and out.get_json() == {"ok": True, "signed_out": True}
    assert client.get("/api/v1/desktop/auth/session").status_code == 401


def test_web_login_still_uses_the_same_session_shape(env):
    _replace_one_time_password(env)
    web = env["app"].test_client()
    res = web.post("/login", data={"tenant_slug": SLUG, "username": "admin", "password": NEW_PASSWORD})
    assert res.status_code == 302 and res.headers["Location"] == "/"
    with web.session_transaction() as sess:
        assert sess["tenant_slug"] == SLUG and sess["role"] == "admin" and sess.permanent is True
    assert web.get("/api/v1/desktop/auth/session").status_code == 200


def test_sign_in_is_rate_limited(env):
    client = env["app"].test_client()
    codes = [_desktop_login(client, "wrong-password").status_code for _ in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429
