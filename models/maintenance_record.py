from datetime import datetime

from extensions import db


class MaintenanceRecord(db.Model):
    __tablename__ = "maintenance_record"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    sent_date = db.Column(db.Date, nullable=False)
    workshop_name = db.Column(db.String(150), nullable=False)
    return_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="at_maintenance")
    notes = db.Column(db.Text, nullable=True)
    created_by_employee_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    product = db.relationship("Product", backref=db.backref("maintenance_records", lazy="dynamic"))

    def __repr__(self):
        return f"<MaintenanceRecord {self.id} product={self.product_id} status={self.status}>"
