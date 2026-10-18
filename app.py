from flask import Flask, current_app, redirect, session, url_for, request, g, jsonify, render_template, flash, send_from_directory
from flask_login import current_user
import click
print("=== FINORA APP STARTING - V1.1 (i18n check) ===")
from extensions import db
# Models (Core)
from models.core.tenant import Tenant
from models.core.super_admin import SuperAdmin
from models.core.payment_request import PaymentRequest
from models.core.subscription_plan import SubscriptionPlan

# Models (Tenant)
from models.customer import Customer
from models.customer_credit import CustomerCreditPlan, CustomerInstallment, CustomerCreditPayment
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
from models.ai_assistant_control import (
    AIActionItem,
    AIActionPlan,
    AIAuditRun,
    AIChatMessage,
    AIChatSession,
    AIScheduledAudit,
    AIToolCallLog,
    AIUploadedFile,
)
from models.investment_proposal import InvestmentProposal
from models.delivery_agent import DeliveryAgent
from models.page import Page
from models.role import Role, Permission
from models.comment_log import CommentLog
from models.telegram_chat_profile import TelegramChatProfile
from models.telegram_booking_session import TelegramBookingSession
from models.beauty_service import BeautyService
from models.beauty_service_product import BeautyServiceProduct
from models.beauty_appointment import BeautyAppointment
from models.beauty_session_note import BeautySessionNote
from models.note import Note, NoteRevision

# Routes
from routes.index import index_bp
from routes.payments import payments_bp
from routes.pos import pos_bp
from routes.employees import employees_bp
from routes.payroll import payroll_bp
from modules.hr import hr_bp as hr_desktop_bp, public_bp as hr_recruit_public_bp
from routes.inventory import inventory_bp
from routes.branch_api import branch_api_bp
from routes.delivery_fee_api import delivery_fee_api_bp
from routes.stock_transfers import stock_transfers_bp
from routes.purchases import purchases_bp
from routes.purchase_lists import purchase_lists_bp
from routes.product_dedup import product_dedup_bp
from routes.inventory_ledger import inventory_ledger_bp
from routes.media_library import media_library_bp
from routes.cash import cash_bp
from routes.customers import customers_bp
from routes.customer_credit import customer_credit_bp
from routes.orders import orders_bp
from routes.shipping import shipping_bp
from routes.reports import reports_bp
from routes.daily_closing import daily_closing_bp
from routes.suppliers import suppliers_bp
from routes.expenses import expenses_bp
from routes.accounts import accounts_bp
from routes.ai import ai_bp
from routes.social_ai_routes import social_ai_bp
from routes.settings import settings_bp
from routes.messages import messages_bp
from routes.delivery import delivery_bp
from routes.assistant import assistant_bp
from routes.investments import investments_bp
from routes.agents import agents_bp
from routes.delivery_agent import delivery_agent_bp
from routes.pages import pages_bp
from routes.activity import activity_bp
from routes.notes import notes_bp
from routes.invoice_store import invoice_store_bp
from routes.storefront import storefront_bp
from modules.installments import init_installments
from modules.order_installment_lifecycle import init_order_installment_lifecycle
from routes.quick_sale import quick_sale_bp
from routes.beauty import beauty_bp
from routes.hr import hr_bp
from routes.maintenance import maintenance_bp
from routes.fixed_assets import fixed_assets_bp
from routes.rotating_savings import rotating_savings_bp, rotating_savings_bp_alias
from routes.whatsapp_webhook import whatsapp_webhook_bp
from modules.ai_sales.routes import ai_sales_bp, ai_sales_webhook_bp
from routes.landing import landing_bp
from telegram_bot import telegram_bp
from api_workflows import workflow_api
from models.ai_agent import AgentWorkflow, AgentExecution
from social_ai.workflow_engine import execute_workflow
from utils.starter_business import DEFAULT_FEATURES as STARTER_BUSINESS_DEFAULT_FEATURES
from utils.starter_business import allows as starter_business_allows
from utils.starter_business import feature_for_path as _starter_business_feature_for_path

# =====================================
# App Setup
# =====================================
import os
import sqlite3
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

from utils.sidebar_navigation import organized_sidebar
app.jinja_env.globals["organized_sidebar"] = organized_sidebar

# =====================================
# i18n / Multi-language Setup
# =====================================
import json
from utils.invoice_text_format import format_invoice_text
import os

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

@app.template_filter("json_object")
def json_object(value):
    try:
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}

@app.template_filter("warranty_label")
def warranty_label(value):
    raw = str(value or "").strip().lower()
    labels = {
        "none": "بدون ضمان",
        "no": "بدون ضمان",
        "0": "بدون ضمان",
        "6m": "6 أشهر",
        "1y": "12 شهر",
        "2y": "24 شهر",
    }
    if raw in labels:
        return labels[raw]
    if raw.endswith("m") and raw[:-1].isdigit():
        months = int(raw[:-1])
        return f"{months} شهر" if months == 1 else f"{months} أشهر"
    if raw.endswith("y") and raw[:-1].isdigit():
        years = int(raw[:-1])
        return f"{years * 12} شهر"
    return value or "12 شهر"

@app.template_filter("invoice_rich_text")
def invoice_rich_text(value):
    return format_invoice_text(value)

app.config["UPLOAD_FOLDER"] = "static/uploads/messages"
# حد رفع الملفات (للرسائل، النشر التلقائي صورة/فيديو حتى 500 ميجا)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB
# مجلد وسائط الأوتوبوستر: إن لم يُعيَّن = جذر التطبيق/media (على السيرفر: /var/www/finora/supermaxi/media)
app.config["AUTOPOSTER_MEDIA_ROOT"] = os.environ.get("AUTOPOSTER_MEDIA_ROOT") or os.path.join(app.root_path, "media")

# Reload templates from disk after Smart Deploy (workers restart still recommended)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
if not app.config.get("DEBUG"):
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 300
else:
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

db.init_app(app)
from utils.branch_orm_scope import install_branch_orm_scope

install_branch_orm_scope()

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
    from models.core.feature import TenantFeature, FeatureAuditLog  # noqa: F401
    from models.core.landing_visit import LandingVisit
    from models.core.landing_content import (  # noqa: F401
        LandingCTA,
        LandingAuditLog,
        LandingFAQ,
        LandingFeature,
        LandingMedia,
        LandingModule,
        LandingPageSettings,
        LandingPricingPlan,
        LandingSEO,
        LandingSection,
        LandingTestimonial,
    )
    from models.user import User  # جدول users مطلوب لـ tenant_template_purchases / tenant_template_settings
    from models.telegram_inbox_message import TelegramInboxMessage  # noqa: F401
    from models.telegram_chat_profile import TelegramChatProfile  # noqa: F401
    from models.telegram_booking_session import TelegramBookingSession  # noqa: F401
    from models.beauty_service import BeautyService  # noqa: F401
    from models.beauty_service_product import BeautyServiceProduct  # noqa: F401
    from models.beauty_appointment import BeautyAppointment  # noqa: F401
    from models.beauty_session_note import BeautySessionNote  # noqa: F401
    # Employee.default_warehouse_id references this table.  Register it before
    # create_all so a brand-new core/tenant database can resolve the FK graph.
    from modules.wholesale.models.warehouse import Warehouse  # noqa: F401
    from models.note import Note, NoteRevision  # noqa: F401
    from modules.employee_desk.models import EmployeeQuickReply  # noqa: F401
    from models.customer_credit import CustomerCreditPlan, CustomerInstallment, CustomerCreditPayment  # noqa: F401
    from models.rotating_savings import (  # noqa: F401
        RotatingSaving,
        RotatingSavingPayment,
        RotatingSavingReceipt,
        RotatingSavingAttachment,
        RotatingSavingSettings,
    )
    from models.activity_log import ActivityLog  # noqa: F401
    from models.purchase_list import PurchaseList, PurchaseListItem  # noqa: F401
    from models.receipt import Receipt, ReceiptAllocation  # noqa: F401
    from models.ai_assistant_control import (  # noqa: F401
        AIActionItem,
        AIActionPlan,
        AIAuditRun,
        AIChatMessage,
        AIChatSession,
        AIScheduledAudit,
        AIToolCallLog,
        AIUploadedFile,
    )
    from models.investment_proposal import InvestmentProposal  # noqa: F401
    from models.core.platform_announcement import PlatformAnnouncement  # noqa: F401
    from models.core.announcement_send_log import AnnouncementSendLog  # noqa: F401
    from models.core.leads.models import (  # noqa: F401
        BusinessActivity,
        BusinessLead,
        BusinessLeadPhone,
        LeadAuditLog,
        LeadAutomationRule,
        LeadDiscoveryRun,
        LeadDuplicateCandidate,
        LeadFollowUp,
        LeadImportBatch,
        LeadImportRow,
        LeadInteraction,
        LeadMergeLog,
        LeadNote,
        LeadSavedView,
        LeadScore,
        LeadSourceRecord,
        LeadStatusConfig,
    )

    # Gunicorn imports the app in multiple workers. Serialize PostgreSQL DDL so
    # a newly added model cannot make workers race while creating the same table.
    if db.engine.dialect.name == "postgresql":
        from sqlalchemy import text as sa_text

        schema_lock_key = 736251904  # Stable application-level advisory lock.
        with db.engine.connect() as schema_lock_conn:
            schema_lock_conn.execute(
                sa_text("SELECT pg_advisory_lock(:lock_key)"),
                {"lock_key": schema_lock_key},
            )
            try:
                db.create_all()
            finally:
                schema_lock_conn.execute(
                    sa_text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": schema_lock_key},
                )
    else:
        db.create_all()

    try:
        from sqlalchemy import inspect, text

        inspector = inspect(db.engine)
        if "system_settings" in inspector.get_table_names():
            settings_cols = {col["name"] for col in inspector.get_columns("system_settings")}
            settings_additions = {
                "facebook_app_id": "ALTER TABLE system_settings ADD COLUMN facebook_app_id VARCHAR(100)",
                "facebook_app_secret": "ALTER TABLE system_settings ADD COLUMN facebook_app_secret VARCHAR(255)",
            }
            with db.engine.connect() as conn:
                added = False
                for col, stmt in settings_additions.items():
                    if col not in settings_cols:
                        conn.execute(text(stmt))
                        added = True
                        print(f"Added {col} column to system_settings table.")
                if added:
                    conn.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Migration note (system_settings columns): {e}")

    try:
        from utils.landing_content import ensure_landing_seed

        ensure_landing_seed()
    except Exception as e:
        db.session.rollback()
        print(f"Landing content seed note: {e}")

    try:
        from utils.treasury_schema_guard import ensure_treasury_schema

        ensure_treasury_schema()
    except Exception as e:
        db.session.rollback()
        print(f"Treasury schema note: {e}")

    try:
        from services.leads_crm.schema import ensure_leads_crm_schema
        from services.leads_crm.seed import seed_leads_crm_defaults

        ensure_leads_crm_schema()
        seed_leads_crm_defaults()
    except Exception as e:
        db.session.rollback()
        print(f"Leads CRM schema note: {e}")

    try:
        import sqlite3
        from extensions_tenant import get_tenant_engine
        from utils.payroll_schema import ensure_payroll_schema

        tenants_dir = os.path.join(app.root_path, "tenants")
        # Tenant schemas are upgraded lazily when that company is opened.
        # Sweeping every SQLite file here made startup grow with the entire
        # archive (including test/backup databases) and could block for
        # minutes on WAL locks.  Operations can explicitly opt into the bulk
        # sweep during a maintenance window.
        if (
            os.environ.get("RUN_STARTUP_TENANT_MIGRATIONS") == "1"
            and os.path.isdir(tenants_dir)
        ):
            for db_name in sorted(os.listdir(tenants_dir)):
                if not db_name.endswith(".db"):
                    continue
                tenant_slug = os.path.splitext(db_name)[0]
                try:
                    g.tenant = tenant_slug
                    ensure_payroll_schema()
                except Exception as _payroll_err:
                    print(f"Payroll schema note ({tenant_slug}): {_payroll_err}")
    except Exception as e:
        print(f"Payroll schema migration note: {e}")

    try:
        from sqlalchemy import inspect, text

        inspector = inspect(db.engine)
        for tenant_table in ("tenants", "tenant"):
            if tenant_table not in inspector.get_table_names():
                continue
            tenant_cols = {col["name"] for col in inspector.get_columns(tenant_table)}
            additions = {
                "business_type": "VARCHAR(50) DEFAULT 'general'",
                "feature_overrides_json": "TEXT",
            }
            for column_name, definition in additions.items():
                if column_name not in tenant_cols:
                    db.session.execute(text(
                        f'ALTER TABLE "{tenant_table}" ADD COLUMN "{column_name}" {definition}'
                    ))
            db.session.commit()
            print(f"Ensured business columns on core {tenant_table} table.")
    except Exception as e:
        db.session.rollback()
        print(f"Migration note (core tenant business_type): {e}")

    try:
        import sqlite3
        from extensions_tenant import get_tenant_engine

        tenants_dir = os.path.join(app.root_path, "tenants")
        if (
            os.environ.get("RUN_STARTUP_TENANT_MIGRATIONS") == "1"
            and os.path.isdir(tenants_dir)
        ):
            for db_name in sorted(os.listdir(tenants_dir)):
                if not db_name.endswith(".db"):
                    continue
                tenant_slug = os.path.splitext(db_name)[0]
                db_path = os.path.join(tenants_dir, db_name)
                try:
                    engine = get_tenant_engine(tenant_slug)
                    db.Model.metadata.create_all(engine)
                    from utils.inventory_audit_trail import ensure_inventory_audit_schema_on_engine
                    ensure_inventory_audit_schema_on_engine(engine)
                    conn = sqlite3.connect(db_path)
                    cur = conn.cursor()
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    existing_tables = {row[0] for row in cur.fetchall()}
                    if "tenant" in existing_tables:
                        cur.execute("PRAGMA table_info(tenant)")
                        tenant_cols = {row[1] for row in cur.fetchall()}
                        if "business_type" not in tenant_cols:
                            cur.execute("ALTER TABLE tenant ADD COLUMN business_type TEXT DEFAULT 'general'")
                        if "feature_overrides_json" not in tenant_cols:
                            cur.execute("ALTER TABLE tenant ADD COLUMN feature_overrides_json TEXT")
                    if "system_settings" in existing_tables:
                        cur.execute("PRAGMA table_info(system_settings)")
                        system_settings_cols = {row[1] for row in cur.fetchall()}
                        if "facebook_app_id" not in system_settings_cols:
                            cur.execute("ALTER TABLE system_settings ADD COLUMN facebook_app_id TEXT")
                        if "facebook_app_secret" not in system_settings_cols:
                            cur.execute("ALTER TABLE system_settings ADD COLUMN facebook_app_secret TEXT")
                    if "product" in existing_tables:
                        cur.execute("PRAGMA table_info(product)")
                        product_cols = {row[1] for row in cur.fetchall()}
                        product_additions = {
                            "sku": "ALTER TABLE product ADD COLUMN sku VARCHAR(100)",
                            "description": "ALTER TABLE product ADD COLUMN description TEXT",
                            "image_url": "ALTER TABLE product ADD COLUMN image_url VARCHAR(500)",
                            "meta_json": "ALTER TABLE product ADD COLUMN meta_json TEXT",
                            "skin_type": "ALTER TABLE product ADD COLUMN skin_type TEXT",
                            "usage_type": "ALTER TABLE product ADD COLUMN usage_type TEXT",
                            "requires_patch_test": "ALTER TABLE product ADD COLUMN requires_patch_test BOOLEAN DEFAULT 0",
                            "expiry_date": "ALTER TABLE product ADD COLUMN expiry_date DATE",
                            "opened_date": "ALTER TABLE product ADD COLUMN opened_date DATE",
                            "batch_number": "ALTER TABLE product ADD COLUMN batch_number TEXT",
                        }
                        for col, stmt in product_additions.items():
                            if col not in product_cols:
                                cur.execute(stmt)
                    if "supplier" in existing_tables:
                        cur.execute("PRAGMA table_info(supplier)")
                        supplier_cols = {row[1] for row in cur.fetchall()}
                        if "opening_balance" not in supplier_cols:
                            cur.execute(
                                "ALTER TABLE supplier ADD COLUMN opening_balance INTEGER DEFAULT 0"
                            )
                        if "phone2" not in supplier_cols:
                            cur.execute(
                                "ALTER TABLE supplier ADD COLUMN phone2 VARCHAR(50)"
                            )
                    if "shipping_company" in existing_tables:
                        cur.execute("PRAGMA table_info(shipping_company)")
                        shipping_cols = {row[1] for row in cur.fetchall()}
                        if "opening_balance" not in shipping_cols:
                            cur.execute(
                                "ALTER TABLE shipping_company ADD COLUMN opening_balance INTEGER DEFAULT 0"
                            )
                    if "employee" in existing_tables:
                        cur.execute("PRAGMA table_info(employee)")
                        employee_cols = {row[1] for row in cur.fetchall()}
                        if "last_active" not in employee_cols:
                            cur.execute(
                                "ALTER TABLE employee ADD COLUMN last_active DATETIME"
                            )
                    treasury_tables = (
                        "account_transaction",
                        "supplier_payment",
                        "shipping_payment",
                        "purchase_payment",
                    )
                    for tbl in treasury_tables:
                        if tbl not in existing_tables:
                            continue
                        cur.execute(f"PRAGMA table_info({tbl})")
                        cols = {row[1] for row in cur.fetchall()}
                        if "treasury_account_id" not in cols:
                            cur.execute(
                                f"ALTER TABLE {tbl} ADD COLUMN treasury_account_id INTEGER"
                            )
                    if "account_transaction" in existing_tables:
                        cur.execute("PRAGMA table_info(account_transaction)")
                        at_cols = {row[1] for row in cur.fetchall()}
                        if "treasury_transfer_id" not in at_cols:
                            cur.execute(
                                "ALTER TABLE account_transaction ADD COLUMN treasury_transfer_id INTEGER"
                            )
                    if "invoice_settings" in existing_tables:
                        cur.execute("PRAGMA table_info(invoice_settings)")
                        is_cols = {row[1] for row in cur.fetchall()}
                        report_additions = {
                            "return_policy_notes": "ALTER TABLE invoice_settings ADD COLUMN return_policy_notes TEXT",
                            "report_company_name": "ALTER TABLE invoice_settings ADD COLUMN report_company_name VARCHAR(200)",
                            "report_logo_path": "ALTER TABLE invoice_settings ADD COLUMN report_logo_path VARCHAR(500)",
                            "report_address": "ALTER TABLE invoice_settings ADD COLUMN report_address TEXT",
                            "report_phone": "ALTER TABLE invoice_settings ADD COLUMN report_phone VARCHAR(50)",
                            "report_footer_text": "ALTER TABLE invoice_settings ADD COLUMN report_footer_text TEXT",
                            "report_show_logo": "ALTER TABLE invoice_settings ADD COLUMN report_show_logo BOOLEAN DEFAULT TRUE",
                            "warranty_card_background": "ALTER TABLE invoice_settings ADD COLUMN warranty_card_background TEXT DEFAULT 'linear-gradient(135deg, #031021 0%, #1f2e42 100%)'",
                        }
                        for col, stmt in report_additions.items():
                            if col not in is_cols:
                                cur.execute(stmt)
                    if "order_item" in existing_tables:
                        cur.execute("PRAGMA table_info(order_item)")
                        order_item_cols = {row[1] for row in cur.fetchall()}
                        if "fulfillment_branch_id" not in order_item_cols:
                            cur.execute("ALTER TABLE order_item ADD COLUMN fulfillment_branch_id INTEGER")
                        if "variant_color" not in order_item_cols:
                            cur.execute("ALTER TABLE order_item ADD COLUMN variant_color VARCHAR(80)")
                    if "invoice" in existing_tables:
                        cur.execute("PRAGMA table_info(invoice)")
                        invoice_cols = {row[1] for row in cur.fetchall()}
                        invoice_additions = {
                            "branch_id": "ALTER TABLE invoice ADD COLUMN branch_id INTEGER",
                            "discount_amount": "ALTER TABLE invoice ADD COLUMN discount_amount INTEGER DEFAULT 0",
                            "is_stock_locked": "ALTER TABLE invoice ADD COLUMN is_stock_locked BOOLEAN DEFAULT 0",
                            "stock_lock_reason": "ALTER TABLE invoice ADD COLUMN stock_lock_reason TEXT",
                            "stock_locked_at": "ALTER TABLE invoice ADD COLUMN stock_locked_at DATETIME",
                            "stock_unlocked_at": "ALTER TABLE invoice ADD COLUMN stock_unlocked_at DATETIME",
                        }
                        for col, stmt in invoice_additions.items():
                            if col not in invoice_cols:
                                cur.execute(stmt)
                        stock_state_added = "stock_is_deducted" not in invoice_cols
                        if stock_state_added:
                            cur.execute("ALTER TABLE invoice ADD COLUMN stock_is_deducted BOOLEAN DEFAULT 1")
                        if "stock_deducted_at" not in invoice_cols:
                            cur.execute("ALTER TABLE invoice ADD COLUMN stock_deducted_at DATETIME")
                        if "stock_restored_at" not in invoice_cols:
                            cur.execute("ALTER TABLE invoice ADD COLUMN stock_restored_at DATETIME")
                        if stock_state_added:
                            state_where = (
                                ("COALESCE(is_stock_locked, 0) = 1 OR " if "is_stock_locked" in invoice_cols else "")
                                + "status IN ('ملغي','راجع','مرتجع','راجعة','راجعه') "
                                + "OR payment_status IN ('ملغي','راجع','مرتجع','راجعة','راجعه')"
                            )
                            cur.execute(
                                "UPDATE invoice SET stock_is_deducted = 0 "
                                f"WHERE {state_where}"
                            )
                            cur.execute(
                                "UPDATE invoice SET stock_deducted_at = created_at "
                                "WHERE stock_deducted_at IS NULL AND (stock_is_deducted = 1 "
                                "OR status IN ('ملغي','راجع','مرتجع','راجعة','راجعه') "
                                "OR payment_status IN ('ملغي','راجع','مرتجع','راجعة','راجعه'))"
                            )
                            cur.execute(
                                "UPDATE invoice SET stock_restored_at = created_at "
                                "WHERE stock_restored_at IS NULL AND stock_deducted_at IS NOT NULL "
                                "AND stock_is_deducted = 0"
                            )
                        if "shipping_barcodes_json" not in invoice_cols:
                            cur.execute(
                                "ALTER TABLE invoice ADD COLUMN shipping_barcodes_json TEXT"
                            )
                        cur.execute(
                            "UPDATE invoice SET status = ? "
                            "WHERE status = ? AND payment_status = ?",
                            ("تم التوصيل", "مسدد", "مسدد"),
                        )
                        migrated = cur.rowcount or 0
                        if migrated:
                            print(
                                f"Normalized {migrated} delivered order(s) in tenant {tenant_slug}"
                            )
                    conn.commit()
                    conn.close()
                except Exception as _tenant_err:
                    print(f"Tenant migration note ({db_name}, beauty/business type): {_tenant_err}")
    except Exception as e:
        print(f"Migration note (tenant beauty/business type): {e}")

    try:
        from utils.order_stock_policy import initialize_registered_tenant_policies

        policy_init = (
            initialize_registered_tenant_policies()
            if os.environ.get("RUN_STARTUP_TENANT_MIGRATIONS") == "1"
            else {"tenants": {}, "errors": {}}
        )
        for tenant_slug, result in policy_init["tenants"].items():
            if result.get("migrated"):
                print(
                    "Deferred order stock policy initialized "
                    f"({tenant_slug}): restored {result.get('restored_orders', 0)} "
                    f"order(s) / {result.get('restored_units', 0)} unit(s)."
                )
        for tenant_slug, error in policy_init["errors"].items():
            print(f"Deferred order stock policy note ({tenant_slug}): {error}")
    except Exception as e:
        db.session.rollback()
        print(f"Deferred order stock policy startup note: {e}")

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
            if 'reply_to_id' not in message_columns:
                db.session.execute(text("ALTER TABLE message ADD COLUMN reply_to_id INTEGER"))
            db.session.commit()
    except Exception as e:
        print(f"Migration note: {e}")

    # Migration: Add financial report settings columns to invoice_settings (single-DB fallback)
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'invoice_settings' in inspector.get_table_names():
            is_columns = {col['name'] for col in inspector.get_columns('invoice_settings')}
            report_additions = {
                "return_policy_notes": "ALTER TABLE invoice_settings ADD COLUMN return_policy_notes TEXT",
                "report_company_name": "ALTER TABLE invoice_settings ADD COLUMN report_company_name VARCHAR(200)",
                "report_logo_path": "ALTER TABLE invoice_settings ADD COLUMN report_logo_path VARCHAR(500)",
                "report_address": "ALTER TABLE invoice_settings ADD COLUMN report_address TEXT",
                "report_phone": "ALTER TABLE invoice_settings ADD COLUMN report_phone VARCHAR(50)",
                "report_footer_text": "ALTER TABLE invoice_settings ADD COLUMN report_footer_text TEXT",
                "report_show_logo": "ALTER TABLE invoice_settings ADD COLUMN report_show_logo BOOLEAN DEFAULT TRUE",
                "warranty_card_background": "ALTER TABLE invoice_settings ADD COLUMN warranty_card_background TEXT DEFAULT 'linear-gradient(135deg, #031021 0%, #1f2e42 100%)'",
            }
            for col, stmt in report_additions.items():
                if col not in is_columns:
                    db.session.execute(text(stmt))
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Migration note (invoice_settings report columns): {e}")

    # Migration: Telegram booking memory columns/tables
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(db.engine)
        if "customer" in inspector.get_table_names():
            customer_columns = [col["name"] for col in inspector.get_columns("customer")]
            if "tg_chat_id" not in customer_columns:
                db.session.execute(text("ALTER TABLE customer ADD COLUMN tg_chat_id VARCHAR(64)"))
                db.session.commit()
                print("Added tg_chat_id column to customer table.")

        from models.telegram_chat_profile import TelegramChatProfile

        TelegramChatProfile.__table__.create(bind=db.engine, checkfirst=True)
        TelegramBookingSession.__table__.create(bind=db.engine, checkfirst=True)
        db.session.commit()
        print("Ensured telegram_chat_profiles + telegram_booking_sessions tables exist.")
    except Exception as e:
        print(f"Migration note (telegram booking memory): {e}")
    try:
        # Apply same booking-memory migration on tenant SQLite DBs.
        import os
        import sqlite3

        tenants_dir = os.path.join(app.root_path, "tenants")
        if (
            os.environ.get("RUN_STARTUP_TENANT_MIGRATIONS") == "1"
            and os.path.isdir(tenants_dir)
        ):
            for db_name in sorted(os.listdir(tenants_dir)):
                if not db_name.endswith(".db"):
                    continue
                db_path = os.path.join(tenants_dir, db_name)
                try:
                    conn = sqlite3.connect(db_path)
                    cur = conn.cursor()
                    cur.execute("PRAGMA table_info(customer)")
                    cols = [r[1] for r in cur.fetchall()]
                    if "tg_chat_id" not in cols:
                        cur.execute("ALTER TABLE customer ADD COLUMN tg_chat_id TEXT")
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS telegram_chat_profiles (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            tenant_slug VARCHAR(100),
                            workflow_id INTEGER NOT NULL,
                            chat_id VARCHAR(64) NOT NULL,
                            customer_name VARCHAR(150),
                            phone VARCHAR(30),
                            address VARCHAR(255),
                            city VARCHAR(100),
                            booking_items_json TEXT,
                            created_at DATETIME,
                            updated_at DATETIME
                        )
                        """
                    )
                    cur.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tg_chat_profile_workflow_chat "
                        "ON telegram_chat_profiles (workflow_id, chat_id)"
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS telegram_booking_sessions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id VARCHAR(64) NOT NULL,
                            workflow_id INTEGER NOT NULL,
                            tenant_slug VARCHAR(100),
                            step VARCHAR(32) NOT NULL DEFAULT 'ASK_ADDRESS',
                            address VARCHAR(500),
                            quantity INTEGER,
                            date VARCHAR(100),
                            updated_at DATETIME
                        )
                        """
                    )
                    cur.execute(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tg_booking_session_wf_user "
                        "ON telegram_booking_sessions (workflow_id, user_id)"
                    )
                    conn.commit()
                    conn.close()
                except Exception as _tenant_err:
                    print(f"Tenant migration note ({db_name}): {_tenant_err}")
    except Exception as e:
        print(f"Migration note (tenant telegram booking memory): {e}")
    
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
            if 'opening_balance' not in shipping_columns:
                db.session.execute(text("ALTER TABLE shipping_company ADD COLUMN opening_balance INTEGER DEFAULT 0"))
            if 'branch_id' not in shipping_columns:
                db.session.execute(text("ALTER TABLE shipping_company ADD COLUMN branch_id INTEGER"))
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
                        branch_id INTEGER,
                        report_number VARCHAR(50) NOT NULL UNIQUE,
                        shipping_company_id INTEGER,
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
            if 'branch_id' not in shipping_report_columns:
                db.session.execute(text("ALTER TABLE shipping_report ADD COLUMN branch_id INTEGER"))
            db.session.commit()
            # السماح بـ NULL في shipping_company_id (كشوف المندوبين بدون شركة نقل)
            sr_cols = {col['name']: col for col in inspector.get_columns('shipping_report')}
            if 'shipping_company_id' in sr_cols and not sr_cols['shipping_company_id'].get('nullable', True):
                dialect = db.engine.dialect.name
                if dialect == 'postgresql':
                    db.session.execute(text(
                        "ALTER TABLE shipping_report ALTER COLUMN shipping_company_id DROP NOT NULL"
                    ))
                elif dialect == 'sqlite':
                    with db.engine.connect() as conn:
                        conn.execute(text("""
                            CREATE TABLE shipping_report_new (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                branch_id INTEGER,
                                report_number VARCHAR(50) NOT NULL UNIQUE,
                                shipping_company_id INTEGER,
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
                        conn.execute(text("""
                            INSERT INTO shipping_report_new
                            SELECT id, branch_id, report_number, shipping_company_id, shipping_company_name,
                                   orders_data, total_amount, orders_count, notes, created_at,
                                   created_by, is_executed, order_status_selections
                            FROM shipping_report
                        """))
                        conn.execute(text("DROP TABLE shipping_report"))
                        conn.execute(text("ALTER TABLE shipping_report_new RENAME TO shipping_report"))
                        conn.commit()
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
                # SQLite لا يدعم UNIQUE في ADD COLUMN؛ استخدم عموداً عادياً ثم فهرساً لاحقاً إن لزم
                db.session.execute(text("ALTER TABLE product ADD COLUMN barcode VARCHAR(100)"))
                db.session.commit()
                print("Added barcode column to product table.")
            if 'low_stock_threshold' not in product_columns:
                db.session.execute(text("ALTER TABLE product ADD COLUMN low_stock_threshold INTEGER DEFAULT 5"))
                db.session.commit()
                print("Added low_stock_threshold column to product table.")
            for col_sql in (
                ("sku", "ALTER TABLE product ADD COLUMN sku VARCHAR(100)"),
                ("description", "ALTER TABLE product ADD COLUMN description TEXT"),
                ("image_url", "ALTER TABLE product ADD COLUMN image_url VARCHAR(512)"),
                ("meta_json", "ALTER TABLE product ADD COLUMN meta_json TEXT"),
            ):
                col_name, stmt = col_sql
                if col_name not in product_columns:
                    db.session.execute(text(stmt))
                    db.session.commit()
                    print(f"Added {col_name} column to product table.")
                    product_columns.append(col_name)
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
            if 'is_active' not in delivery_agent_columns:
                db.session.execute(text("ALTER TABLE delivery_agent ADD COLUMN is_active BOOLEAN DEFAULT TRUE"))
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
            if 'facebook_page_id' not in page_columns:
                db.session.execute(text("ALTER TABLE page ADD COLUMN facebook_page_id VARCHAR(128)"))
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

    # Migration: Add order video columns to invoice table
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        if 'invoice' in inspector.get_table_names():
            invoice_columns = [col['name'] for col in inspector.get_columns('invoice')]
            recorded_type = "TIMESTAMP" if db.engine.dialect.name == "postgresql" else "DATETIME"
            if 'order_video_path' not in invoice_columns:
                db.session.execute(text("ALTER TABLE invoice ADD COLUMN order_video_path VARCHAR(255)"))
            if 'order_video_original_name' not in invoice_columns:
                db.session.execute(text("ALTER TABLE invoice ADD COLUMN order_video_original_name VARCHAR(255)"))
            if 'order_video_thumbnail_path' not in invoice_columns:
                db.session.execute(text("ALTER TABLE invoice ADD COLUMN order_video_thumbnail_path VARCHAR(255)"))
            if 'order_video_size_mb' not in invoice_columns:
                db.session.execute(text("ALTER TABLE invoice ADD COLUMN order_video_size_mb FLOAT"))
            if 'order_video_duration_sec' not in invoice_columns:
                db.session.execute(text("ALTER TABLE invoice ADD COLUMN order_video_duration_sec FLOAT"))
            if 'order_video_recorded_at' not in invoice_columns:
                db.session.execute(text(f"ALTER TABLE invoice ADD COLUMN order_video_recorded_at {recorded_type}"))
            if 'shipping_barcodes_json' not in invoice_columns:
                db.session.execute(text("ALTER TABLE invoice ADD COLUMN shipping_barcodes_json TEXT"))
            db.session.commit()
            print("Added order video / shipping barcode columns to invoice table.")
    except Exception as e:
        db.session.rollback()
        print(f"Migration note (order video / shipping barcode columns): {e}")

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
                if 'last_active' not in columns:
                    if db.engine.dialect.name == 'postgresql':
                        conn.execute(text("ALTER TABLE employee ADD COLUMN last_active TIMESTAMP"))
                    else:
                        conn.execute(text("ALTER TABLE employee ADD COLUMN last_active DATETIME"))
                    added = True
                    print("--> Added 'last_active'")
                if 'branch_id' not in columns:
                    conn.execute(text("ALTER TABLE employee ADD COLUMN branch_id INTEGER"))
                    added = True
                    print("--> Added 'branch_id'")
                
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

    # Seed: خطة مجانية (plan_key=free) في Core — للتسجيل بدون دفع
    try:
        from flask import g
        from sqlalchemy import inspect as sa_inspect
        from models.core.subscription_plan import SubscriptionPlan
        from utils.plan_limits import PLAN_DEFINITIONS, resolve_plan_features

        inspector = sa_inspect(db.engine)
        if "subscription_plans" in inspector.get_table_names():
            old_tenant = getattr(g, "tenant", None)
            g.tenant = None
            try:
                if SubscriptionPlan.query.filter_by(plan_key="free").first() is None:
                    fp = SubscriptionPlan(
                        plan_key="free",
                        name="الخطة المجانية",
                        price_monthly=0,
                        price_yearly=0,
                        original_price_monthly=25000,
                        original_price_yearly=250000,
                        max_users=3,
                        max_orders_monthly=500,
                    )
                    fp.set_features(
                        resolve_plan_features(
                            "free", PLAN_DEFINITIONS["free"]["features"]
                        )
                    )
                    db.session.add(fp)
                    db.session.commit()
                    print("Seeded subscription_plans: free (0 IQD)")
            finally:
                g.tenant = old_tenant
    except Exception as e:
        print(f"Seed note (subscription_plans free): {e}")

    # Migration: Create Publisher tables if needed
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        tnames = inspector.get_table_names()

        if 'publisher_pages' not in tnames:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE publisher_pages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_slug VARCHAR(100),
                        page_id VARCHAR(128) NOT NULL,
                        page_name VARCHAR(255),
                        page_token TEXT NOT NULL,
                        created_at DATETIME
                    )
                """))
                conn.commit()
            print("Created publisher_pages table.")

        if 'publisher_media' not in tnames:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE publisher_media (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_slug VARCHAR(100),
                        filename VARCHAR(255) NOT NULL,
                        original_name VARCHAR(255),
                        media_type VARCHAR(20) NOT NULL,
                        size_bytes INTEGER,
                        url_path VARCHAR(512) NOT NULL,
                        created_at DATETIME
                    )
                """))
                conn.commit()
            print("Created publisher_media table.")

        if 'publisher_posts' not in tnames:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE publisher_posts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_slug VARCHAR(100),
                        text TEXT,
                        media_ids TEXT,
                        page_ids TEXT,
                        facebook_post_ids TEXT,
                        status VARCHAR(30) DEFAULT 'draft',
                        publish_type VARCHAR(20) DEFAULT 'now',
                        publish_time DATETIME,
                        visibility VARCHAR(20) DEFAULT 'public',
                        error_message TEXT,
                        created_at DATETIME
                    )
                """))
                conn.commit()
            print("Created publisher_posts table.")
        else:
            # Migration: add visibility column if missing (existing installs)
            post_columns = [col["name"] for col in inspector.get_columns("publisher_posts")]
            if "visibility" not in post_columns:
                with db.engine.connect() as conn:
                    conn.execute(
                        text(
                            "ALTER TABLE publisher_posts ADD COLUMN visibility VARCHAR(20) DEFAULT 'public'"
                        )
                    )
                    conn.commit()
                print("Added visibility column to publisher_posts.")
        if 'publisher_settings' not in tnames:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE publisher_settings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_slug VARCHAR(100),
                        fb_app_id VARCHAR(50),
                        fb_app_secret TEXT,
                        fb_user_token TEXT,
                        updated_at DATETIME
                    )
                """))
                conn.commit()
            print("Created publisher_settings table.")
    except Exception as e:
        print(f"Migration note (publisher tables): {e}")

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
        "can_see_receipts": False,
        "can_create_receipts": False,
        "can_print_receipts": False,
        "can_cancel_receipts": False,
        "can_manage_suppliers": False,
        "can_manage_customers": False,
        "can_see_accounts": False,
        "can_see_finance_workflows": False,
        "can_see_financial": False,
        "can_see_fixed_assets": False,
        "can_manage_fixed_assets": False,
        "can_see_rotating_savings": False,
        "can_manage_rotating_savings": False,
        # صلاحيات ظهور الروابط في القائمة الجانبية
        "can_use_pos": False,
        "can_use_quick_sale": False,
        "can_use_ai_workspace": False,
        "can_see_shipping": False,
        "can_see_agents": False,
        "can_see_pages": False,
        "can_see_messages": False,
        "can_manage_employees": False,
        "can_manage_agents": False,
        "can_manage_pages": False,
        "can_edit_price": False,
        "can_manage_orders": False,
        "can_pay_orders": False,
        "can_return_orders": False,
        "can_delete_orders": False,
        "can_manage_shipping": False,
        "can_manage_settings": False,
        "can_view_dashboard": False,
        "can_view_activity": False,
        "can_use_notes": False,
        "can_use_employee_desk": False,
        "has_assigned_ai_sales_page": False,
        "_": lambda x: x,
        "current_lang": "ar"
    }

    def translate(key):
        lang = session.get('language')
        if not lang and "user_id" in session:
            try:
                from routes.employees import _ensure_employee_profile_schema

                _ensure_employee_profile_schema()
                emp = db.session.get(Employee, session["user_id"])
                if emp and emp.language:
                    lang = emp.language
                    session['language'] = lang
            except: pass
        return get_string(key, lang or 'ar')

    try:
        lang_now = session.get('language', 'ar')
        print(f"DEBUG: Session language is '{lang_now}'")

        # Superadmin templates must not touch tenant Employee/RBAC queries.
        # A leftover company session (user_id+tenant_slug) can abort the SQL txn
        # and then break /superadmin/ with InFailedSqlTransaction.
        if (request.path or "").startswith("/superadmin"):
            return {**default, "_": translate, "current_lang": lang_now}
        
        if "user_id" not in session:
            return {**default, "_": translate, "current_lang": lang_now}

        tenant_slug = (session.get("tenant_slug") or "").strip()
        prev_tenant = getattr(g, "tenant", None)
        if tenant_slug:
            g.tenant = tenant_slug
        try:
            from routes.employees import _ensure_employee_profile_schema

            _ensure_employee_profile_schema()
            employee = db.session.get(Employee, session["user_id"])
        finally:
            g.tenant = prev_tenant
        if not employee:
            return {**default, "_": translate, "current_lang": lang_now}
            
        final_lang = employee.language or lang_now
        print(f"DEBUG: Employee lang: {employee.language}, Final lang: {final_lang}")
        from utils.permission_checks import employee_can

        has_assigned_ai_sales_page = False
        if tenant_slug and employee.role != "admin":
            scoped_tenant = getattr(g, "tenant", None)
            g.tenant = tenant_slug
            try:
                from modules.ai_sales.models import AISalesChannelAccount

                has_assigned_ai_sales_page = bool(
                    AISalesChannelAccount.query.filter(
                        AISalesChannelAccount.default_employee_id == employee.id,
                        AISalesChannelAccount.connection_status != "removed",
                    ).first()
                )
            except Exception:
                db.session.rollback()
            finally:
                g.tenant = scoped_tenant
        
        return {
            "current_employee": employee,
            "can_see_orders": employee_can(employee, "view_orders"),
            "can_see_reports": employee_can(employee, "view_reports"),
            "can_manage_inventory": employee_can(employee, "manage_inventory"),
            "can_see_expenses": employee_can(employee, "view_expenses"),
            "can_see_receipts": employee_can(employee, "view_receipts"),
            "can_create_receipts": employee_can(employee, "create_receipts"),
            "can_print_receipts": employee_can(employee, "print_receipts"),
            "can_cancel_receipts": employee_can(employee, "cancel_receipts"),
            "can_manage_suppliers": employee_can(employee, "manage_suppliers"),
            "can_manage_customers": employee_can(employee, "manage_customers"),
            "can_see_accounts": employee_can(employee, "view_accounts"),
            "can_see_finance_workflows": employee_can(employee, "finance.view"),
            "can_see_financial": employee_can(employee, "view_financial"),
            "can_see_fixed_assets": employee_can(employee, "view_fixed_assets"),
            "can_manage_fixed_assets": employee_can(employee, "manage_fixed_assets"),
            "can_see_rotating_savings": employee_can(employee, "view_rotating_savings"),
            "can_manage_rotating_savings": employee_can(employee, "manage_rotating_savings"),
            # ربط أعلام القائمة الجانبية بصلاحيات الـ RBAC
            "can_use_pos": employee_can(employee, "view_pos"),
            "can_use_quick_sale": employee_can(employee, "view_quick_sale"),
            "can_use_ai_workspace": employee_can(employee, "use_ai_workspace"),
            "can_see_shipping": employee_can(employee, "view_shipping"),
            "can_see_agents": employee_can(employee, "view_agents"),
            "can_see_pages": employee_can(employee, "view_pages"),
            "can_see_messages": employee_can(employee, "view_messages"),
            "can_manage_employees": employee_can(employee, "manage_employees"),
            "can_manage_agents": employee_can(employee, "manage_agents"),
            "can_manage_pages": employee_can(employee, "manage_pages"),
            "can_edit_price": employee_can(employee, "edit_price"),
            "can_manage_orders": employee_can(employee, "manage_orders"),
            "can_pay_orders": employee_can(employee, "pay_orders"),
            "can_return_orders": employee_can(employee, "return_orders"),
            "can_delete_orders": employee_can(employee, "delete_orders"),
            "can_manage_shipping": employee_can(employee, "manage_shipping"),
            "can_manage_settings": employee_can(employee, "manage_settings"),
            "can_view_dashboard": employee_can(employee, "view_dashboard"),
            "can_view_activity": employee_can(employee, "view_activity"),
            "can_use_notes": employee_can(employee, "use_notes"),
            "can_use_employee_desk": employee_can(employee, "use_employee_desk"),
            "has_assigned_ai_sales_page": has_assigned_ai_sales_page,
            "_": translate,
            "current_lang": final_lang,
        }
    except Exception as e:
        print(f"Error in context processor: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return {**default, "_": translate}

# =====================================
# Login Guard (قبل أي صفحة)
# =====================================
def _local_workspace_request() -> bool:
    """Return True only for the studio's loopback-only local workspace."""
    if (os.environ.get("FINORA_LOCAL_WORKSPACE") or "").strip().lower() not in (
        "1", "true", "yes", "on"
    ):
        return False
    remote = (request.remote_addr or "").strip().lower()
    return remote in {"127.0.0.1", "::1", "localhost"}


def _ensure_local_workspace_session() -> bool:
    """Create a local admin session without weakening production authentication."""
    if not _local_workspace_request() or request.path.startswith(("/superadmin", "/super-admin")):
        return False
    if session.get("user_id") and session.get("tenant_slug"):
        g.tenant = session.get("tenant_slug")
        session["local_workspace"] = True
        return True

    requested_slug = (os.environ.get("FINORA_LOCAL_TENANT") or "alnoor").strip().lower()
    candidates = [requested_slug] if requested_slug else []
    # Resolve from Core DB when the preferred local tenant was not provisioned.
    try:
        previous_tenant = getattr(g, "tenant", None)
        g.tenant = None
        core_rows = Tenant.query.filter_by(is_active=True).order_by(Tenant.id).all()
        g.tenant = previous_tenant
        candidates.extend(row.slug for row in core_rows if row.slug not in candidates)
    except Exception:
        db.session.rollback()

    for tenant_slug in candidates:
        if not tenant_slug:
            continue
        try:
            g.tenant = tenant_slug
            # Read only the small identity set with sqlite directly.  Some
            # older local tenant files miss newer optional columns, so an ORM
            # SELECT of the whole Employee model would fail before the normal
            # schema guards get a chance to upgrade them.
            tenant_db = os.path.join(current_app.root_path, "tenants", f"{tenant_slug}.db")
            with sqlite3.connect(tenant_db) as local_conn:
                identity = local_conn.execute(
                    "SELECT id, name, username, role, tenant_id, language "
                    "FROM employee WHERE is_active = 1 "
                    "ORDER BY CASE WHEN role = 'admin' THEN 0 ELSE 1 END, id LIMIT 1"
                ).fetchone()
            employee = identity
        except Exception:
            db.session.rollback()
            employee = None
        if not employee:
            continue

        session.clear()
        session.permanent = True
        session["local_workspace"] = True
        session["tenant_slug"] = tenant_slug
        session["user_id"] = employee[0]
        session["name"] = employee[1] or "Developer"
        session["user_name"] = employee[2] or "admin"
        session["role"] = employee[3] or "admin"
        session["tenant_id"] = employee[4]
        session["business_type"] = "general"
        session["language"] = employee[5] or "ar"
        session["plan_key"] = "enterprise"
        g.tenant = tenant_slug
        app.logger.info("Local workspace auto-login enabled for tenant=%s user=%s", tenant_slug, employee[0])
        return True
    return False


def _hr_activity_allows_path(path):
    """Keep HR tenants inside the dedicated HR workspace."""
    clean_path = str(path or "/")
    return (
        clean_path == "/hr"
        or clean_path.startswith("/hr/")
        or clean_path.startswith("/api/v1/desktop/auth/")
        or clean_path.startswith("/api/v1/desktop/snapshots")
        or clean_path.startswith("/static/")
        or clean_path == "/logout"
        or clean_path == "/account/change-password"
        or clean_path.startswith("/employees/profile/")
    )


def _clinics_activity_allows_path(path):
    """Keep Clinics tenants inside the dedicated medical workspace."""
    clean_path = str(path or "/")
    return (
        clean_path == "/clinics"
        or clean_path.startswith("/clinics/")
        or clean_path.startswith("/c/")
        or clean_path.startswith("/book/")
        or clean_path.startswith("/static/")
        or clean_path.startswith("/api/clinic/ai-tutor/")
        or clean_path == "/api/features/me"
        or clean_path == "/logout"
        or clean_path == "/account/change-password"
        or clean_path.startswith("/employees/profile/")
        or clean_path.startswith("/settings")
        or clean_path.startswith("/permissions")
        or clean_path.startswith("/employees")
    )


def _path_is_open(path: str, open_routes) -> bool:
    """Public-path test with SEGMENT boundaries. A bare ``startswith("/c")`` once exempted every path that merely
    began with «/c» (customers, cash, clinics …) from the login gate; an entry now matches itself and its
    sub-paths only, unless it is written as a prefix (ends with «/»)."""
    if path == "/":
        return True
    for entry in open_routes:
        if entry == "/":
            continue
        if entry.endswith("/"):
            if path.startswith(entry):
                return True
        elif path == entry or path.startswith(entry + "/"):
            return True
    return False


@app.before_request
def require_login():
    # Public recruitment resolves and verifies its tenant independently of staff sessions.
    if request.endpoint in ("hr_recruit_public.public_form", "hr_recruit_public.public_submit"):
        return None
    # Machine clients are authenticated by the MCP backend guard.
    if (request.path == "/mcp" or request.path.startswith("/mcp/")) and (request.headers.get("Authorization") or not session.get("user_id")):
        return None
    local_workspace = _ensure_local_workspace_session()
    # Flask يحمّل الجلسة بـ permanent=False؛ أي تعديل لاحق يحوّل الكوكي لجلسة متصفح
    if session.get("user_id") or session.get("is_superadmin") or session.get("agent_id"):
        session.permanent = True
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
    open_routes = [
        "/",
        "/pos",
        "/pos/",
        "/pos/login",
        "/static",
        "/pricing",
        "/signup",
        "/unsubscribe",
        "/privacy",
        "/terms",
        "/data-deletion",
        "/contact",
        "/landing",
        "/supermax",
        "/super-max",
        "/payment",
        "/login",
        "/payment/success",
        "/payments",
        "/payments/failed",
        "/payments/mock-gateway",
        "/payment_failed",
        "/payments/simulate",
        "/upgrade",
        "/superadmin",
        "/super-admin",
        "/robots.txt",
        "/sitemap.xml",
        "/favicon.ico",
        "/api/superadmin/landing",  # API إدارة صفحة الهبوط محمي بجلسة Super Admin داخل blueprint
        "/api/super-admin/landing",  # alias مطابق للمواصفة
        "/messages/unread-count",  # واجهة للشارة — تُرجع JSON بدون إعادة توجيه
        "/api/landing",  # محتوى صفحة الهبوط المنشور
        "/api/landing-chat",  # مساعد الذكاء الاصطناعي لصفحة الهبوط
        "/telegram",  # بوت تيليجرام: webhook و setup و test — بدون تسجيل (ليستقبل التحديثات من Telegram)
        "/delivery-agent",  # بوابة مندوب التوصيل
        "/employee-desk/login",
        "/employee-desk/logout",
        "/employee-desk/manifest.webmanifest",
        "/employee-desk/sw.js",
        "/store",
        "/shop",  # المتجر العام للزبائن — بدون تسجيل دخول
        "/book",  # حجز مواعيد العيادات العام
        "/c",  # بوابة المريض العامة للعيادة
        "/api/public/clinics",  # API عامة محدودة لبوابة المريض
        "/installment-store",  # متجر الأقساط العام — عزل المستأجر داخل الـ blueprint
        "/orders/p/o",  # تفاصيل طلب عامة (QR) — موقّعة، بدون تسجيل
        "/orders/invoice-video",  # بث فيديو الطلب للعامة — رمز موقّع
        "/webhook",  # WhatsApp Cloud API webhook verification/receive
        "/webhooks/facebook",  # Permanent Messenger webhook (Meta verify + inbound)
        "/api/v1/ai-sales/webhooks/",  # Finora Sales AI public WhatsApp callbacks
        "/ai-sales/public/media/",  # Signed AI Sales media fetched by Meta
        "/webhook-ui",  # صفحة اختبار webhook
        "/api/mobile/v1/",  # Social Commerce mobile API (OTP/JWT — own auth)
        "/api/phone/v1/",  # Finora Phone staff companion API (Bearer — own auth)
        "/api/v1/pos/",  # POS machine API (Bearer — own auth)
        "/api/v1/store",  # Store catalog API (Bearer sk_ — own auth)
        "/api/v1/finora-core/",  # FINORA CORE desktop API (Bearer — own auth, modules/finora_core/auth.py)
        "/api/v1/desktop/",  # FINORA Management Desktop sign-in/session probe (own JSON guard, modules/desktop_api)
    ]

    agent_allowed_paths = ("/delivery-agent", "/messages", "/static")

    def restore_staff_session_from_agent() -> bool:
        if not (session.get("agent_portal") and session.get("agent_id") and session.get("staff_user_id")):
            return False
        staff_keys = (
            "user_id",
            "user_name",
            "name",
            "role",
            "tenant_slug",
            "tenant_id",
            "plan_key",
            "business_type",
            "language",
            "theme",
        )
        for key in ("user_id", "user_name", "role", "tenant_slug", "agent_portal", "agent_employee_id"):
            session.pop(key, None)
        for key in staff_keys:
            staff_key = f"staff_{key}"
            if staff_key in session:
                session[key] = session.pop(staff_key)
        tenant_slug = session.get("tenant_slug")
        if tenant_slug:
            g.tenant = tenant_slug
        return True

    if session.get("agent_portal") and session.get("agent_id") and not any(
        request.path.startswith(p) for p in agent_allowed_paths
    ):
        restore_staff_session_from_agent()

    # Superadmin routes use Core DB only. A leftover company session
    # (user_id + tenant_slug) must not sync Employee / payroll schema here —
    # that can abort the SQL transaction and 500 the dashboard.
    # Auth for these paths is enforced by the superadmin blueprint.
    if (request.path or "").startswith(("/superadmin", "/super-admin")):
        g.tenant = None
        return

    def sync_staff_session_from_db():
        if "user_id" not in session:
            return None
        tenant_slug = (session.get("tenant_slug") or "").strip()
        if tenant_slug:
            g.tenant = tenant_slug
        try:
            from utils.payroll_schema import ensure_payroll_schema
            from routes.employees import _ensure_employee_profile_schema

            ensure_payroll_schema()
            _ensure_employee_profile_schema()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        try:
            employee = db.session.get(Employee, session["user_id"])
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            return None
        if not employee or not employee.is_active:
            session.clear()
            return None
        session["role"] = employee.role or "cashier"
        session["name"] = employee.name
        session["tenant_id"] = employee.tenant_id
        if employee.language:
            session["language"] = employee.language
        return employee

    current_employee_for_request = sync_staff_session_from_db()

    # نشاط الموارد البشرية مساحة مستقلة. حتى الروابط العامة أو الروابط
    # المحفوظة سابقاً لا تفتح صفحات البيع والمخزون والحسابات لهذا النشاط.
    if session.get("user_id"):
        active_business_type = (session.get("business_type") or "").strip()
        tenant_slug = (session.get("tenant_slug") or "").strip()
        if tenant_slug:
            previous_tenant = getattr(g, "tenant", None)
            try:
                g.tenant = None
                from models.core.tenant import Tenant as CoreTenant

                core_tenant = CoreTenant.query.filter_by(slug=tenant_slug).first()
                if core_tenant:
                    active_business_type = (
                        getattr(core_tenant, "business_type", None) or "general"
                    )
                    session["business_type"] = active_business_type
            except Exception:
                db.session.rollback()
            finally:
                g.tenant = previous_tenant

        if active_business_type == "hr_management" and not _hr_activity_allows_path(request.path):
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({
                    "success": False,
                    "error": "هذا النشاط مخصص لإدارة الموارد البشرية فقط",
                }), 403
            return redirect("/hr/")

        if active_business_type == "clinics" and not _clinics_activity_allows_path(request.path):
            if request.path.startswith("/api/") or request.is_json:
                return jsonify({
                    "success": False,
                    "error": "هذا النشاط مخصص لإدارة العيادات والمراكز الطبية فقط",
                }), 403
            return redirect("/clinics/")

        if active_business_type == "starter_business":
            feature = _starter_business_feature_for_path(request.path)
            if feature:
                try:
                    from models.tenant import Tenant as TenantModel
                    from utils.plan_limits import get_plan
                    from utils.tenant_feature_flags import normalize_feature_overrides

                    tenant_row = TenantModel.query.first()
                    plan_key = getattr(tenant_row, "plan_key", None) or session.get("plan_key") or "basic"
                    plan_features = get_plan(plan_key).get("features", {})
                    overrides = normalize_feature_overrides(
                        getattr(tenant_row, "feature_overrides_json", None) if tenant_row else None
                    )
                    allowed = starter_business_allows(
                        feature,
                        plan_features=plan_features,
                        feature_overrides=overrides,
                    )
                except Exception:
                    allowed = feature in STARTER_BUSINESS_DEFAULT_FEATURES
                if not allowed:
                    if request.path.startswith("/api/") or request.is_json:
                        return jsonify({"success": False, "error": "هذه الميزة غير مفعلة لهذا النشاط"}), 403
                    return redirect("/")

    def deny_current_path():
        if request.path.startswith(("/api/", "/notes/api", "/reports/api/")) or request.is_json:
            return jsonify({"success": False, "error": "غير مصرح"}), 403
        # Data clients (desktop app, the web's own XHR calls) must get a 403, not a page redirect: the desktop
        # treats a redirect as "session ended" and signed limited users (cashiers) out.
        accept = (request.headers.get("Accept") or "").lower()
        if (request.headers.get("X-Requested-With") or "").lower() == "xmlhttprequest" or (
            "application/json" in accept and "text/html" not in accept
        ):
            return jsonify({"success": False, "error": "غير مصرح"}), 403
        return redirect("/pos")

    def enforce_page_permission(employee):
        if not employee:
            return None
        path = request.path or ""
        if employee.role == "admin":
            return None
        from utils.permission_checks import employee_can

        if path.startswith(("/superadmin", "/super-admin", "/admin/", "/executive-dashboard")):
            return deny_current_path()

        rules = [
            ("/quick-sale", "view_quick_sale"),
            ("/workspace", "use_ai_workspace"),
            ("/inventory", "manage_inventory"),
            ("/maintenance", "manage_inventory"),
            ("/purchases", "manage_inventory"),
            ("/suppliers", "manage_suppliers"),
            ("/customers", "manage_customers"),
            ("/orders/ordered", ("view_orders", "view_orders_placed")),
            ("/orders/packed", ("view_orders", "view_orders_packed")),
            ("/orders/shipping", ("view_orders", "view_orders_shipped")),
            ("/orders/delivered", ("view_orders", "view_orders_delivered")),
            ("/orders/returned", ("view_orders", "view_orders_returned")),
            ("/orders/cancelled", ("view_orders", "view_orders_returned")),
            ("/orders", "view_orders"),
            ("/shipping/company-returns", "return_orders"),
            ("/shipping", "view_shipping"),
            ("/expenses", "view_expenses"),
            ("/cash", "view_accounts"),
            ("/accounts/finance", "finance.view"),
            ("/api/finance", "finance.view"),
            ("/accounts", "view_accounts"),
            ("/assets", ("view_fixed_assets", "view_accounts")),
            ("/finance/rotating-savings", ("view_rotating_savings", "view_accounts")),
            ("/finance/rotating_savings", ("view_rotating_savings", "view_accounts")),
            ("/reports", "view_reports"),
            ("/messages", "view_messages"),
            ("/pages", "view_pages"),
            ("/agents", "view_agents"),
            ("/employees", "manage_employees"),
            ("/payroll", "manage_employees"),
            ("/settings", "manage_settings"),
            ("/activity", "view_activity"),
            ("/notes", "use_notes"),
            ("/employee-desk", "use_employee_desk"),
            ("/api/employee-desk", "use_employee_desk"),
        ]
        for prefix, required in rules:
            if path.startswith((
                "/employee-desk/login",
                "/employee-desk/logout",
                "/employee-desk/manifest",
                "/employee-desk/sw",
            )):
                break
            if not path.startswith(prefix):
                continue
            if isinstance(required, tuple):
                if prefix in ("/assets", "/finance/rotating-savings", "/finance/rotating_savings"):
                    allowed = any(employee_can(employee, perm) for perm in required)
                else:
                    allowed = all(employee_can(employee, perm) for perm in required)
            else:
                allowed = employee_can(employee, required)
            if not allowed:
                return deny_current_path()
            break
        return None

    denied_by_page_permission = enforce_page_permission(current_employee_for_request)
    if denied_by_page_permission:
        return denied_by_page_permission

    # السماح للمسارات المفتوحة: "/" تطابق تامة، الباقي يبدأ بـ المسار
    if _path_is_open(request.path, open_routes):
        # لوحة التحكم "/" معفاة من require_login لكن تحتاج g.tenant للجلسات النشطة
        if "user_id" in session:
            tenant_slug = session.get("tenant_slug")
            if tenant_slug:
                g.tenant = tenant_slug
        return

    publisher_api_path = (request.path or "").startswith("/publisher/api/")

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
        # API يجب أن يعيد JSON بدل redirect HTML
        if publisher_api_path:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        # Print iframe embeds must not receive the full login page (was getting printed).
        if (request.args.get("finora_embed") or "").strip() == "1":
            return (
                "<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'>"
                "<title>انتهت الجلسة</title></head><body>"
                "<p data-finora-print-blocked='session'>"
                "انتهت الجلسة. أعد تسجيل الدخول ثم اطبع مرة أخرى."
                "</p></body></html>",
                401,
                {"Content-Type": "text/html; charset=utf-8"},
            )
        return redirect("/login")

    # جلسة بوابة المندوب: السماح بالمراسلة وبوابة المندوب فقط.
    # إذا كان المستخدم فتح بوابة المندوب من حساب موظف في نفس المتصفح، نرجع جلسة
    # الموظف الأصلية عند العودة للنظام الإداري بدلاً من إرساله لتسجيل الدخول.
    if session.get("agent_portal") and session.get("agent_id"):
        if not any(request.path.startswith(p) for p in agent_allowed_paths):
            if restore_staff_session_from_agent():
                return
            return redirect("/delivery-agent/dashboard")

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
            
            if not local_workspace and (not core_tenant or not core_tenant.is_subscription_valid()):
                # إنهاء الجلسة وإرجاعه لصفحة الخطط إذا انتهى الاشتراك
                session.clear()
                return redirect("/pricing")
            session["business_type"] = getattr(core_tenant, "business_type", None) or "general"
    except Exception as e:
        print(f"Error checking tenant subscription: {e}")
        pass

    # One authoritative branch context for every authenticated tenant page/API.
    # Individual blueprints may still call it defensively; the operation is
    # idempotent and always reuses the current request/session.
    if (
        session.get("user_id")
        and session.get("tenant_slug")
        and not (request.path or "").startswith(("/superadmin", "/super-admin"))
    ):
        try:
            from utils.branch_context import init_branch_context

            init_branch_context()
        except Exception:
            db.session.rollback()
            app.logger.exception("global branch context initialization failed")



@app.context_processor
def inject_system_settings():
    """تمرير إعدادات النظام العامة لجميع القوالب باسم system_settings."""
    # لا نستعلم عن SystemSettings في مسارات الإدارة العليا (قاعدة Core قد لا تحتوي الجدول)
    if request.path.startswith("/superadmin"):
        return {"system_settings": None}
    tenant_slug = (session.get("tenant_slug") or "").strip()
    prev_tenant = getattr(g, "tenant", None)
    if tenant_slug:
        g.tenant = tenant_slug
    try:
        settings = SystemSettings.get_settings()
    except Exception:
        db.session.rollback()
        settings = None
    finally:
        g.tenant = prev_tenant
    return {"system_settings": settings}


@app.context_processor
def inject_branch_scope_context():
    if request.path.startswith("/superadmin") or not session.get("user_id"):
        return {
            "branches": [],
            "current_branch": None,
            "current_branch_id": None,
            "view_all_branches": False,
            "can_switch_branch": False,
            "branch_scope_label": "",
        }
    try:
        from utils.branch_context import init_branch_context
        from utils.branch_scope import branch_context_payload

        if not hasattr(g, "branches"):
            init_branch_context()
        return branch_context_payload()
    except Exception:
        db.session.rollback()
        return {
            "branches": [],
            "current_branch": None,
            "current_branch_id": None,
            "view_all_branches": False,
            "can_switch_branch": False,
            "branch_scope_label": "",
        }


@app.context_processor
def inject_platform_branding():
    """شعار واسم المنصة من إعدادات السوبر أدمن (Core DB)."""
    try:
        from utils.platform_branding import get_platform_app_name, get_platform_logo_url

        return {
            "platform_logo_url": get_platform_logo_url(),
            "platform_app_name": get_platform_app_name(),
        }
    except Exception:
        return {
            "platform_logo_url": "/static/finora-logo.png",
            "platform_app_name": "Finora",
        }


@app.context_processor
def inject_business_context():
    """Expose the active company's business type to all tenant templates."""
    business_type = session.get("business_type") or "general"
    active_plan_key = session.get("plan_key") or "basic"
    feature_overrides = {}
    if request.path.startswith("/superadmin"):
        return {
            "business_type": "general",
            "is_beauty_center": False,
            "is_wholesale": False,
            "is_food_business": False,
            "is_hr_management": False,
            "is_starter_business": False,
            "is_clinics_business": False,
            "business_allows": lambda module: True,
        }
    try:
        tenant_slug = session.get("tenant_slug")
        if tenant_slug:
            old_tenant = getattr(g, "tenant", None)
            g.tenant = None
            try:
                from models.core.tenant import Tenant as CoreTenant

                core_tenant = CoreTenant.query.filter_by(slug=tenant_slug).first()
                if core_tenant:
                    business_type = getattr(core_tenant, "business_type", None) or "general"
                    session["business_type"] = business_type
            finally:
                g.tenant = old_tenant
            try:
                from extensions_tenant import get_tenant_engine
                from models.tenant import Tenant as TenantModel
                from utils.tenant_feature_flags import (
                    ensure_tenant_feature_overrides_column,
                    normalize_feature_overrides,
                )

                ensure_tenant_feature_overrides_column(get_tenant_engine(tenant_slug))
                previous_tenant = getattr(g, "tenant", None)
                g.tenant = tenant_slug
                try:
                    tenant_row = TenantModel.query.first()
                    if tenant_row and getattr(tenant_row, "plan_key", None):
                        active_plan_key = tenant_row.plan_key
                        session["plan_key"] = active_plan_key
                    feature_overrides = normalize_feature_overrides(
                        getattr(tenant_row, "feature_overrides_json", None) if tenant_row else None
                    )
                finally:
                    g.tenant = previous_tenant
            except Exception:
                feature_overrides = {}
    except Exception:
        business_type = session.get("business_type") or "general"
        feature_overrides = {}

    try:
        from utils.plan_limits import get_plan

        plan_features = get_plan(active_plan_key).get("features", {})
    except Exception:
        # عند تعذر قاعدة Core لا نغلق صفحات كانت تعمل سابقاً.
        plan_features = {}

    def business_allows(module):
        module = str(module or "")
        # الخطة هي السقف العام. إعداد الشركة يستطيع إخفاء ميزة إضافياً، لكنه
        # لا يتجاوز ميزة أوقفها المدير من الخطة نفسها.
        if module in plan_features and not bool(plan_features[module]):
            return False
        if module in feature_overrides:
            return bool(feature_overrides[module])
        if module == "shipping_company_returns":
            return False
        if module == "trade_in_sales":
            # الميزة حساسة ومعطلة افتراضياً، لكن تفعيلها صراحةً داخل الخطة
            # يجب أن ينعكس على الشركة مثل بقية الميزات.
            return bool(plan_features.get(module, False))
        if business_type == "beauty_center":
            allowed_for_beauty = {
                "dashboard",
                "executive_dashboard",
                "notes",
                "beauty",
                "beauty_appointments",
                "beauty_services",
                "beauty_sessions",
                "beauty_alerts",
                "beauty_accounts",
                "inventory",
                "inventory_products",
                "inventory_add_product",
                "inventory_audit",
                "inventory_ledger",
                "inventory_reports",
                "maintenance",
                "customers",
                "customer_blacklist",
                "customer_provinces",
                "customer_credit",
                "beauty_clients",
                "expenses",
                "cash",
                "accounts",
                "employees",
                "employee_page_warnings",
                "payroll",
                "employee_roles",
                "installments",
                "installments_dashboard",
                "installments_products",
                "installments_applications",
                "installments_contracts",
                "installments_overdue",
                "installments_reports",
                "installments_settings",
                "reports",
                "reports_daily",
                "reports_monitors",
                "reports_financial",
                "reports_sales",
                "reports_profit",
                "settings",
                "settings_system",
                "settings_invoice",
                "settings_appearance",
                "settings_branches",
                "settings_storefront",
                "settings_database_repair",
                "messages",
                "activity",
                "storefront",
            }
            return module in allowed_for_beauty
        if business_type == "wholesale":
            allowed_for_wholesale = {
                "dashboard",
                "notes",
                "wholesale",
                "wholesale_ops",
                "wholesale_sales",
                "wholesale_purchases",
                "wholesale_receipts",
                "wholesale_payments",
                "wholesale_customers",
                "wholesale_suppliers",
                "wholesale_products",
                "wholesale_warehouses",
                "wholesale_transfers",
                "wholesale_accounts",
                "wholesale_statement",
                "wholesale_expenses",
                "wholesale_reports",
                "wholesale_settings",
                "inventory",
                "inventory_products",
                "inventory_add_product",
                "inventory_audit",
                "inventory_ledger",
                "inventory_reports",
                "purchases",
                "suppliers",
                "supplier_statement",
                "stock_transfers",
                "customers",
                "customer_blacklist",
                "customer_provinces",
                "customer_credit",
                "expenses",
                "cash",
                "accounts",
                "employees",
                "employee_roles",
                "payroll",
                "installments",
                "installments_dashboard",
                "installments_products",
                "installments_applications",
                "installments_contracts",
                "installments_overdue",
                "installments_reports",
                "installments_settings",
                "reports",
                "reports_daily",
                "reports_financial",
                "reports_sales",
                "reports_profit",
                "settings",
                "settings_system",
                "settings_invoice",
                "settings_appearance",
                "settings_branches",
                "settings_database_repair",
                "permissions",
                "messages",
                "activity",
            }
            return module in allowed_for_wholesale
        if business_type == "food_wholesale_retail":
            allowed_for_food = {
                "food",
                "food_dashboard",
                "food_cashier",
                "food_orders",
                "food_products",
                "food_purchases",
                "food_inventory",
                "food_parties",
                "food_finance",
                "food_reports",
                "food_settings",
            }
            return module in allowed_for_food
        if business_type == "hr_management":
            allowed_for_hr = {
                "hr",
                "hr_dashboard",
                "hr_employees",
                "hr_attendance",
                "hr_leaves",
                "hr_payroll",
                "hr_cash",
                "hr_reports",
                "hr_settings",
            }
            return module in allowed_for_hr
        if business_type == "clinics":
            allowed_for_clinics = {
                "clinics",
                "clinics_dashboard",
                "clinics_reception",
                "clinics_appointments",
                "clinics_patients",
                "clinics_visits",
                "clinics_clinical",
                "clinics_billing",
                "clinics_inventory",
                "clinics_admin",
                "clinics_reports",
                "clinics_settings",
            }
            return module in allowed_for_clinics
        if business_type == "starter_business":
            return module in STARTER_BUSINESS_DEFAULT_FEATURES
        return True

    return {
        "business_type": business_type,
        "is_beauty_center": business_type == "beauty_center",
        "is_wholesale": business_type == "wholesale",
        "is_food_business": business_type == "food_wholesale_retail",
        "is_hr_management": business_type == "hr_management",
        "is_starter_business": business_type == "starter_business",
        "is_clinics_business": business_type == "clinics",
        "business_allows": business_allows,
        "tenant_feature_overrides": feature_overrides,
    }


@app.context_processor
def inject_provinces_context():
    if request.path.startswith("/superadmin"):
        return {}
    try:
        from utils.tenant_provinces import get_provinces_context
        return get_provinces_context()
    except Exception:
        from utils.tenant_provinces import (
            DEFAULT_GROUP_LABEL,
            DEFAULT_PRIMARY,
            DEFAULT_PROVINCES,
            FILTER_GROUP,
            FILTER_PRIMARY,
        )
        return {
            "primary_province": DEFAULT_PRIMARY,
            "provinces_group_label": DEFAULT_GROUP_LABEL,
            "tenant_provinces_list": list(DEFAULT_PROVINCES),
            "tenant_group_provinces": [n for n in DEFAULT_PROVINCES if n != DEFAULT_PRIMARY],
            "province_filter_primary": FILTER_PRIMARY,
            "province_filter_group": FILTER_GROUP,
        }


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
        # عند وجود جلسة شركة، جلب الخطة من قاعدة بيانات المستأجر.
        # ملاحظة: مسار "/" (لوحة التحكم) يُعفى في require_login قبل ضبط g.tenant،
        # لذلك نربط g.tenant مؤقتاً هنا حتى يعمل الاستعلام دائماً.
        try:
            tenant_slug = session.get("tenant_slug")
            if tenant_slug:
                prev_tenant = getattr(g, "tenant", None)
                g.tenant = tenant_slug
                try:
                    from models.tenant import Tenant as TenantModel
                    t = TenantModel.query.first()
                    if t and getattr(t, "plan_key", None):
                        plan_key = t.plan_key
                        session["plan_key"] = plan_key
                finally:
                    g.tenant = prev_tenant
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


@app.context_processor
def inject_help_context():
    """Contextual help: page-level and field-level tooltips."""
    from utils.help_registry import get_page_help, get_field_help, help_fields_json

    lang = session.get("language", "ar")
    if "user_id" in session:
        try:
            emp = db.session.get(Employee, session["user_id"])
            if emp and emp.language:
                lang = emp.language
        except Exception:
            pass

    endpoint = request.endpoint if request else None
    path = request.path if request else ""

    return {
        "page_help": get_page_help(endpoint, path, lang),
        "help_field": lambda key: get_field_help(key, lang),
        "help_fields_json": help_fields_json(lang),
    }


# =====================================
# Register Blueprints
# =====================================
app.register_blueprint(index_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(ai_bp, url_prefix="/ai")
app.register_blueprint(social_ai_bp, url_prefix="/social-ai")
app.register_blueprint(workflow_api)
try:
    from modules.finora_ai import init_finora_ai
    init_finora_ai(app)
    print("Finora AI + MCP Phase 1 loaded.")
except Exception as _finora_ai_ex:
    print(f"Finora AI + MCP load warning: {_finora_ai_ex}")

app.register_blueprint(pos_bp)
app.register_blueprint(employees_bp, url_prefix="/employees")
app.register_blueprint(payroll_bp, url_prefix="/payroll")
app.register_blueprint(hr_desktop_bp)
app.register_blueprint(hr_recruit_public_bp)
app.register_blueprint(inventory_bp, url_prefix="/inventory")
app.register_blueprint(stock_transfers_bp)
app.register_blueprint(branch_api_bp)
app.register_blueprint(delivery_fee_api_bp)
app.register_blueprint(purchases_bp, url_prefix="/purchases")
app.register_blueprint(purchase_lists_bp)
app.register_blueprint(product_dedup_bp)
app.register_blueprint(maintenance_bp)
app.register_blueprint(fixed_assets_bp)
app.register_blueprint(rotating_savings_bp)
app.register_blueprint(rotating_savings_bp_alias)
app.register_blueprint(inventory_ledger_bp, url_prefix="/inventory/ledger")
app.register_blueprint(media_library_bp)
app.register_blueprint(cash_bp, url_prefix="/cash")
app.register_blueprint(customers_bp)
app.register_blueprint(customer_credit_bp)
app.register_blueprint(orders_bp, url_prefix="/orders")
app.register_blueprint(shipping_bp, url_prefix="/shipping")
app.register_blueprint(reports_bp, url_prefix="/reports")
from modules.reports_api import init_reports_api
init_reports_api(app)
app.register_blueprint(daily_closing_bp)
app.register_blueprint(suppliers_bp, url_prefix="/suppliers")
app.register_blueprint(expenses_bp, url_prefix="/expenses")
app.register_blueprint(accounts_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(messages_bp)
app.register_blueprint(delivery_bp)
app.register_blueprint(assistant_bp)
app.register_blueprint(investments_bp)
app.register_blueprint(agents_bp)
app.register_blueprint(delivery_agent_bp)
app.register_blueprint(pages_bp)
app.register_blueprint(activity_bp, url_prefix="/activity")
app.register_blueprint(notes_bp)
app.register_blueprint(landing_bp)
from routes.permissions import permissions_bp
app.register_blueprint(permissions_bp, url_prefix="/admin/permissions")

from routes.superadmin import superadmin_bp
app.register_blueprint(superadmin_bp)

from routes.superadmin_leads import superadmin_leads_bp
app.register_blueprint(superadmin_leads_bp)

from routes.superadmin_features import superadmin_features_bp
app.register_blueprint(superadmin_features_bp)

from routes.features_api import features_api_bp
app.register_blueprint(features_api_bp)

from modules.ai_tutor.routes import ai_tutor_bp
app.register_blueprint(ai_tutor_bp)

from routes.superadmin_ai_tutor import superadmin_ai_tutor_bp
app.register_blueprint(superadmin_ai_tutor_bp)

from routes.admin import admin_bp
app.register_blueprint(admin_bp)

app.register_blueprint(invoice_store_bp)
app.register_blueprint(storefront_bp)
from modules.catalog.routes import catalog_admin_bp
app.register_blueprint(catalog_admin_bp)
from modules.pricing.routes import pricing_bp
app.register_blueprint(pricing_bp)
from modules.search.routes import search_admin_bp
app.register_blueprint(search_admin_bp)
from modules.recommendations.routes import recommendations_bp
app.register_blueprint(recommendations_bp)
from modules.store_analytics.routes import store_analytics_bp
app.register_blueprint(store_analytics_bp)
init_installments(app)
init_order_installment_lifecycle(app)

@app.route("/store")
@app.route("/store/")
def store_root_alias():
    return redirect(url_for("storefront.shop_root"))

app.register_blueprint(quick_sale_bp)
app.register_blueprint(beauty_bp)
app.register_blueprint(hr_bp)
try:
    from modules.wholesale import init_wholesale

    init_wholesale(app)
    print("Wholesale module loaded.")
except Exception as _ws_ex:
    print(f"Wholesale module load warning: {_ws_ex}")
try:
    from modules.food import init_food_workspace

    init_food_workspace(app)
    print("Food workspace loaded.")
except Exception as _food_ex:
    print(f"Food workspace load warning: {_food_ex}")
try:
    from modules.clinics import init_clinics

    init_clinics(app)
    print("Clinics workspace loaded.")
except Exception as _clinics_ex:
    print(f"Clinics workspace load warning: {_clinics_ex}")
try:
    from modules.receipts import init_receipts

    init_receipts(app)
    print("Receipts module loaded.")
except Exception as _receipts_init_err:
    print(f"Receipts module init skipped: {_receipts_init_err}")
from modules.finance import init_finance
init_finance(app)
app.register_blueprint(whatsapp_webhook_bp)
app.register_blueprint(ai_sales_bp)
app.register_blueprint(ai_sales_webhook_bp)
from modules.facebook_monitor import facebook_monitor_bp
app.register_blueprint(facebook_monitor_bp)
from modules.employee_desk import employee_desk_bp
app.register_blueprint(employee_desk_bp)
from modules.facebook_routing import facebook_routing_bp
app.register_blueprint(facebook_routing_bp)
app.register_blueprint(telegram_bp)

# ── Publisher (Facebook Publishing Platform) ──────────────────────────────
try:
    from modules.publisher import publisher_bp, init_publisher
    app.register_blueprint(publisher_bp, url_prefix="/publisher")
    init_publisher(app)
    print("Publisher module loaded.")
except Exception as _pub_ex:
    print(f"Publisher module load warning: {_pub_ex}")

# ── AI Workspace (LEON) — Phase 1 foundation ─────────────────────────────
try:
    from modules.workspace import workspace_bp, init_workspace
    app.register_blueprint(workspace_bp, url_prefix="/workspace")
    init_workspace(app)
    print("Workspace module loaded.")
except Exception as _ws_ex:
    print(f"Workspace module load warning: {_ws_ex}")

# ── Mobile Social Commerce API (Phase 1) ────────────────────────────────
try:
    from modules.mobile_app import init_mobile_app
    init_mobile_app(app)
    print("Mobile app API loaded.")
except Exception as _mobile_ex:
    print(f"Mobile app API load warning: {_mobile_ex}")

# ── Finora Phone staff companion API (Phase 1) ──────────────────────────
try:
    from modules.phone_app import init_phone_app
    init_phone_app(app)
    print("Phone app API loaded.")
except Exception as _phone_ex:
    print(f"Phone app API load warning: {_phone_ex}")

# ── POS machine API (voice Core) ──────────────────────────────────────
try:
    from modules.pos_api import init_pos_api
    init_pos_api(app)
    print("POS machine API loaded.")
except Exception as _pos_api_ex:
    print(f"POS machine API load warning: {_pos_api_ex}")
try:
    from modules.desktop_api import init_desktop_api

    init_desktop_api(app)
except Exception as _desktop_api_ex:
    print(f"Desktop management API load warning: {_desktop_api_ex}")

try:
    from modules.finora_core import init_finora_core
    init_finora_core(app)
    print("FINORA CORE API loaded.")
except Exception as _finora_core_ex:
    print(f"FINORA CORE API load warning: {_finora_core_ex}")

try:
    from modules.store_api import init_store_api
    init_store_api(app)
    print("Store catalog API loaded.")
except Exception as _store_api_ex:
    print(f"Store catalog API load warning: {_store_api_ex}")


@app.cli.command("phone-db")
@click.argument("action", type=click.Choice(["upgrade", "upgrade-all", "downgrade", "current"]))
@click.option("--tenant", default=None, help="Tenant slug (required except upgrade-all)")
@click.option("--to", "to_version", default=0, type=int, help="Target version for downgrade")
def phone_db_command(action, tenant, to_version):
    """Upgrade/downgrade Finora Phone schema on tenant DBs.

    Examples:
      flask phone-db upgrade --tenant acme
      flask phone-db upgrade-all
      flask phone-db current --tenant acme
      flask phone-db downgrade --tenant acme --to 1
    """
    import click
    from flask import g
    from modules.phone_app import migrations as phone_mig
    from extensions_tenant import is_valid_tenant_slug, get_tenant_db_path

    def _upgrade_one(slug: str) -> int:
        if not is_valid_tenant_slug(slug):
            raise click.ClickException(f"Invalid tenant slug: {slug}")
        path = get_tenant_db_path(slug)
        if not os.path.exists(path):
            raise click.ClickException(f"Tenant DB not found: {path}")
        g.tenant = slug
        return phone_mig.upgrade()

    with app.app_context():
        if action == "upgrade-all":
            tenants_dir = os.path.join(app.root_path, "tenants")
            if not os.path.isdir(tenants_dir):
                raise click.ClickException(f"Tenants dir missing: {tenants_dir}")
            count = 0
            for name in sorted(os.listdir(tenants_dir)):
                if not name.endswith(".db"):
                    continue
                slug = name[:-3]
                try:
                    v = _upgrade_one(slug)
                    click.echo(f"{slug}: upgraded to v{v}")
                    count += 1
                except Exception as exc:
                    click.echo(f"{slug}: FAILED {exc}", err=True)
            click.echo(f"Done. {count} tenants processed.")
            return

        if not tenant:
            raise click.ClickException("--tenant is required for this action")

        if not is_valid_tenant_slug(tenant):
            raise click.ClickException(f"Invalid tenant slug: {tenant}")
        path = get_tenant_db_path(tenant)
        if not os.path.exists(path):
            raise click.ClickException(f"Tenant DB not found: {path}")
        g.tenant = tenant

        if action == "upgrade":
            v = phone_mig.upgrade()
            click.echo(f"{tenant}: upgraded to v{v}")
        elif action == "downgrade":
            v = phone_mig.downgrade(to_version)
            click.echo(f"{tenant}: downgraded to v{v}")
        elif action == "current":
            v = phone_mig.get_schema_version()
            click.echo(f"{tenant}: phone schema v{v} (target {phone_mig.TARGET_VERSION})")


@app.cli.command("seed_landing_page")
def seed_landing_page_command():
    """Seed Finora Cloud landing page draft/published content."""
    with app.app_context():
        from utils.landing_content import ensure_landing_seed

        created = ensure_landing_seed()
        print("Landing page seed created." if created else "Landing page seed already exists.")

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
    """413: حد الحجم 500MB — رد JSON لطلبات API (رفع وسائط الأوتوبوستر)."""
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
    try:
        db.session.rollback()
    except Exception:
        pass
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
    # A versioned static file (``…css?v=20261017``) never changes under the same URL — a new version gets a new
    # ``v`` — so browsers keep it for a year instead of re-checking every 5 minutes (repeat visits load instantly).
    if request.endpoint == "static" and request.args.get("v") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response

from utils.activity_middleware import register_activity_middleware
register_activity_middleware(app)

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
# Scheduled Expense Posting (time-of-day)
# =====================================
def _start_expense_posting_scheduler():
    """خصم المصاريف المجدولة بساعة محددة كل دقيقة لكل المستأجرين."""
    import os
    import sys

    if os.environ.get("SERVER_SOFTWARE", "").startswith("gunicorn/") or "gunicorn" in (sys.argv[0] or ""):
        return
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
        from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]
        from routes.expenses import run_scheduled_expense_posting_for_all_tenants

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            lambda: run_scheduled_expense_posting_for_all_tenants(app),
            IntervalTrigger(minutes=1),
            id="expense_timed_posting",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
    except Exception:
        pass

_start_expense_posting_scheduler()

# =====================================
# Weekly Announcement Scheduler
# =====================================
def _start_weekly_announcement_scheduler():
  import os
  import sys

  if os.environ.get("SERVER_SOFTWARE", "").startswith("gunicorn/") or "gunicorn" in (sys.argv[0] or ""):
      return

  try:
      from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
      from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
      from models.core.global_setting import GlobalSetting
      from utils.announcement_service import run_weekly_announcement_job

      def _run_weekly():
          with app.app_context():
              try:
                  run_weekly_announcement_job()
              except Exception:
                  try:
                      app.logger.exception("weekly announcement scheduler failed")
                  except Exception:
                      pass

      def _schedule_job(scheduler):
          with app.app_context():
              day = (GlobalSetting.get_setting("WEEKLY_ANNOUNCEMENT_DAY", "mon") or "mon").lower()[:3]
              try:
                  hour = int(GlobalSetting.get_setting("WEEKLY_ANNOUNCEMENT_HOUR", "9") or 9)
              except ValueError:
                  hour = 9
              hour = max(0, min(23, hour))
              day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
              dow = day_map.get(day, 0)
              scheduler.add_job(
                  _run_weekly,
                  CronTrigger(day_of_week=dow, hour=hour, minute=0),
                  id="weekly_announcement",
                  replace_existing=True,
              )

      scheduler = BackgroundScheduler()
      _schedule_job(scheduler)
      scheduler.start()
  except Exception:
      pass

_start_weekly_announcement_scheduler()

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

# =====================================
# AI Assistant Scheduled Audits
# =====================================
def _start_ai_assistant_audit_scheduler():
    import os
    import sys

    if os.environ.get("SERVER_SOFTWARE", "").startswith("gunicorn/") or "gunicorn" in (sys.argv[0] or ""):
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
        from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]

        def _run_ai_assistant_audits():
            with app.app_context():
                try:
                    from flask import g
                    from models.core.tenant import Tenant as CoreTenant
                    from utils.ai_assistant_service import ensure_ai_assistant_schema, run_due_scheduled_audits

                    tenants = CoreTenant.query.filter_by(is_active=True).all()
                    if not tenants:
                        ensure_ai_assistant_schema()
                        run_due_scheduled_audits()
                        return
                    for tenant in tenants:
                        tenant_slug = tenant.slug
                        g.tenant = tenant_slug
                        try:
                            ensure_ai_assistant_schema()
                            run_due_scheduled_audits()
                        except Exception:
                            db.session.rollback()
                            try:
                                app.logger.exception("AI assistant audit failed for tenant %s", tenant_slug)
                            except Exception:
                                pass
                        finally:
                            g.tenant = None
                except Exception:
                    try:
                        app.logger.exception("AI assistant audit scheduler failed")
                    except Exception:
                        pass

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _run_ai_assistant_audits,
            IntervalTrigger(minutes=1),
            id="ai_assistant_audits",
            replace_existing=True,
        )
        scheduler.start()
    except Exception:
        pass


_start_ai_assistant_audit_scheduler()

# =====================================
# Weak Employee Auto Message Scheduler
# =====================================
def _start_weak_employee_message_scheduler():
    import os
    import sys

    if os.environ.get("SERVER_SOFTWARE", "").startswith("gunicorn/") or "gunicorn" in (sys.argv[0] or ""):
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
        from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]

        def _run_weak_employee_messages():
            with app.app_context():
                try:
                    from flask import g
                    from models.core.tenant import Tenant as CoreTenant
                    from utils.weak_employee_messaging import send_weak_employee_messages

                    old_tenant = getattr(g, "tenant", None)
                    g.tenant = None
                    try:
                        tenants = CoreTenant.query.filter_by(is_active=True).all()
                    except Exception:
                        tenants = []
                    finally:
                        g.tenant = old_tenant

                    for tenant in tenants:
                        tenant_slug = getattr(tenant, "slug", None)
                        if not tenant_slug:
                            continue
                        g.tenant = tenant_slug
                        try:
                            send_weak_employee_messages()
                        except Exception:
                            db.session.rollback()
                            try:
                                app.logger.exception("weak employee message scheduler failed for tenant %s", tenant_slug)
                            except Exception:
                                pass
                        finally:
                            g.tenant = None
                except Exception:
                    try:
                        app.logger.exception("weak employee message scheduler failed")
                    except Exception:
                        pass

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _run_weak_employee_messages,
            IntervalTrigger(hours=1),
            id="weak_employee_messages",
            replace_existing=True,
        )
        scheduler.start()
    except Exception:
        pass


_start_weak_employee_message_scheduler()

# =====================================
# Financial / Operational Watchdog Scheduler
# =====================================
def _start_watchdog_persist_scheduler():
    import os
    import sys

    if os.environ.get("SERVER_SOFTWARE", "").startswith("gunicorn/") or "gunicorn" in (sys.argv[0] or ""):
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
        from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]

        def _run_watchdog_persist():
            with app.app_context():
                try:
                    from flask import g
                    from models.core.tenant import Tenant as CoreTenant
                    from utils.financial_watchdog import persist_watchdog_alerts

                    old_tenant = getattr(g, "tenant", None)
                    g.tenant = None
                    try:
                        tenants = CoreTenant.query.filter_by(is_active=True).all()
                    except Exception:
                        tenants = []
                    finally:
                        g.tenant = old_tenant

                    for tenant in tenants:
                        tenant_slug = getattr(tenant, "slug", None)
                        if not tenant_slug:
                            continue
                        g.tenant = tenant_slug
                        try:
                            persist_watchdog_alerts()
                        except Exception:
                            db.session.rollback()
                            try:
                                app.logger.exception("watchdog persist scheduler failed for tenant %s", tenant_slug)
                            except Exception:
                                pass
                        finally:
                            g.tenant = None
                except Exception:
                    try:
                        app.logger.exception("watchdog persist scheduler failed")
                    except Exception:
                        pass

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _run_watchdog_persist,
            IntervalTrigger(hours=6),
            id="watchdog_persist_alerts",
            replace_existing=True,
        )
        scheduler.start()
    except Exception:
        pass


_start_watchdog_persist_scheduler()

# =====================================
# Leads Discovery Scheduler
# =====================================
def _start_leads_discovery_scheduler():
    """Run one daily public-map discovery pass for Super Admin leads."""
    import os

    if os.environ.get("LEADS_DISCOVERY_SCHEDULER_ENABLED", "1") in {"0", "false", "False"}:
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
        from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
        from services.leads_crm.discovery_service import acquire_scheduler_lock, run_scheduled_lead_discovery

        if not acquire_scheduler_lock():
            try:
                app.logger.info("Leads discovery scheduler lock not acquired")
            except Exception:
                pass
            return

        def _run_daily_discovery():
            with app.app_context():
                try:
                    limit = int(os.environ.get("LEADS_DISCOVERY_DAILY_LIMIT", "100") or "100")
                except ValueError:
                    limit = 100
                try:
                    run_scheduled_lead_discovery(limit=max(1, min(limit, 100)))
                except Exception:
                    db.session.rollback()
                    try:
                        app.logger.exception("leads discovery scheduler failed")
                    except Exception:
                        pass

        try:
            hour = int(os.environ.get("LEADS_DISCOVERY_HOUR", "5") or "5")
        except ValueError:
            hour = 5
        hour = max(0, min(hour, 23))

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _run_daily_discovery,
            CronTrigger(hour=hour, minute=15),
            id="leads_daily_discovery",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
    except Exception:
        pass


_start_leads_discovery_scheduler()


def _start_order_installment_lifecycle_scheduler():
    """Auto-settle due installment-order lifecycles every 5 minutes."""
    import os

    if os.environ.get("ORDER_INSTALLMENT_SCHEDULER_ENABLED", "1") in {"0", "false", "False"}:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore[import-untyped]
        from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]

        def _run_order_installment_auto_settle():
            with app.app_context():
                try:
                    from flask import g
                    from models.core.tenant import Tenant as CoreTenant
                    from modules.order_installment_lifecycle.service import process_due_lifecycles

                    old_tenant = getattr(g, "tenant", None)
                    g.tenant = None
                    try:
                        tenants = CoreTenant.query.filter_by(is_active=True).all()
                    except Exception:
                        tenants = []
                    finally:
                        g.tenant = old_tenant

                    for tenant in tenants:
                        tenant_slug = getattr(tenant, "slug", None)
                        if not tenant_slug:
                            continue
                        g.tenant = tenant_slug
                        try:
                            process_due_lifecycles(limit=100)
                        except Exception:
                            db.session.rollback()
                            try:
                                app.logger.exception(
                                    "order installment auto-settle failed for tenant %s",
                                    tenant_slug,
                                )
                            except Exception:
                                pass
                        finally:
                            g.tenant = None
                except Exception:
                    try:
                        app.logger.exception("order installment auto-settle scheduler failed")
                    except Exception:
                        pass

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _run_order_installment_auto_settle,
            IntervalTrigger(minutes=5),
            id="order_installment_auto_settle",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
    except Exception:
        pass


_start_order_installment_lifecycle_scheduler()

# Favicon for browser tabs (/favicon.ico)
@app.route("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "favicon.png", mimetype="image/png")


@app.route("/robots.txt")
def robots_txt():
    """Public robots.txt — must be plain text (not redirected to /login)."""
    from flask import Response

    body = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "Allow: /pricing",
            "Allow: /signup",
            "Allow: /login",
            "Allow: /landing",
            "Allow: /privacy",
            "Allow: /terms",
            "Allow: /data-deletion",
            "Allow: /supermax",
            "Allow: /store",
            "Allow: /shop",
            "Disallow: /api/",
            "Disallow: /superadmin",
            "Disallow: /super-admin",
            "Disallow: /employees",
            "Disallow: /settings",
            "Disallow: /messages",
            "Disallow: /pos/",
            "Disallow: /delivery-agent",
            "Disallow: /webhook",
            # store pages that are per-visitor or endless filter combinations (each store has its own sitemap.xml)
            "Disallow: /shop/*/api/",
            "Disallow: /shop/*/cart",
            "Disallow: /shop/*/checkout",
            "Disallow: /shop/*/account",
            "Disallow: /shop/*/compare",
            "Disallow: /shop/*/personalization",
            "",
            "Sitemap: https://www.finora.company/sitemap.xml",
            "",
        ]
    )
    resp = Response(body, mimetype="text/plain; charset=utf-8")
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/sitemap.xml")
def sitemap_xml():
    """Minimal public sitemap for marketing pages."""
    from flask import Response
    from datetime import date

    today = date.today().isoformat()
    urls = [
        ("https://www.finora.company/", "1.0", "daily"),
        ("https://www.finora.company/pricing", "0.9", "weekly"),
        ("https://www.finora.company/signup", "0.9", "weekly"),
        ("https://www.finora.company/login", "0.6", "monthly"),
        ("https://www.finora.company/privacy", "0.4", "yearly"),
        ("https://www.finora.company/terms", "0.4", "yearly"),
        ("https://www.finora.company/data-deletion", "0.3", "yearly"),
        ("https://www.finora.company/landing", "0.7", "weekly"),
        ("https://www.finora.company/supermax", "0.6", "monthly"),
    ]
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, priority, changefreq in urls:
        parts.extend(
            [
                "  <url>",
                f"    <loc>{loc}</loc>",
                f"    <lastmod>{today}</lastmod>",
                f"    <changefreq>{changefreq}</changefreq>",
                f"    <priority>{priority}</priority>",
                "  </url>",
            ]
        )
    parts.append("</urlset>")
    resp = Response("\n".join(parts) + "\n", mimetype="application/xml; charset=utf-8")
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


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
