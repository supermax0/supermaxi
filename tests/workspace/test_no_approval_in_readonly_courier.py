"""Read-only courier workflow must never require approval."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _iter_window_types(step):
    for spec in (step.get("open_windows") or []) + (step.get("ensure_windows") or []):
        yield spec.get("type")


def test_courier_recipe_has_no_approval():
    from modules.workspace.recipes.courier_settlement_recipe import (
        COURIER_SETTLEMENT_RECIPE,
    )

    steps = COURIER_SETTLEMENT_RECIPE["steps"]
    for step_id, step in steps.items():
        assert not step.get("requires_approval"), f"{step_id} must not require approval"
        assert "approval_panel" not in list(
            _iter_window_types(step)
        ), f"{step_id} must not open approval_panel"

    final = steps["complete"]
    assert final.get("status_after_step") == "completed"
    print("test_courier_recipe_has_no_approval ok")


def test_return_and_purchase_have_no_approval_panel():
    from modules.workspace.recipes.return_statement_recipe import RETURN_STATEMENT_RECIPE
    from modules.workspace.recipes.purchase_invoice_recipe import PURCHASE_INVOICE_RECIPE

    for recipe in (RETURN_STATEMENT_RECIPE, PURCHASE_INVOICE_RECIPE):
        for step_id, step in recipe["steps"].items():
            assert "approval_panel" not in list(
                _iter_window_types(step)
            ), f"{recipe['workflow_type']}.{step_id} must not open approval_panel"
    print("test_return_and_purchase_have_no_approval_panel ok")


if __name__ == "__main__":
    test_courier_recipe_has_no_approval()
    test_return_and_purchase_have_no_approval_panel()
    print("all no-approval readonly tests passed")
