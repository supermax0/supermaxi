"""Production polish: permissions seed, saved videos, coupons admin."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

TENANT = f"test_mobile_prod_{os.getpid()}"


def _wipe(tenant: str) -> None:
    db_file = ROOT / "tenants" / f"{tenant}.db"
    try:
        if db_file.exists():
            db_file.unlink()
    except OSError:
        pass


def _headers(tenant: str, token: str | None = None) -> dict:
    h = {"X-Tenant-Slug": tenant, "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def test_permissions_saved_videos_coupons_admin():
    _wipe(TENANT)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.core.tenant import Tenant as CoreTenant
    from models.employee import Employee
    from models.role import Permission
    from modules.mobile_app.models import MobileVideo, MobileVideoSave
    from modules.mobile_app.permissions import MOBILE_APP_PERMISSIONS
    from werkzeug.security import generate_password_hash

    from datetime import datetime, timedelta

    app.config["TESTING"] = True
    app.config["MOBILE_OTP_DEBUG_RETURN_CODE"] = True

    with app.app_context():
        g.tenant = None
        existing = CoreTenant.query.filter_by(slug=TENANT).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
        core = CoreTenant(
            name="Mobile Prod Polish",
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
        from modules.mobile_app.schema_guard import ensure_mobile_app_schema

        ensure_mobile_app_schema()
        names = {p.name for p in Permission.query.all()}
        for perm_name, _ in MOBILE_APP_PERMISSIONS:
            assert perm_name in names, perm_name

        admin = Employee(
            name="Admin",
            username=f"mprod_{os.getpid()}",
            password=generate_password_hash("x"),
            role="admin",
            is_active=True,
        )
        db.session.add(admin)
        video = MobileVideo(
            title="محفوظ",
            status="published",
            processing_status="ready",
            processing_progress=100,
            visibility="public",
            published_at=datetime.utcnow(),
        )
        db.session.add(video)
        db.session.commit()
        admin_id = admin.id
        video_id = video.id

    client = app.test_client()
    r = client.post(
        "/api/mobile/v1/auth/request-otp",
        headers=_headers(TENANT),
        json={"phone": "07705554433"},
    )
    assert r.status_code == 200
    code = r.get_json()["debug_code"]
    r = client.post(
        "/api/mobile/v1/auth/verify-otp",
        headers=_headers(TENANT),
        json={
            "phone": "07705554433",
            "code": code,
            "device_id": "prod-device",
            "name": "مستخدم",
        },
    )
    assert r.status_code == 200
    token = r.get_json()["access_token"]
    user_id = r.get_json()["user"]["id"]

    with app.app_context():
        g.tenant = TENANT
        db.session.add(MobileVideoSave(user_id=user_id, video_id=video_id))
        db.session.commit()

    r = client.get("/api/mobile/v1/profile/saved-videos", headers=_headers(TENANT, token))
    assert r.status_code == 200
    items = r.get_json()["items"]
    assert any(v.get("id") == video_id for v in items)

    with client.session_transaction() as sess:
        sess["employee_id"] = admin_id
        sess["user_id"] = admin_id
        sess["tenant_slug"] = TENANT

    r = client.get("/mobile-app/coupons")
    assert r.status_code == 200
    r = client.post(
        "/mobile-app/coupons",
        data={
            "action": "create",
            "code": "SAVE10",
            "name": "خصم 10",
            "discount_type": "percent",
            "value": "10",
            "min_subtotal": "0",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert b"SAVE10" in r.data or "SAVE10".encode() in r.data

    with app.app_context():
        g.tenant = None
        row = CoreTenant.query.filter_by(slug=TENANT).first()
        if row:
            db.session.delete(row)
            db.session.commit()
    _wipe(TENANT)
