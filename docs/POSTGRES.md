# PostgreSQL — التثبيت والهجرة

## تثبيت PostgreSQL على Ubuntu VPS

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
```

## إنشاء المستخدم وقاعدة البيانات

```bash
sudo -u postgres psql
```

داخل `psql`:

```sql
CREATE USER finora WITH PASSWORD 'password';
CREATE DATABASE finora_db OWNER finora;
GRANT ALL PRIVILEGES ON DATABASE finora_db TO finora;
\q
```

## إعداد المتغيرات

في ملف `.env`:

```
DATABASE_URL=postgresql://finora:password@localhost/finora_db
FLASK_ENV=production
SECRET_KEY=your-secret-key
```

## الهجرة من SQLite إلى PostgreSQL

1. **إنشاء الجداول في PostgreSQL** (أول مرة):

   ```bash
   export DATABASE_URL=postgresql://finora:password@localhost/finora_db
   flask db upgrade
   ```
   إذا لم تُنشأ الجداول بعد، شغّل التطبيق مرة واحدة مع `DATABASE_URL` يشير إلى PostgreSQL (سيُنشئ الجداول عبر `create_all`).

2. **نسخ البيانات من SQLite إلى PostgreSQL**:

   ```bash
   export DATABASE_URL=postgresql://finora:password@localhost/finora_db
   python scripts/migrate_sqlite_to_postgres.py
   ```

3. **تشغيل التطبيق على PostgreSQL**:

   ```bash
   gunicorn wsgi:app
   ```

## أوامر Flask-Migrate

```bash
flask db init      # مرة واحدة لإنشاء مجلد migrations
flask db migrate -m "وصف التغيير"
flask db upgrade   # تطبيق الهجرات
```

## ملاحظة

- قاعدة البيانات **الأساسية (Core)** فقط تُهاجر إلى PostgreSQL (جداول: super_admins, tenants, payment_requests, subscription_plans, global_settings).
- قواعد بيانات **الشركات (Tenants)** تبقى SQLite (ملف لكل شركة في `tenants/`) ما لم تُضف لاحقاً آلية هجرة منفصلة لها.
