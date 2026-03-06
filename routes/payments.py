import os
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash, current_app, g
from extensions import db
from models.core.payment_request import PaymentRequest

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def _zaincash_transfer_phone():
    """رقم تحويل زين كاش من إعدادات السوبر أدمن (قاعدة Core)."""
    old_tenant = getattr(g, "tenant", None)
    g.tenant = None
    try:
        from models.core.global_setting import GlobalSetting
        return GlobalSetting.get_setting("ZAINCASH_TRANSFER_PHONE", "07734049148")
    except Exception:
        return "07734049148"
    finally:
        g.tenant = old_tenant


@payments_bp.route("/checkout", methods=["POST", "GET"])
def checkout():
    if request.method == "POST":
        data = request.form
        plan_key = data.get("plan_key", "basic")
        billing_period = data.get("billing", "monthly")
    else:
        plan_key = request.args.get("plan_key", "basic")
        billing_period = request.args.get("billing", "monthly")
        
    PRICES = {
        "basic": {"monthly": 25000, "yearly": 250000},
        "pro": {"monthly": 45000, "yearly": 450000},
        "enterprise": {"monthly": 90000, "yearly": 900000},
    }
    
    plan_data = PRICES.get(plan_key, PRICES["basic"])
    amount = plan_data["yearly"] if billing_period == "yearly" else plan_data["monthly"]
    zaincash_transfer_phone = _zaincash_transfer_phone()

    return render_template("zaincash_checkout.html", amount=amount, plan_key=plan_key, zaincash_transfer_phone=zaincash_transfer_phone)


@payments_bp.route("/zaincash-submit", methods=["POST"])
def zaincash_submit():
    # Because we are saving to Core DB, we must ensure g.tenant is None
    g.tenant = None
    
    amount = request.form.get("amount")
    tenant_name = request.form.get("tenant_name").strip().lower()
    owner_name = request.form.get("owner_name")
    phone = request.form.get("phone")
    email = request.form.get("email")
    zaincash_reference = request.form.get("zaincash_reference", "")
    
    if 'receipt_image' not in request.files:
        flash("الرجاء إرفاق صورة الإيصال")
        return redirect(url_for("payments.checkout"))
        
    file = request.files['receipt_image']
    if file.filename == '':
        flash("لم يتم اختيار صورة")
        return redirect(url_for("payments.checkout"))
        
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{tenant_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
        
        # Ensure upload folder exists
        upload_folder = os.path.join(current_app.root_path, "static", "uploads", "receipts")
        os.makedirs(upload_folder, exist_ok=True)
        
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)
        
        # Relative path for DB
        db_filepath = f"uploads/receipts/{filename}"
        
        new_request = PaymentRequest(
            tenant_name=tenant_name,
            owner_name=owner_name,
            phone=phone,
            email=email,
            amount=float(amount) if amount else 0.0,
            zaincash_reference=zaincash_reference,
            receipt_image_path=db_filepath,
            status="pending"
        )
        
        db.session.add(new_request)
        db.session.commit()
        
        return render_template("payment_success.html", datetime=datetime)
    else:
        flash("نوع الملف غير مسموح. يرجى رفع صورة بصيغة JPG, PNG أو PDF.")
        return redirect(url_for("payments.checkout"))

@payments_bp.route("/success")
def success():
    return render_template("payment_success.html", datetime=datetime)
