"""Automatic reminders for weak employee performance."""
from __future__ import annotations

from datetime import datetime, timedelta
from string import Formatter

from extensions import db
from models.employee import Employee
from models.message import Message
from models.system_settings import SystemSettings


DEFAULT_WEAK_EMPLOYEE_MESSAGE = (
    "\u0645\u0631\u062d\u0628\u0627 {employee_name}\u060c "
    "\u0646\u062d\u062a\u0627\u062c \u0646\u0631\u0627\u062c\u0639 \u0623\u062f\u0627\u0621\u0643 "
    "\u062e\u0644\u0627\u0644 \u0622\u062e\u0631 {period_days} \u064a\u0648\u0645. "
    "\u0639\u062f\u062f \u0637\u0644\u0628\u0627\u062a\u0643 {orders_count} "
    "\u0648\u0645\u0628\u064a\u0639\u0627\u062a\u0643 {sales_display}. "
    "\u064a\u0631\u062c\u0649 \u0645\u062a\u0627\u0628\u0639\u0629 \u0627\u0644\u0637\u0644\u0628\u0627\u062a "
    "\u0648\u0631\u0641\u0639 \u0627\u0644\u0646\u0634\u0627\u0637\u060c "
    "\u0648\u0625\u0630\u0627 \u062a\u062d\u062a\u0627\u062c \u0645\u0633\u0627\u0639\u062f\u0629 "
    "\u062a\u0648\u0627\u0635\u0644 \u0645\u0639 \u0627\u0644\u0625\u062f\u0627\u0631\u0629."
)

DEFAULT_WEAK_EMPLOYEE_MESSAGE_SETTINGS = {
    "enabled": False,
    "interval_days": 3,
    "period_days": 30,
    "min_orders": 5,
    "min_sales": 0,
    "message": DEFAULT_WEAK_EMPLOYEE_MESSAGE,
    "last_run_at": "",
    "last_sent_count": 0,
}


class _SafeFormatDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _iso_now(now: datetime | None = None) -> str:
    return (now or datetime.utcnow()).replace(microsecond=0).isoformat()


def get_weak_employee_message_settings(settings: SystemSettings | None = None) -> dict:
    settings = settings or SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    raw = flags.get("weak_employee_auto_message") or {}
    if not isinstance(raw, dict):
        raw = {}
    config = {**DEFAULT_WEAK_EMPLOYEE_MESSAGE_SETTINGS, **raw}
    try:
        config["interval_days"] = max(1, int(config.get("interval_days") or 3))
    except (TypeError, ValueError):
        config["interval_days"] = 3
    try:
        config["period_days"] = max(1, int(config.get("period_days") or 30))
    except (TypeError, ValueError):
        config["period_days"] = 30
    try:
        config["min_orders"] = max(0, int(config.get("min_orders") or 0))
    except (TypeError, ValueError):
        config["min_orders"] = 5
    try:
        config["min_sales"] = max(0, int(config.get("min_sales") or 0))
    except (TypeError, ValueError):
        config["min_sales"] = 0
    config["enabled"] = bool(config.get("enabled"))
    config["message"] = (config.get("message") or DEFAULT_WEAK_EMPLOYEE_MESSAGE).strip()
    if not config["message"]:
        config["message"] = DEFAULT_WEAK_EMPLOYEE_MESSAGE
    return config


def save_weak_employee_message_settings(data: dict) -> dict:
    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    previous = get_weak_employee_message_settings(settings)
    config = get_weak_employee_message_settings(settings)

    config["enabled"] = bool(data.get("enabled"))
    config["message"] = (data.get("message") or DEFAULT_WEAK_EMPLOYEE_MESSAGE).strip()
    config["interval_days"] = max(1, int(data.get("interval_days") or 3))
    config["period_days"] = max(1, int(data.get("period_days") or 30))
    config["min_orders"] = max(0, int(data.get("min_orders") or 0))
    config["min_sales"] = max(0, int(data.get("min_sales") or 0))

    if config["enabled"] and not previous.get("enabled"):
        config["last_run_at"] = _iso_now()

    flags["weak_employee_auto_message"] = config
    settings.set_ui_flags(flags)
    settings.updated_at = datetime.utcnow()
    db.session.commit()
    return config


def _format_message(template: str, employee_data: dict, config: dict) -> str:
    values = _SafeFormatDict(
        employee_name=employee_data.get("name") or "",
        username=employee_data.get("username") or "",
        orders_count=employee_data.get("orders_count", 0),
        sales=employee_data.get("sales", 0),
        sales_display=employee_data.get("sales_display", "0 \u062f.\u0639"),
        returned_count=employee_data.get("returned_count", 0),
        return_rate=employee_data.get("return_rate", 0),
        min_orders=config.get("min_orders", 0),
        min_sales=config.get("min_sales", 0),
        period_days=config.get("period_days", 30),
        reason=employee_data.get("reason") or "",
    )
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            values[field_name]
    return template.format_map(values)


def _admin_sender_id() -> int | None:
    admin = (
        Employee.query
        .filter(Employee.is_active.is_(True), Employee.role == "admin")
        .order_by(Employee.id.asc())
        .first()
    )
    return admin.id if admin else None


def send_weak_employee_messages(*, force: bool = False, now: datetime | None = None) -> dict:
    """Send reminders to weak employees when due."""
    from routes.reports import _build_monitor_data

    now = now or datetime.utcnow()
    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    config = get_weak_employee_message_settings(settings)

    if not config["enabled"] and not force:
        return {"success": True, "skipped": True, "reason": "disabled", "sent": 0}

    last_run_at = _parse_dt(config.get("last_run_at"))
    interval_days = int(config.get("interval_days") or 3)
    if not force:
        if not last_run_at:
            config["last_run_at"] = _iso_now(now)
            flags["weak_employee_auto_message"] = config
            settings.set_ui_flags(flags)
            db.session.commit()
            return {"success": True, "skipped": True, "reason": "schedule_started", "sent": 0}
        if now - last_run_at < timedelta(days=interval_days):
            return {"success": True, "skipped": True, "reason": "not_due", "sent": 0}

    sender_id = _admin_sender_id()
    if not sender_id:
        return {"success": False, "skipped": True, "reason": "no_admin_sender", "sent": 0}

    period_days = int(config.get("period_days") or 30)
    monitor = _build_monitor_data(
        now - timedelta(days=period_days),
        now,
        int(config.get("min_orders") or 0),
        int(config.get("min_sales") or 0),
    )
    weak_employees = monitor.get("weak_employees") or []

    sent = 0
    for employee_data in weak_employees:
        receiver_id = employee_data.get("id")
        if not receiver_id or int(receiver_id) == int(sender_id):
            continue
        db.session.add(
            Message(
                sender_id=sender_id,
                receiver_id=int(receiver_id),
                content=_format_message(config["message"], employee_data, config),
            )
        )
        sent += 1

    config["last_run_at"] = _iso_now(now)
    config["last_sent_count"] = sent
    flags["weak_employee_auto_message"] = config
    settings.set_ui_flags(flags)
    settings.updated_at = now
    db.session.commit()

    return {
        "success": True,
        "skipped": False,
        "sent": sent,
        "weak_count": len(weak_employees),
        "last_run_at": config["last_run_at"],
    }
