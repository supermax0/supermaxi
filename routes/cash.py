"""
صفحة الصندوق (Cash)
إدارة الرصيد النقدي الفعلي (Cash Balance)

هذه الصفحة هي المصدر الوحيد لمعرفة الكاش الحقيقي
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash
from extensions import db
from models.account_transaction import AccountTransaction
from models.employee import Employee
from utils.cash_calculations import (
    calculate_cash_balance,
    get_cash_movements,
    get_cash_summary
)

cash_bp = Blueprint("cash", __name__, url_prefix="/cash")

def check_permission(permission_name):
    """فحص الصلاحية"""
    if "user_id" not in session:
        return False
    employee = Employee.query.get(session["user_id"])
    if not employee or not employee.is_active:
        return False
    if employee.role == "admin":
        return True
    return getattr(employee, permission_name, False)


# ======================================
# Cash Page (Main)
# ======================================
@cash_bp.route("/", methods=["GET", "POST"])
def cash():
    """الصفحة الرئيسية للصندوق"""
    # فحص الصلاحية
    if not check_permission("can_see_accounts"):
        return redirect("/pos"), 403
    
    # ==========================
    # إضافة حركة نقدية يدوياً
    # ==========================
    if request.method == "POST" and request.form.get("form_type") == "cash_transaction":
        transaction_type = request.form.get("transaction_type")  # cash_in أو cash_out
        reason = request.form.get("reason", "").strip()
        amount = int(request.form.get("amount", 0))
        note = request.form.get("note", "").strip()
        
        if not reason:
            flash("⚠️ يجب إدخال سبب الحركة", "error")
            return redirect(url_for("cash.cash"))
        
        if amount <= 0:
            flash("⚠️ المبلغ يجب أن يكون أكبر من صفر", "error")
            return redirect(url_for("cash.cash"))
        
        # تسجيل الحركة في AccountTransaction
        # استخدام note للتمييز بأنها حركة كاش يدوية
        tx_type = "deposit" if transaction_type == "cash_in" else "withdraw"
        cash_note = f"صندوق - {reason}"
        if note:
            cash_note += f" - {note}"
        
        tx = AccountTransaction(
            type=tx_type,
            amount=amount,
            note=cash_note
        )
        
        db.session.add(tx)
        db.session.commit()
        
        flash(f"✅ تم تسجيل الحركة النقدية بنجاح - {reason}", "success")
        return redirect(url_for("cash.cash"))
    
    # ==========================
    # حساب الرصيد النقدي
    # ==========================
    cash_balance = calculate_cash_balance()
    cash_summary = get_cash_summary()
    cash_movements = get_cash_movements()
    
    # آخر 50 حركة للعرض
    recent_movements = cash_movements[-50:] if cash_movements else []
    
    return render_template(
        "cash.html",
        cash_balance=cash_balance,
        cash_summary=cash_summary,
        movements=recent_movements
    )


# ======================================
# Get Cash Movements (API)
# ======================================
@cash_bp.route("/api/movements")
def get_cash_movements_api():
    """API للحصول على حركات الكاش"""
    if not check_permission("can_see_accounts"):
        return jsonify({"error": "Unauthorized"}), 403
    
    movements = get_cash_movements()
    summary = get_cash_summary()
    
    return jsonify({
        "summary": summary,
        "movements": movements[-100:]  # آخر 100 حركة
    })
