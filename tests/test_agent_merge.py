"""Real merge of duplicate delivery agents: same branch only, payroll-bearing duplicates refused, nothing deleted."""
from __future__ import annotations

import pytest

from tests.test_branch_management_api import _client, _make_ctx, app  # noqa: F401

API = "/api/v1/desktop/shipping-center/agents"


@pytest.fixture()
def ctx(app):  # noqa: F811
    from flask import g

    from extensions import db
    from models.customer import Customer
    from models.delivery_agent import DeliveryAgent
    from models.invoice import Invoice

    ids = _make_ctx(app)
    with app.test_request_context():
        g.tenant = ids["tenant"]
        main = ids["main"]
        primary = DeliveryAgent(name="علي  حسن", phone="0770 111 2222", branch_id=main, username="ali", password="x",
                                is_active=True)
        dup = DeliveryAgent(name="علي حسن", phone="07701112222", branch_id=main, is_active=True, total_orders=3)
        paid = DeliveryAgent(name="علي حسن", phone="07701112222", branch_id=main, is_active=True, salary=500000,
                             pay_type="monthly")
        db.session.add_all([primary, dup, paid])
        db.session.flush()
        customer = Customer.query.execution_options(skip_branch_scope=True).first()
        invoice = Invoice(customer_id=customer.id, customer_name=customer.name, branch_id=main,
                          employee_id=ids["admin_id"], employee_name="admin", total=1000, paid_amount=0,
                          status="تم الطلب", payment_status="غير مسدد", sale_type="cash", stock_is_deducted=False,
                          delivery_agent_id=dup.id)
        db.session.add(invoice)
        db.session.commit()
        ids.update(primary=primary.id, dup=dup.id, paid=paid.id, invoice=invoice.id)
    return {**ids, "admin": _client(ids)}


def test_preview_flags_same_branch_duplicates_and_blocks_payroll(ctx):
    rows = ctx["admin"].get(f"{API}/duplicates").get_json()["rows"]
    assert len(rows) == 1 and rows[0]["primary_id"] == ctx["primary"]  # the record with the portal login wins
    by = {d["id"]: d for d in rows[0]["duplicates"]}
    assert by[ctx["dup"]]["invoices"] == 1 and by[ctx["dup"]]["blocker"] == ""
    assert by[ctx["paid"]]["blocker"] and rows[0]["can_merge"] is False


def test_merge_moves_invoices_deactivates_and_refuses_payroll_duplicates(ctx):
    from flask import g

    from models.delivery_agent import DeliveryAgent
    from models.invoice import Invoice

    refused = ctx["admin"].post(f"{API}/merge", json={"primary_id": ctx["primary"],
                                                      "duplicate_ids": [ctx["dup"], ctx["paid"]]})
    assert refused.status_code == 409  # payroll duplicate blocks the whole merge, nothing changes
    done = ctx["admin"].post(f"{API}/merge", json={"primary_id": ctx["primary"], "duplicate_ids": [ctx["dup"]]})
    assert done.status_code == 200, done.get_json()
    assert done.get_json()["invoices_moved"] == 1
    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        q = DeliveryAgent.query.execution_options(skip_branch_scope=True)
        assert q.get(ctx["dup"]).is_active is False and q.get(ctx["primary"]).is_active is True
        assert q.get(ctx["primary"]).total_orders == 3  # counters carried over, not lost
        assert q.get(ctx["paid"]).is_active is True  # untouched
        assert Invoice.query.execution_options(skip_branch_scope=True).get(ctx["invoice"]).delivery_agent_id == ctx["primary"]


def test_only_admin_and_different_people_are_refused(ctx):
    clerk = ctx["app"].test_client()
    with clerk.session_transaction() as sess:
        sess["user_id"], sess["tenant_slug"], sess["role"] = ctx["clerk_id"], ctx["tenant"], "sales"
    assert clerk.post(f"{API}/merge", json={"primary_id": ctx["primary"], "duplicate_ids": [ctx["dup"]]}).status_code in (401, 403)
    assert ctx["admin"].post(f"{API}/merge", json={"primary_id": ctx["primary"], "duplicate_ids": []}).status_code == 400
