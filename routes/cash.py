"""
صفحة الصندوق (Cash)
إدارة الرصيد النقدي الفعلي (Cash Balance)

هذه الصفحة هي المصدر الوحيد لمعرفة الكاش الحقيقي
"""

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash
from extensions import db
from models.account_transaction import AccountTransaction
from utils.cash_calculations import (
    calculate_cash_balance,
    get_cash_movements,
    get_cash_summary
)
from utils.permission_checks import check_permission
from utils.activity_logger import log_activity
from utils.treasury_helpers import get_default_cash_account
from utils.treasury_calculations import (
    list_treasury_accounts,
    calculate_treasury_balance,
    calculate_total_liquidity,
    get_treasury_movements,
    assert_sufficient_balance,
    InsufficientTreasuryBalance,
)
from utils.treasury_schema_guard import ensure_treasury_schema
from utils.branch_scope import resolve_write_branch_id

cash_bp = Blueprint("cash", __name__, url_prefix="/cash")


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
    
    # ==========================
    # إضافة حركة نقدية يدوياً
    # ==========================
    if request.method == "POST" and request.form.get("form_type") == "cash_transaction":
        branch_id = resolve_write_branch_id(request.form)
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
        cash_account = get_default_cash_account(branch_id)
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
            branch_id=branch_id,
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
    treasury_accounts = list_treasury_accounts()
    selected_account = None
    try:
        selected_id = int(request.args.get("treasury_account_id") or 0)
    except (TypeError, ValueError):
        selected_id = 0
    if selected_id:
        selected_account = next(
            (account for account in treasury_accounts if int(account.id) == selected_id),
            None,
        )

    if selected_account is not None:
        from modules.sales_returns.collections import undated_balance
        cash_movements = get_treasury_movements(selected_account.id)
        from utils.cash_movement_values import movement_amount
        cash_summary = {
            "total_in": sum(movement_amount(m) for m in cash_movements if m["type"] == "cash_in"),
            "total_out": sum(movement_amount(m) for m in cash_movements if m["type"] == "cash_out"),
            "current_balance": calculate_treasury_balance(selected_account.id),
            "movements_count": len(cash_movements),
            "undated_collection_balance": undated_balance(selected_account.id),
        }
    else:
        cash_summary = get_cash_summary()
        cash_movements = get_cash_movements()

    bank_balances = [
        {"account": acc, "balance": calculate_treasury_balance(acc.id)}
        for acc in treasury_accounts
        if not acc.is_cash
    ]
    total_liquidity = calculate_total_liquidity()

    return render_template(
        "cash.html",
        cash_balance=cash_balance,
        cash_summary=cash_summary,
        movements=cash_movements or [],
        bank_balances=bank_balances,
        total_liquidity=total_liquidity,
        selected_treasury_account=selected_account,
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
        "movements": movements or [],
    })
