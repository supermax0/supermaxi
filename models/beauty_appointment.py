from datetime import datetime

from extensions import db


class BeautyAppointment(db.Model):
    __tablename__ = "beauty_appointment"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("beauty_service.id"), nullable=False)
    appointment_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="pending")
    notes = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship("Customer")
    service = db.relationship("BeautyService", back_populates="appointments")
    session_notes = db.relationship(
        "BeautySessionNote",
        back_populates="appointment",
        cascade="all, delete-orphan",
        lazy=True,
    )

    def __repr__(self):
        return f"<BeautyAppointment {self.id} {self.status}>"
