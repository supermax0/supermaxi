"""Unified party ledger for customer / supplier statements."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class PartyLedgerEntry(db.Model):
    __tablename__ = "party_ledger_entry"
    __table_args__ = (
        db.Index(
            "ix_party_ledger_tenant_party_date",
            "tenant_id",
            "party_type",
            "party_id",
            "entry_date",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=True, index=True)
    party_type = db.Column(db.String(20), nullable=False)  # customer|supplier
    party_id = db.Column(db.Integer, nullable=False, index=True)
    entry_date = db.Column(db.Date, nullable=False, index=True)
    doc_no = db.Column(db.String(80), nullable=True)
    entry_type = db.Column(db.String(40), nullable=False)
    description = db.Column(db.Text, nullable=True)
    debit = db.Column(db.Integer, nullable=False, default=0)
    credit = db.Column(db.Integer, nullable=False, default=0)
    balance_after = db.Column(db.Integer, nullable=True)
    currency = db.Column(db.String(10), nullable=False, default="IQD")
    exchange_rate = db.Column(db.Float, nullable=False, default=1.0)
    amount_base = db.Column(db.Integer, nullable=True)  # IQD equivalent snapshot
    reference_type = db.Column(db.String(50), nullable=True)
    reference_id = db.Column(db.Integer, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "party_type": self.party_type,
            "party_id": self.party_id,
            "entry_date": self.entry_date.isoformat() if self.entry_date else None,
            "doc_no": self.doc_no,
            "entry_type": self.entry_type,
            "description": self.description,
            "debit": int(self.debit or 0),
            "credit": int(self.credit or 0),
            "balance_after": self.balance_after,
            "currency": self.currency,
            "exchange_rate": float(self.exchange_rate or 1),
            "amount_base": self.amount_base,
            "reference_type": self.reference_type,
            "reference_id": self.reference_id,
        }
