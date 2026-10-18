"""Documented customer debt origins and collections. Reading never migrates or posts."""
import csv
import io
import json
from collections import defaultdict
from datetime import date

from flask import jsonify, render_template, request, session
from sqlalchemy import and_, inspect, or_

from extensions import db
from models.invoice import Invoice
from models.customer_credit import CustomerCreditPlan
from modules.finance.models import FinanceJournalLink, FinanceVoucher
from .customer_transactions import _customer, _history, _serialize, _summary, _business_date
from .customers import _authorize, _invoices, _plans, _pagination, _scoped, _today
from .routes import desktop_api_bp, _error

LIMIT = 20000


class StatementError(ValueError):
    pass


def _day(name):
    value = request.args.get(name)
    if not value:
        return None
    try:
        result = date.fromisoformat(value)
        if result.isoformat() != value:
            raise ValueError()
        return value
    except ValueError:
        raise StatementError("التاريخ غير صالح؛ استخدم سنة-شهر-يوم")


def _statement(customer_id):
    start, end = _day("date_from"), _day("date_to")
    if start and end and start > end:
        raise StatementError("بداية الفترة بعد نهايتها")
    query, records = _history(customer_id)
    if query.count() > LIMIT:
        raise StatementError("السجل يتجاوز 20 ألف حركة؛ يحتاج تصديراً موسعاً")
    rows = [_serialize(row) for row in query.all()]
    summary = _summary(customer_id, query, records)
    inspector = inspect(db.session.connection())
    invoices = _invoices().filter_by(customer_id=customer_id).with_entities(Invoice.id, Invoice.total, Invoice.created_at)
    plans = _plans().filter_by(customer_id=customer_id, invoice_id=None).with_entities(CustomerCreditPlan.id, CustomerCreditPlan.total_amount, CustomerCreditPlan.created_at)
    if invoices.count() + plans.count() > LIMIT:
        raise StatementError("عدد مستندات العميل يتجاوز نطاق الكشف الحالي")
    invoice_rows, plan_rows = invoices.all(), plans.all()
    invoice_ids, plan_ids = {row.id for row in invoice_rows}, {row.id for row in plan_rows}
    created = {("invoice", row.id): row.created_at for row in invoice_rows}
    created.update({("plan", row.id): row.created_at for row in plan_rows})
    archived_keys = set()
    births, origins = set(), set()
    malformed = 0
    if inspector.has_table(FinanceVoucher.__tablename__) and inspector.has_table(FinanceJournalLink.__tablename__):
        source = _scoped(FinanceVoucher.query, FinanceVoucher).filter(
            FinanceVoucher.tenant_key == session["tenant_slug"],
            FinanceVoucher.status.in_(["posted", "reversed"]),
            FinanceVoucher.source_type.in_(["invoice_auto", "customer_debt_auto"]),
            or_(and_(FinanceVoucher.party_type == "customer", FinanceVoucher.party_id == customer_id),
                and_(FinanceVoucher.party_type != "customer", FinanceVoucher.source_type == "invoice_auto", FinanceVoucher.source_id.in_(invoice_ids))),
            FinanceVoucher.id.in_(db.session.query(FinanceJournalLink.voucher_id)))
        if source.count() + len(rows) > LIMIT:
            raise StatementError("السجل يتجاوز 20 ألف حركة؛ يحتاج تصديراً موسعاً")
        for voucher in source.order_by(FinanceVoucher.created_at, FinanceVoucher.id):
            kind = "invoice" if voucher.source_type == "invoice_auto" else "plan"
            key = "sale" if kind == "invoice" else "principal"
            try:
                payload = json.loads(voucher.payload)
                before, after = payload["before"], payload["after"]
                a, b = before.get(key, 0), after.get(key, 0)
                if not isinstance(a, int) or isinstance(a, bool) or not isinstance(b, int) or isinstance(b, bool):
                    raise ValueError()
            except (ValueError, TypeError, KeyError, AttributeError):
                malformed += 1
                continue
            identity = (kind, voucher.source_id)
            if identity not in created or (created[identity] and voucher.created_at and voucher.created_at < created[identity]):
                # SQLite can reuse deleted IDs. An old posting is not proof of
                # the newly created document that now happens to have that ID.
                archived_keys.add(identity)
            if identity not in origins and a == 0 and voucher.party_type == "customer" and voucher.party_id == customer_id:
                births.add(identity)
            origins.add(identity)
            change = b - a
            if not change:
                continue
            rows.append({"kind": "debt_origin", "id": voucher.id,
                "date": voucher.transaction_date.isoformat(),
                "description": ("إثبات / زيادة " if change > 0 else "تخفيض / عكس ") + ("أصل فاتورة" if kind == "invoice" else "أصل دين مستقل"),
                "document": ("فاتورة #" if kind == "invoice" else "دين مستقل #") + str(voucher.source_id),
                "amount": change, "cash": 0, "debt_change": change, "advance_change": 0,
                "invoice_id": voucher.source_id if kind == "invoice" else None,
                "plan_id": voucher.source_id if kind == "plan" else None, "voucher_id": voucher.id,
                "status": voucher.status, "note": voucher.notes})
    missing = sum((bool(row.total) or ("invoice", row.id) in origins) and ("invoice", row.id) not in births for row in invoice_rows)
    missing += sum((bool(row.total_amount) or ("plan", row.id) in origins) and ("plan", row.id) not in births for row in plan_rows)
    archived = len(archived_keys)
    for row in rows:
        try:
            row["date"] = _business_date(row["date"]) if row["date"] else None
        except (ValueError, TypeError):
            row["date"] = None
            malformed += 1
        row["net_change"] = row["debt_change"] - row["advance_change"]
        row.update(debt_balance=None, advance_balance=None, net_balance=None)
    debt_delta = sum(row["debt_change"] for row in rows)
    advance_delta = sum(row["advance_change"] for row in rows)
    residual = summary["debt"] - debt_delta
    advance_residual = summary["advance"] - advance_delta
    undated = sum(row["date"] is None for row in rows)
    complete = not (missing or archived or malformed or undated or residual or advance_residual or summary["unexplained_documents"])
    rows.sort(key=lambda row: (row["date"] or "", row["kind"], row["id"]))
    # Voucher dates have day precision. Publish day-end balances only, not a
    # fabricated intraday order between a sale and several collections.
    daily = defaultdict(list)
    for row in rows:
        daily[row["date"]].append(row)
    debt = advance = 0
    opening_debt = opening_advance = closing_debt = closing_advance = 0
    if complete:
        for day, entries in daily.items():
            debt += sum(row["debt_change"] for row in entries)
            advance += sum(row["advance_change"] for row in entries)
            entries[-1].update(debt_balance=debt, advance_balance=advance, net_balance=debt-advance)
            if start and day < start:
                opening_debt, opening_advance = debt, advance
            if not end or day <= end:
                closing_debt, closing_advance = debt, advance
    selected = [row for row in rows if (not start or row["date"] is not None and row["date"] >= start)
                and (not end or row["date"] is not None and row["date"] <= end)]
    return selected, {**summary, "opening_net": opening_debt-opening_advance if complete else None,
        "closing_net": closing_debt-closing_advance if complete else None,
        "debits": sum(max(0, row["net_change"]) for row in selected),
        "credits": sum(max(0, -row["net_change"]) for row in selected)}, {
        "complete": complete, "missing_origins": missing, "archived_documents": archived,
        "malformed_sources": malformed, "undated_movements": undated,
        "unplaced_debt": residual, "unplaced_advance": advance_residual,
        "balance_basis": "day_end", "date_from": start, "date_to": end}


def _read(customer_id):
    denied = _authorize()
    if denied:
        return None, None, denied
    customer = _customer(customer_id)
    if not customer:
        return None, None, _error("العميل غير موجود أو خارج الفروع المسموحة", 404, "not_found")
    try:
        return customer, _statement(customer_id), None
    except StatementError as error:
        return None, None, _error(str(error), 400, "validation")


@desktop_api_bp.get("/customers/<int:customer_id>/account-history")
def account_history(customer_id):
    customer, result, denied = _read(customer_id)
    if denied:
        return denied
    paging = _pagination()
    if not paging:
        return _error("الصفحة غير صحيحة", 400, "validation")
    page, size = paging
    rows, summary, coverage = result
    return jsonify(success=True, data={"items": rows[(page-1)*size:page*size], "total": len(rows),
        "page": page, "page_size": size, "as_of": _today().isoformat(), "summary": summary, "coverage": coverage})


@desktop_api_bp.get("/customers/<int:customer_id>/account-history/print")
def account_history_print(customer_id):
    customer, result, denied = _read(customer_id)
    if denied:
        return denied
    rows, summary, coverage = result
    return render_template("customers/account_history_print.html", customer=customer, rows=rows,
        summary=summary, coverage=coverage, as_of=_today().isoformat())


@desktop_api_bp.get("/customers/<int:customer_id>/account-history/export")
def account_history_export(customer_id):
    customer, result, denied = _read(customer_id)
    if denied:
        return denied
    rows, summary, coverage = result
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["كشف حساب تاريخي", "موثق" if coverage["complete"] else "تاريخ ناقص؛ الأرصدة غير مثبتة"])
    writer.writerow(["رصيد الفترة الافتتاحي", summary["opening_net"], "رصيد الفترة الختامي", summary["closing_net"]])
    writer.writerow(["التاريخ", "الحركة", "المستند", "تغير الدين", "تغير المقدم", "حركة النقد", "رصيد نهاية اليوم"])
    for row in rows:
        literal = lambda text: "'" + text if str(text).lstrip().startswith(("=", "+", "-", "@")) else text
        writer.writerow([row["date"] or "غير محدد", literal(row["description"]), literal(row["document"]),
            row["debt_change"], row["advance_change"], row["cash"], row["net_balance"]])
    return jsonify(success=True, data={"content": "\ufeff" + output.getvalue(), "filename": f"customer-{customer.id}-account-history.csv"})
