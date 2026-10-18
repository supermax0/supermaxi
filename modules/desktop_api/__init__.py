"""FINORA Management Desktop — JSON sign-in for the Electron management client.

The desktop client reuses the existing session-based FINORA endpoints (orders,
purchases, inventory). This module only adds the JSON equivalent of the web
login form plus a session/permissions probe; it holds no business logic.
"""

from __future__ import annotations

from flask import Flask


def init_desktop_api(app: Flask) -> None:
    from modules.desktop_api.routes import desktop_api_bp
    from modules.desktop_api import sync  # noqa: F401 — register synchronization routes
    from modules.desktop_api import snapshots  # noqa: F401 — register offline read snapshots
    from modules.desktop_api import stock  # noqa: F401 — register device inventory grants
    from modules.desktop_api import pos_sync  # noqa: F401 — atomic reserved POS checkout
    from modules.desktop_api import customers  # noqa: F401 — scoped customer workspace
    from modules.desktop_api import customer_schedules  # noqa: F401 — atomic schedule edits
    from modules.desktop_api import customer_plan_builder  # noqa: F401 — schedule creation and future repartition
    from modules.desktop_api import customer_debt_builder  # noqa: F401 — documented opening receivables
    from modules.desktop_api import customer_transactions  # noqa: F401 — collection history reads
    from modules.desktop_api import customer_statement  # noqa: F401 — documented debt origins and day-end balances
    from modules.desktop_api import inventory_activity  # noqa: F401 — recorded movements and quantity evidence
    from modules.desktop_api import shipping_center  # noqa: F401 — shipping & settlement center (FINORA's own manifests)
    from modules.desktop_api import shipping_center_finance  # noqa: F401 — statements, receipts, returns inspection
    from modules.desktop_api import shipping_center_insights  # noqa: F401 — missing orders and overdue follow-up
    from modules.desktop_api import branches  # noqa: F401 — branches & warehouses (multi-branch management)
    from modules.desktop_api import branch_cash  # noqa: F401 — branch cash transfers (request / approve / receive)
    from modules.desktop_api import permissions  # noqa: F401 — permissions administration
    from modules.stock_operations import routes as stock_operations_routes  # noqa: F401 — scoped native stock documents
    from modules.inventory_audit import routes as inventory_audit_routes  # noqa: F401 — persistent counting and review

    app.register_blueprint(desktop_api_bp)
