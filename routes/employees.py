from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session
from extensions import db
from models.employee import Employee
from models.invoice import Invoice
from models.delivery_agent import DeliveryAgent
from models.page import Page, employee_pages
from sqlalchemy.sql import func
from sqlalchemy import inspect, text

employees_bp = Blueprint("employees", __name__)


def _ensure_employee_profile_schema():
    """
    تأكد من وجود أعمدة اللغة/الثيم في جدول employee حتى في قواعد بيانات الشركات القديمة.
    تُستدعى عند تسجيل الدخول وعند طلبات الموظفين. يجب استخدام محرك قاعدة بيانات الـ tenant
    عندما يكون g.tenant معيّناً، وإلاّ تُهاجر القاعدة الافتراضية فقط.
    """
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


@employees_bp.before_request
def ensure_employee_schema():
    _ensure_employee_profile_schema()

# ===============================
# Employees Page
# ===============================
@employees_bp.route("/", methods=["GET", "POST"])
def employees():
    # إضافة موظف
    if request.method == "POST":
        from utils.plan_guard import users_limit_check
        from werkzeug.security import generate_password_hash
        # فحص حد المستخدمين بناءً على الخطة
        limit_result = users_limit_check()
        if not limit_result["ok"]:
            return render_template(
                "upgrade_required.html",
                limit_error=limit_result["error"]
            ), 403
        emp = Employee(
            name=request.form["name"],
            username=request.form["username"],
            password=generate_password_hash(request.form["password"]),
            role=request.form.get("role", "cashier"),
            salary=int(request.form.get("salary", 0)),
            commission_percent=int(request.form.get("commission", 0))
        )
        db.session.add(emp)
        db.session.commit()
        return redirect(url_for("employees.employees"))

    # جلب الموظفين
    employees = Employee.query.all()

    # إحصائيات الطلبات لكل موظف
    stats = (
        db.session.query(
            Invoice.employee_id,
            func.count(Invoice.id).label("orders"),
            func.sum(Invoice.total).label("sales")
        )
        .group_by(Invoice.employee_id)
        .all()
    )

    stats_map = {
        s.employee_id: {
            "orders": s.orders,
            "sales": s.sales or 0
        }
        for s in stats
    }

    # جلب المندوبين لإضافتهم في القائمة
    delivery_agents = DeliveryAgent.query.order_by(DeliveryAgent.name).all()
    
    # إحصائيات الطلبات لكل مندوب
    agent_stats = (
        db.session.query(
            Invoice.delivery_agent_id,
            func.count(Invoice.id).label("orders"),
            func.sum(Invoice.total).label("sales")
        )
        .filter(Invoice.delivery_agent_id.isnot(None))
        .group_by(Invoice.delivery_agent_id)
        .all()
    )
    
    agent_stats_map = {
        s.delivery_agent_id: {
            "orders": s.orders,
            "sales": s.sales or 0
        }
        for s in agent_stats
    }
    
    # جلب البيجات
    pages = Page.query.all()
    pages_list = [{"id": p.id, "name": p.name} for p in pages]
    
    return render_template(
        "employees.html",
        employees=employees,
        stats=stats_map,
        delivery_agents=delivery_agents,
        agent_stats=agent_stats_map,
        pages=pages_list
    )


# ===============================
# Toggle Active / Disable
# ===============================
@employees_bp.route("/toggle/<int:id>")
def toggle_employee(id):
    emp = Employee.query.get_or_404(id)
    emp.is_active = not emp.is_active
    db.session.commit()
    return redirect(url_for("employees.employees"))

# ===============================
# Add Delivery Agent Account
# ===============================
@employees_bp.route("/add-agent-account", methods=["POST"])
def add_agent_account():
    """إضافة حساب تسجيل دخول للمندوب"""
    
    # التحقق من تسجيل الدخول
    if "user_id" not in session or session.get("role") != "admin":
        return jsonify({"error": "غير مصرح"}), 403
    
    data = request.json
    agent_id = data.get("agent_id")
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    
    if not agent_id or not username or not password:
        return jsonify({"error": "يرجى ملء جميع الحقول"}), 400
    
    agent = DeliveryAgent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "المندوب غير موجود"}), 404
    
    # التحقق من أن اسم المستخدم غير مستخدم من قبل مندوب آخر
    existing_agent = DeliveryAgent.query.filter_by(username=username).first()
    if existing_agent and existing_agent.id != agent_id:
        return jsonify({"error": "اسم المستخدم مستخدم من قبل"}), 400
    
    # التحقق من أن اسم المستخدم غير مستخدم من قبل موظف
    existing_employee = Employee.query.filter_by(username=username).first()
    if existing_employee:
        return jsonify({"error": "اسم المستخدم مستخدم من قبل موظف"}), 400
    
    try:
        agent.username = username
        agent.password = password  # لاحقاً يمكن عمل hash
        db.session.commit()
        return jsonify({"success": True, "message": "تم إضافة حساب المندوب بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500

# ===============================
# Manage Employee Pages
# ===============================
@employees_bp.route("/manage-pages/<int:employee_id>", methods=["POST"])
def manage_employee_pages(employee_id):
    """إدارة البيجات التابعة لموظف"""
    if "user_id" not in session or session.get("role") != "admin":
        return jsonify({"error": "غير مصرح"}), 403
    
    employee = Employee.query.get_or_404(employee_id)
    data = request.json
    page_ids = data.get("page_ids", [])
    
    try:
        # إزالة جميع العلاقات الحالية
        employee.pages = []
        
        # إضافة البيجات المحددة
        for page_id in page_ids:
            page = Page.query.get(page_id)
            if page:
                employee.pages.append(page)
        
        db.session.commit()
        return jsonify({"success": True, "message": "تم تحديث البيجات بنجاح"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"حدث خطأ: {str(e)}"}), 500

# ===============================
# Get Employee Pages (API)
# ===============================
@employees_bp.route("/pages/<int:employee_id>")
def get_employee_pages(employee_id):
    """جلب البيجات التابعة لموظف"""
    employee = Employee.query.get_or_404(employee_id)
    pages = employee.pages.all()
    return jsonify({
        "pages": [{"id": p.id, "name": p.name} for p in pages]
    })

# ===============================
# View Employee Orders with Pages
# ===============================
@employees_bp.route("/view-orders/<int:employee_id>")
def view_employee_orders(employee_id):
    """عرض طلبات الموظف مع البيجات"""
    employee = Employee.query.get_or_404(employee_id)
    
    # جلب الطلبات
    orders = Invoice.query.filter_by(employee_id=employee_id).all()
    
    # جلب البيجات
    pages = employee.pages.all()
    
    # حساب عدد الطلبات لكل بيج
    page_stats = {}
    for page in pages:
        page_orders = Invoice.query.filter_by(
            employee_id=employee_id,
            page_id=page.id
        ).all()
        page_stats[page.id] = {
            "name": page.name,
            "orders_count": len(page_orders),
            "orders": [{"id": o.id, "total": o.total, "customer_name": o.customer_name} for o in page_orders]
        }
    
    # الطلبات بدون بيج
    orders_without_page = Invoice.query.filter_by(
        employee_id=employee_id
    ).filter(Invoice.page_id.is_(None)).all()
    
    return jsonify({
        "employee": {"id": employee.id, "name": employee.name},
        "pages_count": len(pages),
        "pages": [{"id": p.id, "name": p.name} for p in pages],
        "total_orders": len(orders),
        "page_stats": page_stats,
        "orders_without_page": [{"id": o.id, "total": o.total, "customer_name": o.customer_name} for o in orders_without_page]
    })


# ===============================
# Profile Settings
# ===============================

@employees_bp.route("/profile/update", methods=["POST"])
def profile_update():
    """تحديث الاسم الشخصي"""
    if "user_id" not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    
    data = request.json
    new_name = data.get("name", "").strip()
    
    if not new_name:
        return jsonify({"error": "الاسم مطلوب"}), 400
    
    emp = Employee.query.get(session["user_id"])
    if not emp:
        return jsonify({"error": "الموظف غير موجود"}), 404
        
    emp.name = new_name
    db.session.commit()
    
    # تحديث الاسم في الجلسة ليعكس التغيير فوراً في القوالب
    session["name"] = new_name
    
    return jsonify({"success": True, "message": "تم تحديث الاسم بنجاح"})


@employees_bp.route("/profile/settings", methods=["POST"])
def profile_settings():
    """تحديث اللغة والوضع الليلي"""
    if "user_id" not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
    
    data = request.json
    language = data.get("language")
    theme = data.get("theme")
    
    emp = Employee.query.get(session["user_id"])
    if not emp:
        return jsonify({"error": "الموظف غير موجود"}), 404
    
    if language in ["ar", "en", "ku", "tr"]:
        emp.language = language
        session["language"] = language # Persistence in session
        
    if theme in ["dark", "light", "system"]:
        emp.theme_preference = theme
        session["theme"] = theme # Persistence in session
        
    db.session.commit()
    return jsonify({"success": True})


@employees_bp.route("/profile/upload", methods=["POST"])
def profile_upload():
    """رفع صورة شخصية"""
    if "user_id" not in session:
        return jsonify({"error": "غير مسجل دخول"}), 401
        
    if 'file' not in request.files:
        return jsonify({"error": "لم يتم اختيار ملف"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "لم يتم اختيار ملف"}), 400
        
    if file:
        import os
        from werkzeug.utils import secure_filename
        
        # التأكد من وجود مجلد الرفع
        upload_folder = os.path.join('static', 'uploads', 'profiles')
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
            
        filename = secure_filename(f"user_{session['user_id']}_{file.filename}")
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)
        
        # تحديث قاعدة البيانات
        emp = Employee.query.get(session["user_id"])
        if emp:
            # مسح الصورة القديمة إذا وجدت
            if emp.profile_pic and os.path.exists(emp.profile_pic):
                try:
                    os.remove(emp.profile_pic)
                except:
                    pass
            
            emp.profile_pic = file_path.replace('\\', '/')
            db.session.commit()
            
            return jsonify({
                "success": True, 
                "message": "تم رفع الصورة بنجاح",
                "profile_pic": emp.profile_pic
            })
            
    return jsonify({"error": "فشل الرفع"}), 500
