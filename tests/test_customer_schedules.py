"""Schedule edits are isolated, retry safe, and preserve real collection reversals."""
from copy import deepcopy
from datetime import date, timedelta
from uuid import uuid4

import pytest

from tests.test_finance_operations import finance, installment_invoice, standalone_debt, review_opening, voucher, balance


def request_schedule(f, customer_id, plan_id, body=None, *, employee=None, tenant=None, view_all=True):
    from flask import g, session
    path = f"/api/v1/desktop/customers/{customer_id}/plans/{plan_id}" + ("/schedule" if body else "")
    with f["app"].test_request_context(path, method="POST" if body else "GET", json=body):
        actor = employee or f["admin"]
        session.update(user_id=actor.id, role=actor.role, tenant_slug=tenant or f["tenant"])
        g.tenant = f["tenant"]
        g.branch = f["branch"]
        g.view_all_branches = view_all
        g.branch_scope_ready = True
        g.independent_branches_enabled = True
        endpoint, arguments = f["app"].url_map.bind("localhost").match(path, method="POST" if body else "GET")
        return f["app"].make_response(f["app"].view_functions[endpoint](**arguments))


def edit_payload(data):
    return {"idempotency_key": str(uuid4()), "revision": data["revision"], "reason":"طلب العميل تأجيل الاستحقاق",
        "installments": [{"id": row["id"], "date": (date.today() + timedelta(days=30 * (i + 1))).isoformat(),
            "total": row["total"]} for i, row in enumerate(data["installments"])]}


@pytest.mark.parametrize("linked", [True, False])
def test_schedule_changes_preserve_cash_principal_payment_ids_and_exact_reversal(finance, linked):
    from models.customer_credit import CustomerCreditPayment
    from modules.finance import ledger
    f = finance
    if linked:
        customer, invoice, plan = installment_invoice(f)
    else:
        customer, plan = standalone_debt(f, total=400_000, paid=0)
        invoice = None
    review_opening(f)
    row = voucher(f, "customer_payment", 150_000, party_id=customer.id, treasury_account_id=f["bank"].id)
    before = request_schedule(f, customer.id, plan.id).get_json()["data"]
    payment_ids = [payment.id for payment in CustomerCreditPayment.query.order_by(CustomerCreditPayment.id)]
    payload = edit_payload(before)
    payload["installments"][0]["total"] = 175_000
    payload["installments"][1]["total"] = 225_000
    response = request_schedule(f, customer.id, plan.id, payload)
    assert response.status_code == 200, response.get_json()
    after = response.get_json()["data"]
    assert after["revision"] != before["revision"] and after["paid"] == 150_000
    assert after["total"] == 400_000 and after["history_total"] == 1
    assert [i["id"] for i in after["installments"]] == [i["id"] for i in before["installments"]]
    assert after["history"][0]["before"] == before["installments"]
    assert after["history"][0]["after"] == after["installments"]
    assert after["history"][0]["actor"] == f["admin"].name
    assert request_schedule(f, customer.id, plan.id, payload).get_json() == response.get_json()
    assert balance(f, "bank") == 150_000 and ledger.account("receivable").balance == 250_000
    assert [payment.id for payment in CustomerCreditPayment.query.order_by(CustomerCreditPayment.id)] == payment_ids
    changed = deepcopy(payload)
    changed["reason"] = "محاولة تغيير معرّف مستعمل"
    assert request_schedule(f, customer.id, plan.id, changed).status_code == 409
    f["call"]("voucher.reverse", {"id":row["id"], "version":row["version"], "reason":"عكس بعد إعادة الجدولة"})
    assert plan.paid_amount == 0 and (not invoice or invoice.paid_amount == 0)
    assert balance(f, "bank") == 0 and ledger.account("receivable").balance == 400_000
    assert request_schedule(f, customer.id, plan.id).get_json()["data"]["history_total"] == 1


@pytest.mark.parametrize("invalid", ["sum", "below_paid", "duplicate", "foreign", "missing", "paid_row", "boolean", "date"])
def test_schedule_rejects_invalid_rows_without_partial_effects(finance, invalid):
    f = finance
    customer, _, plan = installment_invoice(f)
    voucher(f, "customer_payment", 200_000 if invalid == "paid_row" else 150_000, party_id=customer.id)
    before = request_schedule(f, customer.id, plan.id).get_json()["data"]
    payload = edit_payload(before)
    if invalid == "sum": payload["installments"][0]["total"] += 1
    elif invalid == "below_paid":
        payload["installments"][0]["total"] = 149_999
        payload["installments"][1]["total"] = 250_001
    elif invalid == "duplicate": payload["installments"][1]["id"] = payload["installments"][0]["id"]
    elif invalid == "foreign": payload["installments"][1]["id"] = 999_999
    elif invalid == "missing": payload["installments"].pop()
    elif invalid == "boolean": payload["installments"][0]["total"] = True
    elif invalid == "date": payload["installments"][0]["date"] = "2026-02-30"
    response = request_schedule(f, customer.id, plan.id, payload)
    assert response.status_code == 400
    assert request_schedule(f, customer.id, plan.id).get_json()["data"] == before


def test_schedule_rejects_stale_balance_and_scope_and_get_has_no_writes(finance):
    from models.customer import Customer
    from models.employee import Employee
    from models.role import Role
    from models.activity_log import ActivityLog
    f = finance
    customer, _, plan = installment_invoice(f)
    before = request_schedule(f, customer.id, plan.id).get_json()["data"]
    audit_count = ActivityLog.query.count()
    assert request_schedule(f, customer.id, plan.id).get_json()["data"] == before
    assert ActivityLog.query.count() == audit_count
    payload = edit_payload(before)
    voucher(f, "customer_payment", 50_000, party_id=customer.id)
    assert request_schedule(f, customer.id, plan.id, payload).status_code == 409
    assert request_schedule(f, customer.id, plan.id, tenant="another-company").status_code == 403
    other = Customer(name="عميل آخر", phone="07709999999", branch_id=f["branch"].id)
    staff = Employee(name="Denied", username=uuid4().hex, password="test", role="cashier", is_active=True, branch_id=f["branch"].id)
    staff.roles = [Role(name="schedule-denied-" + uuid4().hex)]
    f["db"].session.add_all([other, staff]); f["db"].session.commit()
    assert request_schedule(f, other.id, plan.id).status_code == 404
    assert request_schedule(f, customer.id, plan.id, employee=staff).status_code == 403
    assert request_schedule(f, customer.id, plan.id, payload, employee=staff).status_code == 403


def test_schedule_audit_failure_rolls_back_and_same_key_can_retry(finance, monkeypatch):
    from models.activity_log import ActivityLog
    f = finance
    customer, _, plan = installment_invoice(f)
    before = request_schedule(f, customer.id, plan.id).get_json()["data"]
    payload = edit_payload(before)
    original = ActivityLog.set_payload
    def fail(*args, **kwargs): raise RuntimeError("forced schedule history failure")
    monkeypatch.setattr(ActivityLog, "set_payload", fail)
    assert request_schedule(f, customer.id, plan.id, payload).status_code == 500
    assert request_schedule(f, customer.id, plan.id).get_json()["data"] == before
    monkeypatch.setattr(ActivityLog, "set_payload", original)
    assert request_schedule(f, customer.id, plan.id, payload).status_code == 200
    assert request_schedule(f, customer.id, plan.id).get_json()["data"]["history_total"] == 1


def test_schedule_rejects_other_branch_even_for_general_admin_in_selected_branch(finance):
    from models.branch import Branch
    f = finance
    customer, invoice, plan = installment_invoice(f)
    before = request_schedule(f, customer.id, plan.id).get_json()["data"]
    other = Branch(code="schedule-other", name="فرع الجدولة الآخر")
    f["db"].session.add(other); f["db"].session.flush()
    customer.branch_id = invoice.branch_id = other.id
    f["db"].session.commit()
    assert request_schedule(f, customer.id, plan.id, view_all=False).status_code == 404
    assert request_schedule(f, customer.id, plan.id, edit_payload(before), view_all=False).status_code == 404
    assert request_schedule(f, customer.id, plan.id).get_json()["data"] == before


def test_schedule_cancellation_blocks_new_edit_but_preserves_exact_successful_replay(finance):
    f = finance
    customer, invoice, plan = installment_invoice(f)
    before = request_schedule(f, customer.id, plan.id).get_json()["data"]
    payload = edit_payload(before)
    saved = request_schedule(f, customer.id, plan.id, payload)
    assert saved.status_code == 200
    invoice.status = "ملغي"
    f["db"].session.commit()
    assert request_schedule(f, customer.id, plan.id).status_code == 404
    assert request_schedule(f, customer.id, plan.id, payload).get_json() == saved.get_json()
    fresh = edit_payload(saved.get_json()["data"])
    assert request_schedule(f, customer.id, plan.id, fresh).status_code == 409
