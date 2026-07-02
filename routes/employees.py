from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session
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
from utils.employee_commission import get_fixed_employee_commission_percent, set_fixed_employee_commission_percent
from utils.team_schema import build_employees_grid_rows, ensure_delivery_agent_schema
from utils.activity_logger import EMPLOYEE_SNAPSHOT_FIELDS, log_activity, log_mutation, snapshot_attrs

employees_bp = Blueprint("employees", __name__)


def _ensure_employee_profile_schema():
    from flask import g

    try:
        if getattr(g, "tenant", None):
            from extensions_tenant import get_tenant_engine

            engine = get_tenant_engine(g.tenant)
        else:
            engine = db.engine

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
            if changed:
                conn.commit()
    except Exception as e:
        msg = str(e).lower()
        if "duplicate column" not in msg:
            print(f"[employees] profile schema ensure failed: {e}")


def _require_manage_employees():
    employee = get_current_employee()
    if not employee_can(employee, "manage_employees"):
        return jsonify({"error": "غير مصرح"}), 403
    return None


@employees_bp.before_request
def ensure_employee_schema():
    _ensure_employee_profile_schema()
    ensure_delivery_agent_schema()


@employees_bp.route("/", methods=["GET", "POST"])
@permission_required("manage_employees")
def employees():
    if request.method == "POST":
        from utils.plan_guard import users_limit_check

        limit_result = users_limit_check()
        if not limit_result["ok"]:
            return render_template("upgrade_required.html", limit_error=limit_result["error"]), 403
        emp = Employee(
            name=request.form["name"],
            username=request.form["username"],
            password=generate_password_hash(request.form["password"]),
            role=request.form.get("role", "cashier"),
            salary=int(request.form.get("salary", 0)),
            commission_percent=get_fixed_employee_commission_percent(),
        )
        db.session.add(emp)
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
    stats = (
        db.session.query(
            Invoice.employee_id,
            func.count(Invoice.id).label("orders"),
            func.sum(Invoice.total).label("sales"),
        )
        .group_by(Invoice.employee_id)
        .all()
    )
    stats_map = {s.employee_id: {"orders": s.orders, "sales": s.sales or 0} for s in stats}

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
        fixed_commission_percent=get_fixed_employee_commission_percent(),
    )


@employees_bp.route("/fixed-commission", methods=["POST"])
@permission_required("manage_employees")
def update_fixed_commission():
    data = request.get_json(silent=True) or {}
    try:
        percent = int(data.get("percent", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "نسبة غير صالحة"}), 400
    value = set_fixed_employee_commission_percent(percent)
    Employee.query.update({"commission_percent": value}, synchronize_session=False)
    db.session.commit()
    return jsonify({"success": True, "percent": value, "message": "تم حفظ نسبة العمولة الثابتة"})


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
    if "salary" in data:
        emp.salary = int(data.get("salary") or 0)
    emp.commission_percent = get_fixed_employee_commission_percent()
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
        employee.pages = []
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
