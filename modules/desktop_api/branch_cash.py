"""Branch cash transfers (FINORA Management Desktop) — JSON over utils/branch_cash_transfers.

Every rule is enforced here on the server: who may request, approve, confirm receipt, reject or cancel, the
balance, replay protection and the closed-period guard. The UI only reflects ``can_*`` flags returned per row.
"""
from __future__ import annotations

from typing import Any

from flask import g, jsonify, request, session

from extensions import db
from models.branch import Branch
from models.branch_cash_transfer import STATUSES, BranchCashTransfer
from models.treasury_account import TreasuryAccount
from modules.desktop_api.routes import _error, desktop_api_bp
from utils import branch_cash_transfers as service
from utils.branch_context import init_branch_context
from utils.branch_management import BranchError
from utils.branch_scope import current_employee
from utils.permission_checks import employee_can

PREFIX = "/branch-cash"


def _ok(**data: Any):
    return jsonify({"ok": True, **data})


def _authorize():
    if not session.get("user_id") or not session.get("tenant_slug"):
        return _error("انتهت الجلسة، سجّل الدخول من جديد", 401, "unauthenticated")
    if str(getattr(g, "tenant", "")) != session["tenant_slug"]:
        return _error("تعذر تحديد الشركة", 403, "tenant_required")
    employee = current_employee()
    if employee is None:
        return _error("انتهت الجلسة، سجّل الدخول من جديد", 401, "unauthenticated")
    if not employee_can(employee, "can_see_accounts"):
        return _error("ليست لديك صلاحية الحسابات لهذا الإجراء", 403, "forbidden")
    if not getattr(g, "branch_scope_ready", False):
        init_branch_context()
    service.ensure_table()
    return None


def _guard(run):
    try:
        return run()
    except BranchError as exc:
        db.session.rollback()
        return _error(str(exc), exc.status, exc.code)


def _document(doc_id: int):
    employee = current_employee()
    doc = service.visible_query(employee).filter(BranchCashTransfer.id == doc_id).first()
    if doc is not None and doc.status == "posting":
        doc = service.reconcile(doc)
    return doc, employee


@desktop_api_bp.get(f"{PREFIX}/meta")
def branch_cash_meta():
    denied = _authorize()
    if denied:
        return denied
    employee = current_employee()
    admin = bool(employee and employee.role == "admin")
    branches = {b.id: b.name for b in Branch.query.execution_options(skip_branch_scope=True).all()}
    accounts = []
    for account in (TreasuryAccount.query.execution_options(skip_branch_scope=True)
                    .filter_by(is_active=True).order_by(TreasuryAccount.branch_id, TreasuryAccount.name).all()):
        if not account.branch_id:
            continue
        own = admin or int(account.branch_id) in service._assigned(employee)
        accounts.append({
            "id": account.id, "name": account.name, "type": account.account_type,
            "branch_id": account.branch_id, "branch_name": branches.get(account.branch_id, ""),
            "can_send_from": bool(own),
            # another branch's balance is not shown to a non-admin
            "balance": service._balance(account.id) if own else None,
        })
    return _ok(accounts=accounts, can_execute_now=admin, statuses=STATUSES,
               pending=service.pending_summary(employee))


@desktop_api_bp.get(PREFIX)
def branch_cash_list():
    denied = _authorize()
    if denied:
        return denied
    employee = current_employee()
    query = service.visible_query(employee)
    status = (request.args.get("status") or "").strip()
    if status in STATUSES:
        query = query.filter(BranchCashTransfer.status == status)
    elif status == "open":
        query = query.filter(BranchCashTransfer.status.in_(("pending", "approved")))
    search = (request.args.get("search") or "").strip()
    if search:
        query = query.filter(db.or_(BranchCashTransfer.number.ilike(f"%{search}%"),
                                    BranchCashTransfer.reference.ilike(f"%{search}%"),
                                    BranchCashTransfer.reason.ilike(f"%{search}%")))
    rows = query.order_by(BranchCashTransfer.id.desc()).limit(200).all()
    return _ok(rows=[service.serialize(r, employee) for r in rows], pending=service.pending_summary(employee))


@desktop_api_bp.get(f"{PREFIX}/<int:doc_id>")
def branch_cash_detail(doc_id: int):
    denied = _authorize()
    if denied:
        return denied
    doc, employee = _document(doc_id)
    if doc is None:
        return _error("التحويل غير موجود أو خارج نطاقك", 404, "not_found")
    return _ok(transfer=service.serialize(doc, employee))


@desktop_api_bp.post(PREFIX)
def branch_cash_create():
    denied = _authorize()
    if denied:
        return denied

    def run():
        employee = current_employee()
        data = request.get_json(silent=True) or {}
        doc = service.create(data, employee, execute_now=bool(data.get("execute_now")))
        return _ok(transfer=service.serialize(db.session.get(BranchCashTransfer, doc.id), employee))

    return _guard(run)


def _action(doc_id: int, name: str):
    denied = _authorize()
    if denied:
        return denied

    def run():
        doc, employee = _document(doc_id)
        if doc is None:
            return _error("التحويل غير موجود أو خارج نطاقك", 404, "not_found")
        data = request.get_json(silent=True) or {}
        if name == "approve":
            service.approve(doc, employee)
        elif name == "receive":
            doc = service.receive(doc, employee)
        elif name == "reject":
            service.reject(doc, employee, data.get("reason", ""))
        else:
            service.cancel(doc, employee, data.get("reason", ""))
        _audit(name, db.session.get(BranchCashTransfer, doc_id))
        return _ok(transfer=service.serialize(db.session.get(BranchCashTransfer, doc_id), employee))

    return _guard(run)


for _name in ("approve", "receive", "reject", "cancel"):
    desktop_api_bp.add_url_rule(
        f"{PREFIX}/<int:doc_id>/{_name}", endpoint=f"branch_cash_{_name}",
        view_func=(lambda n: (lambda doc_id: _action(doc_id, n)))(_name), methods=["POST"])


def _audit(action: str, doc: BranchCashTransfer | None) -> None:
    if doc is None:
        return
    try:
        from utils.activity_logger import log_activity

        log_activity(action, "finance", f"تحويل نقدي {doc.number}: {action}", entity_type="branch_cash_transfer",
                     entity_id=doc.id, payload={"amount": int(doc.amount), "from_branch_id": doc.from_branch_id,
                                                "to_branch_id": doc.to_branch_id, "status": doc.status})
    except Exception:
        pass
