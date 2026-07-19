"""Phase 2 feed + engagement tests."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

TENANT = f"test_mobile_feed_{os.getpid()}"


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


def test_mobile_feed_engagement_flow():
    _wipe(TENANT)
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db
    from flask import g
    from models.employee import Employee
    from modules.mobile_app.models import MobileVideo
    from modules.mobile_app.api.v1.media import _media_mime
    from werkzeug.security import generate_password_hash

    app.config["TESTING"] = True
    app.config["MOBILE_OTP_DEBUG_RETURN_CODE"] = True
    assert _media_mime(Path("segment.ts")) == "video/mp2t"

    with app.app_context():
        g.tenant = TENANT
        init_tenant_db(TENANT)
        admin = Employee(
            name="Admin",
            username=f"admin_{os.getpid()}",
            password=generate_password_hash("x"),
            role="admin",
            is_active=True,
        )
        db.session.add(admin)
        db.session.flush()
        video = MobileVideo(
            creator_employee_id=admin.id,
            title="Test Video",
            description="desc",
            status="published",
            visibility="public",
            processing_status="ready",
            processing_progress=100,
            original_asset_url="/api/mobile/v1/media/videos/1/original",
            hls_master_url="/api/mobile/v1/media/videos/1/hls",
            published_at=datetime.utcnow(),
            allow_sharing=True,
            allow_saving=True,
            is_featured=True,
        )
        db.session.add(video)
        db.session.flush()
        regular_video = MobileVideo(
            creator_employee_id=admin.id,
            title="Regular Video",
            status="published",
            visibility="public",
            processing_status="ready",
            processing_progress=100,
            original_asset_url="/api/mobile/v1/media/videos/2/original",
            published_at=datetime.utcnow(),
        )
        db.session.add(regular_video)
        db.session.commit()
        staff_id = admin.id
        video_id = video.id

    client = app.test_client()

    # Watching and passive engagement work for a guest.
    r = client.get("/api/mobile/v1/feed", headers=_headers(TENANT))
    assert r.status_code == 200
    guest_item = next(v for v in r.get_json()["items"] if v["id"] == video_id)
    assert guest_item["playback_url"].endswith("/hls/master.m3u8")
    first_page = client.get(
        "/api/mobile/v1/feed?limit=1", headers=_headers(TENANT)
    ).get_json()
    assert first_page["items"][0]["id"] == video_id
    assert first_page["next_cursor"]
    second_page = client.get(
        f"/api/mobile/v1/feed?limit=1&cursor={first_page['next_cursor']}",
        headers=_headers(TENANT),
    ).get_json()
    assert [item["title"] for item in second_page["items"]] == ["Regular Video"]
    r = client.post(
        f"/api/mobile/v1/videos/{video_id}/view",
        headers=_headers(TENANT),
        json={"watch_ms": 900, "device_id": "guest-device"},
    )
    assert r.status_code == 200
    r = client.post(
        f"/api/mobile/v1/videos/{video_id}/share",
        headers=_headers(TENANT),
        json={"channel": "app"},
    )
    assert r.status_code == 200

    # Likes and saves are intentionally personal and still require a login.
    r = client.post(
        f"/api/mobile/v1/videos/{video_id}/like", headers=_headers(TENANT)
    )
    assert r.status_code == 401

    # OTP login
    r = client.post(
        "/api/mobile/v1/auth/request-otp",
        headers=_headers(TENANT),
        json={"phone": "07709998877"},
    )
    assert r.status_code == 200
    code = r.get_json()["debug_code"]
    r = client.post(
        "/api/mobile/v1/auth/verify-otp",
        headers=_headers(TENANT),
        json={
            "phone": "07709998877",
            "code": code,
            "device_id": "feed-device",
            "name": "User",
        },
    )
    assert r.status_code == 200
    access = r.get_json()["access_token"]

    # Feed
    r = client.get("/api/mobile/v1/feed", headers=_headers(TENANT, access))
    assert r.status_code == 200, r.get_data(as_text=True)
    items = r.get_json()["items"]
    assert len(items) >= 1
    assert items[0]["id"] == video_id

    # View / like / save / share
    r = client.post(
        f"/api/mobile/v1/videos/{video_id}/view",
        headers=_headers(TENANT, access),
        json={"watch_ms": 1500},
    )
    assert r.status_code == 200
    assert r.get_json()["views_count"] >= 1

    r = client.post(
        f"/api/mobile/v1/videos/{video_id}/like",
        headers=_headers(TENANT, access),
    )
    assert r.status_code == 200
    assert r.get_json()["liked"] is True
    assert r.get_json()["likes_count"] >= 1

    r = client.post(
        f"/api/mobile/v1/videos/{video_id}/save",
        headers=_headers(TENANT, access),
    )
    assert r.status_code == 200
    assert r.get_json()["saved"] is True

    r = client.post(
        f"/api/mobile/v1/videos/{video_id}/share",
        headers=_headers(TENANT, access),
        json={"channel": "whatsapp"},
    )
    assert r.status_code == 200
    assert r.get_json()["shares_count"] >= 1

    # Admin list with test staff header
    r = client.get(
        "/api/mobile/v1/admin/videos",
        headers=_headers(TENANT, staff_id=staff_id),
    )
    assert r.status_code == 200
    assert any(v["id"] == video_id for v in r.get_json()["items"])

    _wipe(TENANT)
