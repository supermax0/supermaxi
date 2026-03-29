from contextlib import contextmanager

from flask import Blueprint, render_template, request, jsonify, send_from_directory, session, g
from extensions import db
from models.invoice_settings import InvoiceSettings
from models.system_settings import SystemSettings
from models.invoice_template import InvoiceTemplate, TenantTemplateSettings, TenantTemplatePurchase
from models.user import User
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
import os
import json
from datetime import datetime
from types import SimpleNamespace

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

# Allowed extensions for logo upload
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'}
UPLOAD_FOLDER = 'static/uploads/logos'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _template_owner_uid():
    slug = (session.get("tenant_slug") or "").strip().lower()
    if slug:
        prev = getattr(g, "tenant", None)
        g.tenant = None
        try:
            from models.core.tenant import Tenant as CoreTenant
            tenant = CoreTenant.query.filter(db.func.lower(CoreTenant.slug) == slug).first()
            if tenant:
                return tenant.id
        except Exception:
            pass
        finally:
            g.tenant = prev
    return session.get("tenant_id") or session.get("user_id")


def _template_owner_lookup_ids(primary_uid):
    ids = []
    legacy_uid = session.get("tenant_id") or session.get("user_id")
    for uid in (primary_uid, legacy_uid):
        if uid and uid not in ids:
            ids.append(uid)
    return ids


@contextmanager
def _core_db():
    prev = getattr(g, "tenant", None)
    g.tenant = None
    try:
        yield
    finally:
        g.tenant = prev


def _ensure_invoice_owner_user(owner_id):
    if not owner_id:
        return None
    existing = db.session.get(User, owner_id)
    if existing:
        return owner_id

    placeholder = User(
        id=owner_id,
        username=f"invoice_owner_{owner_id}",
        email=f"invoice_owner_{owner_id}@local.invalid",
        password_hash=generate_password_hash(f"invoice-owner-{owner_id}"),
        full_name=session.get("name") or f"Invoice Owner {owner_id}",
        is_active=True,
        is_admin=(session.get("role") == "admin"),
    )
    db.session.add(placeholder)
    db.session.flush()
    return owner_id

@settings_bp.route("/")
def settings():
    """صفحة الإعدادات الرئيسية"""
    from models.invoice import Invoice
    invoice_settings = InvoiceSettings.get_settings()
    # Get first order for preview link
    first_order = Invoice.query.order_by(Invoice.id.desc()).first()
    return render_template("settings.html", invoice_settings=invoice_settings, first_order=first_order)

@settings_bp.route("/system")
def system_settings():
    """صفحة إعدادات النظام"""
    from models.employee import Employee
    employees = Employee.query.order_by(Employee.created_at.desc()).all()
    return render_template("system_settings.html", employees=employees)

@settings_bp.route("/system/update-role", methods=["POST"])
def update_employee_role():
    """تحديث صلاحية موظف"""
    try:
        from models.employee import Employee
        data = request.get_json()
        employee_id = data.get("employee_id")
        new_role = data.get("role")
        
        if not employee_id or not new_role:
            return jsonify({"success": False, "error": "بيانات ناقصة"}), 400
        
        employee = Employee.query.get(employee_id)
        if not employee:
            return jsonify({"success": False, "error": "الموظف غير موجود"}), 404
        
        # التحقق من أن الدور صحيح
        if new_role not in ["admin", "cashier"]:
            return jsonify({"success": False, "error": "دور غير صحيح"}), 400
        
        employee.role = new_role
        db.session.commit()
        
        return jsonify({"success": True, "message": "تم تحديث الصلاحية بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400

@settings_bp.route("/system/update-status", methods=["POST"])
def update_employee_status():
    """تحديث حالة موظف (نشط/غير نشط)"""
    try:
        from models.employee import Employee
        data = request.get_json()
        employee_id = data.get("employee_id")
        is_active = data.get("is_active")
        
        if employee_id is None:
            return jsonify({"success": False, "error": "بيانات ناقصة"}), 400
        
        employee = Employee.query.get(employee_id)
        if not employee:
            return jsonify({"success": False, "error": "الموظف غير موجود"}), 404
        
        employee.is_active = bool(is_active)
        db.session.commit()
        
        return jsonify({"success": True, "message": "تم تحديث الحالة بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400

@settings_bp.route("/system/update-password", methods=["POST"])
def update_employee_password():
    """تحديث كلمة مرور موظف"""
    try:
        from models.employee import Employee
        data = request.get_json()
        employee_id = data.get("employee_id")
        new_password = data.get("password")
        
        if not employee_id or not new_password:
            return jsonify({"success": False, "error": "بيانات ناقصة"}), 400
        
        employee = Employee.query.get(employee_id)
        if not employee:
            return jsonify({"success": False, "error": "الموظف غير موجود"}), 404
        
        employee.password = new_password  # في المستقبل يمكن عمل hash
        db.session.commit()
        
        return jsonify({"success": True, "message": "تم تحديث كلمة المرور بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400

@settings_bp.route("/system/update-permissions", methods=["POST"])
def update_employee_permissions():
    """تحديث صلاحيات موظف"""
    try:
        from models.employee import Employee
        data = request.get_json()
        employee_id = data.get("employee_id")
        
        if not employee_id:
            return jsonify({"success": False, "error": "بيانات ناقصة"}), 400
        
        employee = Employee.query.get(employee_id)
        if not employee:
            return jsonify({"success": False, "error": "الموظف غير موجود"}), 404
        
        # تحديث الصلاحيات
        permissions = [
            'can_see_orders',
            'can_see_orders_placed',
            'can_see_orders_delivered',
            'can_see_orders_returned',
            'can_see_orders_shipped',
            'can_edit_price',
            'can_see_reports',
            'can_manage_inventory',
            'can_see_expenses',
            'can_manage_suppliers',
            'can_see_accounts',
            'can_see_financial'
        ]
        
        for perm in permissions:
            if perm in data:
                setattr(employee, perm, bool(data[perm]))
        
        db.session.commit()
        
        return jsonify({"success": True, "message": "تم تحديث الصلاحيات بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400

@settings_bp.route("/system/get-permissions/<int:employee_id>")
def get_employee_permissions(employee_id):
    """جلب صلاحيات موظف"""
    try:
        from models.employee import Employee
        employee = Employee.query.get(employee_id)
        if not employee:
            return jsonify({"success": False, "error": "الموظف غير موجود"}), 404
        
        permissions = {
            'can_see_orders': getattr(employee, 'can_see_orders', True),
            'can_see_orders_placed': getattr(employee, 'can_see_orders_placed', True),
            'can_see_orders_delivered': getattr(employee, 'can_see_orders_delivered', True),
            'can_see_orders_returned': getattr(employee, 'can_see_orders_returned', True),
            'can_see_orders_shipped': getattr(employee, 'can_see_orders_shipped', True),
            'can_edit_price': getattr(employee, 'can_edit_price', False),
            'can_see_reports': getattr(employee, 'can_see_reports', True),
            'can_manage_inventory': getattr(employee, 'can_manage_inventory', False),
            'can_see_expenses': getattr(employee, 'can_see_expenses', False),
            'can_manage_suppliers': getattr(employee, 'can_manage_suppliers', False),
            'can_see_accounts': getattr(employee, 'can_see_accounts', False),
            'can_see_financial': getattr(employee, 'can_see_financial', False)
        }
        
        return jsonify({"success": True, "permissions": permissions})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@settings_bp.route("/invoice")
def invoice_settings():
    """صفحة إعدادات الفاتورة"""
    db.session.rollback()
    owner_uid = _template_owner_uid()
    owner_lookup_ids = _template_owner_lookup_ids(owner_uid)
    with _core_db():
        templates = InvoiceTemplate.query.order_by(InvoiceTemplate.price.asc(), InvoiceTemplate.id.asc()).all()
        tset = TenantTemplateSettings.query.filter_by(tenant_id=owner_uid).first() if owner_uid else None
        if not tset and len(owner_lookup_ids) > 1:
            tset = TenantTemplateSettings.query.filter(TenantTemplateSettings.tenant_id.in_(owner_lookup_ids)).first()
        purchases = TenantTemplatePurchase.query.filter(TenantTemplatePurchase.tenant_id.in_(owner_lookup_ids)).all() if owner_lookup_ids else []
        purchased_ids = {}
        status_rank = {"approved": 3, "pending": 2, "rejected": 1}
        for p in purchases:
            old = purchased_ids.get(p.template_id)
            if not old or status_rank.get(p.status, 0) > status_rank.get(old, 0):
                purchased_ids[p.template_id] = p.status
        template_style = {
            "primary_color": (tset.primary_color if tset else "#2563eb") or "#2563eb",
            "secondary_color": (tset.secondary_color if tset else "#4a5568") or "#4a5568",
            "custom_css": (tset.custom_css if tset else "") or "",
        }
    settings = InvoiceSettings.get_settings()
    return render_template(
        "invoice_settings.html",
        settings=settings,
        templates=templates,
        active_template_id=(tset.active_template_id if tset else None),
        purchased_ids=purchased_ids,
        template_style=template_style,
    )


@settings_bp.route("/appearance")
def appearance_settings():
    """صفحة إعدادات الواجهة (الثيم، الخط، المساعد)"""
    settings = SystemSettings.get_settings()
    return render_template("settings_appearance.html", settings=settings)


@settings_bp.route("/appearance/update", methods=["POST"])
def update_appearance_settings():
    """تحديث إعدادات الواجهة العامة"""
    try:
        settings = SystemSettings.get_settings()
        data = request.get_json(force=True) or {}

        # Basic scalar fields
        if "default_theme" in data:
            if data["default_theme"] in ["system", "light", "dark"]:
                settings.default_theme = data["default_theme"]

        if "font_scale" in data:
            if data["font_scale"] in ["sm", "md", "lg"]:
                settings.font_scale = data["font_scale"]

        if "default_currency" in data:
            settings.default_currency = (data["default_currency"] or "").strip() or "د.ع"

        if "ai_enabled" in data:
            settings.ai_enabled = bool(data["ai_enabled"])

        # UI flags as JSON (extensible for future widgets)
        ui_flags = settings.get_ui_flags()
        ui_updates = data.get("ui_flags") or {}
        if isinstance(ui_updates, dict):
            ui_flags.update(ui_updates)
            settings.set_ui_flags(ui_flags)

        settings.updated_at = datetime.utcnow()
        db.session.commit()

        return jsonify({"success": True, "message": "تم حفظ إعدادات الواجهة بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400

@settings_bp.route("/invoice/update", methods=["POST"])
def update_invoice_settings():
    """تحديث إعدادات الفاتورة"""
    try:
        db.session.rollback()
        settings = InvoiceSettings.get_settings()
        data = request.form
        
        # Company Info
        if 'company_name' in data:
            settings.company_name = data.get('company_name', '')
        if 'company_subtitle' in data:
            settings.company_subtitle = data.get('company_subtitle', '')
        if 'company_address' in data:
            settings.company_address = data.get('company_address', '')
        if 'company_phone' in data:
            settings.company_phone = data.get('company_phone', '')
        if 'warranty_notes' in data:
            settings.warranty_notes = data.get('warranty_notes', '')
        if 'logo_circle_text' in data:
            settings.logo_circle_text = data.get('logo_circle_text', '')
        
        # Column Settings
        settings.show_discount_column = data.get('show_discount_column') == 'true'
        settings.show_tax_column = data.get('show_tax_column') == 'true'
        settings.show_unit_price_with_tax = data.get('show_unit_price_with_tax') == 'true'
        
        # Logo Settings
        settings.use_logo_image = data.get('use_logo_image') == 'true'
        
        # Returned Count Settings
        settings.show_returned_count = data.get('show_returned_count') == 'true'
        
        # Layout Settings (JSON)
        if 'layout_settings' in data:
            try:
                layout_data = json.loads(data.get('layout_settings', '{}'))
                settings.set_layout_settings(layout_data)
            except:
                pass
        
        # Visibility Settings (JSON) - Save additional settings
        visibility_settings = settings.get_visibility_settings()
        if 'show_barcode' in data:
            visibility_settings['show_barcode'] = data.get('show_barcode') == 'true'
        if 'show_qrcode' in data:
            visibility_settings['show_qrcode'] = data.get('show_qrcode') == 'true'
        settings.set_visibility_settings(visibility_settings)

        owner_uid = _template_owner_uid()
        owner_lookup_ids = _template_owner_lookup_ids(owner_uid)
        has_template_related_update = any([
            bool((data.get('selected_template_id') or '').strip()),
            'primary_color' in data,
            'secondary_color' in data,
            'custom_css' in data,
        ])

        raw_tid = (data.get('selected_template_id') or '').strip()
        selected_template_id = None
        if raw_tid:
            try:
                selected_template_id = int(raw_tid)
            except ValueError:
                return jsonify({"success": False, "error": "معرّف القالب غير صالح"}), 400

        if owner_uid and selected_template_id:
            with _core_db():
                template = InvoiceTemplate.query.get(selected_template_id)
                if template and template.is_premium:
                    approved_purchase = TenantTemplatePurchase.query.filter(
                        TenantTemplatePurchase.tenant_id.in_(owner_lookup_ids),
                        TenantTemplatePurchase.template_id == selected_template_id,
                        TenantTemplatePurchase.status == 'approved'
                    ).first() if owner_lookup_ids else None
                    if not approved_purchase:
                        return jsonify({"success": False, "error": "هذا القالب مدفوع ولم تتم الموافقة على شرائه بعد"}), 403

        # invoice_settings في قاعدة المستأجر؛ TenantTemplateSettings/User في Core.
        # commit واحد مع g.tenant مفعّل يوجّه كل الـ flush للمستأجر فيفشل حفظ القوالب → نفصل commit.
        settings.updated_at = datetime.utcnow()
        db.session.commit()

        if owner_uid and has_template_related_update:
            with _core_db():
                _ensure_invoice_owner_user(owner_uid)
                tset = TenantTemplateSettings.query.filter_by(tenant_id=owner_uid).first()
                if not tset:
                    tset = TenantTemplateSettings(tenant_id=owner_uid)
                    db.session.add(tset)

                if selected_template_id is not None:
                    template = InvoiceTemplate.query.get(selected_template_id)
                    if template:
                        tset.active_template_id = selected_template_id

                if 'primary_color' in data and data.get('primary_color'):
                    tset.primary_color = data.get('primary_color')
                if 'secondary_color' in data and data.get('secondary_color'):
                    tset.secondary_color = data.get('secondary_color')
                if 'custom_css' in data:
                    tset.custom_css = data.get('custom_css', '')

                db.session.commit()

        return jsonify({"success": True, "message": "تم حفظ الإعدادات بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400

@settings_bp.route("/invoice/upload-logo", methods=["POST"])
def upload_logo():
    """رفع لوجو الشركة"""
    try:
        if 'logo' not in request.files:
            return jsonify({"success": False, "error": "لم يتم اختيار ملف"}), 400
        
        file = request.files['logo']
        if file.filename == '':
            return jsonify({"success": False, "error": "لم يتم اختيار ملف"}), 400
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # Add timestamp to avoid conflicts
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"logo_{timestamp}_{filename}"
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)
            
            # Update settings
            settings = InvoiceSettings.get_settings()
            settings.logo_path = f"/static/uploads/logos/{filename}"
            settings.updated_at = datetime.utcnow()
            db.session.commit()
            
            return jsonify({
                "success": True,
                "message": "تم رفع اللوجو بنجاح",
                "logo_path": settings.logo_path
            })
        else:
            return jsonify({"success": False, "error": "نوع الملف غير مدعوم"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@settings_bp.route("/invoice/preview", methods=["POST"])
def preview_invoice():
    """معاينة الفاتورة مع الإعدادات"""
    try:
        # Get sample order data for preview
        from models.invoice import Invoice
        from models.order_item import OrderItem
        
        # Get a sample order, otherwise build a mock preview payload
        sample_order = Invoice.query.first()
        if sample_order:
            items = OrderItem.query.filter_by(invoice_id=sample_order.id).limit(3).all()
            if not items:
                from models.product import Product
                product = Product.query.first()
                if product:
                    items = [OrderItem(
                        product_name=product.name,
                        quantity=1,
                        price=product.selling_price,
                        total=product.selling_price
                    )]
                else:
                    items = [
                        SimpleNamespace(product_name="منتج تجريبي 1", quantity=2, price=12000, total=24000),
                        SimpleNamespace(product_name="منتج تجريبي 2", quantity=1, price=18000, total=18000),
                    ]
        else:
            sample_order = SimpleNamespace(
                id="TEST-001",
                customer=SimpleNamespace(
                    name="زبون تجريبي",
                    phone="07700000000",
                    address="عنوان تجريبي",
                    city="بغداد",
                ),
                employee_name="موظف تجريبي",
                created_at=datetime.utcnow(),
                total=42000,
                status="تم الطلب",
                payment_status="غير مسدد",
            )
            items = [
                SimpleNamespace(product_name="منتج تجريبي 1", quantity=2, price=12000, total=24000),
                SimpleNamespace(product_name="منتج تجريبي 2", quantity=1, price=18000, total=18000),
            ]
        
        settings = InvoiceSettings.get_settings()
        owner_uid = _template_owner_uid()
        owner_lookup_ids = _template_owner_lookup_ids(owner_uid)
        with _core_db():
            tset = TenantTemplateSettings.query.filter_by(tenant_id=owner_uid).first() if owner_uid else None
            if not tset and len(owner_lookup_ids) > 1:
                tset = TenantTemplateSettings.query.filter(TenantTemplateSettings.tenant_id.in_(owner_lookup_ids)).first()
        
        # Calculate totals
        total = sum(getattr(item, "total", 0) for item in items) if items else getattr(sample_order, "total", 0)
        due = total
        
        # Calculate returned and cancelled counts for preview
        returned_count = 2  # Mock value for preview
        cancelled_count = 1  # Mock value for preview
        
        if sample_order.customer:
            from models.customer import Customer
            from sqlalchemy import or_
            customer_phone = sample_order.customer.phone
            customers_with_same_phone = Customer.query.filter(
                or_(
                    Customer.phone == customer_phone,
                    Customer.phone2 == customer_phone
                )
            ).all()
            customer_ids = [c.id for c in customers_with_same_phone]
            
            returned_count = Invoice.query.filter(
                Invoice.customer_id.in_(customer_ids),
                or_(
                    Invoice.status == "راجع",
                    Invoice.payment_status == "مرتجع"
                )
            ).count()
            
            cancelled_count = Invoice.query.filter(
                Invoice.customer_id.in_(customer_ids),
                Invoice.status == "ملغي"
            ).count()
        
        # Return preview data
        return jsonify({
            "success": True,
            "order": {
                "id": sample_order.id,
                "customer": {
                    "name": sample_order.customer.name if sample_order.customer else "زبون تجريبي",
                    "phone": sample_order.customer.phone if sample_order.customer else "07700000000",
                    "address": sample_order.customer.address if sample_order.customer else "عنوان تجريبي",
                    "city": sample_order.customer.city if sample_order.customer else "بغداد"
                },
                "employee_name": sample_order.employee_name or "موظف تجريبي",
                "created_at": sample_order.created_at.strftime('%d/%m/%Y %I:%M %p') if sample_order.created_at else ""
            },
            "items": [
                {
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "price": item.price,
                    "total": item.total
                } for item in items
            ],
            "total": total,
            "due": due,
            "returned_count": returned_count,
            "cancelled_count": cancelled_count,
            "settings": {
                "company_name": settings.company_name,
                "company_subtitle": settings.company_subtitle,
                "logo_path": settings.logo_path,
                "company_address": settings.company_address,
                "company_phone": settings.company_phone,
                "warranty_notes": settings.warranty_notes,
                "logo_circle_text": settings.logo_circle_text,
                "show_discount_column": settings.show_discount_column,
                "show_tax_column": settings.show_tax_column,
                "show_unit_price_with_tax": settings.show_unit_price_with_tax,
                "use_logo_image": getattr(settings, 'use_logo_image', False),
                "show_returned_count": getattr(settings, 'show_returned_count', True),
                "layout_settings": settings.get_layout_settings(),
                "visibility_settings": settings.get_visibility_settings(),
                "show_barcode": settings.get_visibility_settings().get('show_barcode', True),
                "show_qrcode": settings.get_visibility_settings().get('show_qrcode', True),
                "primary_color": (tset.primary_color if tset else "#2563eb") or "#2563eb",
                "secondary_color": (tset.secondary_color if tset else "#4a5568") or "#4a5568",
                "custom_css": (tset.custom_css if tset else "") or "",
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

