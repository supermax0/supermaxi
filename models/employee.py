# models/employee.py
from extensions import db
from datetime import datetime

class Employee(db.Model):
    __tablename__ = "employee"

    id = db.Column(db.Integer, primary_key=True)

    # =====================
    # Tenant (الشركة المالكة للحساب)
    # =====================
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey("tenant.id"),
        nullable=True  # سيتم ملؤه عبر الهجرة لـ tenant الافتراضي
    )

    # =====================
    # Basic Info
    # =====================
    name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    role = db.Column(
        db.String(30),
        default="cashier"
    )  # cashier / admin

    is_active = db.Column(db.Boolean, default=True)
    
    # =====================
    # Profile & Preferences
    # =====================
    profile_pic = db.Column(db.String(500), nullable=True)
    language = db.Column(db.String(10), default="ar")  # ar / en
    theme_preference = db.Column(db.String(20), default="dark")  # dark / light / system
    
    # =====================
    # Permissions (صلاحيات مفصلة)
    # =====================
    can_see_orders = db.Column(db.Boolean, default=True)  # رؤية الطلبات (عام)
    can_see_orders_placed = db.Column(db.Boolean, default=True)  # رؤية طلبات "تم الطلب"
    can_see_orders_delivered = db.Column(db.Boolean, default=True)  # رؤية طلبات "واصلة"
    can_see_orders_returned = db.Column(db.Boolean, default=True)  # رؤية طلبات "راجعة"
    can_see_orders_shipped = db.Column(db.Boolean, default=True)  # رؤية طلبات "مشحونة"
    can_edit_price = db.Column(db.Boolean, default=False)  # تعديل السعر
    can_see_reports = db.Column(db.Boolean, default=True)  # رؤية التقارير
    can_manage_inventory = db.Column(db.Boolean, default=False)  # إدارة المخزون
    can_see_expenses = db.Column(db.Boolean, default=False)  # رؤية المصاريف
    can_manage_suppliers = db.Column(db.Boolean, default=False)  # إدارة الموردين
    can_manage_customers = db.Column(db.Boolean, default=True)  # إدارة الزبائن
    can_see_accounts = db.Column(db.Boolean, default=False)  # رؤية الحسابات
    can_see_financial = db.Column(db.Boolean, default=False)  # رؤية البيانات المالية

    # =====================
    # Shipping Company (for delivery employees)
    # =====================
    shipping_company_id = db.Column(
        db.Integer,
        db.ForeignKey("shipping_company.id"),
        nullable=True
    )  # ربط المندوب بشركة النقل

    # =====================
    # Financial (Future Use)
    # =====================
    commission_percent = db.Column(
        db.Integer,
        default=0
    )  # نسبة عمولة %

    salary = db.Column(
        db.Integer,
        default=0
    )  # راتب ثابت (اختياري)

    # =====================
    # Statistics (Cached)
    # =====================
    total_orders = db.Column(
        db.Integer,
        default=0
    )

    total_sales = db.Column(
        db.Integer,
        default=0
    )

    # =====================
    # Time
    # =====================
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # =====================
    # Relationships
    # =====================
    from .role import employee_roles
    roles = db.relationship('Role', secondary=employee_roles,
                            backref=db.backref('employees', lazy='dynamic'))

    invoices = db.relationship(
        "Invoice",
        back_populates="employee",
        lazy=True
    )

    # =====================
    # Helper Methods
    # =====================
    def update_stats(self, order_total):
        """
        تحديث إحصائيات الموظف بعد كل طلب
        """
        self.total_orders += 1
        self.total_sales += order_total

    def calculate_commission(self):
        """
        حساب العمولة حسب النسبة
        """
        if self.commission_percent <= 0:
            return 0
        return int(self.total_sales * self.commission_percent / 100)

    def has_permission(self, permission_name):
        """التحقق مما إذا كان الموظف لديه صلاحية معينة عبر أدواره"""
        if self.role == 'admin':
            return True
        for role in self.roles:
            for perm in role.permissions:
                if perm.name == permission_name:
                    return True
        return False

    def __repr__(self):
        return f"<Employee {self.name} ({self.username})>"
