from extensions import db
from datetime import datetime

class AccountTransaction(db.Model):
    __tablename__ = "account_transaction"

    id = db.Column(db.Integer, primary_key=True)

    type = db.Column(
        db.String(20),
        nullable=False
    )  
    # deposit | withdraw

    amount = db.Column(
        db.Integer,
        nullable=False
    )

    note = db.Column(
        db.String(255)
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    def __repr__(self):
        return f"<Account {self.type} {self.amount}>"
