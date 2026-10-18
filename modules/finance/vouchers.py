"""Draft/approval/reversal and atomic allocations into existing FINORA documents."""
import json
from datetime import datetime
from uuid import uuid4
from sqlalchemy import func
from extensions import db
from models.account_transaction import AccountTransaction
from models.customer import Customer
from models.customer_credit import CustomerCreditPlan
from models.expense import Expense
from models.fixed_asset import FixedAsset
from models.fixed_asset_category import FixedAssetCategory
from models.invoice import Invoice
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.purchase import Purchase
from models.receipt import Receipt, ReceiptAllocation
from models.supplier import Supplier
from models.supplier_payment import SupplierPayment
from models.supplier_payment_allocation import SupplierPaymentAllocation
from models.treasury_transfer import TreasuryTransfer
from utils.financial_period_guard import assert_date_period_open
from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES
from . import ledger, customer_installments
from .common import FinanceError, actor, audit, can, day, dumps, get_row, money, policy, require, scope, tenant_key, text, today, version, write_branch
from .models import FinanceAllocation, FinanceLoan, FinanceLoanPayment, FinanceVoucher

CATEGORIES = {
    "customer_payment": ("receipt", "تسديد زبون", "customer", "operating", "تحصيل دين مسجل؛ يزيد النقد ويخفض دين الزبون دون إيراد جديد."),
    "customer_advance": ("receipt", "دفعة مقدمة من زبون", "customer", "operating", "رصيد للزبون يُسوّى مع فاتورة لاحقاً، ولا يُعد إيراداً الآن."),
    "supplier_refund": ("receipt", "استرجاع دفعة مورد", "supplier", "operating", "استرجاع من رصيد دفعات المورد؛ لا يزيد الأرباح."),
    "loan_funding": ("receipt", "استلام قرض للشركة", "loan", "financing", "يزيد النقد ويثبت أصل القرض كالتزام دون زيادة الربح."),
    "loan_collection": ("receipt", "تحصيل قرض ممنوح", "loan", "investing", "يخفض أصل القرض الممنوح؛ الفائدة فقط تُعد إيراداً."),
    "employee_return": ("receipt", "استرجاع سلفة موظف", "loan", "operating", "يخفض السلفة المستحقة دون زيادة الربح."),
    "capital": ("receipt", "مساهمة رأسمالية", "other", "financing", "زيادة في حقوق المالك وليست إيراد مبيعات."),
    "other_income": ("receipt", "إيراد آخر", "other", "operating", "إيراد جديد يضاف للأرباح؛ لا تستخدمه لتحصيل دين أو قرض."),
    "expense_refund": ("receipt", "استرداد مصروف", "other", "operating", "يرتبط بمصروف أصلي ويخفض المصروف المسترد مرة واحدة."),
    "supplier_payment": ("payment", "تسديد مورد", "supplier", "operating", "يخفض النقد وذمة المورد؛ تكلفة الشراء لا تُخصم من الربح مرة أخرى."),
    "expense": ("payment", "مصروف تشغيل جديد", "other", "operating", "مصروف جديد للفترة يخفض النقد والربح مرة واحدة."),
    "expense_accrual": ("settlement", "إثبات مصروف مستحق", "other", "operating", "يثبت المصروف والالتزام بدون سحب نقد. تسديده لاحقاً لا يكرر المصروف."),
    "accrued_expense": ("payment", "دفع مصروف مستحق", "other", "operating", "تسديد التزام مسجل سابقاً؛ لا يسجل مصروفاً إضافياً."),
    "inventory_purchase": ("payment", "دفع مشتريات مخزون", "supplier", "operating", "اختر فاتورة مشتريات مستلمة؛ الصرف يسدد الفاتورة ولا يكرر إضافة المخزون."),
    "fixed_asset": ("payment", "شراء أصل ثابت", "other", "investing", "يثبت الأصل؛ الإهلاك حسب عمره، دون خصم قيمته كاملة من الأرباح."),
    "loan_payment": ("payment", "تسديد قرض الشركة", "loan", "financing", "أصل القرض لا يخفض الربح؛ الفائدة والرسوم الجديدة فقط مصروف."),
    "loan_grant": ("payment", "منح قرض للغير", "loan", "investing", "يخفض النقد ويثبت حق الشركة باسترداد أصل القرض."),
    "employee_advance": ("payment", "سلفة موظف", "loan", "operating", "تثبت سلفة الموظف وتُربط بالرواتب؛ الأصل لا يخفض الأرباح."),
    "owner_draw": ("payment", "سحب مالك", "other", "financing", "يخفض النقد وحقوق المالك دون تخفيض الربح التشغيلي."),
    "supplier_advance": ("payment", "دفعة مقدمة لمورد", "supplier", "operating", "حق للشركة لدى المورد يطبق لاحقاً على المشتريات دون تكرار الدفع."),
    "customer_refund": ("payment", "رد رصيد زبون", "customer", "operating", "إعادة جزء من دفعات الزبون المقدمة، دون مصروف جديد."),
    "account_transfer": ("transfer", "تحويل داخلي", "other", "internal", "ينقل المال بين حسابين؛ إجمالي النقد والربح لا يتغيران."),
}


def create(payload, *, internal=False):
    require("finance.create")
    category = text(payload.get("category"), 40, True)
    if category not in CATEGORIES:
        raise FinanceError("اختر سبب عملية صحيحاً")
    kind, _, party_type, _, _ = CATEGORIES[category]
    if payload.get("currency_code", "IQD") != "IQD" or str(payload.get("exchange_rate", "1")) not in {"1", "1.0", "1.00000000"}:
        raise FinanceError("العمليات الحالية بالدينار العراقي؛ تحويل العملات غير مفعّل")
    branch_id = write_branch(payload)
    account = ledger.treasury(payload.get("treasury_account_id"), branch_id) if kind!="settlement" else None
    party_id, party_name = None, text(payload.get("party_name"), 150)
    if party_type in {"customer", "supplier", "loan"}:
        model = {"customer": Customer, "supplier": Supplier, "loan": FinanceLoan}[party_type]
        party = get_row(model, payload.get("party_id"))
        if party.branch_id not in (None, branch_id):
            raise FinanceError("الجهة والمستند يجب أن يكونا من نفس فرع العملية")
        party_id, party_name = party.id, getattr(party, "name", getattr(party, "party_name", ""))
    if party_type == "other" and not party_name:
        party_name = CATEGORIES[category][1]
    target = None
    if kind == "transfer":
        target = ledger.treasury(payload.get("target_account_id"), branch_id)
        if target.id == account.id:
            raise FinanceError("اختر حساب وجهة مختلفاً")
    on = day(payload.get("transaction_date") or today().isoformat())
    if on > today():
        raise FinanceError("لا تسجل حركة مالية فعلية بتاريخ مستقبلي")
    row = FinanceVoucher(tenant_key=tenant_key(), branch_id=branch_id, number=f"DRAFT-{uuid4().hex}",
        kind=kind, category=category, party_type=party_type, party_id=party_id, party_name=party_name,
        amount=money(payload.get("amount")), treasury_account_id=account.id if account else None,
        target_account_id=target.id if target else None, transaction_date=on, created_by=actor().id,
        notes=text(payload.get("notes"), 4000), payload=dumps(payload))
    db.session.add(row)
    db.session.flush()
    row.number = f"{ {'receipt':'RC','payment':'PY','transfer':'TR','settlement':'AC'}[kind] }-{row.id:06d}"
    if not internal:
        audit("create", "voucher", row)
    return row


def edit(row, payload):
    require("finance.create")
    version(row, payload)
    if row.status != "draft" or (actor().id != row.created_by and not can("finance.approve")):
        raise FinanceError("تعديل السند متاح كمسودة فقط", "conflict", 409)
    replacement = create({**json.loads(row.payload), **payload}, internal=True)
    for field in ("kind", "category", "party_type", "party_id", "party_name", "amount", "treasury_account_id", "branch_id",
                  "target_account_id", "transaction_date", "notes", "payload"):
        setattr(row, field, getattr(replacement, field))
    # Keep the original identity; the temporary validated draft was never posted.
    db.session.delete(replacement)
    row.number = f"{ {'receipt':'RC','payment':'PY','transfer':'TR','settlement':'AC'}[row.kind] }-{row.id:06d}"
    row.version += 1
    audit("edit", "voucher", row, {"version": row.version})
    return row


def decide(row, action, payload):
    version(row, payload)
    if action == "submit":
        require("finance.create")
        if row.status != "draft" or (row.created_by != actor().id and not can("finance.approve")):
            raise FinanceError("لا يمكن تقديم هذا السند", "conflict", 409)
        row.status = "pending"
    elif action in {"cancel", "reject"}:
        require("finance.approve" if action == "reject" else "finance.create")
        if row.status not in {"draft", "pending"} or (action == "cancel" and row.created_by != actor().id and not can("finance.approve")):
            raise FinanceError("السند المرحّل يُصحح بالعكس ولا يُلغى", "conflict", 409)
        reason = text(payload.get("reason"), 1000, True)
        row.status = "cancelled" if action == "cancel" else "rejected"
        audit(action, "voucher", row, {"reason": reason})
    elif action == "approve":
        approve(row)
        return row
    else:
        raise FinanceError("إجراء غير صالح")
    row.version += 1
    audit(action, "voucher", row)
    return row


def transaction(row, tx_type, amount, account_id=None):
    owner = row.category in {"capital", "owner_draw"}
    note = f"{CATEGORIES.get(row.category, ('', 'عكس سند'))[1]} — {row.number} [FV:{row.id}]"
    if not owner:
        note = "صندوق - حركة مالية: " + note
    tx = AccountTransaction(branch_id=row.branch_id, type=tx_type, amount=amount,
        note=note[:255], treasury_account_id=account_id or row.treasury_account_id,
        created_at=datetime.combine(row.transaction_date, datetime.min.time()))
    db.session.add(tx)
    db.session.flush()
    return tx


def allocation(row, kind, reference_id, amount, before=0, after=0):
    result = FinanceAllocation(voucher_id=row.id, reference_type=kind, reference_id=reference_id,
        amount=amount, before_amount=before, after_amount=after)
    db.session.add(result)
    return result


def expense(row, amount, title=None, category=None, noncash=False):
    record = Expense(branch_id=row.branch_id, title=text(title or row.party_name, 150, True),
        category=text(category or json.loads(row.payload).get("expense_category") or "other", 100),
        amount=amount, expense_date=row.transaction_date, treasury_account_id=row.treasury_account_id,
        cash_posted=True, note=f"{'غير نقدي: ' if noncash else ''}[FV:{row.id}] {row.number}", employee_id=actor().id)
    db.session.add(record)
    db.session.flush()
    allocation(row, "expense", record.id, abs(amount))
    return record


def outstanding_credit(party_type, party_id):
    role = "customer_advance" if party_type == "customer" else "supplier_advance"
    rows = scope(FinanceVoucher.query, FinanceVoucher).filter(FinanceVoucher.party_type == party_type,
        FinanceVoucher.party_id == party_id, FinanceVoucher.status.in_(["posted", "reversed"])).all()
    result = 0
    for row in rows:
        data = json.loads(row.payload)
        category = data.get("original_category", row.category)
        sign = -1 if row.category == "reversal" else 1
        if category == role:
            result += sign * row.amount
        elif category in {"customer_refund", "supplier_refund", "customer_credit_apply", "supplier_credit_apply"}:
            result -= sign * row.amount
    return max(0, result)


def invoice_payment(row, payload, *, offset=False):
    query = scope(Invoice.query, Invoice).filter(Invoice.customer_id == row.party_id,
        Invoice.status.notin_(list(CANCELED_STATUSES) + list(RETURN_STATUSES)), Invoice.total > func.coalesce(Invoice.paid_amount,0))
    invoices = query.order_by(Invoice.created_at, Invoice.id).with_for_update().all()
    invoice_map = {invoice.id: invoice for invoice in invoices}
    customer = get_row(Customer, row.party_id)
    debts = CustomerCreditPlan.query.filter(CustomerCreditPlan.customer_id == row.party_id,
        CustomerCreditPlan.invoice_id.is_(None), CustomerCreditPlan.total_amount > func.coalesce(CustomerCreditPlan.paid_amount, 0)
    ).order_by(CustomerCreditPlan.created_at, CustomerCreditPlan.id).with_for_update().all() if customer.branch_id == row.branch_id else []
    debt_map = {debt.id: debt for debt in debts}
    requested = payload.get("allocations") or []
    if requested:
        if not isinstance(requested, list) or len(requested) > 100:
            raise FinanceError("توزيع الفواتير غير صالح")
        plan, seen = [], set()
        for item in requested:
            if not isinstance(item, dict) or bool(item.get("invoice_id")) == bool(item.get("plan_id")):
                raise FinanceError("حدد فاتورة أو ديناً مستقلاً لكل تخصيص")
            amount = money(item.get("amount"))
            if item.get("plan_id"):
                plan_id = money(item.get("plan_id"))
                debt = debt_map.get(plan_id)
                if not debt or ("debt", plan_id) in seen or amount > debt.remaining:
                    raise FinanceError("الدين تغيّر أو مبلغ تخصيصه أكبر من المستحق", "conflict", 409)
                seen.add(("debt", plan_id))
                plan.append((debt, amount))
                continue
            invoice_id = money(item.get("invoice_id"))
            invoice = invoice_map.get(invoice_id)
            if not invoice or ("invoice", invoice_id) in seen or invoice.branch_id != row.branch_id or amount > invoice.total - (invoice.paid_amount or 0):
                raise FinanceError("إحدى الفواتير تغيّرت أو مبلغ تخصيصها أكبر من المستحق", "conflict", 409)
            seen.add(("invoice", invoice_id))
            plan.append((invoice, amount))
        if sum(amount for _, amount in plan) != row.amount:
            raise FinanceError("يجب أن يساوي مجموع التوزيع مبلغ السند")
    else:
        plan, remaining = [], row.amount
        for invoice in invoices:
            if invoice.branch_id != row.branch_id:
                continue
            amount = min(remaining, invoice.total - (invoice.paid_amount or 0))
            if amount:
                plan.append((invoice, amount))
            remaining -= amount
            if remaining == 0:
                break
        for debt in debts if remaining else []:
            amount = min(remaining, debt.remaining)
            if amount:
                plan.append((debt, amount))
            remaining -= amount
            if remaining == 0:
                break
        if remaining:
            raise FinanceError("المبلغ أكبر من المستحق؛ سجل الفائض كسند دفعة مقدمة صريح", "overpayment", 409)
    receipt = None
    payment_method = "finance_offset" if offset else "cash" if ledger.treasury(row.treasury_account_id, row.branch_id).account_type == "cash" else "bank"
    outstanding = sum(i.total-(i.paid_amount or 0) for i in invoices) + sum(p.remaining for p in debts)
    if not offset:
        receipt = Receipt(branch_id=row.branch_id, receipt_number=row.number, source_type="customer",
            source_id=row.party_id, source_name=row.party_name, amount=row.amount,
            treasury_account_id=row.treasury_account_id, receipt_date=row.transaction_date,
            payment_method=payment_method, allocation_method="manual", created_by=actor().id,
            status="معتمد", notes=row.notes, balance_before=outstanding,
            balance_after=outstanding-row.amount)
        db.session.add(receipt)
        db.session.flush()
        row.source_type, row.source_id = "receipt", receipt.id
    for invoice, amount in plan:
        if isinstance(invoice, CustomerCreditPlan):
            before = int(invoice.paid_amount or 0)
            customer_installments.collect_standalone(row, invoice, amount)
            allocation(row, "customer_debt", invoice.id, amount, before, invoice.paid_amount)
            if not offset:
                transaction(row, "deposit", amount)
            if receipt:
                db.session.add(ReceiptAllocation(receipt_id=receipt.id, reference_type="customer_debt",
                    reference_id=invoice.id, reference_label=f"دين مستقل #{invoice.id}", allocated_amount=amount))
            continue
        before = int(invoice.paid_amount or 0)
        customer_installments.collect(row, invoice, amount)
        # Preserve pre-ledger collections before creating the first attributed row.
        from modules.sales_returns.collections import for_invoice
        if before and not for_invoice(invoice.id) and not InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id).first():
            from utils.treasury_helpers import get_default_cash_account
            db.session.add(InvoicePaymentLedger(branch_id=invoice.branch_id, invoice_id=invoice.id,
                amount_delta=before, treasury_account_id=get_default_cash_account(invoice.branch_id).id,
                recorded_at=invoice.created_at, source_module="finance_legacy_baseline", payment_method="cash"))
        invoice.paid_amount = before + amount
        invoice.payment_status = "مسدد" if invoice.paid_amount == invoice.total else "جزئي"
        db.session.add(InvoicePaymentLedger(branch_id=invoice.branch_id, invoice_id=invoice.id,
            amount_delta=amount, treasury_account_id=row.treasury_account_id,
            recorded_at=datetime.combine(row.transaction_date, datetime.min.time()),
            source_module=f"finance:{row.id}", payment_method="finance_offset" if offset else payment_method, note=row.number))
        allocation(row, "invoice", invoice.id, amount, before, invoice.paid_amount)
        if receipt:
            db.session.add(ReceiptAllocation(receipt_id=receipt.id, reference_type="invoice", reference_id=invoice.id,
                reference_label=getattr(invoice, "invoice_no", None) or str(invoice.id), allocated_amount=amount))


def supplier_payment(row, payload, *, offset=False):
    supplier = get_row(Supplier, row.party_id)
    if row.amount > max(0, supplier.remaining):
        raise FinanceError("مبلغ الدفع أكبر من دين المورد", "overpayment", 409)
    from utils.supplier_payment_allocation import allocate_supplier_payment_fifo, backfill_supplier_payment_allocations, effective_purchase_payment_totals
    # Backfill within this transaction; never call the legacy helper that commits mid-operation.
    backfill_supplier_payment_allocations(supplier.id)
    before = supplier.total_paid or 0
    supplier.total_paid = before + row.amount
    payment = SupplierPayment(branch_id=row.branch_id, supplier_id=supplier.id, amount=row.amount,
        note=f"[FV:{row.id}] {row.number}", document_number=row.number, treasury_account_id=row.treasury_account_id,
        source_module="finance", payment_method="offset" if offset else "cash",
        created_at=datetime.combine(row.transaction_date, datetime.min.time()))
    db.session.add(payment)
    db.session.flush()
    requested = payload.get("allocations") or []
    if row.category == "inventory_purchase" and not requested:
        raise FinanceError("اختر فاتورة المشتريات المستلمة المطلوب دفعها")
    if requested:
        if len(requested) > 100 or sum(money(item.get("amount")) for item in requested) != row.amount:
            raise FinanceError("توزيع المشتريات يجب أن يساوي مبلغ السند")
        seen = set()
        for item in requested:
            purchase = get_row(Purchase, item.get("purchase_id"))
            amount = money(item.get("amount"))
            paid = effective_purchase_payment_totals(purchase)[0]
            total = purchase.grand_total or purchase.total or 0
            if purchase.supplier_id != supplier.id or purchase.branch_id != row.branch_id or purchase.id in seen or purchase.status in {"draft", "draft_editing", "cancelled", "canceled"} or amount > total - paid:
                raise FinanceError("فاتورة المشتريات غير مستحقة أو تغيّر رصيدها", "conflict", 409)
            seen.add(purchase.id)
            db.session.add(SupplierPaymentAllocation(supplier_payment_id=payment.id, purchase_id=purchase.id,
                allocation_type="purchase", target_key=f"purchase:{purchase.id}", amount=amount))
            allocation(row, "purchase", purchase.id, amount, paid, paid + amount)
    else:
        allocate_supplier_payment_fifo(payment, supplier=supplier, recorded_at=datetime.utcnow())
    allocation(row, "supplier_payment", payment.id, row.amount, before, supplier.total_paid)
    row.source_type, row.source_id = "supplier_payment", payment.id


def approve(row):
    require("finance.approve")
    if row.status not in {"draft", "pending"}:
        raise FinanceError("السند ليس بانتظار الترحيل", "already_posted", 409)
    rules = policy()
    if row.amount > rules["approval_limit"] and not can("finance.approve_large"):
        raise FinanceError("المبلغ يتجاوز حد اعتمادك؛ أرسله للمدير", "approval_limit", 403)
    if rules["separate_approval"] and row.amount >= rules["sensitive_threshold"] and row.created_by == actor().id:
        raise FinanceError("هذه العملية تحتاج اعتماد موظف مخول آخر", "separate_approval", 403)
    assert_date_period_open(row.transaction_date, "اعتماد السند")
    assert_date_period_open(today(), "اعتماد السند")
    payload = json.loads(row.payload)
    cash = ledger.treasury(row.treasury_account_id, row.branch_id) if row.treasury_account_id else None
    if row.kind in {"payment", "transfer"}:
        ledger.check_funds(cash, row.amount)
    row.approved_by = actor().id
    cash_gl = ledger.treasury_gl(cash) if cash else None
    category, amount = row.category, row.amount
    pairs, cash_handled = [], False
    if category == "customer_payment":
        invoice_payment(row, payload)
        pairs, cash_handled = [(cash_gl, ledger.account("receivable"), amount)], True
    elif category in {"customer_credit_apply", "supplier_credit_apply"}:
        if amount > outstanding_credit(row.party_type,row.party_id):
            raise FinanceError("تغيّر الرصيد المقدم؛ راجع المبلغ قبل الاعتماد", "overpayment",409)
        if row.party_type=="customer":
            invoice_payment(row,payload,offset=True)
            pairs=[(ledger.account("customer_advance"),ledger.account("receivable"),amount)]
        else:
            supplier_payment(row,payload,offset=True)
            pairs=[(ledger.account("payable"),ledger.account("supplier_advance"),amount)]
        cash_handled=True
    elif category in {"supplier_payment", "inventory_purchase"}:
        supplier_payment(row, payload)
        pairs, cash_handled = [(ledger.account("payable"), cash_gl, amount)], True
    elif category in {"loan_funding", "loan_grant", "employee_advance", "loan_payment", "loan_collection", "employee_return"}:
        from .loans import post_operation
        pairs = post_operation(row, payload, cash_gl)
    elif category == "account_transfer":
        target = ledger.treasury(row.target_account_id, row.branch_id)
        transfer = TreasuryTransfer(branch_id=row.branch_id, from_account_id=cash.id, to_account_id=target.id,
            amount=amount, note=row.number)
        db.session.add(transfer)
        db.session.flush()
        for kind, account_id in [("withdraw", cash.id), ("deposit", target.id)]:
            tx = transaction(row, kind, amount, account_id)
            tx.treasury_transfer_id = transfer.id
        row.source_type, row.source_id = "treasury_transfer", transfer.id
        pairs, cash_handled = [(ledger.treasury_gl(target), cash_gl, amount)], True
    elif category == "expense":
        record = expense(row, amount)
        row.source_type, row.source_id = "expense", record.id
        pairs = [(ledger.account("expense"), cash_gl, amount)]
    elif category == "expense_accrual":
        record=expense(row,amount,noncash=True)
        row.source_type,row.source_id="expense",record.id
        pairs,cash_handled=[(ledger.account("expense"),ledger.account("expense_payable"),amount)],True
    elif category == "interest_accrual":
        from .loans import post_interest_accrual
        pairs,cash_handled=post_interest_accrual(row,payload),True
    elif category == "accrued_expense":
        original = get_row(Expense, payload.get("expense_id"))
        if "HR-" in (original.note or "") or original.employee_payment_id:
            raise FinanceError("مستحقات الموظف تسدد من مسير الرواتب حتى تبقى دفعاته واستقطاعاته مرتبطة")
        if not original.cash_posted or "غير نقدي" not in (original.note or ""):
            raise FinanceError("اختر مصروفاً مستحقاً مثبتاً بمستند غير نقدي")
        already = sum(a.amount for a in FinanceAllocation.query.join(FinanceVoucher, FinanceVoucher.id == FinanceAllocation.voucher_id)
            .filter(FinanceAllocation.reference_type == "accrued_expense", FinanceAllocation.reference_id == original.id,
                    FinanceVoucher.status == "posted").all())
        if amount > original.amount - already:
            raise FinanceError("المبلغ أكبر من المصروف المستحق", "overpayment", 409)
        allocation(row, "accrued_expense", original.id, amount, already, already + amount)
        pairs = [(ledger.account("expense_payable"), cash_gl, amount)]
    elif category == "expense_refund":
        original = get_row(Expense, payload.get("expense_id"))
        if not original.cash_posted or original.amount <= 0:
            raise FinanceError("اختر مصروفاً أصلياً معتمداً")
        if original.employee_payment_id or "HR-" in (original.note or "") or original.category in {"loan_interest","loan_fees"}:
            raise FinanceError("صحح مصروف الراتب أو القرض من العملية المرتبطة به")
        refunded = sum(a.amount for a in FinanceAllocation.query.join(FinanceVoucher, FinanceVoucher.id == FinanceAllocation.voucher_id)
            .filter(FinanceAllocation.reference_type == "expense_refund", FinanceAllocation.reference_id == original.id,
                    FinanceVoucher.status == "posted").all())
        refundable=original.amount
        if "غير نقدي" in (original.note or ""):
            refundable=sum(a.amount for a in FinanceAllocation.query.join(FinanceVoucher,FinanceVoucher.id==FinanceAllocation.voucher_id).filter(
                FinanceAllocation.reference_type=="accrued_expense",FinanceAllocation.reference_id==original.id,FinanceVoucher.status=="posted").all())
        if amount > refundable - refunded:
            raise FinanceError("الاسترداد أكبر من المصروف المتبقي")
        allocation(row, "expense_refund", original.id, amount)
        expense(row, -amount, f"استرداد {original.title}")
        pairs = [(cash_gl, ledger.account("expense"), amount)]
    elif category == "fixed_asset":
        residual = money(payload.get("residual", 0), minimum=0)
        months = money(payload.get("asset_months", 36))
        if residual >= amount or months > 1200:
            raise FinanceError("تحقق من العمر والقيمة المتبقية للأصل")
        category_record = FixedAssetCategory.query.filter_by(id=money(payload.get("asset_category_id")), is_active=True).first()
        if not category_record or not category_record.asset_account or not category_record.asset_account.is_active:
            raise FinanceError("اختر فئة أصل فعالة مرتبطة بحساب محاسبي")
        asset = FixedAsset(branch_id=row.branch_id, asset_code=f"FA-FV-{row.id}", name=text(payload.get("asset_name") or row.party_name,150,True),
            category_id=category_record.id, purchase_price=amount, total_cost=amount, salvage_value=residual,
            useful_life_months=months, purchase_date=row.transaction_date, ready_date=row.transaction_date,
            status="active", payment_method="cash" if cash.is_cash else "bank", treasury_account_id=cash.id,
            paid_amount=amount, credit_amount=0, created_by=actor().id, book_value=amount,
            monthly_depreciation=(amount-residual)//months, accumulated_depreciation=0,
            is_depreciable=category_record.is_depreciable, depreciation_method="straight_line",
            asset_account_id=category_record.asset_account_id,
            accumulated_depreciation_account_id=category_record.accumulated_depreciation_account_id,
            depreciation_expense_account_id=category_record.depreciation_expense_account_id)
        db.session.add(asset)
        db.session.flush()
        row.source_type, row.source_id = "asset", asset.id
        pairs = [(category_record.asset_account, cash_gl, amount)]
    elif category in {"customer_advance", "supplier_advance", "capital", "owner_draw", "other_income"}:
        role = {"capital": "capital", "owner_draw": "owner_draw", "other_income": "other_revenue"}.get(category, category)
        pairs = [(cash_gl, ledger.account(role), amount)] if row.kind == "receipt" else [(ledger.account(role), cash_gl, amount)]
    elif category in {"customer_refund", "supplier_refund"}:
        if amount > outstanding_credit(row.party_type, row.party_id):
            raise FinanceError("الاسترجاع أكبر من رصيد الدفعات المقدمة")
        role = "customer_advance" if row.party_type == "customer" else "supplier_advance"
        pairs = [(ledger.account(role), cash_gl, amount)] if row.kind == "payment" else [(cash_gl, ledger.account(role), amount)]
    else:
        raise FinanceError("هذا السبب لا يملك معالجة مالية صالحة")
    if not cash_handled:
        tx = transaction(row, "deposit" if row.kind == "receipt" else "withdraw", amount)
        if row.category == "employee_advance":
            from modules.hr.models import HRAdvance
            loan = get_row(FinanceLoan, row.party_id)
            db.session.get(HRAdvance, loan.hr_advance_id).transaction_id = tx.id
    ledger.post(row, pairs)
    if row.source_type == "receipt":
        db.session.get(Receipt, row.source_id).journal_entry_id = ledger.entries(row)[0].id
    if row.source_type == "asset":
        db.session.get(FixedAsset, row.source_id).acquisition_journal_entry_id = ledger.entries(row)[0].id
    row.status, row.posting_date, row.approved_at = "posted", today(), datetime.utcnow()
    row.version += 1
    audit("post", "voucher", row, {"amount": amount, "category": category})
    return row


def reverse(row, payload):
    require("finance.reverse")
    version(row, payload)
    reason = text(payload.get("reason"), 1000, True)
    if row.status != "posted" or row.category == "reversal":
        raise FinanceError("السند غير قابل للعكس", "conflict", 409)
    from modules.sales_returns.funding import assert_source_reversible
    assert_source_reversible(row.id)
    if (row.source_type or "").endswith("_auto") or json.loads(row.payload).get("returned_invoice"):
        raise FinanceError("صحّح المستند الأصلي من شاشته حتى تتحدث الكميات والالتزامات مع القيد")
    assert_date_period_open(row.transaction_date, "عكس السند الأصلي")
    on = day(payload.get("transaction_date") or today().isoformat())
    if on > today():
        raise FinanceError("تاريخ العكس لا يمكن أن يكون مستقبلياً")
    assert_date_period_open(on, "عكس السند")
    assert_date_period_open(today(), "عكس السند")
    allocations = FinanceAllocation.query.filter_by(voucher_id=row.id).all()
    if row.source_type=="expense" and FinanceAllocation.query.join(FinanceVoucher,FinanceVoucher.id==FinanceAllocation.voucher_id).filter(
        FinanceAllocation.reference_type.in_(["accrued_expense","expense_refund"]),FinanceAllocation.reference_id==row.source_id,
        FinanceVoucher.status=="posted").first():
        raise FinanceError("المصروف عليه تسديد أو استرداد؛ اعكس العمليات التابعة أولاً", "dependency",409)
    if row.category=="accrued_expense":
        for item in allocations:
            if FinanceAllocation.query.join(FinanceVoucher,FinanceVoucher.id==FinanceAllocation.voucher_id).filter(
                FinanceAllocation.reference_type=="expense_refund",FinanceAllocation.reference_id==item.reference_id,FinanceVoucher.status=="posted").first():
                raise FinanceError("اعكس الاسترداد المرتبط قبل عكس تسديد المصروف", "dependency",409)
    if row.category in {"customer_advance", "supplier_advance"} and row.amount > outstanding_credit(row.party_type, row.party_id):
        raise FinanceError("الدفعة المقدمة مستخدمة؛ اعكس التسويات التابعة أولاً", "dependency", 409)
    if row.category == "fixed_asset" and (db.session.get(FixedAsset, row.source_id).accumulated_depreciation or
        db.session.get(FixedAsset, row.source_id).status in {"sold", "scrapped"}):
        raise FinanceError("الأصل عليه إهلاك؛ عالج الإهلاك قبل عكس الشراء", "dependency", 409)
    for item in allocations:
        if item.reference_type == "invoice":
            invoice = get_row(Invoice, item.reference_id)
            if invoice.status in list(CANCELED_STATUSES) + list(RETURN_STATUSES) or invoice.paid_amount < item.amount:
                raise FinanceError("الفاتورة عليها مرتجع أو تسوية تابعة؛ عالجها قبل العكس", "dependency", 409)
        if item.reference_type == "supplier_payment":
            payment = db.session.get(SupplierPayment, item.reference_id)
            supplier = get_row(Supplier, payment.supplier_id)
            if payment.deleted_at or supplier.total_paid < item.amount:
                raise FinanceError("دفعة المورد مرتبطة بتسوية أخرى", "dependency", 409)
    if row.party_type == "loan":
        from .loans import check_reversal
        check_reversal(row)
    credit_reversals = customer_installments.prepare_reversal(row, allocations)
    # Reversing incoming cash (or a transfer) must not overdraw its receiving account.
    if row.kind == "receipt":
        ledger.check_funds(ledger.treasury(row.treasury_account_id, row.branch_id), row.amount)
    elif row.kind == "transfer":
        ledger.check_funds(ledger.treasury(row.target_account_id, row.branch_id), row.amount)
    rev = FinanceVoucher(tenant_key=tenant_key(), branch_id=row.branch_id, number=f"REV-{uuid4().hex}",
        kind={"receipt":"payment", "payment":"receipt", "transfer":"transfer", "settlement":"settlement"}[row.kind],
        category="reversal", party_type=row.party_type, party_id=row.party_id, party_name=row.party_name,
        amount=row.amount, treasury_account_id=row.target_account_id if row.kind == "transfer" else row.treasury_account_id,
        target_account_id=row.treasury_account_id if row.kind == "transfer" else None,
        transaction_date=on, posting_date=today(), created_by=actor().id, approved_by=actor().id,
        payload=dumps({"original_category": row.category, "original_id": row.id}), notes=reason)
    db.session.add(rev)
    db.session.flush()
    rev.number = f"RV-{rev.id:06d}"
    handled = row.kind == "settlement"
    for item in allocations:
        if item.reference_type == "invoice":
            invoice = get_row(Invoice, item.reference_id)
            invoice.paid_amount -= item.amount
            invoice.payment_status = "جزئي" if invoice.paid_amount else "غير مسدد"
            db.session.add(InvoicePaymentLedger(branch_id=invoice.branch_id, invoice_id=invoice.id,
                amount_delta=-item.amount, treasury_account_id=row.treasury_account_id,
                payment_method="finance_offset" if row.kind == "settlement" else "cash" if ledger.treasury(row.treasury_account_id, row.branch_id).account_type == "cash" else "bank",
                source_module=f"finance:{rev.id}", note=rev.number, recorded_at=datetime.combine(on, datetime.min.time())))
            handled = True
        elif item.reference_type == "customer_debt":
            if row.kind != "settlement":
                transaction(rev, "withdraw", item.amount)
            handled = True
        elif item.reference_type == "supplier_payment":
            payment = db.session.get(SupplierPayment, item.reference_id)
            get_row(Supplier, payment.supplier_id).total_paid -= item.amount
            payment.deleted_at = datetime.utcnow()
            db.session.add(SupplierPayment(branch_id=row.branch_id, supplier_id=payment.supplier_id, amount=-item.amount,
                note=f"[FV:{rev.id}] عكس {row.number}", treasury_account_id=payment.treasury_account_id,
                payment_method=payment.payment_method, source_module="finance_reverse", created_at=datetime.combine(on, datetime.min.time())))
            handled = True
        elif item.reference_type == "expense":
            original = db.session.get(Expense, item.reference_id)
            expense(rev, -original.amount, f"عكس {original.title}", original.category, noncash=row.kind == "settlement")
    customer_installments.reverse(rev, credit_reversals)
    if row.source_type == "receipt":
        receipt = db.session.get(Receipt, row.source_id)
        receipt.status, receipt.cancelled_by, receipt.cancelled_at, receipt.cancel_reason = "ملغى", actor().id, datetime.utcnow(), reason
    if row.party_type == "loan":
        from .loans import apply_reversal
        apply_reversal(row)
    if row.source_type == "asset":
        db.session.get(FixedAsset, row.source_id).status = "draft"
        db.session.get(FixedAsset, row.source_id).acquisition_journal_entry_id = None
    if row.kind == "transfer":
        transaction(rev, "withdraw", row.amount, row.target_account_id)
        transaction(rev, "deposit", row.amount, row.treasury_account_id)
        handled = True
    if not handled:
        transaction(rev, "deposit" if rev.kind == "receipt" else "withdraw", rev.amount)
    ledger.post(rev, ledger.reverse_pairs(row))
    rev.status, rev.approved_at = "posted", datetime.utcnow()
    row.status, row.reversal_id = "reversed", rev.id
    row.version += 1
    audit("reverse", "voucher", row, {"reason": reason, "reversal_id": rev.id})
    return row


def apply_credit(payload):
    require("finance.create")
    party_type = payload.get("party_type")
    if party_type not in {"customer", "supplier"}:
        raise FinanceError("اختر نوع جهة صحيحاً")
    model = Customer if party_type == "customer" else Supplier
    party = get_row(model, payload.get("party_id"))
    amount = money(payload.get("amount"))
    on=day(payload.get("transaction_date") or today().isoformat())
    if on>today():
        raise FinanceError("التسوية لا تسجل بتاريخ مستقبلي")
    if amount > outstanding_credit(party_type, party.id):
        raise FinanceError("مبلغ التسوية أكبر من الرصيد المقدم", "overpayment", 409)
    branch_id = write_branch({**payload, "branch_id": party.branch_id})
    row = FinanceVoucher(tenant_key=tenant_key(), branch_id=branch_id, number=f"ST-{uuid4().hex}",
        kind="settlement", category=f"{party_type}_credit_apply", party_type=party_type,
        party_id=party.id, party_name=party.name, amount=amount, transaction_date=on,
        created_by=actor().id, approved_by=actor().id, payload=dumps(payload), notes=text(payload.get("notes"), 4000))
    db.session.add(row)
    db.session.flush()
    row.number = f"ST-{row.id:06d}"
    intent=payload.get("intent","post")
    if intent=="pending":
        decide(row,"submit",{"version":row.version})
    elif intent=="post":
        approve(row)
    elif intent!="draft":
        raise FinanceError("طريقة حفظ التسوية غير صالحة")
    audit("apply_credit", "voucher", row)
    return row


def serialize(row, *, details=False):
    from models.employee import Employee
    from models.treasury_account import TreasuryAccount
    treasury = db.session.get(TreasuryAccount, row.treasury_account_id) if row.treasury_account_id else None
    employee = db.session.get(Employee, row.created_by)
    labels={"reversal":"عكس سند","customer_credit_apply":"تسوية رصيد زبون","supplier_credit_apply":"تسوية رصيد مورد",
        "customer_debt_posting":"تسجيل رصيد دين مستقل","customer_debt_receipt":"تحصيل دين مستقل","customer_debt_payment":"تصحيح تحصيل دين مستقل",
        "invoice_receipt":"قبض فاتورة","invoice_payment":"استرجاع دفعة فاتورة","invoice_posting":"قيد فاتورة",
        "purchase_payment":"دفع مشتريات","purchase_receipt":"استرجاع دفع مشتريات","purchase_posting":"قيد مشتريات",
        "payroll_payment_payment":"دفع راتب","payroll_payment_receipt":"تصحيح دفع راتب","payroll_payment_posting":"قيد راتب",
        "supplier_payment_payment":"دفع مورد","supplier_payment_receipt":"تصحيح دفع مورد","supplier_payment_posting":"قيد مورد",
        "expense_payment":"دفع مصروف","expense_receipt":"تصحيح مصروف","expense_posting":"استحقاق مصروف",
        "transfer_posting":"تحويل حسابات","owner_transaction_posting":"تصحيح حقوق المالك"}
    result = {"id": row.id, "number": row.number, "kind": row.kind, "category": row.category,
        "category_label": CATEGORIES.get(row.category, ("", labels.get(row.category, "حركة مالية مرتبطة")))[1],
        "party_type": row.party_type, "party_id": row.party_id, "party_name": row.party_name,
        "amount": row.amount, "currency_code": row.currency_code, "exchange_rate": str(row.exchange_rate),
        "treasury_account_id": row.treasury_account_id, "account_name": treasury.name if treasury else "تسوية بدون حركة نقدية",
        "target_account_id": row.target_account_id, "branch_id": row.branch_id,
        "transaction_date": row.transaction_date.isoformat(), "status": row.status, "version": row.version,
        "created_by": row.created_by, "created_by_name": employee.name if employee else "", "approved_by": row.approved_by,
        "source_type": row.source_type, "source_id": row.source_id, "reversal_id": row.reversal_id, "notes": row.notes}
    if details:
        from .models import FinanceAttachment, FinanceAudit
        result["payload"] = json.loads(row.payload)
        result["allocations"] = [{"type": a.reference_type, "id": a.reference_id, "amount": a.amount,
            "before": a.before_amount, "after": a.after_amount} for a in FinanceAllocation.query.filter_by(voucher_id=row.id).all()]
        result["audit"] = [{"action": a.action, "created_by": a.created_by, "at": a.created_at.isoformat(),
            "details": json.loads(a.details)} for a in FinanceAudit.query.filter_by(source_type="voucher", source_id=row.id).order_by(FinanceAudit.id).all()]
        result["attachments"] = [{"id": a.id, "filename": a.filename} for a in FinanceAttachment.query.filter_by(source_type="voucher", source_id=row.id).all()]
        if can("finance.ledger"):
            result["journal"] = [{"id": e.id, "number": e.entry_number, "debit": e.debit_account.name,
                "credit": e.credit_account.name, "amount": e.amount} for e in ledger.entries(row)]
    return result
