"""Reviewed reclassification of legacy overpayments, without moving cash again."""
from collections import defaultdict
from uuid import uuid4
from extensions import db
from models.branch import Branch
from models.customer import Customer
from models.invoice import Invoice
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.supplier import Supplier
from models.supplier_payment import SupplierPayment
from models.supplier_payment_allocation import SupplierPaymentAllocation
from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES
from .common import FinanceError, actor, audit, dumps, tenant_key, today
from .models import FinanceVoucher


def customer_excesses():
    return Invoice.query.filter(Invoice.status.notin_(list(CANCELED_STATUSES)+list(RETURN_STATUSES)),
        Invoice.paid_amount>Invoice.total).all()


def customer_total():
    return sum(max(0,int(i.paid_amount or 0)-int(i.total or 0)) for i in customer_excesses())


def issues():
    result=[]
    for invoice in customer_excesses():
        if not invoice.customer_id or not db.session.get(Customer,invoice.customer_id):
            result.append(f"اربط الفاتورة #{invoice.id} بزبون قبل تصنيف مبلغها الزائد كرصيد مقدم")
        entries=InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id).all()
        if entries and sum(e.amount_delta for e in entries)!=invoice.paid_amount:
            result.append(f"راجع اختلاف دفعات الفاتورة #{invoice.id} عن سجل الدفع قبل الترحيل")
    return result


def seed():
    problem=issues()
    if problem:
        raise FinanceError(problem[0],"opening_review",409)
    default=Branch.query.filter_by(is_default=True,is_active=True).first()
    grouped=defaultdict(int)
    for invoice in customer_excesses():
        original=int(invoice.paid_amount)
        branch_id=invoice.branch_id or default.id if default else invoice.branch_id
        entries=InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id).all()
        if not entries:
            # Preserve the legacy cash baseline before separating its excess.
            db.session.add(InvoicePaymentLedger(branch_id=branch_id,invoice_id=invoice.id,amount_delta=original,
                payment_method="cash",source_module="finance_opening",note="دفعات سابقة قبل تصنيف الرصيد المقدم",
                recorded_at=invoice.created_at))
        excess=original-int(invoice.total)
        db.session.add(InvoicePaymentLedger(branch_id=branch_id,invoice_id=invoice.id,amount_delta=-excess,
            payment_method="finance_offset",source_module="finance_opening",note="تصنيف فائض الدفع كرصيد مقدم؛ بدون حركة نقد"))
        invoice.paid_amount=invoice.total
        grouped[("customer",invoice.customer_id,branch_id)]+=excess
    for supplier in Supplier.query.all():
        from utils.supplier_payment_allocation import backfill_supplier_payment_allocations
        backfill_supplier_payment_allocations(supplier.id)
        excess=max(0,-supplier.remaining)
        if not excess:
            freeze_opening_allocations(supplier)
            continue
        branch_id=supplier.branch_id or default.id if default else supplier.branch_id
        # Reserve unused historical payments so FIFO cannot apply the same
        # advance again to future purchases after its explicit reclassification.
        left=excess
        sources=SupplierPaymentAllocation.query.join(SupplierPayment).filter(
            SupplierPayment.supplier_id==supplier.id,SupplierPayment.deleted_at.is_(None),
            SupplierPaymentAllocation.allocation_type.in_(["on_account","opening_balance"])).order_by(
                SupplierPaymentAllocation.allocation_type.desc(),SupplierPaymentAllocation.id.desc()).all()
        sources.sort(key=lambda source:(source.allocation_type!="on_account",-source.id))
        for source in sources:
            take=min(left,source.amount)
            if not take:
                continue
            reserved=SupplierPaymentAllocation.query.filter_by(supplier_payment_id=source.supplier_payment_id,
                target_key="finance:opening_credit").first()
            if reserved:
                reserved.amount+=take
                if take==source.amount:
                    db.session.delete(source)
                else:
                    source.amount-=take
            elif take==source.amount:
                source.allocation_type="opening_credit"
                source.target_key="finance:opening_credit"
            else:
                source.amount-=take
                db.session.add(SupplierPaymentAllocation(supplier_payment_id=source.supplier_payment_id,
                    allocation_type="opening_credit",target_key="finance:opening_credit",amount=take))
            left-=take
        before=supplier.total_paid
        supplier.total_paid-=excess
        grouped[("supplier",supplier.id,branch_id)]+=excess
        audit("opening.credit.reclassify","supplier",supplier,{"before_paid":before,"after_paid":supplier.total_paid,"credit":excess})
        freeze_opening_allocations(supplier)
    for (kind,party_id,branch_id),amount in grouped.items():
        if not branch_id:
            raise FinanceError("اربط الرصيد المقدم بفرع قبل اعتماد الافتتاحي","branch_required",409)
        party=db.session.get(Customer if kind=="customer" else Supplier,party_id)
        row=FinanceVoucher(tenant_key=tenant_key(),branch_id=branch_id,number=f"OP-{uuid4().hex[:16]}",
            kind="settlement",category=f"{kind}_advance",party_type=kind,party_id=party_id,party_name=party.name,
            amount=amount,transaction_date=today(),posting_date=today(),status="posted",created_by=actor().id,
            approved_by=actor().id,source_type="opening_credit_auto",source_id=party_id,
            payload=dumps({"opening_reclassification":True}),notes="رصيد مقدم سابق؛ تم تصنيفه في الافتتاحي بدون تكرار النقد")
        db.session.add(row)
        audit("opening.credit","voucher",row,{"party_type":kind,"party_id":party_id,"amount":amount})


def freeze_opening_allocations(supplier):
    rows=SupplierPaymentAllocation.query.join(SupplierPayment).filter(
        SupplierPayment.supplier_id==supplier.id,SupplierPayment.deleted_at.is_(None),
        SupplierPaymentAllocation.allocation_type=="opening_balance").all()
    for row in rows:
        row.allocation_type="opening_settled"
    if rows:
        audit("opening.allocations.freeze","supplier",supplier,{"allocations":[row.id for row in rows]})
