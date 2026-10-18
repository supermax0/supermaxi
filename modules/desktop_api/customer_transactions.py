"""Read-only customer collection history; source copies never become extra money."""
import csv
import io
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import jsonify, render_template, session
from sqlalchemy import String, and_, case, cast, func, inspect, literal, or_, select, union_all
from sqlalchemy.orm import aliased

from extensions import db
from models.customer import Customer
from models.account_transaction import AccountTransaction
from models.customer_credit import CustomerCreditPlan, CustomerCreditPayment
from models.invoice import Invoice
from models.invoice_payment_ledger import InvoicePaymentLedger
from modules.finance.models import FinanceVoucher
from modules.desktop_api.customers import _authorize, _invoices, _pagination, _plans, _scoped, _today, _workspace_query
from services.reports_service import effective_paid_expr
from utils.order_status import CANCELED_STATUSES, RETURN_STATUSES
from modules.desktop_api.routes import desktop_api_bp, _error

CATEGORIES = {
    "customer_payment": "تحصيل دين", "customer_credit_apply": "تسوية رصيد مقدم",
    "customer_advance": "رصيد مقدم", "customer_refund": "استرداد رصيد مقدم",
}


def _customer(customer_id):
    return _scoped(Customer.query, Customer).filter_by(id=customer_id).first()


def _vouchers(customer_id):
    return _scoped(FinanceVoucher.query, FinanceVoucher).filter(
        FinanceVoucher.tenant_key == session["tenant_slug"], FinanceVoucher.party_type == "customer",
        FinanceVoucher.party_id == customer_id, FinanceVoucher.status.in_(["posted", "reversed"]))


def _history(customer_id):
    # GET never installs finance, initializes tables, or migrates old ledger columns.
    inspector = inspect(db.session.connection())
    has_finance = inspector.has_table(FinanceVoucher.__tablename__)
    has_ledger = inspector.has_table(InvoicePaymentLedger.__tablename__)
    sources = []
    invoices = _invoices().filter_by(customer_id=customer_id).with_entities(Invoice.id)
    plans = _plans().filter_by(customer_id=customer_id, invoice_id=None).with_entities(CustomerCreditPlan.id)
    voucher_ids = _vouchers(customer_id).with_entities(FinanceVoucher.id) if has_finance else None

    if has_finance:
        original = aliased(FinanceVoucher)
        category = case((FinanceVoucher.category == "reversal", original.category), else_=FinanceVoucher.category)
        sign = case((FinanceVoucher.category == "reversal", -1), else_=1)
        label = case(*[(category == key, literal(value)) for key, value in CATEGORIES.items()], else_="حركة مالية")
        description = case((FinanceVoucher.category == "reversal", literal("عكس ") + label), else_=label)
        sources.append(_vouchers(customer_id).outerjoin(original, and_(
            original.reversal_id == FinanceVoucher.id, original.tenant_key == FinanceVoucher.tenant_key,
            original.party_type == "customer", original.party_id == customer_id,
            original.branch_id == FinanceVoucher.branch_id)).filter(category.in_(list(CATEGORIES))).with_entities(
                literal("voucher").label("kind"), FinanceVoucher.id.label("id"),
                cast(FinanceVoucher.transaction_date, String).label("date"), description.label("description"),
                (FinanceVoucher.amount * sign).label("amount"),
                case((FinanceVoucher.kind == "receipt", FinanceVoucher.amount),
                     (FinanceVoucher.kind == "payment", -FinanceVoucher.amount), else_=0).label("cash"),
                case((category.in_(["customer_payment", "customer_credit_apply"]), -FinanceVoucher.amount * sign), else_=0).label("debt_change"),
                case((category == "customer_advance", FinanceVoucher.amount * sign),
                     (category.in_(["customer_refund", "customer_credit_apply"]), -FinanceVoucher.amount * sign), else_=0).label("advance_change"),
                FinanceVoucher.number.label("document"), literal(None).label("invoice_id"),
                literal(None).label("plan_id"), FinanceVoucher.id.label("voucher_id"),
                FinanceVoucher.status.label("status"), FinanceVoucher.notes.label("note")).statement)

    if has_ledger:
        columns = {row["name"] for row in inspector.get_columns(InvoicePaymentLedger.__tablename__)}
        # Select only physical fields, including on pre-migration tenants.
        table = InvoicePaymentLedger.__table__
        source = table.c.source_module if "source_module" in columns else literal(None)
        method = table.c.payment_method if "payment_method" in columns else literal(None)
        note = table.c.note if "note" in columns else literal("")
        query = db.session.query(table).execution_options(skip_branch_scope=True).filter(table.c.invoice_id.in_(invoices))
        if has_finance:
            query = query.filter(~select(FinanceVoucher.id).where(
                FinanceVoucher.id.in_(voucher_ids),
                source == literal("finance:") + cast(FinanceVoucher.id, String)).exists())
        baseline = source.in_(["invoice_legacy_baseline", "finance_legacy_baseline"])
        sources.append(query.with_entities(literal("invoice_payment").label("kind"), table.c.id.label("id"),
            case((baseline, literal(None)), else_=cast(table.c.recorded_at, String)).label("date"),
            case((baseline, "تحصيل سابق محفوظ"), (method == "finance_offset", "تسوية فاتورة"),
                 (table.c.amount_delta < 0, "تخفيض تحصيل فاتورة"), else_="تحصيل فاتورة").label("description"),
            table.c.amount_delta.label("amount"),
            case((baseline, literal(None)), (method == "finance_offset", 0), else_=table.c.amount_delta).label("cash"),
            (-table.c.amount_delta).label("debt_change"), literal(0).label("advance_change"),
            (literal("فاتورة #") + cast(table.c.invoice_id, String)).label("document"),
            table.c.invoice_id.label("invoice_id"), literal(None).label("plan_id"), literal(None).label("voucher_id"),
            literal("recorded").label("status"), note.label("note")).statement)

    if inspector.has_table(CustomerCreditPayment.__tablename__):
        payment = CustomerCreditPayment
        cash = literal(None)
        if inspector.has_table(AccountTransaction.__tablename__):
            cash = _scoped(db.session.query(func.sum(case((AccountTransaction.type == "deposit", AccountTransaction.amount),
                (AccountTransaction.type == "withdraw", -AccountTransaction.amount), else_=0))), AccountTransaction).filter(
                    AccountTransaction.note.like(literal("%[CP:") + cast(payment.id, String) + literal("]%"))).scalar_subquery()
        query = payment.query.execution_options(skip_branch_scope=True).filter(
            payment.customer_id == customer_id, payment.plan_id.in_(plans))
        if has_finance:
            query = query.filter(~select(FinanceVoucher.id).where(FinanceVoucher.id.in_(voucher_ids),
                payment.note.like(literal("[FV:") + cast(FinanceVoucher.id, String) + literal("]%"))).exists())
        sources.append(query.with_entities(literal("debt_payment").label("kind"), payment.id.label("id"),
            cast(payment.created_at, String).label("date"),
            case((payment.amount < 0, "عكس دفعة دين مستقل"), else_="دفعة دين مستقل").label("description"),
            payment.amount.label("amount"), cash.label("cash"), (-payment.amount).label("debt_change"),
            literal(0).label("advance_change"), (literal("دين مستقل #") + cast(payment.plan_id, String)).label("document"),
            literal(None).label("invoice_id"), payment.plan_id.label("plan_id"), literal(None).label("voucher_id"),
            literal("recorded").label("status"), payment.note.label("note")).statement)
    if not sources:
        sources.append(select(literal("invoice_payment").label("kind"), literal(0).label("id"),
            literal(None).label("date"), literal("").label("description"), literal(0).label("amount"),
            literal(None).label("cash"), literal(0).label("debt_change"), literal(0).label("advance_change"),
            literal("").label("document"), literal(None).label("invoice_id"), literal(None).label("plan_id"),
            literal(None).label("voucher_id"), literal("").label("status"), literal("").label("note")).where(False))
    records = union_all(*sources).subquery()
    return db.session.query(records).execution_options(skip_branch_scope=True), records


def _summary(customer_id, query, records):
    workspace, _, _ = _workspace_query()
    current = workspace.filter(Customer.id == customer_id).first()
    advance = int(query.with_entities(func.coalesce(func.sum(records.c.advance_change), 0)).scalar())
    inspector = inspect(db.session.connection())
    recorded = literal(0)
    if inspector.has_table(InvoicePaymentLedger.__tablename__):
        recorded = select(func.coalesce(func.sum(InvoicePaymentLedger.amount_delta), 0)).where(
            InvoicePaymentLedger.invoice_id == Invoice.id).scalar_subquery()
    difference = effective_paid_expr() - recorded
    dead = list(CANCELED_STATUSES | RETURN_STATUSES)
    invoices = _invoices().execution_options(skip_branch_scope=True).filter(Invoice.customer_id == customer_id,
        Invoice.shipping_company_id.is_(None), Invoice.status.notin_(dead),
        or_(Invoice.payment_status.is_(None), Invoice.payment_status.notin_(dead)), Invoice.is_stock_locked.is_not(True))
    invoice_gaps = invoices.with_entities(func.count(Invoice.id), func.coalesce(func.sum(func.abs(difference)), 0)).filter(difference != 0).one()
    paid = literal(0)
    if inspector.has_table(CustomerCreditPayment.__tablename__):
        paid = select(func.coalesce(func.sum(CustomerCreditPayment.amount), 0)).where(
            CustomerCreditPayment.plan_id == CustomerCreditPlan.id, CustomerCreditPayment.customer_id == customer_id).scalar_subquery()
    gap = func.coalesce(CustomerCreditPlan.paid_amount, 0) - paid
    plan_gaps = _plans().execution_options(skip_branch_scope=True).filter_by(customer_id=customer_id, invoice_id=None).with_entities(
        func.count(CustomerCreditPlan.id), func.coalesce(func.sum(func.abs(gap)), 0)).filter(gap != 0).one()
    return {"debt": int(current[1]), "advance": max(0, advance), "net_due": int(current[1]) - max(0, advance),
        "unexplained_documents": int(invoice_gaps[0] + plan_gaps[0]), "unexplained_amount": int(invoice_gaps[1] + plan_gaps[1])}


def _ordered(query, records):
    return query.order_by(records.c.date.desc(), records.c.kind, records.c.id.desc())


def _business_date(value):
    if not value: return "غير محدد"
    if len(value) == 10: return value
    instant = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    return instant.astimezone(ZoneInfo("Asia/Baghdad")).strftime("%Y-%m-%d")


def _serialize(row):
    value = row._asdict()
    if value["date"] and value["kind"] != "voucher":
        value["date"] = value["date"].replace(" ", "T") + "Z"
    return value


@desktop_api_bp.get("/customers/<int:customer_id>/transactions")
def customer_transactions(customer_id):
    denied = _authorize()
    if denied: return denied
    if not _customer(customer_id): return _error("العميل غير موجود أو خارج الفروع المسموحة", 404, "not_found")
    paging = _pagination()
    if not paging: return _error("الصفحة غير صحيحة", 400, "validation")
    page, size = paging
    query, records = _history(customer_id)
    rows = [_serialize(row) for row in _ordered(query, records).offset((page-1)*size).limit(size)]
    return jsonify(success=True, data={"items": rows, "total": query.count(), "page": page,
        "page_size": size, "summary": _summary(customer_id, query, records), "as_of": _today().isoformat()})


@desktop_api_bp.get("/customers/<int:customer_id>/transactions/print")
def customer_transactions_print(customer_id):
    denied = _authorize()
    if denied: return denied
    customer = _customer(customer_id)
    if not customer: return _error("العميل غير موجود أو خارج الفروع المسموحة", 404, "not_found")
    query, records = _history(customer_id)
    from models.invoice_settings import InvoiceSettings
    return render_template("customers/transactions_print.html", customer=customer,
        rows=_ordered(query, records).all(), summary=_summary(customer_id, query, records),
        settings=InvoiceSettings.query.first(), as_of=_today().isoformat(), business_date=_business_date)


@desktop_api_bp.get("/customers/<int:customer_id>/transactions/export")
def customer_transactions_export(customer_id):
    denied = _authorize()
    if denied: return denied
    if not _customer(customer_id): return _error("العميل غير موجود أو خارج الفروع المسموحة", 404, "not_found")
    query, records = _history(customer_id)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["التاريخ", "الحركة", "المستند", "المبلغ", "حركة النقد", "تغير الدين", "تغير الرصيد المقدم", "الحالة", "ملاحظة"])
    def safe(value):
        text = str(value or "")
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text
    for row in _ordered(query, records).yield_per(500):
        writer.writerow([_business_date(row.date), safe(row.description), safe(row.document), row.amount,
            row.cash if row.cash is not None else "غير محدد", row.debt_change, row.advance_change,
            "معكوس" if row.status == "reversed" else "مسجل", safe(row.note)])
    return jsonify(success=True, data={"content": output.getvalue(), "filename": f"customer-{customer_id}-collections.csv"})
