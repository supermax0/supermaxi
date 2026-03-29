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
    company_address = db.Column(db.Text, default="كراده خارج مجمع عبد الرسول علي قرب شارع العطار")
    company_phone = db.Column(db.String(50), default="07711272744")
    
    # Warranty Notes
    warranty_notes = db.Column(db.Text, default="""مدة الضمان سنه واحدة صيانه لا تشمل الكسر
افحص الجهاز قبل مغادرة المندوب
عند مغادرة المندوب اي خلل مراجعة الصيانه الصيانه حصرا بغداد كراده خارج""")
    
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
        """نص تذييل الفاتورة: أول سطر من ملاحظات الضمان أو عبارة افتراضية."""
        w = (self.warranty_notes or "").strip()
        if not w:
            return "شكراً لتسوقكم معنا!"
        first = w.split("\n")[0].strip()
        return first[:800] if len(first) > 800 else first

    @staticmethod
    def get_settings():
        """Get or create default settings"""
        settings = InvoiceSettings.query.first()
        if not settings:
            settings = InvoiceSettings()
            db.session.add(settings)
            db.session.commit()
        return settings

