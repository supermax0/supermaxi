from sqlalchemy import inspect, text

from extensions import db
from modules.facebook_routing.models import (
    FacebookEmployeeRouting,
    FacebookPageEmployee,
    FacebookPageRouting,
    FacebookRoutingEvent,
)

TABLES = (
    FacebookPageRouting.__table__,
    FacebookPageEmployee.__table__,
    FacebookEmployeeRouting.__table__,
    FacebookRoutingEvent.__table__,
)


def ensure_facebook_routing_schema() -> None:
    bind = db.session.get_bind()
    if bind is None:
        return
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)
    inspector = inspect(bind)
    names = set(inspector.get_table_names())
    dialect = (bind.dialect.name or "").lower()
    stamp = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
    routing_extras = {
        "facebook_page_routing": {"reply_timeout_seconds": "INTEGER DEFAULT 180"},
        "facebook_employee_routing": {
            "reply_timeout_seconds": "INTEGER",
            "last_seen_at": stamp,
            "activity": "VARCHAR(20)",
            "activity_label": "VARCHAR(80)",
        },
    }
    changed = False
    for table_name, columns_def in routing_extras.items():
        if table_name not in names:
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for name, definition in columns_def.items():
            if name not in existing:
                db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}"))
                changed = True
    if "ai_sales_conversation" in names:
        columns = {column["name"] for column in inspector.get_columns("ai_sales_conversation")}
        extras = {
            "assigned_at": stamp,
            "assignment_method": "VARCHAR(40)",
        }
        for name, definition in extras.items():
            if name not in columns:
                db.session.execute(text(f"ALTER TABLE ai_sales_conversation ADD COLUMN {name} {definition}"))
                changed = True
    if changed:
        db.session.commit()
