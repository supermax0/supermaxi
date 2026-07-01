"""Courier workflow integration — Phase 5."""
import io
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _setup(tenant="test_courier_wf"):
    from app import app

    with app.app_context():
        from flask import g
        from extensions_tenant import init_tenant_db
        from modules.workspace.services.schema_guard import ensure_workspace_schema

        g.tenant = tenant
        init_tenant_db(tenant)
        ensure_workspace_schema()
    return app, tenant


def test_courier_recipe_has_readonly_handler():
    from modules.workspace.services.workflow_registry import WorkflowRegistry

    recipe = WorkflowRegistry.get_recipe("courier_settlement")
    step = recipe["steps"]["run_readonly_courier_analysis"]
    assert step.get("handler") == "courier_analysis.run_readonly"
    print("test_courier_recipe_has_readonly_handler ok")


if __name__ == "__main__":
    test_courier_recipe_has_readonly_handler()
    print("Courier workflow tests passed.")
