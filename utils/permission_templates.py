"""Ready-made roles (templates). Installing one creates an ordinary role the admin can edit afterwards.

Installation never overwrites: a role whose name already exists is skipped, so a customised «كاشير» is safe.
Every permission named here must exist in the catalog (checked by tests).
"""
from __future__ import annotations

from typing import Any

from extensions import db
from models.role import Permission, Role
from utils.branch_management import BranchError

_ORDER_VIEWS = ["view_orders", "view_orders_placed", "view_orders_packed", "view_orders_shipped",
                "view_orders_delivered", "view_orders_returned"]

TEMPLATES: list[dict[str, Any]] = [
    {"key": "cashier", "name": "كاشير",
     "description": "البيع من نقطة البيع وطباعة الفاتورة ورؤية طلباته فقط",
     "permissions": ["view_pos", "view_my_orders", "print_pos_invoice", "view_quick_sale", "view_messages"]},
    {"key": "sales", "name": "موظف مبيعات",
     "description": "نقطة البيع والزبائن ومتابعة الطلبات دون تعديل الأسعار أو الحذف",
     "permissions": ["view_pos", "view_my_orders", "print_pos_invoice", "view_quick_sale", "manage_customers",
                     "view_orders", "view_messages"]},
    {"key": "accountant", "name": "محاسب",
     "description": "الحسابات والصندوق والمصاريف والسندات والمحرك المالي وتقارير الفروع (دون إعدادات أو عكس سندات)",
     "permissions": ["view_accounts", "view_financial", "view_expenses", "view_reports", "view_receipts",
                     "create_receipts", "print_receipts", "view_fixed_assets", "view_orders", "pay_orders",
                     "finance.view", "finance.create", "finance.ledger", "finance.print", "finance.reconcile",
                     "view_branch_reports", "allocate_branch_expenses", "view_activity"]},
    {"key": "order_follow_up", "name": "متابعة الطلبات",
     "description": "متابعة الطلبات وحالاتها وتسديدها والتواصل مع الزبائن والشحن",
     "permissions": _ORDER_VIEWS + ["manage_orders", "pay_orders", "manage_customers", "view_shipping",
                                    "view_agents", "view_messages", "print_pos_invoice"]},
    {"key": "inventory", "name": "مسؤول مخزون",
     "description": "المخزون والمنتجات والتحويلات بين الفروع والجرد",
     "permissions": ["manage_inventory", "edit_product", "edit_current_stock", "manage_transfers",
                     "products.create", "products.update", "inventory.audit.view", "inventory.audit.count",
                     "inventory.audit.review", "view_reports"]},
    {"key": "purchasing", "name": "مسؤول مشتريات",
     "description": "الموردون والمشتريات واستلام البضاعة",
     "permissions": ["manage_suppliers", "manage_inventory", "view_expenses", "view_reports"]},
    {"key": "shipping", "name": "مسؤول شحن",
     "description": "شركات الشحن والمندوبون وكشوف التسوية والمرتجعات",
     "permissions": _ORDER_VIEWS + ["manage_orders", "view_shipping", "manage_shipping", "view_agents",
                                    "manage_agents", "view_messages"]},
    {"key": "branch_manager", "name": "مدير فرع",
     "description": "تشغيل فرعه: المبيعات والطلبات والمخزون والتحويلات وتقارير فرعه (دون إدارة الصلاحيات)",
     "permissions": ["view_pos", "view_my_orders", "print_pos_invoice", "manage_customers", "manage_inventory",
                     "edit_current_stock", "manage_transfers", "manage_orders", "pay_orders", "return_orders",
                     "view_reports", "view_expenses", "view_accounts", "view_shipping", "view_agents",
                     "view_branch_reports", "view_activity"] + _ORDER_VIEWS},
    {"key": "hr", "name": "مسؤول موارد بشرية",
     "description": "الموظفون والدوام والإجازات والتوظيف والسلف وتجهيز الرواتب (دون اعتماد أو صرف)",
     "permissions": ["hr.view", "hr.employees.create", "hr.employees.edit", "hr.employees.state",
                     "hr.documents.view", "hr.attendance.view", "hr.attendance.record", "hr.attendance.approve",
                     "hr.leave.manage", "hr.leave.approve", "hr.shifts.manage", "hr.recruitment.manage",
                     "hr.advance.view", "hr.advance.create", "hr.reports.view", "hr.payroll.view",
                     "hr.payroll.prepare"]},
    {"key": "auditor", "name": "مدقق (قراءة فقط)",
     "description": "اطلاع على التقارير والحسابات والسجل دون أي تعديل",
     "permissions": ["view_reports", "view_expenses", "view_accounts", "view_financial", "view_activity",
                     "finance.view", "finance.ledger", "inventory.audit.view", "view_branch_reports"] + _ORDER_VIEWS},
]


def listing() -> list[dict[str, Any]]:
    existing = {r.name for r in Role.query.all()}
    return [{"key": t["key"], "name": t["name"], "description": t["description"],
             "permissions": list(t["permissions"]), "installed": t["name"] in existing} for t in TEMPLATES]


def install(keys: list[str]) -> dict[str, list[str]]:
    from utils.permission_admin import catalog

    catalog()  # makes sure every permission row exists
    wanted = {t["key"]: t for t in TEMPLATES}
    unknown = [k for k in keys if k not in wanted]
    if unknown:
        raise BranchError(f"دور جاهز غير معروف: {unknown[0]}", "validation", 400)
    if not keys:
        raise BranchError("اختر دوراً واحداً على الأقل", "validation", 400)
    created: list[str] = []
    skipped: list[str] = []
    for key in dict.fromkeys(keys):
        template = wanted[key]
        if Role.query.filter_by(name=template["name"]).first() is not None:
            skipped.append(template["name"])
            continue
        role = Role(name=template["name"], description=template["description"])
        role.permissions = Permission.query.filter(Permission.name.in_(template["permissions"])).all()
        db.session.add(role)
        created.append(template["name"])
    db.session.flush()
    return {"created": created, "skipped": skipped}
