"""Multi-branch models: branches, per-branch stock, inter-branch transfers."""
from datetime import datetime

from extensions import db


class Branch(db.Model):
    __tablename__ = "branch"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(60), nullable=False, unique=True, index=True)
    name = db.Column(db.String(150), nullable=False)
    address = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(60), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    stocks = db.relationship("BranchStock", back_populates="branch", lazy="dynamic")
    transfers_out = db.relationship(
        "StockTransfer",
        foreign_keys="StockTransfer.from_branch_id",
        back_populates="from_branch",
        lazy="dynamic",
    )
    transfers_in = db.relationship(
        "StockTransfer",
        foreign_keys="StockTransfer.to_branch_id",
        back_populates="to_branch",
        lazy="dynamic",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "address": self.address or "",
            "phone": self.phone or "",
            "is_active": bool(self.is_active),
            "is_default": bool(self.is_default),
        }

    def __repr__(self):
        return f"<Branch {self.code} {self.name}>"


class BranchStock(db.Model):
    __tablename__ = "branch_stock"
    __table_args__ = (
        db.UniqueConstraint("branch_id", "product_id", name="_branch_product_uc"),
        db.Index("ix_branch_stock_branch_product", "branch_id", "product_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    quantity = db.Column(db.Integer, default=0, nullable=False)
    opening_stock = db.Column(db.Integer, default=0, nullable=False)
    low_stock_threshold = db.Column(db.Integer, default=5, nullable=False)

    branch = db.relationship("Branch", back_populates="stocks")
    product = db.relationship("Product", backref=db.backref("branch_stocks", lazy="dynamic"))

    def __repr__(self):
        return f"<BranchStock branch={self.branch_id} product={self.product_id} qty={self.quantity}>"


class StockTransfer(db.Model):
    __tablename__ = "stock_transfer"

    id = db.Column(db.Integer, primary_key=True)
    transfer_no = db.Column(db.String(60), nullable=True, index=True)
    from_branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    to_branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    status = db.Column(db.String(30), default="draft", nullable=False, index=True)
    note = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    received_by_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime, nullable=True)
    received_at = db.Column(db.DateTime, nullable=True)

    from_branch = db.relationship("Branch", foreign_keys=[from_branch_id], back_populates="transfers_out")
    to_branch = db.relationship("Branch", foreign_keys=[to_branch_id], back_populates="transfers_in")
    created_by = db.relationship("Employee", foreign_keys=[created_by_id], lazy=True)
    received_by = db.relationship("Employee", foreign_keys=[received_by_id], lazy=True)
    lines = db.relationship(
        "StockTransferLine",
        back_populates="transfer",
        cascade="all, delete-orphan",
        lazy=True,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "transfer_no": self.transfer_no or "",
            "from_branch_id": self.from_branch_id,
            "to_branch_id": self.to_branch_id,
            "status": self.status,
            "note": self.note or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "received_at": self.received_at.isoformat() if self.received_at else None,
        }


class StockTransferLine(db.Model):
    __tablename__ = "stock_transfer_line"

    id = db.Column(db.Integer, primary_key=True)
    transfer_id = db.Column(db.Integer, db.ForeignKey("stock_transfer.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    quantity_received = db.Column(db.Integer, nullable=True)

    transfer = db.relationship("StockTransfer", back_populates="lines")
    product = db.relationship("Product", lazy=True)
