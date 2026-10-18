"""Explicit, reviewable opening adjustments in FINORA's existing general ledger."""
import hashlib
import json
from datetime import datetime
from uuid import uuid4
from extensions import db
from models.invoice import Invoice
from models.supplier import Supplier
from models.product import Product
from models.treasury_account import TreasuryAccount
from models.journal_entry import JournalEntry
from modules.hr.models import HRAdvance, HRPayrollItem, HRPayrollRun
from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES
from utils.treasury_calculations import calculate_treasury_balance
from utils.branch_scope import is_general_admin
from . import ledger, loans, vouchers
from .common import DEFAULT_ACCOUNTS, FinanceError, actor, audit, dumps, policy, require, today
from .models import FinanceLoan, FinancePolicy, FinanceMapping


def receivable_target():
    from utils.accounting_calculations import booked_sale_filter
    from .standalone_debts import plans
    excluded=list(CANCELED_STATUSES)+list(RETURN_STATUSES)
    return (sum(max(0,int(i.total or 0)-int(i.paid_amount or 0)) for i in Invoice.query.filter(
        Invoice.status.notin_(excluded),booked_sale_filter()).all())
        + sum(max(0,p.total_amount-int(p.paid_amount or 0)) for p in plans()))


def targets(*, read_only=False):
    rows=[]
    def add(key,target):
        account=ledger.account(key)
        current=int(account.balance)
        rows.append({"key":key,"name":account.name,"current":current,"target":int(target),"difference":int(target)-current})
        if read_only:
            rows[-1].update(account_ids=[account.id], type=DEFAULT_ACCOUNTS[key][2] if key in DEFAULT_ACCOUNTS else "asset")
    from utils.branch_mode import independent_branches_enabled
    from utils.treasury_helpers import get_default_cash_account
    shared=not independent_branches_enabled()
    default_cash=get_default_cash_account() if shared else None
    for account in TreasuryAccount.query.order_by(TreasuryAccount.id).all():
        if shared and account.is_cash and account.id!=default_cash.id:
            continue
        if read_only:
            mapping=db.session.get(FinanceMapping,f"treasury:{account.id}")
            current=int(mapping.account.balance) if mapping else None
            target=int(calculate_treasury_balance(account.id))
            rows.append({"key":f"treasury:{account.id}","name":account.name,"current":current,"target":target,
                "difference":target-current if current is not None else None,"type":"asset",
                "account_ids":[mapping.account_id] if mapping else [], "treasury_account_id":account.id,
                "treasury_type":account.account_type})
            continue
        gl=ledger.treasury_gl(account)
        add(f"treasury:{account.id}",calculate_treasury_balance(account.id))
    receivables=receivable_target()
    if read_only:
        from utils.accounting_calculations import calculate_shipping_opening_balance
        receivables += calculate_shipping_opening_balance()
    add("receivable",receivables)
    suppliers=Supplier.query.all()
    add("payable",sum(max(0,s.remaining) for s in suppliers))
    add("supplier_advance",sum(max(0,-s.remaining)+vouchers.outstanding_credit("supplier",s.id) for s in suppliers))
    from models.customer import Customer
    from .opening_credits import customer_total
    add("customer_advance",sum(vouchers.outstanding_credit("customer",c.id) for c in Customer.query.all())+customer_total())
    advances=HRAdvance.query.filter(HRAdvance.status.in_(["paid","repaying","repaid"])).all()
    add("employee_advance",sum(max(0,a.amount-a.repaid) for a in advances))
    add("salary_payable",sum(max(0,i.net-i.paid) for i in HRPayrollItem.query.join(HRPayrollRun).filter(HRPayrollRun.status.in_(["approved","paid","partially_paid"])).all()))
    for direction,key in (("borrowed","loan_payable"),("lent","loan_receivable")):
        add(key,sum(loans.remaining(row)["principal"] for row in FinanceLoan.query.filter_by(direction=direction,status="active").all()))
    # FIFO lots carry the same valuation used by existing inventory reports.
    from utils.accounting_calculations import calculate_inventory_value
    add("inventory",calculate_inventory_value())
    if read_only:
        # Repeated branch cash/bank definitions must remain distinguishable in
        # the physical-count form; a name alone does not identify an account.
        from models.branch import Branch
        from collections import Counter
        treasuries = [row for row in rows if "treasury_account_id" in row]
        names = Counter(row["name"] for row in treasuries)
        for row in treasuries:
            if names[row["name"]] > 1:
                account = db.session.get(TreasuryAccount, row["treasury_account_id"])
                branch = db.session.get(Branch, account.branch_id) if account.branch_id else None
                row["name"] += f" · {branch.name if branch else 'غير منسوب لفرع'} · #{account.id}"
    return rows


def preview():
    require("finance.settings")
    if not is_general_admin(actor()):
        raise FinanceError("مراجعة الأرصدة الافتتاحية تخص مدير الشركة", "forbidden",403)
    complete=bool(policy().get("opening_migration_complete"))
    debt_upgrade=complete and not policy().get("standalone_debts_reviewed")
    from .standalone_debts import review
    debts, debt_issues=review()
    if debt_upgrade:
        account=ledger.account("receivable")
        target=receivable_target()
        difference=target-int(account.balance)
        rows=[{"key":"receivable","name":"اعتماد الديون المستقلة السابقة", "current":int(account.balance),
            "target":target,"difference":difference}]
    else:
        rows=targets()
    from .opening_credits import issues
    value={"rows":rows,"complete":complete,"debt_upgrade_required":bool(debt_upgrade),
        "standalone_debts":debts,"issues":debt_issues if debt_upgrade else issues()+debt_issues}
    value["hash"]=hashlib.sha256(dumps(value).encode()).hexdigest()
    return value


def apply(payload):
    reviewed=preview()
    if reviewed["complete"] and not reviewed["debt_upgrade_required"]:
        raise FinanceError("الأرصدة الافتتاحية معتمدة مسبقاً؛ لا تُرحّل مرتين", "already_migrated",409)
    if payload.get("preview_hash")!=reviewed["hash"]:
        raise FinanceError("تغيّرت الأرصدة منذ المراجعة؛ اعرض الفروقات مجدداً", "conflict",409)
    from .common import text
    reason=text(payload.get("reason"),1000,True)
    from utils.financial_period_guard import assert_date_period_open
    assert_date_period_open(today(),"اعتماد الأرصدة الافتتاحية")
    if reviewed["issues"]:
        raise FinanceError("؛ ".join(reviewed["issues"]), "opening_review", 409)
    if reviewed["debt_upgrade_required"]:
        difference=reviewed["rows"][0]["difference"]
        if difference:
            receivable,equity=ledger.account("receivable"),ledger.account("opening_equity")
            debit,credit=(receivable,equity) if difference>0 else (equity,receivable)
            db.session.add(JournalEntry(entry_number=f"OPEN-DEBT-{uuid4().hex}",
                description=f"اعتماد ديون مستقلة سابقة — {reason}",reference_type="finance_opening",reference_id=1,
                debit_account_id=debit.id,credit_account_id=credit.id,
                amount=abs(difference),entry_date=datetime.combine(today(),datetime.min.time()),created_by=actor().id))
        from .source_sync import seed_customer_debts
        seed_customer_debts()
        record=db.session.get(FinancePolicy,1)
        record.settings=dumps({**policy(),"standalone_debts_reviewed":True})
        audit("migration.customer_debts","settings",record,{"reason":reason,"preview":reviewed})
        return {"complete":True,"rows":reviewed["rows"]}
    from .opening_credits import seed
    seed()
    equity=ledger.account("opening_equity")
    for item in reviewed["rows"]:
        difference=item["difference"]
        if not difference:
            continue
        account=ledger.account(item["key"])
        debit_normal=account.account_type in {"asset","expense"}
        debit,credit=(account,equity) if (difference>0)==debit_normal else (equity,account)
        db.session.add(JournalEntry(entry_number=f"OPEN-{uuid4().hex}",description=f"افتتاحي: {account.name} — {reason}",
            reference_type="finance_opening",reference_id=1,debit_account_id=debit.id,credit_account_id=credit.id,
            amount=abs(difference),entry_date=datetime.combine(today(),datetime.min.time()),created_by=actor().id))
    # Link the existing advances; no cash transaction, payroll expense, or second advance is created.
    from .common import tenant_key
    for advance in HRAdvance.query.filter(HRAdvance.status.in_(["paid","repaying"])).all():
        if FinanceLoan.query.filter_by(hr_advance_id=advance.id).first():
            continue
        from modules.hr.models import HRPerson
        person=db.session.get(HRPerson,advance.person_id)
        if not person or not person.branch_id:
            raise FinanceError("اربط السلفة السابقة بشخص وفرع قبل اعتماد الافتتاحي","opening_review",409)
        account=db.session.get(TreasuryAccount,advance.treasury_account_id) if advance.treasury_account_id else TreasuryAccount.query.filter_by(branch_id=person.branch_id,is_default=True,is_active=True).first()
        if not person or not person.branch_id or not account:
            raise FinanceError("اربط سلفة الموظف السابقة بشخص وفرع وصندوق قبل اعتماد الافتتاحي","opening_review",409)
        row=FinanceLoan(tenant_key=tenant_key(),branch_id=person.branch_id,number=f"HR-{advance.id:06d}",direction="employee",
            party_name=person.name,person_id=person.id,hr_advance_id=advance.id,principal=advance.amount,
            treasury_account_id=account.id,starts_on=advance.created_at.date(),
            first_due=loans.day(f"{advance.first_month}-01"),instalments=advance.instalments,
            status="active",created_by=actor().id,notes="مرتبط بالسلفة السابقة؛ بدون تكرار التمويل")
        db.session.add(row)
        db.session.flush()
        loans.generate_schedule(row)
    from .source_sync import seed_existing
    seed_existing()
    record=db.session.get(FinancePolicy,1)
    record.settings=dumps({**policy(),"opening_migration_complete":True,"standalone_debts_reviewed":True,"ledger_live":True,"opening_date":today().isoformat()})
    audit("migration.apply","settings",record,{"reason":reason,"preview":reviewed})
    return {"complete":True,"rows":reviewed["rows"]}
