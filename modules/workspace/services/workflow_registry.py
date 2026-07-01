from __future__ import annotations

from typing import Any, Dict, List

from modules.workspace.recipes.courier_settlement_recipe import COURIER_SETTLEMENT_RECIPE
from modules.workspace.recipes.mock_workspace_recipe import MOCK_WORKSPACE_RECIPE
from modules.workspace.recipes.purchase_invoice_recipe import PURCHASE_INVOICE_RECIPE
from modules.workspace.recipes.return_statement_recipe import RETURN_STATEMENT_RECIPE
from modules.workspace.recipes.unknown_document_recipe import UNKNOWN_DOCUMENT_RECIPE
from modules.workspace.services.workflow_errors import WorkflowInvalidTypeError

_RECIPES: Dict[str, Dict[str, Any]] = {
    "mock_workspace": MOCK_WORKSPACE_RECIPE,
    "unknown_document": UNKNOWN_DOCUMENT_RECIPE,
    "courier_settlement": COURIER_SETTLEMENT_RECIPE,
    "return_statement": RETURN_STATEMENT_RECIPE,
    "purchase_invoice": PURCHASE_INVOICE_RECIPE,
}


class WorkflowRegistry:
    @staticmethod
    def list_workflow_types() -> List[str]:
        return sorted(_RECIPES.keys())

    @staticmethod
    def list_available() -> List[Dict[str, str]]:
        return [
            {
                "workflow_type": key,
                "title": recipe.get("title", key),
                "description": recipe.get("description", ""),
            }
            for key, recipe in _RECIPES.items()
        ]

    @staticmethod
    def get_recipe(workflow_type: str) -> Dict[str, Any]:
        recipe = _RECIPES.get(workflow_type)
        if not recipe:
            raise WorkflowInvalidTypeError(f"نوع Workflow غير معروف: {workflow_type}")
        return recipe

    @staticmethod
    def get_step(recipe: Dict[str, Any], step_id: str) -> Dict[str, Any]:
        steps = recipe.get("steps") or {}
        step = steps.get(step_id)
        if not step:
            raise WorkflowInvalidTypeError(f"خطوة غير معروفة: {step_id}")
        return step
