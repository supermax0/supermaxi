"""Tenant feature management: gating, expiry, audit, isolation, Super Admin only."""
from datetime import datetime, timedelta

import pytest
from flask import Flask

from extensions import db


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="feature-tests",
    )
    db.init_app(app)

    import models  # noqa: F401  (registers the full FK graph, as other suites do)
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from models.core.feature import FeatureAuditLog, TenantFeature  # noqa: F401
    from models.core.global_setting import GlobalSetting  # noqa: F401
    from models.core.super_admin import SuperAdmin
    from models.core.tenant import Tenant
    from routes.features_api import features_api_bp
    from routes.superadmin_features import superadmin_features_bp

    app.register_blueprint(superadmin_features_bp)
    app.register_blueprint(features_api_bp)

    with app.app_context():
        db.create_all()
        admin = SuperAdmin(username="root")
        admin.set_password("test-only-secret")
        db.session.add(admin)
        for slug in ("clinic-a", "clinic-b", "clinic-c"):
            db.session.add(Tenant(name=slug.upper(), slug=slug, db_path=f"{slug}.db", is_active=True))
        db.session.commit()
        from services import feature_service

        feature_service.invalidate_cache()
        yield app
        db.session.remove()
        db.drop_all()


def _super(client):
    with client.session_transaction() as sess:
        sess["is_superadmin"] = True
        sess["superadmin_id"] = 1


def _tenant_user(client, slug, *, admin=True):
    with client.session_transaction() as sess:
        sess["user_id"] = 7
        sess["tenant_slug"] = slug
        sess["is_admin"] = admin


def _enable(client, slug, **body):
    return client.patch(f"/superadmin/features/tenants/{slug}/clinic_ai_tutor", json={"enabled": True, **body})


def _tomorrow():
    return (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")


def test_default_is_disabled_without_record(app):
    from models.core.feature import TenantFeature
    from services import feature_service as fs

    assert TenantFeature.query.count() == 0
    status = fs.get_status("clinic-a", fs.AI_TUTOR)
    assert status["state"] == "disabled" and status["effective"] is False
    assert fs.is_enabled_for_slug("clinic-a", fs.AI_TUTOR) is False
    assert fs.is_enabled_for_slug("missing", fs.AI_TUTOR) is False
    assert fs.is_enabled(None, fs.AI_TUTOR) is False


def test_disabled_tenant_api_rejected_with_feature_not_enabled(app):
    client = app.test_client()
    _tenant_user(client, "clinic-a")
    res = client.get("/api/clinic/ai-tutor/status")
    assert res.status_code == 403
    assert res.get_json() == {"error": "FEATURE_NOT_ENABLED", "feature": "clinic_ai_tutor"}
    assert client.get("/api/features/me").get_json()["features"] == {"clinic_ai_tutor": False}


def test_unauthenticated_tenant_api_rejected(app):
    assert app.test_client().get("/api/clinic/ai-tutor/status").status_code == 401


def test_tenant_admin_cannot_enable_feature(app):
    client = app.test_client()
    _tenant_user(client, "clinic-a", admin=True)
    res = _enable(client, "clinic-a")
    assert res.status_code == 403
    assert client.put("/superadmin/features/clinic_ai_tutor/global", json={"enabled": False}).status_code == 403
    assert client.post("/superadmin/features/clinic_ai_tutor/bulk",
                       json={"slugs": ["clinic-a"], "enabled": True}).status_code == 403
    from services import feature_service as fs

    assert fs.is_enabled_for_slug("clinic-a", fs.AI_TUTOR) is False


def test_anonymous_cannot_use_admin_api(app):
    assert _enable(app.test_client(), "clinic-a").status_code == 403


def test_super_admin_enable_and_disable_with_isolation(app):
    admin, a, b = app.test_client(), app.test_client(), app.test_client()
    _super(admin)
    _tenant_user(a, "clinic-a")
    _tenant_user(b, "clinic-b")

    assert _enable(admin, "clinic-a").status_code == 200
    ok = a.get("/api/clinic/ai-tutor/status")
    assert ok.status_code == 200 and ok.get_json()["enabled"] is True
    assert a.get("/api/features/me").get_json()["features"]["clinic_ai_tutor"] is True
    assert b.get("/api/clinic/ai-tutor/status").status_code == 403

    res = admin.patch("/superadmin/features/tenants/clinic-a/clinic_ai_tutor", json={"enabled": False})
    assert res.status_code == 200
    assert a.get("/api/clinic/ai-tutor/status").status_code == 403  # cache invalidated immediately
    assert b.get("/api/clinic/ai-tutor/status").status_code == 403


def test_expiry_in_past_rejected_and_expired_feature_stops(app):
    from models.core.feature import TenantFeature
    from services import feature_service as fs

    admin, a = app.test_client(), app.test_client()
    _super(admin)
    _tenant_user(a, "clinic-a")

    past = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert _enable(admin, "clinic-a", expires_at=past).status_code == 400
    assert TenantFeature.query.count() == 0

    assert _enable(admin, "clinic-a", expires_at=_tomorrow()).status_code == 200
    assert a.get("/api/clinic/ai-tutor/status").status_code == 200

    row = TenantFeature.query.one()
    row.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    fs.invalidate_cache()
    assert a.get("/api/clinic/ai-tutor/status").status_code == 403
    assert fs.get_status("clinic-a", fs.AI_TUTOR)["state"] == "expired"
    assert [r["slug"] for r in fs.list_overview(fs.AI_TUTOR, state="expired")] == ["clinic-a"]

    # Re-enabling an expired row needs an explicit new expiry (or permanent).
    assert admin.patch("/superadmin/features/tenants/clinic-a/clinic_ai_tutor",
                       json={"enabled": True}).status_code == 400
    assert _enable(admin, "clinic-a", expires_at=None).status_code == 200
    assert a.get("/api/clinic/ai-tutor/status").status_code == 200


def test_global_kill_switch(app):
    admin, a = app.test_client(), app.test_client()
    _super(admin)
    _tenant_user(a, "clinic-a")
    _enable(admin, "clinic-a")
    assert a.get("/api/clinic/ai-tutor/status").status_code == 200

    assert admin.put("/superadmin/features/clinic_ai_tutor/global", json={"enabled": False}).status_code == 200
    assert a.get("/api/clinic/ai-tutor/status").status_code == 403
    assert admin.put("/superadmin/features/clinic_ai_tutor/global", json={"enabled": True}).status_code == 200
    assert a.get("/api/clinic/ai-tutor/status").status_code == 200


def test_audit_log_records_every_change(app):
    admin = app.test_client()
    _super(admin)
    _enable(admin, "clinic-a", expires_at=_tomorrow())
    admin.patch("/superadmin/features/tenants/clinic-a/clinic_ai_tutor", json={"expires_at": None})
    admin.patch("/superadmin/features/tenants/clinic-a/clinic_ai_tutor",
                json={"configuration": {"allow_ai_chat": False}})
    admin.patch("/superadmin/features/tenants/clinic-a/clinic_ai_tutor", json={"enabled": False})
    admin.put("/superadmin/features/clinic_ai_tutor/global", json={"enabled": False})

    logs = admin.get("/superadmin/features/clinic_ai_tutor/audit").get_json()["logs"]
    actions = [row["action"] for row in logs]
    assert sorted(actions) == sorted(
        ["ENABLED", "EXPIRY_CHANGED", "EXPIRY_CHANGED", "CONFIG_CHANGED", "DISABLED", "GLOBAL_DISABLED"]
    )
    assert all(row["performed_by"] == "root#1" for row in logs)
    assert next(r for r in logs if r["action"] == "GLOBAL_DISABLED")["tenant_id"] is None
    scoped = admin.get("/superadmin/features/clinic_ai_tutor/audit?slug=clinic-b").get_json()["logs"]
    assert scoped == []

    # Idempotent repeat writes nothing.
    admin.patch("/superadmin/features/tenants/clinic-a/clinic_ai_tutor", json={"enabled": False})
    assert len(admin.get("/superadmin/features/clinic_ai_tutor/audit").get_json()["logs"]) == len(logs)


def test_configuration_validation(app):
    admin = app.test_client()
    _super(admin)
    for bad in ({"nope": True}, {"allow_ai_chat": "yes"}, ["x"]):
        res = admin.patch("/superadmin/features/tenants/clinic-a/clinic_ai_tutor",
                          json={"enabled": True, "configuration": bad})
        assert res.status_code == 400
    from models.core.feature import TenantFeature

    assert TenantFeature.query.count() == 0  # failed validation rolled back the enable too


def test_unknown_feature_and_tenant(app):
    admin = app.test_client()
    _super(admin)
    assert admin.patch("/superadmin/features/tenants/clinic-a/other_feature", json={"enabled": True}).status_code == 404
    assert admin.patch("/superadmin/features/tenants/ghost/clinic_ai_tutor", json={"enabled": True}).status_code == 404
    assert admin.patch("/superadmin/features/tenants/clinic-a/clinic_ai_tutor",
                       json={"enabled": "true"}).status_code == 400


def test_bulk_enable_is_atomic_and_filters_work(app):
    admin = app.test_client()
    _super(admin)
    bad = admin.post("/superadmin/features/clinic_ai_tutor/bulk",
                     json={"slugs": ["clinic-a", "ghost"], "enabled": True})
    assert bad.status_code == 404
    from models.core.feature import TenantFeature

    assert TenantFeature.query.count() == 0

    ok = admin.post("/superadmin/features/clinic_ai_tutor/bulk",
                    json={"slugs": ["clinic-a", "clinic-c"], "enabled": True, "expires_at": _tomorrow()})
    assert ok.status_code == 200 and ok.get_json()["count"] == 2

    def names(**params):
        query = "&".join(f"{k}={v}" for k, v in params.items())
        res = admin.get(f"/superadmin/features/clinic_ai_tutor/overview?{query}")
        return sorted(row["slug"] for row in res.get_json()["tenants"])

    assert names(state="enabled") == ["clinic-a", "clinic-c"]
    assert names(state="disabled") == ["clinic-b"]
    assert names(q="clinic-b") == ["clinic-b"]
    assert names() == ["clinic-a", "clinic-b", "clinic-c"]
    assert admin.get("/superadmin/features/clinic_ai_tutor/overview?state=bogus").status_code == 400


def test_templates_helper_fails_closed(app):
    from flask import render_template_string

    with app.test_request_context():
        from flask import session

        assert render_template_string("{{ feature_enabled('clinic_ai_tutor') }}") == "False"
        session["user_id"], session["tenant_slug"] = 1, "clinic-a"
        assert render_template_string("{{ feature_enabled('clinic_ai_tutor') }}") == "False"
