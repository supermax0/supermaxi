from datetime import datetime

from extensions import db


MOVEMENT_TYPES = {
    "acquisition": "شراء / اقتناء",
    "depreciation": "استهلاك",
    "maintenance": "صيانة",
    "improvement": "تحسين",
    "transfer": "نقل",
    "disposal": "بيع",
    "scrap": "إتلاف",
    "adjustment": "تعديل",
    "impairment": "انخفاض قيمة",
}


class FixedAssetMovement(db.Model):
    __tablename__ = "fixed_asset_movement"

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(
        db.Integer, db.ForeignKey("fixed_asset.id"), nullable=False, index=True
    )
    movement_type = db.Column(db.String(40), nullable=False)
    movement_date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Integer, default=0)
    old_book_value = db.Column(db.Integer, default=0)
    new_book_value = db.Column(db.Integer, default=0)
    journal_entry_id = db.Column(
        db.Integer, db.ForeignKey("journal_entry.id"), nullable=True
    )
    source_type = db.Column(db.String(50), default="fixed_asset")
    source_id = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    asset = db.relationship("FixedAsset", lazy=True)
    journal_entry = db.relationship("JournalEntry", lazy=True)

    def type_label(self):
        return MOVEMENT_TYPES.get(self.movement_type, self.movement_type)

    def __repr__(self):
        return f"<FixedAssetMovement {self.movement_type} asset={self.asset_id}>"
