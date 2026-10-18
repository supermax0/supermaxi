"""Default dashboard card visibility for new tenants."""

from __future__ import annotations

from typing import Dict, Tuple


DASHBOARD_UI_DEFAULTS_VERSION = 2

# Dashboard metric cards are hidden until the tenant enables the ones they need.
DEFAULT_DASHBOARD_UI_FLAGS: Dict[str, object] = {
    "dashboard_ui_defaults_version": DASHBOARD_UI_DEFAULTS_VERSION,
    # New companies use isolated branches unless the super administrator
    # explicitly keeps them on the legacy shared-data mode before migration.
    "independent_branches_enabled": True,
    "defer_pending_order_stock": True,
    "show_dash_cash_balance": False,
    "show_dash_period_profit": False,
    "show_dash_total_sales": False,
    "show_dash_cash_sales": False,
    "show_dash_credit_sales": False,
    "show_dash_inventory": False,
    "show_dash_liabilities": False,
    "show_dash_agent_dues": False,
    "show_dash_agent_pending": False,
    "show_dash_expenses": False,
}


def get_default_dashboard_ui_flags() -> Dict[str, object]:
    return dict(DEFAULT_DASHBOARD_UI_FLAGS)


def migrate_dashboard_ui_defaults(flags: dict) -> Tuple[dict, bool]:
    """Apply changed defaults once without overriding later user choices."""
    migrated = dict(flags or {})
    try:
        current_version = int(migrated.get("dashboard_ui_defaults_version", 1))
    except (TypeError, ValueError):
        current_version = 1

    if current_version >= DASHBOARD_UI_DEFAULTS_VERSION:
        return migrated, False

    migrated["show_dash_inventory"] = False
    migrated["show_dash_agent_pending"] = False
    migrated["dashboard_ui_defaults_version"] = DASHBOARD_UI_DEFAULTS_VERSION
    return migrated, True
