"""Device stock escrow. Physical stock stays in its native ledgers.

Tenant SQLite triggers protect allocations even from legacy/direct writers.
Reservations have no timeout: a disconnected device may have delivered goods.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import text

from extensions import db


class StockReservationError(ValueError):
    pass


class DesktopStockGrant(db.Model):
    __tablename__ = "desktop_stock_grant"
    id = db.Column(db.String(36), primary_key=True)
    device_id = db.Column(db.String(36), nullable=False, index=True)
    employee_id = db.Column(db.Integer, nullable=False)
    branch_id = db.Column(db.Integer, nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False)
    response_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class DesktopStockAllocation(db.Model):
    __tablename__ = "desktop_stock_allocation"
    __table_args__ = (
        db.CheckConstraint("quantity > 0 AND consumed >= 0 AND returned >= 0 AND consumed + returned <= quantity", name="ck_desktop_allocation_balance"),
        db.Index("ix_desktop_allocation_stock", "stock_id", "variant_id"),
    )
    id = db.Column(db.String(36), primary_key=True)
    grant_id = db.Column(db.String(36), nullable=False, index=True)
    product_id = db.Column(db.Integer, nullable=False, index=True)
    requested_product_id = db.Column(db.Integer, nullable=False)
    branch_id = db.Column(db.Integer, nullable=False)
    stock_id = db.Column(db.Integer, nullable=False)
    variant_id = db.Column(db.Integer, nullable=False, default=0)
    color = db.Column(db.String(80), nullable=False, default="")
    quantity = db.Column(db.Integer, nullable=False)
    consumed = db.Column(db.Integer, nullable=False, default=0)
    returned = db.Column(db.Integer, nullable=False, default=0)


class DesktopStockReturn(db.Model):
    __tablename__ = "desktop_stock_return"
    id = db.Column(db.String(36), primary_key=True)
    device_id = db.Column(db.String(36), nullable=False)
    employee_id = db.Column(db.Integer, nullable=False)
    branch_id = db.Column(db.Integer, nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False)
    response_json = db.Column(db.Text, nullable=False)


HELD = "quantity-consumed-returned"
GUARD_ERROR = "finora_offline_stock_reserved"
GUARD_MESSAGE = "هذه الكمية محجوزة لجهاز أوفلاين؛ أعد الحصة من الجهاز بعد مزامنة مبيعاته أولاً"


def ensure_reservation_schema():
    connection = db.session.connection()
    if connection.dialect.name != "sqlite":
        raise StockReservationError("حجز الجهاز غير مفعّل لمحرك قاعدة البيانات الحالي")
    for model in (DesktopStockGrant, DesktopStockAllocation, DesktopStockReturn):
        model.__table__.create(connection, checkfirst=True)
    connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS desktop_stock_mirror_ticket(product_id INTEGER PRIMARY KEY, quantity INTEGER NOT NULL)")
    stock_held = f"COALESCE((SELECT SUM({HELD}) FROM desktop_stock_allocation WHERE stock_id=OLD.id),0)"
    variant_held = f"COALESCE((SELECT SUM({HELD}) FROM desktop_stock_allocation WHERE variant_id=OLD.id),0)"
    family = """EXISTS (SELECT 1 FROM desktop_stock_allocation a JOIN product p ON p.id=a.product_id
      WHERE a.quantity>a.consumed+a.returned AND
       (a.product_id=OLD.id OR a.requested_product_id=OLD.id OR
        (COALESCE(OLD.catalog_group_id,'')<>'' AND p.catalog_group_id=OLD.catalog_group_id)))"""
    statements = [
        f"""CREATE TRIGGER IF NOT EXISTS trg_desktop_stock_floor BEFORE UPDATE ON branch_stock
        WHEN {stock_held}>0 AND (NEW.quantity<{stock_held} OR NEW.id<>OLD.id
          OR NEW.product_id<>OLD.product_id OR NEW.branch_id<>OLD.branch_id)
        BEGIN SELECT RAISE(ABORT,'{GUARD_ERROR}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS trg_desktop_stock_delete BEFORE DELETE ON branch_stock
        WHEN {stock_held}>0 BEGIN SELECT RAISE(ABORT,'{GUARD_ERROR}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS trg_desktop_color_floor BEFORE UPDATE ON product_color_variant
        WHEN {variant_held}>0 AND (NEW.quantity<{variant_held} OR NEW.id<>OLD.id
          OR NEW.product_id<>OLD.product_id OR NEW.color_name<>OLD.color_name)
        BEGIN SELECT RAISE(ABORT,'{GUARD_ERROR}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS trg_desktop_color_delete BEFORE DELETE ON product_color_variant
        WHEN {variant_held}>0 BEGIN SELECT RAISE(ABORT,'{GUARD_ERROR}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS trg_desktop_color_convert BEFORE INSERT ON product_color_variant
        WHEN EXISTS(SELECT 1 FROM desktop_stock_allocation WHERE product_id=NEW.product_id
          AND variant_id=0 AND quantity>consumed+returned)
        BEGIN SELECT RAISE(ABORT,'{GUARD_ERROR}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS trg_desktop_product_delete BEFORE DELETE ON product
        WHEN {family} BEGIN SELECT RAISE(ABORT,'{GUARD_ERROR}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS trg_desktop_product_identity BEFORE UPDATE ON product
        WHEN {family} AND (NEW.id<>OLD.id OR NEW.branch_id IS NOT OLD.branch_id
          OR NEW.catalog_group_id IS NOT OLD.catalog_group_id OR NEW.active IS NOT OLD.active
          OR NEW.meta_json IS NOT OLD.meta_json)
        BEGIN SELECT RAISE(ABORT,'{GUARD_ERROR}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS trg_desktop_product_mirror BEFORE UPDATE OF quantity ON product
        WHEN NEW.quantity<>OLD.quantity AND {family}
          AND NOT EXISTS(SELECT 1 FROM desktop_stock_mirror_ticket WHERE product_id=OLD.id AND quantity=NEW.quantity)
        BEGIN SELECT RAISE(ABORT,'{GUARD_ERROR}'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_desktop_mirror_ticket AFTER UPDATE OF quantity ON product
        BEGIN DELETE FROM desktop_stock_mirror_ticket WHERE product_id=NEW.id; END""",
        f"""CREATE TRIGGER IF NOT EXISTS trg_desktop_allocation_insert BEFORE INSERT ON desktop_stock_allocation
        WHEN NEW.consumed<>0 OR NEW.returned<>0 OR
          NOT EXISTS(SELECT 1 FROM branch_stock WHERE id=NEW.stock_id AND product_id=NEW.product_id AND branch_id=NEW.branch_id) OR
          NEW.quantity+COALESCE((SELECT SUM({HELD}) FROM desktop_stock_allocation WHERE stock_id=NEW.stock_id),0)
            >(SELECT quantity FROM branch_stock WHERE id=NEW.stock_id) OR
          (NEW.variant_id<>0 AND (NOT EXISTS(SELECT 1 FROM product_color_variant WHERE id=NEW.variant_id
            AND product_id=NEW.product_id AND color_name=NEW.color) OR
           NEW.quantity+COALESCE((SELECT SUM({HELD}) FROM desktop_stock_allocation WHERE variant_id=NEW.variant_id),0)
            >(SELECT quantity FROM product_color_variant WHERE id=NEW.variant_id)))
        BEGIN SELECT RAISE(ABORT,'{GUARD_ERROR}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS trg_desktop_allocation_immutable BEFORE UPDATE ON desktop_stock_allocation
        WHEN NEW.id<>OLD.id OR NEW.grant_id<>OLD.grant_id OR NEW.product_id<>OLD.product_id
          OR NEW.requested_product_id<>OLD.requested_product_id OR NEW.branch_id<>OLD.branch_id
          OR NEW.stock_id<>OLD.stock_id OR NEW.variant_id<>OLD.variant_id OR NEW.color<>OLD.color
          OR NEW.quantity<>OLD.quantity OR NEW.consumed<OLD.consumed OR NEW.returned<OLD.returned
        BEGIN SELECT RAISE(ABORT,'{GUARD_ERROR}'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS trg_desktop_allocation_delete BEFORE DELETE ON desktop_stock_allocation
        WHEN OLD.quantity>OLD.consumed+OLD.returned BEGIN SELECT RAISE(ABORT,'{GUARD_ERROR}'); END""",
    ]
    for statement in statements:
        connection.exec_driver_sql(statement)
    # A general product cannot be converted to an independent stock ledger
    # while a disconnected device still owns any of its inventory.
    for table in ("food_product_profile", "warehouse_stock"):
        if connection.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).first():
            for action in ("INSERT", "UPDATE OF product_id"):
                suffix = "insert" if action == "INSERT" else "update"
                connection.exec_driver_sql(f"""CREATE TRIGGER IF NOT EXISTS trg_desktop_{table}_{suffix}
                  BEFORE {action} ON {table} WHEN EXISTS (
                    SELECT 1 FROM desktop_stock_allocation a JOIN product p ON p.id=a.product_id
                    JOIN product q ON q.id=NEW.product_id
                    WHERE a.quantity>a.consumed+a.returned AND
                    (a.product_id=q.id OR a.requested_product_id=q.id OR
                     (COALESCE(p.catalog_group_id,'')<>'' AND p.catalog_group_id=q.catalog_group_id)))
                  BEGIN SELECT RAISE(ABORT,'{GUARD_ERROR}'); END""")


def require_general_stock(product_id):
    connection = db.session.connection()
    for table in ("food_product_profile", "warehouse_stock"):
        if connection.exec_driver_sql("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).first():
            linked = connection.exec_driver_sql(f"""SELECT 1 FROM {table} s JOIN product p ON p.id=s.product_id
                JOIN product q ON q.id=? WHERE p.id=q.id OR
                (COALESCE(p.catalog_group_id,'')<>'' AND p.catalog_group_id=q.catalog_group_id) LIMIT 1""", (product_id,)).first()
            if linked:
                raise StockReservationError("هذا الصنف يستخدم مخزون المواد الغذائية أو المستودعات؛ حجزه للأوفلاين غير مفعّل بعد")


def reservation_tables_exist():
    connection = db.session.connection()
    return connection.dialect.name == "sqlite" and bool(connection.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='desktop_stock_mirror_ticket'"
    ).first())


def reserved_for_stock(stock_id, variant_id=None):
    if not reservation_tables_exist():
        return 0
    column, value = ("variant_id", variant_id) if variant_id is not None else ("stock_id", stock_id)
    return int(db.session.execute(text(f"SELECT COALESCE(SUM({HELD}),0) FROM desktop_stock_allocation WHERE {column}=:id"), {"id": value}).scalar() or 0)


@contextmanager
def allow_stock_mirror(product_ids, quantity):
    """One-use tickets only for native aggregate synchronization, never stock sales."""
    if not reservation_tables_exist():
        yield
        return
    # Flush physical ledger changes before granting permission for the exact mirror.
    db.session.flush()
    for product_id in product_ids:
        db.session.execute(text("INSERT OR REPLACE INTO desktop_stock_mirror_ticket VALUES (:id,:quantity)"),
                           {"id": product_id, "quantity": quantity})
    try:
        yield
        db.session.flush()
    finally:
        # A failed statement leaves the ORM transaction unusable; rollback clears tickets.
        if db.session.is_active:
            for product_id in product_ids:
                db.session.execute(text("DELETE FROM desktop_stock_mirror_ticket WHERE product_id=:id"), {"id": product_id})
