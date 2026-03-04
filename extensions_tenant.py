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
        
        # الصلاحيات الافتراضية لكل شركة جديدة
        # ملاحظة: إذا أُضيفت صلاحية جديدة هنا فسيتم إنشاؤها فقط إذا لم تكن موجودة مسبقاً.
        default_perms = [
            ('view_orders', 'رؤية الطلبات'),
            ('edit_price', 'تعديل السعر'),
            ('view_reports', 'رؤية التقارير'),
            ('manage_inventory', 'إدارة المخزون'),
            ('view_expenses', 'رؤية المصاريف'),
            ('manage_suppliers', 'إدارة الموردين'),
            ('manage_customers', 'إدارة الزبائن'),
            ('view_accounts', 'رؤية الحسابات'),
            ('view_financial', 'رؤية البيانات المالية'),
            # صلاحيات للروابط في القائمة الجانبية حتى يمكن إخفاؤها من الأدوار
            ('view_pos', 'استخدام نقطة البيع'),
            ('view_shipping', 'رؤية / استخدام الشحن'),
            ('view_agents', 'رؤية مندوبي التوصيل'),
            ('view_pages', 'رؤية / إدارة الصفحات'),
            ('view_messages', 'رؤية واجهة المراسلة'),
        ]
        
        # Add permissions
        for name, desc in default_perms:
            if not session.query(Permission).filter_by(name=name).first():
                session.add(Permission(name=name, description=desc, created_at=datetime.utcnow()))
        
        # Add roles
        if not session.query(Role).filter_by(name='admin').first():
            admin_role = Role(name='admin', description='مدير النظام', created_at=datetime.utcnow())
            session.add(admin_role)
            
        if not session.query(Role).filter_by(name='cashier').first():
            cashier_role = Role(name='cashier', description='كاشير', created_at=datetime.utcnow())
            # Add some default permissions for cashier
            perms = session.query(Permission).filter(Permission.name.in_(['view_orders', 'manage_customers'])).all()
            cashier_role.permissions.extend(perms)
            session.add(cashier_role)
            
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Error initializing tenant defaults {tenant_slug}: {e}")
    finally:
        session.close()
