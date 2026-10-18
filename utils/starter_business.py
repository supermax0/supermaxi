"""Defaults and route-to-feature mapping for the starter business activity."""


DEFAULT_FEATURES = {
    "dashboard", "quick_sale", "orders", "orders_all", "orders_placed",
    "orders_packed", "orders_delivered", "orders_returned", "orders_printing",
    "inventory", "inventory_products", "inventory_add_product", "purchases",
    "suppliers", "customers", "expenses", "receipts", "cash", "accounts",
    "reports", "reports_daily", "reports_sales", "reports_profit", "settings",
    "settings_system", "settings_invoice", "settings_appearance",
}


def feature_for_path(path):
    """Return the feature controlling a starter-business route, if scoped."""
    path = (path or "").rstrip("/") or "/"
    route_features = (
        ("/orders/print", "orders_printing"), ("/orders/export", "orders_printing"),
        ("/orders/reports", "orders_reports"), ("/orders/ordered", "orders_placed"),
        ("/orders/packed", "orders_packed"), ("/orders/shipping", "orders_shipping"),
        ("/orders/delivered", "orders_delivered"), ("/orders/returned", "orders_returned"),
        ("/orders/cancelled", "orders_returned"), ("/orders", "orders"),
        ("/inventory/transfers", "stock_transfers"), ("/inventory/ledger", "inventory_ledger"), ("/inventory/audit", "inventory_audit"),
        ("/inventory/add", "inventory_add_product"), ("/inventory", "inventory"),
        ("/maintenance", "maintenance"), ("/purchases", "purchases"), ("/suppliers", "suppliers"),
        ("/stock-transfers", "stock_transfers"), ("/customers/credit", "customer_credit"),
        ("/customers/blacklist", "customer_blacklist"), ("/customers/provinces", "customer_provinces"),
        ("/customers", "customers"), ("/shipping/company-returns", "shipping_company_returns"), ("/shipping", "shipping"), ("/agents", "agents"),
        ("/employees", "employees"), ("/payroll", "payroll"), ("/admin/permissions", "permissions"),
        ("/expenses", "expenses"), ("/api/receipts", "receipts"), ("/receipts", "receipts"),
        ("/cash", "cash"), ("/accounts", "accounts"),
        ("/quick-sale", "quick_sale"), ("/pos", "pos"),
        ("/notes", "notes"), ("/executive-dashboard", "executive_dashboard"), ("/assets", "fixed_assets"),
        ("/finance/rotating-savings", "rotating_savings"), ("/installments", "installments"),
        ("/reports/monitors", "reports_monitors"), ("/reports/financial", "reports_financial"),
        ("/reports/inventory", "inventory_reports"), ("/reports/suppliers", "supplier_statement"),
        ("/reports/shipping", "shipping_reports"), ("/reports/sales", "reports_sales"),
        ("/reports/profit", "reports_profit"), ("/reports/daily", "reports_daily"),
        ("/reports", "reports"), ("/settings/branches", "settings_branches"),
        ("/settings/storefront", "settings_storefront"), ("/settings/database-repair", "settings_database_repair"),
        ("/settings/system", "settings_system"), ("/settings/invoice", "settings_invoice"),
        ("/settings/appearance", "settings_appearance"), ("/settings", "settings"),
        ("/store", "storefront"), ("/workspace", "ai_workspace"), ("/ai-sales", "ai_sales"),
        ("/social-ai", "ai_sales"), ("/assistant", "assistant_chat"), ("/investments", "investments"),
        ("/messages", "messages"), ("/activity", "activity"), ("/mobile-app", "mobile_app"),
        ("/beauty", "beauty"), ("/wholesale", "wholesale"), ("/hr", "hr"),
        ("/pages", "pages"), ("/admin/invoice-templates", "invoice_templates"),
    )
    for prefix, feature in route_features:
        if path == prefix or path.startswith(prefix + "/"):
            return feature
    return None


def allows(feature, *, plan_features=None, feature_overrides=None) -> bool:
    """Apply plan ceiling, company override, then starter defaults in that order."""
    feature = str(feature or "")
    plan_features = plan_features or {}
    feature_overrides = feature_overrides or {}
    if feature in plan_features and not bool(plan_features[feature]):
        return False
    if feature in feature_overrides:
        return bool(feature_overrides[feature])
    return feature in DEFAULT_FEATURES
