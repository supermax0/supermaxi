# -*- coding: utf-8 -*-
"""سجل تغيّر التحصيل الفعلي للفاتورة — لربط ربح اليوم بلحظة التسديد لا تاريخ إنشاء الطلب."""
from extensions import db
from datetime import datetime


class InvoicePaymentLedger(db.Model):
    __tablename__ = "invoice_payment_ledger"

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=True, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False, index=True)
    currency = db.Column(db.String(10), nullable=True, default="IQD")
    exchange_rate = db.Column(db.Float, nullable=True, default=1.0)
    source_module = db.Column(db.String(40), nullable=True)
    note = db.Column(db.Text, nullable=True)
    payment_method = db.Column(db.String(40), nullable=True)
    # NULL keeps old rows compatible and means the default cash account.
    treasury_account_id = db.Column(
        db.Integer,
        db.ForeignKey("treasury_account.id"),
        nullable=True,
        index=True,
    )
    treasury_account = db.relationship("TreasuryAccount", lazy=True)
    # موجب = تحصيل، سالب = تخفيض (مثل تصفير بعد ترجيع)
    amount_delta = db.Column(db.Integer, nullable=False)
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<InvoicePaymentLedger inv={self.invoice_id} Δ={self.amount_delta}>"
