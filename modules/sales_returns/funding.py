"""Allocate every returned dinar to an original tender under the write lock."""
from sqlalchemy import func, inspect
from extensions import db
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.treasury_account import TreasuryAccount
from modules.finance.common import FinanceError, tenant_key
from modules.finance.models import FinanceAllocation, FinanceVoucher
from .collections import from_original, read_default_cash_id
from .models import SalesReturn, SalesReturnFunding


def _error():
    raise FinanceError("مصدر التحصيل أو رد سابق غير قابل للتخصيص؛ راجع دليله قبل الرد", "source_review", 409)


def plan(invoice, original, allocations, credit):
    if not allocations and not credit:
        return []
    documents = SalesReturn.query.filter_by(tenant_key=tenant_key(), invoice_id=invoice.id).all()
    for document in documents:
        if document.excess_collection and not SalesReturnFunding.query.filter_by(document_id=document.id).first():
            _error()
    used = dict(db.session.query(SalesReturnFunding.source_ledger_id, func.sum(SalesReturnFunding.amount)).join(
        SalesReturn, SalesReturn.id == SalesReturnFunding.document_id).filter(
            SalesReturn.tenant_key == tenant_key(), SalesReturn.invoice_id == invoice.id,
            SalesReturnFunding.source_ledger_id.isnot(None)).group_by(SalesReturnFunding.source_ledger_id).all())
    previous_accounts = {}
    for source_id, account_id in db.session.query(SalesReturnFunding.source_ledger_id, SalesReturnFunding.treasury_account_id).join(
            SalesReturn, SalesReturn.id == SalesReturnFunding.document_id).filter(
                SalesReturn.tenant_key == tenant_key(), SalesReturn.invoice_id == invoice.id,
                SalesReturnFunding.source_ledger_id.isnot(None)).distinct():
        if source_id in previous_accounts and previous_accounts[source_id] != account_id:
            _error()
        previous_accounts[source_id] = account_id
    rows = InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id).order_by(
        InvoicePaymentLedger.recorded_at, InvoicePaymentLedger.id).all()
    buckets, candidates = {}, []
    baseline = from_original(original)
    if baseline:
        origin_used = sum(int(row.amount) for document in documents for row in
            SalesReturnFunding.query.filter_by(document_id=document.id).filter(SalesReturnFunding.origin_id.isnot(None)))
        account = baseline["treasury_account_id"]
        buckets[(account, False)] = baseline["amount"]
        candidates.append({"ledger": None, "voucher": None, "account": account, "offset": False,
            "available": baseline["amount"]-origin_used, "protected": False, "method": "cash"})
    for row in rows:
        offset = row.payment_method == "finance_offset"
        account = None if offset else row.treasury_account_id or read_default_cash_id(invoice.branch_id)
        key = account, offset
        buckets[key] = buckets.get(key, 0) + row.amount_delta
        if row.amount_delta <= 0:
            continue
        if row.id in previous_accounts and previous_accounts[row.id] != account:
            _error()
        available = row.amount_delta-int(used.get(row.id, 0))
        voucher_id = None
        if (row.source_module or "").startswith("finance:"):
            try:
                voucher_id = int(row.source_module.split(":", 1)[1])
            except (TypeError, ValueError):
                _error()
            voucher = db.session.get(FinanceVoucher, voucher_id)
            if not voucher or voucher.tenant_key != tenant_key() or voucher.party_type != "customer" or voucher.party_id != invoice.customer_id:
                _error()
            if voucher.status == "reversed":
                # Its signed reversal remains in buckets, but is not refundable again.
                continue
            allocation = FinanceAllocation.query.filter_by(voucher_id=voucher.id, reference_type="invoice", reference_id=invoice.id).first()
            if (voucher.status != "posted" or not allocation or allocation.amount != row.amount_delta
                    or voucher.branch_id != invoice.branch_id or voucher.kind not in {"receipt", "settlement"}
                    or (not offset and voucher.treasury_account_id != account)):
                _error()
        if available < 0:
            _error()
        treasury = db.session.get(TreasuryAccount, account) if account is not None else None
        method = row.payment_method or ("bank" if treasury and not treasury.is_cash else "cash")
        candidates.append({"ledger": row.id, "voucher": voucher_id, "account": account, "offset": offset,
            "available": available, "protected": voucher_id is not None, "method": method})
    desired = {(row["id"], False): row["amount"] for row in allocations}
    if credit:
        remaining = credit
        for key in sorted(buckets, key=lambda key: (key[0] or 0, key[1])):
            take = min(remaining, max(0, buckets[key]))
            if take:
                desired[key] = take
                remaining -= take
        if remaining:
            _error()
    result = []
    for key, requested in desired.items():
        sources = [row for row in candidates if (row["account"], row["offset"]) == key and row["available"] > 0]
        protected = sum(row["available"] for row in sources if row["protected"])
        ordinary_budget = buckets.get(key, 0)-protected
        # An unexplained historical negative may consume ordinary tenders, but
        # cannot silently consume an immutable finance receipt.
        if ordinary_budget < 0:
            _error()
        remaining = requested
        for source in sources:
            available = source["available"] if source["protected"] else min(source["available"], ordinary_budget)
            take = min(remaining, available)
            if take:
                result.append({"source_ledger_id": source["ledger"], "source_voucher_id": source["voucher"],
                    "treasury_account_id": source["account"], "payment_method": source["method"],
                    "disposition": "credit" if credit else "refund", "amount": take})
                remaining -= take
                if not source["protected"]:
                    ordinary_budget -= take
            if not remaining:
                break
        if remaining:
            _error()
    return result


def assert_source_reversible(voucher_id):
    if not inspect(db.session.connection()).has_table(SalesReturnFunding.__tablename__):
        return
    linked = SalesReturnFunding.query.join(SalesReturn, SalesReturn.id == SalesReturnFunding.document_id).filter(
        SalesReturn.tenant_key == tenant_key(), SalesReturnFunding.source_voucher_id == voucher_id).first()
    if linked:
        raise FinanceError("القبض مرتبط بمرتجع أو رصيد عميل؛ عالج المستند التابع قبل عكس الأصل", "dependency", 409)
