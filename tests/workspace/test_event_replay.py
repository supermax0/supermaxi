"""Event replay tests — Phase 3."""
import sys
from pathlib import Path

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


if __name__ == "__main__":
    test_replay_after_id()
    print("event replay tests passed")
