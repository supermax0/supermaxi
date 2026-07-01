from datetime import datetime

from extensions import db


class TreasuryAccount(db.Model):
    __tablename__ = "treasury_account"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    account_type = db.Column(db.String(20), nullable=False, default="bank")  # cash | bank
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<TreasuryAccount {self.name} ({self.account_type})>"

    @property
    def is_cash(self):
        return (self.account_type or "").strip().lower() == "cash"
