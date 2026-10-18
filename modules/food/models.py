"""Food workspace models.

The existing Product, Invoice and Purchase tables remain the system of record.
Food-only packaging, variant inventory and immutable line snapshots live here
so general Finora companies keep their original behaviour.
"""
from __future__ import annotations

from datetime import date, datetime

from extensions import db


class FoodProductProfile(db.Model):
    __tablename__ = "food_product_profile"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "product_id", name="uq_food_profile_tenant_product"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    short_name = db.Column(db.String(100), nullable=True)
    brand = db.Column(db.String(120), nullable=True, index=True)
    category = db.Column(db.String(120), nullable=True, index=True)
    subcategory = db.Column(db.String(120), nullable=True, index=True)
    origin_country = db.Column(db.String(100), nullable=True)
    default_supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id"), nullable=True)
    supplier_product_code = db.Column(db.String(120), nullable=True)
    track_stock = db.Column(db.Boolean, nullable=False, default=True)
    track_expiry = db.Column(db.Boolean, nullable=False, default=False)
    track_batches = db.Column(db.Boolean, nullable=False, default=False)
    shelf_life_value = db.Column(db.Integer, nullable=True)
    shelf_life_unit = db.Column(db.String(20), nullable=True)
    expiry_warning_days = db.Column(db.Integer, nullable=False, default=30)
    issue_policy = db.Column(db.String(10), nullable=False, default="FIFO")
    reorder_quantity = db.Column(db.Integer, nullable=False, default=0)
    maximum_stock = db.Column(db.Integer, nullable=True)
    storage_location = db.Column(db.String(255), nullable=True)
    storage_type = db.Column(db.String(20), nullable=False, default="normal")
    return_policy = db.Column(db.String(40), nullable=False, default="normal")
    taxable = db.Column(db.Boolean, nullable=False, default=False)
    tax_rate = db.Column(db.Numeric(7, 3), nullable=False, default=0)
    auto_wholesale_pricing = db.Column(db.Boolean, nullable=False, default=True)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = db.relationship("Product", lazy=True)
    variants = db.relationship(
        "FoodProductVariant", back_populates="profile", cascade="all, delete-orphan", lazy=True
    )


class FoodProductVariant(db.Model):
    __tablename__ = "food_product_variant"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "sku", name="uq_food_variant_tenant_sku"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("food_product_profile.id"), nullable=False, index=True)
    variant_name = db.Column(db.String(150), nullable=False)
    flavor = db.Column(db.String(100), nullable=True)
    size = db.Column(db.String(80), nullable=True)
    size_value = db.Column(db.Numeric(12, 3), nullable=True)
    size_unit = db.Column(db.String(20), nullable=True)
    sku = db.Column(db.String(100), nullable=True, index=True)
    image_url = db.Column(db.String(512), nullable=True)
    stock_base = db.Column(db.Integer, nullable=False, default=0)
    average_cost = db.Column(db.Integer, nullable=False, default=0)
    minimum_stock = db.Column(db.Integer, nullable=False, default=0)
    reorder_quantity = db.Column(db.Integer, nullable=False, default=0)
    maximum_stock = db.Column(db.Integer, nullable=True)
    storage_location = db.Column(db.String(255), nullable=True)
    default_sale_unit_id = db.Column(db.Integer, nullable=True)
    default_purchase_unit_id = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    profile = db.relationship("FoodProductProfile", back_populates="variants")
    units = db.relationship(
        "FoodProductUnit", back_populates="variant", cascade="all, delete-orphan", lazy=True
    )


class FoodProductUnit(db.Model):
    __tablename__ = "food_product_unit"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "variant_id", "unit_name", name="uq_food_unit_variant_name"),
        db.CheckConstraint("conversion_factor > 0", name="ck_food_unit_factor_positive"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("food_product_variant.id"), nullable=False, index=True)
    unit_name = db.Column(db.String(80), nullable=False)
    conversion_factor = db.Column(db.Integer, nullable=False, default=1)
    parent_unit_id = db.Column(db.Integer, db.ForeignKey("food_product_unit.id"), nullable=True)
    parent_multiplier = db.Column(db.Integer, nullable=True)
    retail_price = db.Column(db.Integer, nullable=False, default=0)
    wholesale_price = db.Column(db.Integer, nullable=False, default=0)
    wholesale_minimum = db.Column(db.Integer, nullable=False, default=1)
    auto_wholesale = db.Column(db.Boolean, nullable=False, default=False)
    purchase_price = db.Column(db.Integer, nullable=True)
    is_base = db.Column(db.Boolean, nullable=False, default=False)
    can_sell = db.Column(db.Boolean, nullable=False, default=True)
    can_purchase = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)

    variant = db.relationship("FoodProductVariant", back_populates="units")
    barcodes = db.relationship(
        "FoodProductBarcode", back_populates="unit", cascade="all, delete-orphan", lazy=True
    )
    parent_unit = db.relationship("FoodProductUnit", remote_side=[id], lazy=True)


class FoodProductBarcode(db.Model):
    __tablename__ = "food_product_barcode"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "barcode", name="uq_food_barcode_tenant_value"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("food_product_profile.id"), nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("food_product_variant.id"), nullable=False, index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("food_product_unit.id"), nullable=False, index=True)
    barcode = db.Column(db.String(160), nullable=False, index=True)
    is_primary = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True)

    unit = db.relationship("FoodProductUnit", back_populates="barcodes")


class FoodInventoryMovement(db.Model):
    __tablename__ = "food_inventory_movement"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("food_product_variant.id"), nullable=False, index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("food_product_unit.id"), nullable=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("food_expiry_batch.id"), nullable=True)
    movement_type = db.Column(db.String(30), nullable=False, index=True)
    quantity_base = db.Column(db.Integer, nullable=False)
    quantity_before = db.Column(db.Integer, nullable=False)
    quantity_after = db.Column(db.Integer, nullable=False)
    reference_type = db.Column(db.String(40), nullable=True)
    reference_id = db.Column(db.Integer, nullable=True)
    note = db.Column(db.Text, nullable=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class FoodExpiryBatch(db.Model):
    __tablename__ = "food_expiry_batch"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("food_product_variant.id"), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    received_unit_id = db.Column(db.Integer, db.ForeignKey("food_product_unit.id"), nullable=True)
    batch_number = db.Column(db.String(100), nullable=True)
    production_date = db.Column(db.Date, nullable=True)
    expiry_date = db.Column(db.Date, nullable=False, index=True)
    quantity_base = db.Column(db.Integer, nullable=False, default=0)
    reserved_quantity_base = db.Column(db.Integer, nullable=False, default=0)
    received_quantity = db.Column(db.Integer, nullable=True)
    unit_factor_snapshot = db.Column(db.Integer, nullable=False, default=1)
    unit_cost_snapshot = db.Column(db.Integer, nullable=False, default=0)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id"), nullable=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchase.id"), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="sellable", index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class FoodWarehouseStock(db.Model):
    __tablename__ = "food_warehouse_stock"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "warehouse_id", "variant_id", name="uq_food_stock_warehouse_variant"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("food_product_variant.id"), nullable=False, index=True)
    opening_base = db.Column(db.Integer, nullable=False, default=0)
    stock_base = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class FoodProductPriceTier(db.Model):
    __tablename__ = "food_product_price_tier"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "unit_id", "tier_code", "minimum_quantity", name="uq_food_price_tier"),
        db.CheckConstraint("minimum_quantity > 0", name="ck_food_price_tier_min_positive"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("food_product_unit.id"), nullable=False, index=True)
    tier_code = db.Column(db.String(30), nullable=False, default="WHOLESALE")
    minimum_quantity = db.Column(db.Integer, nullable=False, default=1)
    maximum_quantity = db.Column(db.Integer, nullable=True)
    price = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)


class FoodProductAuditLog(db.Model):
    __tablename__ = "food_product_audit_log"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    profile_id = db.Column(db.Integer, db.ForeignKey("food_product_profile.id"), nullable=False, index=True)
    action = db.Column(db.String(40), nullable=False, index=True)
    field_name = db.Column(db.String(80), nullable=True)
    before_value = db.Column(db.Text, nullable=True)
    after_value = db.Column(db.Text, nullable=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class FoodSaleItemSnapshot(db.Model):
    __tablename__ = "food_sale_item_snapshot"
    __table_args__ = (
        db.UniqueConstraint("order_item_id", name="uq_food_sale_snapshot_item"),
        db.CheckConstraint("sale_mode IN ('RETAIL', 'WHOLESALE')", name="ck_food_sale_mode"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    order_item_id = db.Column(db.Integer, db.ForeignKey("order_item.id"), nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("food_product_variant.id"), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey("food_product_unit.id"), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True)
    sale_mode = db.Column(db.String(20), nullable=False)
    variant_name_snapshot = db.Column(db.String(150), nullable=False)
    unit_name_snapshot = db.Column(db.String(80), nullable=False)
    unit_factor_snapshot = db.Column(db.Integer, nullable=False)
    unit_price_snapshot = db.Column(db.Integer, nullable=False)
    cost_snapshot = db.Column(db.Integer, nullable=False, default=0)
    barcode_snapshot = db.Column(db.String(160), nullable=True)
    quantity_base = db.Column(db.Integer, nullable=False)
    product_name_snapshot = db.Column(db.String(150), nullable=True)
    quantity_snapshot = db.Column(db.Numeric(18, 3), nullable=True)
    discount_snapshot = db.Column(db.Integer, nullable=False, default=0)
    tax_snapshot = db.Column(db.Integer, nullable=False, default=0)
    line_total_snapshot = db.Column(db.Integer, nullable=True)
    note_snapshot = db.Column(db.Text, nullable=True)

    order_item = db.relationship("OrderItem", lazy=True)


class FoodSaleBatchAllocation(db.Model):
    __tablename__ = "food_sale_batch_allocation"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    sale_snapshot_id = db.Column(
        db.Integer, db.ForeignKey("food_sale_item_snapshot.id"), nullable=False, index=True
    )
    batch_id = db.Column(
        db.Integer, db.ForeignKey("food_expiry_batch.id"), nullable=False, index=True
    )
    quantity_base = db.Column(db.Integer, nullable=False)


class FoodPurchaseItemSnapshot(db.Model):
    __tablename__ = "food_purchase_item_snapshot"
    __table_args__ = (db.UniqueConstraint("purchase_item_id", name="uq_food_purchase_snapshot_item"),)

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    purchase_item_id = db.Column(db.Integer, db.ForeignKey("purchase_item.id"), nullable=False, index=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("food_product_variant.id"), nullable=False)
    unit_id = db.Column(db.Integer, db.ForeignKey("food_product_unit.id"), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True)
    variant_name_snapshot = db.Column(db.String(150), nullable=False)
    unit_name_snapshot = db.Column(db.String(80), nullable=False)
    unit_factor_snapshot = db.Column(db.Integer, nullable=False)
    unit_price_snapshot = db.Column(db.Integer, nullable=False, default=0)
    barcode_snapshot = db.Column(db.String(160), nullable=True)
    bonus_quantity = db.Column(db.Integer, nullable=False, default=0)
    expiry_date = db.Column(db.Date, nullable=True)
    quantity_base = db.Column(db.Integer, nullable=False)


class FoodSettings(db.Model):
    __tablename__ = "food_settings"
    __table_args__ = (db.UniqueConstraint("tenant_id", name="uq_food_settings_tenant"),)

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    allow_negative_stock = db.Column(db.Boolean, nullable=False, default=False)
    default_sale_mode = db.Column(db.String(20), nullable=False, default="RETAIL")
    expiry_warning_days = db.Column(db.Integer, nullable=False, default=30)
    negative_stock_policy = db.Column(db.String(30), nullable=False, default="prevent")
    hide_out_of_stock = db.Column(db.Boolean, nullable=False, default=False)
    auto_print = db.Column(db.String(20), nullable=False, default="ask")
    fast_pos_mode = db.Column(db.Boolean, nullable=False, default=False)
    scale_barcode_enabled = db.Column(db.Boolean, nullable=False, default=False)
    scale_barcode_prefix = db.Column(db.String(10), nullable=False, default="20")
    scale_barcode_product_digits = db.Column(db.Integer, nullable=False, default=5)
    scale_barcode_value_digits = db.Column(db.Integer, nullable=False, default=5)
    scale_barcode_divisor = db.Column(db.Integer, nullable=False, default=1000)
    default_receivable_days = db.Column(db.Integer, nullable=False, default=30)
    default_payable_days = db.Column(db.Integer, nullable=False, default=30)
    default_issue_policy = db.Column(db.String(10), nullable=False, default="FEFO")
    receipt_footer = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class FoodCustomerProfile(db.Model):
    __tablename__ = "food_customer_profile"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "customer_id", name="uq_food_customer_profile"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False, index=True)
    customer_code = db.Column(db.String(60), nullable=True, index=True)
    company_name = db.Column(db.String(150), nullable=True, index=True)
    credit_limit = db.Column(db.Integer, nullable=True)
    payment_term_days = db.Column(db.Integer, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)


class FoodSupplierProfile(db.Model):
    __tablename__ = "food_supplier_profile"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "supplier_id", name="uq_food_supplier_profile"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id"), nullable=False, index=True)
    payment_term_days = db.Column(db.Integer, nullable=True)
    active = db.Column(db.Boolean, nullable=False, default=True)


class FoodCashSession(db.Model):
    """Opening balance and cash count for one business day / warehouse."""

    __tablename__ = "food_cash_session"
    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id", "business_date", "warehouse_id",
            name="uq_food_cash_session_day_wh",
        ),
        db.CheckConstraint("status IN ('open', 'closed')", name="ck_food_cash_session_status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    business_date = db.Column(db.Date, nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    opening_cash = db.Column(db.Integer, nullable=False, default=0)
    expected_closing_cash = db.Column(db.Integer, nullable=True)
    actual_closing_cash = db.Column(db.Integer, nullable=True)
    cash_variance = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    opened_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    closed_by = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    note = db.Column(db.Text, nullable=True)
    variance_reason = db.Column(db.Text, nullable=True)
    opened_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)


class FoodExpense(db.Model):
    """Food-workspace operating expenses (cash out)."""

    __tablename__ = "food_expense"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100), nullable=True)
    amount = db.Column(db.Integer, nullable=False, default=0)
    expense_date = db.Column(db.Date, nullable=False, index=True)
    note = db.Column(db.String(255), nullable=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class FoodCheckoutRequest(db.Model):
    """Tenant-scoped idempotency record for one completed checkout."""

    __tablename__ = "food_checkout_request"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "idempotency_key", name="uq_food_checkout_tenant_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    idempotency_key = db.Column(db.String(120), nullable=False, index=True)
    request_fingerprint = db.Column(db.String(64), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class FoodHeldSale(db.Model):
    __tablename__ = "food_held_sale"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "hold_no", name="uq_food_hold_tenant_no"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    hold_no = db.Column(db.String(40), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=True, index=True)
    default_sale_mode = db.Column(db.String(20), nullable=False, default="RETAIL")
    cart_json = db.Column(db.Text, nullable=False)
    invoice_discount = db.Column(db.Integer, nullable=False, default=0)
    note = db.Column(db.Text, nullable=True)
    total_snapshot = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="held", index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class FoodSaleReturn(db.Model):
    __tablename__ = "food_sale_return"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "return_no", name="uq_food_return_tenant_no"),
        db.UniqueConstraint("tenant_id", "idempotency_key", name="uq_food_return_tenant_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    return_no = db.Column(db.String(50), nullable=False, index=True)
    idempotency_key = db.Column(db.String(120), nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    refund_method = db.Column(db.String(40), nullable=False, default="cash")
    total = db.Column(db.Integer, nullable=False, default=0)
    reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class FoodSaleReturnLine(db.Model):
    __tablename__ = "food_sale_return_line"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    return_id = db.Column(db.Integer, db.ForeignKey("food_sale_return.id"), nullable=False, index=True)
    sale_snapshot_id = db.Column(db.Integer, db.ForeignKey("food_sale_item_snapshot.id"), nullable=False, index=True)
    quantity = db.Column(db.Numeric(18, 3), nullable=False)
    quantity_base = db.Column(db.Numeric(18, 3), nullable=False)
    amount = db.Column(db.Integer, nullable=False)


class FoodSaleReturnBatchAllocation(db.Model):
    __tablename__ = "food_sale_return_batch_allocation"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    return_line_id = db.Column(db.Integer, db.ForeignKey("food_sale_return_line.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("food_expiry_batch.id"), nullable=False, index=True)
    quantity_base = db.Column(db.Numeric(18, 3), nullable=False)


class FoodPosAuditLog(db.Model):
    __tablename__ = "food_pos_audit_log"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True, index=True)
    action = db.Column(db.String(50), nullable=False, index=True)
    entity_type = db.Column(db.String(40), nullable=True)
    entity_id = db.Column(db.Integer, nullable=True)
    details_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class FoodPurchaseReturn(db.Model):
    """Supplier purchase return document — does not delete the original purchase."""
    __tablename__ = "food_purchase_return"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "return_no", name="uq_food_purchase_return_no"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    return_no = db.Column(db.String(50), nullable=False, index=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchase.id"), nullable=False, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id"), nullable=False, index=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=True, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)
    reason = db.Column(db.String(80), nullable=True)
    note = db.Column(db.Text, nullable=True)
    settlement = db.Column(db.String(20), nullable=False, default="credit")  # credit | cash
    total = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class FoodPurchaseReturnLine(db.Model):
    __tablename__ = "food_purchase_return_line"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    return_id = db.Column(db.Integer, db.ForeignKey("food_purchase_return.id"), nullable=False, index=True)
    purchase_item_id = db.Column(db.Integer, db.ForeignKey("purchase_item.id"), nullable=False, index=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey("food_purchase_item_snapshot.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("food_expiry_batch.id"), nullable=True, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    quantity_base = db.Column(db.Integer, nullable=False, default=0)
    amount = db.Column(db.Integer, nullable=False, default=0)


class FoodPromotion(db.Model):
    """Backend-owned POS promotion rule; the cashier only receives its result."""
    __tablename__ = "food_promotion"
    __table_args__ = (
        db.Index("ix_food_promotion_tenant_active_window", "tenant_id", "active", "starts_at", "ends_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    scope_type = db.Column(db.String(20), nullable=False, default="all")
    scope_value = db.Column(db.String(150), nullable=True, index=True)
    discount_type = db.Column(db.String(20), nullable=False, default="percent")
    discount_value = db.Column(db.Numeric(18, 3), nullable=False, default=0)
    minimum_quantity = db.Column(db.Numeric(18, 3), nullable=False, default=1)
    priority = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    starts_at = db.Column(db.DateTime, nullable=True)
    ends_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


FOOD_MODELS = (
    FoodProductProfile,
    FoodProductVariant,
    FoodProductUnit,
    FoodProductBarcode,
    FoodExpiryBatch,
    FoodInventoryMovement,
    FoodWarehouseStock,
    FoodProductPriceTier,
    FoodProductAuditLog,
    FoodSaleItemSnapshot,
    FoodSaleBatchAllocation,
    FoodPurchaseItemSnapshot,
    FoodSettings,
    FoodCustomerProfile,
    FoodSupplierProfile,
    FoodCashSession,
    FoodExpense,
    FoodCheckoutRequest,
    FoodHeldSale,
    FoodSaleReturn,
    FoodSaleReturnLine,
    FoodSaleReturnBatchAllocation,
    FoodPosAuditLog,
    FoodPurchaseReturn,
    FoodPurchaseReturnLine,
    FoodPromotion,
)
