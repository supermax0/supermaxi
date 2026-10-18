"""Sales-backed HR commissions; financial history is adjusted, never rewritten."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from flask import abort
from sqlalchemy import inspect, or_
from extensions import db
from models.invoice import Invoice
from models.employee_commission_line import EmployeeCommissionLine
from models.employee_payment import EmployeePayment
from models.expense import Expense
from utils.employee_commission_service import delivered_paid_filter
from .common import BAGHDAD, actor, audit, day, fingerprint, integer, json_text, people_query, person, require, text, version
from .models import (HRPerson, HRCommissionPolicy, HRInvoiceSalesPerson, HRCommission,
                     HRCommissionChange, HRCommissionPayment, HRAdvance)
from .finance import journal, month_bounds, treasury, withdraw


def invoice_date(invoice):
    return (invoice.created_at or datetime.utcnow()).replace(tzinfo=timezone.utc).astimezone(BAGHDAD).date()


def policy_for(employee, on):
    return HRCommissionPolicy.query.filter(HRCommissionPolicy.person_id == employee.id,
        HRCommissionPolicy.effective_from <= on).order_by(HRCommissionPolicy.effective_from.desc()).first()


def sales_person(invoice):
    assignment = db.session.get(HRInvoiceSalesPerson, invoice.id)
    return db.session.get(HRPerson, assignment.person_id) if assignment else HRPerson.query.filter_by(employee_id=invoice.employee_id).first() if invoice.employee_id else None


def eligible_invoices(employee, on):
    first, last = month_bounds(on.strftime("%Y-%m"))
    start = datetime.combine(first, datetime.min.time()) - timedelta(hours=3)
    end = datetime.combine(last + timedelta(days=1), datetime.min.time()) - timedelta(hours=3)
    return (Invoice.query.outerjoin(HRInvoiceSalesPerson, HRInvoiceSalesPerson.invoice_id == Invoice.id)
        .filter(Invoice.branch_id == employee.branch_id, Invoice.created_at >= start, Invoice.created_at < end,
            or_(HRInvoiceSalesPerson.person_id == employee.id,
                (HRInvoiceSalesPerson.invoice_id.is_(None)) & (Invoice.employee_id == employee.employee_id) if employee.employee_id else db.false()),
            delivered_paid_filter()).order_by(Invoice.created_at, Invoice.id).all())


def calculation(invoice, employee):
    policy = policy_for(employee, invoice_date(invoice))
    eligible = bool(Invoice.query.filter(Invoice.id == invoice.id, delivered_paid_filter()).first())
    if not policy:
        existing = HRCommission.query.filter_by(person_id=employee.id, invoice_id=invoice.id).first()
        if not existing or not existing.legacy_line_id:
            return None
        original = json.loads(existing.calculation)
        return {**original, "amount": original["legacy_amount"] if eligible else 0, "eligible": eligible,
                "invoice_status": invoice.status, "paid_amount": int(invoice.paid_amount or 0)}
    rules = json.loads(policy.rules)
    base = max(0, int(invoice.total or 0))
    items = [{"id": i.id, "product_id": i.product_id, "quantity": int(i.quantity or 0), "total": int(i.total or 0), "cost": int(i.cost or 0)} for i in invoice.items]
    from modules.sales_returns.line_facts import net_line_rows
    net_items = net_line_rows(invoice)
    if net_items is not None:
        items = net_items
    amount, previous = 0, 0
    if eligible:
        if policy.kind == "fixed":
            amount = rules["fixed"]
        elif policy.kind in ("sales", "profit", "product"):
            if policy.kind == "profit":
                base = max(0, base - sum(i["cost_amount"] if "cost_amount" in i else i["cost"] * i["quantity"] for i in items))
            if policy.kind == "product":
                item_total = sum(i["total"] for i in items)
                base = int(Decimal(sum(i["total"] for i in items if i["product_id"] == rules["product_id"])) *
                           min(Decimal(1), Decimal(base) / Decimal(item_total))) if item_total else 0
            amount = int((Decimal(base) * rules["basis_points"] / Decimal(10000)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        else:
            invoices = eligible_invoices(employee, invoice_date(invoice))
            for row in invoices:
                if row.id == invoice.id:
                    break
                previous += max(0, int(row.total or 0))
            if policy.kind == "target":
                amount = rules["fixed"] if previous < rules["target"] <= previous + base else 0
            elif policy.kind == "tiered":
                lower, total = 0, Decimal(0)
                for tier in rules["tiers"]:
                    upper = tier["up_to"]
                    portion = max(0, min(previous + base, upper) - max(previous, lower))
                    total += Decimal(portion) * tier["basis_points"] / Decimal(10000)
                    lower = upper
                amount = int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return {"amount": amount, "policy_id": policy.id, "kind": policy.kind, "rules": rules, "eligible": eligible,
            "invoice_id": invoice.id, "invoice_total": int(invoice.total or 0), "invoice_status": invoice.status,
            "paid_amount": int(invoice.paid_amount or 0), "base": base, "previous_sales": previous, "items": items}


def outstanding(row):
    changes = HRCommissionChange.query.filter_by(commission_id=row.id, status="accepted").all()
    return max(0, row.amount - row.paid + sum(c.amount + c.receivable_created - c.receivable_reversed for c in changes))


def sync_invoice(invoice, *, reconcile=True):
    # Inspect the caller's connection so a pooled SQLite connection cannot
    # roll back the pending invoice cancellation when the inspector closes.
    if not invoice or not inspect(db.session.connection()).has_table("hr_commission"):
        return False
    employee = sales_person(invoice)
    if not employee or employee.branch_id != invoice.branch_id:
        return False
    actual = calculation(invoice, employee)
    if actual is None:
        return False
    if not db.session.get(HRInvoiceSalesPerson,invoice.id):
        db.session.add(HRInvoiceSalesPerson(invoice_id=invoice.id,person_id=employee.id,created_by=invoice.employee_id or actor().id))
        db.session.flush()
    row = HRCommission.query.filter_by(person_id=employee.id, invoice_id=invoice.id).first()
    legacy = EmployeeCommissionLine.query.filter_by(invoice_id=invoice.id).all()
    if not row:
        paid = [l for l in legacy if l.status == "paid"]
        if paid and (len(paid) != 1 or paid[0].employee_id != employee.employee_id):
            raise ValueError("الفاتورة دخلت بعمولة مدفوعة لموظف آخر")
        if actual["amount"] or paid:
            if not db.session.get(HRInvoiceSalesPerson,invoice.id):
                db.session.add(HRInvoiceSalesPerson(invoice_id=invoice.id,person_id=employee.id,created_by=invoice.employee_id or actor().id))
            old = paid[0] if paid else None
            payment = db.session.get(EmployeePayment, old.payment_id) if old and old.payment_id else None
            row = HRCommission(person_id=employee.id, invoice_id=invoice.id, amount=old.amount if old else actual["amount"],
                paid=old.amount if old else 0, status="paid" if old else "pending", legacy_line_id=old.id if old else None,
                expense_id=payment.expense_id if payment else None, calculation=json_text(actual))
            db.session.add(row)
            db.session.flush()
    if row:
        if row.status in ("pending", "void"):
            if row.amount != actual["amount"] or row.calculation != json_text(actual):
                row.version += 1
            row.amount, row.calculation = actual["amount"], json_text(actual)
            row.status = "pending" if row.amount else "void"
        else:
            changes = HRCommissionChange.query.filter_by(commission_id=row.id).all()
            difference = actual["amount"] - row.amount - sum(c.amount for c in changes if c.status == "accepted")
            digest = fingerprint(actual)
            pending = [c for c in changes if c.status == "pending"]
            if not any(c.source_hash == digest and c.amount == difference for c in pending):
                for change in pending:
                    change.status = "cancelled"
                    change.version += 1
                if difference:
                    db.session.add(HRCommissionChange(commission_id=row.id, amount=difference,
                        target_amount=actual["amount"], source_hash=digest))
        for line in legacy:
            if line.status == "pending":
                line.status = "void"
    if reconcile and actual["kind"] in ("target", "tiered"):
        for other in eligible_invoices(employee, invoice_date(invoice)):
            if other.id != invoice.id:
                sync_invoice(other, reconcile=False)
    return True


def save_policy(payload):
    require("hr.commission.manage")
    employee = person(payload["person_id"], lock=True)
    effective = day(payload["effective_from"])
    frozen = HRCommission.query.join(Invoice, HRCommission.invoice_id == Invoice.id).filter(
        HRCommission.person_id == employee.id, HRCommission.status.in_(("approved", "paid"))).all()
    if any(invoice_date(db.session.get(Invoice, c.invoice_id)) >= effective for c in frozen):
        raise ValueError("توجد عمولات معتمدة متأثرة؛ اختر سرياناً لاحقاً")
    if employee.employee_id:
        old_paid=EmployeeCommissionLine.query.filter_by(employee_id=employee.employee_id,status="paid").all()
        if any(invoice_date(db.session.get(Invoice,l.invoice_id)) >= effective for l in old_paid):
            raise ValueError("توجد عمولات سابقة مصروفة؛ اختر تاريخاً لاحقاً لسياسة جديدة")
    kind = payload.get("kind")
    if kind not in ("fixed", "sales", "profit", "product", "target", "tiered"):
        raise ValueError("نوع سياسة العمولة غير صحيح")
    rules = {"fixed": integer(payload.get("fixed", 0)), "basis_points": integer(payload.get("basis_points", 0), maximum=10000)}
    if kind == "product":
        from models.product import Product
        product = db.session.get(Product, integer(payload.get("product_id"), minimum=1))
        if not product or product.branch_id not in (None, employee.branch_id):
            raise ValueError("اختر منتجاً من فرع الموظف")
        rules["product_id"] = product.id
    if kind == "target":
        rules["target"] = integer(payload.get("target"), minimum=1)
    if kind == "tiered":
        tiers = payload.get("tiers")
        if not isinstance(tiers, list) or not 1 <= len(tiers) <= 10:
            raise ValueError("أضف من 1 إلى 10 شرائح")
        rules["tiers"] = [{"up_to": integer(t["up_to"], minimum=1), "basis_points": integer(t["basis_points"], maximum=10000)} for t in tiers]
        if [t["up_to"] for t in rules["tiers"]] != sorted(set(t["up_to"] for t in rules["tiers"])):
            raise ValueError("رتّب حدود الشرائح تصاعدياً")
    row = HRCommissionPolicy(person_id=employee.id, effective_from=effective, kind=kind, rules=json_text(rules), created_by=actor().id)
    db.session.add(row)
    db.session.flush()
    audit("commission.policy", row.id, person_id=employee.id)
    return {"id": row.id}


def assign_invoice(payload):
    require("hr.commission.manage")
    employee = person(payload["person_id"], lock=True)
    invoice = Invoice.query.filter_by(id=integer(payload["invoice_id"], minimum=1)).with_for_update().first()
    if not invoice or invoice.branch_id != employee.branch_id:
        raise ValueError("الفاتورة لا تتبع فرع الموظف")
    if HRCommission.query.filter_by(invoice_id=invoice.id).filter(HRCommission.status.in_(("approved", "paid"))).first():
        raise ValueError("الفاتورة دخلت بعمولة معتمدة")
    assignment = db.session.get(HRInvoiceSalesPerson, invoice.id)
    if assignment and assignment.person_id != employee.id:
        assignment.person_id=employee.id
    if not policy_for(employee, invoice_date(invoice)):
        raise ValueError("أضف سياسة عمولة سارية بتاريخ الفاتورة أولاً")
    if not assignment:
        db.session.add(HRInvoiceSalesPerson(invoice_id=invoice.id, person_id=employee.id, created_by=actor().id))
        db.session.flush()
    for previous in HRCommission.query.filter(HRCommission.invoice_id == invoice.id,HRCommission.person_id != employee.id).all():
        previous.amount,previous.status=0,"void"
        previous.version+=1
        old_person=db.session.get(HRPerson,previous.person_id)
        old_policy=policy_for(old_person,invoice_date(invoice))
        if old_policy and old_policy.kind in ("target","tiered"):
            for other in eligible_invoices(old_person,invoice_date(invoice)):
                sync_invoice(other,reconcile=False)
    sync_invoice(invoice)
    audit("commission.invoice_assign", invoice.id, person_id=employee.id)
    return {"id": invoice.id}


def commission_for(commission_id):
    row = HRCommission.query.filter_by(id=integer(commission_id, minimum=1)).with_for_update().first()
    if not row:
        abort(404)
    employee = person(row.person_id, lock=True)
    invoice=db.session.get(Invoice,row.invoice_id)
    owner=sales_person(invoice)
    if not owner or owner.id != employee.id:
        raise ValueError("الفاتورة مرتبطة حالياً بموظف مبيعات آخر")
    sync_invoice(invoice)
    db.session.flush()
    return row, employee


def approve_commission(payload):
    require("hr.commission.manage")
    row, employee = commission_for(payload["commission_id"])
    version(row, payload)
    if row.status != "pending" or row.amount <= 0:
        raise ValueError("العمولة ليست مستحقة للاعتماد")
    expense = Expense(branch_id=employee.branch_id, title=f"استحقاق عمولة {employee.code} / فاتورة {row.invoice_id}", category="salary",
        amount=row.amount, note=f"غير نقدي: HR-C{row.id}", cash_posted=True, employee_id=employee.employee_id)
    db.session.add(expense)
    db.session.flush()
    row.expense_id, row.status = expense.id, "approved"
    journal("expense", "payable", row.amount, "hr_commission_accrual", row.id, expense.title)
    audit("commission.approve", row.id, person_id=employee.id)
    return {"id": row.id, "version": row.version}


def pay_commission(payload, command_id):
    require("hr.commission.pay")
    row, employee = commission_for(payload["commission_id"])
    version(row, payload)
    if row.status not in ("approved", "paid") or HRCommissionChange.query.filter_by(commission_id=row.id, status="pending").first():
        raise ValueError("اعتمد العمولة وتسوياتها أولاً")
    amount = outstanding(row)
    if amount <= 0:
        raise ValueError("لا يوجد مبلغ غير مصروف")
    account = treasury(payload["treasury_account_id"], employee)
    note = f"صرف عمولة HR-C{row.id} / {command_id[:8]}"
    tx = withdraw(account, employee, amount, note)
    payment = EmployeePayment(branch_id=employee.branch_id, payee_type="employee" if employee.employee_id else "hr_person",
        payee_id=employee.employee_id or employee.id, payment_kind="hr_commission", amount=amount,
        treasury_account_id=account.id, expense_id=row.expense_id, settled_by=actor().id, note=note, voucher_code=f"HRC-{command_id}")
    db.session.add(payment)
    db.session.flush()
    db.session.add(HRCommissionPayment(commission_id=row.id, payment_id=payment.id, transaction_id=tx.id, command_id=command_id))
    row.paid += amount
    row.status = "paid"
    journal("payable", "bank" if account.account_type == "bank" else "cash", amount, "hr_commission_payment", payment.id, note)
    audit("commission.pay", row.id, person_id=employee.id)
    return {"id": row.id, "version": row.version}


def accept_change(payload):
    require("hr.commission.manage")
    change = db.session.get(HRCommissionChange, integer(payload["change_id"], minimum=1))
    if not change:
        abort(404)
    row, employee = commission_for(change.commission_id)
    version(change, payload)
    actual = calculation(db.session.get(Invoice, row.invoice_id), employee)
    if change.status != "pending" or change.source_hash != fingerprint(actual):
        abort(409, description="تغيّرت بيانات تسوية العمولة؛ حدّث الطلب")
    reason = text(payload.get("reason"), limit=500, required=True)
    amount = abs(change.amount)
    title = f"تسوية عمولة HR-C{row.id}: {reason}"
    db.session.add(Expense(branch_id=employee.branch_id, title=title, category="salary", amount=change.amount,
        note=f"غير نقدي: HR-CD{change.id}", cash_posted=True, employee_id=employee.employee_id))
    if change.amount < 0:
        reversal = min(amount, outstanding(row))
        journal("payable", "expense", reversal, "hr_commission_change", change.id, title)
        receivable = amount - reversal
        if receivable:
            month_bounds(payload["first_month"])
            advance = HRAdvance(person_id=employee.id, amount=receivable, instalments=integer(payload.get("instalments", 1), minimum=1, maximum=60),
                first_month=payload["first_month"], reason=title, status="paid")
            db.session.add(advance)
            db.session.flush()
            change.advance_id, change.receivable_created = advance.id, receivable
            journal("advance", "expense", receivable, "hr_commission_change_receivable", change.id, title)
    else:
        remaining = amount
        negatives = HRCommissionChange.query.filter(HRCommissionChange.commission_id == row.id, HRCommissionChange.advance_id.is_not(None),
                                                    HRCommissionChange.status == "accepted").order_by(HRCommissionChange.id).all()
        for negative in negatives:
            advance = db.session.get(HRAdvance, negative.advance_id)
            cleared = min(remaining, advance.amount - advance.repaid)
            if cleared:
                advance.repaid += cleared
                advance.version += 1
                advance.status = "repaid" if advance.repaid == advance.amount else "repaying"
                change.receivable_reversed += cleared
                journal("expense", "advance", cleared, "hr_commission_change_reversal", change.id, title)
                remaining -= cleared
        journal("expense", "payable", remaining, "hr_commission_change", change.id, title)
    change.status = "accepted"
    row.version += 1
    audit("commission.change", change.id, person_id=employee.id, detail={"amount": change.amount, "reason": reason})
    return {"id": change.id, "version": change.version}


def import_legacy(payload):
    require("hr.commission.manage")
    line = db.session.get(EmployeeCommissionLine, integer(payload["legacy_id"], minimum=1))
    if not line:
        abort(404)
    employee = people_query().filter_by(employee_id=line.employee_id).first()
    if not employee:
        abort(404)
    person(employee.id, lock=True)
    if line.status not in ("pending","paid") or HRCommission.query.filter_by(invoice_id=line.invoice_id).first():
        raise ValueError("العمولة غير معلّقة أو تم نقلها مسبقاً")
    invoice = db.session.get(Invoice, line.invoice_id)
    eligible=bool(Invoice.query.filter(Invoice.id == invoice.id, delivered_paid_filter()).first())
    if invoice.branch_id != employee.branch_id or line.status=="pending" and not eligible:
        raise ValueError("الفاتورة غير مستحقة أو خارج فرع الموظف")
    payment=db.session.get(EmployeePayment,line.payment_id) if line.payment_id else None
    paid=line.status=="paid"
    row = HRCommission(person_id=employee.id, invoice_id=invoice.id, amount=line.amount, paid=line.amount if paid else 0,
        status="paid" if paid else "pending", expense_id=payment.expense_id if payment else None,legacy_line_id=line.id, calculation=json_text({"kind": "legacy", "legacy_amount": line.amount,
        "amount": line.amount, "invoice_id": invoice.id, "eligible": True, "invoice_status": invoice.status,
        "paid_amount": int(invoice.paid_amount or 0)}))
    if not paid:
        line.status = "void"
    if not db.session.get(HRInvoiceSalesPerson,invoice.id):
        db.session.add(HRInvoiceSalesPerson(invoice_id=invoice.id,person_id=employee.id,created_by=actor().id))
    db.session.add(row)
    db.session.flush()
    audit("commission.import", row.id, person_id=employee.id)
    sync_invoice(invoice)
    return {"id": row.id}


def workspace_rows(employees, names, offset, size):
    """Page both ledgers and adjustments without loading the entire ledger."""
    from sqlalchemy import literal, union_all
    ids = [p.id for p in employees]
    account_names = {p.employee_id: names[p.id] for p in employees if p.employee_id}
    hr = db.session.query(HRCommission.id.label("id"), literal("hr").label("source"), HRCommission.created_at.label("date")).filter(HRCommission.person_id.in_(ids))
    legacy = db.session.query(EmployeeCommissionLine.id, literal("legacy"), EmployeeCommissionLine.accrued_at).filter(
        EmployeeCommissionLine.employee_id.in_(list(account_names)), EmployeeCommissionLine.status != "void",
        ~EmployeeCommissionLine.id.in_(db.session.query(HRCommission.legacy_line_id).filter(HRCommission.legacy_line_id.is_not(None))))
    changes = db.session.query(HRCommissionChange.id, literal("change"), HRCommissionChange.created_at).join(
        HRCommission, HRCommission.id == HRCommissionChange.commission_id).filter(HRCommission.person_id.in_(ids), HRCommissionChange.status == "pending")
    combined = union_all(hr.statement, legacy.statement, changes.statement).subquery()
    total = db.session.query(db.func.count()).select_from(combined).scalar()
    entries = db.session.query(combined).order_by(combined.c.date.desc(), combined.c.source, combined.c.id.desc()).offset(offset).limit(size).all()
    result = []
    for entry in entries:
        if entry.source == "legacy":
            row = db.session.get(EmployeeCommissionLine, entry.id)
            result.append({**account_names[row.employee_id], "id": -row.id * 2, "entity_id": row.id,
                "source": "legacy", "invoice_id": row.invoice_id, "amount": row.amount, "status": row.status,
                "paid": row.amount if row.status == "paid" else 0, "remaining": 0 if row.status == "paid" else row.amount,
                "date": row.accrued_at.isoformat() + "Z"})
        elif entry.source == "change":
            change = db.session.get(HRCommissionChange, entry.id)
            row = db.session.get(HRCommission, change.commission_id)
            result.append({**names[row.person_id], "id": -change.id * 2 - 1, "entity_id": change.id,
                "source": "change", "invoice_id": row.invoice_id, "amount": change.amount, "status": "adjustment",
                "version": change.version, "date": change.created_at.isoformat() + "Z"})
        else:
            row = db.session.get(HRCommission, entry.id)
            result.append({**names[row.person_id], "id": row.id, "entity_id": row.id, "source": "hr",
                "invoice_id": row.invoice_id, "amount": row.amount, "paid": row.paid, "remaining": outstanding(row),
                "status": row.status, "version": row.version, "date": row.created_at.isoformat() + "Z",
                "has_changes": bool(HRCommissionChange.query.filter_by(commission_id=row.id, status="pending").first())})
    return result, total
