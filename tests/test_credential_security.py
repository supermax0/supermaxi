"""Phase 9 / Priority 1 — credential security regression tests.

Every tenant-provisioning path (Super Admin create, payment approval, admin password reset, database reset) must:
never use a shared default password, store only the hash, never log / audit / e-mail / persist the plaintext, return
it exactly once (no-store) to the operator, and force a password change at first login. Lost credentials are reset,
never revealed. The tests scan database files, registration files, logs, API responses and activity payloads.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

import pytest
from flask import Flask, g, session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SLUG = "leaktest"


@pytest.fixture()
def sa(tmp_path, monkeypatch, caplog):
    import models  # noqa: F401
    import models.core.leads.models  # noqa: F401
    import models.core.tenant  # noqa: F401
    import models.delivery_agent  # noqa: F401
    import extensions_tenant
    from extensions import db
    from models.core.subscription_plan import SubscriptionPlan
    from services import tenant_provisioning
    from utils import email_helper

    monkeypatch.setattr(extensions_tenant, "_tenant_engines", {})
    monkeypatch.setattr(tenant_provisioning, "_POLICY_COLUMN_ENSURED", set())
    import routes.employees as employees_routes

    monkeypatch.setattr(employees_routes, "_EMPLOYEE_PROFILE_SCHEMA_ENSURED", set())

    emails: list[dict] = []
    monkeypatch.setattr(email_helper, "send_email", lambda **kw: emails.append(kw) or True)

    app = Flask(__name__, root_path=str(tmp_path), template_folder=str(ROOT / "templates"),
                static_folder=str(ROOT / "static"))
    app.config.update(SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'core.db'}", SECRET_KEY="test-secret",
                      TESTING=True)
    db.init_app(app)

    @app.before_request
    def _bind_tenant():  # what app.require_login does for logged-in tenant users
        if session.get("tenant_slug"):
            g.tenant = session["tenant_slug"]

    from routes.index import index_bp
    from routes.superadmin import superadmin_bp

    app.register_blueprint(index_bp)
    app.register_blueprint(superadmin_bp)
    with app.app_context():
        db.Model.metadata.create_all(db.engine)
        db.session.add(SubscriptionPlan(plan_key="basic", name="الأساسية", price_monthly=25000, price_yearly=250000,
                                        max_users=3))
        db.session.commit()
    caplog.set_level(logging.DEBUG)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["is_superadmin"] = True
        sess["superadmin_id"] = 1
    return {"app": app, "client": client, "root": tmp_path, "emails": emails, "caplog": caplog}


def _create(sa, slug=SLUG, **extra):
    data = {"name": "Leak Test Co", "slug": slug, "owner_name": "Owner", "business_type": "general",
            "trial_days": "14", "owner_email": "owner@example.test", **extra}
    return sa["client"].post("/superadmin/tenants/create", data=data)


def _password_from_html(html: str) -> str:
    match = re.search(r'id="once-pass">([^<]+)<', html)
    assert match, "one-time credentials page must show the password"
    return match.group(1)


def _all_stored_bytes(root: Path) -> bytes:
    """Every database / registration / log file the app wrote (Core DB, tenant DBs incl. WAL, profiles)."""
    blob = b""
    for path in root.rglob("*"):
        if path.is_file():
            blob += path.read_bytes()
    return blob


def _assert_nowhere(sa, secret: str, *responses) -> None:
    from extensions_tenant import clear_tenant_engine

    with sa["app"].app_context():
        clear_tenant_engine(SLUG)  # flush/close SQLite handles before scanning the files
    assert secret.encode() not in _all_stored_bytes(sa["root"]), "plaintext password persisted"
    assert secret not in sa["caplog"].text, "plaintext password logged"
    for mail in sa["emails"]:
        assert secret not in json.dumps(mail, ensure_ascii=False), "plaintext password e-mailed"
    for res in responses:
        assert secret not in res.get_data(as_text=True), "password returned by a read endpoint"


def _admin(sa, slug=SLUG):
    from sqlalchemy import text

    from extensions_tenant import get_tenant_engine

    with sa["app"].app_context():
        with get_tenant_engine(slug).connect() as conn:
            return conn.execute(text("SELECT username, password, must_change_password FROM employee "
                                     "WHERE username='admin'")).one()


# ───────────────────────────── generator ─────────────────────────────


def test_initial_passwords_are_random_strong_and_never_the_old_default():
    from services.tenant_provisioning import generate_initial_password

    seen = {generate_initial_password() for _ in range(200)}
    assert len(seen) == 200
    for pw in seen:
        assert len(pw) >= 16 and pw != "password123"
        assert any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw)
    assert "password123" not in (ROOT / "routes" / "superadmin.py").read_text(encoding="utf-8")
    assert "password123" not in (ROOT / "templates" / "superadmin_create_tenant.html").read_text(encoding="utf-8")


def test_provision_result_repr_never_contains_the_password():
    from services.tenant_provisioning import ProvisionResult

    result = ProvisionResult(tenant_id=1, slug="x", username="admin", password="S3cret-Value-XYZ")
    assert "S3cret-Value-XYZ" not in repr(result) and "S3cret-Value-XYZ" not in str(result)


# ───────────────────────────── Super Admin create ─────────────────────────────


def test_superadmin_create_returns_credentials_once_and_stores_only_the_hash(sa):
    res = _create(sa, admin_password="operator-chosen-123")  # an operator-supplied password is ignored
    assert res.status_code == 200
    assert "no-store" in res.headers["Cache-Control"]
    password = _password_from_html(res.get_data(as_text=True))
    assert password != "operator-chosen-123" and password != "password123" and len(password) >= 16
    # nothing flashed (flash messages persist in the session cookie)
    with sa["client"].session_transaction() as sess:
        assert not sess.get("_flashes")

    from werkzeug.security import check_password_hash

    username, stored, must_change = _admin(sa)
    assert stored != password and check_password_hash(stored, password)
    assert bool(must_change) is True

    registration = json.loads((sa["root"] / "tenants" / "profiles" / f"{SLUG}.json").read_text(encoding="utf-8"))
    assert not {"password", "admin_password", "password2"} & set(registration)

    reads = [sa["client"].get(f"/superadmin/tenants/registration/{SLUG}"),
             sa["client"].get(f"/superadmin/tenants/details/{SLUG}"),
             sa["client"].get("/superadmin/tenants/search?q=leak")]
    for read in reads:
        assert read.status_code == 200
        body = read.get_json()
        assert "password" not in json.dumps(body.get("registration", {}))
    assert reads[0].get_json()["registration"].get("password") is None
    # welcome e-mail went out without the password
    assert len(sa["emails"]) == 1
    _assert_nowhere(sa, password, *reads)


def test_failed_provisioning_rolls_back_everything(sa, monkeypatch):
    from services import tenant_provisioning

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(tenant_provisioning, "_create_admin", boom)
    res = _create(sa, slug="rollback1")
    assert res.status_code == 302
    from models.core.tenant import Tenant

    with sa["app"].app_context():
        assert Tenant.query.filter_by(slug="rollback1").first() is None
    assert not (sa["root"] / "tenants" / "rollback1.db").exists()
    assert "disk full" not in res.get_data(as_text=True)


# ───────────────────────────── first login → forced change ─────────────────────────────


def _login(client, password, slug=SLUG):
    return client.post("/login", data={"tenant_slug": slug, "username": "admin", "password": password})


def test_one_time_password_forces_a_change_before_anything_else(sa):
    password = _password_from_html(_create(sa).get_data(as_text=True))
    user = sa["app"].test_client()
    res = _login(user, password)
    assert res.status_code == 302 and res.headers["Location"].endswith("/account/change-password")
    # every other page / API is blocked until the password is replaced
    assert user.get("/").headers["Location"].endswith("/account/change-password")
    blocked = user.get("/api/anything", headers={"Accept": "application/json"})
    assert blocked.status_code == 403 and blocked.get_json()["error"] == "password_change_required"
    page = user.get("/account/change-password")
    assert page.status_code == 200 and page.headers["Cache-Control"] == "no-store"

    # weak / mismatched / unchanged passwords are refused
    for current, new, confirm in ((password, "short", "short"), (password, "LongEnough-1", "Different-22"),
                                  ("wrong-current", "LongEnough-1", "LongEnough-1"), (password, password, password)):
        res = user.post("/account/change-password",
                        data={"current_password": current, "new_password": new, "confirm_password": confirm})
        assert res.status_code == 200 and "cp-error" in res.get_data(as_text=True)

    new_password = "My-Own-Strong-Pass-9"
    res = user.post("/account/change-password", data={"current_password": password, "new_password": new_password,
                                                      "confirm_password": new_password})
    assert res.status_code == 302 and res.headers["Location"] == "/"
    with user.session_transaction() as sess:
        assert "must_change_password" not in sess
    _, stored, must_change = _admin(sa)
    assert bool(must_change) is False and new_password not in stored
    # the one-time password is dead, the new one logs straight in
    assert "/account/change-password" not in (_login(sa["app"].test_client(), new_password).headers["Location"])
    assert _login(sa["app"].test_client(), password).status_code == 200  # login page with an error
    _assert_nowhere(sa, new_password)
    _assert_nowhere(sa, password)


@pytest.mark.parametrize("business_type,workspace", [("clinics", "/clinics/"), ("hr_management", "/hr/"), ("general", "/")])
def test_first_password_change_survives_the_production_activity_guard(sa, business_type, workspace):
    # The production guard runs before the index password policy; a blueprint-only app misses redirect loops.
    # Load the actual guard functions without starting the application's unrelated migrations/workers.
    import ast
    import os
    import sqlite3
    from flask import current_app, request, redirect, jsonify
    from extensions import db
    from models.employee import Employee

    names = {"require_login", "_local_workspace_request", "_ensure_local_workspace_session",
             "_clinics_activity_allows_path", "_hr_activity_allows_path", "_path_is_open"}
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in functions} == names
    for node in functions:
        node.decorator_list = []
    namespace = {"app": sa["app"], "db": db, "Employee": Employee, "g": g, "session": session,
                 "request": request, "current_app": current_app, "redirect": redirect, "jsonify": jsonify,
                 "os": os, "sqlite3": sqlite3, "_debug_log_app": lambda *a, **kw: None}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(ROOT / "app.py"), "exec"), namespace)
    require_login = namespace["require_login"]
    _clinics_activity_allows_path = namespace["_clinics_activity_allows_path"]
    _hr_activity_allows_path = namespace["_hr_activity_allows_path"]

    sa["app"].before_request_funcs[None].insert(0, require_login)
    password = _password_from_html(_create(sa, business_type=business_type).get_data(as_text=True))
    user = sa["app"].test_client()
    assert _login(user, password).headers["Location"].endswith("/account/change-password")
    page = user.get("/account/change-password", follow_redirects=True)
    assert page.status_code == 200 and page.headers["Cache-Control"] == "no-store"
    assert user.get(workspace).headers["Location"].endswith("/account/change-password")
    assert user.get("/api/anything").status_code == 403
    rejected = user.post("/account/change-password", data={"current_password": "incorrect", "new_password": "Strong-Changed-Pass-9", "confirm_password": "Strong-Changed-Pass-9"})
    assert rejected.status_code == 200 and "cp-error" in rejected.get_data(as_text=True)
    changed = user.post("/account/change-password", data={"current_password": password, "new_password": "Strong-Changed-Pass-9", "confirm_password": "Strong-Changed-Pass-9"})
    assert changed.status_code == 302
    with user.session_transaction() as sess:
        assert "must_change_password" not in sess
    assert not _admin(sa)[2]
    if business_type in {"clinics", "hr_management"}:
        assert user.get("/inventory").headers["Location"] == workspace
    _assert_nowhere(sa, password)
    _assert_nowhere(sa, "Strong-Changed-Pass-9")
    for allows in (_clinics_activity_allows_path, _hr_activity_allows_path):
        assert allows("/account/change-password")
        assert not allows("/account/change-password/extra")
        assert not allows("/account/other")


# ───────────────────────────── reset, never reveal ─────────────────────────────


def test_password_reset_generates_server_side_and_returns_once(sa):
    first = _password_from_html(_create(sa).get_data(as_text=True))
    res = sa["client"].post(f"/superadmin/tenants/reset-password/{SLUG}", json={"password": "attacker-chosen"})
    assert res.status_code == 200 and "no-store" in res.headers["Cache-Control"]
    creds = res.get_json()["credentials"]
    assert creds["password"] not in (first, "attacker-chosen", "password123") and len(creds["password"]) >= 16

    from werkzeug.security import check_password_hash

    _, stored, must_change = _admin(sa)
    assert check_password_hash(stored, creds["password"]) and not check_password_hash(stored, "attacker-chosen")
    assert bool(must_change) is True
    # nothing can reveal it afterwards
    reads = [sa["client"].get(f"/superadmin/tenants/registration/{SLUG}"),
             sa["client"].get(f"/superadmin/tenants/details/{SLUG}")]
    _assert_nowhere(sa, creds["password"], *reads)
    assert sa["client"].post("/superadmin/tenants/reset-password/ghost").status_code == 404


def test_database_reset_never_uses_a_default_password(sa):
    _create(sa)
    res = sa["client"].post(f"/superadmin/tenants/reset-db/{SLUG}")
    assert res.status_code == 200, res.get_data(as_text=True)
    body = res.get_json()
    assert "password123" not in json.dumps(body, ensure_ascii=False)
    password = body["credentials"]["password"]
    assert len(password) >= 16 and "no-store" in res.headers["Cache-Control"]
    _, stored, must_change = _admin(sa)
    assert bool(must_change) is True
    _assert_nowhere(sa, password)


def test_payment_approval_path_uses_the_same_secure_provisioning(sa):
    from extensions import db
    from models.core.payment_request import PaymentRequest

    with sa["app"].app_context():
        req = PaymentRequest(tenant_name=SLUG, owner_name="Payer", email="payer@example.test", phone="07700000000",
                             status="pending")
        for column in PaymentRequest.__table__.columns:  # fill any other NOT NULL columns with neutral values
            if not column.nullable and column.default is None and not column.primary_key and getattr(req, column.key) is None:
                setattr(req, column.key, 0 if str(column.type).upper().startswith(("INT", "FLOAT", "NUMERIC")) else "x")
        db.session.add(req)
        db.session.commit()
        req_id = req.id
    res = sa["client"].post(f"/superadmin/requests/{req_id}/approve")
    assert res.status_code == 200 and "no-store" in res.headers["Cache-Control"]
    password = _password_from_html(res.get_data(as_text=True))
    assert password != "password123"
    with sa["app"].app_context():
        assert db.session.get(PaymentRequest, req_id).status == "approved"
    _, _, must_change = _admin(sa)
    assert bool(must_change) is True
    _assert_nowhere(sa, password)


# ───────────────────────────── legacy data & payload redaction ─────────────────────────────


def test_legacy_plaintext_registration_is_scrubbed_on_read(sa):
    _create(sa)
    path = sa["root"] / "tenants" / "profiles" / f"{SLUG}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["password"] = "legacy-plaintext-777"
    path.write_text(json.dumps(data), encoding="utf-8")
    res = sa["client"].get(f"/superadmin/tenants/registration/{SLUG}")
    assert "legacy-plaintext-777" not in res.get_data(as_text=True)
    assert "legacy-plaintext-777" not in path.read_text(encoding="utf-8")


def test_registration_saves_drop_every_credential_field(sa):
    from utils.tenant_registration import load_tenant_registration, save_tenant_registration

    with sa["app"].app_context():
        save_tenant_registration("plain", {"company_name": "X", "password": "p1", "password2": "p1",
                                           "admin_password": "p2", "new_password": "p3"})
        stored = load_tenant_registration("plain")
    assert not {"password", "password2", "admin_password", "new_password"} & set(stored)


def test_activity_payloads_redact_every_password_field(sa):
    from utils.activity_logger import capture_request_body, sanitize_payload

    with sa["app"].test_request_context("/account/change-password", method="POST",
                                        data={"current_password": "a1", "new_password": "b2", "confirm_password": "c3"}):
        body = capture_request_body()
    assert set(body.values()) == {"[redacted]"}
    nested = sanitize_payload({"credentials": {"username": "admin", "password": "zz"}, "access_token": "t"})
    assert "zz" not in json.dumps(nested) and nested["access_token"] == "[redacted]"
