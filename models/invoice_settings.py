from extensions import db
from datetime import datetime
import json

class InvoiceSettings(db.Model):
    __tablename__ = "invoice_settings"
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Company Info
    company_name = db.Column(db.String(200), default="شركة سوبر ماكس")
    company_subtitle = db.Column(db.String(200), default="للتجارة والأجهزة الإلكترونية")
    logo_path = db.Column(db.String(500))  # مسار اللوجو
    
    # Contact Info
    company_address = db.Column(db.Text, default="كراده خارج مجمع سوبر ماكس قرب شارع العطار")
    company_phone = db.Column(db.String(50), default="07711272744")

    # Return policy (shown on ecommerce-style templates)
    return_policy_notes = db.Column(db.Text, default=(
        "يحق للعميل استرجاع أو استبدال المنتجات خلال 3 أيام من تاريخ الاستلام "
        "بشرط أن تكون بحالتها الأصلية غير مستخدمة. للاسترجاع، يرجى التواصل معنا "
        "وتزويدنا برقم الطلب المبين أعلاه."
    ))
    
    # Warranty Notes
    warranty_notes = db.Column(db.Text, default="""مدة الضمان: سنة واحدة.
الصيانة لا تشمل الكسر.
يُرجى فحص الجهاز قبل مغادرة المندوب.
عند مغادرة المندوب، أي خلل يُراجع عبر قسم الصيانة.
الصيانة حصراً في بغداد — كراده خارج مجمع سوبر ماكس قرب شارع العطار.""")
    warranty_card_background = db.Column(
        db.Text,
        default="linear-gradient(135deg, #031021 0%, #1f2e42 100%)"
    )
    
    # Layout Settings (JSON)
    layout_settings = db.Column(db.Text, default='{}')  # JSON string for drag & drop positions
    
    # Visibility Settings (JSON)
    visibility_settings = db.Column(db.Text, default='{}')  # Which elements to show/hide
    
    # Column Settings for Products Table
    show_discount_column = db.Column(db.Boolean, default=True)
    show_tax_column = db.Column(db.Boolean, default=True)
    show_unit_price_with_tax = db.Column(db.Boolean, default=True)
    
    # Logo Settings
    logo_circle_text = db.Column(db.Text, default="""SUPER MAX
ELECTRIC GROUP
AFS
SUPER MAX
AL ATWANI""")
    use_logo_image = db.Column(db.Boolean, default=False)  # استخدام صورة لوجو بدلاً من النص
    
    # Returned Count Settings
    show_returned_count = db.Column(db.Boolean, default=True)  # عرض عداد الرواجع

    # Financial Report Settings (خاصة بالتقرير المالي الشامل — منفصلة عن الفاتورة)
    report_company_name = db.Column(db.String(200))   # اسم الشركة في التقرير (fallback: company_name)
    report_logo_path = db.Column(db.String(500))      # لوجو خاص بالتقرير
    report_address = db.Column(db.Text)               # عنوان في ترويسة التقرير (fallback: company_address)
    report_phone = db.Column(db.String(50))           # هاتف في ترويسة التقرير (fallback: company_phone)
    report_footer_text = db.Column(db.Text)           # نص تذييل التقرير
    report_show_logo = db.Column(db.Boolean, default=True)  # إظهار اللوجو في التقرير

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def get_layout_settings(self):
        """Get layout settings as dict"""
        try:
            return json.loads(self.layout_settings) if self.layout_settings else {}
        except:
            return {}
    
    def set_layout_settings(self, settings_dict):
        """Set layout settings from dict"""
        self.layout_settings = json.dumps(settings_dict)
    
    def get_visibility_settings(self):
        """Get visibility settings as dict"""
        try:
            return json.loads(self.visibility_settings) if self.visibility_settings else {}
        except:
            return {}
    
    def set_visibility_settings(self, settings_dict):
        """Set visibility settings from dict"""
        self.visibility_settings = json.dumps(settings_dict)
    
    def __repr__(self):
        return f"<InvoiceSettings {self.id}>"

    # أسماء موحّدة مع قوالب الفواتير (store_name / phone1 / invoice_note)
    @property
    def store_name(self):
        return (self.company_name or "").strip() or "المتجر"

    @property
    def phone1(self):
        return (self.company_phone or "").strip()

    @property
    def phone2(self):
        return ""

    @property
    def invoice_note(self):
        """نص سياسة الاسترجاع للقوالب."""
        note = (getattr(self, "return_policy_notes", None) or "").strip()
        if note:
            return note[:800]
        w = (self.warranty_notes or "").strip()
        if not w:
            return "شكراً لتسوقكم معنا!"
        first = w.split("\n")[0].strip()
        return first[:800] if len(first) > 800 else first

    @staticmethod
    def get_settings():
        """Get or create default settings"""
        InvoiceSettings.ensure_schema()
        settings = InvoiceSettings.query.first()
        if not settings:
            settings = InvoiceSettings()
            db.session.add(settings)
            db.session.commit()
        return settings

    @staticmethod
    def ensure_schema():
        """Add optional invoice_settings columns for existing tenant databases."""
        try:
            from sqlalchemy import inspect, text

            bind = db.session.get_bind()
            inspector = inspect(bind)
            if "invoice_settings" not in inspector.get_table_names():
                return

            columns = {col["name"] for col in inspector.get_columns("invoice_settings")}
            additions = {
                "return_policy_notes": "ALTER TABLE invoice_settings ADD COLUMN return_policy_notes TEXT",
                "warranty_card_background": (
                    "ALTER TABLE invoice_settings ADD COLUMN warranty_card_background TEXT "
                    "DEFAULT 'linear-gradient(135deg, #031021 0%, #1f2e42 100%)'"
                ),
                "report_company_name": "ALTER TABLE invoice_settings ADD COLUMN report_company_name VARCHAR(200)",
                "report_logo_path": "ALTER TABLE invoice_settings ADD COLUMN report_logo_path VARCHAR(500)",
                "report_address": "ALTER TABLE invoice_settings ADD COLUMN report_address TEXT",
                "report_phone": "ALTER TABLE invoice_settings ADD COLUMN report_phone VARCHAR(50)",
                "report_footer_text": "ALTER TABLE invoice_settings ADD COLUMN report_footer_text TEXT",
                "report_show_logo": "ALTER TABLE invoice_settings ADD COLUMN report_show_logo BOOLEAN DEFAULT TRUE",
            }
            changed = False
            for col, stmt in additions.items():
                if col not in columns:
                    db.session.execute(text(stmt))
                    changed = True
            if changed:
                db.session.commit()
                for obj in list(db.session):
                    if isinstance(obj, InvoiceSettings):
                        db.session.expire(obj)

            row = InvoiceSettings.query.first()
            if row and row.company_address and "عبد الرسول علي" in row.company_address:
                row.company_address = row.company_address.replace("عبد الرسول علي", "سوبر ماكس")
                db.session.commit()
        except Exception:
            db.session.rollback()

