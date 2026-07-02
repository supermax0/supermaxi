from datetime import datetime

from extensions import db


class FixedAssetDepreciation(db.Model):
    __tablename__ = "fixed_asset_depreciation"
    __table_args__ = (
        db.UniqueConstraint(
            "asset_id", "period_year", "period_month", name="uq_fa_depreciation_period"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(
        db.Integer, db.ForeignKey("fixed_asset.id"), nullable=False, index=True
    )
    period_year = db.Column(db.Integer, nullable=False)
    period_month = db.Column(db.Integer, nullable=False)
    depreciation_amount = db.Column(db.Integer, default=0)
    accumulated_before = db.Column(db.Integer, default=0)
    accumulated_after = db.Column(db.Integer, default=0)
    book_value_before = db.Column(db.Integer, default=0)
    book_value_after = db.Column(db.Integer, default=0)
    journal_entry_id = db.Column(
        db.Integer, db.ForeignKey("journal_entry.id"), nullable=True
    )
    status = db.Column(db.String(20), default="posted")
    posted_at = db.Column(db.DateTime, default=datetime.utcnow)
    posted_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    asset = db.relationship("FixedAsset", lazy=True)
    journal_entry = db.relationship("JournalEntry", lazy=True)

    def __repr__(self):
        return f"<FixedAssetDepreciation asset={self.asset_id} {self.period_year}-{self.period_month}>"
