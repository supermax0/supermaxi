"""Branch cash transfers (spec phase 9): workflow in front of the proven treasury engine.

Hard rules under test: money moves exactly once and only at receipt confirmation; the company's total cash,
sales and expenses never change because of a transfer; refused steps post nothing; replay is safe; every
permission is enforced by the server, per branch."""
from __future__ import annotations

from datetime import timedelta

import pytest

from utils.branch_cash_transfers import business_today

from tests.test_branch_management_api import API as BRANCH_API
from tests.test_branch_management_api import _client, _json, _make_ctx, app  # noqa: F401

CASH = "/api/v1/desktop/branch-cash"


@pytest.fixture()
def ctx(app):  # noqa: F811
    from flask import g

    from extensions import db
    from models.employee import Employee
    from models.role import Permission, Role
    from werkzeug.security import generate_password_hash

    ids = _make_ctx(app)
    admin = _client(ids)
    _json(admin.post(f"{BRANCH_API}/feature", json={"enabled": True}))
    second = _json(admin.post(BRANCH_API, json={"code": "MNS", "name": "فرع المنصور"}))["branch"]
    with app.test_request_context():
        g.tenant = ids["tenant"]
        role = Role(name="cash-clerk")
        role.permissions.append(Permission.query.filter_by(name="view_accounts").first()
                                or Permission(name="view_accounts", description="view_accounts"))
        pw = generate_password_hash("x-pass-123")
        receiver = Employee(name="Receiver", username="bc_receiver", password=pw, role="sales", is_active=True,
                            branch_id=second["id"])
        outsider = Employee(name="Outsider", username="bc_outsider", password=pw, role="sales", is_active=True,
                            branch_id=second["id"])  # same branch, but no accounts permission
        db.session.add_all([receiver, outsider])
        db.session.flush()
        clerk = Employee.query.get(ids["clerk_id"])
        clerk.roles.append(role)
        receiver.roles.append(role)
        db.session.commit()
        ids.update(receiver_id=receiver.id, outsider_id=outsider.id)
    accounts = _json(admin.get(f"{CASH}/meta"))["accounts"]
    main_cash = next(a for a in accounts if a["branch_id"] == ids["main"] and a["type"] == "cash")
    other_cash = next(a for a in accounts if a["branch_id"] == second["id"] and a["type"] == "cash")
    return {**ids, "second": second["id"], "src": main_cash["id"], "dst": other_cash["id"]}


def _as(ctx, who):
    client = ctx["app"].test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = ctx[f"{who}_id"]
        sess["tenant_slug"] = ctx["tenant"]
        sess["role"] = "admin" if who == "admin" else "sales"
        sess["name"] = who
    return client


def _balances(ctx):
    rows = {a["id"]: a["balance"] for a in _json(_as(ctx, "admin").get(f"{CASH}/meta"))["accounts"]}
    return rows[ctx["src"]], rows[ctx["dst"]]


def _books(ctx):
    from flask import g

    from models.account_transaction import AccountTransaction
    from models.expense import Expense
    from models.invoice import Invoice
    from models.treasury_transfer import TreasuryTransfer

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        skip = {"skip_branch_scope": True}
        return {
            "transfers": TreasuryTransfer.query.execution_options(**skip).count(),
            "legs": AccountTransaction.query.execution_options(**skip).filter(
                AccountTransaction.treasury_transfer_id.isnot(None)).count(),
            "expenses": Expense.query.execution_options(**skip).count(),
            "invoices": Invoice.query.execution_options(**skip).count(),
        }


def _create(client, ctx, **over):
    body = {"from_account_id": ctx["src"], "to_account_id": ctx["dst"], "amount": 500000,
            "reason": "تغذية صندوق فرع المنصور", "reference": "REF-1", **over}
    return client.post(CASH, json=body)


def test_full_workflow_posts_once_at_receipt_and_keeps_company_totals(ctx):
    clerk, admin, receiver = _as(ctx, "clerk"), _as(ctx, "admin"), _as(ctx, "receiver")
    src0, dst0 = _balances(ctx)
    assert src0 == 2_450_000 and dst0 == 0  # 2,000,000 deposit + 450,000 cash sale in the seed
    books0 = _books(ctx)

    doc = _json(_create(clerk, ctx, operation_id="11111111-1111-4111-8111-111111111111"))["transfer"]
    assert doc["status"] == "pending" and doc["number"].startswith("BCT-") and doc["posted"] is False
    assert doc["can_approve"] is False and doc["can_cancel"] is True  # the requester is not an approver
    assert _balances(ctx) == (src0, dst0) and _books(ctx) == books0  # a request moves nothing

    assert _json(admin.post(f"{CASH}/{doc['id']}/approve"))["transfer"]["status"] == "approved"
    assert _balances(ctx) == (src0, dst0) and _books(ctx) == books0  # approval moves nothing either

    done = _json(receiver.post(f"{CASH}/{doc['id']}/receive"))["transfer"]
    assert done["status"] == "completed" and done["posted"] is True and done["received_by"] == "Receiver"
    assert [e["action"] for e in done["events"]] == ["create", "approve", "receive"]
    assert _balances(ctx) == (src0 - 500000, dst0 + 500000)
    assert sum(_balances(ctx)) == src0 + dst0  # the company's cash is unchanged
    after = _books(ctx)
    assert after["transfers"] == books0["transfers"] + 1 and after["legs"] == books0["legs"] + 2
    assert after["expenses"] == books0["expenses"] and after["invoices"] == books0["invoices"]

    # nothing can post it a second time
    assert receiver.post(f"{CASH}/{doc['id']}/receive").status_code == 409
    assert admin.post(f"{CASH}/{doc['id']}/approve").status_code == 409
    assert _books(ctx) == after and _balances(ctx) == (src0 - 500000, dst0 + 500000)


def test_create_is_replay_safe_and_validated(ctx):
    clerk = _as(ctx, "clerk")
    first = _json(_create(clerk, ctx, operation_id="22222222-2222-4222-8222-222222222222"))["transfer"]
    again = _json(_create(clerk, ctx, operation_id="22222222-2222-4222-8222-222222222222"))["transfer"]
    assert again["id"] == first["id"]  # same operation id: the same document, not a second request
    clash = _create(clerk, ctx, operation_id="22222222-2222-4222-8222-222222222222", amount=1)
    assert clash.status_code == 409
    assert len(_json(clerk.get(CASH))["rows"]) == 1

    assert _create(clerk, ctx, to_account_id=ctx["src"]).status_code == 400  # same account
    assert _create(clerk, ctx, amount=0).status_code == 400
    assert _create(clerk, ctx, amount=-5).status_code == 400
    assert _create(clerk, ctx, reason="").status_code == 400
    future = (business_today() + timedelta(days=3)).isoformat()
    assert _create(clerk, ctx, transfer_date=future).status_code == 400
    over = _create(clerk, ctx, amount=9_000_000)
    assert over.status_code == 409 and "لا يكفي" in over.get_json()["error"]
    # a clerk can only send from his own branch's accounts
    wrong = _create(clerk, ctx, from_account_id=ctx["dst"], to_account_id=ctx["src"], amount=1000)
    assert wrong.status_code == 403
    assert len(_json(clerk.get(CASH))["rows"]) == 1


def test_funds_are_rechecked_at_receipt_and_a_failed_receipt_posts_nothing(ctx):
    from flask import g

    from extensions import db
    from models.account_transaction import AccountTransaction

    clerk, admin, receiver = _as(ctx, "clerk"), _as(ctx, "admin"), _as(ctx, "receiver")
    doc = _json(_create(clerk, ctx, amount=2_000_000))["transfer"]
    _json(admin.post(f"{CASH}/{doc['id']}/approve"))
    with ctx["app"].test_request_context():  # the money leaves the source before the receiver confirms
        g.tenant = ctx["tenant"]
        db.session.add(AccountTransaction(branch_id=ctx["main"], type="withdraw", amount=1_000_000,
                                          note="سحب مالك", treasury_account_id=ctx["src"]))
        db.session.commit()
    before, books = _balances(ctx), _books(ctx)
    res = receiver.post(f"{CASH}/{doc['id']}/receive")
    # the engine's own message, with the real available balance (2,450,000 − the 1,000,000 withdrawn)
    assert res.status_code == 409 and "1,450,000" in res.get_json()["error"]
    assert _balances(ctx) == before and _books(ctx) == books
    assert _json(receiver.get(f"{CASH}/{doc['id']}"))["transfer"]["status"] == "approved"  # still retryable


def test_permissions_are_per_branch_and_enforced_by_the_server(ctx, monkeypatch):
    clerk, admin, receiver, outsider = (_as(ctx, w) for w in ("clerk", "admin", "receiver", "outsider"))
    doc = _json(_create(clerk, ctx))["transfer"]
    assert clerk.post(f"{CASH}/{doc['id']}/approve").status_code == 403
    assert receiver.post(f"{CASH}/{doc['id']}/approve").status_code == 403
    assert receiver.post(f"{CASH}/{doc['id']}/receive").status_code == 409  # not approved yet
    _json(admin.post(f"{CASH}/{doc['id']}/approve"))
    assert clerk.post(f"{CASH}/{doc['id']}/receive").status_code == 403  # sender's branch cannot confirm receipt
    assert outsider.get(CASH).status_code == 403  # no accounts permission at all
    assert outsider.post(f"{CASH}/{doc['id']}/receive").status_code == 403
    # an unrelated third branch cannot even see the document
    third = _json(admin.post(BRANCH_API, json={"code": "BSR", "name": "فرع البصرة"}))["branch"]
    from flask import g

    from extensions import db
    from models.employee import Employee

    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        stranger = Employee(name="Stranger", username="bc_stranger", password="x", role="sales", is_active=True,
                            branch_id=third["id"])
        clerk_row = Employee.query.get(ctx["clerk_id"])
        stranger.roles.append(clerk_row.roles[0])
        db.session.add(stranger)
        db.session.commit()
        ctx["stranger_id"] = stranger.id
    stranger_client = _as(ctx, "stranger")
    assert stranger_client.get(f"{CASH}/{doc['id']}").status_code == 404
    assert _json(stranger_client.get(CASH))["rows"] == []
    # no session at all (the dev-only loopback auto-login is off, as in production)
    monkeypatch.setenv("FINORA_LOCAL_WORKSPACE", "0")
    anonymous = ctx["app"].test_client()
    assert anonymous.get(CASH).status_code in (301, 302, 401, 403)
    assert anonymous.post(f"{CASH}/{doc['id']}/receive").status_code in (301, 302, 401, 403)


def test_reject_and_cancel_close_the_document_without_posting(ctx):
    clerk, admin, receiver = _as(ctx, "clerk"), _as(ctx, "admin"), _as(ctx, "receiver")
    before, books = _balances(ctx), _books(ctx)
    a = _json(_create(clerk, ctx))["transfer"]
    assert receiver.post(f"{CASH}/{a['id']}/reject", json={"reason": ""}).status_code == 400
    rejected = _json(receiver.post(f"{CASH}/{a['id']}/reject", json={"reason": "المبلغ غير متفق عليه"}))["transfer"]
    assert rejected["status"] == "rejected" and rejected["closed_reason"] == "المبلغ غير متفق عليه"
    b = _json(_create(clerk, ctx, amount=1000))["transfer"]
    _json(admin.post(f"{CASH}/{b['id']}/approve"))
    assert receiver.post(f"{CASH}/{b['id']}/cancel", json={"reason": "خطأ"}).status_code == 403  # not the requester
    cancelled = _json(clerk.post(f"{CASH}/{b['id']}/cancel", json={"reason": "طلب مكرر"}))["transfer"]
    assert cancelled["status"] == "cancelled"
    for doc in (a, b):  # terminal states are final
        assert receiver.post(f"{CASH}/{doc['id']}/receive").status_code == 409
        assert admin.post(f"{CASH}/{doc['id']}/approve").status_code == 409
    assert _balances(ctx) == before and _books(ctx) == books


def test_execute_now_is_admin_only_and_still_goes_through_the_document(ctx):
    clerk, admin = _as(ctx, "clerk"), _as(ctx, "admin")
    assert _create(clerk, ctx, execute_now=True).status_code == 403
    before = _balances(ctx)
    doc = _json(_create(admin, ctx, amount=300000, execute_now=True))["transfer"]
    assert doc["status"] == "completed" and doc["posted"] is True
    assert [e["action"] for e in doc["events"]] == ["create", "approve", "receive"]
    assert _balances(ctx) == (before[0] - 300000, before[1] + 300000)
    meta = _json(admin.get(f"{CASH}/meta"))
    assert meta["pending"] == {"count": 0, "amount": 0} and meta["can_execute_now"] is True


def test_interrupted_posting_is_reconciled_from_the_books_never_doubled(ctx):
    """A request killed mid-receipt leaves «posting»; the next read decides from what was really posted."""
    from datetime import datetime, timedelta

    from flask import g

    from extensions import db
    from models.branch_cash_transfer import BranchCashTransfer
    from utils.treasury_calculations import record_treasury_transfer

    clerk, admin, receiver = _as(ctx, "clerk"), _as(ctx, "admin"), _as(ctx, "receiver")

    def stuck(amount, *, posted):
        doc = _json(_create(clerk, ctx, amount=amount))["transfer"]
        _json(admin.post(f"{CASH}/{doc['id']}/approve"))
        with ctx["app"].test_request_context():
            g.tenant = ctx["tenant"]
            row = BranchCashTransfer.query.get(doc["id"])
            row.status = "posting"
            row.received_by_id = ctx["receiver_id"]
            row.updated_at = datetime.utcnow() - timedelta(minutes=10)
            db.session.commit()
            if posted:  # the engine got as far as posting before the process died
                record_treasury_transfer(ctx["src"], ctx["dst"], amount, f"{row.number} — {row.reason}"[:255],
                                         allow_cross_branch=True)
        return doc["id"]

    src0, dst0 = _balances(ctx)
    never = stuck(111000, posted=False)
    assert _json(receiver.get(f"{CASH}/{never}"))["transfer"]["status"] == "approved"  # safely retryable
    assert _balances(ctx) == (src0, dst0)

    did = stuck(222000, posted=True)
    done = _json(receiver.get(f"{CASH}/{did}"))["transfer"]
    assert done["status"] == "completed" and done["posted"] is True  # linked to the posting that happened
    assert _balances(ctx) == (src0 - 222000, dst0 + 222000)
    assert receiver.post(f"{CASH}/{did}/receive").status_code == 409  # and can never be posted again

    # a «posting» that is still fresh (another request may be finishing it) is left alone
    fresh = _json(_create(clerk, ctx, amount=5000))["transfer"]
    _json(admin.post(f"{CASH}/{fresh['id']}/approve"))
    with ctx["app"].test_request_context():
        g.tenant = ctx["tenant"]
        row = BranchCashTransfer.query.get(fresh["id"])
        row.status = "posting"
        row.updated_at = datetime.utcnow()
        db.session.commit()
    assert _json(admin.get(f"{CASH}/{fresh['id']}"))["transfer"]["status"] == "posting"
    assert receiver.post(f"{CASH}/{fresh['id']}/receive").status_code == 409


def test_branches_list_reports_real_pending_transfers(ctx):
    clerk, admin = _as(ctx, "clerk"), _as(ctx, "admin")
    assert _json(admin.get(BRANCH_API))["pending_transfers"] == {"stock": 0, "cash": 0, "cash_amount": 0}
    doc = _json(_create(clerk, ctx, amount=70000))["transfer"]
    assert _json(admin.get(BRANCH_API))["pending_transfers"] == {"stock": 0, "cash": 1, "cash_amount": 70000}
    _json(admin.post(f"{CASH}/{doc['id']}/cancel", json={"reason": "تجربة"}))
    assert _json(admin.get(BRANCH_API))["pending_transfers"]["cash"] == 0
