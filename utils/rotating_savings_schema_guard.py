"""Schema guard for rotating savings tables."""

from sqlalchemy import inspect, text

from extensions import db
from models.rotating_savings import (
    RotatingSaving,
    RotatingSavingAttachment,
    RotatingSavingPayment,
    RotatingSavingReceipt,
    RotatingSavingSettings,
)


def _ensure_columns(table_name, columns: dict):
    """Add missing columns on existing tenant DBs."""
    try:
        inspector = inspect(db.engine)
        if table_name not in inspector.get_table_names():
            return
        existing = {c["name"] for c in inspector.get_columns(table_name)}
        for col, ddl in columns.items():
            if col not in existing:
                db.session.execute(text(ddl))
        db.session.commit()
    except Exception:
        db.session.rollback()


def ensure_rotating_savings_schema():
    bind = db.engine
    RotatingSavingSettings.__table__.create(bind=bind, checkfirst=True)
    RotatingSaving.__table__.create(bind=bind, checkfirst=True)
    RotatingSavingPayment.__table__.create(bind=bind, checkfirst=True)
    RotatingSavingReceipt.__table__.create(bind=bind, checkfirst=True)
    RotatingSavingAttachment.__table__.create(bind=bind, checkfirst=True)

    _ensure_columns(
        "rotating_saving_payments",
        {
            "reversed_at": "ALTER TABLE rotating_saving_payments ADD COLUMN reversed_at DATETIME",
            "reversal_journal_entry_id": "ALTER TABLE rotating_saving_payments ADD COLUMN reversal_journal_entry_id INTEGER",
        },
    )
    _ensure_columns(
        "rotating_saving_receipts",
        {
            "reversed_at": "ALTER TABLE rotating_saving_receipts ADD COLUMN reversed_at DATETIME",
        },
    )
