from flask import Blueprint, render_template, request, redirect, flash, url_for
from extensions import db
from models.role import Role, Permission
from models.employee import Employee
from utils.decorators import admin_required
from utils.activity_logger import log_activity
from routes.settings import _settings_ctx
from utils.branch_scope import require_visible

permissions_bp = Blueprint("permissions", __name__)


DEFAULT_PERMISSIONS = [
    ("view_dashboard", "لوحة التحكم الرئيسية"),
    ("view_orders", "رؤية الطلبات"),
    ("view_orders_placed", "رؤية طلبات «تم الطلب»"),
    ("view_orders_packed", "رؤية طلبات «معباة»"),
    ("view_orders_delivered", "رؤية الطلبات الواصلة"),
    ("view_orders_returned", "رؤية المرتجعات"),
    ("view_orders_shipped", "رؤية الطلبات المشحونة"),
    ("manage_orders", "تعديل الطلبات وحالاتها"),
    ("pay_orders", "تسديد الطلبات (كامل أو جزئي)"),
    ("return_orders", "إرجاع الطلبات"),
    ("delete_orders", "حذف أو إلغاء الطلبات"),
    ("edit_price", "تعديل السعر من نقطة البيع"),
    ("print_pos_invoice", "طباعة فاتورة نقطة البيع"),
    ("view_reports", "رؤية التقارير"),
    ("manage_inventory", "إدارة المخزون"),
    ("view_expenses", "رؤية المصاريف"),
    ("manage_suppliers", "إدارة الموردين"),
    ("manage_customers", "إدارة الزبائن"),
    ("view_accounts", "رؤية الحسابات والصندوق"),
    ("view_financial", "رؤية التقرير المالي الشامل"),
    ("view_fixed_assets", "رؤية الأصول الثابتة"),
    ("manage_fixed_assets", "إدارة الأصول الثابتة"),
    ("approve_fixed_asset_disposal", "الموافقة على بيع/إتلاف الأصول"),
    ("view_rotating_savings", "رؤية الجمعيات والسلف الدوّارة"),
    ("manage_rotating_savings", "إدارة الجمعيات والسلف الدوّارة"),
    ("view_pos", "استخدام نقطة البيع"),
    ("view_my_orders", "عرض الموظف لطلباته فقط من نقطة البيع"),
    ("view_shipping", "رؤية شركات الشحن"),
    ("manage_shipping", "إدارة شركات الشحن والتسويات"),
    ("view_agents", "رؤية مندوبي التوصيل"),
    ("manage_agents", "إدارة مندوبي التوصيل"),
    ("view_pages", "رؤية البيجات"),
    ("manage_pages", "إدارة البيجات (إنشاء/حذف)"),
    ("manage_employees", "إدارة الموظفين"),
    ("view_messages", "رؤية واجهة المراسلة"),
    ("view_quick_sale", "استخدام البيع السريع"),
    ("use_ai_workspace", "استخدام مساحة LEON"),
    ("manage_settings", "إعدادات النظام"),
    ("view_activity", "رؤية سجل النشاط"),
    ("use_notes", "استخدام دفتر الملاحظات الشخصي"),
    ("use_employee_desk", "استخدام مكتب الموظف"),
    ("manage_branches", "إدارة الفروع"),
    ("manage_transfers", "نقل المخزون بين الفروع"),
    ("view_branch_reports", "عرض تقارير مقارنة الفروع (فروعه المعيّنة فقط)"),
    ("manage_branch_staff", "تعيين الموظفين على الفروع"),
    ("run_branch_distribution", "جلسات التوزيع الأولي بين الفروع"),
    ("allocate_branch_expenses", "تصنيف المصاريف وتوزيعها على الفروع"),
    ("merge_delivery_agents", "دمج سجلات المناديب المكررة"),
    ("view_all_branches", "عرض كل الفروع"),
    ("use_ai_assistant", "استخدام مساعد Finora الذكي"),
    ("approve_ai_actions", "الموافقة على خطط المساعد الذكي وتنفيذها"),
    ("manage_ai_schedules", "إدارة دوريات تحليل المساعد الذكي"),
    ("view_ai_audit_logs", "رؤية سجل أدوات ومراجعات المساعد الذكي"),
    ("use_ai_sales", "استخدام صندوق Finora Sales AI"),
    ("manage_ai_sales", "إدارة قنوات وإعدادات Finora Sales AI"),
    ("wholesale_ops", "مركز عمليات تجارة الجملة"),
    ("wholesale_sales", "مبيعات تجارة الجملة"),
    ("wholesale_purchases", "مشتريات تجارة الجملة"),
    ("wholesale_receipts", "قبض تجارة الجملة"),
    ("wholesale_payments", "تسديد تجارة الجملة"),
    ("wholesale_warehouses", "مخازن تجارة الجملة"),
    ("wholesale_statement", "كشف حساب تجارة الجملة"),
    ("wholesale_reports", "تقارير تجارة الجملة"),
    ("wholesale_settings", "إعدادات تجارة الجملة"),
    ("food_cashier", "استخدام كاشير المواد الغذائية"),
    ("cashier.sell", "تنفيذ البيع من كاشير المواد الغذائية"),
    ("cashier.discount_item", "خصم على مادة في الكاشير"),
    ("cashier.discount_invoice", "خصم على فاتورة الكاشير"),
    ("cashier.override_price", "تغيير سعر مادة في الكاشير"),
    ("cashier.sell_credit", "البيع الآجل من الكاشير"),
    ("cashier.override_credit_limit", "تجاوز حد ائتمان العميل"),
    ("cashier.return", "تنفيذ مرتجع من الكاشير"),
    ("cashier.void_sale", "إلغاء فاتورة من الكاشير"),
    ("cashier.reprint", "إعادة طباعة فاتورة الكاشير"),
    ("cashier.open_drawer", "فتح درج النقد"),
    ("cashier.view_other_branch_stock", "عرض مخزون الفروع الأخرى"),
    ("cashier.sell_negative_stock", "السماح بالبيع بمخزون سالب"),
    ("food_orders", "عرض طلبات المواد الغذائية"),
    ("food_products", "إدارة منتجات ووحدات المواد الغذائية"),
    ("products.create", "إنشاء منتجات المواد الغذائية"),
    ("products.update", "تعديل منتجات المواد الغذائية"),
    ("products.archive", "أرشفة منتجات المواد الغذائية"),
    ("products.manage_cost", "إدارة تكلفة منتجات المواد الغذائية"),
    ("products.manage_prices", "إدارة أسعار منتجات المواد الغذائية"),
    ("inventory.opening_balance", "إدخال الرصيد الافتتاحي للمواد الغذائية"),
    ("food_purchases", "إدارة مشتريات المواد الغذائية"),
    ("food_inventory", "إدارة مخزن وجرد المواد الغذائية"),
    ("food_parties", "إدارة عملاء وموردي المواد الغذائية"),
    ("food_finance", "قبض العملاء وتسديد الموردين"),
    ("food_reports", "تقارير المواد الغذائية"),
    ("view_profit", "عرض الأرباح في لوحة المواد الغذائية"),
    ("food_settings", "إعدادات نشاط المواد الغذائية"),
    ("clinics_dashboard", "لوحة تحكم العيادة"),
    ("clinics_reception", "استقبال العيادة والطابور"),
    ("clinics_appointments", "إدارة مواعيد العيادة"),
    ("clinics_patients", "إدارة مرضى العيادة"),
    ("clinics_visits", "زيارات العيادة"),
    ("clinics_clinical", "السجل الطبي والوصفات"),
    ("clinics_billing", "فواتير ومدفوعات العيادة"),
    ("clinics_inventory", "مخزون مستلزمات العيادة"),
    ("clinics_admin", "إدارة الأطباء والخدمات والغرف"),
    ("clinics_reports", "تقارير العيادة"),
    ("clinics_settings", "إعدادات نشاط العيادات"),
    ("dental.view", "عرض وحدة الأسنان"),
    ("dental.chart.view", "عرض مخطط الأسنان"),
    ("dental.chart.edit", "تعديل مخطط الأسنان"),
    ("dental.treatment_plan.view", "عرض خطط علاج الأسنان"),
    ("dental.treatment_plan.create", "إنشاء خطط علاج الأسنان"),
    ("dental.treatment_plan.edit", "تعديل خطط علاج الأسنان"),
    ("dental.treatment_plan.delete", "إلغاء أو أرشفة خطط علاج الأسنان"),
    ("dental.treatment_plan.approve", "اعتماد خطط علاج الأسنان"),
    ("dental.sessions.view", "عرض جلسات الأسنان"),
    ("dental.sessions.create", "إنشاء جلسات الأسنان"),
    ("dental.sessions.edit", "تعديل جلسات الأسنان"),
    ("dental.sessions.complete", "إكمال جلسات الأسنان"),
    ("dental.images.view", "عرض صور الأسنان"),
    ("dental.images.upload", "رفع صور الأسنان"),
    ("dental.images.delete", "حذف بيانات صور الأسنان"),
    ("dental.reports.view", "عرض تقارير الأسنان"),
    ("purchases.view", "عرض مشتريات العيادة"),
    ("purchases.create", "إنشاء فاتورة شراء"),
    ("purchases.edit", "تعديل فاتورة شراء"),
    ("purchases.approve", "اعتماد فاتورة شراء"),
    ("purchases.cancel", "إلغاء فاتورة شراء"),
    ("purchases.receive", "استلام مواد الشراء"),
    ("purchases.return", "مرتجع مشتريات"),
    ("purchases.payment.create", "تسجيل دفعات المورد"),
    ("purchases.payment.view", "عرض دفعات المورد"),
    ("purchases.cost.view", "عرض تكلفة الشراء"),
    ("purchases.export", "تصدير وتقارير المشتريات"),
    ("purchase_request.create", "إنشاء طلب شراء"),
    ("purchase_request.approve", "اعتماد طلب شراء"),
    ("view_receipts", "رؤية القبض والتسديدات"),
    ("create_receipts", "إنشاء سند قبض"),
    ("print_receipts", "طباعة سندات القبض"),
    ("cancel_receipts", "إلغاء سندات القبض"),
    ("installment.view", "عرض طلبات الأقساط (دورة الطلب)"),
    ("installment.mode.toggle", "تفعيل وضع الأقساط (دورة الطلب)"),
    ("installment.create", "إنشاء طلب أقساط (دورة الطلب)"),
    ("installment.return", "ترجيع طلب أقساط (دورة الطلب)"),
    ("installment.manual_settle", "تسديد طلب أقساط يدوياً (دورة الطلب)"),
    ("installment.cancel", "إلغاء طلب أقساط (دورة الطلب)"),
    ("installment.override", "تجاوز قيود دورة الأقساط"),
    ("installment.settings", "إعدادات دورة طلب الأقساط"),
    ("finance.view", "عرض المحرك المالي (الحسابات والقيود)"),
    ("finance.create", "إنشاء السندات والحركات المالية"),
    ("finance.approve", "اعتماد المعاملات المالية"),
    ("finance.approve_large", "اعتماد المعاملات المالية الكبيرة"),
    ("finance.ledger", "عرض دفتر الأستاذ"),
    ("finance.loans", "إدارة القروض"),
    ("finance.print", "طباعة السندات المالية"),
    ("finance.reconcile", "التسوية والمطابقة المالية"),
    ("finance.reverse", "عكس السندات المالية"),
    ("finance.settings", "إعدادات الحسابات والأرصدة الافتتاحية"),
    ("hr.view", "عرض الموارد البشرية"),
    ("hr.employees.create", "إضافة موظف موارد بشرية"),
    ("hr.employees.edit", "تعديل موظف موارد بشرية"),
    ("hr.self", "الخدمة الذاتية للموظف"),
    ("hr.settings.manage", "إعدادات الموارد البشرية"),
    ("hr.employees.state", "تغيير حالة الموظف (تفعيل/إيقاف)"),
    ("hr.resources.manage", "إدارة الأقسام والوظائف والموارد"),
    ("hr.documents.view", "عرض وثائق الموظفين"),
    ("hr.recruitment.manage", "إدارة التوظيف"),
    ("hr.reports.view", "تقارير الموارد البشرية"),
    ("hr.advance.view", "عرض السلف"),
    ("hr.advance.create", "إنشاء سلفة"),
    ("hr.advance.approve", "اعتماد السلف"),
    ("hr.advance.pay", "صرف السلف"),
    ("hr.attendance.view", "عرض الحضور والانصراف"),
    ("hr.attendance.record", "تسجيل الحضور والانصراف"),
    ("hr.attendance.approve", "اعتماد الحضور والتصحيحات"),
    ("hr.leave.manage", "إدارة الإجازات"),
    ("hr.leave.approve", "اعتماد الإجازات"),
    ("hr.shifts.manage", "إدارة الدوام والورديات"),
    ("hr.commission.view", "عرض العمولات"),
    ("hr.commission.manage", "إدارة العمولات"),
    ("hr.commission.pay", "صرف العمولات"),
    ("hr.payroll.view", "عرض الرواتب"),
    ("hr.payroll.prepare", "تجهيز كشف الرواتب"),
    ("hr.payroll.review", "مراجعة كشف الرواتب"),
    ("hr.payroll.approve", "اعتماد كشف الرواتب"),
    ("hr.payroll.pay", "صرف الرواتب"),
    ("inventory.audit.view", "عرض جرد المخزون"),
    ("inventory.audit.count", "إجراء الجرد والعدّ"),
    ("inventory.audit.review", "مراجعة نتائج الجرد"),
    ("inventory.audit.approve", "اعتماد الجرد"),
    ("inventory.audit.post", "ترحيل تسويات الجرد"),
    ("inventory.audit.cost", "عرض كلفة الجرد والفروقات"),
    ("inventory.audit.export", "تصدير تقارير الجرد"),
    ("inventory.audit.investigate", "التحقيق في فروقات الجرد"),
    ("inventory.audit.system", "إعدادات نظام الجرد"),
    ("edit_current_stock", "تعديل الرصيد الحالي للمخزون (تحويل، شطب، جرد)"),
    ("edit_product", "تعديل بيانات المنتجات"),
    ("product.merge_duplicates", "دمج المنتجات المكررة"),
    ("clinics_booking_requests_view", "عرض طلبات حجز العيادة"),
    ("clinics_booking_requests_approve", "اعتماد طلبات حجز العيادة"),
    ("clinics_booking_settings_manage", "إعدادات حجز العيادة"),
    ("clinics_clinical_shared_read", "قراءة السجل الطبي المشترك"),
    ("clinics_communications_view", "عرض مراسلات العيادة"),
    ("clinics_communications_reply", "الرد على مراسلات العيادة"),
    ("clinics_reminders_view", "عرض تذكيرات العيادة"),
    ("clinics_reminders_manage", "إدارة تذكيرات العيادة"),
    ("payroll.view", "عرض رواتب العيادة"),
    ("salary_sensitive_data.view", "عرض بيانات الرواتب الحساسة"),
    ("ai.takeover", "استلام محادثة من المساعد الذكي"),
    ("approvals.decide", "قرار طلبات الموافقة"),
    ("audit.view", "عرض سجل التدقيق (FINORA CORE)"),
    ("conversations.view", "عرض المحادثات"),
    ("messages.send", "إرسال الرسائل"),
    ("notes.write", "كتابة الملاحظات"),
    ("settings.manage", "إدارة إعدادات FINORA CORE"),
    ("pricing.view", "عرض قواعد وسجل أسعار البيع"),
    ("pricing.manage", "إعداد قواعد التسعير واقتراح الأسعار"),
    ("pricing.approve", "اعتماد تغييرات أسعار البيع والعروض"),
    ("mobile_app.adjust_points", "تعديل نقاط تطبيق الزبائن"),
    ("mobile_app.manage_comments", "إدارة تعليقات تطبيق الزبائن"),
    ("mobile_app.manage_coupons", "إدارة كوبونات تطبيق الزبائن"),
    ("mobile_app.manage_rewards", "إدارة مكافآت تطبيق الزبائن"),
    ("mobile_app.manage_videos", "إدارة فيديوهات تطبيق الزبائن"),
]


# Display groups of the roles screen (and the desktop permissions window). Names not listed fall into «أخرى».
PERMISSION_GROUPS = [
    ("dashboard", "لوحة التحكم", ["view_dashboard"]),
    (
        "sales",
        "المبيعات وواجهة الكاشير",
        [
            "view_pos",
            "view_my_orders",
            "view_quick_sale",
            "view_orders",
            "manage_orders",
            "pay_orders",
            "return_orders",
            "delete_orders",
            "edit_price",
            "print_pos_invoice",
            "manage_customers",
        ],
    ),
    (
        "order_status",
        "حالات الطلبات",
        ["view_orders_placed", "view_orders_packed", "view_orders_delivered", "view_orders_returned", "view_orders_shipped"],
    ),
    (
        "order_installment_lifecycle",
        "الأقساط (دورة الطلب)",
        [
            "installment.view",
            "installment.mode.toggle",
            "installment.create",
            "installment.return",
            "installment.manual_settle",
            "installment.cancel",
            "installment.override",
            "installment.settings",
        ],
    ),
    ("inventory", "المخزون والموردين", ["manage_inventory", "manage_suppliers"]),
    ("finance", "الحسابات والتقارير المالية", ["view_expenses", "view_accounts", "view_financial", "view_reports", "view_fixed_assets", "manage_fixed_assets", "view_rotating_savings", "manage_rotating_savings", "view_receipts", "create_receipts", "print_receipts", "cancel_receipts"]),
    ("communication", "الصفحات والمراسلة والشحن", ["view_shipping", "manage_shipping", "view_agents", "view_pages", "view_messages"]),
    ("team", "إدارة الفريق والإعدادات", ["manage_employees", "manage_agents", "manage_pages", "manage_settings"]),
    ("branches", "إدارة الفروع", ["manage_branches", "manage_transfers", "view_branch_reports", "manage_branch_staff", "run_branch_distribution", "allocate_branch_expenses", "merge_delivery_agents"]),
    ("audit", "السجل والمراجعة", ["view_activity"]),
    ("notes", "دفتر الملاحظات", ["use_notes"]),
    ("employee_desk", "مكتب الموظف", ["use_employee_desk"]),
    ("ai_assistant", "المساعد الذكي", ["use_ai_assistant", "use_ai_workspace", "approve_ai_actions", "manage_ai_schedules", "view_ai_audit_logs"]),
    ("ai_sales", "موظف المبيعات الذكي", ["use_ai_sales", "manage_ai_sales"]),
    (
        "wholesale",
        "تجارة الجملة",
        [
            "wholesale_ops",
            "wholesale_sales",
            "wholesale_purchases",
            "wholesale_receipts",
            "wholesale_payments",
            "wholesale_warehouses",
            "wholesale_statement",
            "wholesale_reports",
            "wholesale_settings",
        ],
    ),
    (
        "food",
        "مواد غذائية – جملة ومفرد",
        [
            "food_cashier",
            "cashier.sell",
            "cashier.discount_item",
            "cashier.discount_invoice",
            "cashier.override_price",
            "cashier.sell_credit",
            "cashier.override_credit_limit",
            "cashier.return",
            "cashier.void_sale",
            "cashier.reprint",
            "cashier.open_drawer",
            "cashier.view_other_branch_stock",
            "cashier.sell_negative_stock",
            "food_orders",
            "food_products",
            "food_purchases",
            "food_inventory",
            "food_parties",
            "food_finance",
            "food_reports",
            "view_profit",
            "food_settings",
        ],
    ),
    (
        "clinics",
        "عيادات Finora",
        [
            "clinics_dashboard",
            "clinics_reception",
            "clinics_appointments",
            "clinics_patients",
            "clinics_visits",
            "clinics_clinical",
            "clinics_billing",
            "clinics_inventory",
            "purchases.view",
            "purchases.create",
            "purchases.edit",
            "purchases.approve",
            "purchases.cancel",
            "purchases.receive",
            "purchases.return",
            "purchases.payment.create",
            "purchases.payment.view",
            "purchases.cost.view",
            "purchases.export",
            "purchase_request.create",
            "purchase_request.approve",
            "clinics_admin",
            "clinics_reports",
            "clinics_settings",
            "clinics_booking_requests_view",
            "clinics_booking_requests_approve",
            "clinics_booking_settings_manage",
            "clinics_clinical_shared_read",
            "clinics_communications_view",
            "clinics_communications_reply",
            "clinics_reminders_view",
            "clinics_reminders_manage",
            "payroll.view",
            "salary_sensitive_data.view",
        ],
    ),
    ("finance_engine", "المحرك المالي", ["finance.view", "finance.create", "finance.approve", "finance.approve_large", "finance.ledger", "finance.loans", "finance.print", "finance.reconcile", "finance.reverse", "finance.settings"]),
    ("hr", "الموارد البشرية والرواتب", ["hr.view", "hr.employees.create", "hr.employees.edit", "hr.self", "hr.settings.manage", "hr.employees.state", "hr.resources.manage", "hr.documents.view", "hr.recruitment.manage", "hr.reports.view", "hr.advance.view", "hr.advance.create", "hr.advance.approve", "hr.advance.pay", "hr.attendance.view", "hr.attendance.record", "hr.attendance.approve", "hr.leave.manage", "hr.leave.approve", "hr.shifts.manage", "hr.commission.view", "hr.commission.manage", "hr.commission.pay", "hr.payroll.view", "hr.payroll.prepare", "hr.payroll.review", "hr.payroll.approve", "hr.payroll.pay"]),
    ("inventory_audit", "جرد وعمليات المخزون", ["inventory.audit.view", "inventory.audit.count", "inventory.audit.review", "inventory.audit.approve", "inventory.audit.post", "inventory.audit.cost", "inventory.audit.export", "inventory.audit.investigate", "inventory.audit.system", "edit_current_stock", "edit_product", "product.merge_duplicates"]),
    ("finora_core", "FINORA CORE", ["ai.takeover", "approvals.decide", "audit.view", "conversations.view", "messages.send", "notes.write", "settings.manage"]),
    ("pricing", "التسعير", ["pricing.view", "pricing.manage", "pricing.approve"]),
    ("mobile_app", "تطبيق الزبائن", ["mobile_app.adjust_points", "mobile_app.manage_comments", "mobile_app.manage_coupons", "mobile_app.manage_rewards", "mobile_app.manage_videos"]),
]


def ensure_default_permissions():
    from datetime import datetime

    created = False
    created_names = set()
    for name, desc in DEFAULT_PERMISSIONS:
        if not Permission.query.filter_by(name=name).first():
            db.session.add(Permission(name=name, description=desc, created_at=datetime.utcnow()))
            created = True
            created_names.add(name)
    if created:
        db.session.flush()
        # Preserve the capabilities of roles that used the old all-in-one
        # manage_orders permission.  After this one-time split, each new
        # permission can be disabled independently from the roles screen.
        granular_order_names = {"pay_orders", "return_orders", "delete_orders"}
        newly_created_granular = granular_order_names.intersection(created_names)
        if newly_created_granular:
            new_permissions = {
                permission.name: permission
                for permission in Permission.query.filter(
                    Permission.name.in_(newly_created_granular)
                ).all()
            }
            for role in Role.query.all():
                role_permission_names = {permission.name for permission in role.permissions}
                if "manage_orders" not in role_permission_names:
                    continue
                for permission_name in newly_created_granular:
                    permission = new_permissions.get(permission_name)
                    if permission and permission_name not in role_permission_names:
                        role.permissions.append(permission)
        granular_product_names = {
            "products.create", "products.update", "products.archive",
            "products.manage_cost", "products.manage_prices",
        }
        newly_created_products = granular_product_names.intersection(created_names)
        if newly_created_products:
            new_permissions = {
                permission.name: permission
                for permission in Permission.query.filter(
                    Permission.name.in_(newly_created_products)
                ).all()
            }
            for role in Role.query.all():
                current = {permission.name for permission in role.permissions}
                if "food_products" not in current:
                    continue
                for permission_name in newly_created_products:
                    permission = new_permissions.get(permission_name)
                    if permission and permission_name not in current:
                        role.permissions.append(permission)
        if "inventory.opening_balance" in created_names:
            opening_permission = Permission.query.filter_by(name="inventory.opening_balance").first()
            for role in Role.query.all():
                current = {permission.name for permission in role.permissions}
                if "food_inventory" in current and opening_permission not in role.permissions:
                    role.permissions.append(opening_permission)
        if "view_profit" in created_names:
            profit_permission = Permission.query.filter_by(name="view_profit").first()
            for role in Role.query.all():
                current = {permission.name for permission in role.permissions}
                if profit_permission and profit_permission not in role.permissions and (
                    "food_reports" in current or "products.manage_cost" in current
                ):
                    role.permissions.append(profit_permission)
        if "view_my_orders" in created_names:
            cashier_role = Role.query.filter_by(name="cashier").first()
            my_orders_permission = Permission.query.filter_by(name="view_my_orders").first()
            if cashier_role and my_orders_permission and my_orders_permission not in cashier_role.permissions:
                cashier_role.permissions.append(my_orders_permission)
        if "print_pos_invoice" in created_names:
            cashier_role = Role.query.filter_by(name="cashier").first()
            print_permission = Permission.query.filter_by(name="print_pos_invoice").first()
            if cashier_role and print_permission and print_permission not in cashier_role.permissions:
                cashier_role.permissions.append(print_permission)
        granular_clinic_purchase_names = {
            "purchases.view", "purchases.create", "purchases.edit", "purchases.approve",
            "purchases.cancel", "purchases.receive", "purchases.return",
            "purchases.payment.create", "purchases.payment.view", "purchases.cost.view",
            "purchases.export", "purchase_request.create", "purchase_request.approve",
        }
        newly_created_clinic_purchases = granular_clinic_purchase_names.intersection(created_names)
        if newly_created_clinic_purchases:
            new_permissions = {
                permission.name: permission
                for permission in Permission.query.filter(
                    Permission.name.in_(newly_created_clinic_purchases)
                ).all()
            }
            for role in Role.query.all():
                current = {permission.name for permission in role.permissions}
                if "clinics_inventory" not in current:
                    continue
                for permission_name in newly_created_clinic_purchases:
                    permission = new_permissions.get(permission_name)
                    if permission and permission_name not in current:
                        role.permissions.append(permission)
        db.session.commit()
    from utils.permission_checks import ensure_cashier_role_has_messages, migrate_legacy_permissions_to_roles

    try:
        ensure_cashier_role_has_messages()
    except Exception:
        db.session.rollback()
    try:
        migrate_legacy_permissions_to_roles()
    except Exception:
        db.session.rollback()


@permissions_bp.route("/roles")
@admin_required
def list_roles():
    ensure_default_permissions()

    roles = Role.query.all()
    permissions = Permission.query.all()
    permissions_by_name = {p.name: p for p in permissions}

    groups_config = PERMISSION_GROUPS

    used_names = set()
    perm_groups = []
    for key, title, names in groups_config:
        items = [permissions_by_name[n] for n in names if n in permissions_by_name]
        if not items:
            continue
        used_names.update(n for n in names if n in permissions_by_name)
        perm_groups.append({"key": key, "title": title, "permissions": items})

    # Branch aggregation is an intrinsic admin capability, never a grantable
    # staff permission.  Keep the legacy row for compatibility but hide it.
    other_perms = [
        p for name, p in permissions_by_name.items()
        if name not in used_names and name != "view_all_branches"
    ]
    if other_perms:
        perm_groups.append({"key": "other", "title": "صلاحيات أخرى", "permissions": other_perms})

    return render_template(
        "admin/permissions/roles.html",
        **_settings_ctx("permissions", roles=roles, permissions=permissions, perm_groups=perm_groups),
    )


@permissions_bp.route("/roles/add", methods=["POST"])
@admin_required
def add_role():
    name = request.form.get("name")
    description = request.form.get("description")
    if name:
        if Role.query.filter_by(name=name).first():
            flash("هذا الدور موجود بالفعل", "warning")
        else:
            role = Role(name=name, description=description)
            db.session.add(role)
            db.session.commit()
            flash("تم إضافة الدور بنجاح", "success")
    return redirect(url_for("permissions.list_roles"))


@permissions_bp.route("/roles/edit/<int:id>", methods=["POST"])
@admin_required
def edit_role(id):
    role = Role.query.get_or_404(id)
    role.name = request.form.get("name")
    role.description = request.form.get("description")
    permission_ids = request.form.getlist("permissions")
    role.permissions = Permission.query.filter(
        Permission.id.in_(permission_ids), Permission.name != "view_all_branches"
    ).all()
    db.session.commit()
    try:
        log_activity(
            "update",
            "settings",
            f"تحديث صلاحيات الدور: {role.name}",
            entity_type="role",
            entity_id=role.id,
            payload={"permission_ids": permission_ids},
        )
    except Exception:
        pass
    flash("تم تحديث الدور بنجاح", "success")
    return redirect(url_for("permissions.list_roles"))


@permissions_bp.route("/roles/delete/<int:id>", methods=["POST"])
@admin_required
def delete_role(id):
    role = Role.query.get_or_404(id)
    if role.name in ["admin", "cashier"]:
        flash("لا يمكن حذف الأدوار الأساسية للنظام", "danger")
    else:
        db.session.delete(role)
        db.session.commit()
        flash("تم حذف الدور بنجاح", "success")
    return redirect(url_for("permissions.list_roles"))


@permissions_bp.route("/employee/<int:id>/roles", methods=["GET", "POST"])
@admin_required
def employee_roles(id):
    employee = require_visible(Employee.query.get_or_404(id))
    if request.method == "POST":
        role_ids = request.form.getlist("roles")
        employee.roles = Role.query.filter(Role.id.in_(role_ids)).all()
        if employee.role != "admin":
            from models.branch import Branch

            branch_id = request.form.get("branch_id", type=int)
            branch = Branch.query.filter_by(id=branch_id, is_active=True).first()
            if not branch:
                flash("اختر فرعاً فعالاً للموظف", "danger")
                return redirect(url_for("permissions.employee_roles", id=employee.id))
            employee.branch_id = branch.id
        db.session.commit()
        try:
            log_activity(
                "update",
                "settings",
                f"تحديث أدوار الموظف {employee.name}",
                entity_type="employee",
                entity_id=employee.id,
                payload={"role_ids": role_ids},
            )
        except Exception:
            pass
        flash(f"تم تحديث أدوار الموظف {employee.name} بنجاح", "success")
        return redirect(url_for("employees.employees"))

    roles = Role.query.all()
    from models.branch import Branch
    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name.asc()).all()
    effective = []
    seen = set()
    for role in employee.roles:
        for perm in role.permissions:
            if perm.name not in seen:
                seen.add(perm.name)
                effective.append(perm)
    return render_template(
        "admin/permissions/employee_roles.html",
        **_settings_ctx(
            "permissions",
            employee=employee,
            roles=roles,
            branches=branches,
            effective_permissions=sorted(effective, key=lambda p: p.name),
        ),
    )
