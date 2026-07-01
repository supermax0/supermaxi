from functools import wraps

from flask import flash, jsonify, redirect, request

from utils.permission_checks import employee_can, get_current_employee, guard_permission


def permission_required(permission_name):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            employee = get_current_employee()
            if not employee:
                return redirect("/login")
            denied = guard_permission(permission_name)
            if denied:
                if request.is_json or request.path.startswith("/api/"):
                    return denied
                flash(f"لا تملك الصلاحية اللازمة للقيام بهذا الإجراء ({permission_name})", "danger")
                return redirect("/")
            return f(*args, **kwargs)

        return decorated_function

    return decorator


def permission_required_api(permission_name):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            denied = guard_permission(permission_name, json=True)
            if denied:
                return denied
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
