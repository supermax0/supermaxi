from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session, flash
from extensions import db
from utils.branch_scope import is_general_admin, resolve_write_branch_id
from utils.branch_mode import independent_branches_enabled
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload
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

NON_CASH_MARKERS = ("مخزون افتتاحي", "تسوية جرد", "غير نقدي")
AUTOMATED_WITHDRAW_MARKERS = (
    "مصروف:",
    "صندوق -",
    "مخزون افتتاحي",
    "تسوية جرد",
    "غير نقدي",
    "شراء نقدي",
    "دفعة شراء",
    "تحويل →",
    "تحويل ←",
)
AUTOMATED_DEPOSIT_MARKERS = (
    "إلغاء مصروف",
    "صندوق -",
    "مخزون افتتاحي",
    "تسوية جرد",
    "غير نقدي",
    "تحويل →",
    "تحويل ←",
)
TX_PAGE_SIZE_OPTIONS = (25, 50, 100)


def _note_excludes_markers(column, markers):
    """SQL filter: note is empty or does not contain any of the markers."""
    return and_(*[
        or_(column.is_(None), ~column.contains(marker))
        for marker in markers
    ])


def _financial_transactions_query():
    """Base query for cash/financial movements shown on the accounts page."""
    query = AccountTransaction.query
    for marker in NON_CASH_MARKERS:
        query = query.filter(
            or_(AccountTransaction.note.is_(None), ~AccountTransaction.note.contains(marker))
        )
    return query


def _sum_owner_deposits() -> int:
    total = (
        _financial_transactions_query()
        .filter(
            AccountTransaction.type == "deposit",
            _note_excludes_markers(AccountTransaction.note, AUTOMATED_DEPOSIT_MARKERS),
        )
        .with_entities(func.coalesce(func.sum(AccountTransaction.amount), 0))
        .scalar()
    )
    return int(total or 0)


def _sum_owner_withdrawals() -> int:
    total = (
        _financial_transactions_query()
        .filter(
            AccountTransaction.type == "withdraw",
            _note_excludes_markers(AccountTransaction.note, AUTOMATED_WITHDRAW_MARKERS),
        )
        .with_entities(func.coalesce(func.sum(AccountTransaction.amount), 0))
        .scalar()
    )
    return int(total or 0)


def _paginate_financial_transactions(page: int, per_page: int):
    base_query = _financial_transactions_query()
    total = base_query.count()
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(max(1, page), pages)
    rows = (
        base_query.options(joinedload(AccountTransaction.treasury_account))
        .order_by(AccountTransaction.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return rows, {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev_num": page - 1,
        "next_num": page + 1,
    }


def _visible_cash_balance(treasury_balances) -> int:
    """Sum cash accounts from the same already-scoped rows shown on the page."""
    return sum(
        int(item["balance"] or 0)
        for item in treasury_balances
        if item["account"].is_cash
    )


@accounts_bp.before_request
def _ensure_accounts_schema():
    ensure_treasury_schema()
    try:
        from utils.payroll_schema import ensure_payroll_schema

        ensure_payroll_schema()
    except Exception:
        pass

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
        branch_id = resolve_write_branch_id(request.form)
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
            branch_id=branch_id,
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

    try:
        tx_page = int(request.args.get("page") or 1)
    except (TypeError, ValueError):
        tx_page = 1
    try:
        tx_per_page = int(request.args.get("per_page") or TX_PAGE_SIZE_OPTIONS[0])
    except (TypeError, ValueError):
        tx_per_page = TX_PAGE_SIZE_OPTIONS[0]
    if tx_per_page not in TX_PAGE_SIZE_OPTIONS:
        tx_per_page = TX_PAGE_SIZE_OPTIONS[0]

    transactions_to_display, tx_pagination = _paginate_financial_transactions(
        tx_page, tx_per_page
    )

    # ==========================
    # تصحيح محاسبي: اعتماد الصندوق كمصدر وحيد للرصيد النقدي
    # السبب المحاسبي:
    # - الصندوق (Cash) هو المصدر الوحيد الموثوق للرصيد النقدي
    # - صفحة الحسابات تُستخدم فقط لعرض الأرباح/الإيرادات/رأس المال
    # - لا تقوم صفحة الحسابات بحساب الرصيد النقدي (يُحسب من الصندوق فقط)
    # ==========================
    # حساب إيداعات وسحوبات رأس المال فقط (استبعاد المصاريف والحركات الآلية)
    total_deposit = _sum_owner_deposits()
    total_withdraw = _sum_owner_withdrawals()

    # ==========================
    # الرصيد النقدي يُحسب من الصندوق فقط (Cash Transactions)
    # استخدام حساب الصندوق كمصدر وحيد - منع الازدواجية
    # ==========================
    # يُحسب بعد تحميل حسابات الخزينة المرئية حتى يستخدم نفس نطاق الفرع
    # الذي تستخدمه بطاقات الصناديق والبنوك أدناه.
    balance = 0

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
    if not independent_branches_enabled():
        # Aggregate legacy per-branch treasury rows into one logical shared
        # account for display and reports. No historical row is deleted.
        grouped = {}
        for item in treasury_balances:
            account = item["account"]
            key = ((account.account_type or "bank").strip().lower(), (account.name or "").strip().casefold())
            current = grouped.get(key)
            if current is None:
                grouped[key] = {"account": account, "balance": int(item["balance"] or 0)}
            else:
                current["balance"] += int(item["balance"] or 0)
        treasury_balances = list(grouped.values())
        treasury_accounts = [item["account"] for item in treasury_balances]
    # في عرض «كل الفروع» نجمع صناديق الفروع كلها، وفي عرض فرع واحد
    # تحتوي القائمة تلقائياً على حسابات ذلك الفرع فقط.
    balance = _visible_cash_balance(treasury_balances)
    total_liquidity = calculate_total_liquidity()

    from models.branch import Branch

    visible_account_branch_ids = {
        int(account.branch_id)
        for account in treasury_accounts
        if account.branch_id
    }
    visible_account_branch_names = {
        int(branch.id): branch.name
        for branch in (
            Branch.query.execution_options(skip_branch_scope=True)
            .filter(Branch.id.in_(visible_account_branch_ids or [-1]))
            .all()
        )
    }
    for item in treasury_balances:
        item["branch_name"] = visible_account_branch_names.get(
            int(item["account"].branch_id or 0),
            "فرع غير محدد",
        )
    treasury_show_branch_names = independent_branches_enabled() and len(visible_account_branch_ids) > 1
    treasury_form_choices = treasury_choices_for_form()

    transfer_accounts = treasury_accounts
    transfer_branch_names = {}
    if is_general_admin():
        from utils.treasury_helpers import get_default_cash_account

        active_branches = (
            Branch.query.execution_options(skip_branch_scope=True)
            .filter_by(is_active=True)
            .order_by(Branch.name.asc())
            .all()
        )
        for branch in active_branches:
            get_default_cash_account(branch.id)
        transfer_branch_names = {int(branch.id): branch.name for branch in active_branches}
        transfer_accounts = (
            TreasuryAccount.query.execution_options(skip_branch_scope=True)
            .filter_by(is_active=True)
            .order_by(
                TreasuryAccount.branch_id.asc(),
                TreasuryAccount.account_type.asc(),
                TreasuryAccount.is_default.desc(),
                TreasuryAccount.name.asc(),
            )
            .all()
        )
    else:
        try:
            from flask import g

            if getattr(g, "branch", None) is not None:
                transfer_branch_names[int(g.branch.id)] = g.branch.name
        except Exception:
            pass

    treasury_transfer_choices = [
        {
            "id": account.id,
            "name": account.name,
            "account_type": account.account_type,
            "is_cash": account.is_cash,
            "branch_id": account.branch_id,
            "branch_name": transfer_branch_names.get(int(account.branch_id or 0), "فرع غير محدد"),
        }
        for account in transfer_accounts
    ]
    treasury_transfer_source_choices = sorted(
        treasury_transfer_choices,
        key=lambda item: (
            not item["is_cash"],
            item["branch_name"],
            item["name"],
        ),
    )
    treasury_transfer_destination_choices = sorted(
        treasury_transfer_choices,
        key=lambda item: (
            item["is_cash"],
            item["branch_name"],
            item["name"],
        ),
    )

    if not independent_branches_enabled():
        # Shared mode has one logical treasury; do not expose per-branch
        # duplicate transfer choices from legacy branch rows.
        treasury_transfer_choices = [
            {
                "id": account.id,
                "name": account.name,
                "account_type": account.account_type,
                "is_cash": account.is_cash,
                "branch_id": account.branch_id,
                "branch_name": "مشترك",
            }
            for account in treasury_form_choices
        ]
        treasury_transfer_source_choices = sorted(treasury_transfer_choices, key=lambda item: (not item["is_cash"], item["name"]))
        treasury_transfer_destination_choices = sorted(treasury_transfer_choices, key=lambda item: (item["is_cash"], item["name"]))

    return render_template(
        "accounts.html",
        transactions=transactions_to_display,  # صفحة واحدة من سجل الحركات المالية
        tx_pagination=tx_pagination,
        tx_page_size_options=TX_PAGE_SIZE_OPTIONS,
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
        treasury_choices=treasury_form_choices,
        treasury_show_branch_names=treasury_show_branch_names,
        treasury_transfer_choices=treasury_transfer_choices,
        treasury_transfer_source_choices=treasury_transfer_source_choices,
        treasury_transfer_destination_choices=treasury_transfer_destination_choices,
        can_transfer_all_branches=is_general_admin(),
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
    branch_id = resolve_write_branch_id(request.form)
    tx = AccountTransaction(
        branch_id=branch_id,
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

    bank = TreasuryAccount(
        name=name,
        account_type="bank",
        is_default=False,
        is_active=True,
        branch_id=resolve_write_branch_id(request.form),
    )
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
        transfer = record_treasury_transfer(
            from_account_id,
            to_account_id,
            amount,
            note,
            allow_cross_branch=is_general_admin(),
        )
        from_account = TreasuryAccount.query.execution_options(skip_branch_scope=True).filter_by(
            id=from_account_id
        ).first()
        to_account = TreasuryAccount.query.execution_options(skip_branch_scope=True).filter_by(
            id=to_account_id
        ).first()
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
                    "from_branch_id": from_account.branch_id if from_account else None,
                    "to_branch_id": to_account.branch_id if to_account else None,
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
