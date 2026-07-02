from datetime import datetime

from extensions import db


DEPRECIATION_START_MODES = {
    "purchase": "من تاريخ الشراء",
    "ready": "من تاريخ الجاهزية للاستخدام",
    "next_month": "من بداية الشهر التالي",
}


class FixedAssetSettings(db.Model):
    """إعدادات نظام الأصول الثابتة (صف واحد لكل مستأجر)."""

    __tablename__ = "fixed_asset_settings"

    id = db.Column(db.Integer, primary_key=True, default=1)
    enabled = db.Column(db.Boolean, default=True, nullable=False)
    auto_numbering = db.Column(db.Boolean, default=True, nullable=False)
    code_prefix = db.Column(db.String(20), default="FA", nullable=False)
    allow_code_edit = db.Column(db.Boolean, default=False, nullable=False)
    prevent_delete_posted = db.Column(db.Boolean, default=True, nullable=False)
    allow_without_invoice = db.Column(db.Boolean, default=True, nullable=False)
    require_invoice_attachment = db.Column(db.Boolean, default=False, nullable=False)
    require_location = db.Column(db.Boolean, default=False, nullable=False)
    require_responsible = db.Column(db.Boolean, default=False, nullable=False)

    default_depreciation_method = db.Column(db.String(30), default="straight_line", nullable=False)
    depreciation_start_mode = db.Column(db.String(30), default="purchase", nullable=False)
    allow_manual_depreciation = db.Column(db.Boolean, default=True, nullable=False)
    allow_batch_depreciation = db.Column(db.Boolean, default=True, nullable=False)
    prevent_duplicate_depreciation = db.Column(db.Boolean, default=True, nullable=False)
    require_disposal_approval = db.Column(db.Boolean, default=True, nullable=False)
    enforce_period_close = db.Column(db.Boolean, default=True, nullable=False)

    gain_on_sale_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    loss_on_sale_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    loss_on_scrap_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    maintenance_expense_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    default_journal_description = db.Column(db.Text, nullable=True)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    gain_on_sale_account = db.relationship("Account", foreign_keys=[gain_on_sale_account_id], lazy=True)
    loss_on_sale_account = db.relationship("Account", foreign_keys=[loss_on_sale_account_id], lazy=True)
    loss_on_scrap_account = db.relationship("Account", foreign_keys=[loss_on_scrap_account_id], lazy=True)
    maintenance_expense_account = db.relationship(
        "Account", foreign_keys=[maintenance_expense_account_id], lazy=True
    )

    def depreciation_start_label(self):
        return DEPRECIATION_START_MODES.get(self.depreciation_start_mode, self.depreciation_start_mode)

    def to_dict(self):
        return {
            "enabled": self.enabled,
            "auto_numbering": self.auto_numbering,
            "code_prefix": self.code_prefix,
            "allow_code_edit": self.allow_code_edit,
            "prevent_delete_posted": self.prevent_delete_posted,
            "allow_without_invoice": self.allow_without_invoice,
            "require_invoice_attachment": self.require_invoice_attachment,
            "require_location": self.require_location,
            "require_responsible": self.require_responsible,
            "default_depreciation_method": self.default_depreciation_method,
            "depreciation_start_mode": self.depreciation_start_mode,
            "allow_manual_depreciation": self.allow_manual_depreciation,
            "allow_batch_depreciation": self.allow_batch_depreciation,
            "prevent_duplicate_depreciation": self.prevent_duplicate_depreciation,
            "require_disposal_approval": self.require_disposal_approval,
            "enforce_period_close": self.enforce_period_close,
            "gain_on_sale_account_id": self.gain_on_sale_account_id,
            "loss_on_sale_account_id": self.loss_on_sale_account_id,
            "loss_on_scrap_account_id": self.loss_on_scrap_account_id,
            "maintenance_expense_account_id": self.maintenance_expense_account_id,
            "default_journal_description": self.default_journal_description,
        }
