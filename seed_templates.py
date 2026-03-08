import sys
import os

# Ensure the app context is available
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app
from extensions import db
from models.invoice_template import InvoiceTemplate

def seed_templates():
    with app.app_context():
        # Create all tables (this will create the new ones safely)
        db.create_all()
        
        # Check if templates already exist
        if InvoiceTemplate.query.first():
            print("Templates already exist. Skipping seed.")
            return

        templates = [
            # 1. الأساسي (Basic) - مجاني
            InvoiceTemplate(name="الأساسي (Basic)", description="القالب الافتراضي البسيط والعملي.", is_premium=False, price=0, html_file_name="basic.html"),
            # 2. الكلاسيكي (Classic) - مجاني
            InvoiceTemplate(name="الكلاسيكي (Classic)", description="قالب كلاسيكي بالأبيض والأسود مع جداول واضحة وتصميم رسمي.", is_premium=False, price=0, html_file_name="classic.html"),
            # 3. الحديث المظلم (Modern Dark) - 10000
            InvoiceTemplate(name="الحديث المظلم (Modern Dark)", description="تصميم عصري بخلفية داكنة للعلامات التجارية التي تبحث عن التميز.", is_premium=True, price=10000, html_file_name="modern_dark.html"),
            # 4. الأنيق (Elegant Serif) - 10000
            InvoiceTemplate(name="الأنيق (Elegant)", description="مساحات بيضاء نظيفة وخطوط أنيقة، مناسب للعلامات التجارية الراقية كمحلات الورد والمجوهرات.", is_premium=True, price=10000, html_file_name="elegant.html"),
            # 5. فاتورة حرارية (Thermal POS) - 10000
            InvoiceTemplate(name="وصل حراري (Thermal POS)", description="مُصمم خصيصاً لطابعات الرصيد الحرارية بعرض 80mm.", is_premium=True, price=10000, html_file_name="thermal.html"),
            # 6. الشركات (Corporate Blue) - 10000
            InvoiceTemplate(name="الشركات (Corporate)", description="تصميم احترافي رسمي ممتاز لمعاملات تجارة الجملة (B2B).", is_premium=True, price=10000, html_file_name="corporate.html"),
            # 7. وكالة إبداعية (Creative Agency) - 10000
            InvoiceTemplate(name="إبداعي (Creative)", description="تصميم غير تقليدي مع ألوان زاهية وأشكال هندسية تجذب الانتباه.", is_premium=True, price=10000, html_file_name="creative.html"),
            # 8. التجارة الإلكترونية (E-Commerce) - 10000
            InvoiceTemplate(name="تجارة إلكترونية (E-Commerce)", description="يحتوي على مساحة واضحة لسياسة الارجاع وإرشادات العميل المثالية للمتاجر الإلكترونية.", is_premium=True, price=10000, html_file_name="ecommerce.html"),
            # 9. الخط العربي (Arabic Calligraphy) - 10000
            InvoiceTemplate(name="خط عربي (Arabic Calligraphy)", description="زخارف وتفاصيل مستوحاة من الفن الإسلامي والخط العربي الأصيل.", is_premium=True, price=10000, html_file_name="arabic.html"),
            # 10. الفاخر (Luxury Gold) - 10000
            InvoiceTemplate(name="الفاخر (Luxury Gold)", description="تفاصيل باللونين الأسود والذهبي للمنتجات باهظة الثمن.", is_premium=True, price=10000, html_file_name="luxury.html")
        ]
        
        db.session.bulk_save_objects(templates)
        db.session.commit()
        print(f"Successfully created tables and seeded 10 invoice templates.")

if __name__ == "__main__":
    seed_templates()
