"""JSON API for receipts & settlements."""
from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, jsonify, request, session

from extensions import db
from modules.receipts.schema_guard import ensure_receipts_schema
from modules.receipts.services import allocation as allocation_svc
from modules.receipts.services import movements_feed
from modules.receipts.services import party_search
from modules.receipts.services import receipt_service
from modules.receipts.services import settlements
from modules.receipts.services import source_summary as summary_svc
from modules.receipts.services.helpers import (
    PAYMENT_METHODS,
    ReceiptError,
    parse_int,
)
from utils.decorators import permission_required_api
from utils.permission_checks import check_permission, get_current_employee
from utils.supplier_payment_ops import SupplierPaymentError

receipts_api_bp = Blueprint("receipts_api", __name__, url_prefix="/api/receipts")


@receipts_api_bp.before_request
def _api_schema():
    ensure_receipts_schema()


def _ok(data=None, **extra):
    payload = {"success": True, "data": data}
    payload.update(extra)
    return jsonify(payload)


def _err(exc, status=400):
    if isinstance(exc, ReceiptError):
        code = getattr(exc, "code", None)
        if code == "forbidden":
            status = 403
        return jsonify({"success": False, "error": exc.message, "code": code}), status
    if isinstance(exc, SupplierPaymentError):
        return jsonify({"success": False, "error": exc.message, "code": exc.code}), status
    msg = str(getattr(exc, "message", None) or exc)
    return jsonify({"success": False, "error": msg}), status


def _tid():
    return session.get("tenant_id")


def _emp_id():
    emp = get_current_employee()
    return emp.id if emp else None


def _period_dates(period: str, date_from=None, date_to=None):
    today = date.today()
    period = (period or "").strip()
    if date_from or date_to:
        return date_from, date_to
    if period == "yesterday":
        d = today - timedelta(days=1)
        return d.isoformat(), d.isoformat()
    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start.isoformat(), today.isoformat()
    if period == "month":
        start = today.replace(day=1)
        return start.isoformat(), today.isoformat()
    if period == "custom":
        return date_from, date_to
    return today.isoformat(), today.isoformat()


def _filters_from_request():
    period = request.args.get("period") or (request.get_json(silent=True) or {}).get("period")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    df, dt = _period_dates(period, date_from, date_to)
    return {
        "q": request.args.get("q") or request.args.get("search"),
        "status": request.args.get("status"),
        "source_type": request.args.get("source_type"),
        "source_id": request.args.get("source_id"),
        "payment_method": request.args.get("payment_method"),
        "created_by": request.args.get("created_by"),
        "treasury_account_id": request.args.get("treasury_account_id"),
        "kind": request.args.get("kind") or request.args.get("movement_type"),
        "subtype": request.args.get("subtype"),
        "date_from": df,
        "date_to": dt,
        "period": period or "today",
        "page": request.args.get("page"),
        "per_page": request.args.get("per_page"),
    }


def _capabilities():
    return {
        "can_create_receipt": check_permission("create_receipts"),
        "can_pay_supplier": check_permission("manage_suppliers")
        or check_permission("can_manage_suppliers"),
        "can_add_expense": check_permission("view_expenses")
        or check_permission("can_see_expenses"),
        "can_pay_salary": check_permission("manage_employees")
        or check_permission("can_manage_employees"),
        "can_cancel_receipt": check_permission("cancel_receipts"),
        "can_print_receipt": check_permission("print_receipts"),
    }


@receipts_api_bp.route("", methods=["GET"])
@receipts_api_bp.route("/", methods=["GET"])
@permission_required_api("view_receipts")
def list_receipts():
    filters = _filters_from_request()
    page = max(1, parse_int(request.args.get("page"), 1))
    per_page = min(100, max(1, parse_int(request.args.get("per_page"), 25)))
    q = receipt_service.list_receipts_query(filters)
    total = q.count()
    rows = q.offset((page - 1) * per_page).limit(per_page).all()
    stats = receipt_service.dashboard_stats(filters)
    return _ok(
        {
            "items": [receipt_service.receipt_to_dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "stats": stats,
            "filters": filters,
            "payment_methods": [{"id": k, "label": v} for k, v in PAYMENT_METHODS],
        }
    )


@receipts_api_bp.route("/movements", methods=["GET"])
@permission_required_api("view_receipts")
def list_movements():
    filters = _filters_from_request()
    data = movements_feed.list_movements(filters)
    data["payment_methods"] = [{"id": k, "label": v} for k, v in PAYMENT_METHODS]
    data["capabilities"] = _capabilities()
    return _ok(data)


@receipts_api_bp.route("/meta", methods=["GET"])
@permission_required_api("view_receipts")
def meta():
    from models.treasury_account import TreasuryAccount
    from utils.expense_categories import get_expense_categories

    accounts = (
        TreasuryAccount.query.filter_by(is_active=True)
        .order_by(TreasuryAccount.account_type.asc(), TreasuryAccount.name.asc())
        .all()
    )
    caps = _capabilities()
    modes = []
    if caps["can_create_receipt"]:
        modes.append({"id": "receipt", "label": "سند قبض"})
    if caps["can_pay_supplier"]:
        modes.append({"id": "supplier_payment", "label": "تسديد مورد"})
    if caps["can_add_expense"]:
        modes.append({"id": "expense", "label": "مصروف / راتب حر"})
    if caps["can_pay_salary"]:
        modes.append({"id": "payroll", "label": "صرف راتب موظف"})

    return _ok(
        {
            "payment_methods": [{"id": k, "label": v} for k, v in PAYMENT_METHODS],
            "treasury_accounts": [
                {
                    "id": a.id,
                    "name": a.name,
                    "account_type": a.account_type,
                    "branch_id": a.branch_id,
                }
                for a in accounts
            ],
            "expense_categories": [
                {"id": c.get("key"), "label": c.get("label"), "icon": c.get("icon")}
                for c in get_expense_categories()
            ],
            "capabilities": caps,
            "modes": modes,
        }
    )


@receipts_api_bp.route("/search-sources", methods=["GET"])
@permission_required_api("create_receipts")
def search_sources():
    try:
        source_type = (request.args.get("source_type") or "customer").strip()
        q = request.args.get("q") or ""
        rows = summary_svc.search_sources(
            source_type, q, limit=parse_int(request.args.get("limit"), 20)
        )
        return _ok(rows)
    except Exception as exc:
        return _err(exc)


@receipts_api_bp.route("/search-parties", methods=["GET"])
@permission_required_api("view_receipts")
def search_parties_route():
    try:
        kind = (request.args.get("kind") or request.args.get("source_type") or "customer").strip()
        caps = _capabilities()
        if kind in {"customer", "courier", "shipping_company"} and not caps["can_create_receipt"]:
            return _err(ReceiptError("غير مصرح", "forbidden"), 403)
        if kind == "supplier" and not caps["can_pay_supplier"]:
            return _err(ReceiptError("غير مصرح", "forbidden"), 403)
        if kind in {"employee", "delivery_agent"} and not (
            caps["can_pay_salary"] or caps["can_add_expense"]
        ):
            return _err(ReceiptError("غير مصرح", "forbidden"), 403)
        q = request.args.get("q") or ""
        rows = party_search.search_parties(
            kind, q, limit=parse_int(request.args.get("limit"), 20)
        )
        return _ok(rows)
    except Exception as exc:
        return _err(exc)


@receipts_api_bp.route("/source/<source_type>/<int:source_id>/summary", methods=["GET"])
@permission_required_api("view_receipts")
def source_summary(source_type, source_id):
    try:
        return _ok(summary_svc.source_summary(source_type, source_id))
    except Exception as exc:
        return _err(exc)


@receipts_api_bp.route("/party/<kind>/<int:party_id>/summary", methods=["GET"])
@permission_required_api("view_receipts")
def party_summary_route(kind, party_id):
    try:
        return _ok(party_search.party_summary(kind, party_id))
    except Exception as exc:
        return _err(exc)


@receipts_api_bp.route("/preview-allocation", methods=["POST"])
@permission_required_api("create_receipts")
def preview_allocation():
    data = request.get_json(silent=True) or {}
    try:
        source_type = (data.get("source_type") or "").strip()
        source_id = parse_int(data.get("source_id"))
        amount = parse_int(data.get("amount"))
        opens = summary_svc.open_invoices_for_source(source_type, source_id)
        balance = sum(max(0, int(i.total or 0) - int(i.paid_amount or 0)) for i in opens)
        preview = allocation_svc.preview_allocations(
            open_invoices=opens,
            amount=amount,
            allocation_method=data.get("allocation_method") or "oldest_first",
            allocations=data.get("allocations") or [],
            balance_before=balance,
        )
        return _ok(preview)
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@receipts_api_bp.route("/settlements", methods=["POST"])
@permission_required_api("view_receipts")
def create_settlement():
    data = request.get_json(silent=True) or {}
    try:
        result = settlements.create_settlement(_tid(), data, employee_id=_emp_id())
        if str(data.get("movement_type") or "").strip() != "payroll":
            db.session.commit()
        return _ok(result)
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@receipts_api_bp.route("", methods=["POST"])
@receipts_api_bp.route("/", methods=["POST"])
@permission_required_api("create_receipts")
def create_receipt():
    data = request.get_json(silent=True) or {}
    try:
        result = receipt_service.create_receipt(_tid(), data, employee_id=_emp_id())
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        db.session.rollback()
        return _err(exc)


@receipts_api_bp.route("/<int:receipt_id>", methods=["GET"])
@permission_required_api("view_receipts")
def get_receipt(receipt_id):
    from models.receipt import Receipt

    receipt = Receipt.query.get(receipt_id)
    if not receipt:
        return _err(ReceiptError("سند القبض غير موجود"), 404)
    return _ok(receipt_service.receipt_to_dict(receipt, include_allocations=True))


@receipts_api_bp.route("/<int:receipt_id>/cancel", methods=["POST"])
@permission_required_api("cancel_receipts")
def cancel_receipt(receipt_id):
    data = request.get_json(silent=True) or {}
    try:
        result = receipt_service.cancel_receipt(
            receipt_id,
            employee_id=_emp_id(),
            reason=data.get("reason") or data.get("cancel_reason"),
        )
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        db.session.rollback()
        return _err(exc)
