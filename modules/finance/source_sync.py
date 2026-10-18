"""Incremental posting of existing source documents, in their original transaction.

Activation requires the reviewed opening migration. Cursors suppress historical
reposting, and rollback discards both source changes and their journal entries.
"""
import json
from datetime import datetime
from uuid import uuid4
from flask import g, has_app_context, has_request_context
from sqlalchemy import event, inspect, func, update
from sqlalchemy.orm import Session
from extensions import db
from models.invoice import Invoice
from models.customer import Customer
from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment
from models.order_item import OrderItem
from models.purchase import Purchase
from models.purchase_payment import PurchasePayment
from models.expense import Expense
from models.invoice_payment_ledger import InvoicePaymentLedger
from models.treasury_account import TreasuryAccount
from models.supplier_payment import SupplierPayment
from models.account_transaction import AccountTransaction
from models.treasury_transfer import TreasuryTransfer
from models.employee_payment import EmployeePayment
from models.journal_entry import JournalEntry
from models.inventory_lot import OrderItemCostLayer
from .common import dumps, today, tenant_key
from .models import FinanceSourceState, FinancePolicy, FinanceVoucher, FinanceJournalLink
from . import ledger

MODELS={"invoice":Invoice,"customer_debt":CustomerCreditPlan,"purchase":Purchase,"expense":Expense,"supplier_payment":SupplierPayment,"owner_transaction":AccountTransaction,"transfer":TreasuryTransfer,"payroll_payment":EmployeePayment}
_installed=False


def posting_actor_id():
    from utils.permission_checks import get_current_employee
    employee=get_current_employee() if has_request_context() else None
    if employee and employee.is_active:
        return employee.id
    # Public storefront and background imports have no staff session. Their
    # automatic entries use a disabled service identity, never a human approver.
    from models.employee import Employee
    identity=Employee.query.execution_options(skip_branch_scope=True).filter_by(
        username="__finora_finance_system__",role="system",is_active=False).first()
    if not identity:
        from werkzeug.security import generate_password_hash
        from secrets import token_urlsafe
        identity=Employee(username="__finora_finance_system__",name="ترحيل FINORA التلقائي",role="system",
            password=generate_password_hash(token_urlsafe(48)),is_active=False)
        db.session.add(identity);db.session.flush()
    return identity.id


def enabled(session):
    if not has_app_context() or not getattr(g,"tenant",None):
        return False
    # Check on the session connection: independent inspection connections can
    # rollback in-memory SQLite transactions owned by another session.
    if not inspect(session.connection()).has_table("finance_policy"):
        return False
    row=session.get(FinancePolicy,1)
    return bool(row and json.loads(row.settings).get("ledger_live"))


def snapshot(kind,row):
    if not row:
        return {}
    if kind=="customer_debt":
        return {} if row.invoice_id else {"principal":int(row.total_amount),"paid":int(row.paid_amount or 0),"customer_id":row.customer_id}
    if kind=="payroll_payment":
        # HR workspace owns its payroll/commission journals. Legacy cash payroll
        # has only an Expense and must be recognized once here.
        managed=(row.voucher_code or "").startswith(("HRP-","HRC-"))
        return {"paid":0 if managed else int(row.amount or 0),"account_id":row.treasury_account_id}
    if kind=="supplier_payment":
        managed=(row.source_module or "").startswith("finance")
        return {"paid":int(row.amount) if not managed and not row.deleted_at and row.payment_method!="offset" else 0,"account_id":row.treasury_account_id}
    if kind=="owner_transaction":
        owner=not row.treasury_transfer_id and "[FV:" not in (row.note or "") and "[CP:" not in (row.note or "") and "HR-" not in (row.note or "") and (row.is_owner_deposit() or row.is_owner_withdrawal())
        return {"amount":int(row.amount)*(1 if row.type=="deposit" else -1) if owner else 0,"account_id":row.treasury_account_id}
    if kind=="transfer":
        managed=FinanceVoucher.query.filter_by(source_type="treasury_transfer",source_id=row.id).first() is not None
        return {"amount":0 if managed else row.amount,"from":row.from_account_id,"to":row.to_account_id}
    if kind=="invoice":
        from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES
        from utils.accounting_calculations import invoice_cogs_by_ids
        booked=row.status not in list(CANCELED_STATUSES)+list(RETURN_STATUSES) and (row.stock_is_deducted or (row.paid_amount or 0)>0 or row.payment_status in {"مسدد","جزئي","مسدد جزئي"} or row.status in {"تم التوصيل","جاري الشحن","قيد الشحن","مسدد"})
        entries=InvoicePaymentLedger.query.filter_by(invoice_id=row.id).all()
        amounts={}
        for entry in entries:
            key=f"{entry.treasury_account_id or getattr(row,'treasury_account_id',None) or 0}:{'offset' if entry.payment_method=='finance_offset' else 'cash'}"
            amounts[key]=amounts.get(key,0)+entry.amount_delta
        from modules.sales_returns.collections import for_invoice
        undated = for_invoice(row.id)
        if undated:
            amounts["0:cash"]=amounts.get("0:cash",0)+undated["amount"]
        elif not entries:
            amounts[f"{getattr(row,'treasury_account_id',None) or 0}:cash"]=int(row.paid_amount or 0)
        return {"sale":int(row.total or 0) if booked else 0,"cogs":invoice_cogs_by_ids([row.id]).get(row.id,0) if booked else 0,"payments":amounts}
    if kind=="purchase":
        booked=not row.deleted_at and row.status not in {"draft","draft_editing","cancelled","canceled"} and not row.is_draft
        payments={}
        records=PurchasePayment.query.filter_by(purchase_id=row.id).all()
        methods={"cash","صندوق","نقدي","bank","bank_transfer","transfer","card","بنك","تحويل بنكي","بطاقة"}
        if booked:
            for payment in records:
                if (payment.payment_method or "").strip().lower() in methods:
                    key=str(payment.treasury_account_id or 0)
                    payments[key]=payments.get(key,0)+int(payment.amount or 0)
            if not records and (row.purchase_mode or "cash").strip().lower() in methods:
                payments["0"]=int(row.paid_total or 0)
        return {"inventory":int(row.grand_total or row.total or 0) if booked else 0,"payments":payments}
    excluded="[FV:" in (row.note or "") or "HR-" in (row.note or "") or row.employee_payment_id
    return {"expense":int(row.amount or 0) if row.cash_posted and not excluded else 0,"account_id":row.treasury_account_id,"noncash":"غير نقدي" in (row.note or "")}


def seed_existing():
    for kind,model in MODELS.items():
        for row in model.query.yield_per(200):
            key=f"{kind}:{row.id}"
            cursor=db.session.get(FinanceSourceState,key)
            if not cursor:
                db.session.add(FinanceSourceState(key=key,snapshot=dumps(snapshot(kind,row))))


def seed_customer_debts():
    from .standalone_debts import plans
    for row in plans():
        key=f"customer_debt:{row.id}"
        if not db.session.get(FinanceSourceState,key):
            db.session.add(FinanceSourceState(key=key,snapshot=dumps(snapshot("customer_debt",row))))


def cash(account_id,branch_id):
    account=db.session.get(TreasuryAccount,int(account_id)) if account_id else TreasuryAccount.query.filter_by(branch_id=branch_id,is_default=True).first()
    if not account:
        from .common import FinanceError
        raise FinanceError("اربط صندوق الفرع قبل ترحيل المستند", "account_required",409)
    return ledger.treasury_gl(account)


def synchronize(kind,row_id,deleted=None):
    row=db.session.get(MODELS[kind],row_id)
    source=row or deleted
    if not source:
        return
    from models.branch import Branch
    branch_id=getattr(source,"branch_id",None)
    if kind=="customer_debt":
        if source.invoice_id:
            from .common import FinanceError
            cursor=db.session.get(FinanceSourceState,f"customer_debt:{row_id}")
            if cursor and json.loads(cursor.snapshot):
                raise FinanceError("لا يمكن تحويل دين مستقل معتمد إلى فاتورة؛ راجع المصدر أولاً", "immutable_source",409)
            return
        from .common import FinanceError, policy
        if not policy().get("standalone_debts_reviewed"):
            raise FinanceError("اعتمد الديون المستقلة من إعدادات الحسابات قبل تعديلها أو تسديدها", "opening_review",409)
        customer=db.session.get(Customer,source.customer_id)
        branch_id=customer.branch_id if customer else None
        if not branch_id:
            raise FinanceError("اربط العميل بفرع قبل ترحيل الدين", "branch_required",409)
    if branch_id is None:
        treasury_id=getattr(source,"treasury_account_id",None)
        treasury=db.session.get(TreasuryAccount,treasury_id) if treasury_id else None
        branch=Branch.query.filter_by(is_default=True,is_active=True).first()
        branch_id=treasury.branch_id if treasury else branch.id if branch else None
    if branch_id is None:
        from .common import FinanceError
        raise FinanceError("اربط المستند بفرع قبل ترحيله", "branch_required",409)
    key=f"{kind}:{row_id}"
    cursor=db.session.get(FinanceSourceState,key)
    before=json.loads(cursor.snapshot) if cursor else {}
    after=snapshot(kind,row)
    if before==after:
        return
    if not cursor and row and kind in {"expense","purchase"}:
        from utils.financial_period_guard import assert_date_period_open
        document_date=row.expense_date if kind=="expense" else row.purchase_date
        if document_date:
            assert_date_period_open(document_date,"ترحيل المستند المرتبط")
    pairs=[]
    cash_posts=[]
    def delta(amount,debit,credit):
        if amount and debit.id!=credit.id:
            pairs.append((debit,credit,amount) if amount>0 else (credit,debit,-amount))
    managed=bool(getattr(g,"finance_operation",False))
    amount=0
    if kind=="customer_debt":
        if row:
            from .customer_installments import standalone_schedule
            standalone_schedule(row)
            if not cursor and row.paid_amount:
                from .common import FinanceError
                raise FinanceError("الدين المضاف يحتوي دفعات سابقة؛ راجع مصدرها قبل الترحيل", "opening_review",409)
        if before and before.get("customer_id")!=after.get("customer_id") and row:
            from .common import FinanceError
            raise FinanceError("لا يمكن نقل دين معتمد إلى عميل آخر", "immutable_source",409)
        if not row and before.get("paid",0):
            from .common import FinanceError
            raise FinanceError("الدين عليه تسديدات؛ اعكس السندات قبل حذفه", "dependency",409)
        delta(after.get("principal",0)-before.get("principal",0),ledger.account("receivable"),ledger.account("opening_equity"))
        change=after.get("paid",0)-before.get("paid",0)
        if change and not managed:
            from utils.branch_mode import independent_branches_enabled
            query=TreasuryAccount.query.execution_options(skip_branch_scope=True).filter_by(
                account_type="cash",is_active=True)
            if independent_branches_enabled():
                query=query.filter_by(branch_id=branch_id)
            treasury=query.order_by(TreasuryAccount.is_default.desc(),TreasuryAccount.id).first()
            if not treasury:
                from .common import FinanceError
                raise FinanceError("اربط صندوق الفرع قبل ترحيل الدين", "account_required",409)
            debit,credit=ledger.treasury_gl(treasury),ledger.account("receivable")
            pair=(debit,credit,change) if change>0 else (credit,debit,-change)
            cash_posts.append((change,treasury.id,[pair],None))
    elif kind=="invoice":
        delta(after.get("sale",0)-before.get("sale",0),ledger.account("receivable"),ledger.account("revenue"))
        delta(after.get("cogs",0)-before.get("cogs",0),ledger.account("cogs"),ledger.account("inventory"))
        old,new=before.get("payments",{}),after.get("payments",{})
        for payment in sorted(set(old)|set(new)):
            change=new.get(payment,0)-old.get(payment,0)
            if not change or managed:
                continue
            account_id,method=payment.split(":")
            if method=="offset":
                delta(change,ledger.account("customer_advance"),ledger.account("receivable"))
                if change<0:
                    # Return restores the customer's advance, with no cash refund.
                    credit=FinanceVoucher(tenant_key=tenant_key(),branch_id=branch_id,number=f"CR-{uuid4().hex}",kind="settlement",category="customer_advance",party_type="customer",party_id=source.customer_id,party_name=source.customer_name,amount=-change,transaction_date=today(),posting_date=today(),status="posted",created_by=posting_actor_id(),approved_by=posting_actor_id(),payload=dumps({"returned_invoice":row_id}),source_type="invoice",source_id=row_id)
                    db.session.add(credit)
            else:
                # Existing receipt services may already own the exact collection journal.
                from models.receipt import Receipt
                latest=InvoicePaymentLedger.query.filter_by(invoice_id=row_id).order_by(InvoicePaymentLedger.id.desc()).first()
                receipt_id=(latest.source_module or "").removeprefix("receipts:") if latest and (latest.source_module or "").startswith("receipts:") else ""
                existing=db.session.get(Receipt,int(receipt_id)) if receipt_id.isdigit() else None
                debit,credit=cash(int(account_id),branch_id),ledger.account("receivable")
                pair=(debit,credit,change) if change>0 else (credit,debit,-change)
                owned_entry=(existing.journal_entry_id if change>0 else existing.reverse_journal_entry_id) if existing else None
                cash_posts.append((change,int(account_id),[pair],owned_entry))
    elif kind=="purchase":
        delta(after.get("inventory",0)-before.get("inventory",0),ledger.account("inventory"),ledger.account("payable"))
        old=before.get("payments",{"0":before.get("paid",0)})
        new=after.get("payments",{})
        for account_id in set(old)|set(new):
            change=new.get(account_id,0)-old.get(account_id,0)
            if change and not managed:
                debit,credit=ledger.account("payable"),cash(int(account_id),branch_id)
                pair=(debit,credit,change) if change>0 else (credit,debit,-change)
                cash_posts.append((-change,int(account_id),[pair],None))
    elif kind in {"supplier_payment","payroll_payment"}:
        amount=after.get("paid",0)-before.get("paid",0)
        if before.get("account_id")!=after.get("account_id"):
            if before.get("paid",0):
                delta(-before["paid"],ledger.account("salary_expense" if kind=="payroll_payment" else "payable"),cash(before.get("account_id"),branch_id))
            if after.get("paid",0):
                delta(after["paid"],ledger.account("salary_expense" if kind=="payroll_payment" else "payable"),cash(after.get("account_id"),branch_id))
        elif amount:
            delta(amount,ledger.account("salary_expense" if kind=="payroll_payment" else "payable"),cash(after.get("account_id") or before.get("account_id"),branch_id))
    elif kind=="owner_transaction":
        old,new=before.get("amount",0),after.get("amount",0)
        for value,sign,account_id in ((old,-1,before.get("account_id")),(new,1,after.get("account_id"))):
            if value:
                if value>0:
                    delta(sign*value,cash(account_id,branch_id),ledger.account("capital"))
                else:
                    delta(-sign*value,ledger.account("owner_draw"),cash(account_id,branch_id))
        amount=new-old
    elif kind=="transfer":
        for value,sign in ((before,-1),(after,1)):
            if value.get("amount"):
                delta(sign*value["amount"],cash(value["to"],branch_id),cash(value["from"],branch_id))
        amount=0
    else:
        amount=after.get("expense",0)-before.get("expense",0)
        moved=before.get("account_id")!=after.get("account_id") or bool(before.get("noncash"))!=bool(after.get("noncash"))
        if moved:
            for value,sign in ((before,-1),(after,1)):
                if value.get("expense",0):
                    opposite=ledger.account("expense_payable") if value.get("noncash") else cash(value.get("account_id"),branch_id)
                    delta(sign*value["expense"],ledger.account("expense"),opposite)
        elif amount:
            opposite=ledger.account("expense_payable") if after.get("noncash",before.get("noncash")) else cash(after.get("account_id") or before.get("account_id"),branch_id)
            delta(amount,ledger.account("expense"),opposite)
    if pairs:
        from utils.financial_period_guard import assert_date_period_open
        on=today()
        assert_date_period_open(on,"ترحيل المستند المرتبط")
        has_cash=bool(amount) and not managed and not (kind=="expense" and after.get("noncash",before.get("noncash")))
        incoming=(amount>0) if kind in {"invoice","owner_transaction"} else (amount<0)
        category=f"{kind}_{'receipt' if incoming else 'payment'}" if has_cash else f"{kind}_posting"
        if kind=="owner_transaction" and has_cash:
            category="capital" if incoming else "owner_draw"
        voucher=FinanceVoucher(tenant_key=tenant_key(),branch_id=branch_id,number=f"SRC-{uuid4().hex[:16]}",kind=("receipt" if incoming else "payment") if has_cash else "settlement",category=category,party_type="other",party_name=getattr(source,"customer_name",getattr(source,"title",f"{kind} #{row_id}")),amount=abs(amount) if has_cash else sum(p[2] for p in pairs),treasury_account_id=getattr(source,"treasury_account_id",None),transaction_date=on,posting_date=on,status="posted",created_by=posting_actor_id(),approved_by=posting_actor_id(),source_type=f"{kind}_auto",source_id=row_id,payload=dumps({"before":before,"after":after}),notes="مرحّل تلقائياً من المستند الأصلي")
        db.session.add(voucher)
        if kind=="customer_debt":
            voucher.party_type, voucher.party_id, voucher.party_name = "customer", source.customer_id, customer.name
        elif kind=="invoice":
            voucher.party_type, voucher.party_id = "customer", source.customer_id
        db.session.flush()
        ledger.post(voucher,pairs)
        from .common import audit
        audit("source.post","voucher",voucher,{"source_type":kind,"source_id":row_id,"before":before,"after":after},created_by=voucher.created_by)
    for signed,account_id,posting,existing_entry in cash_posts:
        from utils.financial_period_guard import assert_date_period_open
        from .common import audit
        assert_date_period_open(today(),"ترحيل المستند المرتبط")
        treasury=db.session.get(TreasuryAccount,account_id) if account_id else TreasuryAccount.query.filter_by(
            branch_id=branch_id,is_default=True,is_active=True).first()
        party_type="customer" if kind in {"invoice","customer_debt"} else "supplier"
        party_id=source.customer_id if kind in {"invoice","customer_debt"} else source.supplier_id
        voucher=FinanceVoucher(tenant_key=tenant_key(),branch_id=branch_id,number=f"SRC-{uuid4().hex[:16]}",
            kind="receipt" if signed>0 else "payment",category=f"{kind}_{'receipt' if signed>0 else 'payment'}",
            party_type=party_type,party_id=party_id,party_name=customer.name if kind=="customer_debt" else getattr(source,"customer_name",f"مشتريات #{row_id}"),
            amount=abs(signed),treasury_account_id=treasury.id if treasury else None,transaction_date=today(),posting_date=today(),
            status="posted",created_by=posting_actor_id(),approved_by=posting_actor_id(),source_type=f"{kind}_auto",source_id=row_id,
            payload=dumps({"before":before,"after":after}),notes="حركة من المستند الأصلي؛ لا يتكرر مصدر النقد")
        db.session.add(voucher);db.session.flush()
        if existing_entry:
            db.session.add(FinanceJournalLink(voucher_id=voucher.id,journal_entry_id=existing_entry))
        else:
            ledger.post(voucher,posting)
        audit("source.post","voucher",voucher,{"source_type":kind,"source_id":row_id},created_by=voucher.created_by)
    if cursor:
        cursor.snapshot=dumps(after)
    else:
        db.session.add(FinanceSourceState(key=key,snapshot=dumps(after)))


def collect(session,flush_context,instances):
    if session.info.get("finance_syncing"):
        return
    guard_managed_sources(session)
    if not enabled(session):
        return
    pending=session.info.setdefault("finance_sources",{})
    for row in list(session.new)+list(session.dirty)+list(session.deleted):
        if isinstance(row,CustomerCreditPlan) and row in session.dirty and inspect(row).attrs.invoice_id.history.has_changes():
            previous=session.query(CustomerCreditPlan.invoice_id).filter(CustomerCreditPlan.id==row.id).scalar()
            if previous!=row.invoice_id:
                from .common import FinanceError
                raise FinanceError("لا يمكن تغيير ربط خطة دين بعد تفعيل الترحيل؛ راجع المصدر أولاً", "immutable_source",409)
        for kind,model in MODELS.items():
            if isinstance(row,model):
                pending[id(row)]=(kind,row,row in session.deleted)
                break
        if isinstance(row,(OrderItem,InvoicePaymentLedger)) and row.invoice_id:
            invoice=session.get(Invoice,row.invoice_id)
            if invoice:
                pending[id(invoice)]=("invoice",invoice,False)
        if isinstance(row,PurchasePayment) and row.purchase_id:
            purchase=session.get(Purchase,row.purchase_id)
            if purchase:
                pending[id(purchase)]=( "purchase",purchase,False)
        if isinstance(row,OrderItemCostLayer):
            item=session.get(OrderItem,row.order_item_id) if row.order_item_id else row.order_item
            invoice=session.get(Invoice,item.invoice_id) if item and item.invoice_id else None
            if invoice:
                pending[id(invoice)]=("invoice",invoice,False)


def commit(session):
    # Releasing a stock-movement SAVEPOINT does not commit the business
    # transaction. Defer source posting and its guard to the outer commit.
    if session.in_nested_transaction():
        return
    if session.info.get("finance_atomic") and not session.info.get("finance_commit_allowed"):
        from .common import FinanceError
        raise FinanceError("تعذر إكمال العملية كوحدة واحدة؛ تهيئة الحسابات يجب أن تسبق الترحيل", "atomicity_guard",409)
    if session.info.get("finance_syncing") or not enabled(session):
        return
    session.flush()
    session.info["finance_syncing"]=True
    try:
        session.execute(update(FinancePolicy).where(FinancePolicy.id==1).values(revision=FinancePolicy.revision+1))
        pending=session.info.pop("finance_sources",{})
        for kind,row,deleted in pending.values():
            if row.id:
                synchronize(kind,row.id,row if deleted else None)
    finally:
        session.info["finance_syncing"]=False


def clear(session,*args):
    if session.in_nested_transaction():
        return
    session.info.pop("finance_sources",None)


def guard_managed_sources(session):
    if not has_app_context() or not getattr(g,"tenant",None):
        return
    from modules.sales_returns.guards import guard_sources
    guard_sources(session)
    from models.customer_schedule_payment_link import CustomerSchedulePaymentLink
    for row in list(session.dirty) + list(session.deleted):
        if isinstance(row, CustomerSchedulePaymentLink) and (row in session.deleted or session.is_modified(row, include_collections=False)):
            from .common import FinanceError
            raise FinanceError("ربط التحصيل السابق محفوظ؛ لا يمكن تعديله أو حذفه", "immutable_source", 409)
    if getattr(g,"finance_operation",False):
        return
    from models.supplier_payment import SupplierPayment
    from models.receipt import Receipt, ReceiptAllocation
    from models.supplier_payment_allocation import SupplierPaymentAllocation
    from models.fixed_asset import FixedAsset
    from .common import FinanceError
    candidates=list(session.dirty)+list(session.deleted)
    if not candidates or not inspect(session.connection()).has_table("financial_vouchers"):
        return
    for row in candidates:
        managed=False
        def old_values(name):
            return [getattr(row,name),*inspect(row).attrs[name].history.deleted]
        if isinstance(row,Expense):
            managed=any("[FV:" in (value or "") for value in old_values("note"))
        elif isinstance(row,SupplierPayment):
            managed=any((value or "").startswith("finance") for value in old_values("source_module")) or SupplierPaymentAllocation.query.filter(
                SupplierPaymentAllocation.supplier_payment_id==row.id,
                SupplierPaymentAllocation.allocation_type.in_(["opening_credit","opening_settled"])).first() is not None
        elif isinstance(row,SupplierPaymentAllocation):
            managed=any(value in {"opening_credit","opening_settled"} for value in old_values("allocation_type"))
        elif isinstance(row,(Receipt,ReceiptAllocation)):
            receipt_id=row.id if isinstance(row,Receipt) else row.receipt_id
            managed=FinanceVoucher.query.filter_by(source_type="receipt",source_id=receipt_id).first() is not None
        elif isinstance(row,FinanceVoucher):
            history=inspect(row).attrs.status.history
            previous=history.deleted[0] if history.deleted else row.status
            managed=previous in {"posted","reversed"}
        elif isinstance(row,AccountTransaction):
            managed=any("[FV:" in (value or "") or "[CP:" in (value or "") for value in old_values("note"))
        elif isinstance(row,CustomerCreditPayment):
            managed=any("[FV:" in (value or "") for value in old_values("note")) or AccountTransaction.query.filter(
                AccountTransaction.note.like(f"%[CP:{row.id}]%")).first() is not None
            if managed and (row.note or "").startswith("[FV:"):
                from .customer_installments import is_reversed_invoice_archive
                if is_reversed_invoice_archive(session, row):
                    managed=False
        elif isinstance(row,CustomerCreditPlan) and row in session.deleted:
            from .models import FinanceAllocation
            managed=FinanceAllocation.query.filter_by(reference_type="customer_debt",reference_id=row.id).first() is not None
        elif isinstance(row,JournalEntry):
            managed=row.reference_type in {"finance_opening", "inventory_count", "inventory_writeoff"} or FinanceJournalLink.query.filter_by(journal_entry_id=row.id).first() is not None
        elif isinstance(row,TreasuryTransfer):
            managed=FinanceVoucher.query.filter_by(source_type="treasury_transfer",source_id=row.id).first() is not None
        elif isinstance(row,FixedAsset):
            original=FinanceVoucher.query.filter_by(source_type="asset",source_id=row.id).first()
            protected=("status","total_cost","paid_amount","credit_amount","treasury_account_id","acquisition_journal_entry_id","asset_account_id")
            managed=bool(original and any(inspect(row).attrs[name].history.has_changes() for name in protected))
        if managed and (row in session.deleted or session.is_modified(row,include_collections=False)):
            raise FinanceError("السجل مرتبط بسند مرحّل؛ استخدم عكس السند من الحسابات لحفظ الأثر المحاسبي", "immutable_source",409)


def install():
    global _installed
    if _installed:
        return
    event.listen(Session,"before_flush",collect)
    event.listen(Session,"before_commit",commit)
    event.listen(Session,"after_rollback",clear)
    event.listen(Session,"after_commit",clear)
    _installed=True
