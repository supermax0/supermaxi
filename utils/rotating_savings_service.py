"""
خدمة الجمعيات والسلف الدوّارة — قيود محاسبية تلقائية.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional
import uuid

from extensions import db
from models.account import Account
from models.account_transaction import AccountTransaction
from models.employee import Employee
from models.journal_entry import JournalEntry
from models.rotating_savings import (
    RotatingSaving,
    RotatingSavingPayment,
    RotatingSavingReceipt,
    RotatingSavingSettings,
)
from utils.accounting_logic import ACCOUNT_CODES, get_or_create_account, initialize_accounts
from utils.rotating_savings_schema_guard import ensure_rotating_savings_schema
from utils.rotating_savings_audit import log_rotating_saving_audit, saving_snapshot
from utils.treasury_calculations import InsufficientTreasuryBalance, assert_sufficient_balance
from utils.treasury_helpers import resolve_treasury_account_id

RS_GL = {
    "ROTATING_PARENT": "1205",
    "ROTATING_COMPANY": "1205-01",
    "ROTATING_EMPLOYEE": "1205-02",
    "LIABILITY_PARENT": "2205",
    "LIABILITY_SUB": "2205-01",
    "OWNER_DRAWINGS": "3102",
    "FEE_EXPENSE": "6105",
    "BANK": "1002",
    "OWNER_CURRENT": "3103",
}


class RotatingSavingError(Exception):
    pass


def _safe_int(value, default=0):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return default


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def get_settings() -> RotatingSavingSettings:
    ensure_rotating_savings_schema()
    row = RotatingSavingSettings.query.first()
    if not row:
        row = RotatingSavingSettings()
        db.session.add(row)
        db.session.commit()
    return row


def ensure_rotating_savings_gl_accounts():
    initialize_accounts()
    get_or_create_account(
        RS_GL["ROTATING_PARENT"],
        "سلف وجمعيات دوّارة",
        "asset",
        "حساب أصل الجمعيات والسلف الدوّارة",
    )
    get_or_create_account(
        RS_GL["ROTATING_COMPANY"],
        "جمعيات باسم الشركة",
        "asset",
        "جمعيات دوّارة باسم الشركة",
    )
    get_or_create_account(
        RS_GL["ROTATING_EMPLOYEE"],
        "سلف موظفين من خلال جمعية",
        "asset",
        "سلف موظفين عبر جمعيات",
    )
    get_or_create_account(
        RS_GL["LIABILITY_PARENT"],
        "التزامات جمعيات دوّارة",
        "liability",
        "التزامات الجمعيات الدوّارة",
    )
    get_or_create_account(
        RS_GL["LIABILITY_SUB"],
        "أقساط جمعيات مستحقة بعد الاستلام",
        "liability",
        "أقساط جمعيات مستحقة بعد الاستلام",
    )
    get_or_create_account(
        RS_GL["OWNER_DRAWINGS"],
        "مسحوبات المالك",
        "equity",
        "مسحوبات المالك من الجمعيات الشخصية",
    )
    get_or_create_account(
        RS_GL["OWNER_CURRENT"],
        "جاري المالك",
        "equity",
        "حساب جاري المالك",
    )
    get_or_create_account(
        RS_GL["FEE_EXPENSE"],
        "مصاريف ورسوم جمعيات",
        "expense",
        "رسوم وعمولات الجمعيات فقط",
    )
    get_or_create_account(
        RS_GL["BANK"],
        "البنك",
        "asset",
        "حساب البنك",
    )
    db.session.commit()


def _next_sub_code(parent_code: str, saving_name: str) -> str:
    base = parent_code.replace("-", "")
    existing = Account.query.filter(Account.code.like(f"{parent_code}-%")).count()
    suffix = str(existing + 1).zfill(2)
    return f"{parent_code}-{suffix}"


def _create_saving_sub_account(saving: RotatingSaving) -> Optional[int]:
    ensure_rotating_savings_gl_accounts()
    if saving.type == "tracking_only":
        return None
    if saving.type == "company":
        parent = RS_GL["ROTATING_COMPANY"]
        acc_type = "asset"
    elif saving.type == "employee":
        parent = RS_GL["ROTATING_EMPLOYEE"]
        acc_type = "asset"
    elif saving.type == "owner_personal":
        settings = get_settings()
        code = RS_GL["OWNER_DRAWINGS"] if settings.owner_return_mode == "drawings" else RS_GL["OWNER_CURRENT"]
        acc = Account.query.filter_by(code=code).first()
        return acc.id if acc else None
    else:
        return None

    code = _next_sub_code(parent, saving.name)
    acc = get_or_create_account(
        code,
        f"{parent} - {saving.name}",
        acc_type,
        f"حساب جمعية: {saving.name}",
    )
    return acc.id


def _journal_by_ids(
    debit_account_id,
    credit_account_id,
    amount,
    description,
    reference_type="rotating_saving",
    reference_id=None,
    created_by=None,
):
    amount = _safe_int(amount)
    if amount <= 0:
        return None
    if debit_account_id == credit_account_id:
        raise RotatingSavingError("الحساب المدين والدائن يجب أن يكونا مختلفين")
    entry_number = f"JE-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
    entry = JournalEntry(
        entry_number=entry_number,
        description=description,
        reference_type=reference_type,
        reference_id=reference_id,
        debit_account_id=debit_account_id,
        credit_account_id=credit_account_id,
        amount=amount,
        entry_date=datetime.utcnow(),
        created_by=created_by,
    )
    db.session.add(entry)
    db.session.flush()
    return entry


def _resolve_gl_cash_account(payment_method: str):
    if payment_method == "bank":
        acc = Account.query.filter_by(code=RS_GL["BANK"]).first()
        if not acc:
            ensure_rotating_savings_gl_accounts()
            acc = Account.query.filter_by(code=RS_GL["BANK"]).first()
        return acc.id if acc else None
    acc = Account.query.filter_by(code=ACCOUNT_CODES["CASH"]).first()
    if not acc:
        initialize_accounts()
        acc = Account.query.filter_by(code=ACCOUNT_CODES["CASH"]).first()
    return acc.id if acc else None


def _treasury_withdraw(amount, note, treasury_account_id, user_id=None):
    amount = _safe_int(amount)
    if amount <= 0:
        return None
    tid = resolve_treasury_account_id(treasury_account_id)
    assert_sufficient_balance(tid, amount)
    tx = AccountTransaction(
        type="withdraw",
        amount=amount,
        note=note,
        treasury_account_id=tid,
    )
    db.session.add(tx)
    db.session.flush()
    return tx


def _treasury_deposit(amount, note, treasury_account_id):
    amount = _safe_int(amount)
    if amount <= 0:
        return None
    tid = resolve_treasury_account_id(treasury_account_id)
    tx = AccountTransaction(
        type="deposit",
        amount=amount,
        note=note,
        treasury_account_id=tid,
    )
    db.session.add(tx)
    db.session.flush()
    return tx


def _liability_account_id(saving: RotatingSaving) -> int:
    if saving.liability_account_id:
        return saving.liability_account_id
    ensure_rotating_savings_gl_accounts()
    acc = Account.query.filter_by(code=RS_GL["LIABILITY_SUB"]).first()
    if not acc:
        raise RotatingSavingError("حساب الالتزامات غير موجود")
    saving.liability_account_id = acc.id
    return acc.id


def _fee_account_id(saving: RotatingSaving) -> int:
    if saving.fee_expense_account_id:
        return saving.fee_expense_account_id
    ensure_rotating_savings_gl_accounts()
    acc = Account.query.filter_by(code=RS_GL["FEE_EXPENSE"]).first()
    saving.fee_expense_account_id = acc.id
    return acc.id


def _owner_equity_account_id(saving: RotatingSaving) -> int:
    settings = get_settings()
    if saving.owner_drawings_account_id:
        return saving.owner_drawings_account_id
    ensure_rotating_savings_gl_accounts()
    code = RS_GL["OWNER_DRAWINGS"] if settings.owner_return_mode == "drawings" else RS_GL["OWNER_CURRENT"]
    acc = Account.query.filter_by(code=code).first()
    saving.owner_drawings_account_id = acc.id
    return acc.id


def build_saving_from_form(data, user_id=None) -> RotatingSaving:
    ensure_rotating_savings_schema()
    ensure_rotating_savings_gl_accounts()
    settings = get_settings()
    if not settings.enabled:
        raise RotatingSavingError("موديول الجمعيات معطّل من الإعدادات")

    name = (data.get("name") or "").strip()
    if not name:
        raise RotatingSavingError("اسم الجمعية مطلوب")

    saving_type = (data.get("type") or "company").strip()
    monthly = _safe_int(data.get("monthly_amount"))
    months = _safe_int(data.get("total_months"), 1)
    if monthly <= 0:
        raise RotatingSavingError("مبلغ القسط الشهري مطلوب")
    if months <= 0:
        raise RotatingSavingError("عدد الأشهر مطلوب")

    start = _parse_date(data.get("start_date")) or date.today()
    expected_receive = _safe_int(data.get("expected_receive_amount"))
    if expected_receive <= 0:
        expected_receive = monthly * months

    saving = RotatingSaving(
        name=name,
        description=(data.get("description") or "").strip() or None,
        type=saving_type,
        manager_name=(data.get("manager_name") or "").strip() or None,
        manager_phone=(data.get("manager_phone") or "").strip() or None,
        employee_id=_safe_int(data.get("employee_id")) or None,
        owner_id=_safe_int(data.get("owner_id")) or None,
        members_count=_safe_int(data.get("members_count"), 1) or 1,
        monthly_amount=monthly,
        total_months=months,
        expected_receive_amount=expected_receive,
        start_date=start,
        expected_end_date=_parse_date(data.get("expected_end_date")),
        expected_receive_month=_safe_int(data.get("expected_receive_month")) or None,
        receive_method=(data.get("receive_method") or "manual").strip(),
        default_payment_method=(data.get("default_payment_method") or "cash").strip(),
        default_treasury_account_id=_safe_int(data.get("default_treasury_account_id")) or None,
        has_fees=str(data.get("has_fees", "")).lower() in ("1", "true", "on", "yes"),
        fee_amount=_safe_int(data.get("fee_amount")),
        notes=(data.get("notes") or "").strip() or None,
        remaining_to_pay=monthly * months,
        created_by=user_id,
    )

    if saving_type != "tracking_only":
        sub_id = _create_saving_sub_account(saving)
        if saving_type == "company":
            saving.asset_account_id = sub_id
        elif saving_type == "employee":
            saving.employee_receivable_account_id = sub_id
        elif saving_type == "owner_personal":
            saving.owner_drawings_account_id = _owner_equity_account_id(saving)

    if not saving.expected_end_date and months:
        saving.expected_end_date = start + timedelta(days=30 * months)

    db.session.add(saving)
    db.session.flush()

    prior_count = _safe_int(data.get("prior_payments_count"))
    if prior_count > 0:
        _create_prior_payments(
            saving,
            count=prior_count,
            amount_per=_safe_int(data.get("prior_payment_amount"), monthly),
            first_date=_parse_date(data.get("prior_first_date")) or start,
            payment_method=(data.get("prior_payment_method") or saving.default_payment_method),
            treasury_id=_safe_int(data.get("prior_treasury_account_id")) or saving.default_treasury_account_id,
            combined=str(data.get("prior_combined_entry", "")).lower() in ("1", "true", "on"),
            user_id=user_id,
        )

    recalculate_balances(saving)
    log_rotating_saving_audit(
        "create",
        f"إنشاء جمعية: {saving.name}",
        saving_id=saving.id,
        new_values=saving_snapshot(saving),
        user_id=user_id,
    )
    return saving


def _create_prior_payments(
    saving,
    count,
    amount_per,
    first_date,
    payment_method,
    treasury_id,
    combined=False,
    user_id=None,
):
    if saving.type == "tracking_only":
        for i in range(count):
            pdate = first_date + timedelta(days=30 * i)
            db.session.add(
                RotatingSavingPayment(
                    rotating_saving_id=saving.id,
                    payment_no=i + 1,
                    due_date=pdate,
                    payment_date=pdate,
                    amount=amount_per,
                    payment_method=payment_method,
                    treasury_account_id=treasury_id,
                    status="paid",
                    created_by=user_id,
                )
            )
        db.session.flush()
        recalculate_balances(saving)
        return

    if combined and count > 1:
        total = amount_per * count
        record_payment(
            saving,
            payment_date=first_date,
            amount=total,
            payment_method=payment_method,
            treasury_account_id=treasury_id,
            notes=f"قيد تجميعي — {count} دفعات سابقة",
            user_id=user_id,
        )
        return

    for i in range(count):
        pdate = first_date + timedelta(days=30 * i)
        record_payment(
            saving,
            payment_date=pdate,
            amount=amount_per,
            payment_method=payment_method,
            treasury_account_id=treasury_id,
            notes=f"دفعة سابقة #{i + 1}",
            user_id=user_id,
        )


def record_payment(
    saving: RotatingSaving,
    payment_date,
    amount,
    payment_method="cash",
    treasury_account_id=None,
    fee_amount=0,
    notes=None,
    user_id=None,
    is_post_receipt=None,
):
    if saving.type == "tracking_only":
        raise RotatingSavingError("جمعية المتابعة فقط لا تولّد قيوداً")

    amount = _safe_int(amount)
    fee_amount = _safe_int(fee_amount)
    if amount <= 0:
        raise RotatingSavingError("مبلغ الدفعة يجب أن يكون أكبر من صفر")

    payment_date = _parse_date(payment_date) or date.today()
    treasury_id = treasury_account_id or saving.default_treasury_account_id
    cash_gl = _resolve_gl_cash_account(payment_method)

    if is_post_receipt is None:
        is_post_receipt = saving.receive_status in ("received", "partial_received")

    payment = RotatingSavingPayment(
        rotating_saving_id=saving.id,
        payment_no=(RotatingSavingPayment.query.filter_by(rotating_saving_id=saving.id).count() + 1),
        due_date=payment_date,
        payment_date=payment_date,
        amount=amount,
        fee_amount=fee_amount,
        payment_method=payment_method,
        treasury_account_id=treasury_id,
        is_post_receipt=is_post_receipt,
        notes=notes,
        created_by=user_id,
    )
    db.session.add(payment)
    db.session.flush()

    desc = f"تسجيل دفعة جمعية شهرية - {saving.name}"
    note = f"جمعية/سلفة دوّارة — دفع قسط — {saving.name}"

    try:
        tx = _treasury_withdraw(amount, note, treasury_id)
        payment.treasury_transaction_id = tx.id if tx else None
    except InsufficientTreasuryBalance as exc:
        raise RotatingSavingError(str(exc)) from exc

    entry = None
    if saving.type == "company":
        if is_post_receipt:
            liability_id = _liability_account_id(saving)
            entry = _journal_by_ids(
                liability_id,
                cash_gl,
                amount,
                f"تسوية التزام جمعية - {saving.name}",
                reference_id=saving.id,
                created_by=user_id,
            )
        else:
            if not saving.asset_account_id:
                saving.asset_account_id = _create_saving_sub_account(saving)
            entry = _journal_by_ids(
                saving.asset_account_id,
                cash_gl,
                amount,
                desc,
                reference_id=saving.id,
                created_by=user_id,
            )
    elif saving.type == "owner_personal":
        equity_id = _owner_equity_account_id(saving)
        entry = _journal_by_ids(
            equity_id,
            cash_gl,
            amount,
            desc,
            reference_id=saving.id,
            created_by=user_id,
        )
    elif saving.type == "employee":
        if not saving.employee_receivable_account_id:
            saving.employee_receivable_account_id = _create_saving_sub_account(saving)
        entry = _journal_by_ids(
            saving.employee_receivable_account_id,
            cash_gl,
            amount,
            desc,
            reference_id=saving.id,
            created_by=user_id,
        )

    payment.journal_entry_id = entry.id if entry else None

    if fee_amount > 0:
        _record_fee_on_payment(payment, fee_amount, payment_method, treasury_id, user_id)

    recalculate_balances(saving)
    log_rotating_saving_audit(
        "payment",
        f"تسجيل دفعة جمعية: {saving.name} — {amount:,} د.ع",
        saving_id=saving.id,
        extra={"payment_id": payment.id, "amount": amount},
        user_id=user_id,
    )
    return payment


def _record_fee_on_payment(payment, fee_amount, payment_method, treasury_id, user_id):
    saving = payment.saving
    fee_id = _fee_account_id(saving)
    cash_gl = _resolve_gl_cash_account(payment_method)
    note = f"جمعية/سلفة دوّارة — دفع رسوم — {saving.name}"
    tx = _treasury_withdraw(fee_amount, note, treasury_id)
    entry = _journal_by_ids(
        fee_id,
        cash_gl,
        fee_amount,
        f"تسجيل رسوم جمعية - {saving.name}",
        reference_id=saving.id,
        created_by=user_id,
    )
    payment.fee_amount = fee_amount
    payment.fee_journal_entry_id = entry.id if entry else None
    payment.fee_treasury_transaction_id = tx.id if tx else None


def record_receipt(
    saving: RotatingSaving,
    receipt_date,
    received_amount,
    deposit_method="cash",
    treasury_account_id=None,
    notes=None,
    user_id=None,
    allow_over_expected=False,
):
    if saving.type == "tracking_only":
        raise RotatingSavingError("جمعية المتابعة فقط لا تولّد قيوداً")

    received_amount = _safe_int(received_amount)
    if received_amount <= 0:
        raise RotatingSavingError("مبلغ الاستلام يجب أن يكون أكبر من صفر")

    if received_amount > saving.expected_receive_amount and not allow_over_expected:
        raise RotatingSavingError(
            "مبلغ الاستلام أكبر من المتوقع — يتطلب موافقة المدير المالي"
        )

    receipt_date = _parse_date(receipt_date) or date.today()
    treasury_id = treasury_account_id or saving.default_treasury_account_id
    cash_gl = _resolve_gl_cash_account(deposit_method)

    paid_before = _safe_int(saving.total_paid)
    liability_created = max(received_amount - paid_before, 0)
    asset_closed = min(paid_before, received_amount)

    receipt = RotatingSavingReceipt(
        rotating_saving_id=saving.id,
        receipt_date=receipt_date,
        received_amount=received_amount,
        deposit_method=deposit_method,
        treasury_account_id=treasury_id,
        paid_before_receipt=paid_before,
        liability_created=liability_created,
        asset_closed_amount=asset_closed,
        notes=notes,
        created_by=user_id,
    )
    db.session.add(receipt)
    db.session.flush()

    note = f"جمعية/سلفة دوّارة — استلام جمعية — {saving.name}"
    tx = _treasury_deposit(received_amount, note, treasury_id)
    receipt.treasury_transaction_id = tx.id if tx else None

    entry_ids = []
    desc = f"استلام مبلغ جمعية - {saving.name}"

    if saving.type == "company":
        if asset_closed > 0:
            e1 = _journal_by_ids(
                cash_gl,
                saving.asset_account_id,
                asset_closed,
                desc,
                reference_id=saving.id,
                created_by=user_id,
            )
            if e1:
                entry_ids.append(str(e1.id))
        if liability_created > 0:
            liability_id = _liability_account_id(saving)
            e2 = _journal_by_ids(
                cash_gl,
                liability_id,
                liability_created,
                f"{desc} — التزام متبقي",
                reference_id=saving.id,
                created_by=user_id,
            )
            if e2:
                entry_ids.append(str(e2.id))
        saving.receive_status = "received"
        saving.status = "received"
    elif saving.type == "owner_personal":
        equity_id = _owner_equity_account_id(saving)
        e = _journal_by_ids(
            cash_gl,
            equity_id,
            received_amount,
            desc,
            reference_id=saving.id,
            created_by=user_id,
        )
        if e:
            entry_ids.append(str(e.id))
        saving.receive_status = "received"
        saving.status = "received"
    elif saving.type == "employee":
        if not saving.employee_receivable_account_id:
            raise RotatingSavingError("حساب ذمة الموظف غير محدد")
        e = _journal_by_ids(
            cash_gl,
            saving.employee_receivable_account_id,
            min(received_amount, paid_before),
            desc,
            reference_id=saving.id,
            created_by=user_id,
        )
        if e:
            entry_ids.append(str(e.id))
        saving.receive_status = "received"

    receipt.journal_entry_ids = ",".join(entry_ids) if entry_ids else None
    recalculate_balances(saving)
    log_rotating_saving_audit(
        "receipt",
        f"استلام جمعية: {saving.name} — {received_amount:,} د.ع",
        saving_id=saving.id,
        extra={"receipt_id": receipt.id, "received_amount": received_amount},
        user_id=user_id,
    )
    return receipt


def record_fee(
    saving: RotatingSaving,
    fee_date,
    amount,
    payment_method="cash",
    treasury_account_id=None,
    notes=None,
    user_id=None,
):
    amount = _safe_int(amount)
    if amount <= 0:
        raise RotatingSavingError("مبلغ الرسوم مطلوب")

    fee_date = _parse_date(fee_date) or date.today()
    treasury_id = treasury_account_id or saving.default_treasury_account_id
    fee_id = _fee_account_id(saving)
    cash_gl = _resolve_gl_cash_account(payment_method)

    note = f"جمعية/سلفة دوّارة — دفع رسوم — {saving.name}"
    _treasury_withdraw(amount, note, treasury_id)
    _journal_by_ids(
        fee_id,
        cash_gl,
        amount,
        f"تسجيل رسوم جمعية - {saving.name}",
        reference_id=saving.id,
        created_by=user_id,
    )
    saving.total_fees = _safe_int(saving.total_fees) + amount
    recalculate_balances(saving)
    log_rotating_saving_audit(
        "fee",
        f"رسوم جمعية: {saving.name} — {amount:,} د.ع",
        saving_id=saving.id,
        extra={"amount": amount},
        user_id=user_id,
    )


def recalculate_balances(saving: RotatingSaving):
    paid = (
        db.session.query(db.func.coalesce(db.func.sum(RotatingSavingPayment.amount), 0))
        .filter(
            RotatingSavingPayment.rotating_saving_id == saving.id,
            RotatingSavingPayment.status == "paid",
        )
        .scalar()
    )
    received = (
        db.session.query(db.func.coalesce(db.func.sum(RotatingSavingReceipt.received_amount), 0))
        .filter(RotatingSavingReceipt.rotating_saving_id == saving.id)
        .scalar()
    )
    fees = (
        db.session.query(db.func.coalesce(db.func.sum(RotatingSavingPayment.fee_amount), 0))
        .filter(
            RotatingSavingPayment.rotating_saving_id == saving.id,
            RotatingSavingPayment.status == "paid",
        )
        .scalar()
    )

    saving.total_paid = _safe_int(paid)
    saving.total_received = _safe_int(received)
    saving.total_fees = _safe_int(fees) + _safe_int(saving.fee_amount if saving.has_fees else 0)
    saving.remaining_to_pay = max(saving.expected_total_to_pay - saving.total_paid, 0)

    if saving.type == "tracking_only":
        saving.accounting_status = "tracking"
        saving.asset_balance = 0
        saving.liability_balance = 0
        saving.owner_drawings_balance = 0
        saving.employee_receivable_balance = 0
        db.session.flush()
        return

    if saving.type == "company":
        if saving.receive_status == "not_received":
            saving.asset_balance = saving.total_paid
            saving.liability_balance = 0
            saving.accounting_status = "asset"
        else:
            last_receipt = (
                RotatingSavingReceipt.query.filter_by(rotating_saving_id=saving.id)
                .order_by(RotatingSavingReceipt.receipt_date.desc())
                .first()
            )
            liability_base = _safe_int(last_receipt.liability_created if last_receipt else 0)
            post_paid = (
                db.session.query(db.func.coalesce(db.func.sum(RotatingSavingPayment.amount), 0))
                .filter(
                    RotatingSavingPayment.rotating_saving_id == saving.id,
                    RotatingSavingPayment.status == "paid",
                    RotatingSavingPayment.is_post_receipt.is_(True),
                )
                .scalar()
            )
            saving.liability_balance = max(liability_base - _safe_int(post_paid), 0)
            saving.asset_balance = 0
            saving.accounting_status = "liability" if saving.liability_balance > 0 else "closed"
            if saving.liability_balance <= 0 and saving.remaining_to_pay <= 0:
                saving.status = "completed"
                saving.accounting_status = "closed"
    elif saving.type == "owner_personal":
        saving.owner_drawings_balance = max(saving.total_paid - saving.total_received, 0)
        saving.accounting_status = "owner_drawings" if saving.owner_drawings_balance > 0 else "closed"
        if saving.remaining_to_pay <= 0 and saving.receive_status == "received":
            saving.status = "completed"
    elif saving.type == "employee":
        saving.employee_receivable_balance = max(saving.total_paid - saving.total_received, 0)
        saving.accounting_status = (
            "employee_receivable" if saving.employee_receivable_balance > 0 else "closed"
        )

    db.session.flush()


def dashboard_stats():
    ensure_rotating_savings_schema()
    q = RotatingSaving.query.filter(RotatingSaving.deleted_at.is_(None))
    savings = q.all()
    active = [s for s in savings if s.status == "active"]
    return {
        "active_count": len(active),
        "total_paid": sum(s.total_paid for s in savings),
        "total_received": sum(s.total_received for s in savings),
        "remaining_to_pay": sum(s.remaining_to_pay for s in savings),
        "total_liability": sum(s.liability_balance for s in savings),
        "total_owner_drawings": sum(s.owner_drawings_balance for s in savings if s.type == "owner_personal"),
        "defaulted_count": sum(1 for s in savings if s.status == "defaulted"),
        "completed_count": sum(1 for s in savings if s.status == "completed"),
        "total_fees": sum(s.total_fees for s in savings),
    }


def list_journal_entries_for_saving(saving_id: int):
    entries = JournalEntry.query.filter_by(
        reference_type="rotating_saving", reference_id=saving_id
    ).order_by(JournalEntry.entry_date.desc()).all()
    return entries


def build_open_balances_report(filters=None):
    filters = filters or {}
    q = RotatingSaving.query.filter(RotatingSaving.deleted_at.is_(None))
    saving_type = (filters.get("type") or "").strip()
    status = (filters.get("status") or "").strip()
    if saving_type:
        q = q.filter(RotatingSaving.type == saving_type)
    if status:
        q = q.filter(RotatingSaving.status == status)
    rows = []
    for s in q.order_by(RotatingSaving.name).all():
        if filters.get("non_zero_only"):
            balance = s.asset_balance or s.liability_balance or s.owner_drawings_balance or s.employee_receivable_balance
            if not balance and not s.remaining_to_pay:
                continue
        last_payment = (
            RotatingSavingPayment.query.filter_by(rotating_saving_id=s.id, status="paid")
            .order_by(RotatingSavingPayment.payment_date.desc())
            .first()
        )
        rows.append({
            "saving": s,
            "last_payment_date": last_payment.payment_date if last_payment else None,
        })
    return rows


def build_warnings_report():
    warnings = []
    savings = RotatingSaving.query.filter(RotatingSaving.deleted_at.is_(None)).all()
    today = date.today()
    for s in savings:
        if s.type != "tracking_only" and not s.asset_account_id and s.type == "company":
            warnings.append({"type": "no_account", "saving": s, "message": "جمعية بدون حساب محاسبي"})
        unpaid_late = RotatingSavingPayment.query.filter(
            RotatingSavingPayment.rotating_saving_id == s.id,
            RotatingSavingPayment.status == "paid",
            RotatingSavingPayment.due_date != None,  # noqa: E711
            RotatingSavingPayment.due_date < today,
            RotatingSavingPayment.payment_date > RotatingSavingPayment.due_date,
        ).count()
        if unpaid_late:
            warnings.append({"type": "late", "saving": s, "message": f"{unpaid_late} دفعات متأخرة"})
        if s.receive_status == "received" and s.type == "company":
            receipts = RotatingSavingReceipt.query.filter_by(rotating_saving_id=s.id).all()
            if not receipts or not any(r.journal_entry_ids for r in receipts):
                warnings.append({"type": "no_receipt_entry", "saving": s, "message": "استلام بدون قيد"})
        if s.total_received > s.expected_receive_amount:
            warnings.append({"type": "over_receive", "saving": s, "message": "استلام أكبر من المتوقع"})
    return warnings


def financial_summary():
    """ملخص للتقرير المالي الشامل."""
    try:
        ensure_rotating_savings_schema()
    except Exception:
        return None
    stats = dashboard_stats()
    return {
        "active_count": stats["active_count"],
        "total_paid": stats["total_paid"],
        "total_received": stats["total_received"],
        "total_liability": stats["total_liability"],
        "total_owner_drawings": stats["total_owner_drawings"],
        "total_fees": stats["total_fees"],
    }


def _reverse_journal_entry(original: JournalEntry, description: str, saving_id: int, user_id=None):
    if not original:
        return None
    return _journal_by_ids(
        original.credit_account_id,
        original.debit_account_id,
        original.amount,
        description,
        reference_id=saving_id,
        created_by=user_id,
    )


def reverse_payment(payment_id: int, user_id=None, notes=None):
    payment = RotatingSavingPayment.query.get(payment_id)
    if not payment:
        raise RotatingSavingError("الدفعة غير موجودة")
    if payment.status == "reversed":
        raise RotatingSavingError("الدفعة معكوسة مسبقاً")
    if payment.status != "paid":
        raise RotatingSavingError("لا يمكن عكس هذه الدفعة")

    saving = payment.saving
    if saving.type == "tracking_only":
        raise RotatingSavingError("جمعية المتابعة فقط لا تدعم العكس المحاسبي")

    old_snapshot = saving_snapshot(saving)
    amount = _safe_int(payment.amount)

    if payment.journal_entry_id:
        orig = JournalEntry.query.get(payment.journal_entry_id)
        rev = _reverse_journal_entry(
            orig,
            f"عكس دفعة جمعية - {saving.name}",
            saving.id,
            user_id,
        )
        payment.reversal_journal_entry_id = rev.id if rev else None

    note = f"جمعية/سلفة دوّارة — عكس دفع قسط — {saving.name}"
    _treasury_deposit(amount, note, payment.treasury_account_id)

    if payment.fee_amount and payment.fee_journal_entry_id:
        fee_orig = JournalEntry.query.get(payment.fee_journal_entry_id)
        _reverse_journal_entry(
            fee_orig,
            f"عكس رسوم جمعية - {saving.name}",
            saving.id,
            user_id,
        )
        _treasury_deposit(payment.fee_amount, f"{note} — رسوم", payment.treasury_account_id)

    payment.status = "reversed"
    payment.reversed_at = datetime.utcnow()
    if notes:
        payment.notes = (payment.notes or "") + f"\n[معكوس] {notes}"

    recalculate_balances(saving)
    log_rotating_saving_audit(
        "reverse_payment",
        f"عكس دفعة جمعية: {saving.name} — {amount:,} د.ع",
        saving_id=saving.id,
        old_values=old_snapshot,
        new_values=saving_snapshot(saving),
        extra={"payment_id": payment.id},
        user_id=user_id,
    )
    return payment


def reverse_receipt(receipt_id: int, user_id=None, notes=None):
    receipt = RotatingSavingReceipt.query.get(receipt_id)
    if not receipt:
        raise RotatingSavingError("الاستلام غير موجود")
    if receipt.reversed_at:
        raise RotatingSavingError("الاستلام معكوس مسبقاً")

    saving = receipt.saving
    if saving.type == "tracking_only":
        raise RotatingSavingError("جمعية المتابعة فقط لا تدعم العكس المحاسبي")

    old_snapshot = saving_snapshot(saving)
    amount = _safe_int(receipt.received_amount)

    for entry_id in receipt.journal_entry_id_list():
        orig = JournalEntry.query.get(entry_id)
        _reverse_journal_entry(
            orig,
            f"عكس استلام جمعية - {saving.name}",
            saving.id,
            user_id,
        )

    note = f"جمعية/سلفة دوّارة — عكس استلام — {saving.name}"
    try:
        _treasury_withdraw(amount, note, receipt.treasury_account_id)
    except InsufficientTreasuryBalance as exc:
        raise RotatingSavingError(str(exc)) from exc

    receipt.reversed_at = datetime.utcnow()
    if notes:
        receipt.notes = (receipt.notes or "") + f"\n[معكوس] {notes}"

    active_receipts = [
        r for r in saving.receipts if not r.reversed_at and r.id != receipt.id
    ]
    if not active_receipts:
        saving.receive_status = "not_received"
        if saving.status == "received":
            saving.status = "active"

    recalculate_balances(saving)
    log_rotating_saving_audit(
        "reverse_receipt",
        f"عكس استلام جمعية: {saving.name} — {amount:,} د.ع",
        saving_id=saving.id,
        old_values=old_snapshot,
        new_values=saving_snapshot(saving),
        extra={"receipt_id": receipt.id},
        user_id=user_id,
    )
    return receipt


def build_summary_report():
    """بيانات تقرير ملخص الجمعيات مع رسوم بيانية."""
    ensure_rotating_savings_schema()
    stats = dashboard_stats()
    savings = RotatingSaving.query.filter(RotatingSaving.deleted_at.is_(None)).all()

    by_type = {}
    by_status = {}
    monthly_paid = {}
    monthly_received = {}
    open_balances = []

    for s in savings:
        by_type[s.type] = by_type.get(s.type, 0) + 1
        by_status[s.status] = by_status.get(s.status, 0) + 1
        balance = s.asset_balance or s.liability_balance or s.remaining_to_pay
        if balance:
            open_balances.append({"name": s.name, "balance": balance})

        for p in s.payments:
            if p.status != "paid":
                continue
            key = p.payment_date.strftime("%Y-%m") if p.payment_date else "unknown"
            monthly_paid[key] = monthly_paid.get(key, 0) + _safe_int(p.amount)

        for r in s.receipts:
            if r.reversed_at:
                continue
            key = r.receipt_date.strftime("%Y-%m") if r.receipt_date else "unknown"
            monthly_received[key] = monthly_received.get(key, 0) + _safe_int(r.received_amount)

    months = sorted(set(list(monthly_paid.keys()) + list(monthly_received.keys())))
    top_saving = max(savings, key=lambda x: x.total_paid, default=None) if savings else None

    not_received = [s for s in savings if s.receive_status == "not_received" and s.status == "active"]
    received_with_due = [
        s for s in savings if s.receive_status == "received" and s.liability_balance > 0
    ]

    from models.rotating_savings import SAVING_TYPES, SAVING_STATUSES

    return {
        "stats": stats,
        "by_type": [{"type": k, "label": SAVING_TYPES.get(k, k), "count": v} for k, v in by_type.items()],
        "by_status": [{"status": k, "label": SAVING_STATUSES.get(k, k), "count": v} for k, v in by_status.items()],
        "monthly_labels": months,
        "monthly_paid": [monthly_paid.get(m, 0) for m in months],
        "monthly_received": [monthly_received.get(m, 0) for m in months],
        "open_balances": sorted(open_balances, key=lambda x: x["balance"], reverse=True)[:12],
        "top_saving": top_saving,
        "not_received_count": len(not_received),
        "received_with_due_count": len(received_with_due),
        "late_count": len([w for w in build_warnings_report() if w["type"] == "late"]),
    }


def get_dashboard_alerts():
    """تنبيهات الجمعيات للوحة التحكم."""
    try:
        ensure_rotating_savings_schema()
    except Exception:
        return []

    alerts = []
    today = date.today()
    tomorrow = today + timedelta(days=1)
    savings = RotatingSaving.query.filter(
        RotatingSaving.deleted_at.is_(None),
        RotatingSaving.status == "active",
    ).all()

    for s in savings:
        if s.remaining_to_pay <= 0:
            continue
        next_due = s.start_date + timedelta(days=30 * _safe_int(s.total_paid // max(s.monthly_amount, 1)))
        if next_due == tomorrow:
            alerts.append({
                "type": "info",
                "icon": "📅",
                "message": f"موعد دفعة جمعية «{s.name}» غداً — {s.monthly_amount:,} د.ع",
                "action": f"/finance/rotating-savings/{s.id}",
            })
        elif next_due < today and s.receive_status == "not_received":
            alerts.append({
                "type": "warning",
                "icon": "⏰",
                "message": f"دفعة جمعية «{s.name}» متأخرة",
                "action": f"/finance/rotating-savings/{s.id}",
            })
        if s.receive_status == "received" and s.liability_balance > 0:
            alerts.append({
                "type": "info",
                "icon": "🔄",
                "message": f"جمعية «{s.name}» — تم الاستلام وبقي {s.liability_balance:,} د.ع التزام",
                "action": f"/finance/rotating-savings/{s.id}",
            })
        progress = s.total_paid / max(s.expected_total_to_pay, 1)
        if 0.8 <= progress < 1 and s.status == "active":
            alerts.append({
                "type": "info",
                "icon": "✅",
                "message": f"جمعية «{s.name}» قاربت على الاكتمال ({int(progress * 100)}%)",
                "action": f"/finance/rotating-savings/{s.id}",
            })

    for w in build_warnings_report()[:5]:
        alerts.append({
            "type": "warning",
            "icon": "⚠️",
            "message": f"{w['saving'].name}: {w['message']}",
            "action": f"/finance/rotating-savings/{w['saving'].id}",
        })

    return alerts[:15]


def export_savings_rows():
    """صفوف تصدير Excel/CSV."""
    rows = []
    for s in RotatingSaving.query.filter(RotatingSaving.deleted_at.is_(None)).order_by(RotatingSaving.name).all():
        rows.append({
            "الاسم": s.name,
            "النوع": s.type_label(),
            "القسط الشهري": s.monthly_amount,
            "المدفوع": s.total_paid,
            "المستلم": s.total_received,
            "المتبقي": s.remaining_to_pay,
            "رصيد الأصل": s.asset_balance,
            "رصيد الالتزام": s.liability_balance,
            "الحالة": s.status_label(),
            "حالة الاستلام": s.receive_status_label(),
        })
    return rows


def export_statement_rows(saving: RotatingSaving):
    rows = []
    for p in saving.payments:
        rows.append({
            "النوع": "دفعة",
            "التاريخ": str(p.payment_date),
            "المبلغ": p.amount,
            "الحالة": p.status_label(),
            "ملاحظات": p.notes or "",
        })
    for r in saving.receipts:
        if r.reversed_at:
            continue
        rows.append({
            "النوع": "استلام",
            "التاريخ": str(r.receipt_date),
            "المبلغ": r.received_amount,
            "الحالة": "مستلم",
            "ملاحظات": r.notes or "",
        })
    return rows
