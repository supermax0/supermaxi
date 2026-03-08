from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
import os
from datetime import datetime

from extensions import db
from models.invoice_template import InvoiceTemplate, TenantTemplateSettings, TenantTemplatePurchase

invoice_store_bp = Blueprint('invoice_store', __name__)

@invoice_store_bp.route('/admin/invoice-templates', methods=['GET'])
@login_required
def store_home():
    # Only tenant admins or owners can access but let's assume current_user is valid
    # Check if templates need to be seeded
    if InvoiceTemplate.query.count() == 0:
        seed_templates()

    # In a multi-tenant system, we check their active template
    settings = TenantTemplateSettings.query.filter_by(tenant_id=current_user.id).first()
    active_id = settings.active_template_id if settings else None
    
    # Get all templates
    templates = InvoiceTemplate.query.order_by(InvoiceTemplate.price.asc(), InvoiceTemplate.id.asc()).all()
    
    # Get purchased templates for this user
    purchases = TenantTemplatePurchase.query.filter_by(tenant_id=current_user.id).all()
    purchased_ids = {p.template_id: p.status for p in purchases} # status: 'pending', 'approved'

def seed_templates():
    default_templates = [
        {'name': 'الأساسي (Basic)', 'description': 'قالب بسيط ونظيف ومجاني.', 'file_path': 'basic', 'is_premium': False, 'price': 0, 'preview_image': 'basic_preview.png'},
        {'name': 'الكلاسيكي (Classic)', 'description': 'أبيض وأسود، مناسب للطباعة السريعة.', 'file_path': 'classic', 'is_premium': False, 'price': 0, 'preview_image': 'classic_preview.png'},
        {'name': 'الحديث المظلم (Dark)', 'description': 'قالب احترافي داكن للعلامات العصرية.', 'file_path': 'modern_dark', 'is_premium': True, 'price': 5000, 'preview_image': 'dark_preview.png'},
        {'name': 'الأنيق (Elegant)', 'description': 'خطوط Serif وحواف رقيقة، مناسب للأزياء.', 'file_path': 'elegant', 'is_premium': True, 'price': 7000, 'preview_image': 'elegant_preview.png'},
        {'name': 'الحراري (Thermal 80mm)', 'description': 'مخصص لطابعات الريسيت الحرارية.', 'file_path': 'thermal', 'is_premium': True, 'price': 3000, 'preview_image': 'thermal_preview.png'},
        {'name': 'الشركات (Corporate)', 'description': 'شكل رسمي أزرق، مثالي للتعامل B2B.', 'file_path': 'corporate', 'is_premium': True, 'price': 8000, 'preview_image': 'corporate_preview.png'},
        {'name': 'إبداعي (Creative)', 'description': 'ألوان نابضة بالحياة وتصميم غير متناظر.', 'file_path': 'creative', 'is_premium': True, 'price': 6000, 'preview_image': 'creative_preview.png'},
        {'name': 'المتجر الإلكتروني', 'description': 'يعرض شروط الاسترجاع بشكل واضح وبارز.', 'file_path': 'ecommerce', 'is_premium': True, 'price': 5000, 'preview_image': 'ecommerce_preview.png'},
        {'name': 'الخط العربي الأصيل', 'description': 'زخرفة إسلامية وخط عربي أصيل.', 'file_path': 'arabic', 'is_premium': True, 'price': 10000, 'preview_image': 'arabic_preview.png'},
        {'name': 'الفاخر (Luxury Gold)', 'description': 'ذهبي وأسود، فخامة مطلقة للعطور والمجوهرات.', 'file_path': 'luxury', 'is_premium': True, 'price': 15000, 'preview_image': 'luxury_preview.png'},
    ]
    for t in default_templates:
        tmpl = InvoiceTemplate(
            name=t['name'],
            description=t['description'],
            file_path=t['file_path'],
            is_premium=t['is_premium'],
            price=t['price'],
            preview_image=t['preview_image']
        )
        db.session.add(tmpl)
    db.session.commit()
    
    return render_template('invoice_templates_store.html', 
                          templates=templates, 
                          active_id=active_id, 
                          purchased_ids=purchased_ids)

@invoice_store_bp.route('/admin/invoice-templates/buy/<int:template_id>', methods=['POST'])
@login_required
def buy_template(template_id):
    template = InvoiceTemplate.query.get_or_404(template_id)
    
    # Check if already purchased
    existing = TenantTemplatePurchase.query.filter_by(tenant_id=current_user.id, template_id=template_id).first()
    if existing:
        return jsonify({'success': False, 'message': 'لقد قمت بطلب هذا القالب مسبقاً.'}), 400
        
    # If free, activate directly
    if not template.is_premium or template.price == 0:
        settings = TenantTemplateSettings.query.filter_by(tenant_id=current_user.id).first()
        if not settings:
            settings = TenantTemplateSettings(tenant_id=current_user.id)
            db.session.add(settings)
        settings.active_template_id = template_id
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم تفعيل القالب بنجاح!', 'free': True})
        
    # If paid, process manual Zain Cash transfer
    ref_number = request.form.get('reference_number')
    if not ref_number:
        return jsonify({'success': False, 'message': 'يرجى إدخال رقم الحوالة.'}), 400
        
    # In a real app we'd handle file uploads for 'receipt_image' here
    # receipt = request.files.get('receipt_image')
    
    purchase = TenantTemplatePurchase(
        tenant_id=current_user.id,
        template_id=template_id,
        amount_paid=template.price,
        status='pending',
        reference_number=ref_number
    )
    
    db.session.add(purchase)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'تم إرسال طلب الشراء. سيتم تفعيل القالب بعد مراجعة الحوالة من قبل الإدارة.', 'free': False})

@invoice_store_bp.route('/admin/invoice-templates/activate/<int:template_id>', methods=['POST'])
@login_required
def activate_template(template_id):
    template = InvoiceTemplate.query.get_or_404(template_id)
    
    if template.is_premium:
        # Verify purchase
        purchase = TenantTemplatePurchase.query.filter_by(tenant_id=current_user.id, template_id=template_id, status='approved').first()
        if not purchase:
            return jsonify({'success': False, 'message': 'يجب شراء القالب أو انتظار موافقة الإدارة أولاً.'}), 403
            
    # Activate
    settings = TenantTemplateSettings.query.filter_by(tenant_id=current_user.id).first()
    if not settings:
        settings = TenantTemplateSettings(tenant_id=current_user.id)
        db.session.add(settings)
        
    settings.active_template_id = template_id
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'تم تفعيل القالب بنجاح!'})

@invoice_store_bp.route('/superadmin/invoice-purchases', methods=['GET'])
@login_required
def manage_purchases():
    # In a real system, verify if current_user is Super Admin
    if current_user.role != 'admin':
        flash('ليس لديك صلاحية لدخول هذه الصفحة', 'danger')
        return redirect(url_for('index.home'))
        
    purchases = TenantTemplatePurchase.query.order_by(TenantTemplatePurchase.created_at.desc()).all()
    # Assuming we need to fetch user names
    from models.employee import Employee
    for p in purchases:
        p.user = Employee.query.get(p.tenant_id)
        p.template = InvoiceTemplate.query.get(p.template_id)
        
    return render_template('manage_template_purchases.html', purchases=purchases)

@invoice_store_bp.route('/superadmin/invoice-purchases/approve/<int:purchase_id>', methods=['POST'])
@login_required
def approve_purchase(purchase_id):
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
    purchase = TenantTemplatePurchase.query.get_or_404(purchase_id)
    purchase.status = 'approved'
    db.session.commit()
    return jsonify({'success': True, 'message': 'تمت الموافقة على الشراء وتفعيل القالب للتاجر.'})

@invoice_store_bp.route('/superadmin/invoice-purchases/reject/<int:purchase_id>', methods=['POST'])
@login_required
def reject_purchase(purchase_id):
    if current_user.role != 'admin':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
    purchase = TenantTemplatePurchase.query.get_or_404(purchase_id)
    purchase.status = 'rejected'
    db.session.commit()
    return jsonify({'success': True, 'message': 'تم رفض طلب الشراء.'})
