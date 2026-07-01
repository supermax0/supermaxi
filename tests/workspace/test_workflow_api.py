"""Workflow API smoke tests."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_workflow_blueprint_registered():
    from app import app

    names = [bp.name for bp in app.blueprints.values()]
    assert "workspace" in names
    print("workflow blueprint ok")


def test_workflow_api_imports():
    from modules.workspace.api.workflow_api import workflow_api_bp
    from modules.workspace.services.workflow_engine import WorkflowEngine

    assert workflow_api_bp is not None
    assert WorkflowEngine is not None
    print("workflow api imports ok")


if __name__ == "__main__":
    test_workflow_api_imports()
    test_workflow_blueprint_registered()
    print("workflow api tests passed")
