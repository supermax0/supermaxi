from datetime import datetime

from extensions import db


class DailyAudit(db.Model):
    """Daily cash/report review state."""

    __tablename__ = "daily_audit"

    id = db.Column(db.Integer, primary_key=True)
    report_date = db.Column(db.Date, nullable=False, unique=True, index=True)
    status = db.Column(db.String(20), default="pending", nullable=False, index=True)
    expected_cash_balance = db.Column(db.Integer, default=0, nullable=False)
    actual_cash_count = db.Column(db.Integer, nullable=True)
    difference = db.Column(db.Integer, default=0, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    reviewer = db.relationship("Employee", foreign_keys=[reviewed_by], lazy=True)

    @property
    def status_label(self):
        return {
            "pending": "بانتظار التدقيق",
            "matched": "مطابق",
            "mismatch": "يوجد خلل",
        }.get(self.status, self.status or "بانتظار التدقيق")
