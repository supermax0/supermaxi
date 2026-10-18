"""Validate old voucher attribution without editing a posted financial source."""
import json

from sqlalchemy import inspect

from extensions import db
from models.customer_credit import CustomerCreditPayment, CustomerCreditPlan
from models.customer_schedule_payment_link import CustomerSchedulePaymentLink
from modules.desktop_api.customers import _scoped
from modules.finance.common import tenant_key
from modules.finance.models import FinanceAllocation, FinanceVoucher


def inspect_history(invoice, entries):
    result = {"snapshot": [], "sources": {}, "vouchers": [], "blocked": ""}
    inspector = inspect(db.session.connection())
    allocations = FinanceAllocation.query.filter_by(reference_type="invoice", reference_id=invoice.id).order_by(
        FinanceAllocation.id).all() if inspector.has_table(FinanceAllocation.__tablename__) else []
    financial_entries = [entry for entry in entries if str(entry.get("source_module") or "").startswith("finance:")]
    if not allocations and not financial_entries:
        return result
    try:
        if not inspector.has_table(FinanceVoucher.__tablename__):
            raise ValueError("missing vouchers")
        by_voucher = {}
        for entry in financial_entries:
            voucher_id = int(entry["source_module"].split(":", 1)[1])
            by_voucher.setdefault(voucher_id, []).append(entry)
        ids = {a.voucher_id for a in allocations} | set(by_voucher)
        vouchers = {v.id: v for v in _scoped(FinanceVoucher.query, FinanceVoucher).filter(FinanceVoucher.id.in_(ids)).all()}
        reversal_ids = {v.reversal_id for v in vouchers.values() if v.reversal_id}
        vouchers.update({v.id: v for v in _scoped(FinanceVoucher.query, FinanceVoucher).filter(FinanceVoucher.id.in_(reversal_ids)).all()})
        result["snapshot"] = [{"allocation": [a.id, a.voucher_id, a.amount, a.before_amount, a.after_amount]} for a in allocations]
        result["snapshot"] += [{"voucher": [v.id, v.tenant_key, v.branch_id, v.category, v.party_type, v.party_id,
            v.amount, v.status, v.version, v.reversal_id, v.transaction_date.isoformat(), v.number, v.approved_by,
            v.treasury_account_id, v.kind, v.payload]} for v in sorted(vouchers.values(), key=lambda v: v.id)]
        if inspector.has_table(CustomerSchedulePaymentLink.__tablename__):
            links = CustomerSchedulePaymentLink.query.filter(CustomerSchedulePaymentLink.invoice_allocation_id.in_([a.id for a in allocations])).all()
            result["snapshot"] += [{"link": [link.id, link.invoice_allocation_id, link.payment_id, link.reversal_payment_id]} for link in links]
            if links:
                raise ValueError("already attributed source")
        for allocation in allocations:
            original = vouchers.get(allocation.voucher_id)
            if (not original or original.tenant_key != tenant_key() or original.party_type != "customer"
                    or original.party_id != invoice.customer_id or original.status not in {"posted", "reversed"}
                    or original.category not in {"customer_payment", "customer_credit_apply"}
                    or original.kind not in {"receipt", "settlement"} or not original.approved_by
                    or not 0 < allocation.amount <= original.amount
                    or allocation.after_amount - allocation.before_amount != allocation.amount):
                raise ValueError("invalid original source")
            # A voucher can also contain slices for other, already scheduled documents.
            for credit in FinanceAllocation.query.filter_by(voucher_id=original.id, reference_type="credit_plan_payment"):
                payment = db.session.get(CustomerCreditPayment, credit.reference_id)
                old_plan = db.session.get(CustomerCreditPlan, payment.plan_id) if payment and payment.plan_id else None
                if not old_plan and original.status == "reversed" and payment:
                    # A fully reversed slice for another returned invoice can be
                    # legitimately archived with its plan/installment detached.
                    reverse_slice = FinanceAllocation.query.filter_by(voucher_id=original.reversal_id,
                        reference_type="credit_plan_reversal", reference_id=payment.id, amount=credit.amount).first()
                    if (payment.plan_id is None and payment.installment_id is None
                            and payment.customer_id == original.party_id and payment.amount == credit.amount
                            and (payment.note or "").startswith(f"[FV:{original.id}]")
                            and reverse_slice and reverse_slice.before_amount - reverse_slice.after_amount == credit.amount):
                        continue
                if not old_plan or old_plan.invoice_id == invoice.id:
                    raise ValueError("orphan or already allocated installment source")
            expected = [(original, allocation.amount, False)]
            if original.status == "reversed":
                reversal = vouchers.get(original.reversal_id)
                if (not reversal or reversal.tenant_key != original.tenant_key or reversal.status != "posted"
                        or reversal.category != "reversal" or reversal.party_type != "customer"
                        or reversal.party_id != invoice.customer_id or reversal.branch_id != original.branch_id
                        or reversal.amount != original.amount or json.loads(reversal.payload).get("original_id") != original.id):
                    raise ValueError("missing reversal source")
                expected.append((reversal, -allocation.amount, True))
            elif original.reversal_id:
                raise ValueError("inconsistent source status")
            for source, amount, reversed_slice in expected:
                matched = by_voucher.pop(source.id, [])
                if (len(matched) != 1 or matched[0]["amount_delta"] != amount
                        or not matched[0].get("recorded_at")
                        or matched[0].get("treasury_account_id") != source.treasury_account_id
                        or (matched[0].get("payment_method") == "finance_offset") != (original.kind == "settlement")):
                    raise ValueError("missing or mismatched voucher ledger slice")
                result["sources"][matched[0]["id"]] = (allocation, source, reversed_slice)
            result["vouchers"].append({"id": original.id, "number": original.number,
                "date": original.transaction_date.isoformat(), "amount": allocation.amount,
                "reversed": original.status == "reversed"})
        if by_voucher:
            raise ValueError("unallocated finance ledger")
        protected = sum(entry["amount_delta"] for entry in financial_entries)
        if not 0 <= protected <= int(invoice.paid_amount or 0):
            raise ValueError("finance owned amount exceeds current paid")
    except (ValueError, TypeError, KeyError, AttributeError):
        result["blocked"] = "حصص سندات الحسابات وسجل الفاتورة غير متطابقة أو خارج النطاق؛ راجع السند الأصلي قبل الجدولة"
    return result


def preserve_history(plan, row, entries, context, employee_id):
    """Create only installment history and immutable links to existing allocations."""
    pairs = {}
    for entry in entries:
        if not entry["amount_delta"]:
            continue
        source = context["sources"].get(entry["id"])
        payment = CustomerCreditPayment(customer_id=plan.customer_id, plan_id=plan.id,
            installment_id=row.id, amount=entry["amount_delta"], created_at=entry["recorded_at"],
            employee_id=source[1].approved_by if source else None,
            note=f"[FV:{source[1].id}] {source[1].number} — تخصيص لجدول لاحق" if source else
                f"[IP:{plan.invoice_id}] تخصيص تحصيل سابق من سجل الفاتورة #{entry['id']}")
        db.session.add(payment)
        db.session.flush()
        if source:
            allocation, _, is_reversal = source
            pairs.setdefault(allocation.id, {})["reversal" if is_reversal else "original"] = payment.id
    for allocation_id, pair in pairs.items():
        db.session.add(CustomerSchedulePaymentLink(invoice_allocation_id=allocation_id, payment_id=pair["original"],
            reversal_payment_id=pair.get("reversal"), employee_id=employee_id))
