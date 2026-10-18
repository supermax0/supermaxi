from unittest.mock import patch

from flask import Flask


def test_workspace_request_syncs_shared_invoice_schema_even_when_workspace_is_ready():
    import modules.workspace as workspace_module

    app = Flask(__name__)
    app.secret_key = "workspace-schema-test"
    tenant_slug = "workspace_shared_schema_sync"
    workspace_module._tenant_context_ready.add(tenant_slug)
    try:
        with app.test_request_context("/workspace/api/sessions"):
            from flask import session

            session["tenant_slug"] = tenant_slug
            with patch(
                "modules.wholesale.schema_guard.ensure_wholesale_schema"
            ) as ensure_shared_schema:
                workspace_module._ensure_workspace_request_context()

            ensure_shared_schema.assert_called_once_with()
    finally:
        workspace_module._tenant_context_ready.discard(tenant_slug)
