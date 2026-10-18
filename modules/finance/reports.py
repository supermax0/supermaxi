"""Cash flow, general ledger, party statements and due notices from actual posted sources."""
import json
from flask import g
from datetime import datetime, timedelta
from sqlalchemy import or_, func
from extensions import db
from models.account import Account
from models.journal_entry import JournalEntry
from models.treasury_account import TreasuryAccount
from . import ledger, loans, vouchers
from .common import actor, day, get_row, money, policy, scope, today
from .models import FinanceJournalLink, FinanceLoan, FinanceVoucher


def filtered(args):
    query = scope(FinanceVoucher.query, FinanceVoucher)
    if args.get("date_from"):
        query = query.filter(FinanceVoucher.transaction_date >= day(args["date_from"]))
    if args.get("date_to"):
        query = query.filter(FinanceVoucher.transaction_date <= day(args["date_to"]))
    for key in ("kind", "category", "status", "party_type"):
        if args.get(key):
            query = query.filter(getattr(FinanceVoucher, key) == args[key])
    for key in ("party_id", "treasury_account_id", "branch_id", "created_by"):
        if args.get(key):
            query = query.filter(getattr(FinanceVoucher, key) == money(args[key]))
    for key, minimum in (("min_amount", True), ("max_amount", False)):
        if args.get(key):
            amount = money(args[key], minimum=0)
            query = query.filter(FinanceVoucher.amount >= amount if minimum else FinanceVoucher.amount <= amount)
    if args.get("q"):
        search = str(args["q"])[:150].replace("%", r"\%").replace("_", r"\_")
        query = query.filter(or_(FinanceVoucher.number.ilike(f"%{search}%", escape="\\"),
            FinanceVoucher.party_name.ilike(f"%{search}%", escape="\\"), FinanceVoucher.notes.ilike(f"%{search}%", escape="\\")))
    return query


def stats(args):
    rows = filtered(args).all()
    posted = [row for row in rows if row.status in {"posted", "reversed"}]
    received = sum(row.amount for row in posted if row.kind == "receipt")
    paid = sum(row.amount for row in posted if row.kind == "payment")
    return {"received": received, "paid": paid, "cash_flow": received-paid,
            "pending": sum(row.status == "pending" for row in rows), "drafts": sum(row.status == "draft" for row in rows)}


def cash_flow(args):
    groups = {key: {"in": 0, "out": 0, "net": 0} for key in ("operating", "investing", "financing")}
    for row in filtered(args).filter(FinanceVoucher.status.in_(["posted", "reversed"])).all():
        category = json.loads(row.payload).get("original_category", row.category)
        if row.kind in {"transfer", "settlement"}:
            continue
        activity = vouchers.CATEGORIES.get(category, ("", "", "", "operating"))[3]
        if activity in groups:
            groups[activity]["in" if row.kind == "receipt" else "out"] += row.amount
    for group in groups.values():
        group["net"] = group["in"]-group["out"]
    return {"activities": groups, "net": sum(group["net"] for group in groups.values()),
            "internal_transfers_excluded": True, "cash_flow_is_profit": False}


def journal_query(args):
    query = JournalEntry.query
    # Legacy entries lack branch_id. Restricted users receive only entries linked
    # to their authorized vouchers; company-level review belongs to general admins.
    from utils.branch_scope import is_general_admin
    if not is_general_admin(actor()) or (getattr(g, "branch", None) and not getattr(g, "view_all_branches", False)):
        ids = scope(db.session.query(FinanceVoucher.id), FinanceVoucher).subquery()
        links = db.session.query(FinanceJournalLink.journal_entry_id).filter(FinanceJournalLink.voucher_id.in_(db.select(ids.c.id)))
        permitted = JournalEntry.id.in_(links)
        from sqlalchemy import inspect
        if inspect(db.session.connection()).has_table("inventory_count_line"):
            from modules.inventory_audit.models import InventoryCountLine, InventoryCountSession
            from modules.inventory_audit.common import visible_branches
            from flask import session
            count_links = db.session.query(InventoryCountLine.journal_entry_id).join(InventoryCountSession).filter(
                InventoryCountLine.branch_id.in_(visible_branches()),
                InventoryCountSession.tenant_key == session["tenant_slug"], InventoryCountSession.status == "posted")
            permitted = or_(permitted, JournalEntry.id.in_(count_links))
        if inspect(db.session.connection()).has_table("inventory_writeoff"):
            from models.stock_operations import InventoryWriteOff
            loss_links=scope(db.session.query(InventoryWriteOff.journal_entry_id),InventoryWriteOff).filter(
                InventoryWriteOff.sealed.is_(True))
            permitted=or_(permitted,JournalEntry.id.in_(loss_links))
        query = query.filter(permitted)
    if args.get("date_from"):
        query = query.filter(JournalEntry.entry_date >= datetime.combine(day(args["date_from"]), datetime.min.time()))
    if args.get("date_to"):
        query = query.filter(JournalEntry.entry_date < datetime.combine(day(args["date_to"])+timedelta(days=1), datetime.min.time()))
    return query


def trial_balance(args):
    totals = {}
    for entry in journal_query(args).all():
        for account_id, column in ((entry.debit_account_id, "debit"), (entry.credit_account_id, "credit")):
            totals.setdefault(account_id, {"debit": 0, "credit": 0})[column] += entry.amount
    rows = []
    for record in Account.query.filter(Account.id.in_(list(totals))).order_by(Account.code).all():
        total = totals[record.id]
        balance = total["debit"]-total["credit"]
        rows.append({"id": record.id, "code": record.code, "name": record.name, "type": record.account_type,
            **total, "debit_balance": max(0,balance), "credit_balance": max(0,-balance),
            "balance": balance if record.account_type in {"asset", "expense"} else -balance})
    debit, credit = sum(row["debit"] for row in rows), sum(row["credit"] for row in rows)
    revenue = sum(row["balance"] for row in rows if row["type"] == "revenue")
    expenses = sum(row["balance"] for row in rows if row["type"] == "expense")
    return {"rows": rows, "debit": debit, "credit": credit, "balanced": debit == credit,
        "revenue": revenue, "expenses": expenses, "profit": revenue-expenses,
        "assets": sum(row["balance"] for row in rows if row["type"] == "asset"),
        "liabilities": sum(row["balance"] for row in rows if row["type"] == "liability"),
        "equity": sum(row["balance"] for row in rows if row["type"] == "equity"),
        "opening_migration_complete": policy().get("opening_migration_complete", False)}


def journal_rows(args):
    page, count = money(args.get("page", 1)), min(100, money(args.get("page_size", 25)))
    query = journal_query(args)
    if args.get("q"):
        query = query.filter(JournalEntry.description.contains(str(args["q"])[:150]))
    return {"total": query.count(), "page": page, "page_size": count,
        "rows": [{"id": row.id, "number": row.entry_number, "date": row.entry_date.date().isoformat(),
            "description": row.description, "debit": row.debit_account.name, "credit": row.credit_account.name,
            "amount": row.amount, "source_type": row.reference_type, "source_id": row.reference_id}
            for row in query.order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc()).offset((page-1)*count).limit(count).all()]}


def loan_stats(rows):
    active = [row for row in rows if row["status"] == "active"]
    return {"principal": sum(row["principal"] for row in active),
        "remaining": sum(row["remaining_principal"] for row in active),
        "monthly_due": sum(item["remaining"] for row in scope(FinanceLoan.query, FinanceLoan).filter(FinanceLoan.id.in_([r["id"] for r in active])).all()
                           for item in loans.schedule(row) if item["due_date"][:7] == today().strftime("%Y-%m")),
        "overdue": sum(row["overdue"] for row in active),
        "interest": sum(row["remaining_interest"] for row in active)}


def notifications():
    rules, result = policy(), []
    boundary = today()+timedelta(days=rules["due_warning_days"])
    for row in scope(FinanceLoan.query, FinanceLoan).filter(FinanceLoan.status == "active").all():
        for item in loans.schedule(row):
            if item["remaining"] and day(item["due_date"]) <= boundary:
                result.append({"type": "overdue" if item["status"] == "overdue" else "due", "source_type": "loan", "source_id": row.id,
                    "title": f"{row.number} — {row.party_name}", "amount": item["remaining"], "date": item["due_date"]})
    from utils.treasury_calculations import calculate_treasury_balance
    for row in ledger.visible_treasuries():
        balance = calculate_treasury_balance(row.id)
        if balance < rules["low_balance"]:
            result.append({"type": "low_balance", "source_type": "account", "source_id": row.id, "title": row.name, "amount": balance})
    for row in filtered({"status":"pending"}).limit(100).all():
        result.append({"type":"approval", "source_type":"voucher", "source_id":row.id, "title":row.number, "amount":row.amount})
    seen={}
    for row in filtered({"date_from":today().isoformat(),"date_to":today().isoformat(),"status":"posted"}).all():
        if row.kind not in {"receipt","payment"} or (row.source_type or "").endswith("_auto"):
            continue
        signature=(row.branch_id,row.category,row.party_type,row.party_id,row.party_name,row.amount,row.treasury_account_id)
        if signature in seen:
            result.append({"type":"possible_duplicate","source_type":"voucher","source_id":row.id,
                "title":f"راجع تشابه {row.number} مع {seen[signature]}","amount":row.amount})
        else:
            seen[signature]=row.number
    from .models import FinanceReconciliation
    for row in scope(FinanceReconciliation.query,FinanceReconciliation).filter(FinanceReconciliation.status=="pending").all():
        from .reconciliation import serialize
        difference=serialize(row)["difference"]
        if difference:
            result.append({"type":"reconciliation_difference","source_type":"account","source_id":row.treasury_account_id,
                "title":f"فرق كشف مصرفي #{row.id}","amount":difference})
    return result[:500]


def operational_report(name,args):
    """Current outstanding amounts; age is document age, not an invented due date."""
    rows=[]
    labels={"customer-aging":"أعمار ديون العملاء","supplier-aging":"أعمار ديون الموردين",
        "instalments":"الأقساط القادمة والمتأخرة","employee-advances":"سلف الموظفين",
        "reconciliation-differences":"التسويات والفروقات"}
    def add(key,party,reference,on,amount,status="",source_type="",source_id=None):
        on=on.date() if isinstance(on,datetime) else on
        if (args.get("date_from") and on<day(args["date_from"])) or (args.get("date_to") and on>day(args["date_to"])):
            return
        age=max(0,(today()-on).days)
        bucket="0–30" if age<=30 else "31–60" if age<=60 else "61–90" if age<=90 else "90+"
        rows.append({"id":key,"name":party,"reference":str(reference),"date":on.isoformat(),"age":age,
            "amount":int(amount),"status":status or bucket,"source_type":source_type,"source_id":source_id})
    if name=="customer-aging":
        from models.invoice import Invoice
        from models.customer import Customer
        from models.customer_credit import CustomerCreditPlan
        from utils.order_status import CANCELED_STATUSES,RETURN_STATUSES
        from utils.accounting_calculations import booked_sale_filter
        for i in scope(Invoice.query,Invoice).filter(Invoice.status.notin_(list(CANCELED_STATUSES)+list(RETURN_STATUSES)),
            Invoice.deleted_at.is_(None),booked_sale_filter()).all():
            amount=max(0,int(i.total or 0)-int(i.paid_amount or 0))
            if amount:
                add(f"invoice:{i.id}",i.customer_name,f"فاتورة #{i.id}",i.created_at,amount,source_type="customer",source_id=i.customer_id)
        customer_ids=scope(Customer.query,Customer).with_entities(Customer.id)
        for plan in CustomerCreditPlan.query.filter(CustomerCreditPlan.invoice_id.is_(None),
            CustomerCreditPlan.customer_id.in_(customer_ids)).all():
            if plan.remaining:
                add(f"customer-debt:{plan.id}",plan.customer.name,f"دين مستقل #{plan.id}",plan.created_at,
                    plan.remaining,source_type="customer",source_id=plan.customer_id)
    elif name=="supplier-aging":
        from models.supplier import Supplier
        from models.purchase import Purchase
        from utils.supplier_payment_allocation import effective_purchase_payment_totals
        for supplier in scope(Supplier.query,Supplier).all():
            left=max(0,supplier.remaining)
            purchases=scope(Purchase.query,Purchase).filter(Purchase.supplier_id==supplier.id,Purchase.deleted_at.is_(None),
                Purchase.status.notin_(["draft","draft_editing","cancelled","canceled"])).order_by(Purchase.purchase_date,Purchase.id).all()
            for p in purchases:
                amount=min(left,effective_purchase_payment_totals(p)[1]);left-=amount
                if amount:
                    add(f"purchase:{p.id}",supplier.name,p.invoice_no or f"مشتريات #{p.id}",p.purchase_date,amount,
                        source_type="supplier",source_id=supplier.id)
            if left:
                add(f"supplier:{supplier.id}",supplier.name,"رصيد سابق غير مفصل",supplier.created_at,left,
                    source_type="supplier",source_id=supplier.id)
    elif name in {"instalments","employee-advances"}:
        query=scope(FinanceLoan.query,FinanceLoan).filter(FinanceLoan.status=="active")
        if name=="employee-advances":
            query=query.filter(FinanceLoan.direction=="employee")
        for loan in query.all():
            for item in loans.schedule(loan):
                if item["remaining"]:
                    add(f"loan:{loan.id}:{item['number']}",loan.party_name,f"{loan.number} · قسط {item['number']}",
                        day(item["due_date"]),item["remaining"],"متأخر" if item["status"]=="overdue" else "قادم / مستحق",
                        "loan",loan.id)
    elif name=="reconciliation-differences":
        from .models import FinanceReconciliation
        from .reconciliation import serialize
        for row in scope(FinanceReconciliation.query,FinanceReconciliation).all():
            value=serialize(row)
            add(f"reconciliation:{row.id}",row.account.name if hasattr(row,"account") else f"حساب #{row.treasury_account_id}",
                f"كشف #{row.id}",row.ends_on,value["difference"],"مطابق" if row.status=="matched" else "بانتظار المطابقة",
                "account",row.treasury_account_id)
    else:
        from .common import FinanceError
        raise FinanceError("التقرير غير موجود","not_found",404)
    rows.sort(key=lambda row:(row["date"],row["id"]))
    return {"rows":rows,"total":sum(row["amount"] for row in rows),"title":labels[name],"as_of":today().isoformat(),
        "note":"الأرصدة المتبقية الحالية؛ العمر محسوب من تاريخ المستند ولا يعني وجود موعد استحقاق متفق عليه." if name.endswith("aging") else "الأرقام من العمليات الحالية المعتمدة."}
