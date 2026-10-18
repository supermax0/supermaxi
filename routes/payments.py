import os
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash, current_app, g
from extensions import db
from models.core.payment_request import PaymentRequest

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
PLAN_PRICES = {
    "basic": {"monthly": 25000, "yearly": 250000},
    "pro": {"monthly": 45000, "yearly": 450000},
    "enterprise": {"monthly": 90000, "yearly": 900000},
}

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

    plan_key = plan_key if plan_key in PLAN_PRICES else "basic"
    billing_period = "yearly" if billing_period == "yearly" else "monthly"
    amount = PLAN_PRICES[plan_key][billing_period]
    zaincash_transfer_phone = _zaincash_transfer_phone()
    checkout_prefill = {
        "tenant_name": (session.get("tenant_slug") or "").strip(),
        "owner_name": (session.get("name") or "").strip(),
        "phone": "",
        "email": "",
    }
    if checkout_prefill["tenant_name"]:
        try:
            from utils.tenant_registration import load_tenant_registration

            registration = load_tenant_registration(checkout_prefill["tenant_name"]) or {}
            checkout_prefill["owner_name"] = (registration.get("contact_name") or checkout_prefill["owner_name"]).strip()
            checkout_prefill["phone"] = (registration.get("phone") or "").strip()
            checkout_prefill["email"] = (registration.get("email") or "").strip()
        except Exception:
            current_app.logger.exception("failed to prefill checkout for %s", checkout_prefill["tenant_name"])

    return render_template(
        "zaincash_checkout.html",
        amount=amount,
        plan_key=plan_key,
        billing=billing_period,
        zaincash_transfer_phone=zaincash_transfer_phone,
        checkout_prefill=checkout_prefill,
    )


@payments_bp.route("/zaincash-submit", methods=["POST"])
def zaincash_submit():
    # Because we are saving to Core DB, we must ensure g.tenant is None
    g.tenant = None
    
    plan_key = (request.form.get("plan_key") or "basic").strip()
    billing = (request.form.get("billing") or "monthly").strip()
    plan_key = plan_key if plan_key in PLAN_PRICES else "basic"
    billing = "yearly" if billing == "yearly" else "monthly"
    amount = PLAN_PRICES[plan_key][billing]
    tenant_name = (request.form.get("tenant_name") or "").strip().lower()
    owner_name = (request.form.get("owner_name") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip()
    zaincash_reference = request.form.get("zaincash_reference", "")

    def checkout_redirect():
        return redirect(url_for("payments.checkout", plan_key=plan_key, billing=billing))

    if not all((tenant_name, owner_name, phone, email)):
        flash("يرجى إكمال بيانات طلب التفعيل المطلوبة.")
        return checkout_redirect()
    
    if 'receipt_image' not in request.files:
        flash("الرجاء إرفاق صورة الإيصال")
        return checkout_redirect()
        
    file = request.files['receipt_image']
    if file.filename == '':
        flash("لم يتم اختيار صورة")
        return checkout_redirect()
        
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
            amount=float(amount),
            zaincash_reference=zaincash_reference,
            receipt_image_path=db_filepath,
            status="pending"
        )
        
        db.session.add(new_request)
        db.session.commit()
        
        return render_template("payment_success.html", datetime=datetime)
    else:
        flash("نوع الملف غير مسموح. يرجى رفع صورة بصيغة JPG, PNG أو PDF.")
        return checkout_redirect()

@payments_bp.route("/success")
def success():
    return render_template("payment_success.html", datetime=datetime)
