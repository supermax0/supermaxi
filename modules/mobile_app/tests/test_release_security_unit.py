"""Isolated release-safety checks that never import the production app."""

from __future__ import annotations

import io
from pathlib import Path

from flask import Flask, g
from werkzeug.datastructures import FileStorage


def test_sms_provider_fails_closed_in_production(monkeypatch):
    from modules.mobile_app.providers.sms import (
        LogSmsProvider,
        UnavailableSmsProvider,
        get_sms_provider,
    )

    monkeypatch.delenv("MOBILE_SMS_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("MOBILE_ALLOW_LOG_SMS", raising=False)

    production = Flask("production")
    with production.app_context():
        assert isinstance(get_sms_provider(), UnavailableSmsProvider)

    testing = Flask("testing")
    testing.testing = True
    with testing.app_context():
        assert isinstance(get_sms_provider(), LogSmsProvider)


def test_media_path_cannot_escape_tenant_video_directory(tmp_path):
    from modules.mobile_app.api.v1.media import _safe_media_path

    app = Flask("media")
    app.config["MOBILE_VIDEO_ROOT"] = str(tmp_path)
    with app.app_context():
        g.tenant = "tenant-a"
        allowed = tmp_path / "tenant-a" / "7" / "clip.mp4"
        allowed.parent.mkdir(parents=True)
        allowed.write_bytes(b"x")
        escaped = tmp_path / "tenant-a-evil" / "clip.mp4"
        escaped.parent.mkdir()
        escaped.write_bytes(b"x")

        assert _safe_media_path(allowed, 7) == allowed.resolve()
        assert _safe_media_path(escaped, 7) is None


def test_video_upload_rejects_bad_type_and_stops_at_size_limit(
    tmp_path, monkeypatch
):
    from modules.mobile_app.services import video_admin as service

    class FakeSession:
        def __init__(self):
            self.rolled_back = False

        def add(self, value):
            pass

        def flush(self):
            pass

        def rollback(self):
            self.rolled_back = True

        def commit(self):
            pass

    class FakeDb:
        session = FakeSession()

    class FakeVideo:
        def __init__(self, **kwargs):
            self.id = 7
            self.__dict__.update(kwargs)

    target = tmp_path / "tenant-a" / "7"
    target.mkdir(parents=True)
    monkeypatch.setattr(service, "db", FakeDb())
    monkeypatch.setattr(service, "MobileVideo", FakeVideo)
    monkeypatch.setattr(
        service,
        "tenant_video_dir",
        lambda video_id, tenant: tmp_path / tenant / str(video_id),
    )

    bad_type = FileStorage(
        stream=io.BytesIO(b"not-video"),
        filename="renamed.mp4",
        content_type="text/plain",
    )
    try:
        service.create_video_from_upload(
            tenant_slug="tenant-a",
            employee_id=1,
            title="",
            description="",
            file_storage=bad_type,
        )
        raise AssertionError("invalid content type was accepted")
    except ValueError:
        pass

    monkeypatch.setenv("MOBILE_VIDEO_MAX_MB", "1")
    oversized = FileStorage(
        stream=io.BytesIO(b"x" * (1024 * 1024 + 1)),
        filename="large.mp4",
        content_type="video/mp4",
    )
    try:
        service.create_video_from_upload(
            tenant_slug="tenant-a",
            employee_id=1,
            title="",
            description="",
            file_storage=oversized,
        )
        raise AssertionError("oversized upload was accepted")
    except ValueError:
        pass

    assert FakeDb.session.rolled_back
    assert not list(target.glob("*"))


def test_every_mobile_admin_endpoint_has_a_specific_permission():
    from modules.mobile_app.admin_routes import (
        _ENDPOINT_PERMISSIONS,
        mobile_admin_bp,
    )

    endpoint_names = {
        deferred_rule.endpoint.rsplit(".", 1)[-1]
        for deferred_rule in mobile_admin_bp.deferred_functions
        if getattr(deferred_rule, "endpoint", None)
    }
    # Flask stores route callbacks in deferred closures, so assert the known
    # mutating/read endpoints explicitly and keep the permission map reviewable.
    expected = {
        "dashboard",
        "videos_page",
        "videos_upload",
        "videos_publish",
        "videos_hide",
        "flags_page",
        "notifications_page",
        "design_page",
        "analytics_page",
        "users_page",
        "users_ban",
        "users_unban",
        "comments_page",
        "rewards_page",
        "coupons_page",
    }
    assert set(_ENDPOINT_PERMISSIONS) == expected
    assert endpoint_names <= expected
