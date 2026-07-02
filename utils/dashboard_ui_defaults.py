"""Default dashboard card visibility for new tenants."""

from __future__ import annotations

from typing import Dict

# Most cards off; only agent pending reports queue on by default.
DEFAULT_DASHBOARD_UI_FLAGS: Dict[str, bool] = {
    "show_dash_cash_balance": False,
    "show_dash_period_profit": False,
    "show_dash_total_sales": False,
    "show_dash_cash_sales": False,
    "show_dash_credit_sales": False,
    "show_dash_inventory": False,
    "show_dash_liabilities": False,
    "show_dash_agent_dues": False,
    "show_dash_agent_pending": True,
    "show_dash_expenses": False,
}


def get_default_dashboard_ui_flags() -> Dict[str, bool]:
    return dict(DEFAULT_DASHBOARD_UI_FLAGS)
