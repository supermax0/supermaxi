"""Admin UI + provider smoke tests for mobile app production hardening."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

TENANT = f"test_mobile_admin_{os.getpid()}"


def _wipe(tenant: str) -> None:
    db_file = ROOT / "tenants" / f"{tenant}.db"
    try:
        if db_file.exists():
            db_file.unlink()
    except OSError:
        pass


def test_mobile_admin_dashboard_and_providers():
    _wipe(TENANT)
    from datetime import datetime, timedelta

    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.core.tenant import Tenant as CoreTenant
    from models.employee import Employee
    from modules.mobile_app.providers.sms import LogSmsProvider, get_sms_provider
    from modules.mobile_app.providers.push import LogPushProvider, get_push_provider
    from werkzeug.security import generate_password_hash

    app.config["TESTING"] = True

    with app.app_context():
        assert isinstance(get_sms_provider(), LogSmsProvider)
    assert isinstance(get_push_provider(), LogPushProvider)
    assert LogSmsProvider().send_otp("07701112233", "123456") is True
    assert LogPushProvider().send(token="abc", title="t", body="b") is True

    with app.app_context():
        g.tenant = None
        existing = CoreTenant.query.filter_by(slug=TENANT).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
        core = CoreTenant(
            name="Mobile Admin Test",
            slug=TENANT,
            db_path=f"tenants/{TENANT}.db",
            business_type="general",
            is_active=True,
            subscription_end_date=datetime.utcnow() + timedelta(days=30),
        )
        db.session.add(core)
        db.session.commit()

        g.tenant = TENANT
        init_tenant_db(TENANT)
        admin = Employee(
            name="Admin",
            username=f"madmin_{os.getpid()}",
            password=generate_password_hash("x"),
            role="admin",
            is_active=True,
        )
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["employee_id"] = admin_id
        sess["user_id"] = admin_id
        sess["tenant_slug"] = TENANT

    r = client.get("/mobile-app/")
    assert r.status_code == 200, r.data[:500]
    assert "لوحة".encode("utf-8") in r.data or b"Feature" in r.data

    r = client.get("/mobile-app/flags")
    assert r.status_code == 200
    r = client.post(
        "/mobile-app/flags",
        data={"key": "ai_assistant_enabled", "enabled": "0"},
        follow_redirects=True,
    )
    assert r.status_code == 200

    r = client.get("/mobile-app/design")
    assert r.status_code == 200
    r = client.post(
        "/mobile-app/design",
        data={"app_name": "Finora Mobile", "gold_accent": "#D9A441"},
        follow_redirects=True,
    )
    assert r.status_code == 200

    r = client.get("/mobile-app/analytics")
    assert r.status_code == 200

    for path in ("/mobile-app/users", "/mobile-app/comments", "/mobile-app/rewards"):
        r = client.get(path)
        assert r.status_code == 200, path

    with app.app_context():
        g.tenant = None
        row = CoreTenant.query.filter_by(slug=TENANT).first()
        if row:
            db.session.delete(row)
            db.session.commit()
    _wipe(TENANT)
