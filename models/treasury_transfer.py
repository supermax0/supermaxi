from datetime import datetime

from extensions import db


class TreasuryTransfer(db.Model):
    __tablename__ = "treasury_transfer"

    id = db.Column(db.Integer, primary_key=True)
    from_account_id = db.Column(
        db.Integer,
        db.ForeignKey("treasury_account.id"),
        nullable=False,
    )
    to_account_id = db.Column(
        db.Integer,
        db.ForeignKey("treasury_account.id"),
        nullable=False,
    )
    amount = db.Column(db.Integer, nullable=False)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    from_account = db.relationship(
        "TreasuryAccount",
        foreign_keys=[from_account_id],
        lazy=True,
    )
    to_account = db.relationship(
        "TreasuryAccount",
        foreign_keys=[to_account_id],
        lazy=True,
    )

    def __repr__(self):
        return f"<TreasuryTransfer {self.from_account_id}->{self.to_account_id} {self.amount}>"
