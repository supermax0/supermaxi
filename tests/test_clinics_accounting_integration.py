"""End-to-end accounting contract for the Clinics subledger."""
from datetime import date, datetime

import pytest
from flask import Flask

from extensions import db


@pytest.fixture()
def clinic_accounting_db():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SECRET_KEY="clinic-accounting-test",
    )
    db.init_app(app)
    import models  # noqa: F401
    from models.delivery_agent import DeliveryAgent  # noqa: F401
    from modules.clinics.models import CLINIC_MODELS  # noqa: F401
    from utils.accounting_logic import _INITIALIZED_ACCOUNT_BINDS
    with app.app_context():
        _INITIALIZED_ACCOUNT_BINDS.clear()
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        _INITIALIZED_ACCOUNT_BINDS.clear()


def _patient(tenant_id=1):
    from modules.clinics.models import ClinicPatient
    row = ClinicPatient(tenant_id=tenant_id, file_number=f"P-{tenant_id}", full_name=f"Patient {tenant_id}")
    db.session.add(row)
    db.session.flush()
    return row


def _invoice(tenant_id=1, total=100_000):
    from modules.clinics.models import ClinicInvoice
    patient = _patient(tenant_id)
    row = ClinicInvoice(
        tenant_id=tenant_id,
        patient_id=patient.id,
        invoice_number=f"CI-{tenant_id}-1",
        invoice_date=date(2026, 9, 1),
        subtotal=total,
        total=total,
        balance=total,
        paid=0,
        status="open",
    )
    db.session.add(row)
    db.session.flush()
    return row


def _assert_entry(entry, debit, credit, amount):
    assert entry.debit_account.code == debit
    assert entry.credit_account.code == credit
    assert entry.amount == amount
    assert entry.amount > 0  # each simplified engine row is intrinsically balanced


def test_invoice_posts_ar_to_medical_revenue_and_is_idempotent(clinic_accounting_db):
    from models.journal_entry import JournalEntry
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    from modules.clinics.models import AccountingPosting

    invoice = _invoice(total=100_000)
    first = ClinicAccountingPostingService.post_clinic_invoice(invoice.id, 1)
    second = ClinicAccountingPostingService.post_clinic_invoice(invoice.id, 1)

    assert first.id == second.id
    _assert_entry(first, "1201", "4101", 100_000)
    assert JournalEntry.query.count() == 1
    assert AccountingPosting.query.count() == 1


@pytest.mark.parametrize("method,debit", [("cash", "1001"), ("card", "1003"), ("transfer", "1002")])
def test_patient_payment_method_mapping(clinic_accounting_db, method, debit):
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    from modules.clinics.models import ClinicPayment

    invoice = _invoice(total=100_000)
    ClinicAccountingPostingService.post_clinic_invoice(invoice.id, 1)
    payment = ClinicPayment(
        tenant_id=1, invoice_id=invoice.id, patient_id=invoice.patient_id,
        amount=40_000, method=method, paid_at=datetime(2026, 9, 2, 10),
    )
    db.session.add(payment)
    db.session.flush()
    entry = ClinicAccountingPostingService.post_clinic_payment(payment.id, 1)
    _assert_entry(entry, debit, "1201", 40_000)


def test_partial_and_multiple_payments_leave_correct_ar(clinic_accounting_db):
    from modules.clinics.accounting_service import ClinicAccountingPostingService, reconcile_clinic_receivables
    from modules.clinics.service import receive_payment

    invoice = _invoice(total=100_000)
    ClinicAccountingPostingService.post_clinic_invoice(invoice.id, 1)
    receive_payment(1, invoice.id, {"amount": 20_000, "method": "cash"})
    receive_payment(1, invoice.id, {"amount": 30_000, "method": "card"})
    receive_payment(1, invoice.id, {"amount": 50_000, "method": "transfer"})

    assert invoice.balance == 0
    assert invoice.status == "paid"
    assert reconcile_clinic_receivables(1)["gl_balance"] == 0


def test_expense_purchase_supplier_payment_and_doctor_entries(clinic_accounting_db):
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    from modules.clinics.models import ClinicDoctor, ClinicDoctorSettlement, ClinicExpense, ClinicPurchase, ClinicPurchasePayment, ClinicSupplier

    expense = ClinicExpense(tenant_id=1, title="Rent", amount=15_000, expense_date=date(2026, 9, 2), payment_method="cash")
    supplier = ClinicSupplier(tenant_id=1, name="Medical Supplier")
    doctor = ClinicDoctor(tenant_id=1, full_name="Dr Test", commission_pct=40)
    db.session.add_all((expense, supplier, doctor))
    db.session.flush()
    purchase = ClinicPurchase(
        tenant_id=1, supplier_id=supplier.id, purchase_number="PUR-1", purchase_date=date(2026, 9, 3),
        subtotal=80_000, total=80_000, balance=80_000, paid=0, invoice_status="approved",
    )
    settlement = ClinicDoctorSettlement(
        tenant_id=1, doctor_id=doctor.id, period_from=date(2026, 9, 1), period_to=date(2026, 9, 30),
        doctor_share=40_000, clinic_share=60_000, gross_revenue=100_000, balance=40_000, status="open",
    )
    db.session.add_all((purchase, settlement))
    db.session.flush()
    supplier_payment = ClinicPurchasePayment(
        tenant_id=1, purchase_id=purchase.id, payment_number="PP-1", payment_date=date(2026, 9, 4),
        amount=25_000, payment_method="cash",
    )
    db.session.add(supplier_payment)
    db.session.flush()

    _assert_entry(ClinicAccountingPostingService.post_clinic_expense(expense.id, 1), "6201", "1001", 15_000)
    _assert_entry(ClinicAccountingPostingService.post_clinic_purchase(purchase.id, 1), "1101", "2001", 80_000)
    _assert_entry(ClinicAccountingPostingService.post_clinic_purchase_payment(supplier_payment.id, 1), "2001", "1001", 25_000)
    _assert_entry(ClinicAccountingPostingService.post_doctor_settlement(settlement.id, 1), "6101", "2101", 40_000)


def test_payment_refund_is_not_credit_note_and_void_reverses_invoice(clinic_accounting_db):
    from models.journal_entry import JournalEntry
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    from modules.clinics.models import ClinicRefund
    from modules.clinics.service import void_invoice

    invoice = _invoice(total=100_000)
    original = ClinicAccountingPostingService.post_clinic_invoice(invoice.id, 1)
    refund = ClinicRefund(
        tenant_id=1, invoice_id=invoice.id, patient_id=invoice.patient_id,
        amount=20_000, method="cash", refunded_at=datetime(2026, 9, 4),
    )
    db.session.add(refund)
    db.session.flush()
    refund_entry = ClinicAccountingPostingService.post_clinic_refund(refund.id, 1)
    _assert_entry(refund_entry, "1201", "1001", 20_000)

    invoice.paid = 0
    reversed_invoice = void_invoice(1, invoice.id)
    assert reversed_invoice["status"] == "void"
    reversal = JournalEntry.query.filter(JournalEntry.id.notin_((original.id, refund_entry.id))).one()
    _assert_entry(reversal, "4101", "1201", 100_000)


def test_inventory_consumption_uses_weighted_average_cost(clinic_accounting_db):
    from modules.clinics.accounting_service import ClinicAccountingPostingService
    from modules.clinics.models import ClinicInventoryItem, ClinicInventoryMovement

    item = ClinicInventoryItem(tenant_id=1, name="Gloves", average_cost=1_600, current_stock=7)
    db.session.add(item)
    db.session.flush()
    movement = ClinicInventoryMovement(
        tenant_id=1, item_id=item.id, movement_type="out", quantity=3,
        unit_cost=item.average_cost, reason="procedure",
    )
    db.session.add(movement)
    db.session.flush()
    entry = ClinicAccountingPostingService.post_inventory_consumption(movement.id, 1)
    _assert_entry(entry, "5001", "1101", 4_800)


def test_cash_session_formula_excludes_card_and_transfer(clinic_accounting_db):
    from modules.clinics.models import (
        ClinicDoctor, ClinicDoctorSettlement, ClinicExpense, ClinicPayment,
        ClinicPurchase, ClinicPurchasePayment, ClinicRefund, ClinicSupplier,
    )
    from modules.clinics.service_extras import get_clinic_cash_movements

    invoice = _invoice(total=1_000_000)
    opened = datetime(2026, 9, 14, 8)
    patient_id = invoice.patient_id
    supplier = ClinicSupplier(tenant_id=1, name="Supplier")
    doctor = ClinicDoctor(tenant_id=1, full_name="Doctor")
    db.session.add_all((supplier, doctor))
    db.session.flush()
    purchase = ClinicPurchase(
        tenant_id=1, supplier_id=supplier.id, purchase_number="P-1", purchase_date=opened.date(),
        total=100_000, subtotal=100_000, balance=0, paid=100_000,
    )
    db.session.add(purchase)
    db.session.flush()
    db.session.add_all((
        ClinicPayment(tenant_id=1, invoice_id=invoice.id, patient_id=patient_id, amount=500_000, method="cash", paid_at=datetime(2026, 9, 14, 9)),
        ClinicPayment(tenant_id=1, invoice_id=invoice.id, patient_id=patient_id, amount=75_000, method="card", paid_at=datetime(2026, 9, 14, 9)),
        ClinicPayment(tenant_id=1, invoice_id=invoice.id, patient_id=patient_id, amount=25_000, method="transfer", paid_at=datetime(2026, 9, 14, 9)),
        ClinicRefund(tenant_id=1, invoice_id=invoice.id, patient_id=patient_id, amount=50_000, method="cash", refunded_at=datetime(2026, 9, 14, 10)),
        ClinicExpense(tenant_id=1, title="Expense", amount=40_000, payment_method="cash", expense_date=opened.date()),
        ClinicPurchasePayment(tenant_id=1, purchase_id=purchase.id, payment_number="PP-1", amount=100_000, payment_method="cash", payment_date=opened.date()),
        ClinicDoctorSettlement(
            tenant_id=1, doctor_id=doctor.id, period_from=opened.date(), period_to=opened.date(),
            doctor_share=150_000, paid_amount=150_000, balance=0, status="paid", payment_method="cash",
            created_at=datetime(2026, 9, 14, 11),
        ),
    ))
    db.session.flush()
    result = get_clinic_cash_movements(1, opened, datetime(2026, 9, 14, 18), opening_cash=100_000)
    assert result["expected_cash"] == 260_000


def test_accrual_profit_and_tenant_source_isolation(clinic_accounting_db):
    from modules.clinics.accounting_service import ClinicAccountingPostingService, clinic_accounting_report

    invoice = _invoice(tenant_id=1, total=1_000_000)
    entry = ClinicAccountingPostingService.post_clinic_invoice(invoice.id, 1)
    report = clinic_accounting_report(1, date(2026, 9, 1), date(2026, 9, 30))
    assert report["medical_revenue"] == 1_000_000
    assert report["patient_receivables"] == 1_000_000
    assert report["cash_balance"] == 0
    assert report["net_profit"] == 1_000_000
    with pytest.raises(ValueError, match="المستأجر"):
        ClinicAccountingPostingService.post_clinic_invoice(invoice.id, 2)
    assert entry.id is not None


def test_profit_comes_from_gl_not_collections(clinic_accounting_db):
    from modules.clinics.accounting_service import ClinicAccountingPostingService, clinic_accounting_report
    from modules.clinics.models import ClinicDoctor, ClinicDoctorSettlement, ClinicExpense, ClinicInventoryItem, ClinicInventoryMovement

    invoice = _invoice(total=1_000_000)
    doctor = ClinicDoctor(tenant_id=1, full_name="Dr Margin")
    expense = ClinicExpense(tenant_id=1, title="Clinic rent", amount=150_000, payment_method="cash", expense_date=date(2026, 9, 5))
    item = ClinicInventoryItem(tenant_id=1, name="Medical supplies", current_stock=0, average_cost=100_000)
    db.session.add_all((doctor, expense, item))
    db.session.flush()
    settlement = ClinicDoctorSettlement(
        tenant_id=1, doctor_id=doctor.id, period_from=date(2026, 9, 1), period_to=date(2026, 9, 30),
        gross_revenue=1_000_000, doctor_share=300_000, clinic_share=700_000, balance=300_000, status="open",
        created_at=datetime(2026, 9, 5),
    )
    movement = ClinicInventoryMovement(
        tenant_id=1, item_id=item.id, movement_type="out", quantity=1, unit_cost=100_000,
        created_at=datetime(2026, 9, 5),
    )
    db.session.add_all((settlement, movement))
    db.session.flush()
    ClinicAccountingPostingService.post_clinic_invoice(invoice.id, 1)
    ClinicAccountingPostingService.post_doctor_settlement(settlement.id, 1)
    ClinicAccountingPostingService.post_clinic_expense(expense.id, 1)
    ClinicAccountingPostingService.post_inventory_consumption(movement.id, 1)

    report = clinic_accounting_report(1, date(2026, 9, 1), date(2026, 9, 30))
    assert report["net_profit"] == 450_000


def test_historical_migration_is_explicit_balanced_and_preserves_date(clinic_accounting_db):
    from models.journal_entry import JournalEntry
    from modules.clinics.accounting_service import ClinicAccountingMigrationService

    invoice = _invoice(total=125_000)
    assert JournalEntry.query.count() == 0  # deployment/schema creation never auto-posts history
    preview = ClinicAccountingMigrationService.preview(1)
    assert preview["journal_entries_to_create"] == 1
    assert preview["debit_total"] == preview["credit_total"] == 125_000
    result = ClinicAccountingMigrationService.run(1)
    assert result["created"] == 1
    entry = JournalEntry.query.one()
    assert entry.entry_date.date() == invoice.invoice_date
    second = ClinicAccountingMigrationService.run(1)
    assert second["created"] == 0
    assert JournalEntry.query.count() == 1
