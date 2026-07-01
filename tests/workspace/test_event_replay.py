"""Event replay tests — Phase 3."""
import sys
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_replay_after_id():
    from app import app

    tenant = "test_event_replay"
    with app.app_context():
        from flask import g

        g.tenant = tenant
        from extensions_tenant import init_tenant_db
        from modules.workspace.services.schema_guard import ensure_workspace_schema
        from modules.workspace.services import event_bus
        from modules.workspace.services.session_service import SessionService

        init_tenant_db(tenant)
        ensure_workspace_schema()

        ws = SessionService.create_session(user_id=1, tenant_slug=tenant)
        e1 = event_bus.emit_event(ws.id, "report.appended", {"line": "أول"})
        e2 = event_bus.emit_event(ws.id, "report.appended", {"line": "ثاني"})

        all_ev = event_bus.replay_events(ws.id, 0)
        assert len(all_ev) >= 2

        after = event_bus.replay_events(ws.id, e1.id)
        assert len(after) >= 1
        assert all(ev.id > e1.id for ev in after)

        none_new = event_bus.replay_events(ws.id, e2.id)
        assert len(none_new) == 0
        print("test_replay_after_id ok")


def test_stream_endpoint_replays_with_context():
    from app import app

    tenant = "test_event_stream_endpoint"
    with app.app_context():
        from flask import g

        from extensions import db
        g.tenant = tenant
        from extensions_tenant import init_tenant_db
        from models.core.tenant import Tenant as CoreTenant
        from models.tenant import Tenant as TenantProfile
        from modules.workspace.services.schema_guard import ensure_workspace_schema
        from modules.workspace.services import event_bus
        from modules.workspace.services.session_service import SessionService

        g.tenant = None
        core = CoreTenant.query.filter_by(slug=tenant).first()
        if not core:
            core = CoreTenant(
                name="Event Stream Tenant",
                slug=tenant,
                db_path=f"tenants/{tenant}.db",
                is_active=True,
                subscription_end_date=datetime.utcnow() + timedelta(days=30),
            )
            db.session.add(core)
            db.session.commit()

        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_workspace_schema()
        if not TenantProfile.query.first():
            db.session.add(
                TenantProfile(
                    name="Event Stream Tenant",
                    plan_key="enterprise",
                    plan_name="Enterprise",
                    is_active=True,
                )
            )
            db.session.commit()

        ws = SessionService.create_session(user_id=44, tenant_slug=tenant)
        event_bus.emit_event(ws.id, "report.appended", {"line": "stream ok"})
        session_id = ws.id

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 44
            sess["tenant_slug"] = tenant
            sess["plan_key"] = "enterprise"

        resp = client.get(
            f"/workspace/api/sessions/{session_id}/stream?since=0",
            buffered=False,
        )
        assert resp.status_code == 200
        first = next(resp.response).decode("utf-8")
        assert "event:" in first
        assert "data:" in first
        resp.close()
        print("test_stream_endpoint_replays_with_context ok")


if __name__ == "__main__":
    test_replay_after_id()
    test_stream_endpoint_replays_with_context()
    print("event replay tests passed")
