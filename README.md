# Finora

نظام محاسبة وإدارة مبيعات متكامل (SaaS) متعدد الشركات — نقطة بيع، مخزون، طلبات، تقارير، وصلات دفع.

## الوصف

Finora منصة ويب لإدارة المحاسبة والمبيعات والمخزون مع دعم عدة شركات (multi-tenant)، لوحة تحكم، نقطة بيع (POS)، وإعدادات صلاحيات للموظفين.

## المميزات

- **نقطة البيع (POS)** — فواتير، زبائن، بحث بالباركود
- **إدارة المخزون** — منتجات، جرد، مشتريات، موردين
- **الطلبات والشحن** — حالات الطلبات، مندوبون، تقارير توصيل
- **التقارير والمالية** — مصروفات، صندوق، حسابات، تقارير متقدمة
- **متعدد الشركات** — كل شركة لها قاعدة بيانات مستقلة واشتراك
- **الصلاحيات والأدوار** — أدوار قابلة للتخصيص وصلاحيات تفصيلية
- **واجهة عربية** — دعم RTL وترجمة (ar, en, ku, tr)

## التثبيت

```bash
# استنساخ المستودع
git clone https://github.com/supermax0/supermaxi.git finora-saas
cd finora-saas

# بيئة افتراضية
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# الاعتماديات
pip install -r requirements.txt

# نسخ ملف البيئة وتعديله
copy .env.example .env
# عدّل .env: SECRET_KEY, DATABASE_URL, FLASK_ENV
```

## التشغيل محلياً

```bash
# تطوير (Development)
set FLASK_ENV=development
python app.py

# أو تحديد منفذ
set FLASK_PORT=5008
python app.py
```

التطبيق يعمل على `http://127.0.0.1:5008` (أو المنفذ المحدد).

## النشر (Deployment)

```bash
# إنتاج (Production)
set FLASK_ENV=production
set SECRET_KEY=your-secure-secret-key
set DATABASE_URL=sqlite:///database.db

# تشغيل بـ Gunicorn (مُوصى به)
gunicorn wsgi:app --bind 0.0.0.0:5008
```

- استخدم خادم ويب (Nginx/Apache) كـ reverse proxy واترك SSL عليه.
- للبيانات الحساسة استخدم قاعدة بيانات قوية (مثل PostgreSQL) وعدّل `DATABASE_URL`.

## هيكل المشروع

```
├── app.py              # نقطة دخول التطبيق
├── config.py           # إعدادات التطوير والإنتاج
├── wsgi.py             # نقطة دخول Gunicorn
├── requirements.txt
├── routes/             # مسارات التطبيق
├── models/             # نماذج البيانات
├── templates/
├── static/
├── translations/
└── tenants/            # قواعد بيانات الشركات (يُستثنى من Git)
```

## الترخيص

انظر [LICENSE](LICENSE).
