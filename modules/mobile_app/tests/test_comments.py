"""Phase 3 comments + moderation tests."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

TENANT = f"test_mobile_comments_{os.getpid()}"


def _wipe(tenant: str) -> None:
    db_file = ROOT / "tenants" / f"{tenant}.db"
    try:
        if db_file.exists():
            db_file.unlink()
    except OSError:
        pass


def _headers(tenant: str, token: str | None = None, staff_id: int | None = None) -> dict:
    h = {"X-Tenant-Slug": tenant, "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if staff_id is not None:
        h["X-Test-Staff-Id"] = str(staff_id)
    return h


def test_mobile_comments_replies_likes_and_admin_moderation():
    _wipe(TENANT)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.employee import Employee
    from modules.mobile_app.models import MobileModerationRule, MobileVideo
    from werkzeug.security import generate_password_hash

    app.config["TESTING"] = True
    app.config["MOBILE_OTP_DEBUG_RETURN_CODE"] = True

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        admin = Employee(
            name="Admin",
            username=f"cadmin_{os.getpid()}",
            password=generate_password_hash("x"),
            role="admin",
            is_active=True,
        )
        db.session.add(admin)
        db.session.flush()
        video = MobileVideo(
            creator_employee_id=admin.id,
            title="Clip",
            status="published",
            visibility="public",
            processing_status="ready",
            processing_progress=100,
            published_at=datetime.utcnow(),
            allow_comments=True,
        )
        db.session.add(video)
        db.session.add(
            MobileModerationRule(
                rule_type="blocked_word",
                pattern="كلمةسيئة",
                action="reject",
                is_active=True,
            )
        )
        db.session.commit()
        staff_id = admin.id
        video_id = video.id

    client = app.test_client()

    r = client.post(
        "/api/mobile/v1/auth/request-otp",
        headers=_headers(TENANT),
        json={"phone": "07701112233"},
    )
    assert r.status_code == 200
    code = r.get_json()["debug_code"]
    r = client.post(
        "/api/mobile/v1/auth/verify-otp",
        headers=_headers(TENANT),
        json={
            "phone": "07701112233",
            "code": code,
            "device_id": "c-device",
            "name": "Commenter",
        },
    )
    assert r.status_code == 200
    access = r.get_json()["access_token"]

    # Reject moderated word
    r = client.post(
        f"/api/mobile/v1/videos/{video_id}/comments",
        headers=_headers(TENANT, access),
        json={"body": "هذا كلمةسيئة"},
    )
    assert r.status_code == 400
    assert r.get_json()["code"] == "moderation_rejected"

    # Create root comment
    r = client.post(
        f"/api/mobile/v1/videos/{video_id}/comments",
        headers=_headers(TENANT, access),
        json={"body": "فيديو رائع"},
    )
    assert r.status_code == 201, r.get_data(as_text=True)
    comment_id = r.get_json()["comment"]["id"]

    # Reply
    r = client.post(
        f"/api/mobile/v1/comments/{comment_id}/replies",
        headers=_headers(TENANT, access),
        json={"body": "أتفق معك"},
    )
    assert r.status_code == 201
    reply_id = r.get_json()["comment"]["id"]

    # Like comment
    r = client.post(
        f"/api/mobile/v1/comments/{comment_id}/like",
        headers=_headers(TENANT, access),
    )
    assert r.status_code == 200
    assert r.get_json()["liked"] is True

    # List
    r = client.get(
        f"/api/mobile/v1/videos/{video_id}/comments",
        headers=_headers(TENANT, access),
    )
    assert r.status_code == 200
    items = r.get_json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == comment_id
    assert items[0]["liked_by_me"] is True
    assert len(items[0]["replies"]) == 1
    assert items[0]["replies"][0]["id"] == reply_id

    # Report
    r = client.post(
        f"/api/mobile/v1/comments/{reply_id}/report",
        headers=_headers(TENANT, access),
        json={"reason": "spam"},
    )
    assert r.status_code == 201

    # Admin pin + company reply + hide
    r = client.post(
        f"/api/mobile/v1/admin/comments/{comment_id}/pin",
        headers=_headers(TENANT, staff_id=staff_id),
        json={"pinned": True},
    )
    assert r.status_code == 200
    assert r.get_json()["comment"]["is_pinned"] is True

    r = client.post(
        "/api/mobile/v1/admin/comments/reply",
        headers=_headers(TENANT, staff_id=staff_id),
        json={"video_id": video_id, "parent_id": comment_id, "body": "شكراً لتواصلكم"},
    )
    assert r.status_code == 201
    assert r.get_json()["comment"]["is_company_reply"] is True

    r = client.post(
        f"/api/mobile/v1/admin/comments/{reply_id}/hide",
        headers=_headers(TENANT, staff_id=staff_id),
    )
    assert r.status_code == 200
    assert r.get_json()["comment"]["status"] == "hidden"

    # Delete own root
    r = client.delete(
        f"/api/mobile/v1/comments/{comment_id}",
        headers=_headers(TENANT, access),
    )
    assert r.status_code == 200

    _wipe(TENANT)
