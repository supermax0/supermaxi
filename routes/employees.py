from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session
from datetime import datetime
from werkzeug.security import generate_password_hash
from extensions import db
from models.employee import Employee
from models.invoice import Invoice
from models.delivery_agent import DeliveryAgent
from models.page import Page
from sqlalchemy.sql import func
from sqlalchemy import inspect, text

from utils.agent_passwords import hash_agent_password
from utils.decorators import permission_required
from utils.permission_checks import employee_can, get_current_employee
from utils.employee_commission import get_fixed_employee_commission_amount, set_fixed_employee_commission_amount
from utils.employee_commission_service import (
    backfill_invoice_employee_ids,
    build_employee_commission_stats_map,
    build_monthly_statement,
    settle_employee_commission,
)
from utils.team_schema import build_employees_grid_rows, ensure_delivery_agent_schema
from utils.payroll_schema import ensure_payroll_schema
from utils.payroll_service import apply_payroll_config, WEEKDAY_LABELS
from utils.activity_logger import EMPLOYEE_SNAPSHOT_FIELDS, log_activity, log_mutation, snapshot_attrs

employees_bp = Blueprint("employees", __name__)

_EMPLOYEE_PROFILE_SCHEMA_ENSURED: set[str] = set()


def _employee_schema_bind_key(engine) -> str:
    try:
        return f"{engine.dialect.name}:{engine.url}"
    except Exception:
        return str(id(engine))


def _ensure_employee_profile_schema():
    from flask import g

    try:
        if getattr(g, "tenant", None):
            from extensions_tenant import get_tenant_engine

            engine = get_tenant_engine(g.tenant)
        else:
            engine = db.engine
    except Exception as e:
        print(f"[employees] profile schema engine resolve failed: {e}")
        return

    bind_key = _employee_schema_bind_key(engine)
    if bind_key in _EMPLOYEE_PROFILE_SCHEMA_ENSURED:
        return

    try:
        inspector = inspect(engine)
        if "employee" not in inspector.get_table_names():
            return

        columns = {col["name"] for col in inspector.get_columns("employee")}
        with engine.connect() as conn:
            changed = False
            if "language" not in columns:
                conn.execute(text("ALTER TABLE employee ADD COLUMN language VARCHAR(10) DEFAULT 'ar'"))
                changed = True
            if "profile_pic" not in columns:
                conn.execute(text("ALTER TABLE employee ADD COLUMN profile_pic VARCHAR(500)"))
                changed = True
            if "theme_preference" not in columns:
                conn.execute(text("ALTER TABLE employee ADD COLUMN theme_preference VARCHAR(20) DEFAULT 'dark'"))
                changed = True
            if "phone" not in columns:
                conn.execute(text("ALTER TABLE employee ADD COLUMN phone VARCHAR(20)"))
                changed = True
            if changed:
                conn.commit()
        _EMPLOYEE_PROFILE_SCHEMA_ENSURED.add(bind_key)
    except Exception as e:
        msg = str(e).lower()
        if "duplicate column" in msg:
            _EMPLOYEE_PROFILE_SCHEMA_ENSURED.add(bind_key)
            return
        print(f"[employees] profile schema ensure failed: {e}")


def _normalize_employee_phone(raw) -> str | None:
    phone = str(raw or "").strip()
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    return digits[:20] or None


DEFAULT_PAGE_WITHDRAWAL_WARNING = (
    "مرحباً {employee_name}،\n"
    "\n"
    "نود إبلاغك بضعف أدائك على البيجات المعيّنة لك.\n"
    "\n"
    "──────────────\n"
    "تفاصيل البيجات\n"
    "──────────────\n"
    "{pages_details}\n"
    "──────────────\n"
    "المجموع: {pages_count} بيج — {total_orders} طلب\n"
    "──────────────\n"
    "\n"
    "في حال استمرار الأداء الضعيف سيتم سحب البيج من عندك.\n"
    "يرجى تحسين المتابعة ورفع النشاط.\n"
    "\n"
    "شكراً لك."
)


def _wa_digits(phone: str | None) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("0"):
        return "964" + digits[1:]
    if not digits.startswith("964"):
        return "964" + digits
    return digits


def _build_employee_page_cards():
    """Active employees with assigned pages + per-page order/sales totals."""
    employees_list = (
        Employee.query.filter(Employee.is_active.is_(True))
        .order_by(Employee.name.asc())
        .all()
    )
    cards = []
    for emp in employees_list:
        pages = list(emp.pages.all())
        page_rows = []
        total_orders = 0
        total_sales = 0
        for page in pages:
            row = (
                db.session.query(
                    func.count(Invoice.id).label("orders_count"),
                    func.coalesce(func.sum(Invoice.total), 0).label("sales"),
                )
                .filter(Invoice.employee_id == emp.id, Invoice.page_id == page.id)
                .one()
            )
            orders_count = int(row.orders_count or 0)
            sales = int(row.sales or 0)
            total_orders += orders_count
            total_sales += sales
            page_rows.append(
                {
                    "id": page.id,
                    "name": page.name,
                    "orders_count": orders_count,
                    "sales": sales,
                }
            )
        cards.append(
            {
                "id": emp.id,
                "name": emp.name,
                "username": emp.username,
                "phone": getattr(emp, "phone", None) or "",
                "role": emp.role,
                "pages_count": len(page_rows),
                "total_orders": total_orders,
                "total_sales": total_sales,
                "pages": page_rows,
                "wa_digits": _wa_digits(getattr(emp, "phone", None)),
            }
        )
    return cards


def _require_manage_employees():
    employee = get_current_employee()
    if not employee_can(employee, "manage_employees"):
        return jsonify({"error": "غير مصرح"}), 403
    return None


def _ensure_commission_schema():
    from flask import g

    try:
        if getattr(g, "tenant", None):
            from extensions_tenant import get_tenant_engine

            engine = get_tenant_engine(g.tenant)
        else:
            engine = db.engine

        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        with engine.connect() as conn:
            changed = False
            if "invoice" in tables:
                columns = {col["name"] for col in inspector.get_columns("invoice")}
                if "employee_commission_settled_at" not in columns:
                    dialect = engine.dialect.name
                    col_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"
                    conn.execute(
                        text(f"ALTER TABLE invoice ADD COLUMN employee_commission_settled_at {col_type}")
                    )
                    changed = True

            if changed:
                conn.commit()

        from models.employee_commission_settlement import EmployeeCommissionSettlement

        EmployeeCommissionSettlement.__table__.create(engine, checkfirst=True)
    except Exception as e:
        msg = str(e).lower()
        if "duplicate column" not in msg and "already exists" not in msg:
            print(f"[employees] commission schema ensure failed: {e}")


@employees_bp.before_request
def ensure_employee_schema():
    _ensure_employee_profile_schema()
    ensure_delivery_agent_schema()
    ensure_payroll_schema()
    _ensure_commission_schema()
    try:
        backfill_invoice_employee_ids()
    except Exception as e:
        print(f"[employees] commission backfill failed: {e}")


@employees_bp.route("/", methods=["GET", "POST"])
@permission_required("manage_employees")
def employees():
    if request.method == "POST":
        from utils.plan_guard import users_limit_check

        limit_result = users_limit_check()
        if not limit_result["ok"]:
            return render_template("upgrade_required.html", limit_error=limit_result["error"]), 403
        role_name = request.form.get("role", "cashier")
        emp = Employee(
            name=request.form["name"],
            username=request.form["username"],
            password=generate_password_hash(request.form["password"]),
            phone=_normalize_employee_phone(request.form.get("phone")),
            role=role_name,
            salary=int(request.form.get("salary", 0)),
            commission_percent=max(
                0,
                int(request.form.get("commission", get_fixed_employee_commission_amount()) or 0),
            ),
        )
        apply_payroll_config(
            emp,
            pay_type=request.form.get("pay_type"),
            salary=int(request.form.get("salary", 0) or 0),
            pay_day_of_month=request.form.get("pay_day_of_month"),
            pay_weekday=request.form.get("pay_weekday"),
            commission=int(request.form.get("commission", 0) or 0) if request.form.get("commission") else None,
        )
        db.session.add(emp)
        db.session.flush()
        from models.role import Role

        base_role = Role.query.filter_by(name=role_name).first()
        if base_role:
            emp.roles = [base_role]
        db.session.commit()
        try:
            log_activity(
                "create",
                "employees",
                f"إضافة موظف: {emp.name}",
                entity_type="employee",
                entity_id=emp.id,
                payload={"employee": snapshot_attrs(emp, *EMPLOYEE_SNAPSHOT_FIELDS)},
            )
        except Exception:
            pass
        return redirect(url_for("employees.employees"))

    employees_list = Employee.query.all()
    stats_map = build_employee_commission_stats_map(unsettled_only=True)

    delivery_agents = DeliveryAgent.query.order_by(DeliveryAgent.name).all()
    agent_stats = (
        db.session.query(
            Invoice.delivery_agent_id,
            func.count(Invoice.id).label("orders"),
            func.sum(Invoice.total).label("sales"),
        )
        .filter(Invoice.delivery_agent_id.isnot(None))
        .group_by(Invoice.delivery_agent_id)
        .all()
    )
    agent_stats_map = {s.delivery_agent_id: {"orders": s.orders, "sales": s.sales or 0} for s in agent_stats}

    pages = Page.query.all()
    pages_list = [{"id": p.id, "name": p.name} for p in pages]
    agents_without_login = [a for a in delivery_agents if not a.username]
    employees_grid_rows = build_employees_grid_rows(
        employees_list, stats_map, delivery_agents, agent_stats_map
    )

    return render_template(
        "employees.html",
        employees=employees_list,
        employees_grid_rows=employees_grid_rows,
        stats=stats_map,
        delivery_agents=delivery_agents,
        agent_stats=agent_stats_map,
        pages=pages_list,
        agents_without_login=agents_without_login,
        fixed_commission_amount=get_fixed_employee_commission_amount(),
        weekday_labels=WEEKDAY_LABELS,
    )


@employees_bp.route("/fixed-commission", methods=["POST"])
@permission_required("manage_employees")
def update_fixed_commission():
    data = request.get_json(silent=True) or {}
    try:
        amount = int(data.get("amount", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "مبلغ غير صالح"}), 400
    value = set_fixed_employee_commission_amount(amount)
    Employee.query.update({"commission_percent": value}, synchronize_session=False)
    db.session.commit()
    return jsonify({"success": True, "amount": value, "message": "تم حفظ مبلغ العمولة الثابتة"})


@employees_bp.route("/commission-statement")
@permission_required("manage_employees")
def commission_statement():
    try:
        year = int(request.args.get("year") or datetime.utcnow().year)
        month = int(request.args.get("month") or datetime.utcnow().month)
    except (TypeError, ValueError):
        return jsonify({"error": "فترة غير صالحة"}), 400

    if month < 1 or month > 12:
        return jsonify({"error": "الشهر غير صالح"}), 400

    rows = build_monthly_statement(year, month)
    fixed_amount = get_fixed_employee_commission_amount()
    total_orders = sum(r["orders"] for r in rows)
    total_amount = sum(r["amount"] for r in rows)

    return jsonify(
        {
            "success": True,
            "year": year,
            "month": month,
            "fixed_commission_amount": fixed_amount,
            "rows": rows,
            "total_orders": total_orders,
            "total_amount": total_amount,
        }
    )


@employees_bp.route("/commission-settle", methods=["POST"])
@permission_required("manage_employees")
def commission_settle():
    data = request.get_json(silent=True) or {}
    try:
        employee_id = int(data.get("employee_id"))
        year = int(data.get("year"))
        month = int(data.get("month"))
    except (TypeError, ValueError):
        return jsonify({"error": "بيانات غير صالحة"}), 400

    if month < 1 or month > 12:
        return jsonify({"error": "الشهر غير صالح"}), 400

    current = get_current_employee()
    settled_by = current.id if current else None

    try:
        result = settle_employee_commission(employee_id, year, month, settled_by=settled_by)
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500

    if not result.get("ok"):
        return jsonify({"error": result.get("error", "فشل السداد")}), 400

    try:
        log_activity(
            "update",
            "employees",
            f"سداد عمولة الموظف {result['employee_name']} — {result['order_count']} طلب — {result['amount']} د.ع ({year}-{month:02d})",
            entity_type="employee",
            entity_id=employee_id,
            payload=result,
        )
    except Exception:
        pass

    return jsonify({"success": True, **result, "message": "تم تسجيل السداد بنجاح"})


@employees_bp.route("/toggle/<int:id>", methods=["POST"])
@permission_required("manage_employees")
def toggle_employee(id):
    emp = Employee.query.get_or_404(id)
    before = snapshot_attrs(emp, *EMPLOYEE_SNAPSHOT_FIELDS)
    emp.is_active = not emp.is_active
    db.session.commit()
    try:
        log_mutation(
            "update",
            "employees",
            "employee",
            emp.id,
            before,
            snapshot_attrs(emp, *EMPLOYEE_SNAPSHOT_FIELDS),
            f"{'تفعيل' if emp.is_active else 'تعطيل'} الموظف {emp.name}",
        )
    except Exception:
        pass
    return redirect(url_for("employees.employees"))


@employees_bp.route("/update/<int:id>", methods=["POST"])
@permission_required("manage_employees")
def update_employee(id):
    emp = Employee.query.get_or_404(id)
    before = snapshot_attrs(emp, *EMPLOYEE_SNAPSHOT_FIELDS)
    data = request.get_json(silent=True) or request.form
    name = str(data.get("name") or "").strip()
    if name:
        emp.name = name
    if "phone" in data:
        emp.phone = _normalize_employee_phone(data.get("phone"))
    if "salary" in data:
        emp.salary = int(data.get("salary") or 0)
    if "commission" in data:
        emp.commission_percent = max(0, int(data.get("commission") or 0))
    apply_payroll_config(
        emp,
        pay_type=data.get("pay_type"),
        salary=int(data.get("salary", emp.salary or 0) or 0) if "salary" in data else None,
        pay_day_of_month=data.get("pay_day_of_month"),
        pay_weekday=data.get("pay_weekday"),
        commission=int(data.get("commission") or 0) if "commission" in data else None,
    )
    db.session.commit()
    try:
        log_mutation(
            "update",
            "employees",
            "employee",
            emp.id,
            before,
            snapshot_attrs(emp, *EMPLOYEE_SNAPSHOT_FIELDS),
            f"تحديث بيانات الموظف {emp.name}",
        )
    except Exception:
        pass
    return jsonify({"success": True, "message": "تم تحديث بيانات الموظف"})


@employees_bp.route("/update-agent/<int:id>", methods=["POST"])
@permission_required("manage_employees")
def update_delivery_agent(id):
    agent = DeliveryAgent.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    if name:
        agent.name = name.replace("🚚", "").strip()
    if "salary" in data:
        agent.salary = int(data.get("salary") or 0)
    apply_payroll_config(
        agent,
        pay_type=data.get("pay_type"),
        salary=int(data.get("salary", agent.salary or 0) or 0) if "salary" in data else None,
        pay_day_of_month=data.get("pay_day_of_month"),
        pay_weekday=data.get("pay_weekday"),
    )
    password = str(data.get("password") or "").strip()
    if password:
        if len(password) < 4:
            return jsonify({"error": "كلمة المرور قصيرة جداً"}), 400
        agent.password = hash_agent_password(password)
    db.session.commit()
    return jsonify({"success": True, "message": "تم تحديث بيانات المندوب"})


@employees_bp.route("/reset-password/<int:id>", methods=["POST"])
@permission_required("manage_employees")
def reset_employee_password(id):
    emp = Employee.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    password = str(data.get("password") or "").strip()
    if len(password) < 4:
        return jsonify({"error": "كلمة المرور قصيرة جداً"}), 400
    emp.password = generate_password_hash(password)
    db.session.commit()
    return jsonify({"success": True, "message": "تم تحديث كلمة المرور"})


@employees_bp.route("/add-agent-account", methods=["POST"])
@permission_required("manage_agents")
def add_agent_account():
    data = request.json or {}
    agent_id = data.get("agent_id")
    username = str(data.get("username") or "").strip()
    password = str(data.get("password") or "").strip()

    if not agent_id or not username or not password:
        return jsonify({"error": "يرجى ملء جميع الحقول"}), 400

    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "المندوب غير موجود"}), 404

    existing_agent = DeliveryAgent.query.filter_by(username=username).first()
    if existing_agent and existing_agent.id != agent_id:
        return jsonify({"error": "اسم المستخدم مستخدم من قبل"}), 400

    existing_employee = Employee.query.filter_by(username=username).first()
    if existing_employee:
        return jsonify({"error": "اسم المستخدم مستخدم من قبل موظف"}), 400

    try:
        agent.username = username
        agent.password = hash_agent_password(password)
        db.session.commit()
        return jsonify({"success": True, "message": "تم إضافة حساب المندوب بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500


@employees_bp.route("/manage-pages/<int:employee_id>", methods=["POST"])
@permission_required("manage_employees")
def manage_employee_pages(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    data = request.json or {}
    page_ids = data.get("page_ids", [])
    try:
        for page in employee.pages.all():
            employee.pages.remove(page)
        for page_id in page_ids:
            page = Page.query.get(page_id)
            if page:
                employee.pages.append(page)
        db.session.commit()
        return jsonify({"success": True, "message": "تم تحديث البيجات بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500


@employees_bp.route("/pages/<int:employee_id>")
@permission_required("manage_employees")
def get_employee_pages(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    pages = employee.pages.all()
    return jsonify({"pages": [{"id": p.id, "name": p.name} for p in pages]})


@employees_bp.route("/view-orders/<int:employee_id>")
@permission_required("manage_employees")
def view_employee_orders(employee_id):
    employee = Employee.query.get_or_404(employee_id)
    orders = Invoice.query.filter_by(employee_id=employee_id).all()
    pages = employee.pages.all()
    page_stats = {}
    for page in pages:
        page_orders = Invoice.query.filter_by(employee_id=employee_id, page_id=page.id).all()
        page_stats[page.id] = {
            "name": page.name,
            "orders_count": len(page_orders),
            "orders": [{"id": o.id, "total": o.total, "customer_name": o.customer_name} for o in page_orders],
        }
    orders_without_page = Invoice.query.filter_by(employee_id=employee_id).filter(Invoice.page_id.is_(None)).all()
    return jsonify(
        {
            "employee": {"id": employee.id, "name": employee.name},
            "pages_count": len(pages),
            "pages": [{"id": p.id, "name": p.name} for p in pages],
            "total_orders": len(orders),
            "page_stats": page_stats,
            "orders_without_page": [
                {"id": o.id, "total": o.total, "customer_name": o.customer_name} for o in orders_without_page
            ],
        }
    )


@employees_bp.route("/page-warnings")
@permission_required("manage_employees")
def page_warnings():
    cards = _build_employee_page_cards()
    return render_template(
        "employee_page_warnings.html",
        cards=cards,
        default_message=DEFAULT_PAGE_WITHDRAWAL_WARNING,
    )


@employees_bp.route("/page-warnings/update-phone/<int:employee_id>", methods=["POST"])
@permission_required("manage_employees")
def update_employee_phone_for_warnings(employee_id):
    emp = Employee.query.get_or_404(employee_id)
    data = request.get_json(silent=True) or {}
    emp.phone = _normalize_employee_phone(data.get("phone"))
    db.session.commit()
    return jsonify(
        {
            "success": True,
            "phone": emp.phone or "",
            "wa_digits": _wa_digits(emp.phone),
            "message": "تم حفظ رقم الهاتف",
        }
    )


@employees_bp.route("/delete/<int:id>", methods=["POST"])
@permission_required("manage_employees")
def delete_employee(id):
    emp = Employee.query.get(id)
    if not emp:
        return jsonify({"error": "الموظف غير موجود"}), 404

    current_id = session.get("user_id")
    if current_id and int(current_id) == emp.id:
        return jsonify({"error": "لا يمكنك حذف حسابك الحالي"}), 400

    linked_orders = Invoice.query.filter_by(employee_id=emp.id).count()
    if linked_orders:
        return jsonify({
            "error": f"لا يمكن الحذف: الموظف مرتبط بـ {linked_orders} طلب. عطّله بدلاً من ذلك."
        }), 400

    before = snapshot_attrs(emp, *EMPLOYEE_SNAPSHOT_FIELDS)
    try:
        emp.pages = []
        emp.roles = []
        db.session.delete(emp)
        db.session.commit()
        try:
            log_mutation(
                "delete",
                "employees",
                "employee",
                id,
                before,
                None,
                f"حذف الموظف {before.get('name', id)}",
            )
        except Exception:
            pass
        return jsonify({"success": True, "message": "تم حذف الموظف بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500


@employees_bp.route("/profile/update", methods=["POST"])
def profile_update():
    if "user_id" not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    data = request.json or {}
    new_name = str(data.get("name") or "").strip()
    if not new_name:
        return jsonify({"error": "الاسم مطلوب"}), 400
    emp = Employee.query.get(session["user_id"])
    if not emp:
        return jsonify({"error": "الموظف غير موجود"}), 404
    emp.name = new_name
    db.session.commit()
    session["name"] = new_name
    return jsonify({"success": True, "message": "تم تحديث الاسم بنجاح"})


@employees_bp.route("/profile/settings", methods=["POST"])
def profile_settings():
    if "user_id" not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    data = request.json or {}
    language = data.get("language")
    theme = data.get("theme")
    emp = Employee.query.get(session["user_id"])
    if not emp:
        return jsonify({"error": "الموظف غير موجود"}), 404
    if language in ["ar", "en", "ku", "tr"]:
        emp.language = language
        session["language"] = language
    if theme in ["dark", "light", "system"]:
        emp.theme_preference = theme
        session["theme"] = theme
    db.session.commit()
    return jsonify({"success": True})


@employees_bp.route("/profile/upload", methods=["POST"])
def profile_upload():
    if "user_id" not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    if "file" not in request.files:
        return jsonify({"error": "لم يتم اختيار ملف"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "لم يتم اختيار ملف"}), 400
    if file:
        import os
        from werkzeug.utils import secure_filename

        upload_folder = os.path.join("static", "uploads", "profiles")
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        filename = secure_filename(f"user_{session['user_id']}_{file.filename}")
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)
        emp = Employee.query.get(session["user_id"])
        if emp:
            if emp.profile_pic and os.path.exists(emp.profile_pic):
                try:
                    os.remove(emp.profile_pic)
                except Exception:
                    pass
            emp.profile_pic = file_path.replace("\\", "/")
            db.session.commit()
            return jsonify({"success": True, "message": "تم رفع الصورة بنجاح", "profile_pic": emp.profile_pic})
    return jsonify({"error": "فشل الرفع"}), 500
