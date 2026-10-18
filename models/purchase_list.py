"""Temporary daily purchase planning models.

Purchase lists are deliberately inert.  Only the execution service is allowed
to turn their rows into confirmed ``Purchase`` records.
"""
from datetime import datetime

from extensions import db


class PurchaseList(db.Model):
    __tablename__ = "purchase_list"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "list_number", name="uq_purchase_list_tenant_number"),
        db.Index("ix_purchase_list_tenant_status", "tenant_id", "status"),
        db.Index("ix_purchase_list_branch_date", "branch_id", "list_date"),
        db.CheckConstraint(
            "status IN ('draft','open','partially_executed','executing','executed','cancelled')",
            name="ck_purchase_list_status",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=True, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouse.id"), nullable=True, index=True)
    list_number = db.Column(db.String(60), nullable=False, index=True)
    list_date = db.Column(db.Date, nullable=False, index=True)
    responsible_employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    executed_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    executed_at = db.Column(db.DateTime, nullable=True)
    execution_key = db.Column(db.String(100), nullable=True, unique=True, index=True)

    branch = db.relationship("Branch", lazy=True)
    warehouse = db.relationship("Warehouse", lazy=True)
    responsible_employee = db.relationship("Employee", foreign_keys=[responsible_employee_id], lazy=True)
    creator = db.relationship("Employee", foreign_keys=[created_by], lazy=True)
    executor = db.relationship("Employee", foreign_keys=[executed_by], lazy=True)
    items = db.relationship(
        "PurchaseListItem",
        back_populates="purchase_list",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="PurchaseListItem.id",
    )

    @property
    def is_editable(self) -> bool:
        return self.status in {"draft", "open", "partially_executed"}


class PurchaseListItem(db.Model):
    __tablename__ = "purchase_list_item"
    __table_args__ = (
        db.Index("ix_purchase_list_item_list_status", "purchase_list_id", "status"),
        db.Index("ix_purchase_list_item_tenant_supplier", "tenant_id", "supplier_id"),
        db.Index("ix_purchase_list_item_tenant_product", "tenant_id", "product_id"),
        db.CheckConstraint("quantity > 0", name="ck_purchase_list_item_quantity"),
        db.CheckConstraint("purchase_price >= 0 AND discount >= 0 AND tax >= 0", name="ck_purchase_list_item_amounts"),
        db.CheckConstraint(
            "payment_method IN ('cash','card','bank_transfer','credit')",
            name="ck_purchase_list_item_payment_method",
        ),
        db.CheckConstraint(
            "status IN ('draft','selected','executed','discarded','cancelled')",
            name="ck_purchase_list_item_status",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=True, index=True)
    purchase_list_id = db.Column(
        db.Integer,
        db.ForeignKey("purchase_list.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id"), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_id = db.Column(db.Integer, nullable=True)
    unit_name = db.Column(db.String(50), nullable=True, default="قطعة")
    purchase_price = db.Column(db.Integer, nullable=False, default=0)
    discount = db.Column(db.Integer, nullable=False, default=0)
    tax = db.Column(db.Integer, nullable=False, default=0)
    payment_method = db.Column(db.String(30), nullable=False, default="credit", index=True)
    payment_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"), nullable=True, index=True)
    purchase_reason = db.Column(db.String(40), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_selected = db.Column(db.Boolean, nullable=False, default=True, index=True)
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    purchase_invoice_id = db.Column(db.Integer, db.ForeignKey("purchase.id"), nullable=True, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    executed_at = db.Column(db.DateTime, nullable=True)

    purchase_list = db.relationship("PurchaseList", back_populates="items", lazy=True)
    product = db.relationship("Product", lazy=True)
    supplier = db.relationship("Supplier", lazy=True)
    payment_account = db.relationship("TreasuryAccount", lazy=True)
    purchase_invoice = db.relationship("Purchase", foreign_keys=[purchase_invoice_id], lazy=True)

    @property
    def total(self) -> int:
        unit_total = max(0, int(self.purchase_price or 0) - int(self.discount or 0) + int(self.tax or 0))
        return unit_total * max(0, int(self.quantity or 0))
