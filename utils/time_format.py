"""Tenant display preference only; never changes stored dates or scheduling."""
import json
import re
from datetime import date, datetime, time

from flask import g, has_app_context, has_request_context, session
from sqlalchemy import inspect

DEFAULT_TIME_FORMAT = "12"


def get_time_format():
    if not has_app_context() or not getattr(g, "tenant", None):
        return DEFAULT_TIME_FORMAT
    key = str(g.tenant)
    memo = getattr(g, "_time_format_memo", {})
    if key in memo:
        return memo[key]
    from extensions import db
    from models.system_settings import SystemSettings
    with db.session.no_autoflush:
        inspector = inspect(db.session.connection())
        if not inspector.has_table(SystemSettings.__tablename__) or "ui_flags" not in {
            column["name"] for column in inspector.get_columns(SystemSettings.__tablename__)
        }:
            memo[key] = DEFAULT_TIME_FORMAT
            g._time_format_memo = memo
            return DEFAULT_TIME_FORMAT
        row = db.session.query(SystemSettings.ui_flags).first()
    try:
        flags = json.loads(row[0] or "{}") if row else {}
    except (ValueError, TypeError):
        flags = {}
    value = flags.get("time_format") if isinstance(flags, dict) else None
    value = value if value in ("12", "24") else DEFAULT_TIME_FORMAT
    memo[key] = value
    g._time_format_memo = memo
    return value


def set_time_format(value):
    if value not in ("12", "24"):
        raise ValueError("اختر تنسيق الوقت 12 أو 24 ساعة")
    from models.system_settings import SystemSettings
    from extensions import db
    settings = SystemSettings.get_settings()
    flags = settings.get_ui_flags()
    flags["time_format"] = value
    settings.set_ui_flags(flags)
    db.session.commit()
    g._time_format_memo = {str(g.tenant): value}
    return value


def format_clock(value, pattern="%H:%M", *, time_format=None):
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = time.fromisoformat(value)
        except ValueError:
            return value
    mode = time_format or get_time_format()
    if mode == "24":
        return value.strftime(pattern.replace("%I", "%H").replace(" %p", "").replace("%p", ""))
    pattern = pattern.replace("%H", "%I")
    if "%I" in pattern and "%p" not in pattern:
        pattern += " %p"
    return value.strftime(pattern).replace("AM", "ص").replace("PM", "م")


def format_timestamp(value, pattern="%Y-%m-%d %H:%M", *, local=False):
    if not value:
        return ""
    if isinstance(value, str):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return value
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if isinstance(value, time):
        return format_clock(value, pattern if "%" in pattern else "%H:%M")
    if isinstance(value, datetime) and not local:
        from utils.business_time import business_datetime
        value = business_datetime(value)
    if isinstance(value, date) and not isinstance(value, datetime) and pattern == "%Y-%m-%d %H:%M":
        return value.isoformat()
    if isinstance(value, (date, datetime)):
        return format_clock(value, pattern)
    return str(value)


def install_time_format(app):
    if app.extensions.get("finora_time_format"):
        return
    app.extensions["finora_time_format"] = True
    app.jinja_env.filters["finora_datetime"] = format_timestamp
    app.jinja_env.filters["finora_clock"] = format_clock

    @app.context_processor
    def time_context():
        return {"finora_time_format": get_time_format(),
                "finora_time_authenticated": bool(has_request_context() and session.get("user_id") and session.get("tenant_slug") == getattr(g, "tenant", None))}
