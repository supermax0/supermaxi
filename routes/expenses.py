from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from extensions import db
from utils.branch_scope import resolve_write_branch_id
from utils.branch_mode import independent_branches_enabled
from models.expense import Expense
from models.account_transaction import AccountTransaction
from datetime import datetime, time, timedelta
from utils.business_time import business_now, display_time
from sqlalchemy import and_, or_
from utils.plan_guard import feature_required
from utils.permission_checks import check_permission, _wants_json_response
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
from utils.expense_series import (
    serialize_expense_row,
    build_repeat_note,
    build_series_payload,
    find_series_members,
    new_series_id,
    series_edit_anchor_id,
    update_scheduled_series,
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


def _parse_post_time(raw):
    """Parse HH:MM or HH:MM:SS; empty → None (due from start of day)."""
    value = (raw or "").strip()
    if not value:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def _expense_due_at(expense_date, post_time):
    """Moment when an expense becomes payable."""
    if not expense_date:
        return None
    return datetime.combine(expense_date, post_time or time.min)


def _is_expense_due(expense_date, post_time, now=None):
    now = now or business_now()
    due_at = _expense_due_at(expense_date, post_time)
    return bool(due_at and now >= due_at)


def _post_expense_to_treasury(expense, treasury_account_id=None):
    """خصم المصروف من الصندوق/البنك مرة واحدة."""
    from models.treasury_account import TreasuryAccount
    from utils.treasury_helpers import get_default_cash_account

    account_id = treasury_account_id or expense.treasury_account_id
    if account_id in (None, "", 0, "0"):
        account_id = get_default_cash_account(expense.branch_id).id
    else:
        account = (
            TreasuryAccount.query.execution_options(skip_branch_scope=True)
            .filter_by(
                id=int(account_id),
                is_active=True,
            )
            .first()
        )
        if not account:
            raise ValueError("حساب المصروف غير موجود أو غير فعال")
        if independent_branches_enabled():
            # Localize pre-branch expenses/accounts on first accounting use.
            if not expense.branch_id or not account.branch_id:
                from utils.branch_migration import get_default_branch

                default_branch = get_default_branch()
                legacy_branch_id = (
                    expense.branch_id
                    or account.branch_id
                    or (default_branch.id if default_branch else None)
                )
                if legacy_branch_id:
                    expense.branch_id = expense.branch_id or legacy_branch_id
                    account.branch_id = account.branch_id or legacy_branch_id
            if int(account.branch_id or 0) != int(expense.branch_id or 0):
                raise ValueError("حساب المصروف لا يتبع فرع المصروف")
        account_id = account.id
    amount = int(expense.amount or 0)
    if amount <= 0:
        raise ValueError("مبلغ المصروف يجب أن يكون أكبر من صفر")

    # Claim the row in SQL before writing the withdrawal.  Concurrent page
    # loads can no longer post the same scheduled expense twice.
    claimed = (
        db.session.query(Expense)
        .filter(Expense.id == expense.id, Expense.cash_posted.is_(False))
        .update({Expense.cash_posted: True}, synchronize_session=False)
    )
    if claimed != 1:
        db.session.expire(expense)
        return None
    try:
        assert_sufficient_balance(account_id, amount)
    except Exception:
        db.session.query(Expense).filter(Expense.id == expense.id).update(
            {Expense.cash_posted: False}, synchronize_session=False
        )
        raise
    withdraw_tx = AccountTransaction(
        branch_id=expense.branch_id,
        type="withdraw",
        amount=amount,
        note=build_expense_withdraw_note(expense),
        treasury_account_id=account_id,
    )
    db.session.add(withdraw_tx)
    expense.treasury_account_id = account_id
    expense.cash_posted = True
    return withdraw_tx


def post_due_unposted_expenses(now=None):
    """خصم المصاريف المستحقة فقط — مع احترام ساعة الصرف إن وُجدت."""
    ensure_treasury_schema()
    now = now or business_now()
    today = now.date()
    now_time = now.time().replace(microsecond=0)
    unposted = (
        Expense.query.filter(
            Expense.cash_posted.is_(False),
            Expense.expense_date.isnot(None),
            or_(
                Expense.expense_date < today,
                and_(
                    Expense.expense_date == today,
                    or_(
                        Expense.post_time.is_(None),
                        Expense.post_time <= now_time,
                    ),
                ),
            ),
        )
        .order_by(Expense.expense_date.asc(), Expense.id.asc())
        .all()
    )
    posted = 0
    skipped = 0
    for expense in unposted:
        try:
            withdraw_tx = _post_expense_to_treasury(expense)
            if withdraw_tx is not None:
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


def run_scheduled_expense_posting_for_all_tenants(app):
    """خصم المصاريف المجدولة بساعة محددة عبر كل المستأجرين (مجدول خلفي)."""
    import os
    from pathlib import Path

    if os.name == "nt":
        return _post_scheduled_expenses_for_tenants(app)
    import fcntl

    # A per-run lock survives worker overlap and releases automatically on exit.
    # Keeping a lifetime lock would leave a new worker without a scheduler after
    # a graceful reload. SQL's cash_posted claim still guards concurrent page loads.
    directory = Path(app.instance_path)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(directory / "expense-posting.lock",
                         os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        return _post_scheduled_expenses_for_tenants(app)


def _post_scheduled_expenses_for_tenants(app):
    from flask import g
    from models.core.tenant import Tenant

    with app.app_context():
        slugs = [tenant.slug for tenant in Tenant.query.all() if tenant.slug]
        db.session.remove()
        for slug in slugs:
            g.tenant = slug
            try:
                post_due_unposted_expenses()
            except Exception:
                db.session.rollback()
                app.logger.exception("Scheduled expense posting failed for tenant %s", slug)
            finally:
                db.session.remove()
                g.tenant = None


class _ExpenseInput:
    """Read the same fields from a form or a JSON body."""

    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        value = self.data.get(key, default) if hasattr(self.data, "get") else default
        return default if value is None else value


def create_expense_batch(data) -> dict:
    """Create one expense (or a recurring series) and post the due ones to the treasury.

    Shared by the web page (form) and the desktop API (JSON) — one set of rules: positive amount, sufficient
    balance for everything due now, scheduled items stay unposted until their date/time.
    Raises ValueError / InsufficientTreasuryBalance; the caller rolls back and reports the message.
    """
    form = _ExpenseInput(data)
    branch_id = resolve_write_branch_id(data)
    try:
        expense_amount = int(float(form.get("amount") or 0))
    except (TypeError, ValueError):
        expense_amount = 0
    if expense_amount <= 0:
        raise ValueError("مبلغ المصروف يجب أن يكون أكبر من صفر.")
    expense_title = str(form.get("title") or "").strip()
    if not expense_title:
        raise ValueError("عنوان المصروف مطلوب.")
    if len(expense_title) > 150:
        raise ValueError("عنوان المصروف طويل جداً.")
    expense_category = str(form.get("category") or "").strip() or "other"
    expense_note = str(form.get("note") or "").strip()[:200]
    try:
        expense_date = datetime.strptime(str(form.get("expense_date") or ""), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("تاريخ المصروف غير صالح.") from exc
    treasury_account_id = resolve_treasury_account_id(form.get("treasury_account_id"))
    post_time = _parse_post_time(form.get("expense_time"))
    repeat_enabled = str(form.get("repeat_enabled") or "") in {"1", "true", "True", "on"}
    try:
        repeat_interval = max(1, min(int(form.get("repeat_interval") or 1), 365))
        repeat_count = max(1, min(int(form.get("repeat_count") or 1), 366)) if repeat_enabled else 1
    except (TypeError, ValueError) as exc:
        raise ValueError("إعدادات التكرار غير صالحة.") from exc
    repeat_unit = str(form.get("repeat_unit") or "months").strip()
    if repeat_unit not in {"days", "weeks", "months", "years"}:
        repeat_unit = "months"

    now = business_now()
    # خصم فوري فقط للتواريخ/الساعات المستحقة — المجدولة لاحقاً تبقى بدون سحب
    due_count = 0
    for i in range(repeat_count):
        current_date = _next_recurring_date(expense_date, repeat_interval, repeat_unit, i)
        if _is_expense_due(current_date, post_time, now):
            due_count += 1
    amount_to_withdraw = expense_amount * due_count
    if amount_to_withdraw > 0:
        assert_sufficient_balance(treasury_account_id, amount_to_withdraw)

    series_id = new_series_id() if repeat_count > 1 else None
    created_ids = []
    for i in range(repeat_count):
        current_date = _next_recurring_date(expense_date, repeat_interval, repeat_unit, i)
        note_value = (
            build_repeat_note(expense_note, i + 1, repeat_count)
            if repeat_count > 1
            else (expense_note or "")
        )
        is_due = _is_expense_due(current_date, post_time, now)
        expense = Expense(
            branch_id=branch_id,
            title=expense_title,
            category=expense_category,
            amount=expense_amount,
            note=note_value,
            expense_date=current_date,
            post_time=post_time,
            treasury_account_id=treasury_account_id,
            repeat_series_id=series_id,
            cash_posted=False,
        )
        db.session.add(expense)
        db.session.flush()
        created_ids.append(expense.id)
        if is_due:
            _post_expense_to_treasury(expense, treasury_account_id)

    db.session.commit()

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
                "post_time": post_time.strftime("%H:%M") if post_time else None,
            },
        )
    except Exception:
        pass

    scheduled = repeat_count - due_count
    time_hint = f" الساعة {display_time(post_time)}" if post_time else ""
    if repeat_count > 1:
        msg = f"تم تسجيل {repeat_count} مصروف"
        if due_count:
            msg += f" وخصم {amount_to_withdraw:,} من الصندوق ({due_count} مستحق)"
        if scheduled:
            msg += f" — {scheduled} مجدول{time_hint} بدون خصم حتى يحين موعده"
        msg += "."
    elif due_count:
        msg = "تم تسجيل المصروف وخصمه من الصندوق."
    else:
        msg = f"تم جدولة المصروف{time_hint} بدون خصم من الصندوق حتى يحين موعده."
    return {
        "message": msg,
        "ids": created_ids,
        "count": repeat_count,
        "posted_count": due_count,
        "scheduled_count": scheduled,
        "amount_withdrawn": amount_to_withdraw,
    }


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
        try:
            result = create_expense_batch(request.form)
        except (ValueError, InsufficientTreasuryBalance) as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return redirect(url_for("expenses.expenses"))
        flash(result["message"], "success")
        return redirect(url_for("expenses.expenses"))

    expenses = Expense.query.order_by(Expense.expense_date.desc()).all()
    today = business_now().date()
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

    series_edit_anchors = set()
    seen_series = set()
    for row in expenses:
        if row.id in seen_series:
            continue
        members = find_series_members(row)
        for member in members:
            seen_series.add(member.id)
        scheduled = [m for m in members if not bool(m.cash_posted)]
        if not scheduled:
            continue
        # زر التعديل على أول مجدول؛ يجلب كل المجدولين المرتبطين
        if len(members) > 1 or len(scheduled) >= 1:
            anchor = series_edit_anchor_id(members)
            if anchor:
                series_edit_anchors.add(anchor)

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
        series_edit_anchors=series_edit_anchors,
    )


@expenses_bp.route("/api/series/<int:expense_id>", methods=["GET"])
@feature_required("expenses")
def expense_series_get(expense_id):
    if not check_permission("can_see_expenses"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    ensure_treasury_schema()
    expense = Expense.query.get_or_404(expense_id)
    try:
        payload = build_series_payload(expense)
        db.session.commit()
        return jsonify({"success": True, "series": payload})
    except Exception:
        db.session.rollback()
        return jsonify({"success": False, "error": "تعذر جلب سلسلة المصروف"}), 500


@expenses_bp.route("/api/series/<int:expense_id>", methods=["POST"])
@feature_required("expenses")
def expense_series_update(expense_id):
    if not check_permission("can_see_expenses"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    ensure_treasury_schema()
    expense = Expense.query.get_or_404(expense_id)
    if getattr(expense, "employee_payment_id", None):
        return jsonify({"success": False, "error": "لا يمكن تعديل مصروف راتب من هنا"}), 400
    data = request.get_json(silent=True) or {}
    try:
        payload = update_scheduled_series(expense, data)
        db.session.commit()
        try:
            log_activity(
                "update",
                "finance",
                f"تعديل سلسلة مصروف مجدول: {payload.get('title')}",
                entity_type="expense",
                entity_id=expense_id,
                payload={
                    "series_id": payload.get("series_id"),
                    "scheduled_count": payload.get("scheduled_count"),
                    "amount": payload.get("amount"),
                    "treasury_account_id": payload.get("treasury_account_id"),
                },
            )
        except Exception:
            pass
        return jsonify({"success": True, "series": payload})
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        from werkzeug.exceptions import HTTPException

        if isinstance(exc, HTTPException):
            raise
        db.session.rollback()
        return jsonify({"success": False, "error": "تعذر حفظ تعديلات السلسلة"}), 500


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


def _expense_action_response(ok, message, status=200):
    if _wants_json_response():
        payload = {"success": bool(ok)}
        if ok:
            payload["message"] = message
        else:
            payload["error"] = message
        return jsonify(payload), status
    if not ok:
        flash(message, "error")
    return redirect(url_for("expenses.expenses"))


@expenses_bp.route("/delete/<int:id>", methods=["POST"])
def delete_expense(id):
    # فحص الصلاحية
    if not check_permission("can_see_expenses"):
        if _wants_json_response():
            return jsonify({"success": False, "error": "غير مصرح"}), 403
        return redirect("/pos"), 403
    ensure_treasury_schema()
    e = Expense.query.get_or_404(id)
    expense_snapshot = {"id": e.id, "title": e.title, "amount": e.amount, "category": e.category}
    if getattr(e, "employee_payment_id", None):
        return _expense_action_response(
            False,
            "لا يمكن حذف مصروف راتب أو عمولة من صفحة المصاريف. عالج سجل الرواتب حتى تبقى الخزينة والرواتب متطابقة.",
            400,
        )

    # إرجاع المبلغ فقط إذا كان قد خُصم فعلياً من الصندوق
    if e.cash_posted:
        withdraw_tx = AccountTransaction.query.filter(
            AccountTransaction.type == "withdraw",
            AccountTransaction.amount == e.amount,
            AccountTransaction.note.like(f"%{expense_withdraw_marker(e.id)}%"),
        ).order_by(AccountTransaction.created_at.desc()).first()

        if not withdraw_tx:
            # Compatibility for legacy rows written before the marker existed.
            # Only accept one unambiguous movement from the same branch/account.
            legacy_candidates = AccountTransaction.query.filter(
                AccountTransaction.type == "withdraw",
                AccountTransaction.amount == e.amount,
                AccountTransaction.branch_id == e.branch_id,
                AccountTransaction.note.like(f"%{e.title}%"),
            )
            if e.treasury_account_id:
                legacy_candidates = legacy_candidates.filter(
                    AccountTransaction.treasury_account_id == e.treasury_account_id
                )
            legacy_candidates = legacy_candidates.order_by(
                AccountTransaction.created_at.desc()
            ).limit(2).all()
            if len(legacy_candidates) == 1:
                withdraw_tx = legacy_candidates[0]

        if not withdraw_tx:
            return _expense_action_response(
                False,
                "تعذر حذف المصروف لأن حركة السحب الأصلية غير موجودة أو غير واضحة. لم يتم تغيير الحسابات.",
                400,
            )

        deposit_tx = AccountTransaction(
            branch_id=e.branch_id,
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
    return _expense_action_response(True, "تم حذف المصروف")


# =====================================================
# Desktop API (FINORA Management) — JSON over the same rules as the page
# =====================================================
_EXPENSE_TABS = ("all", "posted", "scheduled")


def _expense_api_denied():
    if not check_permission("can_see_expenses"):
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    return None


def _treasury_rows():
    return [
        {
            "id": int(a.id),
            "name": a.name,
            "type": (a.account_type or "").strip().lower() or "cash",
            "is_default": bool(a.is_default),
            "branch_name": getattr(a, "branch_name", None),
        }
        for a in treasury_choices_for_form()
    ]


def _parse_day(raw):
    try:
        return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date() if raw else None
    except ValueError:
        return None


@expenses_bp.route("/api/meta", methods=["GET"])
@feature_required("expenses")
def expenses_api_meta():
    denied = _expense_api_denied()
    if denied:
        return denied
    ensure_treasury_schema()
    return jsonify({
        "success": True,
        "categories": get_expense_categories(),
        "treasury_accounts": _treasury_rows(),
        "today": business_now().date().strftime("%Y-%m-%d"),
    })


@expenses_bp.route("/api/page", methods=["GET"])
@feature_required("expenses")
def expenses_api_page():
    """One page of expenses with tab counts, period totals and a per-category breakdown of the filtered set."""
    denied = _expense_api_denied()
    if denied:
        return denied
    ensure_treasury_schema()
    try:
        post_due_unposted_expenses()  # same as opening the page: due scheduled expenses are posted first
    except Exception:
        db.session.rollback()

    from sqlalchemy import func as sa_func

    from models.treasury_account import TreasuryAccount
    from utils.expense_categories import get_category_map, normalize_category_key, resolve_category_meta

    tab = (request.args.get("tab") or "all").strip()
    if tab not in _EXPENSE_TABS:
        tab = "all"
    search = (request.args.get("search") or "").strip()
    category = (request.args.get("category") or "").strip()
    date_from = _parse_day(request.args.get("date_from"))
    date_to = _parse_day(request.args.get("date_to"))
    account_id = request.args.get("treasury_account_id", type=int)
    sort = (request.args.get("sort") or "date").strip()
    page = max(1, request.args.get("page", 1, type=int) or 1)
    page_size = max(10, min(request.args.get("page_size", 25, type=int) or 25, 100))

    base = Expense.query
    if search:
        like = f"%{search}%"
        base = base.filter(or_(Expense.title.ilike(like), Expense.note.ilike(like)))
    category_map = get_category_map()
    if category:
        key = normalize_category_key(category, category_map)
        aliases = {category, key, resolve_category_meta(key, category_map).get("label") or key}
        base = base.filter(Expense.category.in_([a for a in aliases if a]))
    if date_from:
        base = base.filter(Expense.expense_date >= date_from)
    if date_to:
        base = base.filter(Expense.expense_date <= date_to)
    if account_id:
        base = base.filter(Expense.treasury_account_id == account_id)

    counts = {
        "all": base.count(),
        "posted": base.filter(Expense.cash_posted.is_(True)).count(),
        "scheduled": base.filter(Expense.cash_posted.is_(False)).count(),
    }
    filtered = base
    if tab == "posted":
        filtered = filtered.filter(Expense.cash_posted.is_(True))
    elif tab == "scheduled":
        filtered = filtered.filter(Expense.cash_posted.is_(False))

    filtered_total = int(filtered.with_entities(sa_func.coalesce(sa_func.sum(Expense.amount), 0)).scalar() or 0)
    by_category = {}
    for raw_category, amount, count in (
        filtered.with_entities(Expense.category, sa_func.sum(Expense.amount), sa_func.count(Expense.id))
        .group_by(Expense.category)
        .all()
    ):
        key = normalize_category_key(raw_category, category_map)
        meta = resolve_category_meta(key, category_map)
        slot = by_category.setdefault(key, {"key": key, "label": meta.get("label") or key,
                                            "icon": meta.get("icon") or "", "amount": 0, "count": 0})
        slot["amount"] += int(amount or 0)
        slot["count"] += int(count or 0)

    if sort == "amount":
        ordered = filtered.order_by(Expense.amount.desc(), Expense.id.desc())
    elif sort == "oldest":
        ordered = filtered.order_by(Expense.expense_date.asc(), Expense.id.asc())
    else:
        ordered = filtered.order_by(Expense.expense_date.desc(), Expense.id.desc())
    total = counts[tab]
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    rows = ordered.offset((page - 1) * page_size).limit(page_size).all()

    account_ids = {r.treasury_account_id for r in rows if r.treasury_account_id}
    account_names = {
        a.id: a.name
        for a in TreasuryAccount.query.execution_options(skip_branch_scope=True)
        .filter(TreasuryAccount.id.in_(account_ids or [-1]))
        .all()
    }

    def row_dto(e):
        data = serialize_expense_row(e)
        key = normalize_category_key(e.category, category_map)
        meta = resolve_category_meta(key, category_map)
        data.update(
            category_key=key,
            category_label=meta.get("label") or key,
            category_icon=meta.get("icon") or "",
            treasury_account_name=account_names.get(e.treasury_account_id, ""),
            status="posted" if e.cash_posted else "scheduled",
            is_payroll=bool(getattr(e, "employee_payment_id", None)),
            created_at=e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else "",
        )
        return data

    today = business_now().date()
    scheduled_q = Expense.query.filter(Expense.cash_posted.is_(False))
    return jsonify({
        "success": True,
        "rows": [row_dto(e) for e in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "counts": counts,
        "summary": {
            "today_total": sum_posted_expenses(today, today),
            "month_total": sum_posted_expenses(today.replace(day=1), today),
            "year_total": sum_posted_expenses(today.replace(month=1, day=1), today),
            "scheduled_total": int(
                scheduled_q.with_entities(sa_func.coalesce(sa_func.sum(Expense.amount), 0)).scalar() or 0
            ),
            "scheduled_count": scheduled_q.count(),
            "filtered_total": filtered_total,
        },
        "by_category": sorted(by_category.values(), key=lambda c: c["amount"], reverse=True),
    })


@expenses_bp.route("/api/create", methods=["POST"])
@feature_required("expenses")
def expenses_api_create():
    denied = _expense_api_denied()
    if denied:
        return denied
    ensure_treasury_schema()
    data = request.get_json(silent=True) or {}
    try:
        result = create_expense_batch(data)
    except InsufficientTreasuryBalance as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 409
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, **result})
