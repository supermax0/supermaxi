import os
from datetime import date
from pathlib import Path


def test_hr_employee_attendance_leave_and_payroll_cycle():
    from app import app
    from extensions import db
    from extensions_tenant import clear_tenant_engine, init_tenant_db
    from flask import g, session
    from models.employee import Employee
    from models.hr import (
        HRAttendance,
        HRDepartment,
        HREmployeeProfile,
        HRLeaveRequest,
        HRPayrollAdjustment,
    )
    from models.tenant import Tenant
    from routes import hr as hr_routes

    slug = f"test_hr_management_{os.getpid()}"
    database = Path(__file__).resolve().parents[1] / "tenants" / f"{slug}.db"
    clear_tenant_engine(slug)
    database.unlink(missing_ok=True)

    try:
        with app.app_context():
            g.tenant = slug
            init_tenant_db(slug)
            tenant = Tenant(
                name="HR Test",
                business_type="hr_management",
                plan_key="basic",
                plan_name="Basic",
                is_active=True,
            )
            db.session.add(tenant)
            db.session.flush()
            admin = Employee(
                tenant_id=tenant.id,
                name="HR Admin",
                username=f"hr-admin-{os.getpid()}",
                password="x",
                role="admin",
                is_active=True,
            )
            db.session.add(admin)
            db.session.commit()
            admin_id = admin.id

            def invoke(path, view, *, method="GET", data=None):
                with app.test_request_context(path, method=method, data=data or {}):
                    g.tenant = slug
                    session.update(
                        user_id=admin_id,
                        role="admin",
                        tenant_slug=slug,
                        business_type="hr_management",
                    )
                    return view()

            invoke(
                "/hr/departments",
                hr_routes.add_department,
                method="POST",
                data={"name": "المالية", "code": "FIN", "color": "#4f46e5"},
            )
            department = HRDepartment.query.filter_by(code="FIN").one()

            invoke(
                "/hr/employees",
                hr_routes.employees,
                method="POST",
                data={
                    "name": "موظف اختبار",
                    "employee_code": "EMP-100",
                    "username": f"hr-staff-{os.getpid()}",
                    "password": "secret12",
                    "phone": "07700000000",
                    "department_id": str(department.id),
                    "job_title": "محاسب",
                    "employment_type": "full_time",
                    "hire_date": date.today().isoformat(),
                    "salary": "1000000",
                    "pay_type": "monthly",
                    "pay_day_of_month": "25",
                    "annual_leave_entitlement": "21",
                },
            )
            employee = Employee.query.filter_by(username=f"hr-staff-{os.getpid()}").one()
            profile = HREmployeeProfile.query.filter_by(employee_id=employee.id).one()
            assert profile.employee_code == "EMP-100"
            assert profile.department_id == department.id
            assert employee.salary == 1_000_000

            # The same code is rejected instead of causing a database error.
            invoke(
                "/hr/employees",
                hr_routes.employees,
                method="POST",
                data={
                    "name": "موظف مكرر",
                    "employee_code": "emp-100",
                    "username": f"hr-staff-duplicate-{os.getpid()}",
                    "password": "secret12",
                },
            )
            assert HREmployeeProfile.query.filter_by(employee_code="EMP-100").count() == 1

            invoke(
                "/hr/attendance/mark",
                hr_routes.mark_attendance,
                method="POST",
                data={
                    "employee_id": str(employee.id),
                    "attendance_date": date.today().isoformat(),
                    "status": "present",
                    "check_in": "09:30",
                    "check_out": "17:00",
                    "overtime_minutes": "30",
                },
            )
            attendance = HRAttendance.query.filter_by(
                employee_id=employee.id, attendance_date=date.today()
            ).one()
            assert attendance.status == "late"
            assert attendance.late_minutes == 15
            assert attendance.overtime_minutes == 30

            tomorrow = date.today().fromordinal(date.today().toordinal() + 1)
            day_after = date.today().fromordinal(date.today().toordinal() + 2)
            invoke(
                "/hr/leaves",
                hr_routes.leaves,
                method="POST",
                data={
                    "employee_id": str(employee.id),
                    "leave_type": "annual",
                    "start_date": tomorrow.isoformat(),
                    "end_date": day_after.isoformat(),
                    "reason": "اختبار الدورة",
                },
            )
            leave = HRLeaveRequest.query.filter_by(employee_id=employee.id).one()
            assert leave.days_count == 2

            invoke(
                f"/hr/leaves/{leave.id}/decision",
                lambda: hr_routes.leave_decision(leave.id),
                method="POST",
                data={"decision": "approved", "admin_note": "مقبولة"},
            )
            assert HRAttendance.query.filter_by(notes=f"إجازة #{leave.id}", status="leave").count() == 2

            # Cancelling an approved leave removes only its automatic attendance rows.
            invoke(
                f"/hr/leaves/{leave.id}/decision",
                lambda: hr_routes.leave_decision(leave.id),
                method="POST",
                data={"decision": "cancelled"},
            )
            assert HRAttendance.query.filter_by(notes=f"إجازة #{leave.id}").count() == 0

            invoke(
                "/hr/payroll",
                hr_routes.payroll,
                method="POST",
                data={
                    "employee_id": str(employee.id),
                    "period_year": str(date.today().year),
                    "period_month": str(date.today().month),
                    "adjustment_type": "allowance",
                    "title": "بدل نقل",
                    "amount": "50000",
                },
            )
            adjustment = HRPayrollAdjustment.query.filter_by(employee_id=employee.id).one()
            assert adjustment.amount == 50_000
            assert adjustment.adjustment_type == "allowance"

            from models.account_transaction import AccountTransaction
            from models.employee_payment import EmployeePayment
            from models.hr import HRSettings
            from models.treasury_account import TreasuryAccount
            from utils.treasury_schema_guard import ensure_treasury_schema

            ensure_treasury_schema()
            cash = TreasuryAccount.query.filter_by(account_type="cash", is_active=True).first()
            if not cash:
                cash = TreasuryAccount(name="الصندوق", account_type="cash", is_default=True, is_active=True)
                db.session.add(cash)
                db.session.flush()
            db.session.add(
                AccountTransaction(
                    type="deposit",
                    amount=5_000_000,
                    note="رصيد اختبار رواتب",
                    treasury_account_id=cash.id,
                )
            )
            settings_row = HRSettings.query.first() or HRSettings()
            if settings_row.id is None:
                db.session.add(settings_row)
            settings_row.salary_payout_method = "direct"
            settings_row.payroll_cash_account_id = cash.id
            db.session.commit()

            pay_response = invoke(
                "/hr/payroll/pay",
                hr_routes.pay_salary,
                method="POST",
                data={
                    "employee_id": str(employee.id),
                    "period_year": str(date.today().year),
                    "period_month": str(date.today().month),
                },
            )
            assert getattr(pay_response, "status_code", 302) in (301, 302)
            payment = EmployeePayment.query.filter_by(payee_type="employee", payee_id=employee.id).one()
            assert payment.amount == 1_050_000
            assert payment.voucher_code
            assert payment.payout_method == "direct"

            voucher_html = invoke(
                f"/hr/payroll/payments/{payment.id}/print",
                lambda: hr_routes.salary_voucher(payment.id),
            )
            assert "مستند صرف راتب" in voucher_html
            assert payment.voucher_code in voucher_html
            assert "1,050,000" in voucher_html

            dashboard_html = invoke("/hr/", hr_routes.dashboard)
            assert "Finora HR" in dashboard_html
            assert "كل ما يخص فريقك، في لوحة واحدة" in dashboard_html
            assert 'href="/inventory"' not in dashboard_html
            assert 'href="/pos"' not in dashboard_html
            assert "دفتر الملاحظات" not in dashboard_html
            assert "message-notify.js" not in dashboard_html
    finally:
        try:
            with app.app_context():
                db.session.remove()
        finally:
            clear_tenant_engine(slug)
            database.unlink(missing_ok=True)


def test_hr_activity_path_isolation():
    from app import _hr_activity_allows_path

    for allowed_path in (
        "/hr",
        "/hr/",
        "/hr/employees",
        "/hr/payroll/export",
        "/static/css/hr.css",
        "/employees/profile/update",
        "/logout",
    ):
        assert _hr_activity_allows_path(allowed_path)

    for unrelated_path in (
        "/",
        "/inventory/",
        "/pos",
        "/quick-sale",
        "/orders",
        "/expenses",
        "/cash",
        "/reports",
        "/settings",
        "/messages/unread-count",
        "/hr-other",
    ):
        assert not _hr_activity_allows_path(unrelated_path)
