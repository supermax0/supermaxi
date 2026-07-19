"""
صفحة الصندوق (Cash)
إدارة الرصيد النقدي الفعلي (Cash Balance)

هذه الصفحة هي المصدر الوحيد لمعرفة الكاش الحقيقي
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash
from sqlalchemy import or_
from extensions import db
from models.account_transaction import AccountTransaction
from models.employee import Employee
from utils.cash_calculations import (
    calculate_cash_balance,
    get_cash_movements,
    get_cash_summary
)
from utils.permission_checks import check_permission
from utils.activity_logger import log_activity
from utils.delivery_expense_service import restore_missing_delivery_fee_withdrawals
from utils.treasury_helpers import get_default_cash_account
from utils.treasury_calculations import (
    list_treasury_accounts,
    calculate_treasury_balance,
    calculate_total_liquidity,
    assert_sufficient_balance,
    InsufficientTreasuryBalance,
)
from utils.treasury_schema_guard import ensure_treasury_schema

cash_bp = Blueprint("cash", __name__, url_prefix="/cash")


def _inventory_non_cash_transaction_filter():
    return or_(
        AccountTransaction.note.like("%مخزون افتتاحي%"),
        AccountTransaction.note.like("%تسوية جرد%"),
        AccountTransaction.note.like("%غير نقدي%"),
    )


def _inventory_non_cash_transactions_query():
    return AccountTransaction.query.filter(_inventory_non_cash_transaction_filter())


# ======================================
# Cash Page (Main)
# ======================================
@cash_bp.route("/", methods=["GET", "POST"])
def cash():
    """الصفحة الرئيسية للصندوق"""
    # فحص الصلاحية
    if not check_permission("can_see_accounts"):
        return redirect("/pos"), 403

    ensure_treasury_schema()
    restored_delivery = restore_missing_delivery_fee_withdrawals()
    if restored_delivery["count"] > 0:
        flash(
            f"تم إرجاع {restored_delivery['count']} حركة أجور توصيل بقيمة {restored_delivery['total']:,} د.ع إلى الصندوق.",
            "success",
        )
    
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

        ensure_treasury_schema()
        cash_account = get_default_cash_account()
        tx_type = "deposit" if transaction_type == "cash_in" else "withdraw"
        if tx_type == "withdraw":
            try:
                assert_sufficient_balance(cash_account.id, amount)
            except InsufficientTreasuryBalance as exc:
                flash(str(exc), "error")
                return redirect(url_for("cash.cash"))
        
        # تسجيل الحركة في AccountTransaction
        # استخدام note للتمييز بأنها حركة كاش يدوية
        cash_note = f"صندوق - {reason}"
        if note:
            cash_note += f" - {note}"
        
        tx = AccountTransaction(
            type=tx_type,
            amount=amount,
            note=cash_note,
            treasury_account_id=cash_account.id,
        )
        
        db.session.add(tx)
        db.session.commit()
        try:
            log_activity(
                "create",
                "finance",
                f"حركة صندوق — {reason}: {amount}",
                entity_type="account_transaction",
                payload={"type": tx_type, "amount": amount, "note": cash_note},
            )
        except Exception:
            pass
        
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
    
    bank_balances = [
        {"account": acc, "balance": calculate_treasury_balance(acc.id)}
        for acc in list_treasury_accounts()
        if not acc.is_cash
    ]
    total_liquidity = calculate_total_liquidity()
    inventory_non_cash_count = _inventory_non_cash_transactions_query().count()

    return render_template(
        "cash.html",
        cash_balance=cash_balance,
        cash_summary=cash_summary,
        movements=recent_movements,
        bank_balances=bank_balances,
        total_liquidity=total_liquidity,
        inventory_non_cash_count=inventory_non_cash_count,
    )


@cash_bp.route("/cleanup-inventory-noncash", methods=["POST"])
def cleanup_inventory_noncash():
    """Remove legacy inventory valuation rows that were incorrectly saved as cash movements."""
    if not check_permission("can_see_accounts"):
        return redirect("/pos"), 403

    rows = _inventory_non_cash_transactions_query().all()
    count = len(rows)
    total = sum(int(row.amount or 0) for row in rows)
    for row in rows:
        db.session.delete(row)
    db.session.commit()

    try:
        log_activity(
            "delete",
            "finance",
            f"تنظيف حركات مخزون غير نقدية من الصندوق — {count} حركة",
            entity_type="account_transaction",
            payload={"count": count, "total": total},
        )
    except Exception:
        pass

    flash(f"تم حذف {count} حركة مخزون غير نقدية من سجل الصندوق.", "success")
    return redirect(url_for("cash.cash"))


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
