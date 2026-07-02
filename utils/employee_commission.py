"""مبلغ عمولة الموظفين الثابت (على مستوى النظام)."""

from __future__ import annotations


def get_fixed_employee_commission_amount() -> int:
    from models.system_settings import SystemSettings

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    try:
        raw = flags.get("employee_commission_amount")
        if raw is None:
            raw = flags.get("employee_commission_percent", 0)
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def set_fixed_employee_commission_amount(amount: int) -> int:
    from models.system_settings import SystemSettings

    value = max(0, int(amount or 0))
    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags["employee_commission_amount"] = value
    settings.set_ui_flags(flags)
    return value


def get_employee_commission_amount(employee) -> int:
    """Per-order commission stored on the employee record."""
    if employee is None:
        return get_fixed_employee_commission_amount()
    try:
        return max(0, int(getattr(employee, "commission_percent", 0) or 0))
    except (TypeError, ValueError):
        return 0
