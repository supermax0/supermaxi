from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session, flash
from extensions import db
from sqlalchemy import func, or_
from models.account_transaction import AccountTransaction
from models.invoice import Invoice
from models.order_item import OrderItem
from models.expense import Expense
from models.employee import Employee
from models.treasury_account import TreasuryAccount

# =======================
# Accounting Calculations (الحسابات المحاسبية الصحيحة)
# =======================
from utils.accounting_calculations import (
    calculate_total_revenue,      # المبيعات المحتسبة محاسبياً
    calculate_total_cogs,         # COGS للطلبات المحتسبة
    calculate_total_expenses,     # المصاريف
    calculate_net_profit           # صافي الربح (Accrual)
)
from utils.cash_calculations import _effective_paid_amount
from utils.permission_checks import check_permission
from utils.activity_logger import log_activity
from utils.treasury_helpers import resolve_treasury_account_id, treasury_choices_for_form
from utils.treasury_calculations import (
    calculate_treasury_balance,
    calculate_total_liquidity,
    record_treasury_transfer,
    InsufficientTreasuryBalance,
    list_treasury_accounts,
)
from utils.treasury_schema_guard import ensure_treasury_schema

accounts_bp = Blueprint("accounts", __name__, url_prefix="/accounts")

def _build_order_accounting_impact(limit=12):
    """Read-only impact cards for recent orders; it does not post accounting entries."""
    rows = []
    invoices = (
        db.session.query(
            Invoice.id,
            Invoice.customer_name,
            Invoice.created_at,
            Invoice.status,
            Invoice.payment_status,
            Invoice.total,
            Invoice.paid_amount,
        )
        .order_by(Invoice.created_at.desc())
        .limit(limit)
        .all()
    )
    invoice_ids = [invoice.id for invoice in invoices]
    cost_rows = {}

    if invoice_ids:
        from utils.order_item_costs import exclude_delivery_fee_items

        cost_rows = {
            row.invoice_id: {
                "stock_cost": int(row.stock_cost or 0),
                "items_count": int(row.items_count or 0),
            }
            for row in (
                db.session.query(
                    OrderItem.invoice_id,
                    func.sum(OrderItem.cost * OrderItem.quantity).label("stock_cost"),
                    func.sum(OrderItem.quantity).label("items_count"),
                )
                .filter(OrderItem.invoice_id.in_(invoice_ids), exclude_delivery_fee_items(OrderItem))
                .group_by(OrderItem.invoice_id)
                .all()
            )
        }

    for invoice in invoices:
        sale_value = int(invoice.total or 0)
        paid_amount = _effective_paid_amount(invoice)
        impact_cost = cost_rows.get(invoice.id, {})
        total_cost = impact_cost.get("stock_cost", 0)
        items_count = impact_cost.get("items_count", 0)

        rows.append({
            "invoice_id": invoice.id,
            "customer_name": invoice.customer_name,
            "created_at": invoice.created_at,
            "status": invoice.status,
            "payment_status": invoice.payment_status,
            "sale_value": sale_value,
            "paid_amount": paid_amount,
            "receivable_amount": max(sale_value - paid_amount, 0),
            "stock_cost": total_cost,
            "gross_profit": sale_value - total_cost,
            "items_count": items_count,
        })

    return rows


# ============================
# Accounts Page
# ============================
@accounts_bp.route("/", methods=["GET", "POST"])
def accounts():
    # فحص الصلاحية
    if not check_permission("can_see_accounts"):
        return redirect("/pos"), 403

    if request.method == "POST":
        ensure_treasury_schema()
        treasury_account_id = resolve_treasury_account_id(request.form.get("treasury_account_id"))
        tx_type = (request.form.get("type") or "").strip()
        if tx_type not in ("deposit", "withdraw"):
            flash("نوع الحركة غير صالح", "error")
            return redirect(url_for("accounts.accounts"))
        try:
            amount = int(request.form.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            flash("المبلغ يجب أن يكون أكبر من صفر", "error")
            return redirect(url_for("accounts.accounts"))
        note = (request.form.get("note") or "").strip()
        if not note:
            flash("يرجى كتابة سبب واضح للحركة المالية اليدوية", "error")
            return redirect(url_for("accounts.accounts"))
        if tx_type == "withdraw":
            try:
                from utils.treasury_calculations import assert_sufficient_balance

                assert_sufficient_balance(treasury_account_id, amount)
            except InsufficientTreasuryBalance as exc:
                flash(str(exc), "error")
                return redirect(url_for("accounts.accounts"))
        tx = AccountTransaction(
            type=tx_type,
            amount=amount,
            note=f"حركة يدوية - {note}",
            treasury_account_id=treasury_account_id,
        )
        db.session.add(tx)
        db.session.commit()
        try:
            log_activity(
                "create",
                "finance",
                f"حركة حساب — {tx.type}: {tx.amount}",
                entity_type="account_transaction",
                payload={"type": tx.type, "amount": tx.amount, "note": tx.note},
            )
        except Exception:
            pass
        return redirect(url_for("accounts.accounts"))

    transactions = AccountTransaction.query.order_by(
        AccountTransaction.created_at.desc()
    ).all()

    # ==========================
    # تصحيح محاسبي: استبعاد حركات المخزون الافتتاحي من الحسابات المالية
    # السبب المحاسبي:
    # - المخزون الافتتاحي يُعتبر قيمة مخزون فقط (Asset)
    # - لا يؤثر على الرصيد المالي (Cash/Balance)
    # - يجب استبعاده من حساب الرصيد المالي
    # ==========================
    # فلترة الحركات المالية: استبعاد قيود المخزون/القيود غير النقدية من عرض النقد ورأس المال.
    non_cash_markers = ("مخزون افتتاحي", "تسوية جرد", "غير نقدي")
    financial_transactions = [
        t for t in transactions 
        if not (t.note and any(marker in t.note for marker in non_cash_markers))
    ]
    
    # عرض الحركات المالية فقط (بدون حركات المخزون الافتتاحي)
    transactions_to_display = financial_transactions

    # ==========================
    # تصحيح محاسبي: اعتماد الصندوق كمصدر وحيد للرصيد النقدي
    # السبب المحاسبي:
    # - الصندوق (Cash) هو المصدر الوحيد الموثوق للرصيد النقدي
    # - صفحة الحسابات تُستخدم فقط لعرض الأرباح/الإيرادات/رأس المال
    # - لا تقوم صفحة الحسابات بحساب الرصيد النقدي (يُحسب من الصندوق فقط)
    # ==========================
    # حساب إيداعات وسحوبات رأس المال فقط (استبعاد المصاريف والحركات الآلية)
    total_deposit = sum(
        t.amount for t in financial_transactions if t.is_owner_deposit()
    )

    total_withdraw = sum(
        t.amount for t in financial_transactions if t.is_owner_withdrawal()
    )

    # ==========================
    # الرصيد النقدي يُحسب من الصندوق فقط (Cash Transactions)
    # استخدام حساب الصندوق كمصدر وحيد - منع الازدواجية
    # ==========================
    from utils.cash_calculations import calculate_cash_balance
    balance = calculate_cash_balance()  # الرصيد من الصندوق - المصدر الوحيد الموثوق

    # ===============================
    # حساب صافي الأرباح على أساس الطلبات المسجلة
    # الصيغة المحاسبية:
    # صافي الربح = المبيعات المحتسبة - COGS - المصاريف
    #
    # ملاحظة مهمة:
    # - الربح يظهر عند إنشاء الطلب "تم الطلب".
    # - التحصيل اللاحق يؤثر على الصندوق فقط، ولا يعيد احتساب ربح الطلب.
    # ===============================

    booked_sales = calculate_total_revenue()
    total_cost = calculate_total_cogs()
    
    # المصاريف
    # السبب المحاسبي: المصاريف حساب مستقل، لا تؤثر على المخزون أو رأس المال مباشرة
    total_expenses = calculate_total_expenses()
    
    # حساب الربح قبل المصاريف (Gross Profit)
    # السبب المحاسبي: الربح الإجمالي = الإيرادات - COGS (قبل المصاريف)
    gross_profit = booked_sales - total_cost
    
    # صافي الربح (Net Profit)
    # الصيغة المحاسبية الصحيحة: الربح = الإيرادات - COGS - المصاريف
    # ==========================
    # تصحيح محاسبي: الربح يُحسب فقط من المبيعات # CRUCIAL ACCOUNTING FIX
    # السبب المحاسبي:
    # - الربح = Sales - COGS (يُحسب فقط عند البيع)
    # - لا يُحسب من الحركات النقدية (قبض / صرف / إيداع)
    # - لا يُضاف تلقائياً إلى رأس المال (يُضاف فقط في نهاية الفترة المالية)
    # - الحركات النقدية تُستخدم لتحديث الصندوق فقط، لا تؤثر على الأرباح
    # ==========================
    net_profit = calculate_net_profit()
    
    # ==========================
    # تم إزالة منطق إضافة الربح تلقائياً إلى رأس المال
    # السبب: الربح يُحسب فقط من المبيعات، ولا يجب إعادة حسابه من الحركات النقدية
    # ==========================

    # حساب نسب التحذير
    expense_ratio = (total_expenses / gross_profit * 100) if gross_profit > 0 else 0
    profit_ratio = (net_profit / booked_sales * 100) if booked_sales > 0 else 0
    
    # تحديد نوع التنبيه
    alert_type = None
    alert_message = None
    
    if net_profit < 0:
        # خسارة - المصاريف أعلى من الربح
        alert_type = "danger"
        alert_message = f"⚠️ تحذير: خسارة! المصاريف ({total_expenses:,} د.ع) أعلى من الربح ({gross_profit:,} د.ع)"
    elif expense_ratio >= 80:
        # المصاريف مقاربة للربح (80% أو أكثر)
        alert_type = "warning"
        alert_message = f"⚠️ تحذير: المصاريف ({total_expenses:,} د.ع) تمثل {expense_ratio:.1f}% من الربح ({gross_profit:,} د.ع) - قريبة جداً من الخسارة!"
    elif profit_ratio < 20 and booked_sales > 0:
        # الربح قليل (أقل من 20% من المبيعات)
        alert_type = "info"
        alert_message = f"💡 ملاحظة: الربح الصافي ({net_profit:,} د.ع) يمثل {profit_ratio:.1f}% فقط من المبيعات ({booked_sales:,} د.ع) - ربح قليل"

    ensure_treasury_schema()
    treasury_accounts = list_treasury_accounts()
    treasury_balances = [
        {
            "account": acc,
            "balance": calculate_treasury_balance(acc.id),
        }
        for acc in treasury_accounts
    ]
    total_liquidity = calculate_total_liquidity()

    return render_template(
        "accounts.html",
        transactions=transactions_to_display,  # عرض الحركات المالية فقط (بدون المخزون الافتتاحي)
        total_deposit=total_deposit,
        total_withdraw=total_withdraw,
        balance=balance,
        net_profit=net_profit,
        total_expenses=total_expenses,
        gross_profit=gross_profit,
        booked_sales=booked_sales,
        order_accounting_impact=_build_order_accounting_impact(),
        alert_type=alert_type,
        alert_message=alert_message,
        treasury_accounts=treasury_accounts,
        treasury_balances=treasury_balances,
        total_liquidity=total_liquidity,
        treasury_choices=treasury_choices_for_form(),
    )

# ============================
# Add Capital from Profit
# ============================
@accounts_bp.route("/add-capital-from-profit", methods=["POST"])
def add_capital_from_profit():
    """
    إضافة الربح لرأس المال (إغلاق الفترة المالية)
    
    ملاحظة محاسبية مهمة:
    - الربح لا يُضاف لرأس المال مباشرة إلا في نهاية الفترة المالية
    - هذه الوظيفة تُستخدم لإغلاق الفترة وإضافة الربح لرأس المال
    """
    # حساب صافي الأرباح (الصيغة المحاسبية: الإيرادات - COGS - المصاريف)
    # ملاحظة مهمة: هذا "قيد إغلاق فترة" وليس حركة كاش فعلية
    net_profit = calculate_net_profit()
    
    if net_profit <= 0:
        return jsonify({
            "success": False,
            "error": "لا يوجد ربح صافي لإضافته إلى رأس المال"
        }), 400
    
    # تسجيل حركة "غير نقدية" للمتابعة فقط (لا تؤثر على الصندوق)
    # يتم استبعادها من حساب الكاش عبر فلتر "غير نقدي" في cash_calculations
    tx = AccountTransaction(
        type="deposit",
        amount=int(net_profit),
        note=f"إغلاق فترة (غير نقدي) - زيادة رأس المال من صافي الأرباح ({net_profit:,} د.ع)"
    )
    db.session.add(tx)
    db.session.commit()
    try:
        log_activity(
            "create",
            "finance",
            f"إغلاق فترة — إضافة {net_profit} إلى رأس المال",
            entity_type="account_transaction",
            payload={"amount": int(net_profit), "note": tx.note},
        )
    except Exception:
        pass
    
    return jsonify({
        "success": True,
        "message": f"تم إضافة {net_profit:,} د.ع إلى رأس المال من صافي الأرباح",
        "amount": int(net_profit)
    })


@accounts_bp.route("/add-bank", methods=["POST"])
def add_bank():
    if not check_permission("can_see_accounts"):
        return redirect("/pos"), 403

    ensure_treasury_schema()
    name = (request.form.get("bank_name") or "").strip()
    if not name:
        flash("يرجى إدخال اسم البنك", "error")
        return redirect(url_for("accounts.accounts"))

    existing = TreasuryAccount.query.filter(
        TreasuryAccount.account_type == "bank",
        func.lower(TreasuryAccount.name) == name.lower(),
    ).first()
    if existing:
        flash("يوجد بنك بنفس الاسم مسبقاً", "error")
        return redirect(url_for("accounts.accounts"))

    bank = TreasuryAccount(name=name, account_type="bank", is_default=False, is_active=True)
    db.session.add(bank)
    db.session.commit()
    try:
        log_activity(
            "create",
            "finance",
            f"إضافة بنك — {name}",
            entity_type="treasury_account",
            payload={"name": name},
        )
    except Exception:
        pass
    flash(f"تم إضافة البنك: {name}", "success")
    return redirect(url_for("accounts.accounts"))


@accounts_bp.route("/transfer", methods=["POST"])
def treasury_transfer():
    if not check_permission("can_see_accounts"):
        return redirect("/pos"), 403

    ensure_treasury_schema()
    try:
        from_account_id = int(request.form.get("from_account_id") or 0)
        to_account_id = int(request.form.get("to_account_id") or 0)
        amount = int(request.form.get("amount") or 0)
    except (TypeError, ValueError):
        flash("بيانات التحويل غير صالحة", "error")
        return redirect(url_for("accounts.accounts"))

    note = (request.form.get("note") or "").strip() or None
    try:
        transfer = record_treasury_transfer(from_account_id, to_account_id, amount, note)
        try:
            log_activity(
                "create",
                "finance",
                f"تحويل {amount} من {transfer.from_account_id} إلى {transfer.to_account_id}",
                entity_type="treasury_transfer",
                payload={
                    "from_account_id": from_account_id,
                    "to_account_id": to_account_id,
                    "amount": amount,
                    "note": note,
                },
            )
        except Exception:
            pass
        flash("تم تنفيذ التحويل بنجاح", "success")
    except InsufficientTreasuryBalance as exc:
        flash(str(exc), "error")
    except ValueError as exc:
        flash(str(exc), "error")

    return redirect(url_for("accounts.accounts"))
