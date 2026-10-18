"""HR accruals and payments using FINORA's existing journals and treasury."""
import calendar
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from flask import abort
from extensions import db
from models.employee import Employee
from models.employee_payment import EmployeePayment
from models.account_transaction import AccountTransaction
from models.expense import Expense
from models.treasury_account import TreasuryAccount
from utils.accounting_logic import create_journal_entry, get_or_create_account
from utils.treasury_calculations import assert_sufficient_balance
from utils.branch_mode import independent_branches_enabled
from .common import BAGHDAD, actor, audit, branch, day, integer, json_text, people_query, person, require, text, version
from .models import (HRPerson, HRContract, HRAttendance, HRLeave, HRLeaveType, HRRecord,
                     HRPayrollRun, HRPayrollItem, HRPayrollPayment, HRAdvance, HRAdvanceRepayment,
                     HRPayAdjustment, HROffboarding)

ACCOUNTS = {"expense": ("5102", "مصروف رواتب وعمولات الموظفين", "expense"),
            "payable": ("2102", "مستحقات الموظفين", "liability"),
            "advance": ("1202", "سلف الموظفين", "asset"),
            "cash": ("1001", "النقدية / الصندوق", "asset"),
            "bank": ("1002", "البنك", "asset")}


def journal(debit, credit, amount, reference, reference_id, description, treasury_account_id=None):
    if amount <= 0:
        return
    accounts=dict(ACCOUNTS)
    from sqlalchemy import inspect
    if inspect(db.session.connection()).has_table("financial_account_mappings"):
        from modules.finance.models import FinanceMapping
        for key,role in {"expense":"salary_expense","payable":"salary_payable","advance":"employee_advance"}.items():
            mapping=db.session.get(FinanceMapping,role)
            if mapping:
                accounts[key]=(mapping.account.code,mapping.account.name,mapping.account.account_type)
        if treasury_account_id:
            from modules.finance.ledger import treasury_gl
            mapped=treasury_gl(db.session.get(TreasuryAccount,treasury_account_id))
            for key in ("cash","bank"):
                accounts[key]=(mapped.code,mapped.name,mapped.account_type)
    for key in (debit, credit):
        code, name, kind = accounts[key]
        get_or_create_account(code, name, kind, commit=False)
    create_journal_entry(accounts[debit][0], accounts[credit][0], amount, description,
                         reference_type=reference, reference_id=reference_id, created_by=actor().id)


def month_bounds(value):
    value = text(value, limit=7, required=True)
    first = day(value + "-01")
    if first.strftime("%Y-%m") != value or not 2000 <= first.year <= 2100:
        raise ValueError("الشهر غير صحيح")
    return first, date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])


def approved_items(person_id):
    return HRPayrollItem.query.join(HRPayrollRun).filter(HRPayrollItem.person_id == person_id,
                                                       HRPayrollRun.status == "approved")


def assert_contract_editable(person_id, effective):
    if approved_items(person_id).filter(HRPayrollRun.month >= effective.strftime("%Y-%m")).first():
        raise ValueError("يوجد مسير معتمد متأثر بالتعديل؛ سجّل تسوية مستقلة")


def assert_attendance_editable(person_id, on):
    if approved_items(person_id).filter(HRPayrollRun.month == on.strftime("%Y-%m")).first():
        raise ValueError("الفترة دخلت بمسير معتمد؛ لا يمكن تغيير الحساب الأصلي")


def calculate_person(employee, month):
    first, last = month_bounds(month)
    records = {r.work_date: r for r in HRAttendance.query.filter(HRAttendance.person_id == employee.id,
                                                               HRAttendance.work_date >= first, HRAttendance.work_date <= last).all()}
    contracts = HRContract.query.filter(HRContract.person_id == employee.id, HRContract.effective_from <= last).order_by(HRContract.effective_from).all()
    if not contracts:
        raise ValueError(f"لا يوجد عقد مالي ساري للموظف {employee.name}")
    types = {t.id: t for t in HRLeaveType.query.all()}
    leaves = HRLeave.query.filter(HRLeave.person_id == employee.id, HRLeave.status == "approved", HRLeave.starts <= last, HRLeave.ends >= first).all()
    from .models import HRLeaveDay
    leave_days={r.on_date:r for r in HRLeaveDay.query.filter(HRLeaveDay.leave_id.in_([l.id for l in leaves]),
        HRLeaveDay.on_date>=first,HRLeaveDay.on_date<=last).all()}
    gross = Decimal(0)
    overtime_bonus = Decimal(0)
    attendance_penalties = 0
    exit_record = HROffboarding.query.filter_by(person_id=employee.id).first()
    components = []
    for i in range((last - first).days + 1):
        on = first + timedelta(days=i)
        applicable = [c for c in contracts if c.effective_from <= on]
        if on < employee.joined_on or not applicable or exit_record and on > exit_record.ends_on:
            continue
        terms = json.loads(applicable[-1].terms)
        if terms.get("contract_end") and on > day(terms["contract_end"]):
            continue
        rate = integer(terms["salary"])
        kind = terms["salary_type"]
        leave_day=leave_days.get(on)
        fraction=min(Decimal(1),Decimal(leave_day.half_days)/2) if leave_day else Decimal(0)
        unpaid_fraction=fraction if leave_day and not leave_day.paid else Decimal(0)
        paid_fraction=fraction if leave_day and leave_day.paid else Decimal(0)
        multiplier = Decimal(1) - unpaid_fraction
        record = records.get(on)
        if kind in ("monthly", "monthly_commission"):
            amount = Decimal(rate) / Decimal((last - first).days + 1) * multiplier
        elif kind == "weekly":
            amount = Decimal(rate) / Decimal(7) * multiplier
        elif kind == "daily":
            worked_fraction=(Decimal(1)-fraction) if record and record.check_out else Decimal(0)
            amount=Decimal(rate)*(worked_fraction+paid_fraction)
        elif kind == "hourly":
            amount = Decimal(rate) * Decimal(record.worked_minutes) / Decimal(60) if record and record.check_out else Decimal(0)
            if paid_fraction:
                from .attendance import assigned_shifts,bounds
                shift=assigned_shifts([employee],on).get(employee.id)
                if not shift:
                    raise ValueError("حدد وردية الموظف لحساب ساعات الإجازة المدفوعة")
                start,end=bounds(shift,on)
                scheduled=max(0,int((end-start).total_seconds()//60)-shift["break_minutes"])
                credited=Decimal(scheduled)*paid_fraction
                # Paid leave credits the unworked scheduled hours, never the same worked minute twice.
                worked=record.worked_minutes if record and record.check_out else 0
                credited=min(credited,Decimal(max(0,scheduled-worked)))
                amount+=Decimal(rate)*credited/60
        else:
            amount = Decimal(0)
        bonus = Decimal(0)
        penalty = 0
        if record and record.check_out:
            bonus = Decimal(integer(terms.get("overtime_hourly_bonus",0))) * Decimal(record.overtime_minutes) / Decimal(60)
            penalty += integer(terms.get("late_minute_penalty",0)) * record.late_minutes
        elif (not record or not record.check_in) and kind in ("monthly","monthly_commission","weekly") and terms.get("absence_daily_penalty"):
            from .attendance import assigned_shifts, bounds, is_work_day
            shift = assigned_shifts([employee],on).get(employee.id)
            if shift and is_work_day(employee,on) and bounds(shift,on)[1] < datetime.utcnow() and not any(l.starts <= on <= l.ends for l in leaves):
                penalty += integer(terms["absence_daily_penalty"])
        overtime_bonus += bonus
        attendance_penalties += penalty
        amount += bonus
        gross += amount
        components.append({"date": on.isoformat(), "contract_id": applicable[-1].id, "type": kind,
                           "rate": rate, "minutes": record.worked_minutes if record else 0,
                           "amount": int(amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)),
                           "overtime_bonus":int(bonus.quantize(Decimal(1),rounding=ROUND_HALF_UP)),"attendance_penalty":penalty})
    gross = int(gross.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if components:
        components[-1]["amount"] += gross-sum(c["amount"] for c in components)
    adjustments = [{"id": r.id, "source": "workspace", "kind": r.kind, "amount": r.amount, "title": r.title}
                   for r in HRPayAdjustment.query.filter_by(person_id=employee.id, month=month).order_by(HRPayAdjustment.id).all()]
    if employee.employee_id:
        from models.hr import HRPayrollAdjustment
        adjustments += [{"id": r.id, "source": "legacy", "kind": r.adjustment_type, "amount": int(r.amount or 0), "title": r.title}
                        for r in HRPayrollAdjustment.query.filter_by(employee_id=employee.employee_id,
                            period_year=first.year, period_month=first.month).order_by(HRPayrollAdjustment.id).all()]
    gross += sum(r["amount"] for r in adjustments if r["kind"] == "allowance")
    # A legacy salary already paid during this period is never accrued again.
    legacy_paid = 0
    if employee.employee_id:
        legacy_paid = int(db.session.query(db.func.coalesce(db.func.sum(EmployeePayment.amount), 0)).filter(
            EmployeePayment.payee_type == "employee", EmployeePayment.payee_id == employee.employee_id,
            EmployeePayment.payment_kind.in_(("salary_weekly", "salary_monthly")),
            db.or_(db.and_(EmployeePayment.period_year == first.year, EmployeePayment.period_month == first.month),
                   db.and_(EmployeePayment.period_year.is_(None),
                       EmployeePayment.paid_at >= datetime.combine(first, datetime.min.time()),
                       EmployeePayment.paid_at < datetime.combine(last + timedelta(days=1), datetime.min.time())))).scalar())
    gross = max(0, gross - legacy_paid)
    wage_deductions = min(gross, attendance_penalties + sum(r["amount"] for r in adjustments if r["kind"] == "deduction"))
    repayments = []
    available = gross - wage_deductions
    for advance in HRAdvance.query.filter(HRAdvance.person_id == employee.id, HRAdvance.status.in_(("paid", "repaying")),
                                         HRAdvance.first_month <= month).order_by(HRAdvance.id).all():
        first_paid, _ = month_bounds(advance.first_month)
        elapsed = (first.year - first_paid.year) * 12 + first.month - first_paid.month + 1
        scheduled = min(advance.amount, (advance.amount * min(elapsed, advance.instalments) + advance.instalments - 1) // advance.instalments)
        amount = min(max(0, scheduled - advance.repaid), advance.amount - advance.repaid, available)
        if amount:
            repayments.append({"advance_id": advance.id, "amount": amount})
            available -= amount
    return {"gross": gross, "deductions": gross - available, "net": available,
            "legacy_paid": legacy_paid, "days": components, "advance_repayments": repayments,
            "person_version": employee.version, "adjustments": adjustments, "wage_deductions": wage_deductions,
            "overtime_bonus":int(overtime_bonus.quantize(Decimal(1),rounding=ROUND_HALF_UP)),"attendance_penalties":attendance_penalties,
            "ends_on": exit_record.ends_on.isoformat() if exit_record else None}


def eligible_people(branch_id, last, unrestricted=False):
    query=HRPerson.query.execution_options(skip_branch_scope=True) if unrestricted else people_query()
    return query.outerjoin(HROffboarding, HROffboarding.person_id == HRPerson.id).filter(
        HRPerson.branch_id == branch_id, HRPerson.joined_on <= last,
        db.or_(HRPerson.status.in_(("active", "leave", "suspended")),
               db.and_(HRPerson.status == "terminated", HROffboarding.ends_on >= last.replace(day=1)))).all()


def prepare_payroll(payload):
    require("hr.payroll.prepare")
    _, last = month_bounds(payload["month"])
    branch_id = branch(payload)
    if {p.id for p in eligible_people(branch_id,last)} != {p.id for p in eligible_people(branch_id,last,unrestricted=True)}:
        raise PermissionError("إعداد مسير الفرع يتطلب نطاقاً يشمل كل موظفي الفرع")
    run = HRPayrollRun(branch_id=branch_id, month=payload["month"], created_by=actor().id)
    db.session.add(run)
    db.session.flush()
    employees = eligible_people(branch_id, last)
    if not employees:
        raise ValueError("لا يوجد موظفون في الفرع المختار")
    for employee in employees:
        calculation = calculate_person(employee, run.month)
        db.session.add(HRPayrollItem(run_id=run.id, person_id=employee.id, gross=calculation["gross"],
                                     deductions=calculation["deductions"], net=calculation["net"], calculation=json_text(calculation)))
    audit("payroll.prepare", run.id, detail={"month": run.month, "branch_id": branch_id})
    return {"id": run.id, "version": run.version}


def payroll_run(run_id):
    run = db.session.get(HRPayrollRun, integer(run_id, minimum=1))
    if not run:
        abort(404)
    permitted = people_query().filter(HRPerson.branch_id == run.branch_id).first()
    if not permitted:
        abort(403)
    item_ids={i.person_id for i in HRPayrollItem.query.filter_by(run_id=run.id).all()}
    allowed={p.id for p in people_query().filter(HRPerson.id.in_(item_ids)).all()}
    if item_ids-allowed:
        abort(403,description="مراجعة مسير الفرع تتطلب نطاق كل الموظفين المشمولين")
    return run


def recalculate_payroll(payload):
    require("hr.payroll.prepare")
    run = payroll_run(payload["run_id"])
    version(run, payload)
    if run.status not in ("draft", "reviewed"):
        raise ValueError("المسير المعتمد ثابت؛ لا يمكن إعادة احتسابه")
    reason = text(payload.get("reason"), limit=500, required=True)
    _, last = month_bounds(run.month)
    employees = eligible_people(run.branch_id, last)
    if not employees:
        raise ValueError("لا يوجد موظفون مستحقون في هذه الفترة")
    old = {i.person_id: i for i in HRPayrollItem.query.filter_by(run_id=run.id).all()}
    for employee in employees:
        calculation = calculate_person(employee, run.month)
        item = old.pop(employee.id, None)
        if item is None:
            item = HRPayrollItem(run_id=run.id, person_id=employee.id)
            db.session.add(item)
        item.gross, item.deductions, item.net = (calculation[k] for k in ("gross", "deductions", "net"))
        item.calculation = json_text(calculation)
    for item in old.values():
        db.session.delete(item)
    run.status = "draft"
    audit("payroll.recalculate", run.id, detail={"reason": reason})
    return {"id": run.id, "version": run.version}


def decide_payroll(payload):
    target = payload.get("status")
    require("hr.payroll.review" if target == "reviewed" else "hr.payroll.approve")
    run = payroll_run(payload["run_id"])
    version(run, payload)
    if (run.status, target) not in (("draft", "reviewed"), ("reviewed", "approved")):
        raise ValueError("راجع مسير الرواتب قبل الاعتماد")
    items = HRPayrollItem.query.filter_by(run_id=run.id).all()
    _, last = month_bounds(run.month)
    eligible = eligible_people(run.branch_id, last)
    if {p.id for p in eligible} != {i.person_id for i in items}:
        abort(409, description="تغيّرت قائمة الموظفين؛ أعد احتساب المسير")
    # Recalculate under the same transaction, then compare every source snapshot.
    for item in items:
        employee = person(item.person_id, lock=True)
        actual = calculate_person(employee, run.month)
        if actual != json.loads(item.calculation):
            abort(409, description="تغيّرت مصادر الراتب؛ أعد احتساب المسير قبل الاعتماد")
    if target == "approved":
        if last >= datetime.now(BAGHDAD).date():
            raise ValueError("اعتماد الراتب النهائي متاح بعد نهاية الفترة؛ استخدم السلفة للدفع قبل الإقفال")
        if HRAttendance.query.filter(HRAttendance.person_id.in_([i.person_id for i in items]),
            HRAttendance.work_date >= last.replace(day=1), HRAttendance.work_date <= last,
            HRAttendance.check_in.is_not(None), HRAttendance.check_out.is_(None)).first():
            raise ValueError("توجد سجلات حضور بدون انصراف؛ صحّح الدوام قبل اعتماد المسير")
        for item in items:
            employee = person(item.person_id)
            calculation = json.loads(item.calculation)
            wage_deductions = calculation.get("wage_deductions", 0)
            if item.gross:
                expense = Expense(branch_id=employee.branch_id, title=f"استحقاق راتب {employee.code} / {run.month}",
                                  category="salary", amount=item.gross - wage_deductions, note=f"غير نقدي: HR-{run.id}-{item.id}",
                                  cash_posted=True, employee_id=employee.employee_id)
                db.session.add(expense)
                db.session.flush()
                item.expense_id = expense.id
                journal("expense", "payable", item.gross, "hr_payroll_accrual", item.id, expense.title)
                journal("payable", "expense", wage_deductions, "hr_wage_deduction", item.id, f"استقطاع أجر {employee.code}")
            for repayment in calculation["advance_repayments"]:
                advance = db.session.get(HRAdvance, repayment["advance_id"])
                advance.repaid += repayment["amount"]
                advance.status = "repaid" if advance.repaid == advance.amount else "repaying"
                advance.version += 1
                db.session.add(HRAdvanceRepayment(advance_id=advance.id, payroll_item_id=item.id, amount=repayment["amount"]))
                journal("payable", "advance", repayment["amount"], "hr_advance_deduction", item.id, f"استقطاع سلفة من راتب {employee.code}")
            if employee.employee_id:
                # The HR approval workflow now owns this payee's salary. The
                # legacy automatic/full-cycle payer must not pay it a second time.
                account = db.session.get(Employee, employee.employee_id)
                account.pay_type = "commission" if "commission" in str(account.pay_type) else "none"
        run.approved_by, run.approved_at = actor().id, datetime.utcnow()
    run.status = target
    audit(f"payroll.{target}", run.id)
    return {"id": run.id, "version": run.version}


def treasury(account_id, employee):
    account = TreasuryAccount.query.filter_by(id=integer(account_id, minimum=1), is_active=True).with_for_update().first()
    if not account or (independent_branches_enabled() and account.branch_id != employee.branch_id):
        raise ValueError("اختر صندوقاً أو بنكاً فعالاً من فرع الموظف")
    return account


def withdraw(account, employee, amount, note):
    assert_sufficient_balance(account.id, amount)
    row = AccountTransaction(branch_id=employee.branch_id, type="withdraw", amount=amount,
                             note=note, treasury_account_id=account.id)
    db.session.add(row)
    db.session.flush()
    return row


def pay_payroll(payload, command_id):
    require("hr.payroll.pay")
    item = db.session.get(HRPayrollItem, integer(payload["item_id"], minimum=1))
    if not item:
        abort(404)
    employee = person(item.person_id, lock=True)
    run = payroll_run(item.run_id)
    if run.status != "approved":
        raise ValueError("اعتمد مسير الرواتب أولاً")
    amount = integer(payload["amount"], minimum=1)
    if amount > item.net - item.paid:
        raise ValueError("المبلغ أكبر من الراتب غير المصروف")
    changed = (HRPayrollItem.query.filter(HRPayrollItem.id == item.id, HRPayrollItem.net - HRPayrollItem.paid >= amount)
               .update({HRPayrollItem.paid: HRPayrollItem.paid + amount}, synchronize_session=False))
    if changed != 1:
        abort(409, description="تغيّر المبلغ غير المصروف؛ حدّث الراتب")
    db.session.refresh(item)
    account = treasury(payload["treasury_account_id"], employee)
    note = f"صرف راتب HR-{run.id}-{item.id} / {command_id[:8]}"
    tx = withdraw(account, employee, amount, note)
    first, last = month_bounds(run.month)
    payment = EmployeePayment(branch_id=employee.branch_id,
                              payee_type="employee" if employee.employee_id else "hr_person",
                              payee_id=employee.employee_id or employee.id, payment_kind="hr_salary",
                              amount=amount, period_start=first, period_end=last, period_year=first.year, period_month=first.month,
                              treasury_account_id=account.id, expense_id=item.expense_id, settled_by=actor().id,
                              note=text(payload.get("reference", ""), limit=255), voucher_code=f"HRP-{command_id}")
    db.session.add(payment)
    db.session.flush()
    db.session.add(HRPayrollPayment(payroll_item_id=item.id, payment_id=payment.id, transaction_id=tx.id, command_id=command_id))
    journal("payable", "bank" if account.account_type == "bank" else "cash", amount, "hr_payroll_payment", payment.id, note, treasury_account_id=account.id)
    audit("payroll.pay", payment.id, person_id=employee.id, detail={"amount": amount, "item_id": item.id})
    return {"id": payment.id, "remaining": item.net - item.paid}


def request_advance(payload):
    require("hr.advance.create")
    employee = person(payload["person_id"], lock=True)
    amount = integer(payload["amount"], minimum=1)
    month_bounds(payload["first_month"])
    row = HRAdvance(person_id=employee.id, amount=amount, instalments=integer(payload["instalments"], minimum=1, maximum=60),
                    first_month=payload["first_month"], reason=text(payload.get("reason", ""), limit=500))
    db.session.add(row)
    db.session.flush()
    audit("advance.request", row.id, person_id=employee.id)
    return {"id": row.id}


def decide_advance(payload):
    require("hr.advance.approve")
    row = db.session.get(HRAdvance, integer(payload["advance_id"], minimum=1))
    if not row:
        abort(404)
    person(row.person_id, lock=True)
    version(row, payload)
    if row.status != "pending" or payload.get("status") not in ("approved", "rejected"):
        raise ValueError("السلفة لا تقبل هذا الإجراء")
    row.status = payload["status"]
    audit(f"advance.{row.status}", row.id, person_id=row.person_id)
    return {"id": row.id, "version": row.version}


def pay_advance(payload):
    require("hr.advance.pay")
    row = db.session.get(HRAdvance, integer(payload["advance_id"], minimum=1))
    if not row:
        abort(404)
    employee = person(row.person_id, lock=True)
    version(row, payload)
    if row.status != "approved":
        raise ValueError("السلفة غير معتمدة أو صُرفت مسبقاً")
    account = treasury(payload["treasury_account_id"], employee)
    tx = withdraw(account, employee, row.amount, f"صرف سلفة HR-A{row.id} / {employee.code}")
    row.treasury_account_id, row.transaction_id, row.status = account.id, tx.id, "paid"
    journal("advance", "bank" if account.account_type == "bank" else "cash", row.amount, "hr_advance_payment", row.id, tx.note, treasury_account_id=account.id)
    audit("advance.pay", row.id, person_id=employee.id, detail={"amount": row.amount})
    return {"id": row.id, "version": row.version}
