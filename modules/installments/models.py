from __future__ import annotations

from datetime import datetime

from extensions import db


class InstallmentCustomerAccount(db.Model):
    __tablename__ = "installment_customer_accounts"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "phone", name="uq_installment_customer_account_tenant_phone"),
        db.UniqueConstraint("tenant_id", "customer_id", name="uq_installment_customer_account_tenant_customer"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False, index=True)
    phone = db.Column(db.String(30), nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship("Customer", lazy=True)


class InstallmentProduct(db.Model):
    __tablename__ = "installment_products"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "slug", name="uq_installment_product_tenant_slug"),
        db.UniqueConstraint("tenant_id", "product_id", name="uq_installment_product_tenant_product"),
        db.CheckConstraint("cash_price >= 0", name="ck_installment_product_cash_price"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    slug = db.Column(db.String(180), nullable=False)
    short_description = db.Column(db.String(500))
    full_description = db.Column(db.Text)
    cash_price = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(120), index=True)
    warranty_information = db.Column(db.Text)
    delivery_information = db.Column(db.Text)
    seo_title = db.Column(db.String(180))
    seo_description = db.Column(db.String(500))
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    featured = db.Column(db.Boolean, nullable=False, default=False, index=True)
    show_cash_price = db.Column(db.Boolean, nullable=False, default=True)
    show_stock = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = db.relationship("Product", lazy=True)
    media = db.relationship("InstallmentProductMedia", back_populates="installment_product", cascade="all, delete-orphan", order_by="InstallmentProductMedia.sort_order")
    plans = db.relationship("InstallmentPlan", back_populates="installment_product", cascade="all, delete-orphan", order_by="InstallmentPlan.sort_order")


class InstallmentProductMedia(db.Model):
    __tablename__ = "installment_product_media"
    __table_args__ = (
        db.CheckConstraint("media_type IN ('image','video')", name="ck_installment_media_type"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, index=True)
    installment_product_id = db.Column(db.Integer, db.ForeignKey("installment_products.id", ondelete="CASCADE"), nullable=False, index=True)
    media_type = db.Column(db.String(10), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    is_main = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    installment_product = db.relationship("InstallmentProduct", back_populates="media")


class InstallmentPlan(db.Model):
    __tablename__ = "installment_plans"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "installment_product_id", "months", name="uq_installment_plan_product_months"),
        db.CheckConstraint("months > 0 AND months <= 120", name="ck_installment_plan_months"),
        db.CheckConstraint("pricing_mode IN ('percentage','fixed_total','fixed_monthly')", name="ck_installment_plan_pricing_mode"),
        db.CheckConstraint("down_payment_type IN ('none','fixed','percentage')", name="ck_installment_plan_down_type"),
        db.CheckConstraint("processing_fee >= 0", name="ck_installment_plan_fee"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, index=True)
    installment_product_id = db.Column(db.Integer, db.ForeignKey("installment_products.id", ondelete="CASCADE"), nullable=False, index=True)
    months = db.Column(db.Integer, nullable=False)
    pricing_mode = db.Column(db.String(20), nullable=False)
    markup_percentage = db.Column(db.Numeric(9, 4))
    fixed_total_price = db.Column(db.Integer)
    fixed_monthly_amount = db.Column(db.Integer)
    down_payment_type = db.Column(db.String(20), nullable=False, default="none")
    down_payment_value = db.Column(db.Numeric(14, 4), nullable=False, default=0)
    processing_fee = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    installment_product = db.relationship("InstallmentProduct", back_populates="plans")


class InstallmentApplication(db.Model):
    __tablename__ = "installment_applications"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "application_number", name="uq_installment_application_number"),
        db.UniqueConstraint("tenant_id", "idempotency_key", name="uq_installment_application_idempotency"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, index=True)
    application_number = db.Column(db.String(40), nullable=False, index=True)
    idempotency_key = db.Column(db.String(80), nullable=False)
    tracking_token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), index=True)
    customer_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(30), nullable=False, index=True)
    phone2 = db.Column(db.String(30))
    city = db.Column(db.String(100), nullable=False)
    area = db.Column(db.String(150))
    address = db.Column(db.String(300), nullable=False)
    nearest_landmark = db.Column(db.String(250))
    employer = db.Column(db.String(200))
    monthly_income = db.Column(db.Integer)
    notes = db.Column(db.Text)
    internal_notes = db.Column(db.Text)
    status = db.Column(db.String(30), nullable=False, default="new", index=True)
    rejection_reason = db.Column(db.Text)
    assigned_employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), index=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("employee.id"))
    reviewed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship("Customer", lazy=True)
    items = db.relationship("InstallmentApplicationItem", back_populates="application", cascade="all, delete-orphan")
    documents = db.relationship("InstallmentApplicationDocument", back_populates="application", cascade="all, delete-orphan")
    activities = db.relationship("InstallmentApplicationActivity", back_populates="application", cascade="all, delete-orphan", order_by="InstallmentApplicationActivity.created_at")
    contract = db.relationship("InstallmentContract", back_populates="application", uselist=False)


class InstallmentApplicationItem(db.Model):
    __tablename__ = "installment_application_items"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, index=True)
    application_id = db.Column(db.Integer, db.ForeignKey("installment_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    installment_product_id = db.Column(db.Integer, db.ForeignKey("installment_products.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("installment_plans.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    product_name_snapshot = db.Column(db.String(180), nullable=False, default="")
    sku_snapshot = db.Column(db.String(100))
    main_image_snapshot = db.Column(db.String(500))
    months_snapshot = db.Column(db.Integer, nullable=False, default=1)
    pricing_mode_snapshot = db.Column(db.String(20), nullable=False, default="percentage")
    markup_snapshot = db.Column(db.Numeric(9, 4))
    cash_price = db.Column(db.Integer, nullable=False)
    installment_total = db.Column(db.Integer, nullable=False)
    down_payment = db.Column(db.Integer, nullable=False)
    financed_amount = db.Column(db.Integer, nullable=False)
    monthly_payment = db.Column(db.Integer, nullable=False)
    final_payment = db.Column(db.Integer, nullable=False)
    processing_fee = db.Column(db.Integer, nullable=False, default=0)
    calculation_json = db.Column(db.Text, nullable=False)

    application = db.relationship("InstallmentApplication", back_populates="items")
    installment_product = db.relationship("InstallmentProduct", lazy=True)
    product = db.relationship("Product", lazy=True)
    plan = db.relationship("InstallmentPlan", lazy=True)


class InstallmentApplicationDocument(db.Model):
    __tablename__ = "installment_application_documents"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, index=True)
    application_id = db.Column(db.Integer, db.ForeignKey("installment_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    document_type = db.Column(db.String(50), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    application = db.relationship("InstallmentApplication", back_populates="documents")


class InstallmentApplicationActivity(db.Model):
    __tablename__ = "installment_application_activities"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, index=True)
    application_id = db.Column(db.Integer, db.ForeignKey("installment_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("employee.id"))
    action = db.Column(db.String(50), nullable=False)
    from_status = db.Column(db.String(30))
    to_status = db.Column(db.String(30))
    note = db.Column(db.Text)
    metadata_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    application = db.relationship("InstallmentApplication", back_populates="activities")


class InstallmentContract(db.Model):
    __tablename__ = "installment_contracts"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "contract_number", name="uq_installment_contract_number"),
        db.CheckConstraint("total_amount >= 0 AND paid_amount >= 0 AND remaining_amount >= 0", name="ck_installment_contract_amounts"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, index=True)
    application_id = db.Column(db.Integer, db.ForeignKey("installment_applications.id"), nullable=False, unique=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False, unique=True)
    contract_number = db.Column(db.String(40), nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default="active", index=True)
    total_amount = db.Column(db.Integer, nullable=False)
    down_payment = db.Column(db.Integer, nullable=False, default=0)
    paid_amount = db.Column(db.Integer, nullable=False, default=0)
    remaining_amount = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    first_due_date = db.Column(db.Date)
    financed_amount = db.Column(db.Integer, nullable=False, default=0)
    number_of_installments = db.Column(db.Integer, nullable=False, default=0)
    created_by_id = db.Column(db.Integer, db.ForeignKey("employee.id"))
    approved_by_id = db.Column(db.Integer, db.ForeignKey("employee.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    application = db.relationship("InstallmentApplication", back_populates="contract")
    customer = db.relationship("Customer", lazy=True)
    invoice = db.relationship("Invoice", lazy=True)
    schedules = db.relationship("InstallmentSchedule", back_populates="contract", cascade="all, delete-orphan", order_by="InstallmentSchedule.sequence")
    items = db.relationship("InstallmentContractItem", back_populates="contract", cascade="all, delete-orphan")
    payments = db.relationship("InstallmentPayment", back_populates="contract")


class InstallmentContractItem(db.Model):
    __tablename__ = "installment_contract_items"
    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="ck_installment_contract_item_quantity"),
        db.CheckConstraint("installment_total >= 0 AND financed_amount >= 0", name="ck_installment_contract_item_amounts"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("installment_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    application_item_id = db.Column(db.Integer, db.ForeignKey("installment_application_items.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    product_name = db.Column(db.String(180), nullable=False)
    sku = db.Column(db.String(100))
    main_image = db.Column(db.String(500))
    quantity = db.Column(db.Integer, nullable=False)
    months = db.Column(db.Integer, nullable=False)
    pricing_mode = db.Column(db.String(20), nullable=False)
    cash_price = db.Column(db.Integer, nullable=False)
    installment_total = db.Column(db.Integer, nullable=False)
    fees = db.Column(db.Integer, nullable=False, default=0)
    down_payment = db.Column(db.Integer, nullable=False, default=0)
    financed_amount = db.Column(db.Integer, nullable=False)
    calculation_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    contract = db.relationship("InstallmentContract", back_populates="items")
    product = db.relationship("Product", lazy=True)


class InstallmentSchedule(db.Model):
    __tablename__ = "installment_schedules"
    __table_args__ = (
        db.UniqueConstraint("contract_id", "sequence", name="uq_installment_schedule_sequence"),
        db.CheckConstraint("amount > 0 AND paid_amount >= 0", name="ck_installment_schedule_amounts"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("installment_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = db.Column(db.Integer, nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    paid_amount = db.Column(db.Integer, nullable=False, default=0)
    remaining_amount = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    paid_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    contract = db.relationship("InstallmentContract", back_populates="schedules")
    allocations = db.relationship("InstallmentPaymentAllocation", back_populates="schedule")


class InstallmentPayment(db.Model):
    __tablename__ = "installment_payments"
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "payment_number", name="uq_installment_payment_number"),
        db.CheckConstraint("amount > 0", name="ck_installment_payment_amount"),
    )

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("installment_contracts.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), index=True)
    payment_number = db.Column(db.String(40), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    payment_method = db.Column(db.String(30), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"))
    reference = db.Column(db.String(120))
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="posted", index=True)
    reversal_of_id = db.Column(db.Integer, db.ForeignKey("installment_payments.id"))
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entry.id"))
    received_by_id = db.Column(db.Integer, db.ForeignKey("employee.id"))
    received_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    contract = db.relationship("InstallmentContract", back_populates="payments", foreign_keys=[contract_id])
    allocations = db.relationship("InstallmentPaymentAllocation", back_populates="payment", cascade="all, delete-orphan")


class InstallmentPaymentAllocation(db.Model):
    __tablename__ = "installment_payment_allocations"
    __table_args__ = (db.CheckConstraint("amount > 0", name="ck_installment_allocation_amount"),)

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("installment_payments.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey("installment_schedules.id"), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)

    payment = db.relationship("InstallmentPayment", back_populates="allocations")
    schedule = db.relationship("InstallmentSchedule", back_populates="allocations")


class InstallmentSettings(db.Model):
    __tablename__ = "installment_settings"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenant.id"), nullable=False, unique=True, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    store_name = db.Column(db.String(180), nullable=False, default="Finora Installment Store")
    logo_path = db.Column(db.String(500))
    banner_path = db.Column(db.String(500))
    contact_phone = db.Column(db.String(30))
    whatsapp = db.Column(db.String(30))
    address = db.Column(db.String(300))
    map_url = db.Column(db.String(500))
    terms = db.Column(db.Text)
    currency = db.Column(db.String(10), nullable=False, default="IQD")
    second_phone_required = db.Column(db.Boolean, nullable=False, default=False)
    documents_config_json = db.Column(db.Text)
    guarantor_required = db.Column(db.Boolean, nullable=False, default=False)
    employment_required = db.Column(db.Boolean, nullable=False, default=False)
    allowed_durations_json = db.Column(db.Text)
    minimum_down_payment_percentage = db.Column(db.Numeric(6, 3), nullable=False, default=0)
    payment_day = db.Column(db.Integer, nullable=False, default=1)
    grace_days = db.Column(db.Integer, nullable=False, default=0)
    receivable_account_id = db.Column(db.Integer, db.ForeignKey("account.id"))
    sales_account_id = db.Column(db.Integer, db.ForeignKey("account.id"))
    cash_account_id = db.Column(db.Integer, db.ForeignKey("account.id"))
    bank_account_id = db.Column(db.Integer, db.ForeignKey("account.id"))
    fee_account_id = db.Column(db.Integer, db.ForeignKey("account.id"))
    reservation_policy = db.Column(db.String(30), nullable=False, default="on_approval")
    allow_advance_payment = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
