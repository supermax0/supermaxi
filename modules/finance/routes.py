"""Authenticated finance API and matching web/print views."""
import csv
import base64
import hashlib
import io
import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
from flask import Blueprint, current_app, jsonify, render_template, request, send_file
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy import func
from werkzeug.exceptions import HTTPException
from extensions import db
from models.account import Account
from models.branch import Branch
from models.customer import Customer
from models.expense import Expense
from models.fixed_asset_category import FixedAssetCategory
from models.invoice import Invoice
from models.purchase import Purchase
from models.supplier import Supplier
from models.treasury_account import TreasuryAccount
from modules.hr.models import HRPerson
from utils.financial_period_guard import PeriodClosedError
from utils.treasury_calculations import InsufficientTreasuryBalance, calculate_treasury_balance
from . import ledger, loans, reconciliation, reports, vouchers, cash_shifts, control
from .common import DEFAULT_ACCOUNTS, DEFAULT_POLICY, PERMISSIONS, FinanceError, actor, audit, can, command, day, dumps, get_row, money, policy, require, scope, tenant_key, text, today
from .models import FinanceAttachment, FinanceLoan, FinanceMapping, FinancePolicy, FinanceReconciliation, FinanceVoucher, FinanceCashShift
from .schema import ensure_schema

finance_bp = Blueprint("finance", __name__)


@finance_bp.before_request
def setup():
    require("finance.view")
    ensure_schema()


@finance_bp.errorhandler(FinanceError)
@finance_bp.errorhandler(PeriodClosedError)
@finance_bp.errorhandler(InsufficientTreasuryBalance)
def validation_error(exc):
    db.session.rollback()
    return jsonify({"success": False, "error": str(exc), "code": getattr(exc, "code", "validation")}), getattr(exc, "status", 400)


@finance_bp.errorhandler(IntegrityError)
@finance_bp.errorhandler(OperationalError)
def conflict_error(exc):
    db.session.rollback()
    current_app.logger.warning("Finance database conflict: %s", type(exc).__name__)
    return jsonify({"success": False, "error": "تغيّرت البيانات أو تعذر الحفظ؛ أعد المحاولة بنفس معرّف العملية", "code": "conflict"}), 409


@finance_bp.errorhandler(HTTPException)
def http_error(exc):
    db.session.rollback()
    return jsonify({"success":False,"error":"سجل الدخول بحساب مخول" if exc.code in {401,403} else exc.description,"code":"unauthorized" if exc.code in {401,403} else "request_error"}),exc.code


@finance_bp.errorhandler(Exception)
def unexpected_error(exc):
    db.session.rollback()
    current_app.logger.exception("Finance operation failed")
    return jsonify({"success":False,"error":"تعذر إكمال العملية؛ لم تُحفظ تغييراتها. أعد المحاولة أو راجع الإدارة","code":"server_error"}),500


def ok(data):
    return jsonify({"success": True, "data": data})


def payload():
    result = request.get_json(silent=True)
    if not isinstance(result, dict):
        raise FinanceError("أرسل بيانات عملية صحيحة")
    return result


def action(operation, data):
    if operation == "control.measure":
        control.authorize(measure=True)
    def run():
        if operation == "control.measure":
            return control.measure(data)
        if operation == "cash_shift.open":
            return cash_shifts.open_shift(data)
        if operation == "cash_shift.close":
            return cash_shifts.close_shift(get_row(FinanceCashShift, data.get("id")), data)
        if operation == "voucher.create":
            row = vouchers.create(data)
            intent = data.get("intent", "draft")
            if intent == "post":
                vouchers.approve(row)
            elif intent == "pending":
                vouchers.decide(row, "submit", {"version":row.version})
            elif intent != "draft":
                raise FinanceError("اختر الحفظ كمسودة أو طلب الاعتماد أو الترحيل")
            return vouchers.serialize(row, details=True)
        if operation.startswith("voucher."):
            row = get_row(FinanceVoucher, data.get("id"))
            name = operation.split(".")[1]
            if name == "edit":
                vouchers.edit(row, data)
            elif name == "reverse":
                vouchers.reverse(row, data)
            else:
                vouchers.decide(row, name, data)
            return vouchers.serialize(row, details=True)
        if operation == "credit.apply":
            return vouchers.serialize(vouchers.apply_credit(data), details=True)
        if operation == "loan.create":
            return loans.serialize(loans.create(data), details=True)
        if operation.startswith("loan."):
            row = get_row(FinanceLoan, data.get("id"))
            name = operation.split(".")[1]
            handlers = {"fund":loans.fund, "pay":loans.pay, "reschedule":loans.reschedule,
                        "close":loans.close, "accrue":loans.accrue_interest}
            if name not in handlers:
                raise FinanceError("إجراء قرض غير صالح")
            handlers[name](row, data)
            return loans.serialize(row, details=True)
        if operation == "reconciliation.create":
            return reconciliation.serialize(reconciliation.create(data))
        if operation == "reconciliation.match":
            return reconciliation.serialize(reconciliation.match(get_row(FinanceReconciliation, data.get("id")), data))
        if operation == "settings.save":
            return save_settings(data)
        if operation == "account.create":
            require("finance.settings")
            from .common import write_branch
            kind = data.get("account_type")
            if kind not in {"cash", "bank", "wallet"}:
                raise FinanceError("نوع الحساب غير صالح")
            row = TreasuryAccount(name=text(data.get("name"), 120, True), account_type=kind,
                branch_id=write_branch(data), is_active=True, is_default=False)
            db.session.add(row)
            db.session.flush()
            ledger.treasury_gl(row)
            audit("create", "account", row)
            return {"id":row.id, "name":row.name, "type":kind, "balance":0, "branch_id":row.branch_id}
        if operation in {"period.close", "period.reopen"}:
            require("finance.settings")
            from utils.financial_period_guard import close_financial_period, reopen_financial_period
            year, month = money(data.get("year")), money(data.get("month"))
            if year < 2000 or year > 2200 or month > 12:
                raise FinanceError("اختر فترة مالية صحيحة")
            if operation == "period.close":
                pending = reports.filtered({"status":"pending", "date_from":f"{year}-{month:02d}-01",
                    "date_to":(loans.monthly_date(day(f"{year}-{month:02d}-01"),1)-timedelta(days=1)).isoformat()}).count()
                if pending:
                    raise FinanceError("توجد سندات معلقة؛ راجعها قبل إقفال الفترة")
                row = close_financial_period(year,month,actor().id,text(data.get("reason"),1000,True))
                audit("period.close","period",row,{"year":year,"month":month})
            else:
                reason = text(data.get("reason"),1000,True)
                reopen_financial_period(year,month)
                audit("period.reopen","period",db.session.get(FinancePolicy,1),{"year":year,"month":month,"reason":reason})
            return {"year":year,"month":month,"closed":operation=="period.close"}
        if operation == "migration.apply":
            from .migration import apply
            return apply(data)
        raise FinanceError("عملية مالية غير معروفة")
    result = command(operation, data, run)
    return cash_shifts.guard_result(result) if operation in {"cash_shift.open", "cash_shift.close"} else result


@finance_bp.post("/api/finance/commands")
def commands():
    data = payload()
    operation = text(data.pop("operation", None), 50, True)
    return ok(action(operation, data))


@finance_bp.post("/api/finance/vouchers")
def create_voucher():
    return ok(action("voucher.create",payload()))


@finance_bp.post("/api/finance/vouchers/<int:row_id>/<operation>")
def voucher_action(row_id,operation):
    return ok(action(f"voucher.{operation}",{**payload(),"id":row_id}))


@finance_bp.post("/api/finance/loans")
def create_loan():
    return ok(action("loan.create",payload()))


@finance_bp.post("/api/finance/loans/<int:row_id>/payments")
def loan_payment(row_id):
    return ok(action("loan.pay",{**payload(),"id":row_id}))


@finance_bp.get("/api/finance/meta")
def meta():
    from utils.expense_categories import get_expense_categories
    return ok({"financial_control_available": True, "cash_shifts_available": True, "capabilities":{key:can(key) for key in PERMISSIONS}, "policy":{key:policy()[key] for key in DEFAULT_POLICY},
        "categories":[{"id":key,"kind":value[0],"label":value[1],"party_type":value[2],"activity":value[3],"help":value[4]}
                      for key,value in vouchers.CATEGORIES.items()],
        "accounts":[{"id":row.id,"name":row.name,"type":row.account_type,"branch_id":row.branch_id,"balance":calculate_treasury_balance(row.id)}
                    for row in ledger.visible_treasuries()],
        "branches":[{"id":row.id,"name":row.name} for row in Branch.query.filter_by(is_active=True).all()
                    if actor().role=="admin" or row.id==actor().branch_id],
        "expenses":get_expense_categories(),
        "asset_categories":[{"id":row.id,"name":row.name} for row in FixedAssetCategory.query.filter_by(is_active=True).all()]})


@finance_bp.get("/api/finance/cash-shifts")
def cash_shift_list():
    return ok(cash_shifts.listing(request.args))


@finance_bp.get("/api/finance/control/current")
def financial_control_current():
    return ok(control.current())


@finance_bp.get("/api/finance/control/snapshots")
def financial_control_snapshots():
    return ok(control.listing(request.args))


@finance_bp.get("/api/finance/control/snapshots/<int:row_id>")
def financial_control_snapshot(row_id):
    return ok(control.serialize(control.get_snapshot(row_id), details=True))


@finance_bp.get("/api/finance/control/compare")
def financial_control_compare():
    return ok(control.compare(request.args.get("start"), request.args.get("end")))


@finance_bp.get("/accounts/finance/control/snapshots/<int:row_id>/print")
def financial_control_snapshot_print(row_id):
    require("finance.print")
    return render_template("finance/control_print.html", snapshot=control.serialize(control.get_snapshot(row_id), details=True), comparison=None,
        local_time=_financial_control_print_time)


@finance_bp.get("/accounts/finance/control/compare/print")
def financial_control_comparison_print():
    require("finance.print")
    return render_template("finance/control_print.html", snapshot=None, comparison=control.compare(request.args.get("start"), request.args.get("end")),
        local_time=_financial_control_print_time)


def _financial_control_print_time(value):
    from utils.time_format import format_timestamp
    return format_timestamp(value, "%Y-%m-%d %H:%M:%S")


@finance_bp.get("/api/finance/cash-shifts/<int:row_id>")
def cash_shift_details(row_id):
    return ok(cash_shifts.details(row_id))


@finance_bp.get("/accounts/finance/cash-shifts/<int:row_id>/print")
def print_cash_shift(row_id):
    require("finance.print")
    from utils.time_format import format_timestamp
    data = cash_shifts.details(row_id)
    for field in ("opened_at", "closed_at"):
        data[field + "_local"] = format_timestamp(data[field], "%Y-%m-%d %H:%M:%S") if data[field] else "—"
    return render_template("finance/cash_shift_print.html", data=data)


@finance_bp.get("/api/finance/parties")
def party_search():
    kind = request.args.get("type","customer")
    model = {"customer":Customer,"supplier":Supplier,"employee":HRPerson,"loan":FinanceLoan}.get(kind)
    if not model:
        raise FinanceError("نوع الجهة غير صالح")
    field = model.party_name if kind=="loan" else model.name
    query = scope(model.query,model)
    if request.args.get("q"):
        query=query.filter(field.contains(request.args["q"][:150],autoescape=True))
    return ok({"items":[{"id":row.id,"name":getattr(row,"name",getattr(row,"party_name",""))}
                        for row in query.order_by(field).limit(100).all()]})


@finance_bp.get("/api/finance/parties/<kind>/<int:row_id>")
def party_detail(kind,row_id):
    model = {"customer":Customer,"supplier":Supplier}.get(kind)
    if not model:
        raise FinanceError("نوع الجهة غير صالح")
    row = get_row(model,row_id)
    invoices=[]
    debt_total=0
    if kind=="customer":
        from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES
        query=scope(Invoice.query,Invoice).filter(Invoice.customer_id==row.id,
            Invoice.status.notin_(list(CANCELED_STATUSES)+list(RETURN_STATUSES)),Invoice.total>func.coalesce(Invoice.paid_amount,0))
        debt_total=int(query.with_entities(func.coalesce(func.sum(Invoice.total-func.coalesce(Invoice.paid_amount,0)),0)).scalar())
        for invoice in query.order_by(Invoice.created_at,Invoice.id).limit(200).all():
            invoices.append({"id":invoice.id,"number":str(invoice.id),"total":invoice.total,
                "paid":invoice.paid_amount or 0,"remaining":invoice.total-(invoice.paid_amount or 0),"type":"invoice"})
        from models.customer_credit import CustomerCreditPlan
        query=CustomerCreditPlan.query.filter(CustomerCreditPlan.customer_id==row.id,
            CustomerCreditPlan.invoice_id.is_(None),CustomerCreditPlan.total_amount>func.coalesce(CustomerCreditPlan.paid_amount,0))
        debt_total+=int(query.with_entities(func.coalesce(func.sum(CustomerCreditPlan.total_amount-func.coalesce(CustomerCreditPlan.paid_amount,0)),0)).scalar())
        for plan in query.order_by(CustomerCreditPlan.created_at,CustomerCreditPlan.id).limit(200).all():
            invoices.append({"id":plan.id,"number":f"دين مستقل #{plan.id}","total":plan.total_amount,
                "paid":plan.paid_amount or 0,"remaining":plan.remaining,"type":"customer_debt"})
    else:
        from utils.supplier_payment_allocation import effective_purchase_payment_totals
        records=scope(Purchase.query,Purchase).filter(Purchase.supplier_id==row.id,
            Purchase.status.notin_(["draft","draft_editing","cancelled","canceled"])).order_by(Purchase.created_at).limit(200).all()
        paid={record.id:effective_purchase_payment_totals(record)[0] for record in records}
        for record in records:
            total=record.grand_total or record.total or 0
            used=paid.get(record.id,0)
            if total>used:
                invoices.append({"id":record.id,"number":record.invoice_no or str(record.id),"total":total,
                    "paid":used,"remaining":total-used,"type":"purchase"})
    return ok({"id":row.id,"name":row.name,"branch_id":row.branch_id,"credit":vouchers.outstanding_credit(kind,row.id),
        "debt":debt_total if kind=="customer" else max(0,row.remaining),"invoices":invoices,
        "movements":[vouchers.serialize(record) for record in reports.filtered({"party_type":kind,"party_id":str(row.id)}).order_by(FinanceVoucher.id).all()]})


@finance_bp.get("/api/finance/vouchers")
def voucher_list():
    query = reports.filtered(request.args)
    page,count=money(request.args.get("page",1)),min(100,money(request.args.get("page_size",25)))
    return ok({"items":[vouchers.serialize(row) for row in query.order_by(FinanceVoucher.id.desc()).offset((page-1)*count).limit(count).all()],
        "total":query.count(),"page":page,"page_size":count,"stats":reports.stats(request.args)})


@finance_bp.get("/api/finance/vouchers/<int:row_id>")
def voucher_detail(row_id):
    return ok(vouchers.serialize(get_row(FinanceVoucher,row_id),details=True))


@finance_bp.get("/api/finance/loans")
def loan_list():
    query=scope(FinanceLoan.query,FinanceLoan)
    if request.args.get("q"):
        query=query.filter(FinanceLoan.party_name.contains(request.args["q"][:150],autoescape=True))
    if request.args.get("direction"):
        query=query.filter_by(direction=request.args["direction"])
    if request.args.get("status"):
        query=query.filter_by(status=request.args["status"])
    for key in ("treasury_account_id","branch_id"):
        if request.args.get(key):
            query=query.filter(getattr(FinanceLoan,key)==money(request.args[key]))
    if request.args.get("date_from"):
        query=query.filter(FinanceLoan.starts_on>=day(request.args["date_from"]))
    if request.args.get("date_to"):
        query=query.filter(FinanceLoan.starts_on<=day(request.args["date_to"]))
    page,count=money(request.args.get("page",1)),min(100,money(request.args.get("page_size",25)))
    items=[loans.serialize(row) for row in query.order_by(FinanceLoan.id.desc()).offset((page-1)*count).limit(count).all()]
    return ok({"items":items,"total":query.count(),"page":page,"page_size":count,"stats":reports.loan_stats([loans.serialize(row) for row in query.all()])})


@finance_bp.get("/api/finance/loans/<int:row_id>")
@finance_bp.get("/api/finance/loans/<int:row_id>/schedule")
def loan_detail(row_id):
    return ok(loans.serialize(get_row(FinanceLoan,row_id),details=True))


@finance_bp.get("/api/finance/accounts")
def accounts():
    return meta()


@finance_bp.get("/api/finance/accounts/<int:row_id>/ledger")
def account_ledger(row_id):
    account=ledger.treasury(row_id)
    return ok({"id":account.id,"name":account.name,"balance":calculate_treasury_balance(row_id),
        "movements":reconciliation.movements(account,day(request.args["date_from"]) if request.args.get("date_from") else None,
            day(request.args["date_to"]) if request.args.get("date_to") else None)})


@finance_bp.get("/api/finance/journal")
def journals():
    require("finance.ledger")
    return ok(reports.journal_rows(request.args))


@finance_bp.get("/api/finance/reports/<report>")
def financial_report(report):
    require("finance.ledger")
    return ok(report_data(report,request.args))


def report_data(report,args):
    if report in {"customer-aging","supplier-aging","instalments","employee-advances","reconciliation-differences"}:
        return reports.operational_report(report,args)
    if report=="cash-flow":
        return reports.cash_flow(args)
    if report in {"trial-balance","profit-loss","balance-sheet"}:
        filters=dict(args)
        if report=="balance-sheet":
            filters.pop("date_from",None)
        data=reports.trial_balance(filters)
        if report!="trial-balance":
            types={"revenue","expense"} if report=="profit-loss" else {"asset","liability","equity"}
            data["rows"]=[r for r in data["rows"] if r["type"] in types]
        return data
    raise FinanceError("التقرير غير موجود","not_found",404)


@finance_bp.get("/accounts/finance/reports/<report>/print")
def print_report(report):
    require("finance.print")
    require("finance.ledger")
    from models.invoice_settings import InvoiceSettings
    titles={"trial-balance":"ميزان المراجعة","profit-loss":"الأرباح والخسائر","balance-sheet":"الميزانية العمومية","cash-flow":"التدفق النقدي",
        "customer-aging":"أعمار ديون العملاء","supplier-aging":"أعمار ديون الموردين","instalments":"الأقساط القادمة والمتأخرة",
        "employee-advances":"سلف الموظفين","reconciliation-differences":"التسويات والفروقات"}
    return render_template("finance/report_print.html",data=report_data(report,request.args),report=report,
        title=titles[report],date_from=request.args.get("date_from", ""),date_to=request.args.get("date_to", ""),settings=InvoiceSettings.get_settings())


@finance_bp.get("/api/finance/notifications")
def notifications():
    return ok({"items":reports.notifications()})


@finance_bp.get("/api/finance/reconciliations")
def reconciliations():
    require("finance.reconcile")
    return ok({"items":[reconciliation.serialize(row) for row in scope(FinanceReconciliation.query,FinanceReconciliation).order_by(FinanceReconciliation.id.desc()).limit(50).all()]})


@finance_bp.get("/api/finance/settings")
def settings():
    require("finance.settings")
    return ok({"policy":{key:policy()[key] for key in DEFAULT_POLICY},"mappings":[{"key":row.key,"account_id":row.account_id,"name":row.account.name,"type":row.account.account_type}
        for row in FinanceMapping.query.order_by(FinanceMapping.key).all()],
        "chart":[{"id":row.id,"name":row.name,"code":row.code,"type":row.account_type} for row in Account.query.filter_by(is_active=True).all()]})


def save_settings(data):
    require("finance.settings")
    original=policy()
    requested=data.get("policy",{})
    if not isinstance(requested,dict):
        raise FinanceError("إعدادات غير صالحة")
    for key,value in requested.items():
        if key not in DEFAULT_POLICY:
            raise FinanceError("إعداد غير قابل للتغيير من هذا المسار")
        if isinstance(DEFAULT_POLICY[key],bool):
            if not isinstance(value,bool):
                raise FinanceError("اختر قيمة إعداد صحيحة")
            original[key]=value
        else:
            original[key]=money(value,minimum=0)
    for item in data.get("mappings",[]):
        row=db.session.get(FinanceMapping,text(item.get("key"),80,True))
        target=db.session.get(Account,money(item.get("account_id")))
        if not row or not target or not target.is_active or target.account_type!=row.account.account_type:
            raise FinanceError("نوع حساب الربط لا يطابق المعالجة المطلوبة")
        if row.account_id!=target.id and row.account.balance:
            raise FinanceError("حساب الربط عليه رصيد؛ رحّل إعادة التصنيف أولاً حتى لا تتغير المعالجة التاريخية")
        row.account_id=target.id
    record=db.session.get(FinancePolicy,1)
    record.settings=dumps(original)
    audit("settings.save","settings",record,{"policy":original,"mappings":data.get("mappings",[])})
    return {"policy":original}


@finance_bp.get("/api/finance/migration/preview")
def migration_preview():
    require("finance.settings")
    from .migration import preview
    return ok(preview())


@finance_bp.get("/api/finance/vouchers/export")
def export():
    require("finance.print")
    return current_app.response_class(export_csv(),mimetype="text/csv",headers={"Content-Disposition":"attachment; filename=finora-vouchers.csv"})


def export_csv():
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(["رقم السند","التاريخ","النوع","التصنيف","الجهة","الحساب","المبلغ","الحالة","الموظف"])
    for row in reports.filtered(request.args).order_by(FinanceVoucher.id).yield_per(100):
        item=vouchers.serialize(row)
        values=[item[key] for key in ("number","transaction_date","kind","category_label","party_name","account_name","amount","status","created_by_name")]
        writer.writerow(["'"+value if isinstance(value,str) and value.startswith(("=","+","-","@")) else value for value in values])
    return "\ufeff"+output.getvalue()


@finance_bp.get("/api/finance/vouchers/export/content")
def export_content():
    require("finance.print")
    return ok({"filename":"FINORA-finance.csv","content":export_csv()})


@finance_bp.get("/accounts/finance")
def index():
    return render_template("finance/index.html")


@finance_bp.get("/accounts/finance/vouchers/<int:row_id>/print")
def print_voucher(row_id):
    require("finance.print")
    from models.invoice_settings import InvoiceSettings
    return render_template("finance/print.html",kind="voucher",data=vouchers.serialize(get_row(FinanceVoucher,row_id),details=True),settings=InvoiceSettings.get_settings())


@finance_bp.get("/accounts/finance/loans/<int:row_id>/print")
def print_loan(row_id):
    require("finance.print")
    from models.invoice_settings import InvoiceSettings
    return render_template("finance/print.html",kind="loan",data=loans.serialize(get_row(FinanceLoan,row_id),details=True),settings=InvoiceSettings.get_settings())


def attachment_root():
    return Path(current_app.instance_path)/"private_finance"/hashlib.sha256(tenant_key().encode()).hexdigest()


@finance_bp.post("/api/finance/attachments/<kind>/<int:row_id>")
def upload(kind,row_id):
    require("finance.create")
    model={"voucher":FinanceVoucher,"loan":FinanceLoan}.get(kind)
    if not model:
        raise FinanceError("نوع مستند غير صالح")
    row=get_row(model,row_id)
    if row.created_by!=actor().id and not can("finance.approve"):
        raise FinanceError("لا يمكن إرفاق مستند لهذا السجل","forbidden",403)
    file=request.files.get("file")
    if not file:
        raise FinanceError("اختر المرفق")
    content=file.read(10*1024*1024+1)
    if not content or len(content)>10*1024*1024:
        raise FinanceError("حجم المرفق يجب ألا يتجاوز 10 ميغابايت")
    signatures=[(b"%PDF-","application/pdf","pdf"),(b"\x89PNG\r\n\x1a\n","image/png","png"),(b"\xff\xd8\xff","image/jpeg","jpg")]
    detected=next((item for item in signatures if content.startswith(item[0])),None)
    if not detected:
        raise FinanceError("المرفقات المسموحة PDF أو PNG أو JPEG")
    root=attachment_root()
    root.mkdir(parents=True,exist_ok=True)
    storage=f"{uuid4().hex}.{detected[2]}"
    target=root/storage
    target.write_bytes(content)
    try:
        item=FinanceAttachment(source_type=kind,source_id=row.id,filename=text(Path(file.filename or "مرفق").name,200,True),
            storage_key=storage,mime_type=detected[1],created_by=actor().id)
        db.session.add(item)
        db.session.flush()
        audit("attachment.add",kind,row,{"attachment_id":item.id})
        db.session.commit()
    except Exception:
        target.unlink(missing_ok=True)
        db.session.rollback()
        raise
    return ok({"id":item.id,"filename":item.filename})


@finance_bp.get("/api/finance/attachments/<int:row_id>")
def download(row_id):
    item=db.session.get(FinanceAttachment,row_id)
    if not item:
        raise FinanceError("المرفق غير موجود","not_found",404)
    get_row(FinanceVoucher if item.source_type=="voucher" else FinanceLoan,item.source_id)
    return send_file(attachment_root()/item.storage_key,mimetype=item.mime_type,as_attachment=True,
        download_name=item.filename,max_age=0)


@finance_bp.get("/api/finance/attachments/<int:row_id>/content")
def attachment_content(row_id):
    item=db.session.get(FinanceAttachment,row_id)
    if not item:
        raise FinanceError("المرفق غير موجود","not_found",404)
    get_row(FinanceVoucher if item.source_type=="voucher" else FinanceLoan,item.source_id)
    target=attachment_root()/item.storage_key
    if not target.is_file():
        raise FinanceError("ملف المرفق غير موجود","not_found",404)
    return ok({"filename":item.filename,"mime":item.mime_type,"content":base64.b64encode(target.read_bytes()).decode("ascii")})
