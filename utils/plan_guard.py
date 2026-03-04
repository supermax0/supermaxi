"""
plan_guard.py — Decorators لحماية الـ routes بناءً على خطة الاشتراك.
"""
from functools import wraps
from flask import session, jsonify, request, render_template
from utils.plan_limits import has_feature, check_user_limit, check_order_limit, get_plan


def feature_required(feature_name):
    """
    Decorator يمنع الوصول إذا لم تكن خطة الاشتراك تدعم الميزة.
    يُرجع JSON إذا كان الطلب AJAX، أو HTML لو كان صفحة عادية.

    الاستخدام:
        @blueprint.route("/suppliers")
        @feature_required("suppliers")
        def suppliers_page():
            ...
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # الأدمن يتجاوز كل فحوصات الخطط
            if session.get("role") == "admin":
                return fn(*args, **kwargs)
            plan_key = session.get("plan_key", "basic")
            if not has_feature(plan_key, feature_name):
                plan = get_plan(plan_key)
                if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({
                        "error": "upgrade_required",
                        "feature": feature_name,
                        "current_plan": plan_key,
                        "message": f"هذه الميزة غير متاحة في {plan['name']}. يرجى الترقية."
                    }), 403
                return render_template("upgrade_required.html",
                    feature=feature_name,
                    plan=plan), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def users_limit_check():
    """
    يُستدعى قبل إضافة موظف جديد للتحقق من عدم تجاوز الحد.
    يُرجع dict مع "ok" و "error" إذا وُجد.
    """
    from models.employee import Employee
    tenant_id = session.get("tenant_id")
    plan_key  = session.get("plan_key", "basic")
    if not tenant_id:
        return {"ok": True}
    count = Employee.query.filter_by(tenant_id=tenant_id).count()
    if not check_user_limit(plan_key, count):
        plan = get_plan(plan_key)
        return {
            "ok": False,
            "error": f"وصلت للحد الأقصى من المستخدمين ({plan['max_users']}) في {plan['name']}."
        }
    return {"ok": True}


def orders_limit_check():
    """
    يُستدعى قبل إنشاء طلب جديد للتحقق من عدم تجاوز حد الطلبات الشهرية.
    """
    from datetime import datetime
    tenant_id = session.get("tenant_id")
    plan_key  = session.get("plan_key", "basic")
    plan      = get_plan(plan_key)
    max_orders = plan["max_orders_monthly"]
    if max_orders is None:
        return {"ok": True}
    if not tenant_id:
        return {"ok": True}
    try:
        from models.order_item import OrderItem
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        count = OrderItem.query.filter(
            OrderItem.created_at >= month_start
        ).count()
        if not check_order_limit(plan_key, count):
            return {
                "ok": False,
                "error": f"وصلت للحد الأقصى من الطلبات الشهرية ({max_orders:,}) في {plan['name']}."
            }
    except Exception:
        pass
    return {"ok": True}
