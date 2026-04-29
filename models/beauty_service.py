from datetime import datetime

from extensions import db


class BeautyService(db.Model):
    __tablename__ = "beauty_service"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=True)
    name = db.Column(db.String(150), nullable=False)
    price = db.Column(db.Integer, nullable=False, default=0)
    duration_minutes = db.Column(db.Integer, nullable=False, default=30)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    product_mappings = db.relationship(
        "BeautyServiceProduct",
        back_populates="service",
        cascade="all, delete-orphan",
        lazy=True,
    )
    appointments = db.relationship("BeautyAppointment", back_populates="service", lazy=True)

    def __repr__(self):
        return f"<BeautyService {self.name}>"
