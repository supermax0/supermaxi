
from flask import Flask, redirect, session, url_for, request, g, jsonify, render_template, flash
from flask_login import current_user
print("=== FINORA APP STARTING - V1.1 (i18n check) ===")
from extensions import db
# Models (Core)
from models.core.tenant import Tenant
from models.core.super_admin import SuperAdmin
from models.core.payment_request import PaymentRequest
from models.core.subscription_plan import SubscriptionPlan

# Models (Tenant)
from models.customer import Customer
from models.product import Product
from models.message import Message
from models.invoice import Invoice
from models.order_item import OrderItem
from models.shipping import ShippingCompany
from models.shipping_report import ShippingReport
from models.employee import Employee
from models.report import Report
from models.invoice_settings import InvoiceSettings
from models.system_analytics import SystemAnalytics
from models.system_alert import SystemAlert
from models.system_settings import SystemSettings
from models.assistant_memory import AssistantMemory
from models.delivery_agent import DeliveryAgent
from models.page import Page
from models.role import Role, Permission
from models.comment_log import CommentLog

# Routes
from routes.index import index_bp
from routes.payments import payments_bp
from routes.pos import pos_bp
from routes.employees import employees_bp
from routes.inventory import inventory_bp
from routes.purchases import purchases_bp
from routes.inventory_ledger import inventory_ledger_bp
from routes.cash import cash_bp
from routes.customers import customers_bp
from routes.orders import orders_bp
from routes.shipping import shipping_bp
from routes.reports import reports_bp
from routes.suppliers import suppliers_bp
from routes.expenses import expenses_bp
from routes.accounts import accounts_bp
from routes.ai import ai_bp
from routes.social_ai_routes import social_ai_bp
from routes.settings import settings_bp
from routes.messages import messages_bp
from routes.delivery import delivery_bp
from routes.assistant import assistant_bp
from routes.agents import agents_bp
from routes.delivery_agent import delivery_agent_bp
from routes.pages import pages_bp
from routes.invoice_store import invoice_store_bp
from routes.storefront import storefront_bp
from telegram_bot import telegram_bp
from api_workflows import workflow_api
from models.ai_agent import AgentWorkflow, AgentExecution
from social_ai.workflow_engine import execute_workflow

# =====================================
# App Setup
# =====================================
import os
try:
    import importlib.util
    if importlib.util.find_spec("dotenv"):
        importlib.import_module("dotenv").load_dotenv()
except (ImportError, AttributeError):
    pass

from config import Config, DevelopmentConfig, ProductionConfig
_env = (os.environ.get("FLASK_ENV") or "development").lower()
app = Flask(__name__)
app.config.from_object(ProductionConfig if _env == "production" else DevelopmentConfig)

# =====================================
# i18n / Multi-language Setup
# =====================================
import json

def load_translations():
    translations = {}
    folder = os.path.join(app.root_path, 'translations')
    if os.path.exists(folder):
        for filename in os.listdir(folder):
            if filename.endswith('.json'):
                lang_code = filename.replace('.json', '')
                try:
                    with open(os.path.join(folder, filename), 'r', encoding='utf-8') as f:
                        translations[lang_code] = json.load(f)
                except Exception as e:
                    print(f"Error loading translation {filename}: {e}")
    return translations

# Global translations dictionary
app_translations = load_translations()
print(f"Loaded translations for: {list(app_translations.keys())}")

def get_string(key, lang='ar'):
    """Helper to get a translated string"""
    # Fallback to Arabic if language not found
    lang_data = app_translations.get(lang) or app_translations.get('ar', {})
    return lang_data.get(key, key) # Return key itself if string not found

# =====================================
# Jinja Filters
# =====================================
@app.template_filter('toLocaleString')
def to_locale_string(value):
    try:
        if value is None: return "0"
        return "{:,.0f}".format(float(value))
    except (ValueError, TypeError):
        return value

app.config["UPLOAD_FOLDER"] = "static/uploads/messages"
# حد رفع الملفات (للرسائل، النشر التلقائي صورة/فيديو حتى 500 ميجا)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB
# مجلد وسائط الأوتوبوستر: إن لم يُعيَّن = جذر التطبيق/media (على السيرفر: /var/www/finora/supermaxi/media)
app.config["AUTOPOSTER_MEDIA_ROOT"] = os.environ.get("AUTOPOSTER_MEDIA_ROOT") or os.path.join(app.root_path, "media")

# في التطوير فقط: إعادة تحميل القوالب وتقليل كاش الملفات
if not app.config.get("DEBUG"):
    app.config["TEMPLATES_AUTO_RELOAD"] = False
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600
else:
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

db.init_app(app)

try:
    from flask_migrate import Migrate
    migrate = Migrate(app, db)
except ImportError:
    migrate = None

# =====================================
# Create Tables + Admin Account
# =====================================
with app.app_context():
    # Import core models so create_all() knows what tables to create (including FKs e.g. users)
    from models.core.super_admin import SuperAdmin
    from models.core.tenant import Tenant
    from models.core.payment_request import PaymentRequest
    from models.core.global_setting import GlobalSetting
    from models.core.landing_visit import LandingVisit
    from models.user import User  # جدول users مطلوب لـ tenant_template_purchases / tenant_template_settings
    from models.telegram_inbox_message import TelegramInboxMessage  # noqa: F401

    db.create_all()

    # Database health check on startup
    try:
        from sqlalchemy import text
        db.session.execute(text("SELECT 1"))
        db.session.commit()
        print("Database connection OK.")
    except Exception as e:
        print(f"Database health check: {e}")

    # =====================================
    # DB Init: Core Database defaults
    # =====================================
    try:
        from werkzeug.security import generate_password_hash

        # 1. Create default SuperAdmin if none exists
        admin = SuperAdmin.query.filter_by(username="supermax").first()
        if not admin:
            admin = SuperAdmin(
                username="supermax",
                password_hash=generate_password_hash("supermax123")
            )
            db.session.add(admin)
            db.session.commit()
            print("Created default SuperAdmin account.")
    except Exception as e:
        print(f"Core DB Init note: {e}")

    # Legacy migrations for tenants are removed since we use physical DB per tenant now.

    # Migration: Add message file columns if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        message_columns = [col['name'] for col in inspector.get_columns('message')] if 'message' in inspector.get_table_names() else []

        if 'message' in inspector.get_table_names():
            if 'file_type' not in message_columns:
                db.session.execute(text("ALTER TABLE message ADD COLUMN file_type VARCHAR(50)"))
            if 'file_path' not in message_columns:
                db.session.execute(text("ALTER TABLE message ADD COLUMN file_path VARCHAR(500)"))
            if 'file_name' not in message_columns:
                db.session.execute(text("ALTER TABLE message ADD COLUMN file_name VARCHAR(255)"))
            if 'is_edited' not in message_columns:
                db.session.execute(text("ALTER TABLE message ADD COLUMN is_edited BOOLEAN DEFAULT 0"))
            db.session.commit()
    except Exception as e:
        print(f"Migration note: {e}")

    # Migration: Add shipping_company_id to employee if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'employee' in inspector.get_table_names():
            employee_columns = [col['name'] for col in inspector.get_columns('employee')]
            if 'shipping_company_id' not in employee_columns:
                db.session.execute(text("ALTER TABLE employee ADD COLUMN shipping_company_id INTEGER REFERENCES shipping_company(id)"))
                db.session.commit()
                print("Added shipping_company_id column to employee table.")
    except Exception as e:
        print(f"Migration note (employee shipping_company_id): {e}")

    # Migration: Add access_token, username, password to shipping_company if needed
    try:
        from sqlalchemy import inspect, text
        import secrets
        inspector = inspect(db.engine)
        if 'shipping_company' in inspector.get_table_names():
            shipping_columns = [col['name'] for col in inspector.get_columns('shipping_company')]
            if 'access_token' not in shipping_columns:
                db.session.execute(text("ALTER TABLE shipping_company ADD COLUMN access_token VARCHAR(64)"))
            if 'username' not in shipping_columns:
                db.session.execute(text("ALTER TABLE shipping_company ADD COLUMN username VARCHAR(50)"))
            if 'password' not in shipping_columns:
                db.session.execute(text("ALTER TABLE shipping_company ADD COLUMN password VARCHAR(200)"))
            # إنشاء tokens للشركات الموجودة
            companies = ShippingCompany.query.all()
            for company in companies:
                if not company.access_token:
                    access_token = secrets.token_urlsafe(32)
                    while ShippingCompany.query.filter_by(access_token=access_token).first():
                        access_token = secrets.token_urlsafe(32)
                    company.access_token = access_token
            db.session.commit()
            print("Added access_token, username, password columns to shipping_company table.")
    except Exception as e:
        print(f"Migration note (shipping_company): {e}")

    # Migration: Create shipping_report table if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'shipping_report' not in inspector.get_table_names():
            # إنشاء الجدول يدوياً
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE shipping_report (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        report_number VARCHAR(50) NOT NULL UNIQUE,
                        shipping_company_id INTEGER NOT NULL,
                        shipping_company_name VARCHAR(150) NOT NULL,
                        orders_data TEXT,
                        total_amount INTEGER DEFAULT 0,
                        orders_count INTEGER DEFAULT 0,
                        notes TEXT,
                        created_at DATETIME,
                        created_by VARCHAR(100),
                        is_executed BOOLEAN DEFAULT 0,
                        order_status_selections TEXT,
                        FOREIGN KEY (shipping_company_id) REFERENCES shipping_company(id)
                    )
                """))
                conn.commit()
            print("Created shipping_report table.")
        else:
            # إضافة الأعمدة الجديدة إذا لم تكن موجودة
            shipping_report_columns = [col['name'] for col in inspector.get_columns('shipping_report')]
            if 'is_executed' not in shipping_report_columns:
                db.session.execute(text("ALTER TABLE shipping_report ADD COLUMN is_executed BOOLEAN DEFAULT 0"))
            if 'order_status_selections' not in shipping_report_columns:
                db.session.execute(text("ALTER TABLE shipping_report ADD COLUMN order_status_selections TEXT"))
            db.session.commit()
            print("Shipping report table already exists.")
    except Exception as e:
        print(f"Migration note (shipping_report): {e}")

    # Migration: Add permissions columns to employee table if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'employee' in inspector.get_table_names():
            employee_columns = [col['name'] for col in inspector.get_columns('employee')]
            permission_columns = {
                'can_see_orders': "BOOLEAN DEFAULT 1",
                'can_see_orders_placed': "BOOLEAN DEFAULT 1",
                'can_see_orders_delivered': "BOOLEAN DEFAULT 1",
                'can_see_orders_returned': "BOOLEAN DEFAULT 1",
                'can_see_orders_shipped': "BOOLEAN DEFAULT 1",
                'can_edit_price': "BOOLEAN DEFAULT 0",
                'can_see_reports': "BOOLEAN DEFAULT 1",
                'can_manage_inventory': "BOOLEAN DEFAULT 0",
                'can_see_expenses': "BOOLEAN DEFAULT 0",
                'can_manage_suppliers': "BOOLEAN DEFAULT 0",
                'can_manage_customers': "BOOLEAN DEFAULT 1",
                'can_see_accounts': "BOOLEAN DEFAULT 0",
                'can_see_financial': "BOOLEAN DEFAULT 0"
            }
            for col_name, col_type in permission_columns.items():
                if col_name not in employee_columns:
                    db.session.execute(text(f"ALTER TABLE employee ADD COLUMN {col_name} {col_type}"))
            db.session.commit()
            print("Added permission columns to employee table.")
    except Exception as e:
        print(f"Migration note (employee permissions): {e}")

    # Migration: Add barcode and threshold to product if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'product' in inspector.get_table_names():
            product_columns = [col['name'] for col in inspector.get_columns('product')]
            if 'barcode' not in product_columns:
                db.session.execute(text("ALTER TABLE product ADD COLUMN barcode VARCHAR(100) UNIQUE"))
                db.session.commit()
                print("Added barcode column to product table.")
            if 'low_stock_threshold' not in product_columns:
                db.session.execute(text("ALTER TABLE product ADD COLUMN low_stock_threshold INTEGER DEFAULT 5"))
                db.session.commit()
                print("Added low_stock_threshold column to product table.")
    except Exception as e:
        print(f"Migration note (barcode/threshold): {e}")

    # Migration: Create delivery_agent table if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'delivery_agent' not in inspector.get_table_names():
            # إنشاء الجدول يدوياً
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE delivery_agent (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(100) NOT NULL,
                        shipping_company_id INTEGER,
                        phone VARCHAR(20),
                        notes TEXT,
                        total_orders INTEGER DEFAULT 0,
                        total_amount INTEGER DEFAULT 0,
                        created_at DATETIME,
                        FOREIGN KEY (shipping_company_id) REFERENCES shipping_company(id)
                    )
                """))
                conn.commit()
            print("Created delivery_agent table.")
    except Exception as e:
        print(f"Migration note (delivery_agent): {e}")

    # Migration: Add username and password to delivery_agent if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'delivery_agent' in inspector.get_table_names():
            delivery_agent_columns = [col['name'] for col in inspector.get_columns('delivery_agent')]
            if 'username' not in delivery_agent_columns:
                db.session.execute(text("ALTER TABLE delivery_agent ADD COLUMN username VARCHAR(50) UNIQUE"))
            if 'password' not in delivery_agent_columns:
                db.session.execute(text("ALTER TABLE delivery_agent ADD COLUMN password VARCHAR(200)"))
            db.session.commit()
            print("Added username and password columns to delivery_agent table.")
    except Exception as e:
        print(f"Migration note (delivery_agent username/password): {e}")

    # Migration: Add delivery_agent_id to invoice if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'invoice' in inspector.get_table_names():
            invoice_columns = [col['name'] for col in inspector.get_columns('invoice')]
            if 'delivery_agent_id' not in invoice_columns:
                db.session.execute(text("ALTER TABLE invoice ADD COLUMN delivery_agent_id INTEGER REFERENCES delivery_agent(id)"))
                db.session.commit()
                print("Added delivery_agent_id column to invoice table.")
    except Exception as e:
        print(f"Migration note (invoice delivery_agent_id): {e}")

    # Migration: Add page_id and page_name to invoice if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'invoice' in inspector.get_table_names():
            invoice_columns = [col['name'] for col in inspector.get_columns('invoice')]
            if 'page_id' not in invoice_columns:
                db.session.execute(text("ALTER TABLE invoice ADD COLUMN page_id INTEGER REFERENCES page(id)"))
            if 'page_name' not in invoice_columns:
                db.session.execute(text("ALTER TABLE invoice ADD COLUMN page_name VARCHAR(150)"))
            db.session.commit()
            print("Added page_id and page_name columns to invoice table.")
    except Exception as e:
        print(f"Migration note (invoice page_id/page_name): {e}")

    # Migration: Create system_analytics and system_alert tables if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()

        if 'system_analytics' not in table_names:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE system_analytics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        analysis_type VARCHAR(50) NOT NULL,
                        title VARCHAR(200) NOT NULL,
                        description TEXT,
                        severity VARCHAR(20) DEFAULT 'info',
                        related_data TEXT,
                        status VARCHAR(20) DEFAULT 'active',
                        is_resolved BOOLEAN DEFAULT 0,
                        resolved_at DATETIME,
                        resolved_by INTEGER REFERENCES employee(id),
                        affected_count INTEGER DEFAULT 0,
                        estimated_impact INTEGER DEFAULT 0,
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                """))
                conn.commit()
            print("Created system_analytics table.")

        if 'system_alert' not in table_names:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE system_alert (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        alert_type VARCHAR(50) NOT NULL,
                        title VARCHAR(200) NOT NULL,
                        message TEXT NOT NULL,
                        priority VARCHAR(20) DEFAULT 'medium',
                        is_read BOOLEAN DEFAULT 0,
                        is_dismissed BOOLEAN DEFAULT 0,
                        related_id INTEGER,
                        related_type VARCHAR(50),
                        created_at DATETIME,
                        read_at DATETIME
                    )
                """))
                conn.commit()
            print("Created system_alert table.")
    except Exception as e:
        print(f"Migration note (system tables): {e}")

    # Migration: Create assistant_memory table if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()

        if 'assistant_memory' not in table_names:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE assistant_memory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        memory_type VARCHAR(50) NOT NULL,
                        memory_key VARCHAR(200) NOT NULL,
                        memory_value TEXT,
                        occurrence_count INTEGER DEFAULT 1,
                        last_occurrence DATETIME,
                        first_occurrence DATETIME,
                        confidence REAL DEFAULT 50.0,
                        is_verified BOOLEAN DEFAULT 0,
                        verified_by INTEGER REFERENCES employee(id),
                        verified_at DATETIME,
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                """))
                conn.commit()
            print("Created assistant_memory table.")
    except Exception as e:
        print(f"Migration note (assistant_memory): {e}")

    # Migration: Add scheduled_date to invoice table
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('invoice')]

        if 'scheduled_date' not in columns:
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE invoice ADD COLUMN scheduled_date DATETIME"))
                conn.commit()
            print("Added scheduled_date column to invoice table.")
    except Exception as e:
        print(f"Migration note (scheduled_date): {e}")

    # Migration: Add visibility columns to page if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'page' in inspector.get_table_names():
            page_columns = [col['name'] for col in inspector.get_columns('page')]
            if 'visible_to_cashier' not in page_columns:
                db.session.execute(text("ALTER TABLE page ADD COLUMN visible_to_cashier BOOLEAN DEFAULT 1"))
            if 'visible_to_admin' not in page_columns:
                db.session.execute(text("ALTER TABLE page ADD COLUMN visible_to_admin BOOLEAN DEFAULT 1"))
            db.session.commit()
            print("Added visibility columns to page table.")
    except Exception as e:
        print(f"Migration note (page visibility): {e}")

    # Migration: Add paid_amount to invoice table
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'invoice' in inspector.get_table_names():
            invoice_columns = [col['name'] for col in inspector.get_columns('invoice')]
            if 'paid_amount' not in invoice_columns:
                db.session.execute(text("ALTER TABLE invoice ADD COLUMN paid_amount INTEGER DEFAULT 0"))
                db.session.commit()
                print("Added paid_amount column to invoice table.")
    except Exception as e:
        print(f"Migration note (paid_amount): {e}")

    # Migration: Create RBAC tables if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()

        if 'permissions' not in table_names:
            # Note: We use conn.execute for table creation to ensure it's done before any model queries
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE permissions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(50) NOT NULL UNIQUE,
                        description VARCHAR(200),
                        created_at DATETIME
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE roles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(50) NOT NULL UNIQUE,
                        description VARCHAR(200),
                        created_at DATETIME
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE role_permissions (
                        role_id INTEGER,
                        permission_id INTEGER,
                        PRIMARY KEY (role_id, permission_id),
                        FOREIGN KEY (role_id) REFERENCES roles(id),
                        FOREIGN KEY (permission_id) REFERENCES permissions(id)
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE employee_roles (
                        employee_id INTEGER,
                        role_id INTEGER,
                        PRIMARY KEY (employee_id, role_id),
                        FOREIGN KEY (employee_id) REFERENCES employee(id),
                        FOREIGN KEY (role_id) REFERENCES roles(id)
                    )
                """))
                conn.commit()
            print("Created RBAC tables.")
    except Exception as e:
        print(f"Migration note (RBAC tables): {e}")

    # Migration: Add employee profile columns if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'employee' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('employee')]
            print(f"Current columns in 'employee': {columns}")

            with db.engine.connect() as conn:
                added = False
                if 'profile_pic' not in columns:
                    conn.execute(text("ALTER TABLE employee ADD COLUMN profile_pic VARCHAR(500)"))
                    added = True
                    print("--> Added 'profile_pic'")
                if 'language' not in columns:
                    conn.execute(text("ALTER TABLE employee ADD COLUMN language VARCHAR(10) DEFAULT 'ar'"))
                    added = True
                    print("--> Added 'language'")
                if 'theme_preference' not in columns:
                    conn.execute(text("ALTER TABLE employee ADD COLUMN theme_preference VARCHAR(20) DEFAULT 'dark'"))
                    added = True
                    print("--> Added 'theme_preference'")

                if added:
                    conn.commit()
                    print("Applied profile migrations to employee table.")
                else:
                    print("Employee table is up to date.")
    except Exception as e:
        print(f"Migration error (employee profile): {e}")

    # Migration: Add original_price columns to subscription_plans (core DB)
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'subscription_plans' in inspector.get_table_names():
            sp_columns = [col['name'] for col in inspector.get_columns('subscription_plans')]
            print(f"Current columns in 'subscription_plans': {sp_columns}")

            with db.engine.connect() as conn:
                sp_added = False
                if 'original_price_monthly' not in sp_columns:
                    conn.execute(text("ALTER TABLE subscription_plans ADD COLUMN original_price_monthly INTEGER"))
                    sp_added = True
                    print("--> Added 'original_price_monthly' to subscription_plans")
                if 'original_price_yearly' not in sp_columns:
                    conn.execute(text("ALTER TABLE subscription_plans ADD COLUMN original_price_yearly INTEGER"))
                    sp_added = True
                    print("--> Added 'original_price_yearly' to subscription_plans")

                if sp_added:
                    conn.commit()
                    print("Applied subscription_plans migrations.")
                else:
                    print("subscription_plans table is up to date.")
    except Exception as e:
        print(f"Migration error (subscription_plans): {e}")

# #region agent log (app-level)
def _debug_log_app(run_id: str, hypothesis_id: str, location: str, message: str, data: dict | None = None) -> None:
    import os, json, time
    try:
        root = app.root_path
        path = os.path.join(root, "debug-180817.log")
        payload = {
            "sessionId": "180817",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
# #endregion

# =====================================
# Context Processor (لتمرير البيانات لجميع القوالب)
# =====================================
@app.context_processor
def inject_global_data():
    """تمرير الصلاحيات والترجمة لجميع القوالب"""
    default = {
        "current_employee": None,
        "can_see_orders": False,
        "can_see_reports": False,
        "can_manage_inventory": False,
        "can_see_expenses": False,
        "can_manage_suppliers": False,
        "can_manage_customers": False,
        "can_see_accounts": False,
        "can_see_financial": False,
        # صلاحيات ظهور الروابط في القائمة الجانبية
        "can_use_pos": False,
        "can_see_shipping": False,
        "can_see_agents": False,
        "can_see_pages": False,
        "can_see_messages": False,
        "can_edit_price": False,
        "_": lambda x: x,
        "current_lang": "ar"
    }

    def translate(key):
        lang = session.get('language')
        if not lang and "user_id" in session:
            try:
                emp = db.session.get(Employee, session["user_id"])
                if emp and emp.language:
                    lang = emp.language
                    session['language'] = lang
            except: pass
        return get_string(key, lang or 'ar')

    try:
        lang_now = session.get('language', 'ar')
        print(f"DEBUG: Session language is '{lang_now}'")

        if "user_id" not in session:
            return {**default, "_": translate, "current_lang": lang_now}

        employee = db.session.get(Employee, session["user_id"])
        if not employee:
            return {**default, "_": translate, "current_lang": lang_now}

        final_lang = employee.language or lang_now
        print(f"DEBUG: Employee lang: {employee.language}, Final lang: {final_lang}")

        return {
            "current_employee": employee,
            "can_see_orders": employee.has_permission("view_orders"),
            "can_see_reports": employee.has_permission("view_reports"),
            "can_manage_inventory": employee.has_permission("manage_inventory"),
            "can_see_expenses": employee.has_permission("view_expenses"),
            "can_manage_suppliers": employee.has_permission("manage_suppliers"),
            "can_manage_customers": employee.has_permission("manage_customers"),
            "can_see_accounts": employee.has_permission("view_accounts"),
            "can_see_financial": employee.has_permission("view_financial"),
            # ربط أعلام القائمة الجانبية بصلاحيات الـ RBAC
            "can_use_pos": employee.has_permission("view_pos"),
            "can_see_shipping": employee.has_permission("view_shipping"),
            "can_see_agents": employee.has_permission("view_agents"),
            "can_see_pages": employee.has_permission("view_pages"),
            "can_see_messages": employee.has_permission("view_messages"),
            "can_edit_price": employee.has_permission("edit_price"),
            "_": translate,
            "current_lang": final_lang
        }
    except Exception as e:
        print(f"Error in context processor: {e}")
        return {**default, "_": translate}

# =====================================
# Login Guard (قبل أي صفحة)
# =====================================

_OPEN_ROUTES = [
    "/",
    "/pos",
    "/pos/login",
    "/static",
    "/pricing",
    "/signup",
    "/privacy",
    "/terms",
    "/contact",
    "/payment",
    "/login",
    "/payment/success",
    "/payments/failed",
    "/payments/mock-gateway",
    "/payments/simulate",
    "/upgrade",
    "/superadmin",
    "/messages/unread-count",  # واجهة للشارة — تُرجع JSON بدون إعادة توجيه
    "/api/landing-chat",  # مساعد الذكاء الاصطناعي لصفحة الهبوط
    "/telegram",  # بوت تيليجرام: webhook و setup و test — بدون تسجيل (ليستقبل التحديثات من Telegram)
]


def _is_public_path(path: str) -> bool:
    """تحقق إن كان المسار لا يحتاج تسجيل دخول (يُستخدم في require_login)."""
    if path == "/":
        return True
    for prefix in _OPEN_ROUTES:
        if prefix != "/" and path.startswith(prefix):
            return True
    return False


@app.before_request
def require_login():
    # #region agent log
    try:
        _debug_log_app(
            "run1",
            "H1",
            "app.require_login:entry",
            "before_request",
            {
                "path": request.path,
                "is_ajax": request.headers.get("X-Requested-With") == "XMLHttpRequest",
                "has_user_id": "user_id" in session,
            },
        )
    except Exception:
        pass
    # #endregion

    # مسارات مسموحة بدون تسجيل (الصفحة الرئيسية "/" تصل لـ root() فتُوجّه إلى /pricing)
    if _is_public_path(request.path or ""):
        return

    # إذا ما مسجّل دخول
    if "user_id" not in session:
        # #region agent log
        try:
            _debug_log_app(
                "run1",
                "H1",
                "app.require_login:redirect_login",
                "no user_id in session -> redirect /login",
                {"path": request.path},
            )
        except Exception:
            pass
        # #endregion
        return redirect("/login")

    # التحقق من صلاحية الاشتراك (SaaS)
    try:
        tenant_slug = session.get("tenant_slug")
        if tenant_slug:
            g.tenant = tenant_slug

            # Since g.tenant is now set, any queries to Tenant by mistake
            # would hit the tenant DB instead of Core DB.
            # To verify their subscription, we temporally unset g.tenant
            g.tenant = None
            from models.core.tenant import Tenant as CoreTenant
            core_tenant = CoreTenant.query.filter_by(slug=tenant_slug).first()
            g.tenant = tenant_slug  # Restore

            if not core_tenant or not core_tenant.is_subscription_valid():
                # إنهاء الجلسة وإرجاعه لصفحة الخطط إذا انتهى الاشتراك
                session.clear()
                return redirect("/pricing")
    except Exception as e:
        print(f"Error checking tenant subscription: {e}")
        pass



@app.context_processor
def inject_system_settings():
    """تمرير إعدادات النظام العامة لجميع القوالب باسم system_settings."""
    # لا نستعلم عن SystemSettings في مسارات الإدارة العليا (قاعدة Core قد لا تحتوي الجدول)
    if request.path.startswith("/superadmin"):
        return {"system_settings": None}
    try:
        settings = SystemSettings.get_settings()
    except Exception:
        settings = None
    return {"system_settings": settings}


# تفضيل آمن عند فشل تحميل خطط الاشتراك (يتجنب 500)
_SAFE_PLAN = {
    "key": "basic",
    "name": "الخطة الأساسية",
    "features": {},
}

@app.context_processor
def inject_plan_context():
    """
    تمرير بيانات خطة الاشتراك لجميع القوالب تلقائياً.
    الخطة تُقرأ من قاعدة بيانات الشركة في كل طلب حتى تظهر التغييرات فوراً (مثلاً بعد تغيير الخطة من الإدارة العليا).
    """
    _fallback = {
        "current_plan": _SAFE_PLAN,
        "plan_key":     "basic",
        "plan_has":     lambda f: False,
    }
    try:
        from utils.plan_limits import get_plan, has_feature as _hf

        plan_key = session.get("plan_key") or "basic"
        # عند وجود جلسة شركة، جلب الخطة الحالية من قاعدة بيانات الشركة لتعكس أي تغيير من الإدارة العليا
        try:
            tenant_slug = session.get("tenant_slug")
            if tenant_slug and getattr(g, "tenant", None) == tenant_slug:
                from models.tenant import Tenant as TenantModel
                t = TenantModel.query.first()
                if t and getattr(t, "plan_key", None):
                    plan_key = t.plan_key
                    session["plan_key"] = plan_key
        except Exception:
            pass

        plan = get_plan(plan_key)

        # العرض يتبع الخطة الفعلية: في القائمة الجانبية تظهر الأقفال للميزات غير المشمولة في الخطّة
        def plan_has(feature, _hf=_hf, _pk=plan_key):
            try:
                return _hf(_pk, feature)
            except Exception:
                return False

        return {
            "current_plan": plan,
            "plan_key":     plan_key,
            "plan_has":     plan_has,
        }
    except Exception:
        return _fallback


# =====================================
# Register Blueprints
# =====================================
app.register_blueprint(index_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(ai_bp, url_prefix="/ai")
app.register_blueprint(social_ai_bp, url_prefix="/social-ai")
app.register_blueprint(workflow_api)

app.register_blueprint(pos_bp)
app.register_blueprint(employees_bp, url_prefix="/employees")
app.register_blueprint(inventory_bp, url_prefix="/inventory")
app.register_blueprint(purchases_bp, url_prefix="/purchases")
app.register_blueprint(inventory_ledger_bp, url_prefix="/inventory/ledger")
app.register_blueprint(cash_bp, url_prefix="/cash")
app.register_blueprint(customers_bp)
app.register_blueprint(orders_bp, url_prefix="/orders")
app.register_blueprint(shipping_bp, url_prefix="/shipping")
app.register_blueprint(reports_bp, url_prefix="/reports")
app.register_blueprint(suppliers_bp, url_prefix="/suppliers")
app.register_blueprint(expenses_bp, url_prefix="/expenses")
app.register_blueprint(accounts_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(messages_bp)
app.register_blueprint(delivery_bp)
app.register_blueprint(assistant_bp)
app.register_blueprint(agents_bp)
app.register_blueprint(delivery_agent_bp)
app.register_blueprint(pages_bp)
from routes.permissions import permissions_bp
app.register_blueprint(permissions_bp, url_prefix="/admin/permissions")

from routes.superadmin import superadmin_bp
app.register_blueprint(superadmin_bp)

from routes.admin import admin_bp
app.register_blueprint(admin_bp)

app.register_blueprint(invoice_store_bp)
app.register_blueprint(storefront_bp)
app.register_blueprint(telegram_bp)

# =====================================
# Logging
# =====================================
import logging
if not app.debug:
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)

# تحذير عند بدء التشغيل إذا لم تُضبط متغيرات بوت تيليجرام (لظهورها في السجلات)
_bot_token = (app.config.get("TELEGRAM_BOT_TOKEN") or app.config.get("BOT_TOKEN") or os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
_openai_key = (app.config.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
if not _bot_token:
    app.logger.warning("BOT_TOKEN / TELEGRAM_BOT_TOKEN not set; Telegram bot will not send replies. Set in systemd Environment= or .env.")
if not _openai_key:
    app.logger.warning("OPENAI_API_KEY not set; Telegram AI replies will be skipped. Set in systemd Environment= or .env.")

# =====================================
# Error Handlers
# =====================================
from werkzeug.exceptions import RequestEntityTooLarge

@app.errorhandler(RequestEntityTooLarge)
def request_entity_too_large(e):
    return jsonify({
        "success": False,
        "error": "file_too_large",
        "message": "حد الحجم 500 ميجابايت.",
    }), 413

@app.errorhandler(404)
def not_found(e):
    if request.accept_mimetypes.best == "application/json":
        return jsonify({"error": "Not found"}), 404
    tpl = os.path.join(app.root_path, "templates", "404.html")
    return (render_template("404.html"), 404) if os.path.exists(tpl) else ("<h1>404</h1><p>الصفحة غير موجودة.</p>", 404)

@app.errorhandler(500)
def server_error(e):
    app.logger.exception("Server error: %s", e)
    if request.accept_mimetypes.best == "application/json":
        return jsonify({"error": "Internal server error"}), 500
    tpl = os.path.join(app.root_path, "templates", "500.html")
    return (render_template("500.html"), 500) if os.path.exists(tpl) else ("<h1>500</h1><p>خطأ في الخادم.</p>", 500)

# =====================================
# Security Headers & Gzip
# =====================================
@app.after_request
def add_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    if app.config.get("SESSION_COOKIE_SECURE"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

try:
    import importlib.util
    if importlib.util.find_spec("flask_compress"):
        flask_compress = importlib.import_module("flask_compress")
        flask_compress.Compress(app)
except (ImportError, AttributeError):
    pass

# =====================================
# Social AI Scheduler
# =====================================
def _start_social_ai_scheduler():
    """مجدول بسيط لمعالجة social_posts المجدولة لكل المستأجرين."""
    import os
    import sys

    if os.environ.get("SERVER_SOFTWARE", "").startswith("gunicorn/") or "gunicorn" in (sys.argv[0] or ""):
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
        from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]
        from flask import g
        from models.tenant import Tenant  # type: ignore[attr-defined]
        from social_ai.scheduler import process_scheduled_social_posts

        def _run_social_ai_scheduled():
            with app.app_context():
                try:
                    tenants = Tenant.query.all()
                except Exception:
                    tenants = []
                for t in tenants:
                    slug = getattr(t, "slug", None)
                    if not slug:
                        continue
                    g.tenant = slug
                    try:
                        process_scheduled_social_posts()
                    except Exception:
                        db.session.rollback()
                    finally:
                        g.tenant = None

        scheduler = BackgroundScheduler()
        scheduler.add_job(_run_social_ai_scheduled, IntervalTrigger(minutes=1), id="social_ai_scheduled")
        scheduler.start()
    except Exception:
        pass

_start_social_ai_scheduler()

# =====================================
# AI Agent Workflows Scheduler
# =====================================
def _start_ai_agent_scheduler():
    """
    مجدول بسيط لتشغيل Workflows الخاصة بالـ AI Agents بشكل دوري
    (مثل وكيل الرد على التعليقات، وكيل تيليجرام، واتساب...).
    """
    import os
    import sys

    # لا نشغّل المجدول تحت Gunicorn لنفس الأسباب المذكورة أعلاه
    if os.environ.get("SERVER_SOFTWARE", "").startswith("gunicorn/") or "gunicorn" in (sys.argv[0] or ""):
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
        from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]
        from flask import g
        from models.tenant import Tenant  # type: ignore[attr-defined]
        from datetime import datetime, timedelta, timezone

        def _run_ai_agent_workflows():
            """
            لكل مستأجر (tenant) نشغّل كل الـ workflows المفعّلة التي تحتوي عقدة
            comment-listener أو whatsapp_listener أو telegram_listener.
            """
            with app.app_context():
                try:
                    tenants = Tenant.query.all()
                except Exception:
                    tenants = []

                now = datetime.now(timezone.utc)
                min_interval = timedelta(seconds=5)

                for t in tenants:
                    slug = getattr(t, "slug", None)
                    if not slug:
                        continue

                    g.tenant = slug
                    try:
                        # قراءة كل الـ workflows المفعّلة لهذا المستأجر
                        q = AgentWorkflow.query.filter_by(is_active=True)
                        workflows = q.all()
                        for wf in workflows:
                            graph = wf.graph_json or {}
                            nodes = graph.get("nodes") or []
                            has_listener = any(
                                (n.get("type") in ("comment-listener", "whatsapp_listener", "telegram_listener"))
                                for n in nodes
                            )
                            if not has_listener:
                                continue

                            # تفادي تشغيل نفس الـ workflow بشكل متوازي أو بشكل مفرط
                            last_exe = (
                                wf.executions.order_by(AgentExecution.started_at.desc()).first()
                            )
                            if last_exe:
                                if last_exe.status == "running":
                                    continue
                                if last_exe.started_at:
                                    started_at = last_exe.started_at
                                    if started_at.tzinfo is None:
                                        started_at = started_at.replace(tzinfo=timezone.utc)
                                    if now - started_at < min_interval:
                                        continue

                            exe = AgentExecution(workflow_id=wf.id, status="running")
                            db.session.add(exe)
                            db.session.commit()

                            try:
                                execute_workflow(exe)
                            except Exception:
                                db.session.rollback()
                    finally:
                        g.tenant = None

        scheduler = BackgroundScheduler()
        # تشغيل كل 5 ثواني لمراقبة الرسائل/التعليقات
        scheduler.add_job(_run_ai_agent_workflows, IntervalTrigger(seconds=5), id="ai_agent_workflows")
        scheduler.start()
    except Exception:
        # فشل المجدول يجب ألا يمنع تشغيل التطبيق الأساسي
        pass


_start_ai_agent_scheduler()

# Backward-compatible alias for typoed social-ai route
@app.route("/social-i")
@app.route("/social-i/")
def social_i_alias():
    return redirect("/social-ai/", code=302)

@app.route("/social-i/<path:rest>")
def social_i_alias_rest(rest):
    return redirect(f"/social-ai/{rest}", code=302)

# =====================================
# Run
# =====================================
if __name__ == "__main__":
    import os

    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "5008"))
    debug = os.environ.get("FLASK_DEBUG", "0") in ("1", "true", "True")

    app.run(host=host, port=port, debug=debug)