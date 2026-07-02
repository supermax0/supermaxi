import os
from flask import g, current_app
from sqlalchemy import create_engine
from extensions import db

# In-memory cache for SQLite engines to avoid recreating them on every request
_tenant_engines = {}

def get_tenant_db_path(tenant_slug):
    """Get the absolute path for the tenant's SQLite database."""
    # current_app.root_path is the directory containing app.py
    tenants_dir = os.path.join(current_app.root_path, "tenants")
    if not os.path.exists(tenants_dir):
        os.makedirs(tenants_dir)
    return os.path.join(tenants_dir, f"{tenant_slug}.db")

def get_tenant_engine(tenant_slug):
    """Get or create an SQLAlchemy engine for the specific tenant."""
    if tenant_slug not in _tenant_engines:
        db_path = get_tenant_db_path(tenant_slug)
        # Create engine
        engine = create_engine(f"sqlite:///{db_path}")
        _tenant_engines[tenant_slug] = engine
        
    return _tenant_engines[tenant_slug]

def clear_tenant_engine(tenant_slug):
    """Remove a tenant engine from the cache and dispose it."""
    if tenant_slug in _tenant_engines:
        engine = _tenant_engines.pop(tenant_slug)
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
            ('view_shipping', 'رؤية شركات الشحن'),
            ('manage_shipping', 'إدارة شركات الشحن'),
            ('view_agents', 'رؤية مندوبي التوصيل'),
            ('view_pages', 'رؤية / إدارة الصفحات'),
            ('view_messages', 'رؤية واجهة المراسلة'),
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
                'view_orders_shipped', 'view_pos',
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
