"""Saved undated collection evidence is not a newly dated payment."""
import json
from flask import g
from extensions import db
from models.invoice import Invoice
from models.treasury_account import TreasuryAccount
from modules.finance.common import FinanceError, tenant_key
from utils.branch_mode import independent_branches_enabled
from .facts import available
from .models import SalesReturn, SalesReturnOrigin


def read_default_cash_id(branch_id):
    query = TreasuryAccount.query.execution_options(skip_branch_scope=True).filter_by(account_type="cash", is_active=True)
    if independent_branches_enabled():
        if branch_id is None:
            from models.branch import Branch
            default = Branch.query.execution_options(skip_branch_scope=True).filter_by(is_default=True, is_active=True).order_by(Branch.id).first()
            if default is None:
                return None
            branch_id = default.id
        query = query.filter(TreasuryAccount.branch_id == branch_id, TreasuryAccount.is_default.is_(True))
    row = query.order_by(TreasuryAccount.is_default.desc(), TreasuryAccount.id).first()
    return row.id if row else None


def capture_undated_collection(invoice, payments):
    if payments or invoice.shipping_company_id or not int(invoice.paid_amount or 0):
        return None
    return {"amount": int(invoice.paid_amount), "treasury_account_id": read_default_cash_id(invoice.branch_id),
        "date": None, "basis": "saved_paid_counter_default_cash"}


def from_original(original):
    value = original.get("undated_collection")
    if value is None:
        return None
    if (value.get("basis") != "saved_paid_counter_default_cash" or value.get("date") is not None
            or type(value.get("amount")) is not int or value["amount"] <= 0
            or (value.get("treasury_account_id") is not None and
                (type(value["treasury_account_id"]) is not int or value["treasury_account_id"] < 1))
            or value["amount"] != original["invoice"]["paid_counter"] or original.get("payments")
            or original["invoice"].get("shipping_company_id")):
        raise FinanceError("دليل التحصيل القديم لا يطابق أصل البيع؛ يلزم مراجعته", "source_review", 409)
    return value


def for_invoice(invoice_id):
    if not available():
        return None
    row = SalesReturnOrigin.query.filter_by(tenant_key=tenant_key(), invoice_id=invoice_id).first()
    return from_original(json.loads(row.snapshot)) if row else None


def reviewed(invoice_id):
    return any(json.loads(row.evidence).get("undated_collection_reviewed") is True
        for row in SalesReturn.query.filter_by(tenant_key=tenant_key(), invoice_id=invoice_id))


def saved_collections():
    if not available():
        return []
    rows = db.session.query(SalesReturnOrigin).execution_options(skip_branch_scope=True).join(
        Invoice, Invoice.id == SalesReturnOrigin.invoice_id).filter(SalesReturnOrigin.tenant_key == g.tenant).all()
    result = []
    for origin in rows:
        info = from_original(json.loads(origin.snapshot))
        if info and info["treasury_account_id"] is not None:
            result.append({**info, "invoice_id": origin.invoice_id})
    return result


def for_treasury(account_id, default_cash_id, records=None):
    ids = {account_id}
    if account_id == default_cash_id and not independent_branches_enabled():
        ids = {row[0] for row in TreasuryAccount.query.execution_options(skip_branch_scope=True).with_entities(
            TreasuryAccount.id).filter_by(account_type="cash", is_active=True)}
    return [row for row in (saved_collections() if records is None else records) if row["treasury_account_id"] in ids]


def undated_balance(account_id=None):
    if not available():
        return 0
    if account_id is not None:
        account = db.session.get(TreasuryAccount, account_id)
        default_id = read_default_cash_id(account.branch_id) if account else None
        return sum(row["amount"] for row in for_treasury(account_id, default_id)) if account else 0
    from utils.treasury_calculations import list_treasury_accounts
    visible = {row.id for row in list_treasury_accounts() if row.is_cash}
    return sum(row["amount"] for row in saved_collections() if row["treasury_account_id"] in visible)
