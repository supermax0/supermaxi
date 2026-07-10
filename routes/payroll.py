from datetime import date, datetime

from flask import Blueprint, jsonify, render_template, request

from extensions import db
from models.delivery_agent import DeliveryAgent
from models.employee import Employee
from utils.activity_logger import log_activity
from utils.decorators import permission_required
from utils.permission_checks import get_current_employee
from utils.payroll_schema import backfill_commission_lines, ensure_payroll_schema
from utils.payroll_service import (
    WEEKDAY_LABELS,
    build_payroll_dashboard,
    get_payment_history,
    pay_salary,
    process_due_salary_payments,
    serialize_commission_lines,
    settle_employee_commission_payment,
)
from utils.treasury_helpers import treasury_choices_for_form

payroll_bp = Blueprint("payroll", __name__)


@payroll_bp.before_request
def _ensure_schema():
    ensure_payroll_schema()
    try:
        backfill_commission_lines()
    except Exception as e:
        print(f"[payroll] backfill failed: {e}")


@payroll_bp.route("/")
@permission_required("manage_employees")
def payroll_page():
    treasury_accounts = treasury_choices_for_form()
    try:
        from utils.treasury_helpers import resolve_treasury_account_id

        default_tid = resolve_treasury_account_id(None)
        process_due_salary_payments(today=date.today(), treasury_account_id=default_tid)
    except Exception:
        db.session.rollback()
    return render_template(
        "payroll.html",
        treasury_accounts=treasury_accounts,
        weekday_labels=WEEKDAY_LABELS,
    )


@payroll_bp.route("/api/dashboard")
@permission_required("manage_employees")
def payroll_dashboard_api():
    data = build_payroll_dashboard()
    return jsonify({"success": True, **data})


@payroll_bp.route("/api/commission/<int:employee_id>")
@permission_required("manage_employees")
def payroll_commission_detail(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    lines = serialize_commission_lines(employee_id)
    total = sum(int(l["amount"] or 0) for l in lines)
    return jsonify(
        {
            "success": True,
            "employee_id": employee.id,
            "employee_name": employee.name,
            "lines": lines,
            "total_amount": total,
            "order_count": len(lines),
        }
    )


@payroll_bp.route("/api/settle-commission", methods=["POST"])
@permission_required("manage_employees")
def payroll_settle_commission():
    data = request.get_json(silent=True) or {}
    try:
        employee_id = int(data.get("employee_id"))
        treasury_account_id = int(data.get("treasury_account_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "بيانات غير صالحة"}), 400

    current = get_current_employee()
    settled_by = current.id if current else None
    now = datetime.utcnow()

    try:
        result = settle_employee_commission_payment(
            employee_id,
            treasury_account_id=treasury_account_id,
            settled_by=settled_by,
            year=now.year,
            month=now.month,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not result.get("ok"):
        return jsonify({"error": result.get("error", "فشل السداد")}), 400

    try:
        log_activity(
            "update",
            "payroll",
            f"سداد عمولة {result['employee_name']} — {result['order_count']} طلب — {result['amount']} د.ع",
            entity_type="employee",
            entity_id=employee_id,
            payload=result,
        )
    except Exception:
        pass

    return jsonify({"success": True, **result, "message": "تم سداد العمولة وخصمها من الخزينة"})


@payroll_bp.route("/api/pay-salary", methods=["POST"])
@permission_required("manage_employees")
def payroll_pay_salary():
    data = request.get_json(silent=True) or {}
    payee_type = str(data.get("payee_type") or "").strip()
    try:
        payee_id = int(data.get("payee_id"))
        treasury_account_id = int(data.get("treasury_account_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "بيانات غير صالحة"}), 400

    manual = bool(data.get("manual", True))
    if payee_type == "delivery_agent":
        payee = DeliveryAgent.query.get_or_404(payee_id)
    elif payee_type == "employee":
        payee = Employee.query.get_or_404(payee_id)
    else:
        return jsonify({"error": "نوع المستفيد غير صالح"}), 400

    current = get_current_employee()
    settled_by = current.id if current else None

    try:
        result = pay_salary(
            payee,
            treasury_account_id=treasury_account_id,
            settled_by=settled_by,
            manual=manual,
            today=date.today(),
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not result.get("ok"):
        return jsonify({"error": result.get("error", "فشل الصرف")}), 400

    try:
        log_activity(
            "update",
            "payroll",
            f"صرف راتب {result['payee_name']} — {result['amount']} د.ع",
            entity_type=payee_type,
            entity_id=payee_id,
            payload=result,
        )
    except Exception:
        pass

    return jsonify({"success": True, **result, "message": "تم صرف الراتب وخصمه من الخزينة"})


@payroll_bp.route("/api/history")
@permission_required("manage_employees")
def payroll_history_api():
    limit = request.args.get("limit", 100, type=int)
    rows = get_payment_history(limit=limit)
    return jsonify({"success": True, "rows": rows})


@payroll_bp.route("/api/process-due", methods=["POST"])
@permission_required("manage_employees")
def payroll_process_due():
    data = request.get_json(silent=True) or {}
    try:
        treasury_account_id = int(data.get("treasury_account_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "اختر حساب الخزينة"}), 400

    current = get_current_employee()
    settled_by = current.id if current else None

    try:
        result = process_due_salary_payments(
            today=date.today(),
            treasury_account_id=treasury_account_id,
            settled_by=settled_by,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(
        {
            "success": True,
            "paid_count": result["paid_count"],
            "skipped_count": result["skipped_count"],
            "paid": result["paid"],
            "skipped": result["skipped"],
            "message": f"تم صرف {result['paid_count']} راتب",
        }
    )
