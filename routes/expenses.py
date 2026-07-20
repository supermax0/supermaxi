from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from extensions import db
from models.expense import Expense
from models.account_transaction import AccountTransaction
from datetime import datetime, timedelta
from utils.plan_guard import feature_required
from utils.permission_checks import check_permission
from utils.activity_logger import log_activity
from utils.expense_posting import build_expense_withdraw_note, expense_withdraw_marker
from utils.expense_queries import sum_posted_expenses
from utils.treasury_helpers import resolve_treasury_account_id, treasury_choices_for_form
from utils.treasury_calculations import assert_sufficient_balance, InsufficientTreasuryBalance
from utils.treasury_schema_guard import ensure_treasury_schema
from utils.expense_categories import (
    get_expense_categories,
    add_expense_category,
    remove_expense_category,
    build_category_groups,
)

expenses_bp = Blueprint("expenses", __name__)


def _add_months(base_date, months):
    month = base_date.month - 1 + months
    year = base_date.year + month // 12
    month = month % 12 + 1
    month_days = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(base_date.day, month_days[month - 1])
    return base_date.replace(year=year, month=month, day=day)


def _next_recurring_date(base_date, step, unit, index):
    offset = max(0, int(step or 1)) * index
    if unit == "weeks":
        return base_date + timedelta(weeks=offset)
    if unit == "months":
        return _add_months(base_date, offset)
    if unit == "years":
        return _add_months(base_date, offset * 12)
    return base_date + timedelta(days=offset)


def _post_expense_to_treasury(expense, treasury_account_id=None):
    """خصم المصروف من الصندوق/البنك مرة واحدة."""
    account_id = treasury_account_id or expense.treasury_account_id
    account_id = resolve_treasury_account_id(account_id)
    assert_sufficient_balance(account_id, expense.amount)
    withdraw_tx = AccountTransaction(
        type="withdraw",
        amount=expense.amount,
        note=build_expense_withdraw_note(expense),
        treasury_account_id=account_id,
    )
    db.session.add(withdraw_tx)
    expense.treasury_account_id = account_id
    expense.cash_posted = True
    return withdraw_tx


def post_due_unposted_expenses():
    """خصم المصاريف المستحقة فقط (تاريخها اليوم أو أقدم) — لا تُخصم المجدولة المستقبلية."""
    ensure_treasury_schema()
    today = datetime.now().date()
    unposted = (
        Expense.query.filter(
            Expense.cash_posted.is_(False),
            Expense.expense_date.isnot(None),
            Expense.expense_date <= today,
        )
        .order_by(Expense.expense_date.asc(), Expense.id.asc())
        .all()
    )
    posted = 0
    skipped = 0
    for expense in unposted:
        try:
            _post_expense_to_treasury(expense)
            posted += 1
        except InsufficientTreasuryBalance:
            skipped += 1
            continue
    if posted:
        db.session.commit()
    return posted, skipped


# توافق مع الاستدعاءات القديمة
def post_all_unposted_expenses():
    return post_due_unposted_expenses()


@expenses_bp.route("/", methods=["GET", "POST"])
@feature_required("expenses")
def expenses():
    # فحص الصلاحية
    if not check_permission("can_see_expenses"):
        return redirect("/pos"), 403

    ensure_treasury_schema()
    try:
        posted, skipped = post_due_unposted_expenses()
        if posted:
            flash(f"تم خصم {posted} مصروف مستحق من الصندوق.", "success")
        if skipped:
            flash(
                f"تعذر خصم {skipped} مصروف مستحق لعدم كفاية الرصيد — أعد المحاولة بعد تغذية الصندوق.",
                "error",
            )
    except Exception:
        db.session.rollback()

    if request.method == "POST":
        expense_amount = int(float(request.form["amount"]))
        treasury_account_id = resolve_treasury_account_id(request.form.get("treasury_account_id"))
        expense_title = request.form["title"]
        expense_category = request.form["category"]
        expense_note = request.form.get("note")
        expense_date = datetime.strptime(
            request.form["expense_date"], "%Y-%m-%d"
        ).date()
        repeat_enabled = request.form.get("repeat_enabled") == "1"
        repeat_interval = max(1, min(int(request.form.get("repeat_interval") or 1), 365))
        repeat_unit = (request.form.get("repeat_unit") or "months").strip()
        if repeat_unit not in {"days", "weeks", "months", "years"}:
            repeat_unit = "months"
        repeat_count = 1
        if repeat_enabled:
            repeat_count = max(1, min(int(request.form.get("repeat_count") or 1), 120))

        today = datetime.now().date()
        # خصم فوري فقط للتواريخ المستحقة (اليوم أو أقدم) — المجدولة لاحقاً تبقى بدون سحب
        due_count = 0
        for i in range(repeat_count):
            current_date = _next_recurring_date(expense_date, repeat_interval, repeat_unit, i)
            if current_date <= today:
                due_count += 1
        amount_to_withdraw = expense_amount * due_count
        if amount_to_withdraw > 0:
            try:
                assert_sufficient_balance(treasury_account_id, amount_to_withdraw)
            except InsufficientTreasuryBalance as exc:
                flash(str(exc), "error")
                return redirect(url_for("expenses.expenses"))

        try:
            for i in range(repeat_count):
                current_date = _next_recurring_date(expense_date, repeat_interval, repeat_unit, i)
                repeat_suffix = f" | تكرار {i + 1}/{repeat_count}" if repeat_count > 1 else ""
                is_due = current_date <= today
                expense = Expense(
                    title=expense_title,
                    category=expense_category,
                    amount=expense_amount,
                    note=(expense_note or "") + repeat_suffix,
                    expense_date=current_date,
                    treasury_account_id=treasury_account_id,
                    cash_posted=False,
                )
                db.session.add(expense)
                db.session.flush()
                if is_due:
                    _post_expense_to_treasury(expense, treasury_account_id)

            db.session.commit()
        except InsufficientTreasuryBalance as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return redirect(url_for("expenses.expenses"))

        try:
            log_activity(
                "create",
                "finance",
                f"مصروف: {expense_title} — {expense_amount}",
                entity_type="expense",
                payload={
                    "title": expense_title,
                    "category": expense_category,
                    "amount": expense_amount,
                    "repeat_count": repeat_count,
                    "posted_now": due_count,
                },
            )
        except Exception:
            pass

        scheduled = repeat_count - due_count
        if repeat_count > 1:
            msg = f"تم تسجيل {repeat_count} مصروف"
            if due_count:
                msg += f" وخصم {amount_to_withdraw:,} من الصندوق ({due_count} مستحق)"
            if scheduled:
                msg += f" — {scheduled} مجدول بدون خصم حتى يحين موعده"
            flash(msg + ".", "success")
        elif due_count:
            flash("تم تسجيل المصروف وخصمه من الصندوق.", "success")
        else:
            flash("تم جدولة المصروف بدون خصم من الصندوق حتى يحين موعده.", "success")
        return redirect(url_for("expenses.expenses"))

    expenses = Expense.query.order_by(Expense.expense_date.desc()).all()
    today = datetime.now().date()
    first_day_of_month = today.replace(day=1)

    # إجمالي المصاريف المخصومة من الصندوق
    total = sum_posted_expenses()
    month_total = sum_posted_expenses(first_day_of_month, today)
    today_total = sum_posted_expenses(today, today)

    # اسم الشهر بالعربي
    month_names = {
        1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل",
        5: "مايو", 6: "يونيو", 7: "يوليو", 8: "أغسطس",
        9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر"
    }
    current_month_name = month_names.get(today.month, "")

    # تاريخ اليوم بصيغة YYYY-MM-DD للعرض
    today_date = today.strftime("%Y-%m-%d")

    # التاريخ الافتراضي للنموذج (اليوم)
    default_date = today.strftime("%Y-%m-%d")

    return render_template(
        "expenses.html",
        expenses=expenses,
        category_groups=build_category_groups(expenses),
        expense_categories=get_expense_categories(),
        total=total,
        month_total=month_total,
        today_total=today_total,
        current_month_name=current_month_name,
        today_date=today_date,
        default_date=default_date,
        treasury_choices=treasury_choices_for_form(),
    )


@expenses_bp.route("/categories/add", methods=["POST"])
@feature_required("expenses")
def add_expense_category_route():
    if not check_permission("can_see_expenses"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or request.form.get("name") or "").strip()
    icon = (data.get("icon") or request.form.get("icon") or "").strip() or None
    try:
        cat = add_expense_category(name, icon)
        return jsonify({"success": True, "category": cat})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "error": "تعذر إضافة الفئة"}), 500


@expenses_bp.route("/categories/remove", methods=["POST"])
@feature_required("expenses")
def remove_expense_category_route():
    if not check_permission("can_see_expenses"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    data = request.get_json(silent=True) or {}
    key = (data.get("key") or request.form.get("key") or "").strip()
    try:
        remove_expense_category(key)
        return jsonify({"success": True})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "error": "تعذر حذف الفئة"}), 500


@expenses_bp.route("/delete/<int:id>")
def delete_expense(id):
    # فحص الصلاحية
    if not check_permission("can_see_expenses"):
        return redirect("/pos"), 403
    ensure_treasury_schema()
    e = Expense.query.get_or_404(id)
    expense_snapshot = {"id": e.id, "title": e.title, "amount": e.amount, "category": e.category}
    if getattr(e, "employee_payment_id", None):
        flash("لا يمكن حذف مصروف راتب أو عمولة من صفحة المصاريف. عالج سجل الرواتب حتى تبقى الخزينة والرواتب متطابقة.", "error")
        return redirect(url_for("expenses.expenses"))

    # إرجاع المبلغ فقط إذا كان قد خُصم فعلياً من الصندوق
    if e.cash_posted:
        withdraw_tx = AccountTransaction.query.filter(
            AccountTransaction.type == "withdraw",
            AccountTransaction.amount == e.amount,
            AccountTransaction.note.like(f"%{expense_withdraw_marker(e.id)}%"),
        ).order_by(AccountTransaction.created_at.desc()).first()

        if not withdraw_tx and e.treasury_account_id:
            withdraw_tx = AccountTransaction.query.filter(
                AccountTransaction.type == "withdraw",
                AccountTransaction.amount == e.amount,
                AccountTransaction.treasury_account_id == e.treasury_account_id,
                AccountTransaction.note.like(f"%{e.title}%"),
            ).order_by(AccountTransaction.created_at.desc()).first()

        if not withdraw_tx:
            withdraw_tx = AccountTransaction.query.filter(
                AccountTransaction.type == "withdraw",
                AccountTransaction.amount == e.amount,
                AccountTransaction.note.like(f"%{e.title}%"),
            ).order_by(AccountTransaction.created_at.desc()).first()

        if withdraw_tx:
            deposit_tx = AccountTransaction(
                type="deposit",
                amount=e.amount,
                note=f"إلغاء مصروف: {e.title} ({e.category})",
                treasury_account_id=withdraw_tx.treasury_account_id or e.treasury_account_id,
            )
            db.session.add(deposit_tx)

    db.session.delete(e)
    db.session.commit()
    try:
        log_activity(
            "delete",
            "finance",
            f"حذف مصروف: {expense_snapshot.get('title')}",
            entity_type="expense",
            entity_id=expense_snapshot.get("id"),
            payload={"expense": expense_snapshot},
        )
    except Exception:
        pass
    return redirect(url_for("expenses.expenses"))
