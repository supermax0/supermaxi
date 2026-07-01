"""Smoke tests for workspace routes."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_workspace_blueprint_registered():
    from app import app

    names = [bp.name for bp in app.blueprints.values()]
    assert "workspace" in names
    print("workspace blueprint registered ok")


def test_workspace_module_imports():
    from modules.workspace import workspace_bp, init_workspace
    from modules.workspace.services.session_service import SessionService
    from modules.workspace.services.event_bus import emit_event

    assert workspace_bp is not None
    assert SessionService is not None
    assert emit_event is not None
    print("workspace imports ok")


if __name__ == "__main__":
    test_workspace_module_imports()
    test_workspace_blueprint_registered()
    print("workspace route tests passed")
