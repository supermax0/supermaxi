"""SSR pages for receipts & settlements."""
from __future__ import annotations

from flask import Blueprint, abort, render_template

from models.receipt import Receipt
from modules.receipts.schema_guard import ensure_receipts_schema
from modules.receipts.services import receipt_service
from utils.decorators import permission_required
from utils.permission_checks import check_permission

receipts_web_bp = Blueprint("receipts_web", __name__, url_prefix="/receipts")


def _invoice_settings():
    try:
        from models.invoice_settings import InvoiceSettings

        return InvoiceSettings.get_settings()
    except Exception:
        return None


@receipts_web_bp.before_request
def _web_schema():
    ensure_receipts_schema()


@receipts_web_bp.route("/")
@receipts_web_bp.route("")
@permission_required("view_receipts")
def index():
    can_create_receipt = check_permission("create_receipts")
    can_pay_supplier = check_permission("manage_suppliers") or check_permission(
        "can_manage_suppliers"
    )
    can_add_expense = check_permission("view_expenses") or check_permission("can_see_expenses")
    can_pay_salary = check_permission("manage_employees") or check_permission(
        "can_manage_employees"
    )
    can_create_any = (
        can_create_receipt or can_pay_supplier or can_add_expense or can_pay_salary
    )
    return render_template(
        "receipts/index.html",
        can_create_receipt=can_create_receipt,
        can_pay_supplier=can_pay_supplier,
        can_add_expense=can_add_expense,
        can_pay_salary=can_pay_salary,
        can_create_any=can_create_any,
    )


@receipts_web_bp.route("/<int:receipt_id>")
@permission_required("view_receipts")
def detail(receipt_id):
    receipt = Receipt.query.get(receipt_id)
    if not receipt:
        abort(404)
    data = receipt_service.receipt_to_dict(receipt, include_allocations=True)
    return render_template(
        "receipts/detail.html",
        receipt=receipt,
        data=data,
        settings=_invoice_settings(),
    )


@receipts_web_bp.route("/<int:receipt_id>/print")
@permission_required("print_receipts")
def print_receipt(receipt_id):
    receipt = Receipt.query.get(receipt_id)
    if not receipt:
        abort(404)
    data = receipt_service.receipt_to_dict(receipt, include_allocations=True)
    return render_template(
        "receipts/print.html",
        receipt=receipt,
        data=data,
        settings=_invoice_settings(),
    )
