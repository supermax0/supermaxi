"""One-off probe: cash balance components and 83k transactions."""
from app import app
from models.account_transaction import AccountTransaction
from utils.treasury_calculations import (
    calculate_treasury_balance,
    _paid_sales_for_default_cash,
    _sum_account_transactions,
    _sum_withdrawals,
    _sum_supplier_payments,
    _sum_shipping_collections,
)
from utils.treasury_helpers import get_default_cash_account

with app.app_context():
    cash_id = get_default_cash_account().id
    txs83 = (
        AccountTransaction.query.filter(AccountTransaction.amount == 83000)
        .order_by(AccountTransaction.created_at.desc())
        .all()
    )
    print("=== 83000 transactions ===")
    for t in txs83:
        print(t.id, t.type, t.amount, repr(t.note), t.created_at)

    paid = _paid_sales_for_default_cash()
    dep = _sum_account_transactions(cash_id, "deposit", cash_id)
    wdr = _sum_withdrawals(cash_id, cash_id)
    sup = _sum_supplier_payments(cash_id, cash_id)
    shp = _sum_shipping_collections(cash_id, cash_id)
    bal = calculate_treasury_balance(cash_id)
    print("paid_sales", paid)
    print("deposits", dep)
    print("withdrawals", wdr)
    print("supplier", sup)
    print("shipping", shp)
    print("balance", bal)
    print("check", paid + dep - wdr - sup + shp)

    print("=== last 20 txs ===")
    for t in AccountTransaction.query.order_by(AccountTransaction.created_at.desc()).limit(20):
        print(t.id, t.type, t.amount, (t.note or "")[:70], t.created_at)
