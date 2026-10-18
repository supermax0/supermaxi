from datetime import date, datetime
from types import SimpleNamespace

from utils.payroll_service import _serialize_payee_due, pay_salary, salary_paid_in_current_cycle


def _monthly_employee(*, last_paid=None):
    return SimpleNamespace(
        id=77,
        name="H",
        is_active=True,
        pay_type="monthly",
        salary=500_000,
        pay_day_of_month=1,
        payroll_effective_from=date(2026, 7, 1),
        last_salary_paid_at=last_paid,
    )


def test_manual_salary_button_is_disabled_after_payment_in_same_cycle():
    today = date(2026, 8, 3)
    employee = _monthly_employee(last_paid=datetime(2026, 8, 3))

    rows = _serialize_payee_due(employee, today=today)

    assert salary_paid_in_current_cycle(employee, today=today) is True
    assert rows and rows[0]["paid_in_current_cycle"] is True
    assert rows[0]["can_pay_manually"] is False


def test_manual_salary_is_available_again_when_next_cycle_starts():
    employee = _monthly_employee(last_paid=datetime(2026, 8, 3))

    assert salary_paid_in_current_cycle(employee, today=date(2026, 9, 1)) is False


def test_backend_rejects_duplicate_manual_salary_in_same_cycle():
    today = date(2026, 8, 3)
    employee = _monthly_employee(last_paid=datetime(2026, 8, 3))

    result = pay_salary(employee, treasury_account_id=1, manual=True, today=today)

    assert result == {"ok": False, "error": "تم صرف راتب هذه الدورة مسبقاً"}
