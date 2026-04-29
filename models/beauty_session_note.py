from datetime import datetime

from extensions import db


class BeautySessionNote(db.Model):
    __tablename__ = "beauty_session_note"

    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("beauty_appointment.id"), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    note = db.Column(db.Text, nullable=True)
    products_used_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    appointment = db.relationship("BeautyAppointment", back_populates="session_notes")
    customer = db.relationship("Customer")

    def __repr__(self):
        return f"<BeautySessionNote appointment={self.appointment_id}>"
