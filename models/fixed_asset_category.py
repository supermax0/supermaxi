from datetime import datetime

from extensions import db


class FixedAssetCategory(db.Model):
    __tablename__ = "fixed_asset_category"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    asset_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    accumulated_depreciation_account_id = db.Column(
        db.Integer, db.ForeignKey("account.id"), nullable=True
    )
    depreciation_expense_account_id = db.Column(
        db.Integer, db.ForeignKey("account.id"), nullable=True
    )
    default_useful_life_months = db.Column(db.Integer, default=60)
    default_salvage_value = db.Column(db.Integer, default=0)
    is_depreciable = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    asset_account = db.relationship(
        "Account", foreign_keys=[asset_account_id], lazy=True
    )
    accumulated_depreciation_account = db.relationship(
        "Account", foreign_keys=[accumulated_depreciation_account_id], lazy=True
    )
    depreciation_expense_account = db.relationship(
        "Account", foreign_keys=[depreciation_expense_account_id], lazy=True
    )

    def __repr__(self):
        return f"<FixedAssetCategory {self.name}>"
