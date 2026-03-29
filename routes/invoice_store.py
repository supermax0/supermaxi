import os
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, g, current_app

from extensions import db
from models.invoice_template import InvoiceTemplate, TenantTemplateSettings, TenantTemplatePurchase
from models.user import User

invoice_store_bp = Blueprint('invoice_store', __name__)


def _session_tenant_slug():
    """معرّف الشركة في الرابط: من الجلسة أو من g.tenant (بعد تسجيل الدخول)."""
    slug = (session.get("tenant_slug") or "").strip().lower()
    if slug:
        return slug
    ctx = getattr(g, "tenant", None)
    if isinstance(ctx, str) and ctx.strip():
        return ctx.strip().lower()
    return ""


def _template_tenant_uid():
    """
    معرّف مالك القالب على مستوى الشركة (يفضَّل tenant.id من Core عبر tenant_slug).
    fallback للجلسات القديمة: tenant_id أو user_id.
    """
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


def _template_lookup_owner_ids(primary_uid):
    """يدعم قراءة الإعدادات القديمة (قبل التحويل لمعرف الشركة المركزي)."""
    ids = []
    legacy_uid = session.get("tenant_id") or session.get("user_id")
    for uid in (primary_uid, legacy_uid):
        if uid and uid not in ids:
            ids.append(uid)
    return ids


def _ensure_invoice_owner_user(owner_id):
    """
    جداول القوالب مرتبطة حالياً بـ users.id بينما التطبيق يعتمد فعلياً على employee/session.
    ننشئ صفاً توافقياً في users عند أول استخدام حتى لا يفشل FK أثناء التفعيل/الشراء.
    """
    if not owner_id:
        return None

    existing = db.session.get(User, owner_id)
    if existing:
        return owner_id

    from werkzeug.security import generate_password_hash

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


@contextmanager
def _core_db():
    """
    كتالوج القوالب وإعدادات/مشتريات القوالب مخزّنة في قاعدة Core.
    عند ضبط g.tenant يوجّه DynamicTenantSession الاستعلامات إلى SQLite المستأجر
    حيث لا توجد جداول invoice_templates → 500.
    """
    prev = getattr(g, "tenant", None)
    g.tenant = None
    try:
        yield
    finally:
        g.tenant = prev


def _require_session_login():
    if "user_id" not in session:
        return redirect("/login")
    return None


@invoice_store_bp.route('/admin/invoice-templates', methods=['GET'])
def store_home():
    redir = _require_session_login()
    if redir:
        return redir
    with _core_db():
        if InvoiceTemplate.query.count() == 0:
            seed_templates()

        uid = _template_tenant_uid()
        lookup_ids = _template_lookup_owner_ids(uid)
        settings = TenantTemplateSettings.query.filter_by(tenant_id=uid).first()
        if not settings and len(lookup_ids) > 1:
            settings = TenantTemplateSettings.query.filter(TenantTemplateSettings.tenant_id.in_(lookup_ids)).first()
        active_id = settings.active_template_id if settings else None

        templates = InvoiceTemplate.query.order_by(InvoiceTemplate.price.asc(), InvoiceTemplate.id.asc()).all()

        purchases = TenantTemplatePurchase.query.filter(TenantTemplatePurchase.tenant_id.in_(lookup_ids)).all() if lookup_ids else []
        purchased_ids = {}
        status_rank = {"approved": 3, "pending": 2, "rejected": 1}
        for p in purchases:
            old = purchased_ids.get(p.template_id)
            if not old or status_rank.get(p.status, 0) > status_rank.get(old, 0):
                purchased_ids[p.template_id] = p.status

        return render_template(
            'invoice_templates_store.html',
            templates=templates,
            active_id=active_id,
            purchased_ids=purchased_ids,
        )


@invoice_store_bp.route('/admin/invoice_templates', methods=['GET'])
def store_home_underscore_alias():
    """Backward-compatible URL (underscore) → canonical hyphenated route."""
    return redirect(url_for('invoice_store.store_home'), code=302)


@invoice_store_bp.route('/admin/invoice-templates/preview/<int:template_id>', methods=['GET'])
def preview_invoice_template(template_id):
    """معاينة قالب فاتورة ببيانات تجريبية (اسم المتجر من إعدادات الفاتورة للشركة)."""
    redir = _require_session_login()
    if redir:
        return redir

    with _core_db():
        catalog = InvoiceTemplate.query.get_or_404(template_id)
        html_name = catalog.html_file_name

    inv_settings = SimpleNamespace(
        store_name="متجر تجريبي",
        company_subtitle="معاينة قالب الفاتورة",
        company_address="بغداد - عنوان تجريبي",
        phone1="07700000000",
        phone2=None,
        invoice_note="شكراً لتسوقكم معنا! — هذه معاينة فقط.",
    )
    slug = session.get("tenant_slug")
    if slug:
        prev = getattr(g, "tenant", None)
        g.tenant = slug
        try:
            from models.invoice_settings import InvoiceSettings

            s = InvoiceSettings.get_settings()
            inv_settings = SimpleNamespace(
                store_name=(s.company_name or "متجر تجريبي"),
                company_subtitle=(s.company_subtitle or "").strip() or "معاينة قالب الفاتورة",
                company_address=(s.company_address or "").strip(),
                phone1=s.company_phone or "",
                phone2=None,
                invoice_note=(s.warranty_notes or "شكراً لتسوقكم معنا!")[:800],
            )
        except Exception:
            pass
        finally:
            g.tenant = prev

    order = SimpleNamespace(
        id=1001,
        created_at=datetime.now(),
        payment_status="مدفوع",
        status="تم الطلب",
        employee_name="موظف تجريبي",
        shipping_company=None,
        note="معاينة قالب — ليست فاتورة حقيقية.",
        customer=SimpleNamespace(
            name="عميل تجريبي",
            phone="07801234567",
            phone2=None,
            city="بغداد",
            address="عنوان تجريبي",
        ),
    )
    items = [
        SimpleNamespace(
            product_name="منتج تجريبي أ",
            price=15000,
            quantity=2,
            total=30000,
            product=None,
        ),
        SimpleNamespace(
            product_name="منتج تجريبي ب",
            price=25000,
            quantity=1,
            total=25000,
            product=None,
        ),
    ]
    total = 55000
    due = 55000
    returned_count = 0
    cancelled_count = 0

    template_styles = {"primary": "#2563eb", "secondary": "#4a5568", "custom_css": None}
    uid = _template_tenant_uid()
    lookup_ids = _template_lookup_owner_ids(uid)
    with _core_db():
        tset = TenantTemplateSettings.query.filter_by(tenant_id=uid).first()
        if not tset and len(lookup_ids) > 1:
            tset = TenantTemplateSettings.query.filter(TenantTemplateSettings.tenant_id.in_(lookup_ids)).first()
        if tset:
            template_styles = {
                "primary": tset.primary_color or template_styles["primary"],
                "secondary": tset.secondary_color or template_styles["secondary"],
                "custom_css": tset.custom_css,
            }

    qp = (request.args.get("primary_color") or "").strip()
    qs = (request.args.get("secondary_color") or "").strip()
    if len(qp) == 7 and qp.startswith("#"):
        template_styles["primary"] = qp
    if len(qs) == 7 and qs.startswith("#"):
        template_styles["secondary"] = qs

    template_file = f"invoices/{html_name}"
    full_path = os.path.join(current_app.template_folder, template_file.replace("/", os.sep))
    if not os.path.isfile(full_path):
        template_file = "invoice.html"

    return render_template(
        template_file,
        order=order,
        items=items,
        total=total,
        due=due,
        returned_count=returned_count,
        cancelled_count=cancelled_count,
        settings=inv_settings,
        template_styles=template_styles,
    )


@invoice_store_bp.route('/admin/invoice-templates/customize', methods=['GET'])
def customize_invoice_templates():
    """
    صفحة التخصيص المطلوبة من متجر القوالب.
    نعيد التوجيه إلى واجهة إعدادات الفاتورة الموجودة فعلاً.
    """
    redir = _require_session_login()
    if redir:
        return redir
    return redirect(url_for('settings.invoice_settings'))


def seed_templates():
    default_templates = [
        {'name': 'الأساسي (Basic)', 'description': 'قالب بسيط ونظيف ومجاني.', 'html_file_name': 'basic.html', 'is_premium': False, 'price': 0},
        {'name': 'الكلاسيكي (Classic)', 'description': 'أبيض وأسود، مناسب للطباعة السريعة.', 'html_file_name': 'classic.html', 'is_premium': False, 'price': 0},
        {'name': 'الحديث المظلم (Dark)', 'description': 'قالب احترافي داكن للعلامات العصرية.', 'html_file_name': 'modern_dark.html', 'is_premium': True, 'price': 5000},
        {'name': 'الأنيق (Elegant)', 'description': 'خطوط Serif وحواف رقيقة، مناسب للأزياء.', 'html_file_name': 'elegant.html', 'is_premium': True, 'price': 7000},
        {'name': 'الحراري (Thermal 80mm)', 'description': 'مخصص لطابعات الريسيت الحرارية.', 'html_file_name': 'thermal.html', 'is_premium': True, 'price': 3000},
        {'name': 'الشركات (Corporate)', 'description': 'شكل رسمي أزرق، مثالي للتعامل B2B.', 'html_file_name': 'corporate.html', 'is_premium': True, 'price': 8000},
        {'name': 'إبداعي (Creative)', 'description': 'ألوان نابضة بالحياة وتصميم غير متناظر.', 'html_file_name': 'creative.html', 'is_premium': True, 'price': 6000},
        {'name': 'المتجر الإلكتروني', 'description': 'يعرض شروط الاسترجاع بشكل واضح وبارز.', 'html_file_name': 'ecommerce.html', 'is_premium': True, 'price': 5000},
        {'name': 'الخط العربي الأصيل', 'description': 'زخرفة إسلامية وخط عربي أصيل.', 'html_file_name': 'arabic.html', 'is_premium': True, 'price': 10000},
        {'name': 'الفاخر (Luxury Gold)', 'description': 'ذهبي وأسود، فخامة مطلقة للعطور والمجوهرات.', 'html_file_name': 'luxury.html', 'is_premium': True, 'price': 15000},
    ]
    for t in default_templates:
        tmpl = InvoiceTemplate(
            name=t['name'],
            description=t['description'],
            html_file_name=t['html_file_name'],
            is_premium=t['is_premium'],
            price=t['price'],
        )
        db.session.add(tmpl)
    db.session.commit()

@invoice_store_bp.route('/admin/invoice-templates/buy/<int:template_id>', methods=['POST'])
def buy_template(template_id):
    redir = _require_session_login()
    if redir:
        return jsonify({'success': False, 'message': 'غير مصرّح'}), 401
    uid = _template_tenant_uid()
    lookup_ids = _template_lookup_owner_ids(uid)
    with _core_db():
        _ensure_invoice_owner_user(uid)
        template = InvoiceTemplate.query.get_or_404(template_id)

        existing = TenantTemplatePurchase.query.filter(
            TenantTemplatePurchase.tenant_id.in_(lookup_ids),
            TenantTemplatePurchase.template_id == template_id
        ).first() if lookup_ids else None
        if existing:
            return jsonify({'success': False, 'message': 'لقد قمت بطلب هذا القالب مسبقاً.'}), 400

        if not template.is_premium or template.price == 0:
            settings = TenantTemplateSettings.query.filter_by(tenant_id=uid).first()
            if not settings:
                settings = TenantTemplateSettings(tenant_id=uid)
                db.session.add(settings)
            settings.active_template_id = template_id
            db.session.commit()
            return jsonify({'success': True, 'message': 'تم تفعيل القالب بنجاح!', 'free': True})

        ref_number = request.form.get('reference_number')
        if not ref_number:
            return jsonify({'success': False, 'message': 'يرجى إدخال رقم الحوالة.'}), 400

        purchase = TenantTemplatePurchase(
            tenant_id=uid,
            template_id=template_id,
            amount_paid=template.price,
            status='pending',
            reference_number=ref_number
        )

        db.session.add(purchase)
        db.session.commit()

        return jsonify({'success': True, 'message': 'تم إرسال طلب الشراء. سيتم تفعيل القالب بعد مراجعة الحوالة من قبل الإدارة.', 'free': False})

@invoice_store_bp.route('/admin/invoice-templates/activate/<int:template_id>', methods=['POST'])
def activate_template(template_id):
    redir = _require_session_login()
    if redir:
        return jsonify({'success': False, 'message': 'غير مصرّح'}), 401
    uid = _template_tenant_uid()
    lookup_ids = _template_lookup_owner_ids(uid)
    with _core_db():
        _ensure_invoice_owner_user(uid)
        template = InvoiceTemplate.query.get_or_404(template_id)

        if template.is_premium:
            purchase = TenantTemplatePurchase.query.filter(
                TenantTemplatePurchase.tenant_id.in_(lookup_ids),
                TenantTemplatePurchase.template_id == template_id,
                TenantTemplatePurchase.status == 'approved'
            ).first() if lookup_ids else None
            if not purchase:
                return jsonify({'success': False, 'message': 'يجب شراء القالب أو انتظار موافقة الإدارة أولاً.'}), 403

        settings = TenantTemplateSettings.query.filter_by(tenant_id=uid).first()
        if not settings:
            settings = TenantTemplateSettings(tenant_id=uid)
            db.session.add(settings)

        settings.active_template_id = template_id
        db.session.commit()

        return jsonify({'success': True, 'message': 'تم تفعيل القالب بنجاح!'})

@invoice_store_bp.route('/superadmin/invoice-purchases', methods=['GET'])
def manage_purchases():
    if "user_id" not in session:
        return redirect("/login")
    if session.get("role") != 'admin':
        flash('ليس لديك صلاحية لدخول هذه الصفحة', 'danger')
        return redirect(url_for('index.index'))

    with _core_db():
        purchases = TenantTemplatePurchase.query.order_by(TenantTemplatePurchase.purchase_date.desc()).all()
        from models.employee import Employee
        for p in purchases:
            # tenant_id في السجل يُطابق جلسة الطلبات (معرّف tenant محلي أو موظف); جدول employee في Core
            p.user = Employee.query.get(p.tenant_id)
            p.template = InvoiceTemplate.query.get(p.template_id)

        return render_template('manage_template_purchases.html', purchases=purchases)

@invoice_store_bp.route('/superadmin/invoice-purchases/approve/<int:purchase_id>', methods=['POST'])
def approve_purchase(purchase_id):
    if session.get("role") != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    with _core_db():
        purchase = TenantTemplatePurchase.query.get_or_404(purchase_id)
        purchase.status = 'approved'
        db.session.commit()
        return jsonify({'success': True, 'message': 'تمت الموافقة على الشراء وتفعيل القالب للتاجر.'})

@invoice_store_bp.route('/superadmin/invoice-purchases/reject/<int:purchase_id>', methods=['POST'])
def reject_purchase(purchase_id):
    if session.get("role") != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    with _core_db():
        purchase = TenantTemplatePurchase.query.get_or_404(purchase_id)
        purchase.status = 'rejected'
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم رفض طلب الشراء.'})
