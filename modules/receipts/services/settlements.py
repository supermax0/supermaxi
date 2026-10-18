"""Create unified settlements (receipt / supplier pay / expense / payroll)."""
from __future__ import annotations

from datetime import date

from extensions import db
from models.delivery_agent import DeliveryAgent
from models.employee import Employee
from modules.receipts.services import receipt_service
from modules.receipts.services.helpers import ReceiptError, parse_int
from utils.expense_quick_add import ExpenseQuickAddError, create_quick_expense
from utils.permission_checks import check_permission, get_current_employee
from utils.supplier_payment_ops import SupplierPaymentError, create_supplier_cash_payment


def create_settlement(
    tenant_id: int | None,
    payload: dict,
    *,
    employee_id: int | None = None,
) -> dict:
    movement_type = str(payload.get("movement_type") or payload.get("kind") or "").strip()
    if movement_type == "receipt":
        if not check_permission("create_receipts"):
            raise ReceiptError("غير مصرح بإنشاء سند قبض", "forbidden")
        result = receipt_service.create_receipt(tenant_id, payload, employee_id=employee_id)
        return {
            "kind": "receipt",
            "id": result.get("id"),
            "amount": result.get("amount"),
            "label": result.get("receipt_number") or "سند قبض",
            "detail_url": f"/receipts/{result.get('id')}",
            "receipt_number": result.get("receipt_number"),
            "message": f"تم إنشاء سند القبض {result.get('receipt_number')}",
            **{k: v for k, v in result.items() if k not in {"id", "amount"}},
        }

    if movement_type == "supplier_payment":
        if not check_permission("manage_suppliers") and not check_permission("can_manage_suppliers"):
            raise ReceiptError("غير مصرح بتسديد الموردين", "forbidden")
        supplier_id = parse_int(payload.get("supplier_id") or payload.get("party_id") or payload.get("source_id"))
        result = create_supplier_cash_payment(
            supplier_id,
            amount=payload.get("amount"),
            treasury_account_id=payload.get("treasury_account_id"),
            note=payload.get("notes") or payload.get("note") or "",
            document_number=payload.get("document_number") or payload.get("reference_number"),
            commit=False,
        )
        return result

    if movement_type == "expense":
        if not check_permission("view_expenses") and not check_permission("can_see_expenses"):
            raise ReceiptError("غير مصرح بإضافة المصاريف", "forbidden")
        try:
            result = create_quick_expense(
                {
                    "title": payload.get("title"),
                    "category": payload.get("category") or "salary",
                    "amount": payload.get("amount"),
                    "note": payload.get("notes") or payload.get("note") or "",
                    "expense_date": payload.get("expense_date") or payload.get("date"),
                    "treasury_account_id": payload.get("treasury_account_id"),
                },
                commit=False,
            )
        except ExpenseQuickAddError as exc:
            raise ReceiptError(exc.message, exc.code) from exc
        return result

    if movement_type == "payroll":
        if not check_permission("manage_employees") and not check_permission("can_manage_employees"):
            raise ReceiptError("غير مصرح بصرف الرواتب", "forbidden")
        return _create_payroll(payload, employee_id=employee_id)

    raise ReceiptError("نوع الحركة غير مدعوم")


def _create_payroll(payload: dict, *, employee_id: int | None = None) -> dict:
    from utils.payroll_service import pay_salary

    payee_type = str(payload.get("payee_type") or payload.get("kind") or "employee").strip()
    payee_id = parse_int(payload.get("payee_id") or payload.get("party_id") or payload.get("source_id"))
    try:
        treasury_account_id = int(payload.get("treasury_account_id"))
    except (TypeError, ValueError):
        raise ReceiptError("اختر الحساب المالي لصرف الراتب")

    manual = payload.get("manual", True)
    if isinstance(manual, str):
        manual = manual.strip().lower() in {"1", "true", "yes", "on"}

    if payee_type == "delivery_agent":
        payee = DeliveryAgent.query.get(payee_id)
    elif payee_type == "employee":
        payee = Employee.query.get(payee_id)
    else:
        raise ReceiptError("نوع المستفيد غير صالح")

    if not payee:
        raise ReceiptError("المستفيد غير موجود")

    settled_by = employee_id
    if settled_by is None:
        try:
            from flask import has_request_context

            if has_request_context():
                current = get_current_employee()
                settled_by = current.id if current else None
        except Exception:
            settled_by = None

    result = pay_salary(
        payee,
        treasury_account_id=treasury_account_id,
        settled_by=settled_by,
        manual=bool(manual),
        today=date.today(),
    )
    if not result.get("ok"):
        raise ReceiptError(result.get("error") or "فشل صرف الراتب")

    expense_id = result.get("expense_id")
    return {
        "kind": "payroll",
        "id": expense_id or result.get("payment_id"),
        "amount": result.get("amount"),
        "label": f"راتب {result.get('payee_name')}",
        "detail_url": "/payroll" if payee_type == "employee" else "/payroll",
        "message": f"تم صرف راتب {result.get('payee_name')} — {result.get('amount'):,} د.ع",
        "payee_name": result.get("payee_name"),
        "payment_id": result.get("payment_id"),
        "expense_id": expense_id,
        "subtype": "payroll",
    }
