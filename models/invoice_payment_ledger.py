# -*- coding: utf-8 -*-
"""سجل تغيّر التحصيل الفعلي للفاتورة — لربط ربح اليوم بلحظة التسديد لا تاريخ إنشاء الطلب."""
from extensions import db
from datetime import datetime


class InvoicePaymentLedger(db.Model):
    __tablename__ = "invoice_payment_ledger"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False, index=True)
    # موجب = تحصيل، سالب = تخفيض (مثل تصفير بعد ترجيع)
    amount_delta = db.Column(db.Integer, nullable=False)
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<InvoicePaymentLedger inv={self.invoice_id} Δ={self.amount_delta}>"
