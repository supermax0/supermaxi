"""Loan contracts, exact monthly schedules, cash repayments and existing HR salary offsets."""
import calendar
import json
from datetime import date, datetime
from uuid import uuid4
from extensions import db
from modules.hr.models import HRAdvance, HRAdvanceRepayment, HRPerson, HRPayrollItem, HRPayrollRun
from . import ledger
from .common import FinanceError, actor, audit, day, dumps, get_row, money, require, tenant_key, text, today, version, write_branch
from .models import FinanceAllocation, FinanceInstalment, FinanceLoan, FinanceLoanPayment, FinanceVoucher


def monthly_date(first, offset):
    total = first.year * 12 + first.month - 1 + offset
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(first.day, calendar.monthrange(year, month)[1]))


def portions(amount, count):
    quotient, remainder = divmod(amount, count)
    return [quotient + (1 if index < remainder else 0) for index in range(count)]


def generate_schedule(loan, principal=None, interest=None, fees=None):
    components = [portions(loan.principal if principal is None else principal, loan.instalments),
                  portions(loan.interest if interest is None else interest, loan.instalments),
                  portions(loan.fees if fees is None else fees, loan.instalments)]
    for index in range(loan.instalments):
        db.session.add(FinanceInstalment(loan_id=loan.id, schedule_version=loan.schedule_version,
            number=index + 1, due_date=monthly_date(loan.first_due, index),
            principal=components[0][index], interest=components[1][index], fees=components[2][index]))


def create(payload):
    require("finance.loans")
    require("finance.create")
    direction = payload.get("direction")
    if direction not in {"borrowed", "lent", "employee"}:
        raise FinanceError("اختر نوع القرض أو السلفة")
    branch_id = write_branch(payload)
    treasury = ledger.treasury(payload.get("treasury_account_id"), branch_id)
    starts = day(payload.get("starts_on") or today().isoformat())
    first = day(payload.get("first_due"))
    count = money(payload.get("instalments"))
    principal = money(payload.get("principal"))
    if count > 360 or count > principal or first < starts:
        raise FinanceError("تحقق من عدد الأقساط وتاريخ أول قسط")
    interest, fees, upfront = (money(payload.get(key, 0), minimum=0) for key in ("interest", "fees", "upfront_fee"))
    if upfront >= principal or (direction != "borrowed" and upfront):
        raise FinanceError("الرسوم المخصومة مقدماً تخص القرض المستلم ويجب أن تقل عن أصله")
    person_id, party_name = None, text(payload.get("party_name"), 150, True)
    if direction == "employee":
        person = get_row(HRPerson, payload.get("person_id"))
        if person.branch_id != branch_id or person.status != "active" or interest or fees:
            raise FinanceError("سلفة الموظف مرتبطة بموظف فعال من نفس الفرع وبدون فوائد أو رسوم")
        person_id, party_name = person.id, person.name
    row = FinanceLoan(tenant_key=tenant_key(), branch_id=branch_id, number=f"LN-{uuid4().hex}",
        direction=direction, party_name=party_name, person_id=person_id, principal=principal,
        interest=interest, fees=fees, upfront_fee=upfront, treasury_account_id=treasury.id,
        starts_on=starts, first_due=first, instalments=count, created_by=actor().id, notes=text(payload.get("notes"), 4000))
    db.session.add(row)
    db.session.flush()
    row.number = f"LN-{row.id:06d}"
    generate_schedule(row)
    audit("contract.create", "loan", row, {"principal": principal, "direction": direction})
    return row


def payment_totals(loan):
    records = FinanceLoanPayment.query.join(FinanceVoucher, FinanceVoucher.id == FinanceLoanPayment.voucher_id).filter(
        FinanceLoanPayment.loan_id == loan.id, FinanceVoucher.status == "posted").all()
    totals = {key: sum(getattr(row, key) for row in records) for key in ("principal", "interest", "fees")}
    if loan.hr_advance_id:
        # HR owns salary deductions. Cash returns also update that same advance.
        advance = db.session.get(HRAdvance, loan.hr_advance_id)
        totals["principal"] = advance.repaid
    return totals


def remaining(loan):
    paid = payment_totals(loan)
    return {key: max(0, getattr(loan, key) - paid[key]) for key in ("principal", "interest", "fees")}


def schedule(loan, *, historical=False):
    paid = payment_totals(loan)
    active_paid = {"principal": max(0, paid["principal"] - loan.schedule_base_principal),
                   "interest": max(0, paid["interest"] - loan.schedule_base_interest),
                   "fees": max(0, paid["fees"] - loan.schedule_base_fees)}
    rows = FinanceInstalment.query.filter_by(loan_id=loan.id, schedule_version=loan.schedule_version).order_by(FinanceInstalment.number).all()
    output = []
    for row in rows:
        applied = {}
        for key in ("principal", "interest", "fees"):
            applied[key] = min(getattr(row, key), active_paid[key])
            active_paid[key] -= applied[key]
        total, used = row.principal + row.interest + row.fees, sum(applied.values())
        status = "paid" if used == total else "partial" if used else "unpaid"
        if total > used and row.due_date < today():
            status = "overdue"
        output.append({"id": row.id, "number": row.number, "due_date": row.due_date.isoformat(),
            "principal": row.principal, "interest": row.interest, "fees": row.fees,
            "total": total, "paid": used, "remaining": total - used, "status": status,
            "paid_principal": applied["principal"], "paid_interest": applied["interest"], "paid_fees": applied["fees"]})
    return output


def fund(loan, payload):
    require("finance.loans")
    version(loan, payload)
    if loan.status != "draft":
        raise FinanceError("القرض مستلم أو مصروف مسبقاً", "conflict", 409)
    from . import vouchers
    category = {"borrowed":"loan_funding", "lent":"loan_grant", "employee":"employee_advance"}[loan.direction]
    if FinanceVoucher.query.filter(FinanceVoucher.party_type=="loan",FinanceVoucher.party_id==loan.id,
        FinanceVoucher.category==category,FinanceVoucher.status.in_(["draft","pending"])).first():
        raise FinanceError("يوجد سند تمويل بانتظار الاعتماد؛ راجعه من القبض والصرف", "conflict",409)
    row = vouchers.create({"category": category, "party_id": loan.id, "branch_id": loan.branch_id,
        "amount": loan.principal - loan.upfront_fee, "treasury_account_id": loan.treasury_account_id,
        "transaction_date": payload.get("transaction_date") or loan.starts_on.isoformat(), "notes": loan.notes})
    from .common import policy
    rules=policy()
    if payload.get("intent")=="pending" or (rules["separate_approval"] and row.amount>=rules["sensitive_threshold"]):
        vouchers.decide(row,"submit",{"version":row.version})
        loan.version+=1
        audit("fund.request","loan",loan,{"voucher_id":row.id})
    else:
        vouchers.approve(row)
    return row


def pay(loan, payload):
    require("finance.loans")
    version(loan, payload)
    if loan.status not in {"active", "closed"} or sum(remaining(loan).values()) <= 0:
        raise FinanceError("القرض غير مفتوح للتسديد", "conflict", 409)
    from . import vouchers
    category = {"borrowed":"loan_payment", "lent":"loan_collection", "employee":"employee_return"}[loan.direction]
    data = {**payload, "category": category, "party_id": loan.id, "branch_id": loan.branch_id,
            "treasury_account_id": payload.get("treasury_account_id") or loan.treasury_account_id}
    row = vouchers.create(data)
    from .common import policy
    rules=policy()
    if payload.get("intent")=="pending" or (rules["separate_approval"] and row.amount>=rules["sensitive_threshold"]):
        vouchers.decide(row,"submit",{"version":row.version})
        loan.version+=1
        audit("payment.request","loan",loan,{"voucher_id":row.id})
    else:
        vouchers.approve(row)
    return row


def accrued_balance(loan):
    accruals = FinanceAllocation.query.join(FinanceVoucher, FinanceVoucher.id == FinanceAllocation.voucher_id).filter(
        FinanceAllocation.reference_type == "loan_interest_accrual", FinanceAllocation.reference_id == loan.id,
        FinanceVoucher.status == "posted").all()
    used = FinanceLoanPayment.query.join(FinanceVoucher, FinanceVoucher.id == FinanceLoanPayment.voucher_id).filter(
        FinanceLoanPayment.loan_id == loan.id, FinanceVoucher.status == "posted").all()
    return max(0, sum(row.amount for row in accruals) - sum(row.accrued_interest for row in used))


def post_operation(row, payload, cash_gl):
    loan = get_row(FinanceLoan, row.party_id)
    if loan.branch_id != row.branch_id:
        raise FinanceError("القرض من فرع آخر")
    category = row.category
    expected_funding = {"borrowed":"loan_funding", "lent":"loan_grant", "employee":"employee_advance"}[loan.direction]
    principal_role = {"borrowed":"loan_payable", "lent":"loan_receivable", "employee":"employee_advance"}[loan.direction]
    if category in {"loan_funding", "loan_grant", "employee_advance"}:
        if category != expected_funding or loan.status != "draft" or row.amount != loan.principal - loan.upfront_fee:
            raise FinanceError("تأكد من نوع القرض ومبلغ الاستلام الفعلي؛ التمويل يتم مرة واحدة", "conflict", 409)
        if row.transaction_date < loan.starts_on:
            raise FinanceError("تاريخ التمويل يسبق العقد")
        loan.status, loan.funding_voucher_id = "active", row.id
        if loan.direction == "employee":
            first_month = loan.first_due.strftime("%Y-%m")
            advance = HRAdvance(person_id=loan.person_id, amount=loan.principal, repaid=0,
                instalments=loan.instalments, first_month=first_month, reason=loan.notes,
                status="paid", treasury_account_id=row.treasury_account_id)
            db.session.add(advance)
            db.session.flush()
            loan.hr_advance_id = advance.id
        if loan.direction == "borrowed":
            pairs = [(cash_gl, ledger.account(principal_role), row.amount)]
            if loan.upfront_fee:
                from .vouchers import expense
                expense(row, loan.upfront_fee, f"رسوم تمويل {loan.number}", "loan_fees", noncash=True)
                pairs.append((ledger.account("interest_expense"), ledger.account(principal_role), loan.upfront_fee))
        else:
            pairs = [(ledger.account(principal_role), cash_gl, row.amount)]
    else:
        expected = {"borrowed":"loan_payment", "lent":"loan_collection", "employee":"employee_return"}[loan.direction]
        if category != expected or loan.status not in {"active", "closed"}:
            raise FinanceError("القرض غير متاح لهذا النوع من التسديد")
        balance = remaining(loan)
        funding = db.session.get(FinanceVoucher, loan.funding_voucher_id) if loan.funding_voucher_id else None
        if row.transaction_date < (funding.transaction_date if funding else loan.starts_on):
            raise FinanceError("تاريخ السداد يسبق الاستلام أو الصرف")
        if any(key in payload for key in ("principal", "interest", "fees")):
            split = {key: money(payload.get(key, 0), minimum=0) for key in ("principal", "interest", "fees")}
        else:
            split = {key: 0 for key in balance}
            left = row.amount
            for instalment in schedule(loan):
                for key in ("interest", "fees", "principal"):
                    use = min(left, instalment[key] - instalment[f"paid_{key}"])
                    split[key] += use
                    left -= use
        if sum(split.values()) != row.amount or any(split[key] > balance[key] for key in split):
            raise FinanceError("تفصيل السداد لا يساوي المبلغ أو يتجاوز أصل/فوائد القرض المتبقية", "overpayment", 409)
        accrued = min(accrued_balance(loan), split["interest"]) if loan.direction == "borrowed" else 0
        payment = FinanceLoanPayment(loan_id=loan.id, voucher_id=row.id,
            principal=split["principal"], interest=split["interest"], fees=split["fees"], accrued_interest=accrued)
        db.session.add(payment)
        if loan.hr_advance_id:
            advance = db.session.get(HRAdvance, loan.hr_advance_id)
            advance.repaid += split["principal"]
            advance.version += 1
            advance.status = "repaid" if advance.repaid == advance.amount else "repaying"
        pairs = []
        if split["principal"]:
            pairs.append((ledger.account(principal_role), cash_gl, split["principal"]) if loan.direction == "borrowed"
                         else (cash_gl, ledger.account(principal_role), split["principal"]))
        if loan.direction == "borrowed":
            if accrued:
                pairs.append((ledger.account("interest_payable"), cash_gl, accrued))
            extra = split["interest"] - accrued + split["fees"]
            if extra:
                from .vouchers import expense
                expense(row, extra, f"فوائد ورسوم {loan.number}", "loan_interest")
                pairs.append((ledger.account("interest_expense"), cash_gl, extra))
        elif split["interest"] + split["fees"]:
            pairs.append((cash_gl, ledger.account("other_revenue"), split["interest"] + split["fees"]))
        if all(balance[key] == split[key] for key in balance):
            loan.status = "closed"
    loan.version += 1
    row.source_type, row.source_id = "loan", loan.id
    audit("fund" if category == expected_funding else "payment", "loan", loan, {"voucher_id": row.id, "amount": row.amount})
    return pairs


def check_reversal(voucher):
    loan = get_row(FinanceLoan, voucher.party_id)
    if voucher.category == "interest_accrual":
        if FinanceLoanPayment.query.join(FinanceVoucher, FinanceVoucher.id == FinanceLoanPayment.voucher_id).filter(
            FinanceLoanPayment.loan_id == loan.id, FinanceLoanPayment.accrued_interest > 0, FinanceVoucher.status == "posted").first():
            raise FinanceError("تم سداد فوائد مستحقة؛ اعكس السداد قبل عكس الاستحقاق", "dependency", 409)
        return
    if voucher.id == loan.funding_voucher_id:
        if sum(payment_totals(loan).values()) or accrued_balance(loan):
            raise FinanceError("القرض لديه أقساط أو استقطاعات راتب أو فوائد مستحقة؛ عالجها قبل عكس التمويل", "dependency", 409)
    else:
        payment = FinanceLoanPayment.query.filter_by(voucher_id=voucher.id).first()
        if not payment or loan.schedule_version > 1:
            raise FinanceError("هناك جدولة تابعة؛ عالجها قبل عكس القسط", "dependency", 409)


def apply_reversal(voucher):
    loan = get_row(FinanceLoan, voucher.party_id)
    if voucher.category == "interest_accrual":
        loan.version += 1
        audit("interest.reverse", "loan", loan, {"voucher_id":voucher.id})
        return
    if voucher.id == loan.funding_voucher_id:
        loan.status, loan.funding_voucher_id = "draft", None
        if loan.hr_advance_id:
            db.session.get(HRAdvance, loan.hr_advance_id).status = "cancelled"
            loan.hr_advance_id = None
    else:
        payment = FinanceLoanPayment.query.filter_by(voucher_id=voucher.id).first()
        if loan.hr_advance_id:
            advance = db.session.get(HRAdvance, loan.hr_advance_id)
            advance.repaid -= payment.principal
            advance.status = "paid" if not advance.repaid else "repaying"
            advance.version += 1
        loan.status = "active"
    loan.version += 1
    audit("reverse", "loan", loan, {"voucher_id": voucher.id})


def reschedule(loan, payload):
    require("finance.loans")
    require("finance.approve")
    version(loan, payload)
    reason = text(payload.get("reason"), 1500, True)
    if loan.status != "active" or loan.direction == "employee":
        raise FinanceError("جدولة القرض المفتوح فقط؛ تعديل استقطاع الموظف يتم قبل اعتماد مسير الراتب")
    balance, paid = remaining(loan), payment_totals(loan)
    first, count = day(payload.get("first_due")), money(payload.get("instalments"))
    if first < today() or count > 360 or count > max(1, balance["principal"]):
        raise FinanceError("تحقق من الجدولة الجديدة")
    from utils.financial_period_guard import assert_date_period_open
    assert_date_period_open(today(), "إعادة الجدولة")
    loan.schedule_version += 1
    loan.schedule_base_principal, loan.schedule_base_interest, loan.schedule_base_fees = paid["principal"], paid["interest"], paid["fees"]
    loan.first_due, loan.instalments = first, count
    generate_schedule(loan, **balance)
    loan.version += 1
    audit("reschedule", "loan", loan, {"reason": reason, "schedule_version": loan.schedule_version})
    return loan


def close(loan, payload):
    require("finance.loans")
    require("finance.approve")
    version(loan, payload)
    if loan.status not in {"active", "closed"} or sum(remaining(loan).values()) or accrued_balance(loan):
        raise FinanceError("لا يمكن إغلاق القرض قبل سداد الأصل والفوائد والرسوم المستحقة")
    loan.status = "closed"
    loan.version += 1
    audit("close", "loan", loan)
    return loan


def accrue_interest(loan, payload):
    require("finance.loans")
    require("finance.approve")
    version(loan, payload)
    amount = money(payload.get("amount"))
    on=day(payload.get("transaction_date") or today().isoformat())
    if on>today():
        raise FinanceError("استحقاق الفائدة لا يسجل بتاريخ مستقبلي")
    if loan.direction != "borrowed" or loan.status != "active" or amount > remaining(loan)["interest"] - accrued_balance(loan):
        raise FinanceError("الفائدة غير مستحقة أو سبق تسجيلها")
    from . import vouchers
    row = FinanceVoucher(tenant_key=tenant_key(), branch_id=loan.branch_id, number=f"AC-{uuid4().hex}",
        kind="settlement", category="interest_accrual", party_type="loan", party_id=loan.id, party_name=loan.party_name,
        amount=amount, transaction_date=on, created_by=actor().id,
        payload=dumps(payload), notes=text(payload.get("notes"), 1000, True))
    db.session.add(row)
    db.session.flush()
    row.number=f"AC-{row.id:06d}"
    from .common import policy
    rules=policy()
    if payload.get("intent")=="pending" or (rules["separate_approval"] and amount>=rules["sensitive_threshold"]):
        vouchers.decide(row,"submit",{"version":row.version})
        loan.version+=1
        audit("interest.request","loan",loan,{"voucher_id":row.id})
    else:
        vouchers.approve(row)
    return row


def post_interest_accrual(row,payload):
    require("finance.loans")
    loan=get_row(FinanceLoan,row.party_id)
    if loan.direction!="borrowed" or loan.status!="active" or row.amount>remaining(loan)["interest"]-accrued_balance(loan):
        raise FinanceError("الفائدة غير مستحقة أو سبق تسجيلها", "conflict",409)
    from .vouchers import expense,allocation
    expense(row,row.amount,f"فوائد مستحقة {loan.number}","loan_interest",noncash=True)
    allocation(row,"loan_interest_accrual",loan.id,row.amount)
    row.source_type,row.source_id="loan",loan.id
    loan.version+=1
    audit("interest.accrue","loan",loan,{"voucher_id":row.id,"amount":row.amount})
    return [(ledger.account("interest_expense"),ledger.account("interest_payable"),row.amount)]


def serialize(loan, *, details=False):
    paid, balance = payment_totals(loan), remaining(loan)
    rows = schedule(loan)
    upcoming = next((row for row in rows if row["remaining"]), None)
    status = "closed" if loan.status in {"active", "closed"} and not sum(balance.values()) else loan.status
    result = {"id": loan.id, "number": loan.number, "direction": loan.direction, "party_name": loan.party_name,
        "branch_id": loan.branch_id, "person_id": loan.person_id, "principal": loan.principal,
        "interest": loan.interest, "fees": loan.fees, "upfront_fee": loan.upfront_fee,
        "received_amount": loan.principal-loan.upfront_fee, "paid_principal": paid["principal"],
        "remaining_principal": balance["principal"], "remaining_interest": balance["interest"], "remaining_fees": balance["fees"],
        "remaining_total": sum(balance.values()), "progress": int(paid["principal"]*100//loan.principal),
        "instalments": loan.instalments, "paid_instalments": sum(row["status"] == "paid" for row in rows),
        "next_due": upcoming["due_date"] if upcoming else None, "next_amount": upcoming["remaining"] if upcoming else 0,
        "overdue": sum(row["remaining"] for row in rows if row["status"] == "overdue") if status == "active" else 0,
        "treasury_account_id": loan.treasury_account_id, "starts_on": loan.starts_on.isoformat(),
        "first_due": loan.first_due.isoformat(), "status": status, "version": loan.version,
        "schedule_version": loan.schedule_version, "funding_voucher_id": loan.funding_voucher_id, "notes": loan.notes}
    result["pending_vouchers"]=[{"id":v.id,"number":v.number,"category":v.category,"amount":v.amount} for v in FinanceVoucher.query.filter(
        FinanceVoucher.party_type=="loan",FinanceVoucher.party_id==loan.id,FinanceVoucher.status=="pending").all()]
    if details:
        from .models import FinanceAttachment, FinanceAudit
        result["schedule"] = rows
        result["past_schedules"] = sorted({row[0] for row in db.session.query(FinanceInstalment.schedule_version).filter(
            FinanceInstalment.loan_id == loan.id, FinanceInstalment.schedule_version != loan.schedule_version).distinct().all()})
        result["schedule_history"]=[{"version":v,"rows":[{"number":i.number,"due_date":i.due_date.isoformat(),"principal":i.principal,"interest":i.interest,"fees":i.fees} for i in FinanceInstalment.query.filter_by(loan_id=loan.id,schedule_version=v).order_by(FinanceInstalment.number).all()]} for v in result["past_schedules"]]
        result["payments"] = [{"voucher_id": p.voucher_id, "principal": p.principal, "interest": p.interest, "fees": p.fees,
            "status": db.session.get(FinanceVoucher, p.voucher_id).status,
            "date": db.session.get(FinanceVoucher, p.voucher_id).transaction_date.isoformat()} for p in FinanceLoanPayment.query.filter_by(loan_id=loan.id).all()]
        result["salary_deductions"] = [{"payroll_item_id": p.payroll_item_id, "amount": p.amount} for p in HRAdvanceRepayment.query.filter_by(advance_id=loan.hr_advance_id).all()] if loan.hr_advance_id else []
        result["audit"] = [{"action": a.action, "at": a.created_at.isoformat(), "created_by": a.created_by,
            "details": json.loads(a.details)} for a in FinanceAudit.query.filter_by(source_type="loan", source_id=loan.id).order_by(FinanceAudit.id).all()]
        result["attachments"] = [{"id": a.id, "filename": a.filename} for a in FinanceAttachment.query.filter_by(source_type="loan", source_id=loan.id).all()]
    return result
