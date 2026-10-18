"""Safe additive initialization on the active tenant's connection."""
from extensions import db
from models.role import Permission
from .common import PERMISSIONS
from .models import MODELS, InventoryCountControl
from threading import RLock
from sqlalchemy.exc import IntegrityError

_READY = set()
_LOCK = RLock()


def ensure_schema():
    from flask import g
    from extensions_tenant import get_tenant_engine
    key = (g.tenant, id(get_tenant_engine(g.tenant)))
    if key in _READY:
        return
    with _LOCK:
        if key in _READY:
            return
        for attempt in range(3):
            try:
                _initialize()
                _READY.add(key)
                return
            except IntegrityError:
                db.session.rollback()
                if attempt == 2:
                    raise


def _initialize():
    from utils.inventory_audit_trail import ensure_inventory_audit_schema
    ensure_inventory_audit_schema()
    connection = db.session.connection()
    for model in MODELS:
        model.__table__.create(connection, checkfirst=True)
    from sqlalchemy import inspect
    if "actor_name" not in {column["name"] for column in inspect(connection).get_columns("inventory_count_event")}:
        connection.exec_driver_sql("ALTER TABLE inventory_count_event ADD COLUMN actor_name VARCHAR(255) NOT NULL DEFAULT ''")
    if "product_snapshot_json" not in {column["name"] for column in inspect(connection).get_columns("inventory_count_line")}:
        connection.exec_driver_sql("ALTER TABLE inventory_count_line ADD COLUMN product_snapshot_json TEXT NOT NULL DEFAULT '{}'")
    if "ticket_product_json" not in {column["name"] for column in inspect(connection).get_columns("inventory_count_line")}:
        connection.exec_driver_sql("ALTER TABLE inventory_count_line ADD COLUMN ticket_product_json TEXT NOT NULL DEFAULT '{}'")
    if "product_snapshot_json" not in {column["name"] for column in inspect(connection).get_columns("inventory_count_offline_ticket")}:
        connection.exec_driver_sql("ALTER TABLE inventory_count_offline_ticket ADD COLUMN product_snapshot_json TEXT NOT NULL DEFAULT '{}'")
    if connection.dialect.name == "sqlite":
        for verb in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(f"""CREATE TRIGGER IF NOT EXISTS inventory_count_event_no_{verb.lower()}
                BEFORE {verb} ON inventory_count_event
                BEGIN SELECT RAISE(ABORT,'inventory_count_history_immutable'); END""")
            connection.exec_driver_sql(f"""CREATE TRIGGER IF NOT EXISTS inventory_count_session_no_{verb.lower()}
                BEFORE {verb} ON inventory_count_session WHEN OLD.status='posted'
                BEGIN SELECT RAISE(ABORT,'inventory_count_posted_immutable'); END""")
            connection.exec_driver_sql(f"""CREATE TRIGGER IF NOT EXISTS inventory_count_line_no_{verb.lower()}
                BEFORE {verb} ON inventory_count_line
                WHEN EXISTS(SELECT 1 FROM inventory_count_session WHERE id=OLD.session_id AND status='posted')
                BEGIN SELECT RAISE(ABORT,'inventory_count_posted_immutable'); END""")
            connection.exec_driver_sql(f"""CREATE TRIGGER IF NOT EXISTS inventory_count_journal_no_{verb.lower()}
                BEFORE {verb} ON journal_entry WHEN OLD.reference_type='inventory_count'
                BEGIN SELECT RAISE(ABORT,'inventory_count_journal_immutable'); END""")
    if not db.session.get(InventoryCountControl, 1):
        db.session.add(InventoryCountControl(id=1, revision=0))
    for key, label in PERMISSIONS.items():
        if not Permission.query.filter_by(name=key).first():
            db.session.add(Permission(name=key, description=label))
    db.session.commit()
