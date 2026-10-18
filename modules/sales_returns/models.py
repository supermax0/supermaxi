"""Append-only original-sale and posted-return evidence; not balance accounts."""
from datetime import datetime
import hashlib
from sqlalchemy import event
from extensions import db


class ReturnEvidenceError(ValueError):
    pass


class SalesReturnOrigin(db.Model):
    __tablename__ = "sales_return_origins"
    __table_args__ = (db.UniqueConstraint("tenant_key", "invoice_id", name="uq_return_original_invoice"),)
    id = db.Column(db.Integer, primary_key=True)
    tenant_key = db.Column(db.String(80), nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    snapshot = db.Column(db.Text, nullable=False)
    snapshot_hash = db.Column(db.String(64), nullable=False)


class SalesReturn(db.Model):
    __tablename__ = "sales_returns"
    __table_args__ = (
        db.UniqueConstraint("tenant_key", "operation_key", name="uq_return_operation_key"),
        db.CheckConstraint("kind IN ('return', 'exchange')", name="ck_return_kind"),
        db.CheckConstraint("credit_amount >= 0 AND cost_amount >= 0 AND debt_relief >= 0 AND excess_collection >= 0 AND refund_amount >= 0 AND customer_credit >= 0", name="ck_return_nonnegative_values"),
        db.CheckConstraint("credit_amount = debt_relief + excess_collection", name="ck_return_credit_parts"),
        db.CheckConstraint("excess_collection = refund_amount + customer_credit", name="ck_return_collection_parts"),
    )
    id = db.Column(db.Integer, primary_key=True)
    tenant_key = db.Column(db.String(80), nullable=False, index=True)
    origin_id = db.Column(db.Integer, db.ForeignKey("sales_return_origins.id"), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    return_location_id = db.Column(db.Integer)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"))
    replacement_invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"))
    operation_key = db.Column(db.String(80), nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False)
    kind = db.Column(db.String(16), default="return", nullable=False)
    reason = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    credit_amount = db.Column(db.BigInteger, nullable=False)
    cost_amount = db.Column(db.BigInteger, nullable=False)
    debt_relief = db.Column(db.BigInteger, nullable=False)
    excess_collection = db.Column(db.BigInteger, nullable=False)
    refund_amount = db.Column(db.BigInteger, nullable=False)
    # Credit created by this document, never a cached current wallet balance.
    customer_credit = db.Column(db.BigInteger, nullable=False)
    evidence = db.Column(db.Text, nullable=False)
    origin = db.relationship("SalesReturnOrigin")
    lines = db.relationship("SalesReturnLine", back_populates="document")


class SalesReturnLine(db.Model):
    __tablename__ = "sales_return_lines"
    __table_args__ = (
        db.UniqueConstraint("document_id", "order_item_id", name="uq_return_document_line"),
        db.CheckConstraint("quantity > 0 AND credit_amount >= 0 AND cost_amount >= 0", name="ck_return_line_values"),
    )
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("sales_returns.id"), nullable=False, index=True)
    order_item_id = db.Column(db.Integer, db.ForeignKey("order_item.id"), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False)
    credit_amount = db.Column(db.BigInteger, nullable=False)
    cost_amount = db.Column(db.BigInteger, nullable=False)
    snapshot = db.Column(db.Text, nullable=False)
    document = db.relationship("SalesReturn", back_populates="lines")
    costs = db.relationship("SalesReturnCost", back_populates="line")


class SalesReturnCost(db.Model):
    __tablename__ = "sales_return_costs"
    __table_args__ = (
        db.UniqueConstraint("line_id", "original_layer_id", name="uq_return_original_layer"),
        db.CheckConstraint("quantity > 0 AND unit_cost >= 0", name="ck_return_cost_values"),
        db.CheckConstraint("cost_basis IN ('saved_fifo', 'saved_layer_cost', 'saved_line_cost')", name="ck_return_cost_basis"),
        db.CheckConstraint("cost_basis != 'saved_fifo' OR (original_layer_id IS NOT NULL AND original_lot_id IS NOT NULL AND original_received_at IS NOT NULL)", name="ck_return_fifo_evidence"),
        db.CheckConstraint("cost_basis != 'saved_layer_cost' OR original_layer_id IS NOT NULL", name="ck_return_layer_evidence"),
    )
    id = db.Column(db.Integer, primary_key=True)
    line_id = db.Column(db.Integer, db.ForeignKey("sales_return_lines.id"), nullable=False, index=True)
    # Historical IDs remain evidence if legacy full-return code removes a live
    # consumption layer. Their saved quantity/cost/date cannot be cascaded away.
    original_layer_id = db.Column(db.Integer)
    original_lot_id = db.Column(db.Integer)
    restored_lot_id = db.Column(db.Integer, nullable=False)
    cost_basis = db.Column(db.String(24), default="saved_fifo", nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.BigInteger, nullable=False)
    original_received_at = db.Column(db.DateTime)
    line = db.relationship("SalesReturnLine", back_populates="costs")


class SalesReturnFunding(db.Model):
    """Which original tender funded a cash refund or restored customer credit."""
    __tablename__ = "sales_return_funding"
    __table_args__ = (
        db.UniqueConstraint("document_id", "source_ledger_id", name="uq_return_funding_ledger"),
        db.UniqueConstraint("document_id", "origin_id", name="uq_return_funding_undated"),
        db.CheckConstraint("amount > 0", name="ck_return_funding_amount"),
        db.CheckConstraint("disposition IN ('refund', 'credit')", name="ck_return_funding_disposition"),
        db.CheckConstraint("(source_ledger_id IS NOT NULL AND origin_id IS NULL) OR (source_ledger_id IS NULL AND origin_id IS NOT NULL)", name="ck_return_funding_source"),
    )
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("sales_returns.id"), nullable=False, index=True)
    source_ledger_id = db.Column(db.Integer, db.ForeignKey("invoice_payment_ledger.id"), index=True)
    origin_id = db.Column(db.Integer, db.ForeignKey("sales_return_origins.id"), index=True)
    source_voucher_id = db.Column(db.Integer, db.ForeignKey("financial_vouchers.id"), index=True)
    treasury_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"))
    payment_method = db.Column(db.String(40), nullable=False)
    disposition = db.Column(db.String(16), nullable=False)
    amount = db.Column(db.BigInteger, nullable=False)


def _immutable(mapper, connection, target):
    raise ReturnEvidenceError("دليل البيع والمرتجع المعتمد لا يعدل أو يحذف؛ يلزم مستند مرتبط مستقل")


@event.listens_for(SalesReturnOrigin, "before_insert")
def _verify_original_hash(mapper, connection, target):
    if hashlib.sha256(target.snapshot.encode("utf-8")).hexdigest() != target.snapshot_hash:
        raise ReturnEvidenceError("بصمة دليل أصل البيع لا تطابق البيانات المحفوظة")


for model in (SalesReturnOrigin, SalesReturn, SalesReturnLine, SalesReturnCost, SalesReturnFunding):
    event.listen(model, "before_update", _immutable)
    event.listen(model, "before_delete", _immutable)
