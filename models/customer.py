from extensions import db
from datetime import datetime

class Customer(db.Model):
    __tablename__ = "customer"

    id = db.Column(db.Integer, primary_key=True)

    # Tenant (الشركة المالكة لهذا الزبون)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey("tenant.id"),
        nullable=True
    )

    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    tg_chat_id = db.Column(db.String(64), index=True)
    phone2 = db.Column(db.String(20))
    city = db.Column(db.String(100))   # بغداد / محافظات
    address = db.Column(db.String(255))
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # علاقات
    invoices = db.relationship(
    "Invoice",
    back_populates="customer",
    lazy=True
)


    def __repr__(self):
        return f"<Customer {self.name} {self.phone}>"
