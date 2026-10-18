"""Employee payables follow posted journals; advance receivables stay separate."""
from datetime import datetime
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload
from models.journal_entry import JournalEntry
from models.employee_payment import EmployeePayment
from .common import BAGHDAD, day, integer, own, person, require
from .models import (HRPayrollItem, HRPayrollPayment, HRCommission, HRCommissionPayment,
                     HRCommissionChange, HRAdvance)


def statement(args, paginate=True):
    employee=person(integer(args.get("person_id"),minimum=1))
    if not own(employee):
        for permission in ("hr.payroll.view","hr.commission.view","hr.advance.view"):
            require(permission)
    first=day(args["date_from"]) if args.get("date_from") else None
    last=day(args["date_to"]) if args.get("date_to") else None
    if first and last and first>last:raise ValueError("بداية الفترة بعد نهايتها")
    items=HRPayrollItem.query.with_entities(HRPayrollItem.id).filter_by(person_id=employee.id)
    commissions=HRCommission.query.with_entities(HRCommission.id).filter_by(person_id=employee.id)
    salary_payments=HRPayrollPayment.query.with_entities(HRPayrollPayment.payment_id).filter(HRPayrollPayment.payroll_item_id.in_(items))
    commission_payments=HRCommissionPayment.query.with_entities(HRCommissionPayment.payment_id).filter(HRCommissionPayment.commission_id.in_(commissions))
    changes=HRCommissionChange.query.with_entities(HRCommissionChange.id).filter(HRCommissionChange.commission_id.in_(commissions))
    refs={"hr_payroll_accrual":items,"hr_wage_deduction":items,"hr_advance_deduction":items,
          "hr_payroll_payment":salary_payments,"hr_commission_accrual":commissions,
          "hr_commission_payment":commission_payments,"hr_commission_change":changes}
    journals=JournalEntry.query.options(joinedload(JournalEntry.debit_account),joinedload(JournalEntry.credit_account)).filter(or_(
        *(and_(JournalEntry.reference_type==kind,JournalEntry.reference_id.in_(ids)) for kind,ids in refs.items()))).order_by(JournalEntry.entry_date,JournalEntry.id).all()
    labels={"hr_payroll_accrual":"راتب مستحق","hr_wage_deduction":"استقطاع أجر",
            "hr_advance_deduction":"تسوية قسط سلفة","hr_payroll_payment":"دفعة راتب",
            "hr_commission_accrual":"عمولة معتمدة","hr_commission_payment":"دفعة عمولة",
            "hr_commission_change":"تسوية عمولة"}
    events=[]
    for row in journals:
        credit=row.credit_account.code=="2102"
        debit=row.debit_account.code=="2102"
        if not credit and not debit:continue
        cash=row.reference_type in ("hr_payroll_payment","hr_commission_payment")
        events.append({"key":f"journal:{row.id}","date":row.entry_date.isoformat()+"Z","label":labels[row.reference_type],
            "due":row.amount if credit else 0,"paid":row.amount if debit and cash else 0,
            "adjustment":row.amount if debit and not cash else 0,
            "document":{"kind":"journal","id":row.id,"number":row.entry_number,"reference_type":row.reference_type,
                        "reference_id":row.reference_id,"description":row.description,"debit":row.debit_account.name,"credit":row.credit_account.name,"amount":row.amount}})
    # Before HR accruals, legacy salary/commission payouts were direct expenses.
    # Show each as a closed historic entitlement and payment, never a new payable.
    if employee.employee_id:
        old=EmployeePayment.query.filter_by(payee_type="employee",payee_id=employee.employee_id).filter(
            ~EmployeePayment.id.in_(salary_payments),~EmployeePayment.id.in_(commission_payments)).all()
        for row in old:
            events.append({"key":f"payment:{row.id}","date":row.paid_at.isoformat()+"Z","label":"صرف سابق مغلق",
                "due":row.amount,"paid":row.amount,"adjustment":0,
                "document":{"kind":"payment","id":row.id,"number":row.voucher_code or f"PAY-{row.id}",
                            "reference_type":row.payment_kind,"reference_id":row.id,"description":row.note or "دفعة من السجل السابق؛ تاريخ نشوء استحقاقها غير محفوظ بالمسير الجديد",
                            "debit":"مصروف سابق","credit":"خزينة","amount":row.amount}})
    events.sort(key=lambda r:(r["date"],r["document"]["id"],r["key"]))
    opening=0;balance=0;rows=[]
    for row in events:
        # Filtering uses the same Baghdad day displayed by the desktop.
        local=datetime.fromisoformat(row["date"].replace("Z","+00:00")).astimezone(BAGHDAD).date()
        if last and local>last:continue
        balance+=row["due"]-row["paid"]-row["adjustment"]
        if first and local<first:
            opening=balance
            continue
        rows.append({**row,"balance":balance})
    advances=[{"id":r.id,"amount":r.amount,"repaid":r.repaid,"remaining":r.amount-r.repaid,"reason":r.reason,"status":r.status}
              for r in HRAdvance.query.filter(HRAdvance.person_id==employee.id,HRAdvance.status.in_(("paid","repaying","repaid"))).order_by(HRAdvance.id).all()]
    page=integer(args.get("page",1),minimum=1)
    size=integer(args.get("page_size",25),minimum=1,maximum=100)
    total=len(rows)
    return {"person_id":employee.id,"name":employee.name,"code":employee.code,"opening":opening,"balance":balance,
            "due":sum(r["due"] for r in rows),"paid":sum(r["paid"] for r in rows),"adjustment":sum(r["adjustment"] for r in rows),
            "rows":rows[(page-1)*size:page*size] if paginate else rows,"total":total,"page":page,"total_pages":max(1,(total+size-1)//size),
            "advances":advances,"advance_remaining":sum(r["remaining"] for r in advances)}
