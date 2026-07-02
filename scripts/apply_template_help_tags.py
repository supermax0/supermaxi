#!/usr/bin/env python3
"""Apply data-help spans to template labels across modules."""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (relative_path, old, new) — unique replacements only
REPLACEMENTS: list[tuple[str, str, str]] = [
    # Purchases
    ("templates/purchases.html", "<h3", "<h3"),  # placeholder skip
    ("templates/purchases_form.html", '<label>المورد', '<label>المورد<span data-help="purchases.supplier"></span'),
    ("templates/purchases_form.html", '<label>رقم الفاتورة', '<label>رقم الفاتورة<span data-help="purchases.invoice_number"></span'),
    # Suppliers
    ("templates/suppliers.html", 'placeholder="اسم المورد"', 'placeholder="اسم المورد" data-help="suppliers.name"'),
    ("templates/suppliers.html", 'placeholder="رقم الهاتف"', 'placeholder="رقم الهاتف" data-help="suppliers.phone"'),
    # Customers
    ("templates/customers.html", 'placeholder="اسم الزبون"', 'placeholder="اسم الزبون" data-help="customers.name"'),
    ("templates/customers.html", 'placeholder="رقم الهاتف"', 'placeholder="رقم الهاتف" data-help="customers.phone"'),
    ("templates/customers.html", 'placeholder="العنوان"', 'placeholder="العنوان" data-help="customers.address"'),
    # Shipping
    ("templates/shipping.html", "shipping_add_company_title') }}</h3>", "shipping_add_company_title') }}<span data-help=\"shipping.company\"></span></h3>"),
    # Expenses
    ("templates/expenses.html", 'name="category"', 'name="category" data-help="expenses.category"'),
    ("templates/expenses.html", 'name="amount"', 'name="amount" data-help="expenses.amount"'),
    ("templates/expenses.html", 'name="date"', 'name="date" data-help="expenses.date"'),
    ("templates/expenses.html", 'id="expenseAccount"', 'id="expenseAccount" data-help="expenses.account"'),
    # Cash
    ("templates/cash.html", "cash_income_title')", "cash_income_title') }}<span data-help=\"cash.income\"></span"),
    ("templates/cash.html", "cash_expense_title')", "cash_expense_title') }}<span data-help=\"cash.expense\"></span"),
    ("templates/cash.html", 'id="cashBalance"', 'id="cashBalance" data-help="cash.balance"'),
    # Accounts
    ("templates/accounts.html", 'placeholder="رمز الحساب"', 'placeholder="رمز الحساب" data-help="accounts.code"'),
    ("templates/accounts.html", 'placeholder="اسم الحساب"', 'placeholder="اسم الحساب" data-help="accounts.name"'),
    # Reports
    ("templates/reports.html", 'id="dateFrom"', 'id="dateFrom" data-help="reports.date_from"'),
    ("templates/reports.html", 'id="dateTo"', 'id="dateTo" data-help="reports.date_to"'),
    ("templates/reports_financial.html", 'id="reportDateFrom"', 'id="reportDateFrom" data-help="reports.date_from"'),
    ("templates/reports_financial.html", 'id="reportDateTo"', 'id="reportDateTo" data-help="reports.date_to"'),
    # Employees
    ("templates/employees.html", 'name="name"', 'name="name" data-help="employees.name"'),
    ("templates/employees.html", 'name="username"', 'name="username" data-help="employees.username"'),
    ("templates/employees.html", 'name="role_id"', 'name="role_id" data-help="employees.role"'),
    # Settings
    ("templates/settings_appearance.html", 'for="defaultTheme">الثيم الافتراضي</label>', 'for="defaultTheme">الثيم الافتراضي<span data-help="settings.theme"></span></label>'),
    ("templates/settings_appearance.html", 'for="fontScale">حجم الخط</label>', 'for="fontScale">حجم الخط<span data-help="settings.font_size"></span></label>'),
    ("templates/settings_appearance.html", 'for="defaultCurrency">العملة الافتراضية</label>', 'for="defaultCurrency">العملة الافتراضية<span data-help="settings.currency"></span></label>'),
    ("templates/settings_branches.html", "<label>اسم الفرع</label>", "<label>اسم الفرع<span data-help=\"settings.branches\"></span></label>"),
    ("templates/settings_storefront.html", 'settings-field-help">يؤثر على الأزرار', '<span data-help="settings.theme"></span></div><div class="settings-field-help" style="display:none">يؤثر على الأزرار'),
    # Fixed assets
    ("templates/fixed_assets/create.html", "<label>اسم الأصل *</label>", "<label>اسم الأصل *<span data-help=\"fixed_assets.name\"></span></label>"),
    ("templates/fixed_assets/create.html", "<label>تكلفة الشراء *</label>", "<label>تكلفة الشراء *<span data-help=\"fixed_assets.value\"></span></label>"),
    ("templates/fixed_assets/depreciation.html", "<label>السنة</label>", "<label>السنة<span data-help=\"fixed_assets.depreciation\"></span></label>"),
    ("templates/fixed_assets/disposal.html", "<label>سبب الاستبعاد</label>", "<label>سبب الاستبعاد<span data-help=\"fixed_assets.disposal\"></span></label>"),
    # Beauty
    ("templates/beauty_services.html", 'name="name"', 'name="name" data-help="beauty.service"'),
    ("templates/beauty_clients.html", 'placeholder="اسم العميل"', 'placeholder="اسم العميل" data-help="customers.name"'),
    # Social AI
    ("templates/social_ai/dashboard.html", '<label>Bot Token</label>', '<label>Bot Token<span data-help="general.save"></span></label>'),
    # Maintenance
    ("templates/maintenance.html" if os.path.exists(os.path.join(ROOT, "templates/maintenance.html")) else "templates/inventory.html",
     "maintenance_field_product", "maintenance_field_product"),  # skip bad
    # Permissions
    ("templates/admin/permissions/roles.html", "<h2", "<h2"),
]


def main() -> None:
    applied = 0
    skipped = 0
    for rel, old, new in REPLACEMENTS:
        if old == new or old.startswith("<h3") or old.startswith("<h2"):
            skipped += 1
            continue
        path = os.path.join(ROOT, rel.replace("/", os.sep))
        if not os.path.isfile(path):
            print(f"SKIP missing: {rel}")
            continue
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if old not in content:
            print(f"SKIP not found in {rel}: {old[:50]}...")
            continue
        if new in content:
            print(f"SKIP already applied: {rel}")
            continue
        content = content.replace(old, new, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        applied += 1
        print(f"OK {rel}")
    print(f"Applied {applied} replacements, skipped {skipped}")


if __name__ == "__main__":
    main()
