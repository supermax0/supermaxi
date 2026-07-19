from datetime import datetime

from extensions import db


ASSET_STATUSES = {
    "draft": "مسودة",
    "active": "نشط",
    "under_installation": "تحت التركيب",
    "fully_depreciated": "مستهلك بالكامل",
    "sold": "مباع",
    "scrapped": "تالف / مُستبعد",
}

PAYMENT_METHODS = {
    "cash": "نقداً",
    "bank": "بنك",
    "credit": "آجل",
    "mixed": "جزء نقد وجزء آجل",
    "capital": "إضافة مالك / رصيد افتتاحي",
}


class FixedAsset(db.Model):
    __tablename__ = "fixed_asset"

    id = db.Column(db.Integer, primary_key=True)
    asset_code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    category_id = db.Column(
        db.Integer, db.ForeignKey("fixed_asset_category.id"), nullable=False
    )
    description = db.Column(db.Text)
    serial_number = db.Column(db.String(120))
    barcode = db.Column(db.String(120))
    image_path = db.Column(db.String(500))

    purchase_date = db.Column(db.Date)
    ready_date = db.Column(db.Date)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id"), nullable=True)
    supplier_invoice_no = db.Column(db.String(120))

    purchase_price = db.Column(db.Integer, default=0)
    shipping_cost = db.Column(db.Integer, default=0)
    installation_cost = db.Column(db.Integer, default=0)
    other_cost = db.Column(db.Integer, default=0)
    discount_amount = db.Column(db.Integer, default=0)
    total_cost = db.Column(db.Integer, default=0)

    salvage_value = db.Column(db.Integer, default=0)
    useful_life_months = db.Column(db.Integer, default=0)
    depreciation_method = db.Column(db.String(50), default="straight_line")
    monthly_depreciation = db.Column(db.Integer, default=0)
    accumulated_depreciation = db.Column(db.Integer, default=0)
    book_value = db.Column(db.Integer, default=0)
    is_depreciable = db.Column(db.Boolean, default=True)

    asset_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True)
    accumulated_depreciation_account_id = db.Column(
        db.Integer, db.ForeignKey("account.id"), nullable=True
    )
    depreciation_expense_account_id = db.Column(
        db.Integer, db.ForeignKey("account.id"), nullable=True
    )

    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True)
    location_text = db.Column(db.String(255))
    responsible_user_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)

    status = db.Column(db.String(40), default="draft", nullable=False)
    payment_method = db.Column(db.String(30))
    treasury_account_id = db.Column(
        db.Integer, db.ForeignKey("treasury_account.id"), nullable=True
    )
    paid_amount = db.Column(db.Integer, default=0)
    credit_amount = db.Column(db.Integer, default=0)

    acquisition_journal_entry_id = db.Column(
        db.Integer, db.ForeignKey("journal_entry.id"), nullable=True
    )
    last_depreciation_year = db.Column(db.Integer, nullable=True)
    last_depreciation_month = db.Column(db.Integer, nullable=True)

    created_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    category = db.relationship("FixedAssetCategory", lazy=True)
    supplier = db.relationship("Supplier", lazy=True)
    branch = db.relationship("Branch", lazy=True)
    responsible_user = db.relationship(
        "Employee", foreign_keys=[responsible_user_id], lazy=True
    )
    acquisition_journal_entry = db.relationship(
        "JournalEntry", foreign_keys=[acquisition_journal_entry_id], lazy=True
    )

    def status_label(self):
        return ASSET_STATUSES.get(self.status, self.status)

    def payment_method_label(self):
        return PAYMENT_METHODS.get(self.payment_method or "", self.payment_method or "—")

    def __repr__(self):
        return f"<FixedAsset {self.asset_code} {self.name}>"
