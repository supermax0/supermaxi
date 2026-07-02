from datetime import datetime

from extensions import db


REQUEST_STATUSES = {
    "pending": "بانتظار الموافقة",
    "approved": "موافق عليه",
    "rejected": "مرفوض",
    "completed": "مكتمل",
    "cancelled": "ملغي",
}


class FixedAssetDisposalRequest(db.Model):
    __tablename__ = "fixed_asset_disposal_request"

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(
        db.Integer, db.ForeignKey("fixed_asset.id"), nullable=False, index=True
    )
    disposal_type = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False, index=True)

    disposal_date = db.Column(db.Date, nullable=False)
    sale_amount = db.Column(db.Integer, default=0)
    payment_method = db.Column(db.String(30))
    treasury_account_id = db.Column(
        db.Integer, db.ForeignKey("treasury_account.id"), nullable=True
    )
    buyer_name = db.Column(db.String(200))
    scrap_reason = db.Column(db.Text)
    notes = db.Column(db.Text)

    requested_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    rejection_reason = db.Column(db.Text)
    completed_disposal_id = db.Column(
        db.Integer, db.ForeignKey("fixed_asset_disposal.id"), nullable=True
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    asset = db.relationship("FixedAsset", lazy=True)
    requester = db.relationship("Employee", foreign_keys=[requested_by], lazy=True)
    approver = db.relationship("Employee", foreign_keys=[approved_by], lazy=True)
    completed_disposal = db.relationship(
        "FixedAssetDisposal", foreign_keys=[completed_disposal_id], lazy=True
    )

    def status_label(self):
        return REQUEST_STATUSES.get(self.status, self.status)

    def type_label(self):
        from models.fixed_asset_disposal import DISPOSAL_TYPES

        return DISPOSAL_TYPES.get(self.disposal_type, self.disposal_type)
