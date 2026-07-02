from datetime import datetime

from extensions import db


class FinancialPeriodClose(db.Model):
    """سجل إغلاق الفترات المحاسبية (شهر/سنة)."""

    __tablename__ = "financial_period_close"

    id = db.Column(db.Integer, primary_key=True)
    period_year = db.Column(db.Integer, nullable=False, index=True)
    period_month = db.Column(db.Integer, nullable=False, index=True)
    closed_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    closed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    notes = db.Column(db.Text)

    closer = db.relationship("Employee", foreign_keys=[closed_by], lazy=True)

    __table_args__ = (
        db.UniqueConstraint("period_year", "period_month", name="uq_financial_period_close"),
    )

    def period_label(self):
        return f"{self.period_year}-{self.period_month:02d}"
