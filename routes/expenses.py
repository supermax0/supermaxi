from flask import Blueprint, render_template, request, redirect, url_for, session
from extensions import db
from models.expense import Expense
from models.account_transaction import AccountTransaction
from models.employee import Employee
from sqlalchemy.sql import func
from datetime import datetime, timedelta
from utils.plan_guard import feature_required

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

def check_permission(permission_name):
    """فحص الصلاحية - helper function"""
    if "user_id" not in session:
        return False
    employee = Employee.query.get(session["user_id"])
    if not employee or not employee.is_active:
        return False
    # Admin لديه جميع الصلاحيات
    if employee.role == "admin":
        return True
        
    perm_map = {
        "can_see_orders": "view_orders",
        "can_see_reports": "view_reports",
        "can_manage_inventory": "manage_inventory",
        "can_see_expenses": "view_expenses",
        "can_manage_suppliers": "manage_suppliers",
        "can_manage_customers": "manage_customers",
        "can_see_accounts": "view_accounts",
        "can_see_financial": "view_financial",
        "can_edit_price": "edit_price",
    }
    rbac_name = perm_map.get(permission_name, permission_name)
    return employee.has_permission(rbac_name)

@expenses_bp.route("/", methods=["GET", "POST"])
@feature_required("expenses")
def expenses():
    # فحص الصلاحية
    if not check_permission("can_see_expenses"):
        return redirect("/pos"), 403

    if request.method == "POST":
        expense_amount = int(float(request.form["amount"]))
        expense_title = request.form["title"]
        expense_category = request.form["category"]
        expense_note = request.form.get("note")
        expense_date = datetime.strptime(
            request.form["expense_date"], "%Y-%m-%d"
        ).date()
        repeat_enabled = request.form.get("repeat_enabled") == "1"
        repeat_interval = max(1, min(int(request.form.get("repeat_interval") or 1), 365))
        repeat_unit = (request.form.get("repeat_unit") or "days").strip()
        if repeat_unit not in {"days", "weeks", "months", "years"}:
            repeat_unit = "days"
        repeat_count = 1
        if repeat_enabled:
            repeat_count = max(1, min(int(request.form.get("repeat_count") or 1), 120))
        
        for i in range(repeat_count):
            current_date = _next_recurring_date(expense_date, repeat_interval, repeat_unit, i)
            repeat_suffix = f" | تكرار {i + 1}/{repeat_count}" if repeat_count > 1 else ""
            expense = Expense(
                title=expense_title,
                category=expense_category,
                amount=expense_amount,
                note=(expense_note or "") + repeat_suffix,
                expense_date=current_date
            )
            db.session.add(expense)
            
            # خصم المبلغ من رأس المال تلقائياً لكل مصروف يتم إنشاؤه
            withdraw_tx = AccountTransaction(
                type="withdraw",
                amount=expense_amount,
                note=f"مصروف: {expense_title} ({expense_category}) بتاريخ {current_date}" + (f" - {expense_note}" if expense_note else "") + repeat_suffix
            )
            db.session.add(withdraw_tx)
        
        db.session.commit()
        return redirect(url_for("expenses.expenses"))

    expenses = Expense.query.order_by(Expense.expense_date.desc()).all()
    total = db.session.query(func.sum(Expense.amount)).scalar() or 0
    
    # حساب مصاريف الشهر الحالي
    today = datetime.now().date()
    first_day_of_month = today.replace(day=1)
    month_total = db.session.query(func.sum(Expense.amount)).filter(
        Expense.expense_date >= first_day_of_month,
        Expense.expense_date <= today
    ).scalar() or 0
    
    # حساب مصاريف اليوم
    today_total = db.session.query(func.sum(Expense.amount)).filter(
        Expense.expense_date == today
    ).scalar() or 0
    
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
        total=total,
        month_total=month_total,
        today_total=today_total,
        current_month_name=current_month_name,
        today_date=today_date,
        default_date=default_date
    )


@expenses_bp.route("/delete/<int:id>")
def delete_expense(id):
    # فحص الصلاحية
    if not check_permission("can_see_expenses"):
        return redirect("/pos"), 403
    e = Expense.query.get_or_404(id)
    
    # إرجاع المبلغ إلى رأس المال عند حذف المصروف
    # البحث عن حركة السحب المرتبطة بهذا المصروف
    withdraw_tx = AccountTransaction.query.filter(
        AccountTransaction.type == "withdraw",
        AccountTransaction.amount == e.amount,
        AccountTransaction.note.like(f"%{e.title}%")
    ).order_by(AccountTransaction.created_at.desc()).first()
    
    if withdraw_tx:
        # إضافة إيداع لتعويض السحب
        deposit_tx = AccountTransaction(
            type="deposit",
            amount=e.amount,
            note=f"إلغاء مصروف: {e.title} ({e.category})"
        )
        db.session.add(deposit_tx)
    
    db.session.delete(e)
    db.session.commit()
    return redirect(url_for("expenses.expenses"))
