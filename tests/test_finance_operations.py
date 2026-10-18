"""Real isolated tenant integration tests for finance commands and existing balances."""
import os
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def finance():
    from app import app
    from extensions import db
    from extensions_tenant import init_tenant_db, clear_tenant_engine
    from flask import g
    from models.branch import Branch
    from models.employee import Employee
    from models.treasury_account import TreasuryAccount
    from models.account_transaction import AccountTransaction
    from modules.finance.common import FinanceError
    from modules.finance import routes
    tenant = f"test_finance_{os.getpid()}_{uuid4().hex[:8]}"
    with app.app_context():
        g.tenant = tenant
        init_tenant_db(tenant)
        branch = Branch(code="FIN", name="Finance", is_default=True, is_active=True)
        db.session.add(branch)
        db.session.flush()
        admin = Employee(name="Finance admin", username=uuid4().hex, password="test", role="admin", is_active=True, branch_id=branch.id)
        cash = TreasuryAccount(name="الصندوق", account_type="cash", branch_id=branch.id, is_default=True, is_active=True)
        bank = TreasuryAccount(name="المصرف", account_type="bank", branch_id=branch.id, is_active=True)
        db.session.add_all([admin, cash, bank])
        db.session.flush()
        db.session.add(AccountTransaction(type="deposit", amount=20_000_000, treasury_account_id=cash.id, branch_id=branch.id, note="رأس مال اختبار"))
        db.session.commit()

        def call(operation, values=None, key=None):
            from flask import session
            with app.test_request_context("/api/finance/commands", method="POST", json={"operation":operation, "idempotency_key":key or uuid4().hex, **(values or {})}):
                session["user_id"] = admin.id
                session["employee_id"] = admin.id
                g.branch = branch
                g.branches = [branch]
                g.view_all_branches = True
                g.branch_scope_ready = True
                g.independent_branches_enabled = False
                try:
                    routes.setup()
                    response = routes.commands()
                    return response.get_json()["data"]
                except Exception:
                    db.session.rollback()
                    raise

        def get(path):
            from flask import session
            with app.test_request_context(path):
                session.update(user_id=admin.id, employee_id=admin.id, role="admin", tenant_slug=tenant)
                g.branch=branch
                g.branches=[branch]
                g.view_all_branches=True
                g.branch_scope_ready=True
                g.independent_branches_enabled=False
                routes.setup()
                endpoint,arguments=app.url_map.bind("localhost").match(path.split("?")[0])
                return app.view_functions[endpoint](**arguments)

        yield {"tenant":tenant,"call":call, "get":get, "cash":cash, "bank":bank, "branch":branch, "admin":admin, "db":db, "app":app}
        db.session.remove()
    clear_tenant_engine(tenant)
    (Path(__file__).resolve().parents[1] / "tenants" / f"{tenant}.db").unlink(missing_ok=True)


def voucher(f, category, amount, **extra):
    return f["call"]("voucher.create", {"category":category, "amount":amount, "treasury_account_id":f["cash"].id, "branch_id":f["branch"].id, "intent":"post", **extra})


def balance(f, account="cash"):
    from utils.treasury_calculations import calculate_treasury_balance
    return calculate_treasury_balance(f[account].id)


def standalone_debt(f, total=500_000, paid=100_000):
    from models.customer import Customer
    from utils.customer_credit_service import create_credit_plan
    customer = Customer(name="دين سابق", phone="07001002003", branch_id=f["branch"].id)
    f["db"].session.add(customer)
    f["db"].session.flush()
    plan = create_credit_plan(customer.id, "opening", total, 2, date.today(), "monthly")
    f["db"].session.flush()
    plan.paid_amount = paid
    plan.installments[0].paid_amount = paid
    f["db"].session.commit()
    return customer, plan


def review_opening(f):
    preview = f["get"]("/api/finance/migration/preview").get_json()["data"]
    f["call"]("migration.apply", {"preview_hash": preview["hash"], "reason": "مراجعة الديون السابقة"})
    return preview


def test_standalone_debt_bank_legacy_cash_and_exact_reversal(finance):
    from modules.finance import ledger
    from models.customer_credit import CustomerCreditPayment
    from models.receipt import Receipt
    from utils.customer_credit_service import allocate_payment_fifo
    f = finance
    customer, plan = standalone_debt(f)
    opening = review_opening(f)
    assert next(r for r in opening["rows"] if r["key"] == "receivable")["target"] == 400_000
    assert balance(f) == 20_000_000 and balance(f, "bank") == 0
    assert ledger.account("receivable").balance == 400_000
    key = uuid4().hex
    payload = {"category": "customer_payment", "party_id": customer.id, "amount": 250_000,
        "branch_id": f["branch"].id, "treasury_account_id": f["bank"].id, "intent": "post",
        "allocations": [{"plan_id": plan.id, "amount": 250_000}]}
    row = f["call"]("voucher.create", payload, key)
    assert row == f["call"]("voucher.create", payload, key)
    assert plan.paid_amount == 350_000 and [i.paid_amount for i in plan.installments] == [250_000, 100_000]
    assert balance(f) == 20_000_000 and balance(f, "bank") == 250_000
    receipt = f["db"].session.get(Receipt, row["source_id"])
    assert receipt.payment_method == "bank" and receipt.balance_before == 400_000 and receipt.balance_after == 150_000
    html = f["get"](f"/accounts/finance/vouchers/{row['id']}/print")
    assert "دين مستقل #" in html and "customer_debt" not in html and "قبضاً إضافياً" in html
    artifacts = Path(__file__).parent / "_artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "finance-standalone-debt.html").write_text(html, encoding="utf-8")
    allocate_payment_fifo(customer.id, 50_000)
    f["db"].session.commit()
    assert plan.paid_amount == 400_000 and ledger.account("receivable").balance == 100_000
    from models.account_transaction import AccountTransaction
    cash_rows = AccountTransaction.query.filter(AccountTransaction.note.like("%[CP:%")).all()
    from utils.treasury_helpers import get_default_cash_account
    from utils.treasury_calculations import calculate_treasury_balance
    canonical_cash = get_default_cash_account(f["branch"].id)
    assert [(p.amount, p.treasury_account_id) for p in cash_rows] == [(50_000, canonical_cash.id)]
    assert calculate_treasury_balance(canonical_cash.id) == 20_050_000 and balance(f, "bank") == 250_000
    reverse_key = uuid4().hex
    reversal = {"id": row["id"], "version": row["version"], "reason": "تصحيح الحساب المختار"}
    reversed_row = f["call"]("voucher.reverse", reversal, reverse_key)
    assert reversed_row == f["call"]("voucher.reverse", reversal, reverse_key)
    assert plan.paid_amount == 150_000 and [i.paid_amount for i in plan.installments] == [100_000, 50_000]
    assert calculate_treasury_balance(canonical_cash.id) == 20_050_000 and balance(f, "bank") == 0
    assert ledger.account("receivable").balance == 350_000
    assert ledger.account("revenue").balance == ledger.account("other_revenue").balance == 0
    assert sum(p.amount for p in CustomerCreditPayment.query.filter_by(plan_id=plan.id)) == 50_000
    assert receipt.status == "ملغى"
    assert f["get"](f"/api/finance/parties/customer/{customer.id}").get_json()["data"]["debt"] == 350_000
    aging = f["get"]("/api/finance/reports/customer-aging").get_json()["data"]
    assert aging["total"] == 350_000 and len(aging["rows"]) == 1


def test_mixed_invoice_and_standalone_receipt_moves_cash_once(finance):
    from models.invoice import Invoice
    from modules.finance import ledger
    f = finance
    customer, plan = standalone_debt(f)
    invoice = Invoice(customer_id=customer.id, customer_name=customer.name, branch_id=f["branch"].id,
        total=200_000, paid_amount=0, status="تم التوصيل", payment_status="غير مسدد")
    f["db"].session.add(invoice)
    f["db"].session.commit()
    review_opening(f)
    row = voucher(f, "customer_payment", 250_000, party_id=customer.id, treasury_account_id=f["bank"].id,
        allocations=[{"invoice_id": invoice.id, "amount": 100_000}, {"plan_id": plan.id, "amount": 150_000}])
    assert invoice.paid_amount == 100_000 and plan.paid_amount == 250_000
    assert balance(f, "bank") == 250_000 and balance(f) == 20_000_000
    assert ledger.account("receivable").balance == 350_000
    f["call"]("voucher.reverse", {"id": row["id"], "version": row["version"], "reason": "عكس دفعة مختلطة"})
    assert invoice.paid_amount == 0 and plan.paid_amount == 100_000
    assert balance(f, "bank") == 0 and ledger.account("receivable").balance == 600_000


def test_standalone_credit_offset_has_no_cash_and_reverses_exactly(finance):
    from modules.finance import ledger
    f = finance
    customer, plan = standalone_debt(f)
    review_opening(f)
    voucher(f, "customer_advance", 100_000, party_id=customer.id)
    row = f["call"]("credit.apply", {"party_type": "customer", "party_id": customer.id, "amount": 100_000,
        "branch_id": f["branch"].id, "treasury_account_id": f["cash"].id,
        "allocations": [{"plan_id": plan.id, "amount": 100_000}]})
    assert plan.paid_amount == 200_000 and balance(f) == 20_100_000
    assert ledger.account("receivable").balance == 300_000 and ledger.account("customer_advance").balance == 0
    f["call"]("voucher.reverse", {"id": row["id"], "version": row["version"], "reason": "تصحيح تسوية الرصيد"})
    assert plan.paid_amount == 100_000 and balance(f) == 20_100_000
    assert ledger.account("receivable").balance == 400_000 and ledger.account("customer_advance").balance == 100_000


def test_standalone_collection_requires_review_and_rollback_is_retryable(finance, monkeypatch):
    from modules.finance import ledger
    from modules.finance.common import FinanceError
    from models.customer_credit import CustomerCreditPayment
    from models.receipt import Receipt
    f = finance
    customer, plan = standalone_debt(f)
    with pytest.raises(FinanceError, match="اعتمد الديون"):
        voucher(f, "customer_payment", 100_000, party_id=customer.id, allocations=[{"plan_id": plan.id, "amount": 100_000}])
    assert plan.paid_amount == 100_000 and CustomerCreditPayment.query.count() == Receipt.query.count() == 0
    review_opening(f)
    original = ledger.post
    def fail(*args, **kwargs):
        raise RuntimeError("posting failed")
    monkeypatch.setattr(ledger, "post", fail)
    key = uuid4().hex
    values = {"category": "customer_payment", "party_id": customer.id, "amount": 100_000, "intent": "post",
        "branch_id": f["branch"].id, "treasury_account_id": f["cash"].id,
        "allocations": [{"plan_id": plan.id, "amount": 100_000}]}
    with pytest.raises(RuntimeError, match="posting failed"):
        f["call"]("voucher.create", values, key)
    assert plan.paid_amount == 100_000 and balance(f) == 20_000_000
    assert CustomerCreditPayment.query.count() == Receipt.query.count() == 0
    monkeypatch.setattr(ledger, "post", original)
    posted = f["call"]("voucher.create", values, key)
    assert posted == f["call"]("voucher.create", values, key)
    assert plan.paid_amount == 200_000 and balance(f) == 20_100_000


def test_customer_debt_summary_does_not_truncate_at_200_documents(finance):
    from models.customer import Customer
    from models.invoice import Invoice
    f = finance
    customer = Customer(name="كشف طويل", phone="07000001001", branch_id=f["branch"].id)
    f["db"].session.add(customer)
    f["db"].session.flush()
    f["db"].session.add_all([Invoice(customer_id=customer.id, customer_name=customer.name,
        branch_id=f["branch"].id, total=1000, paid_amount=0, status="تم التوصيل", payment_status="غير مسدد") for _ in range(205)])
    f["db"].session.commit()
    data = f["get"](f"/api/finance/parties/customer/{customer.id}").get_json()["data"]
    assert len(data["invoices"]) == 200 and data["debt"] == 205_000


@pytest.mark.parametrize("recognized", [0, 400_000, 500_000])
def test_existing_opening_debt_upgrade_is_reviewed_once_without_other_balance_changes(finance, recognized):
    import json
    from modules.finance import ledger
    from modules.finance.common import FinanceError
    from modules.finance.models import FinancePolicy, FinanceSourceState
    f = finance
    review_opening(f)
    record = f["db"].session.get(FinancePolicy, 1)
    settings = json.loads(record.settings)
    settings.pop("standalone_debts_reviewed")
    settings["ledger_live"] = False
    record.settings = json.dumps(settings)
    f["db"].session.commit()
    _, plan = standalone_debt(f)
    settings["ledger_live"] = True
    record.settings = json.dumps(settings)
    f["db"].session.commit()
    from models.journal_entry import JournalEntry
    from datetime import datetime
    if recognized:
        f["db"].session.add(JournalEntry(entry_number=f"OLD-DEBT-{uuid4().hex}", description="رصيد مسجل سابقاً",
            reference_type="legacy_test", reference_id=plan.id, debit_account_id=ledger.account("receivable").id,
            credit_account_id=ledger.account("opening_equity").id, amount=recognized,
            entry_date=datetime.now(), created_by=f["admin"].id))
        f["db"].session.commit()
    before_entries = JournalEntry.query.count()
    before_cash = ledger.treasury_gl(f["cash"]).balance
    before_bank = ledger.treasury_gl(f["bank"]).balance
    before_payable = ledger.account("payable").balance
    preview = f["get"]("/api/finance/migration/preview").get_json()["data"]
    assert preview["complete"] and preview["debt_upgrade_required"] and len(preview["rows"]) == 1
    assert preview["rows"][0]["difference"] == 400_000-recognized
    with pytest.raises(FinanceError, match="تغيّرت الأرصدة"):
        f["call"]("migration.apply", {"preview_hash": "stale", "reason": "فحص مراجعة قديمة"})
    values = {"preview_hash": preview["hash"], "reason": "مراجعة الديون المستقلة فقط"}
    key = uuid4().hex
    result = f["call"]("migration.apply", values, key)
    assert result == f["call"]("migration.apply", values, key)
    assert ledger.account("receivable").balance == 400_000
    assert JournalEntry.query.count() == before_entries + (1 if recognized != 400_000 else 0)
    assert f["db"].session.get(FinanceSourceState, f"customer_debt:{plan.id}") is not None
    assert ledger.treasury_gl(f["cash"]).balance == before_cash
    assert ledger.treasury_gl(f["bank"]).balance == before_bank
    assert ledger.account("payable").balance == before_payable
    with pytest.raises(FinanceError, match="معتمدة مسبقاً"):
        f["call"]("migration.apply", values)


def test_new_standalone_principal_edit_posts_no_revenue_or_cash(finance):
    from models.customer import Customer
    from utils.customer_credit_service import create_credit_plan, update_credit_plan
    from modules.finance import ledger
    from modules.finance.common import FinanceError
    f = finance
    review_opening(f)
    customer = Customer(name="رصيد سابق مضاف", phone="07002003004", branch_id=f["branch"].id)
    f["db"].session.add(customer)
    f["db"].session.flush()
    plan = create_credit_plan(customer.id, "manual", 400_000, 2, date.today(), "monthly")
    f["db"].session.commit()
    assert ledger.account("receivable").balance == 400_000 and balance(f) == 20_000_000
    update_credit_plan(plan.id, total_amount=500_000)
    f["db"].session.commit()
    assert ledger.account("receivable").balance == 500_000 and balance(f) == 20_000_000
    assert ledger.account("revenue").balance == ledger.account("other_revenue").balance == 0
    from models.invoice import Invoice
    invoice = Invoice(customer_id=customer.id, customer_name=customer.name, branch_id=f["branch"].id,
        total=0, paid_amount=0, status="تم الطلب", payment_status="غير مسدد")
    f["db"].session.add(invoice)
    f["db"].session.commit()
    plan.invoice_id = invoice.id
    with pytest.raises(FinanceError, match="تغيير ربط"):
        f["db"].session.commit()
    f["db"].session.rollback()
    assert plan.invoice_id is None and ledger.account("receivable").balance == 500_000


def test_linked_plan_cannot_be_reclassified_as_standalone_after_opening(finance):
    from modules.finance import ledger
    from modules.finance.common import FinanceError
    f = finance
    _, invoice, plan = installment_invoice(f)
    invoice.status = "تم التوصيل"
    f["db"].session.commit()
    review_opening(f)
    assert ledger.account("receivable").balance == 400_000
    plan.invoice_id = None
    with pytest.raises(FinanceError, match="تغيير ربط"):
        f["db"].session.commit()
    f["db"].session.rollback()
    assert plan.invoice_id == invoice.id and ledger.account("receivable").balance == 400_000


@pytest.mark.parametrize("change", ["overpayment", "schedule", "duplicate", "other_customer", "other_branch", "ambiguous"])
def test_standalone_approval_revalidates_source_atomically(finance, change):
    from modules.finance.common import FinanceError
    from models.customer import Customer
    from models.branch import Branch
    from models.receipt import Receipt
    from models.customer_credit import CustomerCreditPayment
    f = finance
    customer, plan = standalone_debt(f)
    review_opening(f)
    allocations = [{"plan_id": plan.id, "amount": 100_000}]
    amount = 100_000
    if change == "overpayment":
        amount = 450_000
        allocations[0]["amount"] = amount
    elif change == "schedule":
        # A corrupted legacy schedule must not be silently repaired during payment.
        from sqlalchemy import update
        from models.customer_credit import CustomerInstallment
        f["db"].session.execute(update(CustomerInstallment).where(CustomerInstallment.id == plan.installments[0].id).values(amount=200_000))
        f["db"].session.commit()
        f["db"].session.expire_all()
    elif change == "duplicate":
        amount = 200_000
        allocations.append({"plan_id": plan.id, "amount": 100_000})
    elif change == "other_customer":
        other = Customer(name="عميل آخر", phone="07009992233", branch_id=f["branch"].id)
        f["db"].session.add(other)
        f["db"].session.commit()
        customer = other
    elif change == "other_branch":
        branch = Branch(code="OTHER-DEBT", name="فرع آخر", is_active=True)
        f["db"].session.add(branch)
        f["db"].session.flush()
        customer.branch_id = branch.id
        f["db"].session.commit()
    elif change == "ambiguous":
        allocations[0]["invoice_id"] = 1
    with pytest.raises(FinanceError):
        voucher(f, "customer_payment", amount, party_id=customer.id, allocations=allocations)
    assert plan.paid_amount == 100_000 and balance(f) == 20_000_000 and balance(f, "bank") == 0
    assert CustomerCreditPayment.query.count() == Receipt.query.count() == 0


def test_standalone_posted_history_cannot_be_edited_directly(finance):
    from modules.finance.common import FinanceError
    from models.customer_credit import CustomerCreditPayment
    from models.account_transaction import AccountTransaction
    f = finance
    customer, plan = standalone_debt(f)
    review_opening(f)
    voucher(f, "customer_payment", 100_000, party_id=customer.id, allocations=[{"plan_id": plan.id, "amount": 100_000}])
    payment = CustomerCreditPayment.query.filter_by(plan_id=plan.id).first()
    payment.amount = 1
    with pytest.raises(FinanceError, match="السجل مرتبط بسند"):
        f["db"].session.commit()
    f["db"].session.rollback()
    transaction = AccountTransaction.query.filter(AccountTransaction.note.like("%[FV:%")).first()
    transaction.amount = 1
    with pytest.raises(FinanceError, match="السجل مرتبط بسند"):
        f["db"].session.commit()
    f["db"].session.rollback()
    assert plan.paid_amount == 200_000 and payment.amount == transaction.amount == 100_000


@pytest.mark.parametrize("action", ["collect", "reverse"])
def test_standalone_rejects_unposted_balance_changes(finance, action):
    from sqlalchemy import update
    from modules.finance.common import FinanceError
    from models.customer_credit import CustomerCreditPlan, CustomerInstallment
    f = finance
    customer, plan = standalone_debt(f)
    review_opening(f)
    row = voucher(f, "customer_payment", 100_000, party_id=customer.id,
        treasury_account_id=f["bank"].id, allocations=[{"plan_id": plan.id, "amount": 100_000}])
    f["db"].session.execute(update(CustomerCreditPlan).where(CustomerCreditPlan.id == plan.id).values(paid_amount=250_000))
    f["db"].session.execute(update(CustomerInstallment).where(CustomerInstallment.id == plan.installments[0].id).values(paid_amount=250_000))
    f["db"].session.commit()
    f["db"].session.expire_all()
    with pytest.raises(FinanceError, match="مصدره المحاسبي"):
        if action == "collect":
            voucher(f, "customer_payment", 100_000, party_id=customer.id, allocations=[{"plan_id": plan.id, "amount": 100_000}])
        else:
            f["call"]("voucher.reverse", {"id": row["id"], "version": row["version"], "reason": "فحص رصيد تغير خارج الترحيل"})
    assert plan.paid_amount == 250_000 and balance(f, "bank") == 100_000 and balance(f) == 20_000_000


def test_draft_has_no_money_effect_and_retry_is_exactly_once(finance):
    from modules.finance.models import FinanceVoucher, FinanceJournalLink
    f = finance
    values = {"category":"expense", "amount":200_000, "treasury_account_id":f["cash"].id, "branch_id":f["branch"].id, "party_name":"كهرباء"}
    key = uuid4().hex
    first = f["call"]("voucher.create", values, key)
    assert first == f["call"]("voucher.create", values, key)
    assert balance(f) == 20_000_000
    assert FinanceVoucher.query.count() == 1
    assert FinanceJournalLink.query.count() == 0
    posted = f["call"]("voucher.approve", {"id":first["id"], "version":first["version"]})
    assert posted["status"] == "posted"
    assert balance(f) == 19_800_000
    assert FinanceJournalLink.query.count() == 1


def test_similar_manual_vouchers_warn_without_blocking_legitimate_payments(finance):
    f = finance
    first = voucher(f, "expense", 200_000, party_name="كهرباء")
    second = voucher(f, "expense", 200_000, party_name="كهرباء")
    assert balance(f) == 19_600_000
    notices = f["get"]("/api/finance/notifications").get_json()["data"]["items"]
    duplicates = [item for item in notices if item["type"] == "possible_duplicate"]
    assert len(duplicates) == 1
    assert duplicates[0]["source_id"] in {first["id"], second["id"]}
    assert first["number"] in duplicates[0]["title"] and second["number"] in duplicates[0]["title"]


def test_six_million_borrowing_and_principal_payment_do_not_make_profit(finance):
    from modules.finance import ledger
    f = finance
    loan = f["call"]("loan.create", {"direction":"borrowed", "party_name":"المصرف", "principal":6_000_000, "instalments":12, "first_due":date.today().isoformat(), "treasury_account_id":f["cash"].id, "branch_id":f["branch"].id})
    assert balance(f) == 20_000_000
    funded = f["call"]("loan.fund", {"id":loan["id"], "version":loan["version"]})
    assert balance(f) == 26_000_000
    assert [r["principal"] for r in funded["schedule"]] == [500_000] * 12
    paid = f["call"]("loan.pay", {"id":funded["id"], "version":funded["version"], "amount":500_000})
    assert paid["remaining_principal"] == 5_500_000
    assert balance(f) == 25_500_000
    assert ledger.account("loan_payable").balance == 5_500_000
    assert ledger.account("interest_expense").balance == ledger.account("other_revenue").balance == 0


def test_partial_customer_receipt_and_reversal_preserve_invoice(finance):
    from models.customer import Customer
    from models.invoice import Invoice
    from modules.finance.common import FinanceError
    f = finance
    c = Customer(name="زبون", phone="07000000000", branch_id=f["branch"].id)
    f["db"].session.add(c)
    f["db"].session.flush()
    invoice = Invoice(customer_id=c.id, customer_name=c.name, branch_id=f["branch"].id, total=400_000, paid_amount=0, status="مكتمل", payment_status="غير مدفوع")
    f["db"].session.add(invoice)
    f["db"].session.commit()
    row = voucher(f, "customer_payment", 150_000, party_id=c.id)
    assert invoice.total - invoice.paid_amount == 250_000
    statement = f["get"](f"/api/finance/parties/customer/{c.id}").get_json()["data"]
    assert statement["debt"] == 250_000 and statement["credit"] == 0
    assert statement["invoices"][0]["remaining"] == 250_000
    assert [movement["id"] for movement in statement["movements"]] == [row["id"]]
    assert balance(f) == 20_150_000
    with pytest.raises(FinanceError):
        voucher(f, "customer_payment", 300_000, party_id=c.id)
    assert invoice.paid_amount == 150_000
    f["call"]("voucher.reverse", {"id":row["id"], "version":row["version"], "reason":"خطأ بالقبض"})
    assert invoice.paid_amount == 0
    assert balance(f) == 20_000_000


def test_customer_finance_collection_keeps_installments_and_legacy_payment_consistent(finance):
    from models.customer_credit import CustomerCreditPayment
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from utils.customer_credit_service import allocate_payment_fifo
    from utils.treasury_helpers import get_default_cash_account
    from utils.treasury_calculations import calculate_treasury_balance
    from flask import g
    f = finance
    customer, invoice, plan = installment_invoice(f)
    # The legacy screen uses the company's default cash; finance keeps the selected account.
    g.independent_branches_enabled = False
    cash_id = get_default_cash_account().id
    # Shared cash aggregates historical cash rows once, through the canonical account.
    liquidity = lambda: calculate_treasury_balance(cash_id)
    opening = liquidity()
    key = uuid4().hex
    values = {"category":"customer_payment", "amount":250_000, "treasury_account_id":f["cash"].id,
        "branch_id":f["branch"].id, "party_id":customer.id, "intent":"post"}
    row = f["call"]("voucher.create", values, key)
    assert invoice.paid_amount == plan.paid_amount == 250_000
    assert [i.paid_amount for i in plan.installments] == [200_000, 50_000]
    assert [i.status for i in plan.installments] == ["paid", "partial"]
    assert sum(p.amount for p in plan.payments) == 250_000
    assert row == f["call"]("voucher.create", values, key)
    assert CustomerCreditPayment.query.count() == 2
    assert balance(f) == 20_250_000
    html = f["get"](f"/accounts/finance/vouchers/{row['id']}/print")
    assert "دفعة قسط" in html and "فاتورة بيع" in html and "قبضاً إضافياً" in html
    assert "credit_plan_payment" not in html
    artifacts = Path(__file__).parent / "_artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "finance-customer-installments.html").write_text(html, encoding="utf-8")
    import json
    (artifacts / "finance-customer-installments.json").write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    _, applied = allocate_payment_fifo(customer.id, 50_000, employee_id=f["admin"].id)
    f["db"].session.commit()
    assert applied == 50_000
    assert invoice.paid_amount == plan.paid_amount == 300_000
    assert [i.paid_amount for i in plan.installments] == [200_000, 100_000]
    assert liquidity() == opening + 300_000
    assert sum(e.amount_delta for e in InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id)) == 300_000
    reversal_key = uuid4().hex
    reversal = {"id":row["id"], "version":row["version"], "reason":"عكس سند التحصيل فقط"}
    reversed_row = f["call"]("voucher.reverse", reversal, reversal_key)
    assert invoice.paid_amount == plan.paid_amount == 50_000
    assert [i.paid_amount for i in plan.installments] == [0, 50_000]
    assert [i.status for i in plan.installments] == ["pending", "partial"]
    assert sum(p.amount for p in plan.payments) == 50_000
    assert sum(p.amount for p in CustomerCreditPayment.query.filter(CustomerCreditPayment.amount < 0)) == -250_000
    assert liquidity() == opening + 50_000
    assert sum(e.amount_delta for e in InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id)) == 50_000
    assert reversed_row == f["call"]("voucher.reverse", reversal, reversal_key)
    assert CustomerCreditPayment.query.count() == 5


def installment_invoice(f):
    from models.customer import Customer
    from models.invoice import Invoice
    from utils.customer_credit_service import create_credit_plan
    customer = Customer(name="زبون أقساط", phone="07701234567", branch_id=f["branch"].id)
    f["db"].session.add(customer)
    f["db"].session.flush()
    invoice = Invoice(customer_id=customer.id, customer_name=customer.name, branch_id=f["branch"].id,
        total=400_000, paid_amount=0, status="مكتمل", payment_status="غير مسدد")
    f["db"].session.add(invoice)
    f["db"].session.flush()
    plan = create_credit_plan(customer.id, "products", 400_000, 2, date.today(), "monthly", invoice_id=invoice.id)
    f["db"].session.commit()
    return customer, invoice, plan


def adjust_invoice_collection(f, invoice, paid):
    from flask import session
    from routes.orders import adjust_payment
    status = "مسدد" if paid == invoice.total else "جزئي" if paid else "غير مسدد"
    with f["app"].test_request_context("/orders/payment/adjust", method="POST",
            json={"id": invoice.id, "payment": status, "paid_amount": paid}):
        session.update(user_id=f["admin"].id, employee_id=f["admin"].id, role="admin")
        return f["app"].make_response(adjust_payment())


def test_invoice_payment_edit_preserves_finance_slices_and_their_bank(finance):
    from flask import g
    from models.customer_credit import CustomerCreditPayment
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from modules.finance import ledger
    from utils.treasury_helpers import get_default_cash_account
    from utils.treasury_calculations import calculate_treasury_balance
    f = finance
    customer, invoice, plan = installment_invoice(f)
    g.independent_branches_enabled = False
    cash_id = get_default_cash_account(f["branch"].id).id
    opening = calculate_treasury_balance(cash_id)
    review_opening(f)
    row = voucher(f, "customer_payment", 150_000, party_id=customer.id,
        treasury_account_id=f["bank"].id)
    assert adjust_invoice_collection(f, invoice, 300_000).status_code == 200
    assert invoice.paid_amount == plan.paid_amount == 300_000
    assert [i.paid_amount for i in plan.installments] == [200_000, 100_000]
    assert calculate_treasury_balance(cash_id) == opening + 150_000
    assert balance(f, "bank") == 150_000
    assert ledger.account("receivable").balance == 100_000
    count = CustomerCreditPayment.query.count()
    assert adjust_invoice_collection(f, invoice, 300_000).status_code == 200
    assert CustomerCreditPayment.query.count() == count
    # Reducing the legacy portion must never withdraw the bank voucher's money.
    assert adjust_invoice_collection(f, invoice, 200_000).status_code == 200
    assert [i.paid_amount for i in plan.installments] == [200_000, 0]
    assert calculate_treasury_balance(cash_id) == opening + 50_000
    assert balance(f, "bank") == 150_000
    assert sum(p.amount for p in plan.payments) == 200_000
    before_rows = InvoicePaymentLedger.query.count()
    rejected = adjust_invoice_collection(f, invoice, 100_000)
    assert rejected.status_code == 409 and "السند الأصلي" in rejected.get_json()["error"]
    assert invoice.paid_amount == plan.paid_amount == 200_000
    assert InvoicePaymentLedger.query.count() == before_rows
    assert balance(f, "bank") == 150_000
    f["call"]("voucher.reverse", {"id":row["id"], "version":row["version"], "reason":"عكس التحصيل المصرفي"})
    assert invoice.paid_amount == plan.paid_amount == 50_000
    assert [i.paid_amount for i in plan.installments] == [50_000, 0]
    assert balance(f, "bank") == 0
    assert adjust_invoice_collection(f, invoice, 0).status_code == 200
    assert invoice.paid_amount == plan.paid_amount == 0
    assert sum(p.amount for p in plan.payments) == 0
    assert calculate_treasury_balance(cash_id) == opening
    assert ledger.account("receivable").balance == 400_000


def test_split_invoice_payment_allocates_installments_only_once(finance):
    from flask import session
    from routes.orders import payment
    from models.customer_credit import CustomerCreditPayment
    f = finance
    _, invoice, plan = installment_invoice(f)
    with f["app"].test_request_context("/orders/payment", method="POST", json={
            "id":invoice.id, "payment":"مسدد", "payment_allocations":[
                {"amount":150_000, "treasury_account_id":f["cash"].id},
                {"amount":250_000, "treasury_account_id":f["bank"].id}]}):
        session.update(user_id=f["admin"].id, role="admin")
        response = f["app"].make_response(payment())
    assert response.status_code == 200, response.get_json()
    assert invoice.paid_amount == plan.paid_amount == 400_000
    assert [i.paid_amount for i in plan.installments] == [200_000, 200_000]
    assert CustomerCreditPayment.query.count() == 2
    assert sum(p.amount for p in plan.payments) == 400_000
    assert balance(f) == 20_150_000 and balance(f, "bank") == 250_000


@pytest.mark.parametrize("invalid", ["amount", "invoice_balance", "payment_slices"])
def test_invoice_payment_edit_rejects_corrupt_schedule_atomically(finance, invalid):
    from models.customer_credit import CustomerCreditPayment
    from models.invoice_payment_ledger import InvoicePaymentLedger
    f = finance
    _, invoice, plan = installment_invoice(f)
    if invalid == "amount":
        plan.installments[0].amount -= 1
    elif invalid == "invoice_balance":
        invoice.paid_amount = 10_000
        invoice.payment_status = "جزئي"
    else:
        invoice.paid_amount = plan.paid_amount = 10_000
        invoice.payment_status = "جزئي"
        plan.installments[0].paid_amount = 10_000
        f["db"].session.add(CustomerCreditPayment(customer_id=plan.customer_id, plan_id=plan.id,
            installment_id=plan.installments[1].id, amount=10_000))
    f["db"].session.commit()
    previous_paid = invoice.paid_amount
    previous_plan = plan.paid_amount
    previous_rows = CustomerCreditPayment.query.count()
    response = adjust_invoice_collection(f, invoice, 50_000)
    assert response.status_code == 409
    assert invoice.paid_amount == previous_paid and plan.paid_amount == previous_plan
    assert CustomerCreditPayment.query.count() == previous_rows
    assert InvoicePaymentLedger.query.count() == 0
    assert balance(f) == 20_000_000


def test_invoice_payment_edit_rolls_back_slices_and_retries(finance, monkeypatch):
    from models.customer_credit import CustomerCreditPayment
    from modules.finance import ledger
    f = finance
    _, invoice, plan = installment_invoice(f)
    review_opening(f)
    original = ledger.post
    def fail(*args, **kwargs):
        raise RuntimeError("forced invoice posting failure")
    monkeypatch.setattr(ledger, "post", fail)
    assert adjust_invoice_collection(f, invoice, 250_000).status_code == 500
    assert invoice.paid_amount == plan.paid_amount == 0
    assert CustomerCreditPayment.query.count() == 0
    monkeypatch.setattr(ledger, "post", original)
    assert adjust_invoice_collection(f, invoice, 250_000).status_code == 200
    assert invoice.paid_amount == plan.paid_amount == 250_000
    assert [i.paid_amount for i in plan.installments] == [200_000, 50_000]
    assert CustomerCreditPayment.query.count() == 2


def test_invoice_payment_edit_keeps_old_unitemized_balance_in_signed_history(finance):
    from flask import g
    from modules.finance import ledger
    from utils.treasury_helpers import get_default_cash_account
    from utils.treasury_calculations import calculate_treasury_balance
    f = finance
    _, invoice, plan = installment_invoice(f)
    g.independent_branches_enabled = False
    cash_id = get_default_cash_account().id
    invoice.paid_amount = plan.paid_amount = plan.installments[0].paid_amount = 100_000
    invoice.payment_status = "جزئي"
    f["db"].session.commit()
    review_opening(f)
    assert calculate_treasury_balance(cash_id) == 20_100_000
    assert adjust_invoice_collection(f, invoice, 250_000).status_code == 200
    assert [i.paid_amount for i in plan.installments] == [200_000, 50_000]
    assert sum(p.amount for p in plan.payments) == 250_000
    assert calculate_treasury_balance(cash_id) == 20_250_000
    assert ledger.account("receivable").balance == 150_000
    original = next(p for p in plan.payments if "رصيد أقساط سابق" in p.note)
    assert original.amount == 100_000 and original.created_at == plan.created_at
    assert adjust_invoice_collection(f, invoice, 50_000).status_code == 200
    assert [i.paid_amount for i in plan.installments] == [50_000, 0]
    assert sum(p.amount for p in plan.payments) == 50_000
    assert original.amount == 100_000
    assert calculate_treasury_balance(cash_id) == 20_050_000
    assert ledger.account("receivable").balance == 350_000


def test_invoice_without_schedule_cannot_reduce_a_finance_voucher_from_orders(finance):
    from models.invoice_payment_ledger import InvoicePaymentLedger
    f = finance
    customer, invoice, plan = installment_invoice(f)
    f["db"].session.delete(plan)
    f["db"].session.commit()
    row = voucher(f, "customer_payment", 100_000, party_id=customer.id,
        treasury_account_id=f["bank"].id)
    rejected = adjust_invoice_collection(f, invoice, 0)
    assert rejected.status_code == 409
    assert invoice.paid_amount == 100_000 and balance(f, "bank") == 100_000
    assert InvoicePaymentLedger.query.count() == 1
    f["call"]("voucher.reverse", {"id":row["id"], "version":row["version"], "reason":"عكس السند قبل التعديل"})
    assert invoice.paid_amount == 0 and balance(f, "bank") == 0


def test_customer_installments_bank_collection_and_advance_offset_keep_cash_separate(finance):
    from modules.finance import ledger
    from models.customer_credit import CustomerCreditPayment
    f = finance
    customer, invoice, plan = installment_invoice(f)
    voucher(f, "customer_advance", 100_000, party_id=customer.id)
    offset = f["call"]("credit.apply", {"party_type":"customer", "party_id":customer.id,
        "branch_id":f["branch"].id, "amount":75_000})
    assert invoice.paid_amount == plan.paid_amount == 75_000
    assert balance(f) == 20_100_000 and balance(f, "bank") == 0
    bank_values = {"category":"customer_payment", "amount":250_000, "party_id":customer.id,
        "treasury_account_id":f["bank"].id, "branch_id":f["branch"].id, "intent":"post"}
    key = uuid4().hex
    bank = f["call"]("voucher.create", bank_values, key)
    assert invoice.paid_amount == plan.paid_amount == 325_000
    assert [i.paid_amount for i in plan.installments] == [200_000, 125_000]
    assert balance(f) == 20_100_000 and balance(f, "bank") == 250_000
    assert bank == f["call"]("voucher.create", bank_values, key)
    assert CustomerCreditPayment.query.count() == 3
    f["call"]("voucher.reverse", {"id":offset["id"], "version":offset["version"], "reason":"فك التسوية"})
    assert invoice.paid_amount == plan.paid_amount == 250_000
    assert [i.paid_amount for i in plan.installments] == [125_000, 125_000]
    assert balance(f) == 20_100_000 and balance(f, "bank") == 250_000
    f["call"]("voucher.reverse", {"id":bank["id"], "version":bank["version"], "reason":"عكس قبض المصرف"})
    assert invoice.paid_amount == plan.paid_amount == 0
    assert [i.paid_amount for i in plan.installments] == [0, 0]
    assert sum(p.amount for p in plan.payments) == 0
    assert balance(f) == 20_100_000 and balance(f, "bank") == 0
    assert ledger.account("receivable").balance == 0
    assert ledger.account("other_revenue").balance == ledger.account("expense").balance == 0


@pytest.mark.parametrize("invalid", ["duplicate", "customer", "total", "paid", "schedule"])
def test_customer_installment_mismatch_rejects_collection_atomically(finance, invalid):
    from models.customer import Customer
    from models.customer_credit import CustomerCreditPayment
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.receipt import Receipt
    from modules.finance.common import FinanceError
    from modules.finance.models import FinanceVoucher
    from utils.customer_credit_service import create_credit_plan
    f = finance
    customer, invoice, plan = installment_invoice(f)
    if invalid == "duplicate":
        create_credit_plan(customer.id, "products", 400_000, 2, date.today(), "monthly", invoice_id=invoice.id)
    elif invalid == "customer":
        other = Customer(name="عميل آخر", phone="07700000002", branch_id=f["branch"].id)
        f["db"].session.add(other)
        f["db"].session.flush()
        plan.customer_id = other.id
    elif invalid == "total":
        plan.total_amount -= 1
    elif invalid == "paid":
        plan.paid_amount = 1
    else:
        plan.installments[0].amount -= 1
    f["db"].session.commit()
    before_paid = plan.paid_amount
    with pytest.raises(FinanceError) as error:
        voucher(f, "customer_payment", 100_000, party_id=customer.id)
    assert error.value.code == "conflict"
    assert invoice.paid_amount == 0 and plan.paid_amount == before_paid
    assert balance(f) == 20_000_000
    assert FinanceVoucher.query.count() == Receipt.query.count() == CustomerCreditPayment.query.count() == 0
    assert InvoicePaymentLedger.query.count() == 0


def test_customer_installment_collection_rolls_back_after_allocation_and_retries_same_key(finance, monkeypatch):
    from models.customer_credit import CustomerCreditPayment
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.receipt import Receipt
    from modules.finance import ledger
    from modules.finance.models import FinanceVoucher
    f = finance
    customer, invoice, plan = installment_invoice(f)
    values = {"category":"customer_payment", "amount":250_000, "party_id":customer.id,
        "treasury_account_id":f["cash"].id, "branch_id":f["branch"].id, "intent":"post"}
    key = uuid4().hex
    def fail(*args, **kwargs):
        raise RuntimeError("failed after allocation")
    with monkeypatch.context() as patch:
        patch.setattr(ledger, "post", fail)
        with pytest.raises(RuntimeError, match="after allocation"):
            f["call"]("voucher.create", values, key)
    assert invoice.paid_amount == plan.paid_amount == 0
    assert [i.paid_amount for i in plan.installments] == [0, 0]
    assert FinanceVoucher.query.count() == Receipt.query.count() == CustomerCreditPayment.query.count() == 0
    assert InvoicePaymentLedger.query.count() == 0 and balance(f) == 20_000_000
    row = f["call"]("voucher.create", values, key)
    assert row == f["call"]("voucher.create", values, key)
    assert invoice.paid_amount == plan.paid_amount == 250_000
    assert CustomerCreditPayment.query.count() == 2 and balance(f) == 20_250_000


def test_customer_installment_reversal_rejects_changed_schedule_without_partial_effects(finance):
    from models.customer_credit import CustomerCreditPayment
    from modules.finance.common import FinanceError
    from modules.finance.models import FinanceVoucher
    f = finance
    customer, invoice, plan = installment_invoice(f)
    row = voucher(f, "customer_payment", 250_000, party_id=customer.id)
    plan.installments[0].paid_amount = 10_000
    f["db"].session.commit()
    with pytest.raises(FinanceError):
        f["call"]("voucher.reverse", {"id":row["id"], "version":row["version"], "reason":"جدول متغير"})
    assert invoice.paid_amount == plan.paid_amount == 250_000
    assert FinanceVoucher.query.count() == 1 and FinanceVoucher.query.one().status == "posted"
    assert CustomerCreditPayment.query.count() == 2 and balance(f) == 20_250_000


def test_customer_workspace_collection_rechecks_live_debt_before_approval(finance):
    from models.customer_credit import CustomerCreditPayment
    from modules.finance.common import FinanceError
    from modules.finance.models import FinanceVoucher
    from utils.customer_credit_service import allocate_payment_fifo
    f = finance
    customer, invoice, plan = installment_invoice(f)
    invoice.status = "تم التوصيل"
    f["db"].session.commit()
    path = f"/api/v1/desktop/customers/{customer.id}/history?kind=receivables"
    document = f["get"](path).get_json()["data"]["items"][0]
    assert document["id"] == invoice.id and document["branch_id"] == f["branch"].id
    assert document["remaining"] == 400_000
    draft = f["call"]("voucher.create", {"category":"customer_payment", "amount":250_000,
        "treasury_account_id":f["bank"].id, "branch_id":document["branch_id"],
        "party_id":customer.id, "intent":"draft", "allocations":[{"invoice_id":document["id"], "amount":250_000}]})
    assert invoice.paid_amount == plan.paid_amount == 0 and balance(f, "bank") == 0
    allocate_payment_fifo(customer.id, 200_000, employee_id=f["admin"].id)
    f["db"].session.commit()
    with pytest.raises(FinanceError) as failure:
        f["call"]("voucher.approve", {"id":draft["id"], "version":draft["version"]})
    assert failure.value.code == "conflict"
    assert invoice.paid_amount == plan.paid_amount == 200_000 and balance(f, "bank") == 0
    assert FinanceVoucher.query.one().status == "draft" and CustomerCreditPayment.query.count() == 1
    edited = f["call"]("voucher.edit", {"id":draft["id"], "version":draft["version"],
        "amount":150_000, "allocations":[{"invoice_id":invoice.id,"amount":150_000}]})
    key = uuid4().hex
    approved = f["call"]("voucher.approve", {"id":edited["id"],"version":edited["version"]}, key)
    assert approved == f["call"]("voucher.approve", {"id":edited["id"],"version":edited["version"]}, key)
    assert invoice.paid_amount == plan.paid_amount == 350_000 and balance(f, "bank") == 150_000
    assert f["get"](path).get_json()["data"]["summary"]["remaining"] == 50_000
    f["call"]("voucher.reverse", {"id":approved["id"],"version":approved["version"],"reason":"عكس التحصيل المصرفي"})
    assert invoice.paid_amount == plan.paid_amount == 200_000 and balance(f, "bank") == 0
    assert f["get"](path).get_json()["data"]["summary"]["remaining"] == 200_000


def test_finance_supplier_payment_uses_posting_time_and_keeps_its_accounting_date(finance):
    from datetime import datetime
    from models.supplier import Supplier
    from models.purchase import Purchase
    from models.product import Product
    from models.supplier_payment import SupplierPayment
    from models.supplier_payment_allocation import SupplierPaymentAllocation
    f = finance
    supplier = Supplier(name="مورد توقيت التخصيص", branch_id=f["branch"].id,
        opening_balance=0, total_debt=600_000, total_paid=0)
    product = Product(name="منتج توقيت التخصيص", buy_price=200_000, sale_price=250_000,
        quantity=3, branch_id=f["branch"].id)
    f["db"].session.add_all([supplier, product])
    f["db"].session.flush()
    on = date.today() - timedelta(days=2)
    purchases = [Purchase(supplier_id=supplier.id, product_id=product.id, quantity=1, price=200_000,
        branch_id=f["branch"].id, total=200_000,
        grand_total=200_000, paid_total=0, status="confirmed", purchase_mode="credit",
        purchase_date=day, created_at=created)
        for day, created in [(on, datetime.utcnow()-timedelta(minutes=1)),
                             (on+timedelta(days=1), datetime.utcnow()-timedelta(minutes=1)),
                             (on, datetime.utcnow()+timedelta(days=1))]]
    f["db"].session.add_all(purchases)
    f["db"].session.commit()
    row = voucher(f, "supplier_payment", 150_000, party_id=supplier.id, transaction_date=on.isoformat())
    payment = SupplierPayment.query.filter_by(source_module="finance").one()
    assert payment.created_at.date() == on
    allocation = SupplierPaymentAllocation.query.filter_by(supplier_payment_id=payment.id).one()
    assert allocation.purchase_id == purchases[0].id and allocation.amount == 150_000
    assert balance(f) == 19_850_000 and supplier.remaining == 450_000
    f["call"]("voucher.reverse", {"id":row["id"], "version":row["version"], "reason":"عكس تخصيص مؤرخ"})
    assert supplier.remaining == 600_000 and balance(f) == 20_000_000


def test_supplier_payment_reduces_debt_without_expense(finance):
    from models.supplier import Supplier
    from modules.finance import ledger
    f = finance
    supplier = Supplier(name="مورد", branch_id=f["branch"].id, opening_balance=2_000_000, total_debt=2_000_000, total_paid=0)
    f["db"].session.add(supplier)
    f["db"].session.commit()
    voucher(f, "supplier_payment", 750_000, party_id=supplier.id)
    assert supplier.remaining == 1_250_000
    assert balance(f) == 19_250_000
    assert ledger.account("expense").balance == 0


def test_specific_purchase_payment_and_detail_do_not_duplicate_stock_or_expense(finance):
    from models.supplier import Supplier
    from models.product import Product
    from models.purchase import Purchase
    from modules.finance import ledger
    from utils.supplier_payment_allocation import effective_purchase_payment_totals
    f=finance
    supplier=Supplier(name="مورد فاتورة",branch_id=f["branch"].id,total_debt=2_000_000,total_paid=0)
    product=Product(name="جهاز",buy_price=1_000_000,sale_price=1_200_000,quantity=2,branch_id=f["branch"].id)
    f["db"].session.add_all([supplier,product]);f["db"].session.flush()
    purchase=Purchase(supplier_id=supplier.id,product_id=product.id,quantity=2,price=1_000_000,total=2_000_000,
        grand_total=2_000_000,status="confirmed",stock_applied=True,branch_id=f["branch"].id)
    f["db"].session.add(purchase);f["db"].session.commit()
    row=voucher(f,"inventory_purchase",750_000,party_id=supplier.id,allocations=[{"purchase_id":purchase.id,"amount":750_000}])
    detail=f["get"](f"/api/finance/parties/supplier/{supplier.id}").get_json()["data"]
    assert detail["invoices"][0]["paid"]==750_000 and detail["debt"]==1_250_000
    assert effective_purchase_payment_totals(purchase)==(750_000,1_250_000,750_000)
    assert product.quantity==2 and ledger.account("expense").balance==0
    f["call"]("voucher.reverse",{"id":row["id"],"version":row["version"],"reason":"تصحيح فاتورة الدفع"})
    assert effective_purchase_payment_totals(purchase)==(0,2_000_000,0)
    assert balance(f)==20_000_000 and product.quantity==2


def test_opening_overpayments_become_usable_credit_without_repeating_cash(finance):
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from models.supplier import Supplier
    from models.supplier_payment import SupplierPayment
    from models.supplier_payment_allocation import SupplierPaymentAllocation
    from modules.finance import ledger
    f=finance
    customer=Customer(name="دفعة سابقة",phone="0701",branch_id=f["branch"].id)
    supplier=Supplier(name="مورد مقدم",branch_id=f["branch"].id,opening_balance=1000,total_debt=1000,total_paid=1300)
    f["db"].session.add_all([customer,supplier]);f["db"].session.flush()
    invoice=Invoice(customer_id=customer.id,customer_name=customer.name,total=500,paid_amount=700,status="تم التوصيل",branch_id=f["branch"].id)
    payment=SupplierPayment(supplier_id=supplier.id,amount=1300,payment_method="cash",branch_id=f["branch"].id,treasury_account_id=f["cash"].id)
    f["db"].session.add_all([invoice,payment]);f["db"].session.flush()
    f["db"].session.add(InvoicePaymentLedger(invoice_id=invoice.id,amount_delta=700,payment_method="cash",branch_id=f["branch"].id))
    f["db"].session.commit()
    before=balance(f)
    preview=f["get"]("/api/finance/migration/preview").get_json()["data"]
    assert preview["issues"]==[]
    f["call"]("migration.apply",{"preview_hash":preview["hash"],"reason":"مراجعة الدفعات السابقة"})
    assert balance(f)==before and invoice.paid_amount==500 and supplier.remaining==0
    assert ledger.account("customer_advance").balance==200 and ledger.account("supplier_advance").balance==300
    assert sum(a.amount for a in SupplierPaymentAllocation.query.filter_by(allocation_type="opening_credit").all())==300
    new_invoice=Invoice(customer_id=customer.id,customer_name=customer.name,total=400,paid_amount=0,status="تم التوصيل",branch_id=f["branch"].id)
    from flask import session
    with f["app"].test_request_context("/invoices"):
        session["user_id"]=f["admin"].id
        f["db"].session.add(new_invoice);f["db"].session.commit()
    applied=f["call"]("credit.apply",{"party_type":"customer","party_id":customer.id,"amount":150,"branch_id":f["branch"].id})
    assert balance(f)==before and new_invoice.paid_amount==150
    assert f["get"](f"/api/finance/parties/customer/{customer.id}").get_json()["data"]["credit"]==50
    f["call"]("voucher.reverse",{"id":applied["id"],"version":applied["version"],"reason":"تصحيح التخصيص"})
    assert balance(f)==before and new_invoice.paid_amount==0
    from models.product import Product
    from routes.purchases import _create_purchase_from_payload
    with f["app"].test_request_context("/purchases",method="POST"):
        session["user_id"]=f["admin"].id
        product=Product(name="شراء من رصيد سابق",buy_price=1000,sale_price=1200,quantity=0,branch_id=f["branch"].id)
        f["db"].session.add(product);f["db"].session.flush()
        purchase,error=_create_purchase_from_payload({"supplier_id":supplier.id,"_validated_branch_id":f["branch"].id,
            "invoice_no":"CREDIT-OPENING","status":"confirmed","purchase_mode":"credit",
            "items":[{"product_id":product.id,"quantity":1,"unit_cost_before_discount":1000}]},[],employee_id=f["admin"].id)
        assert not error,error
        assert supplier.remaining==1000
    applied=f["call"]("credit.apply",{"party_type":"supplier","party_id":supplier.id,"amount":250,"branch_id":f["branch"].id})
    assert supplier.remaining==750 and balance(f)==before
    detail=f["get"](f"/api/finance/parties/supplier/{supplier.id}").get_json()["data"]
    assert detail["credit"]==50 and detail["invoices"][0]["paid"]==250
    f["call"]("voucher.reverse",{"id":applied["id"],"version":applied["version"],"reason":"تصحيح التسوية"})
    assert supplier.remaining==1000 and balance(f)==before
    refunded=voucher(f,"supplier_refund",100,party_id=supplier.id)
    assert balance(f)==before+100
    assert f["get"](f"/api/finance/parties/supplier/{supplier.id}").get_json()["data"]["credit"]==200
    assert refunded["status"]=="posted"


def test_opening_review_blocks_inconsistent_legacy_customer_cash(finance):
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from modules.finance.common import FinanceError
    f=finance
    customer=Customer(name="دفعات غير متطابقة",phone="0702",branch_id=f["branch"].id)
    f["db"].session.add(customer);f["db"].session.flush()
    invoice=Invoice(customer_id=customer.id,customer_name=customer.name,total=100,paid_amount=200,status="تم التوصيل",branch_id=f["branch"].id)
    f["db"].session.add(invoice);f["db"].session.flush()
    f["db"].session.add(InvoicePaymentLedger(invoice_id=invoice.id,amount_delta=150,payment_method="cash",branch_id=f["branch"].id))
    f["db"].session.commit()
    preview=f["get"]("/api/finance/migration/preview").get_json()["data"]
    assert len(preview["issues"])==1
    with pytest.raises(FinanceError,match="اختلاف"):
        f["call"]("migration.apply",{"preview_hash":preview["hash"],"reason":"اختبار الحماية"})
    assert invoice.paid_amount==200


def test_shared_cash_opening_counts_the_existing_pool_once(finance):
    from models.treasury_account import TreasuryAccount
    from models.account_transaction import AccountTransaction
    from modules.finance import ledger
    f=finance
    other=TreasuryAccount(name="صندوق إضافي",account_type="cash",branch_id=f["branch"].id,is_active=True)
    f["db"].session.add(other);f["db"].session.flush()
    f["db"].session.add(AccountTransaction(type="deposit",amount=1_000_000,treasury_account_id=other.id,branch_id=f["branch"].id))
    f["db"].session.commit()
    preview=f["get"]("/api/finance/migration/preview").get_json()["data"]
    cash_rows=[r for r in preview["rows"] if r["key"].startswith("treasury:") and r["target"]]
    assert len(cash_rows)==1 and cash_rows[0]["target"]==21_000_000
    f["call"]("migration.apply",{"preview_hash":preview["hash"],"reason":"صندوق مشترك"})
    assert ledger.treasury_gl(other).id==ledger.treasury_gl(f["cash"]).id
    assert ledger.treasury_gl(other).balance==21_000_000
    assert len([a for a in f["get"]("/api/finance/meta").get_json()["data"]["accounts"] if a["type"]=="cash"])==1


def test_draft_edit_preserves_identity_and_has_no_cash_effect(finance):
    from modules.finance.models import FinanceVoucher,FinanceJournalLink
    from modules.finance.common import FinanceError
    f=finance
    original=f["call"]("voucher.create",{"category":"expense","amount":200000,"branch_id":f["branch"].id,
        "treasury_account_id":f["cash"].id,"party_name":"مسودة كهرباء"})
    edited=f["call"]("voucher.edit",{"id":original["id"],"version":original["version"],"amount":210000})
    assert edited["id"]==original["id"] and edited["version"]==2
    assert FinanceVoucher.query.count()==1 and FinanceJournalLink.query.count()==0 and balance(f)==20_000_000
    posted=f["call"]("voucher.approve",{"id":edited["id"],"version":edited["version"]})
    assert balance(f)==19_790_000
    with pytest.raises(FinanceError):
        f["call"]("voucher.edit",{"id":posted["id"],"version":posted["version"],"amount":100000})


def test_current_debt_aging_installment_and_employee_reports_print(finance):
    from datetime import datetime
    from models.customer import Customer
    from models.invoice import Invoice
    from models.supplier import Supplier
    f=finance
    c=Customer(name="دين قديم",phone="0703",branch_id=f["branch"].id)
    s=Supplier(name="دين مورد قديم",opening_balance=2000000,total_debt=2000000,total_paid=750000,branch_id=f["branch"].id,
        created_at=datetime.now()-timedelta(days=91))
    f["db"].session.add_all([c,s]);f["db"].session.flush()
    f["db"].session.add(Invoice(customer_id=c.id,customer_name=c.name,total=400000,paid_amount=150000,status="تم التوصيل",
        branch_id=f["branch"].id,created_at=datetime.now()-timedelta(days=45)))
    f["db"].session.commit()
    customer=f["get"]("/api/finance/reports/customer-aging").get_json()["data"]
    supplier=f["get"]("/api/finance/reports/supplier-aging").get_json()["data"]
    assert customer["total"]==250000 and customer["rows"][0]["status"]=="31–60"
    assert supplier["total"]==1250000 and supplier["rows"][0]["status"]=="90+"
    loan=f["call"]("loan.create",{"direction":"borrowed","party_name":"أقساط تقرير","principal":6000000,"instalments":12,
        "first_due":date.today().isoformat(),"branch_id":f["branch"].id,"treasury_account_id":f["cash"].id})
    f["call"]("loan.fund",{"id":loan["id"],"version":loan["version"]})
    assert f["get"]("/api/finance/reports/instalments").get_json()["data"]["total"]==6000000
    assert f["get"]("/api/finance/reports/employee-advances").get_json()["data"]["rows"]==[]
    for report in ("customer-aging","supplier-aging","instalments","employee-advances","reconciliation-differences"):
        assert "@media print" in f["get"](f"/accounts/finance/reports/{report}/print")


def test_real_purchase_split_payment_posts_each_account_without_duplicate_cash(finance):
    from flask import session
    from models.supplier import Supplier
    from models.product import Product
    from modules.finance import ledger
    from routes.purchases import _create_purchase_from_payload
    f=finance
    supplier=Supplier(name="شراء متعدد الحسابات",branch_id=f["branch"].id,total_debt=0,total_paid=0)
    product=Product(name="جهاز مشتريات",buy_price=1000000,sale_price=1200000,quantity=0,branch_id=f["branch"].id)
    f["db"].session.add_all([supplier,product]);f["db"].session.commit()
    voucher(f,"account_transfer",1000000,target_account_id=f["bank"].id)
    preview=f["get"]("/api/finance/migration/preview").get_json()["data"]
    f["call"]("migration.apply",{"preview_hash":preview["hash"],"reason":"اختبار تكامل الشراء"})
    with f["app"].test_request_context("/purchases",method="POST"):
        session["user_id"]=f["admin"].id
        purchase,error=_create_purchase_from_payload({"supplier_id":supplier.id,"_validated_branch_id":f["branch"].id,
            "invoice_no":"FIN-SPLIT","status":"confirmed","purchase_mode":"mixed",
            "items":[{"product_id":product.id,"quantity":1,"unit_cost_before_discount":1000000}],
            "payments":[{"amount":100000,"payment_method":"cash","treasury_account_id":f["cash"].id},
                {"amount":250000,"payment_method":"bank","treasury_account_id":f["bank"].id}]},[],employee_id=f["admin"].id)
        assert not error,error
        assert purchase and purchase.paid_total==350000
    assert balance(f)==18900000 and balance(f,"bank")==750000
    assert ledger.treasury_gl(f["cash"]).balance==balance(f) and ledger.treasury_gl(f["bank"]).balance==balance(f,"bank")
    assert ledger.account("inventory").balance==1000000 and ledger.account("payable").balance==650000
    assert ledger.account("expense").balance==0 and product.quantity==1
    bank_stats=f["get"](f"/api/finance/vouchers?treasury_account_id={f['bank'].id}").get_json()["data"]["stats"]
    assert bank_stats["paid"]==250000


def test_legacy_split_invoice_cash_reports_and_return_match_each_account(finance):
    from flask import session
    from models.customer import Customer
    from models.invoice import Invoice
    from models.invoice_payment_ledger import InvoicePaymentLedger
    from modules.finance import ledger
    from utils.payment_ledger import append_payment_ledger_delta
    f=finance
    voucher(f,"account_transfer",1000000,target_account_id=f["bank"].id)
    preview=f["get"]("/api/finance/migration/preview").get_json()["data"]
    f["call"]("migration.apply",{"preview_hash":preview["hash"],"reason":"اختبار تكامل البيع"})
    with f["app"].test_request_context("/pos",method="POST"):
        session["user_id"]=f["admin"].id
        customer=Customer(name="دفعة مقسمة",phone="0740",branch_id=f["branch"].id)
        f["db"].session.add(customer);f["db"].session.flush()
        invoice=Invoice(customer_id=customer.id,customer_name=customer.name,branch_id=f["branch"].id,
            total=1000,paid_amount=500,status="تم التوصيل",stock_is_deducted=False)
        f["db"].session.add(invoice);f["db"].session.flush()
        f["db"].session.add_all([InvoicePaymentLedger(invoice_id=invoice.id,amount_delta=200,treasury_account_id=f["cash"].id,payment_method="cash",branch_id=f["branch"].id),
            InvoicePaymentLedger(invoice_id=invoice.id,amount_delta=300,treasury_account_id=f["bank"].id,payment_method="bank",branch_id=f["branch"].id)])
        f["db"].session.commit();f["db"].session.commit()
        assert ledger.account("revenue").balance==1000 and ledger.account("receivable").balance==500
        assert ledger.treasury_gl(f["cash"]).balance==balance(f)==19000200
        assert ledger.treasury_gl(f["bank"]).balance==balance(f,"bank")==1000300
        invoice.status="مرتجع";invoice.paid_amount=0
        append_payment_ledger_delta(invoice.id,-500,source_module="test_return")
        f["db"].session.commit()
    assert balance(f)==19000000 and balance(f,"bank")==1000000
    assert ledger.account("revenue").balance==0 and ledger.account("receivable").balance==0
    stats=f["get"](f"/api/finance/vouchers?treasury_account_id={f['bank'].id}").get_json()["data"]["stats"]
    assert stats["received"]==stats["paid"]==300


def test_legacy_supplier_account_change_updates_the_same_cash_sources(finance):
    from flask import session
    from models.supplier import Supplier
    from models.supplier_payment import SupplierPayment
    from modules.finance import ledger
    f=finance
    voucher(f,"account_transfer",1000000,target_account_id=f["bank"].id)
    supplier=Supplier(name="تصحيح حساب دفع",total_debt=1000000,total_paid=100000,branch_id=f["branch"].id)
    f["db"].session.add(supplier);f["db"].session.flush()
    payment=SupplierPayment(supplier_id=supplier.id,amount=100000,treasury_account_id=f["cash"].id,
        payment_method="cash",branch_id=f["branch"].id)
    f["db"].session.add(payment);f["db"].session.commit()
    preview=f["get"]("/api/finance/migration/preview").get_json()["data"]
    f["call"]("migration.apply",{"preview_hash":preview["hash"],"reason":"تصحيح مصادر سابقة"})
    with f["app"].test_request_context("/suppliers",method="POST"):
        session["user_id"]=f["admin"].id
        payment.treasury_account_id=f["bank"].id;payment.payment_method="bank"
        f["db"].session.commit()
    assert balance(f)==19000000 and balance(f,"bank")==900000
    assert ledger.treasury_gl(f["cash"]).balance==balance(f)
    assert ledger.treasury_gl(f["bank"]).balance==balance(f,"bank")
    assert ledger.account("payable").balance==900000


def test_supplier_movement_date_filter_uses_iraq_business_day(finance):
    from datetime import datetime
    from flask import session
    from models.supplier import Supplier
    from models.supplier_payment import SupplierPayment
    from modules.receipts.services import movements_feed
    f=finance
    supplier=Supplier(name="قبض منتصف الليل",total_debt=200,total_paid=100,branch_id=f["branch"].id)
    f["db"].session.add(supplier);f["db"].session.flush()
    f["db"].session.add(SupplierPayment(supplier_id=supplier.id,amount=100,treasury_account_id=f["cash"].id,
        branch_id=f["branch"].id,payment_method="cash",created_at=datetime(2026,10,10,22,0)))
    f["db"].session.commit()
    with f["app"].test_request_context("/receipts"):
        session["user_id"]=f["admin"].id
        feed=movements_feed.list_movements({"kind":"supplier_payment","date_from":"2026-10-11","date_to":"2026-10-11"})
    assert feed["total"]==1 and feed["items"][0]["date"]=="2026-10-11"
    assert feed["stats"]["supplier_payment_amount"]==100


def test_automatic_storefront_posting_without_staff_session_is_audited_safely(finance):
    from models.customer import Customer
    from models.invoice import Invoice
    from models.employee import Employee
    from modules.finance import ledger,routes
    from modules.finance.models import FinanceVoucher,FinanceAudit
    from werkzeug.exceptions import Unauthorized
    f=finance
    preview=f["get"]("/api/finance/migration/preview").get_json()["data"]
    f["call"]("migration.apply",{"preview_hash":preview["hash"],"reason":"تكامل المتجر"})
    c=Customer(name="طلب متجر",phone="0750",branch_id=f["branch"].id)
    f["db"].session.add(c);f["db"].session.flush()
    invoice=Invoice(customer_id=c.id,customer_name=c.name,total=400000,paid_amount=0,status="تم الطلب",
        stock_is_deducted=True,branch_id=f["branch"].id)
    f["db"].session.add(invoice);f["db"].session.commit()
    row=FinanceVoucher.query.filter_by(source_type="invoice_auto",source_id=invoice.id).one()
    identity=f["db"].session.get(Employee,row.created_by)
    assert identity.role=="system" and not identity.is_active and row.approved_by==identity.id
    assert FinanceAudit.query.filter_by(source_type="voucher",source_id=row.id,created_by=identity.id).one().device=="FINORA background"
    assert ledger.account("revenue").balance==400000 and balance(f)==20000000
    with f["app"].test_request_context("/api/finance/meta"):
        with pytest.raises(Unauthorized):routes.setup()


def test_existing_receipt_bank_and_cancellation_use_exact_journals_once(finance):
    from flask import session
    from models.customer import Customer
    from models.invoice import Invoice
    from models.treasury_account import TreasuryAccount
    from models.receipt import Receipt
    from modules.receipts.services import receipt_service
    from modules.finance import ledger
    from modules.finance.models import FinanceVoucher,FinanceJournalLink
    from utils.treasury_calculations import calculate_treasury_balance
    f=finance
    customer=Customer(name="سند قبض سابق",phone="0751",branch_id=f["branch"].id)
    bank=TreasuryAccount(name="المصرف الثاني",account_type="bank",is_active=True,branch_id=f["branch"].id)
    f["db"].session.add_all([customer,bank]);f["db"].session.flush()
    invoice=Invoice(customer_id=customer.id,customer_name=customer.name,total=1000,paid_amount=0,status="تم التوصيل",branch_id=f["branch"].id)
    f["db"].session.add(invoice);f["db"].session.commit()
    preview=f["get"]("/api/finance/migration/preview").get_json()["data"]
    f["call"]("migration.apply",{"preview_hash":preview["hash"],"reason":"تكامل سند القبض"})
    with f["app"].test_request_context("/receipts",method="POST"):
        session["user_id"]=f["admin"].id
        receipt=receipt_service.create_receipt(None,{"source_type":"customer","source_id":customer.id,"amount":300,
            "payment_method":"bank","treasury_account_id":bank.id,"allocation_method":"oldest_first",
            "idempotency_key":uuid4().hex,"receipt_date":date.today().isoformat()},employee_id=f["admin"].id)
        f["db"].session.commit()
        assert invoice.paid_amount==300 and ledger.account("receivable").balance==700
        assert ledger.treasury_gl(bank).balance==calculate_treasury_balance(bank.id)==300
        receipt_service.cancel_receipt(receipt["id"],reason="تصحيح اختبار",employee_id=f["admin"].id)
        f["db"].session.commit()
        original=f["db"].session.get(Receipt,receipt["id"])
        correction=FinanceVoucher.query.filter_by(source_type="invoice_auto",source_id=invoice.id,kind="payment").one()
        assert FinanceJournalLink.query.filter_by(voucher_id=correction.id).one().journal_entry_id==original.reverse_journal_entry_id
        assert ledger.account("receivable").balance==1000 and ledger.treasury_gl(bank).balance==calculate_treasury_balance(bank.id)==0


def test_posted_source_protection_cannot_be_removed_by_editing_its_marker(finance):
    from flask import session
    from models.expense import Expense
    from modules.finance.common import FinanceError
    from modules.finance import ledger
    f=finance
    row=voucher(f,"expense",200000,party_name="مصروف محمي")
    expense=f["db"].session.get(Expense,row["source_id"])
    with f["app"].test_request_context("/expenses",method="POST"):
        session["user_id"]=f["admin"].id
        expense.note="تغيير علامة المصدر";expense.amount=100000
        with pytest.raises(FinanceError,match="السجل مرتبط"):
            f["db"].session.commit()
        f["db"].session.rollback()
    assert expense.amount==200000 and balance(f)==19800000 and ledger.account("expense").balance==200000


def test_transfer_preserves_total_cash_and_reversal(finance):
    f = finance
    row = voucher(f, "account_transfer", 1_000_000, target_account_id=f["bank"].id)
    assert balance(f) == 19_000_000
    assert balance(f, "bank") == 1_000_000
    assert balance(f) + balance(f, "bank") == 20_000_000
    f["call"]("voucher.reverse", {"id":row["id"], "version":row["version"], "reason":"تصحيح الحساب"})
    assert balance(f) == 20_000_000
    assert balance(f, "bank") == 0


def test_expense_affects_profit_owner_draw_does_not(finance):
    from modules.finance import ledger
    f = finance
    voucher(f, "expense", 200_000, party_name="كهرباء")
    assert ledger.account("expense").balance == 200_000
    voucher(f, "owner_draw", 500_000)
    assert ledger.account("expense").balance == 200_000
    assert balance(f) == 19_300_000


@pytest.mark.parametrize("amount", [0, -1, "0.5", "NaN", True, "Infinity"])
def test_invalid_money_rolls_back_completely(finance, amount):
    from modules.finance.common import FinanceError
    from modules.finance.models import FinanceVoucher, FinanceCommand
    with pytest.raises(FinanceError):
        voucher(finance, "expense", amount, party_name="كهرباء")
    assert FinanceVoucher.query.count() == FinanceCommand.query.count() == 0
    assert balance(finance) == 20_000_000


def test_advance_application_moves_no_cash_and_restores_credit_on_reversal(finance):
    from models.customer import Customer
    from models.invoice import Invoice
    f=finance
    c=Customer(name="رصيد زبون",phone="1",branch_id=f["branch"].id)
    f["db"].session.add(c)
    f["db"].session.flush()
    i=Invoice(customer_id=c.id,customer_name=c.name,total=400_000,paid_amount=0,status="تم التوصيل",branch_id=f["branch"].id)
    f["db"].session.add(i)
    f["db"].session.commit()
    voucher(f,"customer_advance",300_000,party_id=c.id)
    cash_before=balance(f)
    applied=f["call"]("credit.apply",{"party_type":"customer","party_id":c.id,"amount":150_000,"branch_id":f["branch"].id})
    assert i.paid_amount==150_000
    assert balance(f)==cash_before
    credit=f["get"](f"/api/finance/parties/customer/{c.id}").get_json()["data"]["credit"]
    assert credit==150_000
    f["call"]("voucher.reverse",{"id":applied["id"],"version":applied["version"],"reason":"إلغاء التطبيق"})
    assert balance(f)==cash_before
    assert i.paid_amount==0
    assert f["get"](f"/api/finance/parties/customer/{c.id}").get_json()["data"]["credit"]==300_000


def test_loan_net_funding_and_preaccrued_interest_are_not_expensed_twice(finance):
    from modules.finance import ledger
    f=finance
    loan=f["call"]("loan.create",{"direction":"borrowed","party_name":"قرض برسوم","principal":1_000_000,"interest":100_000,"upfront_fee":25_000,"instalments":2,"first_due":date.today().isoformat(),"treasury_account_id":f["cash"].id,"branch_id":f["branch"].id})
    loan=f["call"]("loan.fund",{"id":loan["id"],"version":loan["version"]})
    assert balance(f)==20_975_000
    assert ledger.account("interest_expense").balance==25_000
    loan=f["call"]("loan.accrue",{"id":loan["id"],"version":loan["version"],"amount":50_000,"notes":"فائدة مستحقة"})
    assert ledger.account("interest_expense").balance==75_000
    loan=f["call"]("loan.pay",{"id":loan["id"],"version":loan["version"],"amount":550_000,"principal":500_000,"interest":50_000,"fees":0})
    assert ledger.account("interest_expense").balance==75_000
    assert ledger.account("interest_payable").balance==0
    assert loan["remaining_principal"]==500_000


def test_migration_is_reviewed_once_and_existing_expenses_post_atomically(finance):
    from modules.finance.common import FinanceError
    from modules.finance import ledger
    from models.expense import Expense
    from flask import session,g
    f=finance
    f["call"]("settings.save",{"policy":{}})
    preview=f["get"]("/api/finance/migration/preview").get_json()["data"]
    assert not preview["complete"]
    with pytest.raises(FinanceError):
        f["call"]("migration.apply",{"preview_hash":"stale","reason":"اختبار"})
    f["call"]("migration.apply",{"preview_hash":preview["hash"],"reason":"تمت المراجعة"})
    assert ledger.treasury_gl(f["cash"]).balance==20_000_000
    with pytest.raises(FinanceError):
        f["call"]("migration.apply",{"preview_hash":preview["hash"],"reason":"تكرار"})
    with f["app"].test_request_context("/expenses"):
        session["user_id"]=f["admin"].id
        row=Expense(title="مصروف قديم المسار",amount=200_000,branch_id=f["branch"].id,treasury_account_id=f["cash"].id,cash_posted=True,expense_date=date.today())
        f["db"].session.add(row)
        f["db"].session.commit()
        assert ledger.account("expense").balance==200_000
        f["db"].session.commit()
        assert ledger.account("expense").balance==200_000


def test_print_views_preserve_draft_and_exact_schedule(finance):
    f=finance
    row=f["call"]("voucher.create",{"category":"expense","amount":200_000,"party_name":"كهرباء","treasury_account_id":f["cash"].id,"branch_id":f["branch"].id})
    html=f["get"](f"/accounts/finance/vouchers/{row['id']}/print")
    artifacts=Path(__file__).parent / "_artifacts"
    artifacts.mkdir(parents=True,exist_ok=True)
    (artifacts/"finance-voucher.html").write_text(html,encoding="utf-8")
    assert "200,000" in html and "لا يثبت حركة نقدية" in html
    assert "@media print" in html and "display:none!important" in html
    loan=f["call"]("loan.create",{"direction":"borrowed","party_name":"عقد طباعة","principal":6_000_000,"instalments":12,"first_due":date.today().isoformat(),"treasury_account_id":f["cash"].id,"branch_id":f["branch"].id})
    html=f["get"](f"/accounts/finance/loans/{loan['id']}/print")
    (artifacts/"finance-loan.html").write_text(html,encoding="utf-8")
    (artifacts/"finance-report.html").write_text(f["get"]("/accounts/finance/reports/trial-balance/print"),encoding="utf-8")
    assert html.count("500,000")==24
    assert "جدول الأقساط" in html


def test_employee_advance_is_deducted_by_real_payroll_without_cash(finance):
    import json
    from flask import session,g
    from modules.hr.models import HRPerson, HRContract, HRAdvance, HRAdvanceRepayment
    from modules.hr import finance as hr
    from modules.finance import ledger
    f=finance
    payroll_date=(date.today().replace(day=1)-timedelta(days=1)).replace(day=1)
    f["call"]("settings.save",{"policy":{}})
    p=HRPerson(name="موظف سلفة",code="FIN-HR",branch_id=f["branch"].id,joined_on=date(2026,1,1),salary=650_000,status="active")
    f["db"].session.add(p)
    f["db"].session.flush()
    f["db"].session.add(HRContract(person_id=p.id,effective_from=date(2026,1,1),created_by=f["admin"].id,terms=json.dumps({"salary":650_000,"salary_type":"monthly"})))
    f["db"].session.commit()
    loan=f["call"]("loan.create",{"direction":"employee","party_name":p.name,"person_id":p.id,"principal":500_000,"instalments":5,"first_due":payroll_date.isoformat(),"starts_on":payroll_date.isoformat(),"treasury_account_id":f["cash"].id,"branch_id":f["branch"].id})
    loan=f["call"]("loan.fund",{"id":loan["id"],"version":loan["version"]})
    assert balance(f)==19_500_000
    with f["app"].test_request_context("/hr/api/commands"):
        session.update(user_id=f["admin"].id,role="admin")
        g.branch=f["branch"]
        g.branch_scope_ready=True
        g.view_all_branches=True
        prepared=hr.prepare_payroll({"branch_id":f["branch"].id,"month":payroll_date.strftime("%Y-%m")})
        hr.decide_payroll({"run_id":prepared["id"],"version":1,"status":"reviewed"})
        hr.decide_payroll({"run_id":prepared["id"],"version":2,"status":"approved"})
        f["db"].session.commit()
    assert balance(f)==19_500_000
    assert HRAdvance.query.one().repaid==100_000
    assert HRAdvanceRepayment.query.count()==1
    current=f["get"](f"/api/finance/loans/{loan['id']}").get_json()["data"]
    assert current["remaining_principal"]==400_000
    assert current["salary_deductions"][0]["amount"]==100_000
    assert ledger.account("employee_advance").balance==400_000


def test_migrated_invoice_collection_posts_sale_and_cash_only_once(finance):
    from models.customer import Customer
    from models.invoice import Invoice
    from modules.finance import ledger
    f=finance
    f["call"]("settings.save",{"policy":{}})
    preview=f["get"]("/api/finance/migration/preview").get_json()["data"]
    f["call"]("migration.apply",{"preview_hash":preview["hash"],"reason":"تهيئة الاختبار"})
    from flask import session
    with f["app"].test_request_context("/pos"):
        session["user_id"]=f["admin"].id
        c=Customer(name="بيع مرتبط",phone="2",branch_id=f["branch"].id)
        f["db"].session.add(c)
        f["db"].session.flush()
        i=Invoice(customer_id=c.id,customer_name=c.name,total=400_000,paid_amount=0,status="تم الطلب",stock_is_deducted=False,branch_id=f["branch"].id)
        f["db"].session.add(i)
        f["db"].session.commit()
    voucher(f,"customer_payment",150_000,party_id=c.id)
    assert ledger.account("revenue").balance==400_000
    assert ledger.account("receivable").balance==250_000
    assert ledger.treasury_gl(f["cash"]).balance==20_150_000
    assert balance(f)==20_150_000


def test_stale_version_double_post_closed_period_and_insufficient_funds(finance):
    from modules.finance.common import FinanceError
    from utils.financial_period_guard import PeriodClosedError
    from utils.treasury_calculations import InsufficientTreasuryBalance
    f=finance
    with pytest.raises(InsufficientTreasuryBalance):
        voucher(f,"expense",21_000_000,party_name="أكبر من الرصيد")
    row=voucher(f,"expense",10_000,party_name="مصروف")
    with pytest.raises(FinanceError):
        f["call"]("voucher.approve",{"id":row["id"],"version":row["version"]})
    with pytest.raises(FinanceError):
        f["call"]("voucher.reverse",{"id":row["id"],"version":1,"reason":"نسخة قديمة"})
    f["call"]("period.close",{"year":date.today().year,"month":date.today().month,"reason":"إقفال اختبار"})
    with pytest.raises(PeriodClosedError):
        voucher(f,"expense",5_000,party_name="فترة مقفلة")
    assert balance(f)==19_990_000


def test_supplier_payment_reversal_and_source_edit_guard(finance):
    from models.supplier import Supplier
    from models.expense import Expense
    from modules.finance.common import FinanceError
    from flask import session
    f=finance
    supplier=Supplier(name="مورد عكس",branch_id=f["branch"].id,total_debt=2_000_000,total_paid=0,opening_balance=2_000_000)
    f["db"].session.add(supplier)
    f["db"].session.commit()
    row=voucher(f,"supplier_payment",750_000,party_id=supplier.id)
    f["call"]("voucher.reverse",{"id":row["id"],"version":row["version"],"reason":"تصحيح الدفع"})
    assert supplier.remaining==2_000_000
    assert balance(f)==20_000_000
    voucher(f,"expense",200_000,party_name="إثبات مصروف")
    with f["app"].test_request_context("/expenses/edit"):
        session["user_id"]=f["admin"].id
        expense=Expense.query.filter(Expense.amount>0).one()
        expense.amount=300_000
        with pytest.raises(FinanceError):
            f["db"].session.commit()
        f["db"].session.rollback()
    assert Expense.query.one().amount==200_000


def test_reconciliation_never_adjusts_balance_and_requires_exact_statement(finance):
    from modules.finance.common import FinanceError
    f=finance
    voucher(f,"account_transfer",1_000_000,target_account_id=f["bank"].id)
    values={"treasury_account_id":f["bank"].id,"starts_on":date.today().isoformat(),"ends_on":date.today().isoformat(),"opening_balance":0,"closing_balance":1_000_000,"lines":[{"date":date.today().isoformat(),"amount":1_000_000,"reference":"تحويل داخلي"}]}
    f["call"]("reconciliation.create",values)
    data=f["get"]("/api/finance/reconciliations").get_json()["data"]["items"][0]
    assert data["status"]=="matched" and data["difference"]==0
    assert balance(f,"bank")==1_000_000
    with pytest.raises(FinanceError):
        f["call"]("reconciliation.create",{**values,"closing_balance":999_000})
    assert balance(f,"bank")==1_000_000


def test_finance_permissions_cannot_be_bypassed(finance):
    from models.role import Role, Permission
    from modules.finance.common import FinanceError
    f=finance
    f["call"]("settings.save",{"policy":{}})
    role=Role(name="Finance read only")
    role.permissions=Permission.query.filter_by(name="finance.view").all()
    f["admin"].role="cashier"
    f["admin"].roles=[role]
    f["db"].session.add(role)
    f["db"].session.commit()
    assert f["get"]("/api/finance/vouchers").get_json()["success"]
    with pytest.raises(FinanceError):
        voucher(f,"expense",200_000,party_name="ممنوع")
    with pytest.raises(FinanceError):
        f["get"]("/api/finance/journal")
    with pytest.raises(FinanceError):
        f["get"]("/api/finance/settings")
    assert balance(f)==20_000_000


def test_web_shell_uses_finora_patterns(finance):
    html=finance["get"]("/accounts/finance")
    assert 'finance.css' in html and 'finance.js' in html
    assert 'القبض والصرف' in html and 'السلف والقروض' in html
    assert 'finance-drawer' in html and 'finance-help' in html


def test_expense_accrual_partial_settlement_refund_and_dependencies(finance):
    from modules.finance.common import FinanceError
    from modules.finance.models import FinanceVoucher
    f=finance
    accrued=voucher(f,"expense_accrual",200000,party_name="كهرباء مستحقة")
    assert balance(f)==20000000
    assert f["get"]("/api/finance/reports/profit-loss").get_json()["data"]["profit"]==-200000
    source=f["db"].session.get(FinanceVoucher,accrued["id"]).source_id
    with pytest.raises(FinanceError):
        voucher(f,"expense_refund",10000,party_name="استرداد",expense_id=source)
    paid=voucher(f,"accrued_expense",75000,party_name="تسديد الكهرباء",expense_id=source)
    assert balance(f)==19925000
    assert f["get"]("/api/finance/reports/profit-loss").get_json()["data"]["profit"]==-200000
    with pytest.raises(FinanceError):
        f["call"]("voucher.reverse",{"id":accrued["id"],"version":accrued["version"],"reason":"تابع"})
    refund=voucher(f,"expense_refund",25000,party_name="استرداد الكهرباء",expense_id=source)
    assert balance(f)==19950000
    with pytest.raises(FinanceError):
        f["call"]("voucher.reverse",{"id":paid["id"],"version":paid["version"],"reason":"تابع"})
    for row in (refund,paid,accrued):
        f["call"]("voucher.reverse",{"id":row["id"],"version":row["version"],"reason":"تصحيح"})
    assert balance(f)==20000000
    assert f["get"]("/api/finance/reports/profit-loss").get_json()["data"]["profit"]==0


def test_finance_transfer_cash_rows_cannot_be_deleted_from_legacy_paths(finance):
    from models.account_transaction import AccountTransaction
    from models.treasury_transfer import TreasuryTransfer
    from modules.finance.models import FinanceVoucher
    from modules.finance.common import FinanceError
    f=finance
    v=voucher(f,"account_transfer",1000000,target_account_id=f["bank"].id)
    transfer_id=f["db"].session.get(FinanceVoucher,v["id"]).source_id
    for model,row_id in [(TreasuryTransfer,transfer_id),(AccountTransaction,AccountTransaction.query.filter_by(treasury_transfer_id=transfer_id).first().id)]:
        f["db"].session.delete(f["db"].session.get(model,row_id))
        with pytest.raises(FinanceError):
            f["db"].session.commit()
        f["db"].session.rollback()
    assert balance(f)==19000000
    assert balance(f,"bank")==1000000


def test_idempotency_payload_change_and_cross_branch_account_are_rejected(finance):
    from modules.finance.common import FinanceError
    from models.branch import Branch
    from models.treasury_account import TreasuryAccount
    f=finance
    key=uuid4().hex
    data={"category":"expense","party_name":"مصروف","amount":200000,"treasury_account_id":f["cash"].id,"branch_id":f["branch"].id,"intent":"post"}
    f["call"]("voucher.create",data,key)
    with pytest.raises(FinanceError):
        f["call"]("voucher.create",{**data,"amount":300000},key)
    assert balance(f)==19800000
    other=Branch(code="OTHER",name="فرع آخر",is_active=True)
    f["db"].session.add(other);f["db"].session.flush()
    account=TreasuryAccount(name="صندوق آخر",branch_id=other.id,account_type="cash",is_active=True)
    f["db"].session.add(account);f["db"].session.commit()
    with pytest.raises(FinanceError):
        f["call"]("voucher.create",{**data,"treasury_account_id":account.id})
    assert balance(f)==19800000


def test_separate_approval_creates_pending_without_cash_effect(finance):
    from modules.finance.common import FinanceError
    from modules.finance.models import FinanceVoucher
    from models.employee import Employee
    from flask import session
    from modules.finance import routes
    f=finance
    f["call"]("settings.save",{"policy":{"separate_approval":True,"sensitive_threshold":1000000}})
    loan=f["call"]("loan.create",{"direction":"borrowed","party_name":"شركة تمويل","principal":6000000,"instalments":12,"first_due":date.today().isoformat(),"treasury_account_id":f["cash"].id,"branch_id":f["branch"].id})
    requested=f["call"]("loan.fund",{"id":loan["id"],"version":loan["version"]})
    pending=requested["pending_vouchers"][0]
    assert balance(f)==20000000
    v=f["db"].session.get(FinanceVoucher,pending["id"])
    with pytest.raises(FinanceError):
        f["call"]("voucher.approve",{"id":v.id,"version":v.version})
    approver=Employee(name="Approver",username=uuid4().hex,password="test",role="admin",is_active=True,branch_id=f["branch"].id)
    f["db"].session.add(approver);f["db"].session.commit()
    with f["app"].test_request_context("/api/finance/commands",method="POST",json={"operation":"voucher.approve","idempotency_key":uuid4().hex,"id":v.id,"version":v.version}):
        session.update(user_id=approver.id,employee_id=approver.id)
        routes.setup();assert routes.commands().get_json()["data"]["status"]=="posted"
    assert balance(f)==26000000


def test_legacy_payroll_source_posts_once_and_keeps_original_cash_source(finance):
    from flask import session
    from modules.finance import ledger
    from models.employee_payment import EmployeePayment
    from models.expense import Expense
    f=finance
    f["call"]("settings.save",{"policy":{}})
    preview=f["get"]("/api/finance/migration/preview").get_json()["data"]
    f["call"]("migration.apply",{"preview_hash":preview["hash"],"reason":"مراجعة"})
    with f["app"].test_request_context("/employees"):
        session.update(user_id=f["admin"].id,employee_id=f["admin"].id)
        from utils.payroll_service import pay_salary
        f["admin"].salary=200000
        f["admin"].pay_type="monthly"
        f["db"].session.commit()
        result=pay_salary(f["admin"],treasury_account_id=f["cash"].id,settled_by=f["admin"].id,manual=True)
        assert result["ok"],result
        assert ledger.account("salary_expense").balance==200000
        assert ledger.treasury_gl(f["cash"]).balance==19800000
        f["db"].session.commit()
        assert ledger.account("salary_expense").balance==200000
        assert balance(f)==19800000


def test_parallel_retry_and_spending_cannot_duplicate_or_overdraw(finance):
    from concurrent.futures import ThreadPoolExecutor
    from flask import session,g
    from modules.finance import routes
    from modules.finance.common import FinanceError
    from utils.treasury_calculations import InsufficientTreasuryBalance
    f=finance;branch_id=f["branch"].id;cash_id=f["cash"].id;actor_id=f["admin"].id;key=uuid4().hex
    def request(key,amount):
        with f["app"].test_request_context("/api/finance/commands",method="POST",json={"operation":"voucher.create","idempotency_key":key,"category":"expense","party_name":"صرف متزامن","amount":amount,"treasury_account_id":cash_id,"branch_id":branch_id,"intent":"post"}):
            g.tenant=f["tenant"];g.view_all_branches=True;g.branch_scope_ready=True
            session.update(user_id=actor_id,employee_id=actor_id)
            try:
                routes.setup();return routes.commands().get_json()["data"]["id"]
            except (FinanceError,InsufficientTreasuryBalance):
                f["db"].session.rollback();return None
            finally:
                f["db"].session.remove()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:request(key,200000),range(2)))
    assert results[0] and results[0]==results[1]
    assert balance(f)==19800000
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:request(uuid4().hex,12000000),range(2)))
    assert sum(r is not None for r in results)==1
    assert balance(f)==7800000


def test_print_reports_and_full_filtered_export(finance):
    f=finance
    for i in range(27):
        voucher(f,"expense",1000,party_name=f"مصروف {i}")
    exported=f["get"]("/api/finance/vouchers/export/content?page=2&page_size=25").get_json()["data"]
    assert len(exported["content"].splitlines())==28
    for report in ("trial-balance","profit-loss","balance-sheet","cash-flow"):
        html=f["get"](f"/accounts/finance/reports/{report}/print")
        assert "FINORA" in html and "@media print" in html
    sheet=f["get"]("/api/finance/reports/balance-sheet?date_from=2200-01-01").get_json()["data"]
    assert sheet["profit"]==-27000


def test_failed_post_rolls_back_source_cash_journal_and_retry_key(finance,monkeypatch):
    from modules.finance import ledger
    from modules.finance.models import FinanceCommand,FinanceVoucher
    from models.expense import Expense
    f=finance
    f["get"]("/api/finance/meta")
    original=ledger.post
    def fail(*args,**kwargs):raise RuntimeError("forced posting failure")
    monkeypatch.setattr(ledger,"post",fail)
    key=uuid4().hex
    data={"category":"expense","party_name":"فشل اختباري","amount":200000,"treasury_account_id":f["cash"].id,"branch_id":f["branch"].id,"intent":"post"}
    with pytest.raises(RuntimeError):f["call"]("voucher.create",data,key)
    assert balance(f)==20000000
    assert FinanceVoucher.query.count()==0 and Expense.query.count()==0
    assert f["db"].session.get(FinanceCommand,key) is None
    monkeypatch.setattr(ledger,"post",original)
    assert f["call"]("voucher.create",data,key)["status"]=="posted"
    assert balance(f)==19800000


def test_fixed_asset_uses_existing_category_and_reversal_restores_cash(finance):
    from models.fixed_asset import FixedAsset
    f=finance
    categories=f["get"]("/api/finance/meta").get_json()["data"]["asset_categories"]
    row=voucher(f,"fixed_asset",1200000,party_name="أصل",asset_name="حاسبة الفرع",asset_category_id=categories[0]["id"],asset_months=36)
    asset=FixedAsset.query.filter_by(name="حاسبة الفرع").one()
    assert asset.status=="active" and asset.acquisition_journal_entry_id
    assert f["get"]("/api/finance/reports/profit-loss").get_json()["data"]["profit"]==0
    f["call"]("voucher.reverse",{"id":row["id"],"version":row["version"],"reason":"إلغاء شراء الأصل"})
    assert asset.status=="draft" and not asset.acquisition_journal_entry_id
    assert balance(f)==20000000


def test_schedule_rounding_partial_early_pay_reschedule_and_history(finance):
    from modules.finance.loans import monthly_date
    f=finance
    assert monthly_date(date(2026,1,31),1)==date(2026,2,28)
    row=f["call"]("loan.create",{"direction":"borrowed","party_name":"عقد دقيق","principal":1000001,"instalments":3,"first_due":date.today().isoformat(),"treasury_account_id":f["cash"].id,"branch_id":f["branch"].id})
    assert sum(i["principal"] for i in row["schedule"])==1000001
    row=f["call"]("loan.fund",{"id":row["id"],"version":row["version"]})
    row=f["call"]("loan.pay",{"id":row["id"],"version":row["version"],"amount":100000})
    assert row["schedule"][0]["status"]=="partial" and row["remaining_principal"]==900001
    row=f["call"]("loan.reschedule",{"id":row["id"],"version":row["version"],"instalments":2,"first_due":date.today().isoformat(),"reason":"تعديل اتفاق الاستحقاق"})
    assert row["schedule_version"]==2 and len(row["schedule_history"][0]["rows"])==3
    assert sum(i["principal"] for i in row["schedule"])==900001
    row=f["call"]("loan.pay",{"id":row["id"],"version":row["version"],"amount":900001,"principal":900001})
    assert row["status"]=="closed" and row["remaining_total"]==0
    assert balance(f)==20000000


def test_private_attachments_validate_content_and_authorize_owner_record(finance):
    from io import BytesIO
    from flask import session
    from modules.finance import routes
    from modules.finance.models import FinanceAttachment
    from modules.finance.common import FinanceError
    f=finance
    row=f["call"]("voucher.create",{"category":"expense","party_name":"مرفق خاص","amount":1000,"treasury_account_id":f["cash"].id,"branch_id":f["branch"].id})
    for content,valid in [(b"<script>invalid</script>",False),(b"%PDF-1.4\n%%EOF",True)]:
        with f["app"].test_request_context("/api/finance/attachments/voucher/1",method="POST",data={"file":(BytesIO(content),"proof.pdf")}):
            session.update(user_id=f["admin"].id,employee_id=f["admin"].id)
            routes.setup()
            if not valid:
                with pytest.raises(FinanceError):routes.upload("voucher",row["id"])
            else:
                data=routes.upload("voucher",row["id"]).get_json()["data"]
    item=f["db"].session.get(FinanceAttachment,data["id"])
    assert f["get"](f"/api/finance/attachments/{item.id}/content").get_json()["data"]["mime"]=="application/pdf"
    with f["app"].test_request_context("/api/finance/attachments/1"):
        session.update(user_id=f["admin"].id,employee_id=f["admin"].id)
        root=routes.attachment_root().resolve();file=(root/item.storage_key).resolve()
        assert root in file.parents
        file.unlink(missing_ok=True)
