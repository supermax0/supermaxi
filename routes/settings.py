from contextlib import contextmanager

from flask import Blueprint, render_template, request, jsonify, send_from_directory, session, g, redirect, current_app
from extensions import db
from models.invoice_settings import InvoiceSettings
from models.system_settings import SystemSettings
from routes.invoice_store import _session_tenant_slug, seed_templates
from models.invoice_template import InvoiceTemplate, TenantTemplateSettings, TenantTemplatePurchase
from models.user import User
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
import os
import json
from datetime import datetime
from types import SimpleNamespace
from utils.permission_checks import guard_permission
from utils.activity_logger import log_activity, log_mutation

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


@settings_bp.before_request
def _settings_permission_guard():
    from flask import session
    if "user_id" not in session:
        return None
    return guard_permission("manage_settings")

# Allowed extensions for logo upload
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'}
UPLOAD_FOLDER = 'static/uploads/logos'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _settings_ctx(nav_key, **extra):
    """سياق مشترك لكل صفحات الإعدادات."""
    from models.employee import Employee
    from utils.permission_checks import check_permission

    is_admin = False
    show_fixed_assets_settings = False
    show_rotating_savings_settings = False
    if "user_id" in session:
        emp = Employee.query.get(session["user_id"])
        is_admin = bool(emp and emp.is_active and emp.role == "admin")
        show_fixed_assets_settings = bool(
            check_permission("manage_fixed_assets") or check_permission("view_fixed_assets")
        )
        show_rotating_savings_settings = bool(
            check_permission("manage_rotating_savings") or check_permission("view_rotating_savings")
        )

    page_titles = {
        "overview": None,
        "appearance": "settings_nav_appearance",
        "system": "settings_nav_system",
        "invoice": "settings_card_invoice_title",
        "branches": "settings_card_branches_title",
        "storefront": "settings_nav_storefront",
        "database": "settings_card_db_repair_title",
        "permissions": "settings_nav_permissions",
        "fixed_assets": "settings_card_fixed_assets_title",
        "rotating_savings": "settings_card_rotating_savings_title",
    }
    title_key = page_titles.get(nav_key)

    return dict(
        settings_nav=nav_key,
        settings_hub_mode=(nav_key == "overview"),
        settings_page_title_key=title_key,
        is_admin=is_admin,
        show_fixed_assets_settings=show_fixed_assets_settings,
        show_rotating_savings_settings=show_rotating_savings_settings,
        **extra,
    )


def _template_owner_uid():
    slug = _session_tenant_slug()
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
    first_order = Invoice.query.order_by(Invoice.id.desc()).first()
    app_downloads = {
        "webview": os.environ.get("APP_WEBVIEW_APK_URL", "/static/downloads/finora-pos-webview.apk"),
        "native": os.environ.get("APP_NATIVE_APK_URL", "/static/downloads/finora-pos-native.apk"),
        "delivery_agent": os.environ.get(
            "APP_DELIVERY_AGENT_APK_URL",
            "/static/downloads/finora-delivery-agent.apk",
        ),
    }
    tenant_slug = _session_tenant_slug()
    portal_base = request.host_url.rstrip("/")
    delivery_agent_portal_url = (
        f"{portal_base}/delivery-agent/login/{tenant_slug}" if tenant_slug else f"{portal_base}/delivery-agent/login"
    )
    return render_template(
        "settings.html",
        **_settings_ctx(
            "overview",
            invoice_settings=invoice_settings,
            first_order=first_order,
            app_downloads=app_downloads,
            delivery_agent_portal_url=delivery_agent_portal_url,
            tenant_slug=tenant_slug,
        ),
    )

@settings_bp.route("/system")
def system_settings():
    """صفحة إعدادات النظام"""
    from models.employee import Employee
    from models.branch import Branch
    from models.role import Role
    from routes.permissions import ensure_default_permissions
    from utils.branch_migration import ensure_branch_schema
    from utils.weak_employee_messaging import get_weak_employee_message_settings

    ensure_branch_schema()
    ensure_default_permissions()
    employees = Employee.query.order_by(Employee.created_at.desc()).all()
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name.asc()).all()
    rbac_roles = Role.query.order_by(Role.name.asc()).all()
    weak_employee_message_settings = get_weak_employee_message_settings()
    return render_template(
        "system_settings.html",
        **_settings_ctx(
            "system",
            employees=employees,
            branches=branches,
            rbac_roles=rbac_roles,
            weak_employee_message_settings=weak_employee_message_settings,
        ),
    )


@settings_bp.route("/system/weak-employee-message", methods=["POST"])
def update_weak_employee_message_settings():
    """حفظ إعدادات رسالة الموظفين الضعيفين التلقائية."""
    try:
        from utils.weak_employee_messaging import save_weak_employee_message_settings

        data = request.get_json(silent=True) or {}
        config = save_weak_employee_message_settings(data)
        try:
            log_activity(
                "update",
                "settings",
                "تحديث إعدادات رسالة الموظفين الضعيفين",
                entity_type="system_settings",
                payload={
                    "enabled": config.get("enabled"),
                    "interval_days": config.get("interval_days"),
                    "period_days": config.get("period_days"),
                    "min_orders": config.get("min_orders"),
                    "min_sales": config.get("min_sales"),
                },
            )
        except Exception:
            pass
        return jsonify({"success": True, "message": "تم حفظ إعدادات الرسالة", "config": config})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@settings_bp.route("/system/weak-employee-message/send-now", methods=["POST"])
def send_weak_employee_message_now():
    """إرسال الرسالة الآن للموظفين الضعيفين، لا ينتظر الجدولة."""
    try:
        from utils.weak_employee_messaging import send_weak_employee_messages

        result = send_weak_employee_messages(force=True)
        if not result.get("success"):
            return jsonify({"success": False, "error": result.get("reason") or "تعذر الإرسال"}), 400
        return jsonify({
            "success": True,
            "message": f"تم إرسال {result.get('sent', 0)} رسالة",
            "result": result,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400

@settings_bp.route("/system/update-role", methods=["POST"])
def update_employee_role():
    """تحديث أدوار موظف (RBAC) مع مزامنة الدور الأساسي admin/cashier."""
    try:
        from models.employee import Employee
        from models.role import Role

        data = request.get_json()
        employee_id = data.get("employee_id")
        role_ids = data.get("role_ids")
        new_role = data.get("role")

        if not employee_id:
            return jsonify({"success": False, "error": "بيانات ناقصة"}), 400

        employee = Employee.query.get(employee_id)
        if not employee:
            return jsonify({"success": False, "error": "الموظف غير موجود"}), 404

        old_role = employee.role
        old_role_ids = [r.id for r in (employee.roles or [])]

        if role_ids is not None:
            if not isinstance(role_ids, list):
                return jsonify({"success": False, "error": "صيغة الأدوار غير صحيحة"}), 400
            role_ids = [int(rid) for rid in role_ids]
            roles = Role.query.filter(Role.id.in_(role_ids)).all() if role_ids else []
            if role_ids and len(roles) != len(set(role_ids)):
                return jsonify({"success": False, "error": "دور غير موجود"}), 400
            employee.roles = roles
            role_names = {r.name for r in roles}
            employee.role = "admin" if "admin" in role_names else "cashier"
        elif new_role:
            if new_role not in ["admin", "cashier"]:
                return jsonify({"success": False, "error": "دور غير صحيح"}), 400
            employee.role = new_role
            base_role = Role.query.filter_by(name=new_role).first()
            if base_role:
                employee.roles = [base_role]
        else:
            return jsonify({"success": False, "error": "بيانات ناقصة"}), 400

        db.session.commit()
        try:
            log_mutation(
                "update",
                "settings",
                "employee",
                employee.id,
                {"role": old_role, "role_ids": old_role_ids},
                {"role": employee.role, "role_ids": [r.id for r in (employee.roles or [])]},
                f"تغيير أدوار الموظف {employee.name}",
            )
        except Exception:
            pass

        return jsonify({"success": True, "message": "تم تحديث الأدوار بنجاح"})
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
    """معطّل — استخدم /admin/permissions/roles لإدارة الصلاحيات عبر RBAC."""
    return jsonify({
        "success": False,
        "error": "تم إيقاف تعديل الصلاحيات القديمة. استخدم صفحة الأدوار والصلاحيات.",
        "redirect": "/admin/permissions/roles",
    }), 410

@settings_bp.route("/system/get-permissions/<int:employee_id>")
def get_employee_permissions(employee_id):
    """جلب صلاحيات موظف"""
    try:
        from models.employee import Employee
        employee = Employee.query.get(employee_id)
        if not employee:
            return jsonify({"success": False, "error": "الموظف غير موجود"}), 404
        
        from utils.permission_checks import LEGACY_TO_RBAC, employee_can

        permissions = {}
        for legacy_key, rbac_key in LEGACY_TO_RBAC.items():
            permissions[legacy_key] = employee_can(employee, rbac_key)
        
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
        seed_templates()
        template_rows = InvoiceTemplate.query.order_by(InvoiceTemplate.price.asc(), InvoiceTemplate.id.asc()).all()
        templates = [
            SimpleNamespace(
                id=row.id,
                name=row.name,
                description=row.description,
                html_file_name=row.html_file_name,
                is_premium=row.is_premium,
                price=row.price or 0,
            )
            for row in template_rows
        ]
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
        active_template_id = tset.active_template_id if tset else None
    settings = InvoiceSettings.get_settings()
    return render_template(
        "invoice_settings.html",
        **_settings_ctx(
            "invoice",
            settings=settings,
            templates=templates,
            active_template_id=active_template_id,
            purchased_ids=purchased_ids,
            template_style=template_style,
        ),
    )


@settings_bp.route("/appearance")
def appearance_settings():
    """صفحة إعدادات الواجهة (الثيم، الخط، المساعد)"""
    settings = SystemSettings.get_settings()
    return render_template(
        "settings_appearance.html",
        **_settings_ctx("appearance", settings=settings),
    )


@settings_bp.route("/storefront")
def storefront_settings():
    """صفحة إعدادات المتجر الإلكتروني."""
    from models.invoice_settings import InvoiceSettings
    from modules.storefront.services.store_layout_service import card_sizes_catalog, card_templates_catalog

    settings = SystemSettings.get_settings()
    invoice_settings = InvoiceSettings.get_settings()
    ui_flags = settings.get_ui_flags() if settings else {}
    return render_template(
        "settings_storefront.html",
        **_settings_ctx(
            "storefront",
            settings=settings,
            invoice_settings=invoice_settings,
            card_templates_catalog=card_templates_catalog(),
            card_sizes_catalog=card_sizes_catalog(),
            storefront_product_sections=ui_flags.get("storefront_product_sections", []),
        ),
    )


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
        data = request.form

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

        # تحقق مدفوع على Core أولاً (قراءة فقط)
        if owner_uid and selected_template_id:
            with _core_db():
                existing_tset = TenantTemplateSettings.query.filter_by(tenant_id=owner_uid).first()
                template = InvoiceTemplate.query.get(selected_template_id)
                if template and template.is_premium:
                    # إذا السوبر أدمن فعّل هذا القالب مسبقاً للشركة، لا نمنع الحفظ.
                    if existing_tset and existing_tset.active_template_id == selected_template_id:
                        pass
                    else:
                        approved_purchase = TenantTemplatePurchase.query.filter(
                            TenantTemplatePurchase.tenant_id.in_(owner_lookup_ids),
                            TenantTemplatePurchase.template_id == selected_template_id,
                            TenantTemplatePurchase.status == 'approved'
                        ).first() if owner_lookup_ids else None
                        if not approved_purchase:
                            return jsonify({"success": False, "error": "هذا القالب مدفوع ولم تتم الموافقة على شرائه بعد"}), 403

        # إزالة أي كائنات Core من الجلسة قبل لمس invoice_settings (تجنّب flush مختلط / StaleDataError)
        db.session.rollback()

        settings = InvoiceSettings.get_settings()

        if 'company_name' in data:
            settings.company_name = data.get('company_name', '')
        if 'company_subtitle' in data:
            settings.company_subtitle = data.get('company_subtitle', '')
        if 'company_address' in data:
            settings.company_address = data.get('company_address', '')
        if 'company_phone' in data:
            settings.company_phone = data.get('company_phone', '')
        if 'return_policy_notes' in data:
            settings.return_policy_notes = data.get('return_policy_notes', '')
        if 'warranty_notes' in data:
            settings.warranty_notes = data.get('warranty_notes', '')
        if 'warranty_card_background' in data:
            settings.warranty_card_background = (
                data.get('warranty_card_background')
                or "linear-gradient(135deg, #031021 0%, #1f2e42 100%)"
            ).strip()
        if 'logo_circle_text' in data:
            settings.logo_circle_text = data.get('logo_circle_text', '')

        # إعدادات التقرير المالي (تُخزّن None عند الفراغ لتفعيل fallback لبيانات الفاتورة)
        if 'report_company_name' in data:
            settings.report_company_name = (data.get('report_company_name') or '').strip() or None
        if 'report_address' in data:
            settings.report_address = (data.get('report_address') or '').strip() or None
        if 'report_phone' in data:
            settings.report_phone = (data.get('report_phone') or '').strip() or None
        if 'report_footer_text' in data:
            settings.report_footer_text = (data.get('report_footer_text') or '').strip() or None
        if 'report_show_logo' in data:
            settings.report_show_logo = data.get('report_show_logo') == 'true'

        settings.show_discount_column = data.get('show_discount_column') == 'true'
        settings.show_tax_column = data.get('show_tax_column') == 'true'
        settings.show_unit_price_with_tax = data.get('show_unit_price_with_tax') == 'true'
        settings.use_logo_image = data.get('use_logo_image') == 'true'
        settings.show_returned_count = data.get('show_returned_count') == 'true'

        if 'layout_settings' in data:
            try:
                layout_data = json.loads(data.get('layout_settings', '{}'))
                settings.set_layout_settings(layout_data)
            except Exception:
                pass

        visibility_settings = settings.get_visibility_settings()
        if 'show_barcode' in data:
            visibility_settings['show_barcode'] = data.get('show_barcode') == 'true'
        if 'show_qrcode' in data:
            visibility_settings['show_qrcode'] = data.get('show_qrcode') == 'true'
        settings.set_visibility_settings(visibility_settings)

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

@settings_bp.route("/invoice/upload-report-logo", methods=["POST"])
def upload_report_logo():
    """رفع لوجو خاص بالتقرير المالي"""
    try:
        if 'logo' not in request.files:
            return jsonify({"success": False, "error": "لم يتم اختيار ملف"}), 400

        file = request.files['logo']
        if file.filename == '':
            return jsonify({"success": False, "error": "لم يتم اختيار ملف"}), 400

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"report_logo_{timestamp}_{filename}"
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            file.save(filepath)

            settings = InvoiceSettings.get_settings()
            settings.report_logo_path = f"/static/uploads/logos/{filename}"
            settings.updated_at = datetime.utcnow()
            db.session.commit()

            return jsonify({
                "success": True,
                "message": "تم رفع لوجو التقرير بنجاح",
                "logo_path": settings.report_logo_path
            })
        else:
            return jsonify({"success": False, "error": "نوع الملف غير مدعوم"}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@settings_bp.route("/storefront/upload-hero-image", methods=["POST"])
def upload_storefront_hero_image():
    """رفع صورة لاستخدامها في شرائح إعلان المتجر (hero)."""
    try:
        if "image" not in request.files:
            return jsonify({"success": False, "error": "لم يتم اختيار ملف"}), 400

        file = request.files["image"]
        if not file or file.filename == "":
            return jsonify({"success": False, "error": "لم يتم اختيار ملف"}), 400

        if not allowed_file(file.filename):
            return jsonify({"success": False, "error": "نوع الملف غير مدعوم"}), 400

        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"storefront_hero_{timestamp}_{filename}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        return jsonify(
            {
                "success": True,
                "message": "تم رفع الصورة بنجاح",
                "url": f"/static/uploads/logos/{filename}",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@settings_bp.route("/invoice/remove-report-logo", methods=["POST"])
def remove_report_logo():
    """حذف لوجو التقرير المالي"""
    try:
        settings = InvoiceSettings.get_settings()
        settings.report_logo_path = None
        settings.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"success": True, "message": "تم حذف لوجو التقرير"})
    except Exception as e:
        db.session.rollback()
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
                "return_policy_notes": getattr(settings, "return_policy_notes", "") or "",
                "warranty_notes": settings.warranty_notes,
                "warranty_card_background": getattr(settings, "warranty_card_background", "") or "linear-gradient(135deg, #031021 0%, #1f2e42 100%)",
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


def _require_active_admin():
    from models.employee import Employee

    if "user_id" not in session:
        return None
    emp = Employee.query.get(session["user_id"])
    if not emp or not emp.is_active or emp.role != "admin":
        return None
    return emp


@settings_bp.route("/branches")
def branches_settings():
    from models.branch import Branch
    from utils.branch_migration import ensure_branch_schema
    from utils.branch_sales import is_sell_from_all_branches_enabled
    from utils.shipping_branch_schedule import get_shipping_branch_schedule_settings

    try:
        ensure_branch_schema()
        branches = Branch.query.order_by(Branch.is_default.desc(), Branch.name.asc()).all()
    except Exception:
        current_app.logger.exception("failed loading branches settings page")
        branches = []
    return render_template(
        "settings_branches.html",
        **_settings_ctx(
            "branches",
            branches=branches,
            sell_from_all_branches=is_sell_from_all_branches_enabled(),
            shipping_branch_schedule=get_shipping_branch_schedule_settings(),
        ),
    )


@settings_bp.route("/branches/shipping-schedule", methods=["POST"])
def branches_shipping_schedule():
    """حفظ جدولة فرع الخصم عند تحويل الطلب إلى جاري الشحن."""
    from models.branch import Branch
    from utils.shipping_branch_schedule import set_shipping_branch_schedule

    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("shipping_branch_schedule_enabled"))
    day_start = (data.get("shipping_day_start") or "08:00").strip()
    day_end = (data.get("shipping_day_end") or "17:00").strip()

    day_branch_id = data.get("shipping_day_branch_id")
    night_branch_id = data.get("shipping_night_branch_id")
    try:
        day_branch_id = int(day_branch_id) if day_branch_id not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "فرع النهار غير صالح"}), 400
    try:
        night_branch_id = int(night_branch_id) if night_branch_id not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "فرع الليل غير صالح"}), 400

    if enabled:
        if not day_branch_id or not night_branch_id:
            return jsonify({
                "success": False,
                "error": "عند التفعيل يجب اختيار فرع النهار وفرع الليل",
            }), 400
        for branch_id, label in ((day_branch_id, "فرع النهار"), (night_branch_id, "فرع الليل")):
            branch = Branch.query.filter_by(id=branch_id, is_active=True).first()
            if not branch:
                return jsonify({"success": False, "error": f"{label} غير موجود أو غير نشط"}), 400

    try:
        set_shipping_branch_schedule(
            enabled=enabled,
            day_branch_id=day_branch_id,
            night_branch_id=night_branch_id,
            day_start=day_start,
            day_end=day_end,
        )
        db.session.commit()
        try:
            log_activity(
                "update",
                "settings",
                "تحديث جدولة فرع الخصم عند الشحن",
                entity_type="system_settings",
                payload={
                    "shipping_branch_schedule_enabled": enabled,
                    "shipping_day_branch_id": day_branch_id,
                    "shipping_night_branch_id": night_branch_id,
                    "shipping_day_start": day_start,
                    "shipping_day_end": day_end,
                },
            )
        except Exception:
            pass
        return jsonify({
            "success": True,
            "message": "تم حفظ جدولة فرع الخصم عند الشحن",
        })
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@settings_bp.route("/branches/sales-policy", methods=["POST"])
def branches_sales_policy():
    """حفظ سياسة البيع عبر الفروع."""
    from utils.branch_sales import set_sell_from_all_branches

    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("sell_from_all_branches"))
    try:
        set_sell_from_all_branches(enabled)
        db.session.commit()
        try:
            log_activity(
                "update",
                "settings",
                "تفعيل البيع لكل الفروع" if enabled else "تعطيل البيع لكل الفروع",
                entity_type="system_settings",
                payload={"sell_from_all_branches": enabled},
            )
        except Exception:
            pass
        return jsonify({
            "success": True,
            "message": "تم حفظ سياسة البيع عبر الفروع",
            "sell_from_all_branches": enabled,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400


@settings_bp.route("/branches/save", methods=["POST"])
def branches_save():
    from models.branch import Branch
    from utils.branch_migration import ensure_branch_schema

    ensure_branch_schema()
    data = request.get_json(silent=True) or {}
    branch_id = data.get("id")
    code = (data.get("code") or "").strip().upper()
    name = (data.get("name") or "").strip()
    address = (data.get("address") or "").strip() or None
    phone = (data.get("phone") or "").strip() or None
    is_active = bool(data.get("is_active", True))
    is_default = bool(data.get("is_default", False))

    if not code or not name:
        return jsonify({"success": False, "error": "الكود والاسم مطلوبان"}), 400

    if branch_id:
        branch = Branch.query.get(branch_id)
        if not branch:
            return jsonify({"success": False, "error": "الفرع غير موجود"}), 404
        before = branch.to_dict()
        dup = Branch.query.filter(Branch.code == code, Branch.id != branch.id).first()
        if dup:
            return jsonify({"success": False, "error": "كود الفرع مستخدم"}), 400
        branch.code = code
        branch.name = name
        branch.address = address
        branch.phone = phone
        branch.is_active = is_active
        if is_default:
            for b in Branch.query.all():
                b.is_default = False
            branch.is_default = True
        db.session.commit()
        log_mutation("update", "branch", "branch", branch.id, before, branch.to_dict(), f"تحديث فرع {branch.name}")
        return jsonify({"success": True, "branch": branch.to_dict()})

    dup = Branch.query.filter_by(code=code).first()
    if dup:
        return jsonify({"success": False, "error": "كود الفرع مستخدم"}), 400
    if is_default:
        for b in Branch.query.all():
            b.is_default = False
    branch = Branch(code=code, name=name, address=address, phone=phone, is_active=is_active, is_default=is_default)
    db.session.add(branch)
    db.session.commit()
    log_mutation("create", "branch", "branch", branch.id, None, branch.to_dict(), f"إضافة فرع {branch.name}")
    return jsonify({"success": True, "branch": branch.to_dict()})


@settings_bp.route("/system/update-branch", methods=["POST"])
def update_employee_branch():
    try:
        from models.branch import Branch
        from models.employee import Employee

        data = request.get_json(silent=True) or {}
        employee_id = data.get("employee_id")
        branch_id = data.get("branch_id")
        if not employee_id:
            return jsonify({"success": False, "error": "معرف الموظف مطلوب"}), 400
        employee = Employee.query.get(employee_id)
        if not employee:
            return jsonify({"success": False, "error": "الموظف غير موجود"}), 404
        if branch_id:
            branch = Branch.query.get(branch_id)
            if not branch:
                return jsonify({"success": False, "error": "الفرع غير موجود"}), 404
        old_branch = employee.branch_id
        employee.branch_id = int(branch_id) if branch_id else None
        db.session.commit()
        log_mutation(
            "update",
            "employee",
            "employee",
            employee.id,
            {"branch_id": old_branch},
            {"branch_id": employee.branch_id},
            f"تعيين فرع للموظف {employee.name}",
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


@settings_bp.route("/database-repair")
def database_repair_page():
    """أداة صيانة مخطط قاعدة بيانات الشركة (جداول/أعمدة ناقصة) — للمدير فقط."""
    if not _require_active_admin():
        return redirect("/settings")
    slug = session.get("tenant_slug") or ""
    return render_template(
        "database_repair.html",
        **_settings_ctx("database", tenant_slug=slug),
    )


@settings_bp.route("/database-repair/api", methods=["POST"])
def database_repair_api():
    """فحص أو تطبيق إصلاحات المخطط على ملف SQLite الخاص بالشركة."""
    from extensions_tenant import clear_tenant_engine, get_tenant_engine
    from services.schema_repair import repair_tenant_schema

    if not _require_active_admin():
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    slug = session.get("tenant_slug")
    if not slug:
        return jsonify({"success": False, "error": "لا يوجد سياق شركة."}), 400

    data = request.get_json(silent=True) or {}
    dry_run = bool(data.get("dry_run", True))

    engine = get_tenant_engine(slug)
    try:
        report = repair_tenant_schema(engine, dry_run=dry_run)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    if not dry_run:
        clear_tenant_engine(slug)

    return jsonify({"success": True, "report": report})

