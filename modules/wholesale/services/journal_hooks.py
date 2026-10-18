"""Double-entry journal hooks for wholesale operations."""
from __future__ import annotations

from datetime import datetime

from extensions import db
from models.account import Account
from models.journal_entry import JournalEntry
from modules.wholesale.services.helpers import to_base_amount


def _find_account(code_or_name_parts: list[str]) -> Account | None:
    for part in code_or_name_parts:
        acc = Account.query.filter(Account.name.contains(part)).first()
        if acc:
            return acc
    return Account.query.first()


def _next_entry_number() -> str:
    last = JournalEntry.query.order_by(JournalEntry.id.desc()).first()
    n = (last.id + 1) if last else 1
    return f"JE-WS-{datetime.utcnow().strftime('%Y%m%d')}-{n:05d}"


def _post_pair(
    *,
    description: str,
    amount: int,
    debit_account: Account | None,
    credit_account: Account | None,
    reference_type: str,
    reference_id: int,
) -> JournalEntry | None:
    if not debit_account or not credit_account or amount <= 0:
        return None
    if debit_account.id == credit_account.id:
        return None
    entry = JournalEntry(
        entry_number=_next_entry_number(),
        description=description,
        reference_type=reference_type,
        reference_id=reference_id,
        debit_account_id=debit_account.id,
        credit_account_id=credit_account.id,
        amount=int(amount),
        entry_date=datetime.utcnow(),
    )
    db.session.add(entry)
    db.session.flush()
    return entry


def post_sale_journals(invoice, *, cogs: int = 0) -> list:
    """Revenue + COGS for a confirmed wholesale sale (amounts in IQD base)."""
    created = []
    currency = getattr(invoice, "currency", None) or "IQD"
    rate = float(getattr(invoice, "exchange_rate", None) or 1)
    total_base = to_base_amount(int(invoice.total or 0), currency, rate)

    ar = _find_account(["عملاء", "ذمم", "مدينون", "Receivable"])
    sales = _find_account(["مبيعات", "إيراد", "Sales"])
    cash = _find_account(["صندوق", "نقدية", "Cash"])
    inventory = _find_account(["مخزون", "بضاعة", "Inventory"])
    cogs_acc = _find_account(["تكلفة", "كلفة", "COGS"])

    sale_type = (getattr(invoice, "sale_type", None) or "credit").lower()
    debit_acc = cash if sale_type == "cash" else ar
    e1 = _post_pair(
        description=f"بيع جملة فاتورة {getattr(invoice, 'invoice_no', None) or invoice.id}",
        amount=total_base,
        debit_account=debit_acc,
        credit_account=sales,
        reference_type="wholesale_sale",
        reference_id=invoice.id,
    )
    if e1:
        created.append(e1)

    if cogs > 0:
        e2 = _post_pair(
            description=f"تكلفة بضاعة فاتورة {getattr(invoice, 'invoice_no', None) or invoice.id}",
            amount=int(cogs),
            debit_account=cogs_acc,
            credit_account=inventory,
            reference_type="wholesale_cogs",
            reference_id=invoice.id,
        )
        if e2:
            created.append(e2)
    return created


def post_receipt_journal(*, amount_base: int, reference_id: int, doc_no: str | None = None) -> JournalEntry | None:
    cash = _find_account(["صندوق", "نقدية", "Cash"])
    ar = _find_account(["عملاء", "ذمم", "مدينون", "Receivable"])
    return _post_pair(
        description=f"قبض جملة {doc_no or reference_id}",
        amount=amount_base,
        debit_account=cash,
        credit_account=ar,
        reference_type="wholesale_receipt",
        reference_id=reference_id,
    )


def post_purchase_journal(purchase, *, amount_base: int) -> JournalEntry | None:
    inventory = _find_account(["مخزون", "بضاعة", "Inventory"])
    ap = _find_account(["موردون", "دائنون", "Payable"])
    cash = _find_account(["صندوق", "نقدية", "Cash"])
    mode = (getattr(purchase, "purchase_mode", None) or "credit").lower()
    credit_acc = cash if mode == "cash" else ap
    return _post_pair(
        description=f"شراء جملة {getattr(purchase, 'invoice_no', None) or purchase.id}",
        amount=amount_base,
        debit_account=inventory,
        credit_account=credit_acc,
        reference_type="wholesale_purchase",
        reference_id=purchase.id,
    )


def post_supplier_payment_journal(*, amount_base: int, reference_id: int, doc_no: str | None = None) -> JournalEntry | None:
    ap = _find_account(["موردون", "دائنون", "Payable"])
    cash = _find_account(["صندوق", "نقدية", "Cash"])
    return _post_pair(
        description=f"تسديد مورد {doc_no or reference_id}",
        amount=amount_base,
        debit_account=ap,
        credit_account=cash,
        reference_type="wholesale_payment",
        reference_id=reference_id,
    )
