from flask import Blueprint, render_template, request, redirect, flash, url_for
from extensions import db
from models.role import Role, Permission
from models.employee import Employee
from utils.decorators import admin_required

permissions_bp = Blueprint("permissions", __name__)


DEFAULT_PERMISSIONS = [
    ("view_orders", "رؤية الطلبات"),
    ("view_orders_placed", "رؤية طلبات «تم الطلب»"),
    ("view_orders_delivered", "رؤية الطلبات الواصلة"),
    ("view_orders_returned", "رؤية المرتجعات"),
    ("view_orders_shipped", "رؤية الطلبات المشحونة"),
    ("edit_price", "تعديل السعر من نقطة البيع"),
    ("view_reports", "رؤية التقارير"),
    ("manage_inventory", "إدارة المخزون"),
    ("view_expenses", "رؤية المصاريف"),
    ("manage_suppliers", "إدارة الموردين"),
    ("manage_customers", "إدارة الزبائن"),
    ("view_accounts", "رؤية الحسابات والصندوق"),
    ("view_financial", "رؤية البيانات المالية"),
    ("view_pos", "استخدام نقطة البيع"),
    ("view_shipping", "رؤية / استخدام الشحن"),
    ("view_agents", "رؤية مندوبي التوصيل"),
    ("manage_agents", "إدارة مندوبي التوصيل"),
    ("view_pages", "رؤية البيجات"),
    ("manage_pages", "إدارة البيجات (إنشاء/حذف)"),
    ("manage_employees", "إدارة الموظفين"),
    ("view_messages", "رؤية واجهة المراسلة"),
]


def ensure_default_permissions():
    from datetime import datetime

    created = False
    for name, desc in DEFAULT_PERMISSIONS:
        if not Permission.query.filter_by(name=name).first():
            db.session.add(Permission(name=name, description=desc, created_at=datetime.utcnow()))
            created = True
    if created:
        db.session.commit()
    from utils.permission_checks import migrate_legacy_permissions_to_roles

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

    groups_config = [
        ("sales", "المبيعات وواجهة الكاشير", ["view_pos", "view_orders", "edit_price", "manage_customers"]),
        (
            "order_status",
            "حالات الطلبات",
            ["view_orders_placed", "view_orders_delivered", "view_orders_returned", "view_orders_shipped"],
        ),
        ("inventory", "المخزون والموردين", ["manage_inventory", "manage_suppliers"]),
        ("finance", "الحسابات والتقارير المالية", ["view_expenses", "view_accounts", "view_financial", "view_reports"]),
        ("communication", "الصفحات والمراسلة والشحن", ["view_shipping", "view_agents", "view_pages", "view_messages"]),
        ("team", "إدارة الفريق", ["manage_employees", "manage_agents", "manage_pages"]),
    ]

    used_names = set()
    perm_groups = []
    for key, title, names in groups_config:
        items = [permissions_by_name[n] for n in names if n in permissions_by_name]
        if not items:
            continue
        used_names.update(n for n in names if n in permissions_by_name)
        perm_groups.append({"key": key, "title": title, "permissions": items})

    other_perms = [p for name, p in permissions_by_name.items() if name not in used_names]
    if other_perms:
        perm_groups.append({"key": "other", "title": "صلاحيات أخرى", "permissions": other_perms})

    return render_template(
        "admin/permissions/roles.html",
        roles=roles,
        permissions=permissions,
        perm_groups=perm_groups,
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
    role.permissions = Permission.query.filter(Permission.id.in_(permission_ids)).all()
    db.session.commit()
    flash("تم تحديث الدور بنجاح", "success")
    return redirect(url_for("permissions.list_roles"))


@permissions_bp.route("/roles/delete/<int:id>")
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
    employee = Employee.query.get_or_404(id)
    if request.method == "POST":
        role_ids = request.form.getlist("roles")
        employee.roles = Role.query.filter(Role.id.in_(role_ids)).all()
        db.session.commit()
        flash(f"تم تحديث أدوار الموظف {employee.name} بنجاح", "success")
        return redirect(url_for("employees.employees"))

    roles = Role.query.all()
    effective = []
    seen = set()
    for role in employee.roles:
        for perm in role.permissions:
            if perm.name not in seen:
                seen.add(perm.name)
                effective.append(perm)
    return render_template(
        "admin/permissions/employee_roles.html",
        employee=employee,
        roles=roles,
        effective_permissions=sorted(effective, key=lambda p: p.name),
    )
