"""نسبة عمولة الموظفين الثابتة (على مستوى النظام)."""

from __future__ import annotations


def get_fixed_employee_commission_percent() -> int:
    from models.system_settings import SystemSettings

    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    try:
        return max(0, min(100, int(flags.get("employee_commission_percent", 0) or 0)))
    except (TypeError, ValueError):
        return 0


def set_fixed_employee_commission_percent(percent: int) -> int:
    from models.system_settings import SystemSettings

    value = max(0, min(100, int(percent or 0)))
    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags["employee_commission_percent"] = value
    settings.set_ui_flags(flags)
    return value
