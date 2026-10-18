"""Branch cash transfer document (multi-branch spec, phase 9).

A workflow record in front of FINORA's own treasury transfer engine. Money moves exactly once, when the
receiver confirms: ``utils.treasury_calculations.record_treasury_transfer`` then posts both legs, checks the
balance under lock and (through the ledger sync) produces the balanced journal — never an expense, never a sale.
Until then nothing is posted, so there is no phantom «cash in transit» that the ledger would count as arrived.
"""
from __future__ import annotations

from datetime import datetime

from extensions import db

def _business_today():
    from modules.finance.common import today

    return today()


STATUSES = {
    "pending": "بانتظار الاعتماد",
    "approved": "معتمد — بانتظار تأكيد الاستلام",
    "posting": "قيد الترحيل",
    "completed": "مكتمل",
    "rejected": "مرفوض",
    "cancelled": "ملغى",
}


class BranchCashTransfer(db.Model):
    __tablename__ = "branch_cash_transfer"

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), nullable=False, unique=True, index=True)
    operation_id = db.Column(db.String(64), nullable=True, unique=True, index=True)  # client UUID: replay-safe create
    from_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"), nullable=False)
    to_account_id = db.Column(db.Integer, db.ForeignKey("treasury_account.id"), nullable=False)
    from_branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    to_branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(10), nullable=False, default="IQD")
    transfer_date = db.Column(db.Date, nullable=False, default=lambda: _business_today())
    reference = db.Column(db.String(100), nullable=True)
    reason = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    requested_by_id = db.Column(db.Integer, nullable=True)
    approved_by_id = db.Column(db.Integer, nullable=True)
    received_by_id = db.Column(db.Integer, nullable=True)
    closed_reason = db.Column(db.String(255), nullable=True)  # rejection / cancellation reason
    treasury_transfer_id = db.Column(db.Integer, nullable=True, index=True)
    events_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
