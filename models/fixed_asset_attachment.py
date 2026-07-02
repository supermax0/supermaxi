from datetime import datetime

from extensions import db


ATTACHMENT_TYPES = {
    "invoice": "فاتورة الشراء",
    "warranty": "الضمان",
    "photo": "صور الأصل",
    "maintenance": "سند صيانة",
    "insurance": "عقد التأمين",
    "sale": "مستند البيع",
    "scrap": "محضر الإتلاف",
    "other": "أخرى",
}


class FixedAssetAttachment(db.Model):
    __tablename__ = "fixed_asset_attachment"

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(
        db.Integer, db.ForeignKey("fixed_asset.id"), nullable=False, index=True
    )
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(120))
    attachment_type = db.Column(db.String(40), default="other", nullable=False)
    file_size = db.Column(db.Integer, nullable=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    asset = db.relationship("FixedAsset", backref="attachments", lazy=True)
    uploader = db.relationship("Employee", foreign_keys=[uploaded_by], lazy=True)

    def type_label(self):
        return ATTACHMENT_TYPES.get(self.attachment_type, self.attachment_type)

    def is_image(self):
        ft = (self.file_type or "").lower()
        return ft.startswith("image/") or (self.file_name or "").lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp", ".gif")
        )
