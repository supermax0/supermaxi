"""Clinic subledger -> General Ledger posting, reconciliation and backfill.

Clinic tables remain the operational source of truth.  This module is the only
place where clinic events are translated into immutable double-entry journals.
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import case, func, or_
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.account import Account
from models.journal_entry import JournalEntry
from modules.clinics.models import (
    AccountingPosting,
    ClinicDoctor,
    ClinicDoctorSettlement,
    ClinicExpense,
    ClinicInventoryItem,
    ClinicInventoryMovement,
    ClinicInvoice,
    ClinicPatient,
    ClinicPayment,
    ClinicPurchase,
    ClinicPurchasePayment,
    ClinicPurchaseReturn,
    ClinicRefund,
    ClinicSupplier,
)
from utils.accounting_logic import ACCOUNT_CODES, create_journal_entry, initialize_accounts


CLINIC_ACCOUNT_CODES = {
    "cash": ACCOUNT_CODES["CASH"],
    "bank": ACCOUNT_CODES["BANK"],
    "card_clearing": ACCOUNT_CODES["CARD_CLEARING"],
    "inventory": ACCOUNT_CODES["INVENTORY"],
    "patient_receivable": ACCOUNT_CODES["ACCOUNTS_RECEIVABLE"],
    "supplier_payable": ACCOUNT_CODES["ACCOUNTS_PAYABLE"],
    "doctor_payable": ACCOUNT_CODES["DOCTOR_PAYABLE"],
    "medical_revenue": ACCOUNT_CODES["MEDICAL_REVENUE"],
    "medical_returns": ACCOUNT_CODES["MEDICAL_RETURNS"],
    "medical_cogs": ACCOUNT_CODES["COGS"],
    "doctor_commission": ACCOUNT_CODES["DOCTOR_COMMISSION_EXPENSE"],
    "clinic_expense": ACCOUNT_CODES["CLINIC_OPERATING_EXPENSE"],
    "payment_fee": ACCOUNT_CODES["PAYMENT_PROCESSING_FEES"],
}

PAYMENT_ACCOUNT_MAP = {
    "cash": CLINIC_ACCOUNT_CODES["cash"],
    "cash_payment": CLINIC_ACCOUNT_CODES["cash"],
    "card": CLINIC_ACCOUNT_CODES["card_clearing"],
    "visa": CLINIC_ACCOUNT_CODES["card_clearing"],
    "pos": CLINIC_ACCOUNT_CODES["card_clearing"],
    "transfer": CLINIC_ACCOUNT_CODES["bank"],
    "bank": CLINIC_ACCOUNT_CODES["bank"],
    "bank_transfer": CLINIC_ACCOUNT_CODES["bank"],
    "zain": CLINIC_ACCOUNT_CODES["card_clearing"],
    "electronic": CLINIC_ACCOUNT_CODES["card_clearing"],
    "other": CLINIC_ACCOUNT_CODES["card_clearing"],
}


def _event_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    return datetime.utcnow()


def _money(value) -> int:
    amount = int(round(Decimal(str(value or 0))))
    if amount <= 0:
        raise ValueError("المبلغ المحاسبي يجب أن يكون أكبر من الصفر")
    return amount


def _payment_account(method: str | None) -> str:
    key = str(method or "cash").strip().lower()
    try:
        return PAYMENT_ACCOUNT_MAP[key]
    except KeyError as exc:
        raise ValueError(f"طريقة الدفع غير مدعومة محاسبياً: {method}") from exc


def _tenant_row(model, tenant_id: int, source_id: int):
    row = model.query.filter_by(tenant_id=int(tenant_id), id=int(source_id)).first()
    if not row:
        raise ValueError("المستند المالي غير موجود ضمن المستأجر الحالي")
    return row


class ClinicAccountingPostingService:
    SOURCE_MODULE = "clinics"

    @classmethod
    def _posting(cls, tenant_id, source_type, source_id, source_event):
        return AccountingPosting.query.filter_by(
            tenant_id=int(tenant_id),
            source_module=cls.SOURCE_MODULE,
            source_type=source_type,
            source_id=int(source_id),
            source_event=source_event,
        ).first()

    @classmethod
    def _claim(cls, tenant_id, source_type, source_id, source_event, actor_id=None, branch_id=None):
        posting = cls._posting(tenant_id, source_type, source_id, source_event)
        if posting:
            return posting
        try:
            with db.session.begin_nested():
                posting = AccountingPosting(
                    tenant_id=int(tenant_id),
                    branch_id=branch_id,
                    source_module=cls.SOURCE_MODULE,
                    source_type=source_type,
                    source_id=int(source_id),
                    source_event=source_event,
                    status="unposted",
                    posted_by=actor_id,
                )
                db.session.add(posting)
                db.session.flush()
        except IntegrityError:
            posting = cls._posting(tenant_id, source_type, source_id, source_event)
            if not posting:
                raise
        return posting

    @classmethod
    def _post_pair(
        cls,
        tenant_id: int,
        source_type: str,
        source_id: int,
        source_event: str,
        debit_code: str,
        credit_code: str,
        amount,
        description: str,
        *,
        actor_id=None,
        branch_id=None,
        entry_date=None,
    ) -> JournalEntry:
        amount = _money(amount)
        initialize_accounts(commit=False)
        posting = cls._claim(
            tenant_id, source_type, source_id, source_event, actor_id=actor_id, branch_id=branch_id
        )
        if posting.status == "posted" and posting.journal_entry_id:
            return db.session.get(JournalEntry, posting.journal_entry_id)
        if posting.status == "reversed":
            raise ValueError("لا يمكن إعادة استخدام حدث محاسبي معكوس؛ أنشئ حدث تصحيح جديداً")
        entry = create_journal_entry(
            debit_account_code=debit_code,
            credit_account_code=credit_code,
            amount=amount,
            description=description,
            reference_type=source_type,
            reference_id=int(source_id),
            created_by=actor_id,
            entry_date=_event_datetime(entry_date),
        )
        db.session.flush()
        posting.journal_entry_id = entry.id
        posting.status = "posted"
        posting.posted_at = datetime.utcnow()
        posting.posted_by = actor_id
        posting.error_message = None
        posting.updated_at = datetime.utcnow()
        db.session.flush()
        return entry

    @staticmethod
    def _same_pair(entry, debit_code: str, credit_code: str, amount: int) -> bool:
        return bool(
            entry
            and int(entry.amount or 0) == int(amount)
            and entry.debit_account
            and entry.debit_account.code == debit_code
            and entry.credit_account
            and entry.credit_account.code == credit_code
        )

    @classmethod
    def _active_revision(cls, tenant_id, source_type, source_id, event_prefix):
        return (
            AccountingPosting.query.filter(
                AccountingPosting.tenant_id == int(tenant_id),
                AccountingPosting.source_module == cls.SOURCE_MODULE,
                AccountingPosting.source_type == source_type,
                AccountingPosting.source_id == int(source_id),
                AccountingPosting.source_event.like(f"{event_prefix}%"),
                AccountingPosting.status == "posted",
            )
            .order_by(AccountingPosting.id.desc())
            .first()
        )

    @classmethod
    def _revision_event(cls, tenant_id, source_type, source_id, prefix):
        count = AccountingPosting.query.filter(
            AccountingPosting.tenant_id == int(tenant_id),
            AccountingPosting.source_module == cls.SOURCE_MODULE,
            AccountingPosting.source_type == source_type,
            AccountingPosting.source_id == int(source_id),
            AccountingPosting.source_event.like(f"{prefix}%"),
        ).count()
        return prefix if count == 0 else f"{prefix}_revision_{count + 1}"

    @classmethod
    def _reverse_registry(cls, posting: AccountingPosting, *, actor_id=None, event="reversed"):
        if posting.status == "reversed" and posting.reversal_journal_entry_id:
            return db.session.get(JournalEntry, posting.reversal_journal_entry_id)
        original = db.session.get(JournalEntry, posting.journal_entry_id)
        if not original:
            raise ValueError("القيد الأصلي غير موجود")
        reversal_event = event
        occupied = cls._posting(posting.tenant_id, posting.source_type, posting.source_id, reversal_event)
        if occupied and occupied.id != posting.id:
            reversal_event = f"{event}_{posting.id}"
        reversal = cls._post_pair(
            posting.tenant_id,
            posting.source_type,
            posting.source_id,
            reversal_event,
            original.credit_account.code,
            original.debit_account.code,
            original.amount,
            f"عكس القيد {original.entry_number} — {original.description}",
            actor_id=actor_id,
            branch_id=posting.branch_id,
        )
        posting.status = "reversed"
        posting.reversed_at = datetime.utcnow()
        posting.reversal_journal_entry_id = reversal.id
        posting.updated_at = datetime.utcnow()
        db.session.flush()
        return reversal

    @classmethod
    def post_clinic_invoice(cls, invoice_id: int, tenant_id: int, actor_id=None):
        invoice = _tenant_row(ClinicInvoice, tenant_id, invoice_id)
        if invoice.status == "void":
            return cls.reverse_posting(
                tenant_id, "clinic_invoice", invoice.id, source_event_prefix="issued",
                reversal_event="voided", actor_id=actor_id,
            )
        amount = int(invoice.total or 0)
        if amount <= 0:
            return None
        debit = CLINIC_ACCOUNT_CODES["patient_receivable"]
        credit = CLINIC_ACCOUNT_CODES["medical_revenue"]
        active = cls._active_revision(tenant_id, "clinic_invoice", invoice.id, "issued")
        if active:
            old = db.session.get(JournalEntry, active.journal_entry_id)
            if cls._same_pair(old, debit, credit, amount):
                return old
            cls._reverse_registry(active, actor_id=actor_id, event=f"revised_{active.id}")
        patient = ClinicPatient.query.filter_by(tenant_id=tenant_id, id=invoice.patient_id).first()
        event = cls._revision_event(tenant_id, "clinic_invoice", invoice.id, "issued")
        description = f"Clinic Invoice #{invoice.invoice_number}"
        if patient:
            description += f" — Patient {patient.full_name}"
        if invoice.visit_id:
            description += f" — Visit {invoice.visit_id}"
        return cls._post_pair(
            tenant_id, "clinic_invoice", invoice.id, event, debit, credit, amount, description,
            actor_id=actor_id, branch_id=invoice.branch_id, entry_date=invoice.invoice_date,
        )

    @classmethod
    def post_clinic_payment(cls, payment_id: int, tenant_id: int, actor_id=None):
        payment = _tenant_row(ClinicPayment, tenant_id, payment_id)
        invoice = _tenant_row(ClinicInvoice, tenant_id, payment.invoice_id)
        return cls._post_pair(
            tenant_id, "clinic_payment", payment.id, "payment_received",
            _payment_account(payment.method), CLINIC_ACCOUNT_CODES["patient_receivable"], payment.amount,
            f"Clinic Payment #{payment.id} — Invoice {invoice.invoice_number}",
            actor_id=actor_id or payment.created_by, branch_id=payment.branch_id,
            entry_date=payment.paid_at,
        )

    @classmethod
    def post_clinic_refund(cls, refund_id: int, tenant_id: int, actor_id=None):
        refund = _tenant_row(ClinicRefund, tenant_id, refund_id)
        invoice = _tenant_row(ClinicInvoice, tenant_id, refund.invoice_id)
        # A payment refund re-opens the receivable; it is not a credit note.
        return cls._post_pair(
            tenant_id, "clinic_refund", refund.id, "refunded",
            CLINIC_ACCOUNT_CODES["patient_receivable"], _payment_account(refund.method), refund.amount,
            f"Clinic Refund #{refund.id} — Invoice {invoice.invoice_number}",
            actor_id=actor_id or refund.created_by, branch_id=refund.branch_id,
            entry_date=refund.refunded_at,
        )

    @classmethod
    def post_clinic_expense(cls, expense_id: int, tenant_id: int, actor_id=None):
        expense = _tenant_row(ClinicExpense, tenant_id, expense_id)
        return cls._post_pair(
            tenant_id, "clinic_expense", expense.id, "expense_created",
            CLINIC_ACCOUNT_CODES["clinic_expense"], _payment_account(expense.payment_method), expense.amount,
            f"Clinic Expense #{expense.id} — {expense.title}",
            actor_id=actor_id or expense.created_by, branch_id=expense.branch_id,
            entry_date=expense.expense_date,
        )

    @classmethod
    def post_clinic_purchase(cls, purchase_id: int, tenant_id: int, actor_id=None):
        purchase = _tenant_row(ClinicPurchase, tenant_id, purchase_id)
        if purchase.invoice_status == "draft":
            return None
        if purchase.invoice_status == "cancelled":
            return cls.reverse_posting(
                tenant_id, "clinic_purchase", purchase.id, source_event_prefix="purchase_created",
                reversal_event="voided", actor_id=actor_id,
            )
        amount = int(purchase.total or 0)
        if amount <= 0:
            return None
        debit = CLINIC_ACCOUNT_CODES["inventory"]
        credit = CLINIC_ACCOUNT_CODES["supplier_payable"]
        active = cls._active_revision(tenant_id, "clinic_purchase", purchase.id, "purchase_created")
        if active:
            old = db.session.get(JournalEntry, active.journal_entry_id)
            if cls._same_pair(old, debit, credit, amount):
                return old
            cls._reverse_registry(active, actor_id=actor_id, event=f"revised_{active.id}")
        supplier = ClinicSupplier.query.filter_by(tenant_id=tenant_id, id=purchase.supplier_id).first()
        event = cls._revision_event(tenant_id, "clinic_purchase", purchase.id, "purchase_created")
        description = f"Clinic Purchase #{purchase.purchase_number}"
        if supplier:
            description += f" — Supplier {supplier.name}"
        return cls._post_pair(
            tenant_id, "clinic_purchase", purchase.id, event, debit, credit, amount, description,
            actor_id=actor_id or purchase.created_by, branch_id=purchase.branch_id,
            entry_date=purchase.purchase_date,
        )

    @classmethod
    def post_clinic_purchase_payment(cls, payment_id: int, tenant_id: int, actor_id=None):
        payment = _tenant_row(ClinicPurchasePayment, tenant_id, payment_id)
        purchase = _tenant_row(ClinicPurchase, tenant_id, payment.purchase_id)
        return cls._post_pair(
            tenant_id, "clinic_purchase_payment", payment.id, "supplier_payment",
            CLINIC_ACCOUNT_CODES["supplier_payable"], _payment_account(payment.payment_method), payment.amount,
            f"Clinic Supplier Payment #{payment.payment_number} — Purchase {purchase.purchase_number}",
            actor_id=actor_id or payment.created_by, branch_id=purchase.branch_id,
            entry_date=payment.payment_date,
        )

    @classmethod
    def post_clinic_purchase_return(cls, return_id: int, tenant_id: int, actor_id=None):
        purchase_return = _tenant_row(ClinicPurchaseReturn, tenant_id, return_id)
        purchase = _tenant_row(ClinicPurchase, tenant_id, purchase_return.purchase_id)
        return cls._post_pair(
            tenant_id, "clinic_purchase_return", purchase_return.id, "purchase_returned",
            CLINIC_ACCOUNT_CODES["supplier_payable"], CLINIC_ACCOUNT_CODES["inventory"],
            purchase_return.total_value,
            f"Clinic Purchase Return #{purchase_return.return_number} — Purchase {purchase.purchase_number}",
            actor_id=actor_id or purchase_return.created_by, branch_id=purchase_return.branch_id,
            entry_date=purchase_return.return_date,
        )

    @classmethod
    def post_doctor_settlement(cls, settlement_id: int, tenant_id: int, actor_id=None):
        settlement = _tenant_row(ClinicDoctorSettlement, tenant_id, settlement_id)
        if settlement.status == "draft" or int(settlement.doctor_share or 0) <= 0:
            return None
        doctor = ClinicDoctor.query.filter_by(tenant_id=tenant_id, id=settlement.doctor_id).first()
        return cls._post_pair(
            tenant_id, "clinic_doctor_settlement", settlement.id, "doctor_accrual",
            CLINIC_ACCOUNT_CODES["doctor_commission"], CLINIC_ACCOUNT_CODES["doctor_payable"],
            settlement.doctor_share,
            f"Doctor Settlement #{settlement.id} — {doctor.full_name if doctor else settlement.doctor_id} — {settlement.period_from} to {settlement.period_to}",
            actor_id=actor_id or settlement.created_by, entry_date=settlement.created_at,
        )

    @classmethod
    def post_doctor_settlement_payment(cls, settlement_id: int, tenant_id: int, actor_id=None):
        settlement = _tenant_row(ClinicDoctorSettlement, tenant_id, settlement_id)
        if int(settlement.paid_amount or 0) <= 0:
            return None
        return cls._post_pair(
            tenant_id, "clinic_doctor_settlement", settlement.id, "doctor_payment",
            CLINIC_ACCOUNT_CODES["doctor_payable"], _payment_account(settlement.payment_method),
            settlement.paid_amount, f"Doctor Settlement Payment #{settlement.id}",
            actor_id=actor_id or settlement.created_by, entry_date=settlement.created_at,
        )

    @classmethod
    def post_inventory_consumption(cls, movement_id: int, tenant_id: int, actor_id=None):
        movement = _tenant_row(ClinicInventoryMovement, tenant_id, movement_id)
        if movement.movement_type not in ("out", "procedure") or movement.reference_type == "purchase_return":
            return None
        amount = int(round(Decimal(str(movement.quantity or 0)) * Decimal(str(movement.unit_cost or 0))))
        if amount <= 0:
            return None
        item = ClinicInventoryItem.query.filter_by(tenant_id=tenant_id, id=movement.item_id).first()
        return cls._post_pair(
            tenant_id, "clinic_inventory_consumption", movement.id, "inventory_consumed",
            CLINIC_ACCOUNT_CODES["medical_cogs"], CLINIC_ACCOUNT_CODES["inventory"], amount,
            f"Clinic Inventory Consumption #{movement.id} — {item.name if item else movement.item_id}",
            actor_id=actor_id or movement.created_by, branch_id=movement.branch_id,
            entry_date=movement.created_at,
        )

    @classmethod
    def reverse_posting(
        cls, tenant_id: int, source_type: str, source_id: int, *,
        source_event_prefix: str, reversal_event="reversed", actor_id=None,
    ):
        existing_reversal = cls._posting(tenant_id, source_type, source_id, reversal_event)
        if existing_reversal and existing_reversal.status == "posted" and existing_reversal.journal_entry_id:
            return db.session.get(JournalEntry, existing_reversal.journal_entry_id)
        posting = cls._active_revision(tenant_id, source_type, source_id, source_event_prefix)
        if not posting:
            return None
        return cls._reverse_registry(posting, actor_id=actor_id, event=reversal_event)

    @classmethod
    def record_error(cls, tenant_id, source_type, source_id, source_event, message, actor_id=None):
        posting = cls._claim(tenant_id, source_type, source_id, source_event, actor_id=actor_id)
        posting.status = "error"
        posting.error_message = str(message)[:4000]
        posting.updated_at = datetime.utcnow()
        db.session.flush()
        return posting

    @classmethod
    def repost(cls, tenant_id: int, posting_id: int, actor_id=None):
        posting = AccountingPosting.query.filter_by(tenant_id=tenant_id, id=posting_id).first()
        if not posting:
            raise ValueError("سجل الترحيل غير موجود")
        if posting.status == "posted":
            return db.session.get(JournalEntry, posting.journal_entry_id)
        if posting.status == "reversed":
            raise ValueError("القيد معكوس ولا يمكن إعادة ترحيله كحدث قديم")
        dispatch = {
            "clinic_invoice": cls.post_clinic_invoice,
            "clinic_payment": cls.post_clinic_payment,
            "clinic_refund": cls.post_clinic_refund,
            "clinic_expense": cls.post_clinic_expense,
            "clinic_purchase": cls.post_clinic_purchase,
            "clinic_purchase_payment": cls.post_clinic_purchase_payment,
            "clinic_purchase_return": cls.post_clinic_purchase_return,
            "clinic_doctor_settlement": cls.post_doctor_settlement,
            "clinic_inventory_consumption": cls.post_inventory_consumption,
        }
        handler = dispatch.get(posting.source_type)
        if not handler:
            raise ValueError("نوع مصدر الترحيل غير مدعوم")
        return handler(posting.source_id, tenant_id, actor_id)


def posting_dict(row: AccountingPosting) -> dict:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "branch_id": row.branch_id,
        "source_module": row.source_module,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "source_event": row.source_event,
        "journal_entry_id": row.journal_entry_id,
        "status": row.status,
        "posted_at": row.posted_at.isoformat() if row.posted_at else None,
        "posted_by": row.posted_by,
        "reversed_at": row.reversed_at.isoformat() if row.reversed_at else None,
        "reversal_journal_entry_id": row.reversal_journal_entry_id,
        "error_message": row.error_message,
    }


def list_accounting_postings(tenant_id: int, *, status=None, source_type=None, limit=200) -> list[dict]:
    query = AccountingPosting.query.filter_by(tenant_id=int(tenant_id), source_module="clinics")
    if status:
        query = query.filter_by(status=str(status))
    if source_type:
        query = query.filter_by(source_type=str(source_type))
    rows = query.order_by(AccountingPosting.id.desc()).limit(min(500, max(1, int(limit)))).all()
    return [posting_dict(row) for row in rows]


def _gl_balance(account_code: str, *, through: datetime | None = None) -> int:
    account = Account.query.filter_by(code=account_code).first()
    if not account:
        return 0
    query = db.session.query(
        func.coalesce(func.sum(case((JournalEntry.debit_account_id == account.id, JournalEntry.amount), else_=0)), 0),
        func.coalesce(func.sum(case((JournalEntry.credit_account_id == account.id, JournalEntry.amount), else_=0)), 0),
    )
    if through is not None:
        query = query.filter(JournalEntry.entry_date <= through)
    debits, credits = query.one()
    if account.account_type in ("asset", "expense"):
        return int(debits or 0) - int(credits or 0)
    return int(credits or 0) - int(debits or 0)


def _metric(name, subledger, gl):
    difference = int(subledger or 0) - int(gl or 0)
    return {
        "name": name,
        "subledger_balance": int(subledger or 0),
        "gl_balance": int(gl or 0),
        "difference": difference,
        "status": "balanced" if difference == 0 else "difference",
    }


def reconcile_clinic_receivables(tenant_id: int) -> dict:
    subledger = db.session.query(func.coalesce(func.sum(ClinicInvoice.balance), 0)).filter(
        ClinicInvoice.tenant_id == int(tenant_id), ClinicInvoice.status != "void"
    ).scalar()
    return _metric("patient_receivables", subledger, _gl_balance(CLINIC_ACCOUNT_CODES["patient_receivable"]))


def reconcile_clinic_supplier_payables(tenant_id: int) -> dict:
    subledger = db.session.query(func.coalesce(func.sum(ClinicPurchase.balance), 0)).filter(
        ClinicPurchase.tenant_id == int(tenant_id), ClinicPurchase.invoice_status != "cancelled"
    ).scalar()
    return _metric("supplier_payables", subledger, _gl_balance(CLINIC_ACCOUNT_CODES["supplier_payable"]))


def reconcile_clinic_doctor_payables(tenant_id: int) -> dict:
    subledger = db.session.query(func.coalesce(func.sum(ClinicDoctorSettlement.balance), 0)).filter(
        ClinicDoctorSettlement.tenant_id == int(tenant_id),
        ClinicDoctorSettlement.status.notin_(("draft", "cancelled")),
    ).scalar()
    return _metric("doctor_payables", subledger, _gl_balance(CLINIC_ACCOUNT_CODES["doctor_payable"]))


def reconcile_clinic_inventory(tenant_id: int) -> dict:
    subledger = db.session.query(
        func.coalesce(func.sum(ClinicInventoryItem.current_stock * ClinicInventoryItem.average_cost), 0)
    ).filter(
        ClinicInventoryItem.tenant_id == int(tenant_id), ClinicInventoryItem.active.is_(True)
    ).scalar()
    subledger = int(round(Decimal(str(subledger or 0))))
    result = _metric("medical_inventory", subledger, _gl_balance(CLINIC_ACCOUNT_CODES["inventory"]))
    result["valuation_method"] = "weighted_average"
    return result


def clinic_accounting_reconciliation(tenant_id: int) -> dict:
    sections = {
        "patient_receivables": reconcile_clinic_receivables(tenant_id),
        "supplier_payables": reconcile_clinic_supplier_payables(tenant_id),
        "doctor_payables": reconcile_clinic_doctor_payables(tenant_id),
        "inventory": reconcile_clinic_inventory(tenant_id),
    }
    error_count = AccountingPosting.query.filter_by(
        tenant_id=int(tenant_id), source_module="clinics", status="error"
    ).count()
    differences = [row for row in sections.values() if row["difference"] != 0]
    if error_count:
        health = "posting_errors"
    elif differences:
        health = "needs_reconciliation"
    else:
        health = "healthy"
    return {
        **sections,
        "error_postings": error_count,
        "has_difference": bool(differences),
        "message": "يوجد فرق بين دفتر العيادة والدليل المحاسبي" if differences else "متطابق",
        "accounting_status": health,
    }


def clinic_accounting_report(tenant_id: int, date_from: date, date_to: date) -> dict:
    end = datetime.combine(date_to, time.max)
    start = datetime.combine(date_from, time.min)

    def period_balance(code):
        account = Account.query.filter_by(code=code).first()
        if not account:
            return 0
        debits, credits = db.session.query(
            func.coalesce(func.sum(case((JournalEntry.debit_account_id == account.id, JournalEntry.amount), else_=0)), 0),
            func.coalesce(func.sum(case((JournalEntry.credit_account_id == account.id, JournalEntry.amount), else_=0)), 0),
        ).filter(JournalEntry.entry_date >= start, JournalEntry.entry_date <= end).one()
        return int(debits or 0) - int(credits or 0) if account.account_type in ("asset", "expense") else int(credits or 0) - int(debits or 0)

    revenue = period_balance(CLINIC_ACCOUNT_CODES["medical_revenue"])
    returns = period_balance(CLINIC_ACCOUNT_CODES["medical_returns"])
    supplies = period_balance(CLINIC_ACCOUNT_CODES["medical_cogs"])
    commissions = period_balance(CLINIC_ACCOUNT_CODES["doctor_commission"])
    operating = period_balance(CLINIC_ACCOUNT_CODES["clinic_expense"])
    fees = period_balance(CLINIC_ACCOUNT_CODES["payment_fee"])
    return {
        "medical_revenue": revenue,
        "medical_returns": returns,
        "medical_supplies_cost": supplies,
        "doctor_commission_expense": commissions,
        "clinic_operating_expenses": operating,
        "payment_fees": fees,
        "net_profit": revenue - returns - supplies - commissions - operating - fees,
        "patient_receivables": _gl_balance(CLINIC_ACCOUNT_CODES["patient_receivable"], through=end),
        "supplier_payables": _gl_balance(CLINIC_ACCOUNT_CODES["supplier_payable"], through=end),
        "doctor_payables": _gl_balance(CLINIC_ACCOUNT_CODES["doctor_payable"], through=end),
        "medical_inventory": _gl_balance(CLINIC_ACCOUNT_CODES["inventory"], through=end),
        "cash_balance": _gl_balance(CLINIC_ACCOUNT_CODES["cash"], through=end),
        "bank_balance": _gl_balance(CLINIC_ACCOUNT_CODES["bank"], through=end),
        "card_clearing": _gl_balance(CLINIC_ACCOUNT_CODES["card_clearing"], through=end),
    }


class ClinicAccountingMigrationService:
    """Explicit, tenant-scoped historical posting.  Deployment never invokes it."""

    TYPES = (
        ("invoices", ClinicInvoice, "clinic_invoice"),
        ("payments", ClinicPayment, "clinic_payment"),
        ("refunds", ClinicRefund, "clinic_refund"),
        ("expenses", ClinicExpense, "clinic_expense"),
        ("purchases", ClinicPurchase, "clinic_purchase"),
        ("supplier_payments", ClinicPurchasePayment, "clinic_purchase_payment"),
        ("purchase_returns", ClinicPurchaseReturn, "clinic_purchase_return"),
        ("doctor_settlements", ClinicDoctorSettlement, "clinic_doctor_settlement"),
        ("inventory_movements", ClinicInventoryMovement, "clinic_inventory_consumption"),
    )

    @classmethod
    def _counts(cls, tenant_id):
        result = {}
        for label, model, source_type in cls.TYPES:
            query = model.query.filter(model.tenant_id == int(tenant_id))
            if model is ClinicInventoryMovement:
                query = query.filter(
                    model.movement_type.in_(("out", "procedure")), model.unit_cost > 0,
                    or_(model.reference_type.is_(None), model.reference_type != "purchase_return"),
                )
            total = query.count()
            posted_ids = {
                row[0] for row in db.session.query(AccountingPosting.source_id).filter(
                    AccountingPosting.tenant_id == int(tenant_id),
                    AccountingPosting.source_module == "clinics",
                    AccountingPosting.source_type == source_type,
                    AccountingPosting.status.in_(("posted", "reversed")),
                ).all()
            }
            result[label] = {"total_records": total, "already_posted": len(posted_ids), "unposted": max(0, total - len(posted_ids))}
        return result

    @classmethod
    def _planned(cls, tenant_id):
        planned = []
        spec = [
            (ClinicInvoice, "invoice", "post_clinic_invoice", "invoice_date", lambda r: int(r.total or 0), 0),
            (ClinicPayment, "payment", "post_clinic_payment", "paid_at", lambda r: int(r.amount or 0), 1),
            (ClinicRefund, "refund", "post_clinic_refund", "refunded_at", lambda r: int(r.amount or 0), 2),
            (ClinicExpense, "expense", "post_clinic_expense", "expense_date", lambda r: int(r.amount or 0), 3),
            (ClinicPurchase, "purchase", "post_clinic_purchase", "purchase_date", lambda r: int(r.total or 0) if r.invoice_status not in ("draft", "cancelled") else 0, 4),
            (ClinicPurchasePayment, "supplier_payment", "post_clinic_purchase_payment", "payment_date", lambda r: int(r.amount or 0), 5),
            (ClinicPurchaseReturn, "purchase_return", "post_clinic_purchase_return", "return_date", lambda r: int(r.total_value or 0), 5),
            (ClinicDoctorSettlement, "doctor_accrual", "post_doctor_settlement", "created_at", lambda r: int(r.doctor_share or 0) if r.status != "draft" else 0, 6),
            (ClinicInventoryMovement, "inventory_consumed", "post_inventory_consumption", "created_at", lambda r: int(round(Decimal(str(r.quantity or 0)) * Decimal(str(r.unit_cost or 0)))) if r.movement_type in ("out", "procedure") and r.reference_type != "purchase_return" else 0, 8),
        ]
        for model, event, handler, date_field, amount_fn, priority in spec:
            for row in model.query.filter(model.tenant_id == int(tenant_id)).all():
                amount = amount_fn(row)
                if amount <= 0:
                    continue
                planned.append({"row": row, "event": event, "handler": handler, "date": _event_datetime(getattr(row, date_field)), "amount": amount, "priority": priority})
                if model is ClinicDoctorSettlement and int(row.paid_amount or 0) > 0:
                    planned.append({"row": row, "event": "doctor_payment", "handler": "post_doctor_settlement_payment", "date": _event_datetime(row.created_at), "amount": int(row.paid_amount), "priority": 7})
        planned.sort(key=lambda item: (item["date"], item["priority"], item["row"].id))
        return planned

    @classmethod
    def preview(cls, tenant_id: int) -> dict:
        counts = cls._counts(tenant_id)
        planned = cls._planned(tenant_id)
        to_create = []
        for item in planned:
            row = item["row"]
            source_type = "clinic_inventory_consumption" if isinstance(row, ClinicInventoryMovement) else row.__tablename__
            event_names = {
                "invoice": "issued",
                "payment": "payment_received",
                "refund": "refunded",
                "expense": "expense_created",
                "purchase": "purchase_created",
                "supplier_payment": "supplier_payment",
                "purchase_return": "purchase_returned",
                "doctor_accrual": "doctor_accrual",
                "doctor_payment": "doctor_payment",
                "inventory_consumed": "inventory_consumed",
            }
            expected_event = event_names[item["event"]]
            query = AccountingPosting.query.filter(
                AccountingPosting.tenant_id == int(tenant_id),
                AccountingPosting.source_type == source_type,
                AccountingPosting.source_id == row.id,
                AccountingPosting.status.in_(("posted", "reversed")),
            )
            if expected_event in ("issued", "purchase_created"):
                query = query.filter(AccountingPosting.source_event.like(f"{expected_event}%"))
            else:
                query = query.filter(AccountingPosting.source_event == expected_event)
            exists = query.first()
            if not exists:
                to_create.append(item)
        total = sum(item["amount"] for item in to_create)
        return {
            "tenant_id": int(tenant_id),
            "records": counts,
            "journal_entries_to_create": len(to_create),
            "debit_total": total,
            "credit_total": total,
            "difference": 0,
            "balanced": True,
        }

    @classmethod
    def run(cls, tenant_id: int, actor_id=None) -> dict:
        preview = cls.preview(tenant_id)
        if preview["debit_total"] != preview["credit_total"]:
            raise ValueError("لا يمكن بدء الترحيل لأن إجمالي المدين لا يساوي إجمالي الدائن")
        created = 0
        errors = []
        known_entry_ids = {row[0] for row in db.session.query(JournalEntry.id).all()}
        for item in cls._planned(tenant_id):
            row = item["row"]
            handler = getattr(ClinicAccountingPostingService, item["handler"])
            try:
                with db.session.begin_nested():
                    entry = handler(row.id, tenant_id, actor_id)
                if entry is not None and entry.id not in known_entry_ids:
                    known_entry_ids.add(entry.id)
                    created += 1
            except Exception as exc:
                source_type = "clinic_inventory_consumption" if isinstance(row, ClinicInventoryMovement) else row.__tablename__
                ClinicAccountingPostingService.record_error(tenant_id, source_type, row.id, item["event"], exc, actor_id)
                errors.append({"source_type": source_type, "source_id": row.id, "error": str(exc)})
        return {"preview": preview, "created": created, "errors": errors, "valid": not errors}

    @classmethod
    def validate(cls, tenant_id: int) -> dict:
        return {"preview": cls.preview(tenant_id), "reconciliation": clinic_accounting_reconciliation(tenant_id)}
