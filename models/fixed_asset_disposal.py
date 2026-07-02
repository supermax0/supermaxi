from datetime import datetime

from extensions import db


DISPOSAL_TYPES = {
    "sale": "بيع",
    "scrap": "إتلاف / شطب",
}


class FixedAssetDisposal(db.Model):
    __tablename__ = "fixed_asset_disposal"

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(
        db.Integer, db.ForeignKey("fixed_asset.id"), nullable=False, index=True
    )
    disposal_type = db.Column(db.String(20), nullable=False)
    disposal_date = db.Column(db.Date, nullable=False)
    sale_amount = db.Column(db.Integer, default=0)
    payment_method = db.Column(db.String(30))
    treasury_account_id = db.Column(
        db.Integer, db.ForeignKey("treasury_account.id"), nullable=True
    )
    buyer_name = db.Column(db.String(200))
    cost_amount = db.Column(db.Integer, default=0)
    accumulated_depreciation_amount = db.Column(db.Integer, default=0)
    book_value = db.Column(db.Integer, default=0)
    gain_amount = db.Column(db.Integer, default=0)
    loss_amount = db.Column(db.Integer, default=0)
    journal_entry_id = db.Column(
        db.Integer, db.ForeignKey("journal_entry.id"), nullable=True
    )
    scrap_reason = db.Column(db.Text)
    attachment_path = db.Column(db.String(500))
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    asset = db.relationship("FixedAsset", lazy=True)
    journal_entry = db.relationship("JournalEntry", lazy=True)

    def type_label(self):
        return DISPOSAL_TYPES.get(self.disposal_type, self.disposal_type)

    def __repr__(self):
        return f"<FixedAssetDisposal {self.disposal_type} asset={self.asset_id}>"
