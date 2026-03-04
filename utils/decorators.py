from functools import wraps
from flask import session, redirect, flash, abort
from models.employee import Employee

def permission_required(permission_name):
    """
    Decorator للتحقق من صلاحية المستخدم قبل السماح له بالدخول للمسار.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect('/pos')
            
            employee = Employee.query.get(session['user_id'])
            if not employee:
                return redirect('/pos')
            
            if not employee.has_permission(permission_name):
                flash(f"لا تملك الصلاحية اللازمة للقيام بهذا الإجراء ({permission_name})", "danger")
                # يمكن توجيهه لصفحة خطأ أو الصفحة الرئيسية
                return redirect('/')
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def admin_required(f):
    """
    Decorator خاص بالمدراء فقط.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/pos')
        
        employee = Employee.query.get(session['user_id'])
        if not employee or employee.role != 'admin':
            flash("هذا الإجراء للمدراء فقط", "danger")
            return redirect('/')
            
        return f(*args, **kwargs)
    return decorated_function
