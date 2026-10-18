"""Branch cash transfers — request → approval → receipt confirmation → one atomic posting.

Money is posted exactly once, at receipt confirmation, by FINORA's own ``record_treasury_transfer`` (both legs,
balance re-checked under lock, balanced journal through the ledger sync). This service only adds the document,
the approvals, replay protection and the audit trail around it.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, update

from extensions import db
from models.branch import Branch
from models.branch_cash_transfer import STATUSES, BranchCashTransfer
from models.treasury_account import TreasuryAccount
from utils.branch_management import BranchError, all_branches_view

MAX_AMOUNT = 9_007_199_254_740_991  # stays exactly representable in the desktop client
POSTING_STALE_AFTER = timedelta(minutes=2)  # a «posting» older than this was interrupted, not in flight


# ───────────────────────────── helpers ─────────────────────────────


def ensure_table() -> None:
    BranchCashTransfer.__table__.create(bind=db.session.connection(), checkfirst=True)


def _account(account_id: Any) -> TreasuryAccount | None:
    try:
        wanted = int(account_id)
    except (TypeError, ValueError):
        return None
    return (TreasuryAccount.query.execution_options(skip_branch_scope=True)
            .filter_by(id=wanted, is_active=True).first())


def _balance(account_id: int) -> int:
    from utils.treasury_calculations import calculate_treasury_balance

    with all_branches_view():
        return int(calculate_treasury_balance(account_id) or 0)


def business_today() -> date:
    from modules.finance.common import today

    return today()


def _number() -> str:
    prefix = f"BCT-{business_today().strftime('%Y%m%d')}-"
    last = (BranchCashTransfer.query.filter(BranchCashTransfer.number.like(f"{prefix}%"))
            .order_by(BranchCashTransfer.id.desc()).first())
    sequence = int(last.number.rsplit("-", 1)[-1]) + 1 if last else 1
    return f"{prefix}{sequence:04d}"


def _log(doc: BranchCashTransfer, action: str, user, **extra: Any) -> None:
    try:
        events = json.loads(doc.events_json or "[]")
    except (TypeError, ValueError):
        events = []
    events.append({"action": action, "by": getattr(user, "id", None), "name": getattr(user, "name", ""),
                   "at": datetime.utcnow().strftime("%Y-%m-%d %H:%M"), "status": doc.status, **extra})
    doc.events_json = json.dumps(events, ensure_ascii=False)


def _is_admin(user) -> bool:
    return bool(user and user.role == "admin")


def _assigned(user) -> list[int]:
    from utils.branch_assignments import assigned_branch_ids

    return assigned_branch_ids(user) if user is not None else []


def _same_branch(user, branch_id: int) -> bool:
    return int(branch_id) in _assigned(user)


def _claim(doc: BranchCashTransfer, allowed: set[str], target: str, **fields: Any) -> None:
    result = db.session.execute(
        update(BranchCashTransfer)
        .where(BranchCashTransfer.id == doc.id, BranchCashTransfer.status.in_(allowed))
        .values(status=target, updated_at=datetime.utcnow(), **fields)
        .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise BranchError("تغيرت حالة التحويل أو عولج من جهاز آخر؛ حدّث القائمة", "conflict", 409)
    db.session.refresh(doc)


def _assert_period_open(on: date, what: str) -> None:
    from utils.financial_period_guard import PeriodClosedError, assert_date_period_open

    try:
        assert_date_period_open(on, what)
    except PeriodClosedError as exc:
        raise BranchError(str(exc), "period_closed", 409) from None


# ───────────────────────────── read model ─────────────────────────────


def capabilities(doc: BranchCashTransfer, user) -> dict[str, bool]:
    open_ = doc.status in ("pending", "approved")  # «posting» is neither: wait for it or let it be reconciled
    admin = _is_admin(user)
    receiver = admin or _same_branch(user, doc.to_branch_id)
    return {
        "can_approve": doc.status == "pending" and admin,
        "can_receive": doc.status == "approved" and receiver,
        "can_reject": open_ and receiver,
        "can_cancel": open_ and (admin or (user is not None and doc.requested_by_id == user.id)),
    }


def serialize(doc: BranchCashTransfer, user=None) -> dict[str, Any]:
    from models.employee import Employee

    source = _any_account(doc.from_account_id)
    target = _any_account(doc.to_account_id)
    branches = {b.id: b.name for b in Branch.query.execution_options(skip_branch_scope=True)
                .filter(Branch.id.in_([doc.from_branch_id, doc.to_branch_id])).all()}
    names = {}
    ids = {i for i in (doc.requested_by_id, doc.approved_by_id, doc.received_by_id) if i}
    if ids:
        names = {e.id: e.name for e in Employee.query.execution_options(skip_branch_scope=True)
                 .filter(Employee.id.in_(ids)).all()}
    try:
        events = json.loads(doc.events_json or "[]")
    except (TypeError, ValueError):
        events = []
    return {
        "id": doc.id, "number": doc.number, "status": doc.status, "status_label": STATUSES.get(doc.status, doc.status),
        "amount": int(doc.amount), "currency": doc.currency,
        "from_account_id": doc.from_account_id, "from_account": source.name if source else "—",
        "to_account_id": doc.to_account_id, "to_account": target.name if target else "—",
        "from_branch_id": doc.from_branch_id, "from_branch": branches.get(doc.from_branch_id, "—"),
        "to_branch_id": doc.to_branch_id, "to_branch": branches.get(doc.to_branch_id, "—"),
        "transfer_date": doc.transfer_date.isoformat() if doc.transfer_date else "",
        "reference": doc.reference or "", "reason": doc.reason, "notes": doc.notes or "",
        "requested_by": names.get(doc.requested_by_id, ""), "approved_by": names.get(doc.approved_by_id, ""),
        "received_by": names.get(doc.received_by_id, ""), "closed_reason": doc.closed_reason or "",
        "created_at": doc.created_at.strftime("%Y-%m-%d %H:%M") if doc.created_at else "",
        "completed_at": doc.completed_at.strftime("%Y-%m-%d %H:%M") if doc.completed_at else "",
        "posted": doc.treasury_transfer_id is not None, "events": events,
        **(capabilities(doc, user) if user is not None else {}),
    }


def _any_account(account_id: int) -> TreasuryAccount | None:
    return (TreasuryAccount.query.execution_options(skip_branch_scope=True).filter_by(id=account_id).first())


def visible_query(user):
    query = BranchCashTransfer.query
    if _is_admin(user):
        return query
    ids = _assigned(user) or [-1]
    return query.filter(or_(BranchCashTransfer.from_branch_id.in_(ids), BranchCashTransfer.to_branch_id.in_(ids)))


def pending_summary(user) -> dict[str, int]:
    row = (visible_query(user).filter(BranchCashTransfer.status.in_(("pending", "approved", "posting")))
           .with_entities(func.count(BranchCashTransfer.id), func.coalesce(func.sum(BranchCashTransfer.amount), 0)).one())
    return {"count": int(row[0] or 0), "amount": int(row[1] or 0)}


# ───────────────────────────── operations ─────────────────────────────


def create(data: dict[str, Any], user, *, execute_now: bool = False) -> BranchCashTransfer:
    ensure_table()
    operation_id = str(data.get("operation_id") or "").strip()[:64] or None
    source, target = _account(data.get("from_account_id")), _account(data.get("to_account_id"))
    try:
        amount = int(data.get("amount"))
    except (TypeError, ValueError):
        raise BranchError("أدخل مبلغاً صحيحاً") from None
    if operation_id:
        existing = BranchCashTransfer.query.filter_by(operation_id=operation_id).first()
        if existing is not None:
            same = (existing.from_account_id, existing.to_account_id, int(existing.amount)) == (
                int(data.get("from_account_id") or 0), int(data.get("to_account_id") or 0), amount)
            if not same:
                raise BranchError("معرّف العملية مستخدم لتحويل مختلف", "conflict", 409)
            return existing  # exact replay: the same document, nothing created twice
    if source is None or target is None:
        raise BranchError("اختر صندوقين فعّالين للتحويل")
    if source.id == target.id:
        raise BranchError("لا يمكن التحويل من الصندوق إلى نفسه")
    if not source.branch_id or not target.branch_id:
        raise BranchError("ربط الصندوقين بفرعيهما مطلوب أولاً")
    if not 0 < amount <= MAX_AMOUNT:
        raise BranchError("مبلغ التحويل يجب أن يكون أكبر من صفر")
    if not _is_admin(user) and not _same_branch(user, source.branch_id):
        raise BranchError("لا يمكنك التحويل إلا من صناديق فرعك", "forbidden", 403)
    if execute_now and not _is_admin(user):
        raise BranchError("التنفيذ المباشر للمدير العام فقط", "forbidden", 403)
    reason = str(data.get("reason") or "").strip()
    if len(reason) < 3:
        raise BranchError("اكتب سبب التحويل")
    try:
        on = date.fromisoformat(str(data.get("transfer_date") or business_today().isoformat())[:10])
    except ValueError:
        raise BranchError("تاريخ التحويل غير صالح") from None
    if on > business_today():
        raise BranchError("لا يمكن تسجيل تحويل بتاريخ مستقبلي")
    _assert_period_open(on, "تحويل نقدي بين الفروع")
    if _balance(source.id) < amount:
        raise BranchError("رصيد الصندوق المصدر لا يكفي لهذا التحويل", "insufficient_funds", 409)

    doc = BranchCashTransfer(
        number=_number(), operation_id=operation_id, from_account_id=source.id, to_account_id=target.id,
        from_branch_id=source.branch_id, to_branch_id=target.branch_id, amount=amount, transfer_date=on,
        reference=str(data.get("reference") or "").strip()[:100] or None, reason=reason[:255],
        notes=str(data.get("notes") or "").strip() or None, status="pending", requested_by_id=user.id)
    db.session.add(doc)
    db.session.flush()
    _log(doc, "create", user)
    db.session.commit()
    if execute_now:
        approve(doc, user)
        receive(doc, user)
    return doc


def approve(doc: BranchCashTransfer, user) -> BranchCashTransfer:
    if not _is_admin(user):
        raise BranchError("اعتماد تحويل الأموال للمدير العام", "forbidden", 403)
    _assert_period_open(doc.transfer_date, "اعتماد تحويل نقدي")
    _claim(doc, {"pending"}, "approved", approved_by_id=user.id, approved_at=datetime.utcnow())
    _log(doc, "approve", user)
    db.session.commit()
    return doc


def _posted_transfer(doc: BranchCashTransfer):
    from models.treasury_transfer import TreasuryTransfer

    return (TreasuryTransfer.query.execution_options(skip_branch_scope=True)
            .filter(TreasuryTransfer.note.like(f"{doc.number} —%")).first())


def reconcile(doc: BranchCashTransfer) -> BranchCashTransfer:
    """Resolve a document stuck in «posting» after an interrupted request (crash, killed process).

    Posted already (the treasury transfer carries the document number) → complete it; never posted → back to
    «approved» so it can be confirmed again. A «posting» younger than two minutes is left alone: another
    request may still be finishing it."""
    if doc.status != "posting":
        return doc
    if doc.updated_at and datetime.utcnow() - doc.updated_at < POSTING_STALE_AFTER:
        return doc
    transfer = _posted_transfer(doc)
    if transfer is not None:
        _claim(doc, {"posting"}, "completed", completed_at=datetime.utcnow(), treasury_transfer_id=transfer.id)
        _log(doc, "reconcile", None, outcome="completed", treasury_transfer_id=transfer.id)
    else:
        _claim(doc, {"posting"}, "approved", received_by_id=None)
        _log(doc, "reconcile", None, outcome="reverted")
    db.session.commit()
    return doc


def receive(doc: BranchCashTransfer, user) -> BranchCashTransfer:
    """Confirm receipt: claim → post both legs through the proven engine → complete.

    The claim is COMMITTED before posting (the engine commits internally, so an uncommitted claim cannot be
    relied on to roll back). On a refusal the claim is explicitly reverted; if the process dies in between,
    ``reconcile`` decides from the treasury transfer's note whether the money was posted."""
    from utils.treasury_calculations import InsufficientTreasuryBalance, record_treasury_transfer

    if not (_is_admin(user) or _same_branch(user, doc.to_branch_id)):
        raise BranchError("تأكيد الاستلام لموظف الفرع المستلم أو المدير العام", "forbidden", 403)
    doc = reconcile(doc)
    if doc.status == "completed":
        raise BranchError("التحويل مكتمل ومرحَّل مسبقاً", "conflict", 409)
    if doc.status == "posting":
        raise BranchError("التحويل قيد الترحيل الآن؛ حدّث بعد لحظات", "conflict", 409)
    _assert_period_open(doc.transfer_date, "تأكيد استلام تحويل نقدي")
    doc_id = doc.id
    _claim(doc, {"approved"}, "posting", received_by_id=user.id)
    db.session.commit()

    def revert() -> None:
        db.session.rollback()
        fresh = db.session.get(BranchCashTransfer, doc_id)
        if fresh is not None and fresh.status == "posting":
            _claim(fresh, {"posting"}, "approved", received_by_id=None)
            db.session.commit()

    try:
        transfer = record_treasury_transfer(
            doc.from_account_id, doc.to_account_id, int(doc.amount), f"{doc.number} — {doc.reason}"[:255],
            allow_cross_branch=True)
    except InsufficientTreasuryBalance as exc:
        revert()
        raise BranchError(str(exc) or "رصيد الصندوق المصدر لا يكفي", "insufficient_funds", 409) from None
    except ValueError as exc:
        revert()
        raise BranchError(str(exc), "conflict", 409) from None
    except Exception:
        db.session.rollback()
        fresh = db.session.get(BranchCashTransfer, doc_id)
        if fresh is not None:
            fresh.updated_at = datetime.utcnow() - POSTING_STALE_AFTER  # let reconcile decide right away
            db.session.commit()
            reconcile(fresh)
        raise
    fresh = db.session.get(BranchCashTransfer, doc_id)
    _claim(fresh, {"posting"}, "completed", completed_at=datetime.utcnow(), treasury_transfer_id=transfer.id)
    _log(fresh, "receive", user, treasury_transfer_id=transfer.id)
    db.session.commit()
    return fresh


def reject(doc: BranchCashTransfer, user, reason: str) -> BranchCashTransfer:
    if not (_is_admin(user) or _same_branch(user, doc.to_branch_id)):
        raise BranchError("الرفض للفرع المستلم أو المدير العام", "forbidden", 403)
    text = str(reason or "").strip()
    if len(text) < 3:
        raise BranchError("اكتب سبب الرفض")
    _claim(doc, {"pending", "approved"}, "rejected", closed_reason=text[:255])
    _log(doc, "reject", user, reason=text[:255])
    db.session.commit()
    return doc


def cancel(doc: BranchCashTransfer, user, reason: str) -> BranchCashTransfer:
    if not (_is_admin(user) or doc.requested_by_id == user.id):
        raise BranchError("الإلغاء لمن أنشأ التحويل أو المدير العام", "forbidden", 403)
    text = str(reason or "").strip()
    if len(text) < 3:
        raise BranchError("اكتب سبب الإلغاء")
    _claim(doc, {"pending", "approved"}, "cancelled", closed_reason=text[:255])
    _log(doc, "cancel", user, reason=text[:255])
    db.session.commit()
    return doc
