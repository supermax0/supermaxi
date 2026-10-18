from extensions import db
from datetime import datetime

class Purchase(db.Model):
    __tablename__ = "purchase"

    __table_args__ = (
        db.UniqueConstraint("branch_id", "invoice_no", name="_purchase_branch_invoice_no_uc"),
    )

    id = db.Column(db.Integer, primary_key=True)

    # =====================
    # Relations (FK فقط)
    # =====================
    supplier_id = db.Column(
        db.Integer,
        db.ForeignKey("supplier.id"),
        nullable=False
    )

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("product.id"),
        nullable=False
    )

    # =====================
    # Legacy single-row fields (kept for backward compatibility)
    # =====================
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Integer, nullable=False)   # سعر الشراء للوحدة
    total = db.Column(db.Integer, nullable=False)   # price * quantity

    # =====================
    # Master (invoice-level) fields for full purchases workflow
    # =====================
    invoice_no = db.Column(db.String(60), nullable=True, index=True)
    status = db.Column(db.String(30), default="draft")  # draft / confirmed
    branch_code = db.Column(db.String(60), nullable=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True)
    reference_no = db.Column(db.String(120), nullable=True)
    supplier_invoice_no = db.Column(db.String(120), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    purchase_mode = db.Column(db.String(30), nullable=True)  # cash / credit / mixed
    payment_term = db.Column(db.String(80), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    shipping_details = db.Column(db.Text, nullable=True)
    extra_cost_note = db.Column(db.String(255), nullable=True)

    sub_total = db.Column(db.Integer, default=0)
    discount_value = db.Column(db.Integer, default=0)
    shipping_extra = db.Column(db.Integer, default=0)
    grand_total = db.Column(db.Integer, default=0)
    paid_total = db.Column(db.Integer, default=0)
    remaining_total = db.Column(db.Integer, default=0)

    created_by_employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    stock_applied = db.Column(db.Boolean, default=False)
    stock_revision = db.Column(db.Integer, nullable=False, default=1)

    warehouse_id = db.Column(db.Integer, nullable=True, index=True)
    purchase_list_id = db.Column(db.Integer, db.ForeignKey("purchase_list.id"), nullable=True, index=True)
    currency = db.Column(db.String(10), nullable=True, default="IQD")
    exchange_rate = db.Column(db.Float, nullable=True, default=1.0)
    payment_currency = db.Column(db.String(10), nullable=True)
    is_draft = db.Column(db.Boolean, default=False, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    source_module = db.Column(db.String(40), nullable=True)
    customs_extra = db.Column(db.Integer, nullable=True, default=0)
    other_extra = db.Column(db.Integer, nullable=True, default=0)

    purchase_date = db.Column(db.Date, default=datetime.utcnow().date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Master-detail relationships
    items = db.relationship(
        "PurchaseItem",
        back_populates="purchase",
        cascade="all, delete-orphan",
        lazy=True,
    )
    payments = db.relationship(
        "PurchasePayment",
        back_populates="purchase",
        cascade="all, delete-orphan",
        lazy=True,
    )
    supplier_payment_allocations = db.relationship(
        "SupplierPaymentAllocation",
        back_populates="purchase",
        passive_deletes=True,
        lazy=True,
    )
    attachments = db.relationship(
        "PurchaseAttachment",
        back_populates="purchase",
        cascade="all, delete-orphan",
        lazy=True,
    )
    created_by = db.relationship("Employee", foreign_keys=[created_by_employee_id], lazy=True)

    def __repr__(self):
        return f"<Purchase #{self.id} inv={self.invoice_no or '-'} total={self.grand_total or self.total}>"
