import os
import re
import sqlite3
import threading
from flask import g, current_app
from sqlalchemy import create_engine, event
from extensions import db

# In-memory cache for SQLite engines to avoid recreating them on every request
_tenant_engines = {}
_tenant_engines_lock = threading.RLock()
_TENANT_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def is_valid_tenant_slug(tenant_slug: str) -> bool:
    return bool(_TENANT_SLUG_RE.fullmatch(str(tenant_slug or "").strip().lower()))

def get_tenant_db_path(tenant_slug):
    """Get the absolute path for the tenant's SQLite database."""
    tenant_slug = str(tenant_slug or "").strip().lower()
    if not is_valid_tenant_slug(tenant_slug):
        raise ValueError("Invalid tenant slug")
    # current_app.root_path is the directory containing app.py
    tenants_dir = os.path.join(current_app.root_path, "tenants")
    if not os.path.exists(tenants_dir):
        os.makedirs(tenants_dir)
    return os.path.join(tenants_dir, f"{tenant_slug}.db")

def get_tenant_engine(tenant_slug):
    """Get or create an SQLAlchemy engine for the specific tenant."""
    tenant_slug = str(tenant_slug or "").strip().lower()
    if not is_valid_tenant_slug(tenant_slug):
        raise ValueError("Invalid tenant slug")
    if tenant_slug in _tenant_engines:
        return _tenant_engines[tenant_slug]

    with _tenant_engines_lock:
        if tenant_slug in _tenant_engines:
            return _tenant_engines[tenant_slug]
        db_path = get_tenant_db_path(tenant_slug)
        engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"timeout": 5, "check_same_thread": False},
            pool_size=max(2, int(os.environ.get("TENANT_DB_POOL_SIZE", "5"))),
            max_overflow=max(0, int(os.environ.get("TENANT_DB_MAX_OVERFLOW", "10"))),
            pool_timeout=max(1, int(os.environ.get("TENANT_DB_POOL_TIMEOUT", "5"))),
            pool_pre_ping=True,
        )

        @event.listens_for(engine, "connect")
        def _configure_sqlite_connection(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.execute("PRAGMA foreign_keys=ON")
                # Some legacy tenant files are intentionally read-only. WAL is
                # an optimization for writable tenants, not a reason to reject
                # an otherwise readable connection.
                try:
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                    cursor.execute("PRAGMA wal_autocheckpoint=1000")
                except sqlite3.OperationalError:
                    pass
            finally:
                cursor.close()

        _tenant_engines[tenant_slug] = engine
        
    return _tenant_engines[tenant_slug]

def clear_tenant_engine(tenant_slug):
    """Remove a tenant engine from the cache and dispose it."""
    with _tenant_engines_lock:
        engine = _tenant_engines.pop(tenant_slug, None)
    if engine is not None:
        engine.dispose()

def init_tenant_db(tenant_slug):
    """
    Initialize the database schema for a new tenant.
    This creates tables for all models inheriting from db.Model.
    Also initializes default roles and permissions.
    """
    engine = get_tenant_engine(tenant_slug)
    db.Model.metadata.create_all(engine)
    
    # Initialize default roles and permissions for this tenant
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    try:
        from models.role import Permission, Role
        from datetime import datetime
        
        default_perms = [
            ('view_dashboard', 'لوحة التحكم الرئيسية'),
            ('view_orders', 'رؤية الطلبات'),
            ('view_orders_placed', 'رؤية طلبات تم الطلب'),
            ('view_orders_packed', 'رؤية طلبات معباة'),
            ('view_orders_delivered', 'رؤية الطلبات الواصلة'),
            ('view_orders_returned', 'رؤية المرتجعات'),
            ('view_orders_shipped', 'رؤية المشحونة'),
            ('manage_orders', 'إدارة الطلبات'),
            ('edit_price', 'تعديل السعر'),
            ('view_reports', 'رؤية التقارير'),
            ('manage_inventory', 'إدارة المخزون'),
            ('view_expenses', 'رؤية المصاريف'),
            ('manage_suppliers', 'إدارة الموردين'),
            ('manage_customers', 'إدارة الزبائن'),
            ('view_accounts', 'رؤية الحسابات'),
            ('view_financial', 'رؤية التقرير المالي'),
            ('view_pos', 'استخدام نقطة البيع'),
            ('view_my_orders', 'عرض الموظف لطلباته فقط من نقطة البيع'),
            ('view_shipping', 'رؤية شركات الشحن'),
            ('manage_shipping', 'إدارة شركات الشحن'),
            ('view_agents', 'رؤية مندوبي التوصيل'),
            ('view_pages', 'رؤية / إدارة الصفحات'),
            ('view_messages', 'رؤية واجهة المراسلة'),
            ('view_quick_sale', 'استخدام البيع السريع'),
            ('use_ai_workspace', 'استخدام مساحة LEON'),
            ('use_ai_sales', 'استخدام صندوق Finora Sales AI'),
            ('manage_ai_sales', 'إدارة قنوات وإعدادات Finora Sales AI'),
            ('mobile_app.manage_videos', 'إدارة فيديوهات تطبيق الهاتف'),
            ('mobile_app.manage_comments', 'إدارة تعليقات تطبيق الهاتف'),
            ('mobile_app.manage_design', 'إدارة هوية تطبيق الهاتف'),
            ('mobile_app.view_analytics', 'عرض تحليلات تطبيق الهاتف'),
            ('mobile_app.manage_settings', 'إعدادات تطبيق الهاتف'),
            ('mobile_app.manage_rewards', 'إدارة نقاط ومكافآت التطبيق'),
            ('mobile_app.adjust_points', 'تعديل نقاط مستخدمي التطبيق'),
            ('mobile_app.manage_coupons', 'إدارة كوبونات التطبيق'),
            ('mobile_app.send_notifications', 'إرسال إشعارات تطبيق الهاتف'),
            ('mobile_app.manage_ai', 'إدارة Finora AI للتطبيق'),
            ('manage_employees', 'إدارة الموظفين'),
            ('manage_agents', 'إدارة المندوبين'),
            ('manage_pages', 'إدارة البيجات'),
            ('manage_settings', 'إعدادات النظام'),
            ('manage_branches', 'إدارة الفروع'),
            ('manage_transfers', 'نقل المخزون بين الفروع'),
            ('view_all_branches', 'عرض كل الفروع'),
        ]

        for name, desc in default_perms:
            if not session.query(Permission).filter_by(name=name).first():
                session.add(Permission(name=name, description=desc, created_at=datetime.utcnow()))
        
        if not session.query(Role).filter_by(name='admin').first():
            admin_role = Role(name='admin', description='مدير النظام', created_at=datetime.utcnow())
            session.add(admin_role)
            
        if not session.query(Role).filter_by(name='cashier').first():
            cashier_role = Role(name='cashier', description='كاشير', created_at=datetime.utcnow())
            perms = session.query(Permission).filter(Permission.name.in_([
                'view_dashboard', 'view_orders', 'manage_orders', 'manage_customers',
                'view_orders_placed', 'view_orders_delivered', 'view_orders_returned',
                'view_orders_packed', 'view_orders_shipped', 'view_pos', 'view_my_orders', 'view_messages',
            ])).all()
            cashier_role.permissions.extend(perms)
            session.add(cashier_role)
            
        session.commit()

        try:
            from models.treasury_account import TreasuryAccount

            if not session.query(TreasuryAccount).filter_by(account_type="cash", is_default=True).first():
                session.add(
                    TreasuryAccount(
                        name="الصندوق",
                        account_type="cash",
                        is_default=True,
                        is_active=True,
                    )
                )
                session.commit()
        except Exception as treasury_err:
            session.rollback()
            print(f"Treasury init note ({tenant_slug}): {treasury_err}")

        try:
            from models.system_settings import SystemSettings
            from utils.dashboard_ui_defaults import get_default_dashboard_ui_flags

            if not session.query(SystemSettings).first():
                settings = SystemSettings()
                settings.set_ui_flags(get_default_dashboard_ui_flags())
                session.add(settings)
                session.commit()
        except Exception as settings_err:
            session.rollback()
            print(f"SystemSettings init note ({tenant_slug}): {settings_err}")
    except Exception as e:
        session.rollback()
        print(f"Error initializing tenant defaults {tenant_slug}: {e}")
    finally:
        session.close()
