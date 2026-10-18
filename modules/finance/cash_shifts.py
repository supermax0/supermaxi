"""Retry-safe cash drawer shifts, separate from the always-live daily report."""
import hashlib
import json
from datetime import datetime
from sqlalchemy import or_

from extensions import db
from utils.branch_scope import is_general_admin
from utils.treasury_calculations import calculate_treasury_balance, get_treasury_movements
from . import ledger
from .common import FinanceError, actor, audit, dumps, get_row, money, require, scope, tenant_key, text, version, write_branch
from .models import FinanceCashShift


def _state(account_id):
    from utils.branch_mode import independent_branches_enabled
    from utils.treasury_helpers import get_default_cash_account
    shared = not independent_branches_enabled()
    if shared:
        account_id = get_default_cash_account().id
    # Capture source identity as well as balance: equal-value edits need review too.
    movements = []
    for row in get_treasury_movements(account_id):
        movements.append({
            "key": row.get("movement_key") or f"{row.get('reference_type')}:{row.get('reference_id')}",
            "at": str(row.get("datetime") or row.get("date")),
            "type": row.get("type"), "amount": int(row.get("amount") or 0),
        })
    movements.sort(key=lambda item: (str(item["key"]), item["at"], item["amount"]))
    balance = int(calculate_treasury_balance(account_id))
    fingerprint = hashlib.sha256(dumps({"balance": balance, "movements": movements, "shared_cash": shared}).encode()).hexdigest()
    return {"balance": balance, "fingerprint": fingerprint, "movement_count": len(movements), "shared_cash": shared}


def open_shift(payload):
    require("finance.create")
    account = ledger.treasury(payload.get("treasury_account_id"))
    if not account.is_cash:
        raise FinanceError("اختر الصندوق النقدي المسموح؛ الصندوق المشترك له وردية واحدة")
    from utils.branch_mode import independent_branches_enabled
    branch_id = account.branch_id or write_branch(payload)
    shared = not independent_branches_enabled()
    key = f"{tenant_key()}:{'shared-cash' if shared else account.id}"
    # This check intentionally ignores UI branch filters for a shared drawer.
    existing = FinanceCashShift.query.execution_options(skip_branch_scope=True).filter_by(tenant_key=tenant_key(), status="open")
    if not shared:
        existing = existing.filter(or_(FinanceCashShift.treasury_account_id == account.id,
            FinanceCashShift.open_account_key == f"{tenant_key()}:shared-cash"))
    if existing.first():
        raise FinanceError("للصندوق وردية مفتوحة؛ أغلقها أولاً", "conflict", 409)
    actual = money(payload.get("opening_actual"), minimum=0)
    state = _state(account.id)
    reason = text(payload.get("reason"), 1500)
    if actual != state["balance"] and not reason:
        raise FinanceError("سبب فرق الرصيد الافتتاحي مطلوب")
    row = FinanceCashShift(tenant_key=tenant_key(), branch_id=branch_id,
        treasury_account_id=account.id, open_account_key=key, name=text(payload.get("name"), 100, True),
        opened_by=actor().id, opening_actual=actual, opening_ledger=state["balance"],
        opening_reason=reason, snapshot=dumps({"opening": state}))
    db.session.add(row)
    db.session.flush()
    audit("open", "cash_shift", row, {"actual": actual, "ledger": state["balance"], "reason": reason})
    return serialize(row)


def preview(row):
    require("finance.view")
    ledger.treasury(row.treasury_account_id)
    state = _state(row.treasury_account_id)
    if json.loads(row.snapshot)["opening"].get("shared_cash") != state["shared_cash"]:
        raise FinanceError("تغيّر نمط الصندوق المشترك والفروع؛ أعد النمط الأصلي وراجع الوردية قبل الإقفال", "conflict", 409)
    expected = row.opening_actual + state["balance"] - row.opening_ledger
    token = hashlib.sha256(dumps({"id": row.id, "version": row.version, "state": state}).encode()).hexdigest()
    return {"ledger": state["balance"], "expected": expected,
        "net_movement": state["balance"] - row.opening_ledger, "token": token,
        "movement_count": state["movement_count"], "fingerprint": state["fingerprint"]}


def close_shift(row, payload):
    require("finance.approve")
    ledger.treasury(row.treasury_account_id)
    if row.opened_by != actor().id and not is_general_admin(actor()):
        raise FinanceError("إغلاق وردية موظف آخر متاح للإدارة فقط", "forbidden", 403)
    version(row, payload)
    if row.status != "open":
        raise FinanceError("الوردية مغلقة ولا تقبل التعديل", "conflict", 409)
    current = preview(row)
    if payload.get("preview_token") != current["token"]:
        raise FinanceError("تغيّرت حركات الصندوق؛ حدّث المعاينة قبل الإغلاق", "conflict", 409)
    actual = money(payload.get("actual"), minimum=0)
    reason = text(payload.get("reason"), 1500)
    variance = actual - current["expected"]
    if variance and not reason:
        raise FinanceError("سبب العجز أو الزيادة مطلوب قبل الإغلاق")
    row.status, row.open_account_key = "closed", None
    row.closed_by, row.closed_at = actor().id, datetime.utcnow()
    row.closer = actor()
    row.closing_actual, row.closing_ledger = actual, current["ledger"]
    row.expected, row.variance, row.closing_reason = current["expected"], variance, reason
    row.version += 1
    row.snapshot = dumps({**json.loads(row.snapshot), "closing": current})
    audit("close", "cash_shift", row, {"actual": actual, "expected": row.expected, "variance": variance, "reason": reason})
    return serialize(row)


def serialize(row):
    return {"id": row.id, "name": row.name, "branch_id": row.branch_id,
        "treasury_account_id": row.treasury_account_id, "account_name": row.account.name,
        "status": row.status, "version": row.version,
        "opened_by": row.opener.name, "closed_by": row.closer.name if row.closer else None,
        "opened_at": row.opened_at.isoformat(), "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "opening_actual": row.opening_actual, "opening_ledger": row.opening_ledger,
        "opening_variance": row.opening_actual - row.opening_ledger, "opening_reason": row.opening_reason,
        "actual": row.closing_actual, "ledger": row.closing_ledger, "expected": row.expected,
        "variance": row.variance, "reason": row.closing_reason}


def listing(args):
    query = scope(FinanceCashShift.query, FinanceCashShift).filter_by(tenant_key=tenant_key())
    if args.get("status"):
        if args["status"] not in {"open", "closed"}:
            raise FinanceError("حالة الوردية غير صحيحة")
        query = query.filter_by(status=args["status"])
    page = money(args.get("page", 1))
    size = min(100, money(args.get("page_size", 25)))
    return {"items": [serialize(row) for row in query.order_by(FinanceCashShift.id.desc()).offset((page-1)*size).limit(size)],
        "total": query.count(), "page": page, "page_size": size}


def details(row_id):
    row = get_row(FinanceCashShift, row_id)
    result = serialize(row)
    if row.status == "open":
        result["preview"] = preview(row)
    else:
        state = _state(row.treasury_account_id)
        result["ledger_changed_since_close"] = state["fingerprint"] != json.loads(row.snapshot)["closing"]["fingerprint"]
    return result


def guard_result(result):
    """A cached command response must still respect the current branch scope."""
    row = scope(FinanceCashShift.query, FinanceCashShift).filter_by(
        id=money(result["id"]), tenant_key=tenant_key()).first()
    if row is None:
        raise FinanceError("السجل غير موجود أو خارج الفروع المسموحة", "not_found", 404)
    return result
