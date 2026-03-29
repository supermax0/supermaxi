from contextlib import contextmanager
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, session, g

from extensions import db
from models.invoice_template import InvoiceTemplate, TenantTemplateSettings, TenantTemplatePurchase

invoice_store_bp = Blueprint('invoice_store', __name__)


def _template_tenant_uid():
    """
    يطابق routes/orders.py (طباعة الفاتورة): معرف سجل tenant المحلي أو موظف الجلسة.
    """
    return session.get("tenant_id") or session.get("user_id")


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
        settings = TenantTemplateSettings.query.filter_by(tenant_id=uid).first()
        active_id = settings.active_template_id if settings else None

        templates = InvoiceTemplate.query.order_by(InvoiceTemplate.price.asc(), InvoiceTemplate.id.asc()).all()

        purchases = TenantTemplatePurchase.query.filter_by(tenant_id=uid).all()
        purchased_ids = {p.template_id: p.status for p in purchases}

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
    with _core_db():
        template = InvoiceTemplate.query.get_or_404(template_id)

        existing = TenantTemplatePurchase.query.filter_by(tenant_id=uid, template_id=template_id).first()
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
    with _core_db():
        template = InvoiceTemplate.query.get_or_404(template_id)

        if template.is_premium:
            purchase = TenantTemplatePurchase.query.filter_by(tenant_id=uid, template_id=template_id, status='approved').first()
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
