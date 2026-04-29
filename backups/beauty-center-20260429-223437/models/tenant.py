from extensions import db
from datetime import datetime, timedelta


class Tenant(db.Model):
    """
    شركة/عميل في نظام الـ SaaS.
    كل شركة لها اشتراك وخطة خاصة وبيانات معزولة.
    """
    __tablename__ = "tenant"

    id = db.Column(db.Integer, primary_key=True)

    # معلومات أساسية
    name = db.Column(db.String(150), nullable=False)
    contact_name = db.Column(db.String(150), nullable=True)
    contact_email = db.Column(db.String(150), nullable=True)
    contact_phone = db.Column(db.String(50), nullable=True)

    # خطة الاشتراك
    plan_key = db.Column(db.String(50), nullable=False, default="basic")  # basic / pro / enterprise
    plan_name = db.Column(db.String(100), nullable=False, default="الخطة الأساسية")
    monthly_price = db.Column(db.Integer, nullable=False, default=0)  # بالدينار العراقي

    # حالة الاشتراك
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subscription_start = db.Column(db.DateTime, default=datetime.utcnow)
    subscription_end = db.Column(db.DateTime, nullable=True)  # تاريخ نهاية الاشتراك

    # اختياري لاحقاً: ربط دومين/ساب‑دومين
    subdomain = db.Column(db.String(100), unique=True, nullable=True)

    @property
    def dynamic_plan(self) -> dict:
        """جلب بيانات الخطة الحالية من النظام المركزي."""
        from utils.plan_limits import get_plan
        return get_plan(self.plan_key)

    @property
    def display_plan_name(self) -> str:
        """اسم الخطة المحدث ديناميكياً."""
        return self.dynamic_plan.get("name", self.plan_name)

    @property
    def display_monthly_price(self) -> int:
        """سعر الخطة المحدثة."""
        return self.dynamic_plan.get("price_monthly", self.monthly_price)

    def is_subscription_valid(self) -> bool:
        """
        يتحقق من أن الاشتراك فعّال وغير منتهي.
        إذا لم يكن هناك subscription_end نعتبره مفتوح (للاشتراكات اليدوية/التجريبية).
        """
        if not self.is_active:
            return False
        if not self.subscription_end:
            return True
        return datetime.utcnow() <= self.subscription_end

    def extend_subscription_months(self, months: int = 1):
        """
        تمديد الاشتراك بعدد من الأشهر من تاريخ الانتهاء الحالي (أو من اليوم إذا منتهي).
        """
        if months <= 0:
            return
        base = self.subscription_end or datetime.utcnow()
        if base < datetime.utcnow():
            base = datetime.utcnow()
        self.subscription_start = datetime.utcnow()
        self.subscription_end = base + timedelta(days=30 * months)

    def __repr__(self):
        return f"<Tenant {self.name} ({self.plan_key})>"

