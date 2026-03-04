from extensions import db
from datetime import datetime

class Supplier(db.Model):
    __tablename__ = "supplier"

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(50))
    address = db.Column(db.String(255))

    total_debt = db.Column(db.Integer, default=0)
    total_paid = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ✅ العلاقة الصحيحة الوحيدة
    purchases = db.relationship(
    "Purchase",
    backref="supplier",
    lazy=True,
    cascade="all, delete"
)


    @property
    def remaining(self):
        return self.total_debt - self.total_paid

    def __repr__(self):
        return f"<Supplier {self.name}>"
