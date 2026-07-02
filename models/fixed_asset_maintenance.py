from datetime import datetime

from extensions import db


MAINTENANCE_TYPES = {
    "regular": "صيانة عادية",
    "improvement": "تحسين رأسمالي",
}


class FixedAssetMaintenance(db.Model):
    __tablename__ = "fixed_asset_maintenance"

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(
        db.Integer, db.ForeignKey("fixed_asset.id"), nullable=False, index=True
    )
    maintenance_date = db.Column(db.Date, nullable=False)
    maintenance_type = db.Column(db.String(30), default="regular")
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id"), nullable=True)
    amount = db.Column(db.Integer, default=0)
    payment_method = db.Column(db.String(30), default="cash")
    treasury_account_id = db.Column(
        db.Integer, db.ForeignKey("treasury_account.id"), nullable=True
    )
    is_capitalized = db.Column(db.Boolean, default=False)
    journal_entry_id = db.Column(
        db.Integer, db.ForeignKey("journal_entry.id"), nullable=True
    )
    description = db.Column(db.Text)
    attachment_path = db.Column(db.String(500))
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    asset = db.relationship("FixedAsset", lazy=True)
    supplier = db.relationship("Supplier", lazy=True)
    journal_entry = db.relationship("JournalEntry", lazy=True)

    def type_label(self):
        return MAINTENANCE_TYPES.get(self.maintenance_type, self.maintenance_type)

    def __repr__(self):
        return f"<FixedAssetMaintenance asset={self.asset_id} type={self.maintenance_type}>"
