"""Statement matching is evidence, never an implicit balance adjustment."""
from datetime import datetime
from extensions import db
from utils.treasury_calculations import get_treasury_movements
from utils.cash_movement_values import signed_movement_amount
from . import ledger
from .common import FinanceError, actor, audit, day, get_row, money, require, text
from .models import FinanceReconciliation, FinanceReconciliationLine


def movements(account, starts=None, ends=None):
    result = []
    for row in get_treasury_movements(account.id):
        on = row["date"]
        if (starts and on < starts) or (ends and on > ends):
            continue
        amount = signed_movement_amount(row)
        result.append({"key": row.get("movement_key") or f"{row.get('reference_type')}:{row.get('reference_id')}",
            "date": on.isoformat(), "amount": amount, "note": row.get("note") or row.get("description") or "",
            "balance_after": row.get("balance_after", 0)})
    return result


def create(payload):
    require("finance.reconcile")
    account = ledger.treasury(payload.get("treasury_account_id"))
    if account.is_cash:
        raise FinanceError("المطابقة المصرفية تخص البنك أو المحفظة")
    starts, ends = day(payload.get("starts_on")), day(payload.get("ends_on"))
    if ends < starts:
        raise FinanceError("نهاية الكشف تسبق بدايته")
    rows = payload.get("lines")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 2000:
        raise FinanceError("أدخل كشفاً يحتوي بين 1 و2000 حركة")
    opening = money(payload.get("opening_balance"), minimum=-9_000_000_000_000_000)
    closing = money(payload.get("closing_balance"), minimum=-9_000_000_000_000_000)
    normalized = []
    for item in rows:
        on = day(item.get("date"))
        amount = money(item.get("amount"), minimum=-9_000_000_000_000_000)
        if not starts <= on <= ends or amount == 0:
            raise FinanceError("تاريخ أو مبلغ حركة الكشف غير صالح")
        normalized.append((on, amount, text(item.get("reference"), 150)))
    if opening + sum(item[1] for item in normalized) != closing:
        raise FinanceError("الرصيد الافتتاحي والحركات لا يساويان رصيد إقفال الكشف")
    row = FinanceReconciliation(branch_id=account.branch_id, treasury_account_id=account.id,
        starts_on=starts, ends_on=ends, opening_balance=opening, closing_balance=closing,
        created_by=actor().id, notes=text(payload.get("notes"), 1500))
    db.session.add(row)
    db.session.flush()
    used = {item[0] for item in db.session.query(FinanceReconciliationLine.ledger_key).filter(
        FinanceReconciliationLine.treasury_account_id == account.id, FinanceReconciliationLine.ledger_key.isnot(None)).all()}
    candidates = movements(account, starts, ends)
    # Ambiguous equal payments remain unmatched. A reference or manual review must resolve them.
    for on, amount, reference in normalized:
        matching = [item for item in candidates if item["date"] == on.isoformat() and item["amount"] == amount and item["key"] not in used]
        key = matching[0]["key"] if len(matching) == 1 else None
        if key:
            used.add(key)
        db.session.add(FinanceReconciliationLine(reconciliation_id=row.id, treasury_account_id=account.id,
            transaction_date=on, amount=amount, reference=reference, ledger_key=key))
    db.session.flush()
    finish(row)
    audit("create", "reconciliation", row)
    return row


def finish(row, persist=True):
    account = ledger.treasury(row.treasury_account_id)
    all_movements = movements(account)
    before = sum(item["amount"] for item in all_movements if item["date"] < row.starts_on.isoformat())
    end = sum(item["amount"] for item in all_movements if item["date"] <= row.ends_on.isoformat())
    lines = FinanceReconciliationLine.query.filter_by(reconciliation_id=row.id).all()
    if persist:
        row.status = "matched" if all(item.ledger_key for item in lines) and before == row.opening_balance and end == row.closing_balance else "pending"
    return before, end


def match(row, payload):
    require("finance.reconcile")
    line = FinanceReconciliationLine.query.filter_by(id=money(payload.get("line_id")), reconciliation_id=row.id).first()
    if not line:
        raise FinanceError("حركة الكشف غير موجودة", "not_found", 404)
    key = text(payload.get("ledger_key"), 100, True)
    account = ledger.treasury(row.treasury_account_id)
    candidate = next((item for item in movements(account, row.starts_on, row.ends_on) if item["key"] == key), None)
    used = FinanceReconciliationLine.query.filter_by(treasury_account_id=account.id, ledger_key=key).first()
    if not candidate or candidate["amount"] != line.amount or (used and used.id != line.id):
        raise FinanceError("الحركة لا تطابق المبلغ أو تمت مطابقتها مسبقاً", "conflict", 409)
    line.ledger_key = key
    db.session.flush()
    finish(row)
    audit("match", "reconciliation", row, {"line_id": line.id, "ledger_key": key, "reason": text(payload.get("reason"), 500, True)})
    return row


def serialize(row):
    before, end = finish(row, persist=False)
    return {"id": row.id, "treasury_account_id": row.treasury_account_id, "starts_on": row.starts_on.isoformat(),
        "ends_on": row.ends_on.isoformat(), "opening_balance": row.opening_balance, "closing_balance": row.closing_balance,
        "ledger_opening": before, "ledger_closing": end, "difference": row.closing_balance-end,
        "status": row.status, "lines": [{"id": line.id, "date": line.transaction_date.isoformat(),
            "amount": line.amount, "reference": line.reference, "ledger_key": line.ledger_key} for line in
            FinanceReconciliationLine.query.filter_by(reconciliation_id=row.id).order_by(FinanceReconciliationLine.id).all()],
        "candidates": movements(ledger.treasury(row.treasury_account_id), row.starts_on, row.ends_on)}
