# models/invoice.py
from extensions import db
from datetime import datetime


class Invoice(db.Model):
    __tablename__ = "invoice"

    id = db.Column(db.Integer, primary_key=True)

    # =====================
    # Tenant (الشركة المالكة للفاتورة)
    # =====================
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey("tenant.id"),
        nullable=True
    )

    # =====================
    # Customer
    # =====================
    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customer.id"),
        nullable=False
    )
    customer_name = db.Column(
        db.String(150),
        nullable=False
    )

    # =====================
    # Employee (Cashier)
    # =====================
    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employee.id"),
        nullable=True
    )
    employee_name = db.Column(
        db.String(100),
        nullable=True
    )

    # =====================
    # Invoice Status
    # =====================
    status = db.Column(
        db.String(30),
        default="تم الطلب"
    )

    payment_status = db.Column(
        db.String(30),
        default="غير مسدد"
    )

    total = db.Column(
        db.Integer,
        default=0
    )

    paid_amount = db.Column(
        db.Integer,
        default=0
    )  # المبلغ المدفوع

    note = db.Column(
        db.Text
    )

    # =====================
    # Shipping
    # =====================
    shipping_company_id = db.Column(
        db.Integer,
        db.ForeignKey("shipping_company.id"),
        
    )

    shipping_status = db.Column(
        db.String(50),
        default="قيد الشحن"
    )
    
    # مندوب التوصيل
    delivery_agent_id = db.Column(
        db.Integer,
        db.ForeignKey("delivery_agent.id"),
        nullable=True
    )
    
    # البيج
    page_id = db.Column(
        db.Integer,
        db.ForeignKey("page.id"),
        nullable=True
    )
    page_name = db.Column(
        db.String(150),
        nullable=True
    )  # حفظ اسم البيج للطباعة السريعة

    # =====================
    # Barcode
    # =====================
    barcode = db.Column(
        db.String(100),
        nullable=True
    )  # باركود الفاتورة
    
    shipping_barcode = db.Column(
        db.String(100),
        nullable=True
    )  # باركود شركة النقل

    # =====================
    # Time
    # =====================
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )
    
    scheduled_date = db.Column(
        db.DateTime,
        nullable=True
    )  # تاريخ تأجيل الطلب

    # =====================
    # Relationships
    # =====================

    # الزبون
    customer = db.relationship(
        "Customer",
        back_populates="invoices"
    )

    # الكاشير
    employee = db.relationship(
        "Employee",
        back_populates="invoices"
    )

    # شركة الشحن
    shipping_company = db.relationship(
        "ShippingCompany",
        back_populates="invoices"
    )
    
    # مندوب التوصيل
    delivery_agent = db.relationship(
        "DeliveryAgent",
        lazy=True
    )

    # عناصر الفاتورة
    items = db.relationship(
        "OrderItem",
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy=True
    )

    # =====================
    # Helper
    # =====================
    def __repr__(self):
        return f"<Invoice #{self.id} | {self.customer_name} | {self.total}>"
