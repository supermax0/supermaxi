import json

from sqlalchemy.orm import validates

from extensions import db
from datetime import datetime


def catalog_category_from_meta(raw: str | None) -> str:
    """Extract the normalized mobile/store category from legacy product JSON."""
    try:
        parsed = json.loads((raw or "").strip())
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    return str(parsed.get("category") or parsed.get("store_badge") or "").strip()[:120]

class Product(db.Model):
    __tablename__ = "product"

    id = db.Column(db.Integer, primary_key=True)

    # Tenant (الشركة المالكة لهذا المنتج)
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey("tenant.id"),
        nullable=True
    )

    name = db.Column(db.String(150), nullable=False)
    sku = db.Column(db.String(100), nullable=True)
    barcode = db.Column(db.String(100), nullable=True)
    buy_price = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'barcode', name='_product_barcode_tenant_uc'),
    )
    sale_price = db.Column(db.Integer, nullable=False)

    shipping_cost = db.Column(db.Integer, default=0)
    marketing_cost = db.Column(db.Integer, default=0)

    opening_stock = db.Column(db.Integer, default=0)  # المخزون الافتتاحي
    quantity = db.Column(db.Integer, default=0)  # المخزون الحالي (يتم حسابه تلقائياً)
    active = db.Column(db.Boolean, default=True)
    store_visible = db.Column(db.Boolean, default=True)
    
    # حد التنبيه لانخفاض المخزون (الرقم الذي إذا وصل إليه المخزون أو قل عنه يظهر التنبيه)
    low_stock_threshold = db.Column(db.Integer, default=5)

    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(512), nullable=True)
    skin_type = db.Column(db.String(100), nullable=True)
    usage_type = db.Column(db.String(100), nullable=True)
    requires_patch_test = db.Column(db.Boolean, default=False)
    expiry_date = db.Column(db.Date, nullable=True)
    opened_date = db.Column(db.Date, nullable=True)
    batch_number = db.Column(db.String(100), nullable=True)
    # حقول إضافية من نموذج الإدخال المتقدم (وحدة، ضريبة، رف، …) JSON
    meta_json = db.Column(db.Text, nullable=True)
    # Indexed projection of the category kept in meta_json for fast mobile
    # filtering and correct pagination on large catalogs.
    catalog_category = db.Column(db.String(120), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 🔗 الربط الصحيح
    order_items = db.relationship(
        "OrderItem",
        back_populates="product",
        cascade="all, delete-orphan"
    )

    @property
    def expected_profit(self):
        return self.sale_price - (
            self.buy_price +
            self.shipping_cost +
            self.marketing_cost
        )
    
    @property
    def current_stock(self):
        """المخزون الحالي (المخزون الافتتاحي + المشتريات - المبيعات)"""
        # يمكن حسابها من opening_stock + total_purchases - total_sales
        # لكن حالياً نستخدم quantity المباشر
        return self.quantity
    
    def get_total_purchased(self):
        """إجمالي الكميات المشتراة"""
        if hasattr(self, 'purchases'):
            return sum(p.quantity for p in self.purchases) if self.purchases else 0
        return 0
    
    def get_total_sold(self):
        """إجمالي الكميات المباعة"""
        if hasattr(self, 'order_items'):
            return sum(item.quantity for item in self.order_items) if self.order_items else 0
        return 0

    purchases = db.relationship(
    "Purchase",
    backref="product",
    lazy=True,
    cascade="all, delete"
)



    @validates("meta_json")
    def _sync_catalog_category(self, _key, value):
        self.catalog_category = catalog_category_from_meta(value)
        return value

    def __repr__(self):
        return f"<Product {self.name}>"
