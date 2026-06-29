import sys
sys.path.append('c:\\Users\\msi\\Desktop\\مجلد جديد (2)\\accounting_system')
from app import app
from extensions import db
from flask import json

with app.test_request_context():
    with app.app_context():
        from routes.index import api_executive_dashboard_data
        try:
            # Call the real endpoint (since we bypassed @admin_required during our test? No, admin_required might block it.
            # Actually, admin_required uses session, so without session it will fail. Let's just mock the inner code accurately.)
            from datetime import date, timedelta
            from sqlalchemy.sql import func
            from models.invoice import Invoice
            from models.purchase import Purchase
            from models.customer import Customer
            from routes.index import (calculate_cash_balance, _net_profit_for_range, 
                                     _expenses_sum_for_range, calculate_supplier_debts,
                                     calculate_shipping_due, calculate_inventory_value)
                                     
            today = date.today()
            month_start = today.replace(day=1)
            
            orders_today = Invoice.query.filter(func.date(Invoice.created_at) == today).count()
            purchases_today_val = db.session.query(func.sum(Purchase.total)).filter(func.date(Purchase.created_at) == today).scalar() or 0
            cash_balance = calculate_cash_balance()
            profit_today = _net_profit_for_range(today, today)
            sales_today_val = db.session.query(func.sum(Invoice.total)).filter(func.date(Invoice.created_at) == today, Invoice.status != 'ملغي').scalar() or 0
            
            daily_labels = []
            sales_data = []
            profit_data = []
            expenses_data = []
            cashflow_data = []
            for i in range(6, -1, -1):
                d = today - timedelta(days=i)
                daily_labels.append(d.strftime("%d %b"))
                
                d_sales = db.session.query(func.sum(Invoice.total)).filter(func.date(Invoice.created_at) == d, Invoice.status != 'ملغي').scalar() or 0
                d_profit = _net_profit_for_range(d, d)
                d_expenses = _expenses_sum_for_range(d, d)
                
                sales_data.append(int(d_sales))
                profit_data.append(int(d_profit))
                expenses_data.append(int(d_expenses))
                cashflow_data.append(int(d_sales) - int(d_expenses))
                
            supplier_debts = calculate_supplier_debts()
            shipping_due = calculate_shipping_due()
            liabilities = supplier_debts + shipping_due
            inventory_value = calculate_inventory_value()
            
            new_customers = Customer.query.filter(func.date(Customer.created_at) >= today - timedelta(days=7)).count()
            
            days_passed = today.day
            sales_this_month = db.session.query(func.sum(Invoice.total)).filter(func.date(Invoice.created_at) >= month_start, Invoice.status != 'ملغي').scalar() or 0
            avg_daily_sales = int(sales_this_month) / days_passed if days_passed > 0 else 0
            print("API SUCCESS. sales_today:", sales_today_val)
        except Exception as e:
            import traceback
            traceback.print_exc()
