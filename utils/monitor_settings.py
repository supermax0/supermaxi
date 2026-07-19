"""إعدادات عتبات مراقب مالي/تشغيلي."""
from __future__ import annotations

from models.system_settings import SystemSettings

MONITORS_HUB_URL = "/reports/monitors"

DEFAULT_MONITOR_SETTINGS = {
    "overdue_warning_days": 7,
    "overdue_critical_days": 10,
    "shipping_stuck_days": 5,
    "shipping_stuck_alert_min": 3,
    "pending_backlog_alert_min": 18,
    "paid_sales_loss_threshold": 500_000,
    "auto_refresh_sec": 300,
    "performance_min_orders": 5,
    "performance_min_sales": 0,
}


def get_monitor_settings(settings: SystemSettings | None = None) -> dict:
    settings = settings or SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    raw = flags.get("monitor_watchdog") or {}
    if not isinstance(raw, dict):
        raw = {}
    config = {**DEFAULT_MONITOR_SETTINGS, **raw}
    for key in (
        "overdue_warning_days",
        "overdue_critical_days",
        "shipping_stuck_days",
        "shipping_stuck_alert_min",
        "pending_backlog_alert_min",
        "paid_sales_loss_threshold",
        "auto_refresh_sec",
        "performance_min_orders",
        "performance_min_sales",
    ):
        try:
            config[key] = max(0, int(config.get(key) or DEFAULT_MONITOR_SETTINGS[key]))
        except (TypeError, ValueError):
            config[key] = DEFAULT_MONITOR_SETTINGS[key]
    if config["overdue_critical_days"] < config["overdue_warning_days"]:
        config["overdue_critical_days"] = config["overdue_warning_days"]
    return config


def save_monitor_settings(data: dict, settings: SystemSettings | None = None) -> dict:
    from extensions import db

    settings = settings or SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    current = get_monitor_settings(settings)
    merged = {**current, **(data or {})}
    for key in DEFAULT_MONITOR_SETTINGS:
        if key in merged:
            try:
                merged[key] = max(0, int(merged[key]))
            except (TypeError, ValueError):
                merged[key] = DEFAULT_MONITOR_SETTINGS[key]
    if merged["overdue_critical_days"] < merged["overdue_warning_days"]:
        merged["overdue_critical_days"] = merged["overdue_warning_days"]
    flags["monitor_watchdog"] = merged
    settings.set_ui_flags(flags)
    db.session.commit()
    return get_monitor_settings(settings)
