from functools import wraps

from flask import flash, redirect

from utils.permission_checks import employee_can, get_current_employee


def permission_required(permission_name):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            employee = get_current_employee()
            if not employee:
                return redirect("/pos")
            if not employee_can(employee, permission_name):
                flash(f"لا تملك الصلاحية اللازمة للقيام بهذا الإجراء ({permission_name})", "danger")
                return redirect("/")
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        employee = get_current_employee()
        if not employee or employee.role != "admin":
            flash("هذا الإجراء للمدراء فقط", "danger")
            return redirect("/")
        return f(*args, **kwargs)

    return decorated_function
