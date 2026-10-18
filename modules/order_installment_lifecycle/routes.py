# -*- coding: utf-8 -*-
"""HTTP routes for order installment lifecycle."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from extensions import db
from modules.order_installment_lifecycle import service as svc
from modules.order_installment_lifecycle.constants import ERROR_PERMISSION_DENIED
from modules.order_installment_lifecycle.models import OrderInstallmentLifecycle
from modules.order_installment_lifecycle.schema_guard import ensure_order_installment_tables
from utils.permission_checks import get_current_employee

order_installment_bp = Blueprint(
    "order_installment_lifecycle",
    __name__,
    url_prefix="/api/order-installment",
)


def _json_error(exc: Exception, default_code: int = 400):
    if isinstance(exc, svc.OrderInstallmentError):
        return jsonify({
            "success": False,
            "error": exc.message,
            "code": exc.code,
        }), exc.status_code
    return jsonify({"success": False, "error": str(exc)}), default_code


@order_installment_bp.route("/settings", methods=["GET"])
def get_settings():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    employee = get_current_employee()
    if not employee:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    ensure_order_installment_tables()
    return jsonify({
        "success": True,
        "settings": svc.settings_dict(),
        "ui": svc.ui_context_for_employee(employee),
    })


@order_installment_bp.route("/settings", methods=["PUT", "POST"])
def put_settings():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    employee = get_current_employee()
    if not employee:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    try:
        data = request.get_json(silent=True) or {}
        settings = svc.update_settings(data, employee=employee)
        db.session.commit()
        return jsonify({"success": True, "settings": settings, "message": "تم حفظ إعدادات دورة الأقساط"})
    except Exception as exc:
        db.session.rollback()
        return _json_error(exc)


@order_installment_bp.route("/mode", methods=["GET"])
def get_mode():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    employee = get_current_employee()
    ui = svc.ui_context_for_employee(employee)
    return jsonify({"success": True, **ui})


@order_installment_bp.route("/mode/enable", methods=["POST"])
def enable_mode():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    employee = get_current_employee()
    try:
        svc.set_installment_mode(True, employee=employee)
        return jsonify({
            "success": True,
            "mode_on": True,
            "message": "تم تفعيل وضع الأقساط. أي طلب جديد يتم إنشاؤه الآن سيتم تسجيله كطلب أقساط.",
        })
    except Exception as exc:
        return _json_error(exc)


@order_installment_bp.route("/mode/disable", methods=["POST"])
def disable_mode():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    employee = get_current_employee()
    try:
        svc.set_installment_mode(False, employee=employee)
        return jsonify({
            "success": True,
            "mode_on": False,
            "message": "تم إيقاف وضع الأقساط. الطلبات الجديدة ستُنشأ كطلبات عادية.",
        })
    except Exception as exc:
        return _json_error(exc)


@order_installment_bp.route("/lifecycles", methods=["GET"])
def list_lifecycles():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    employee = get_current_employee()
    if not employee or not svc.can_view(employee):
        return jsonify({
            "success": False,
            "error": "ليست لديك صلاحية عرض طلبات الأقساط",
            "code": ERROR_PERMISSION_DENIED,
        }), 403
    ensure_order_installment_tables()
    status = (request.args.get("status") or "").strip().upper() or None
    q = OrderInstallmentLifecycle.query
    if status:
        q = q.filter(OrderInstallmentLifecycle.status == status)
    rows = q.order_by(OrderInstallmentLifecycle.due_at.asc()).limit(500).all()
    return jsonify({
        "success": True,
        "items": [
            {**row.to_dict(), "countdown": svc.countdown_label(row)}
            for row in rows
        ],
        "summary": svc.dashboard_summary(),
    })


@order_installment_bp.route("/dashboard-summary", methods=["GET"])
def dashboard_summary():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    employee = get_current_employee()
    if not employee or not (svc.feature_enabled() and (svc.can_view(employee) or employee.role == "admin")):
        return jsonify({"success": True, "summary": None})
    return jsonify({"success": True, "summary": svc.dashboard_summary()})


@order_installment_bp.route("/grant-basic/<int:role_id>", methods=["POST"])
def grant_basic(role_id: int):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "غير مصرح"}), 403
    employee = get_current_employee()
    if not employee or not (employee.role == "admin" or employee.has_permission("manage_employees")):
        return jsonify({"success": False, "error": "غير مصرح", "code": ERROR_PERMISSION_DENIED}), 403
    from models.role import Role

    role = Role.query.get(role_id)
    if not role:
        return jsonify({"success": False, "error": "الدور غير موجود"}), 404
    granted = svc.grant_basic_permissions_to_role(role)
    db.session.commit()
    try:
        from utils.activity_logger import log_activity

        log_activity(
            "grant_installment_basic",
            "order_installment_lifecycle",
            f"منح صلاحيات الأقساط الأساسية للدور {role.name}",
            entity_type="role",
            entity_id=role.id,
            payload={"granted": granted},
        )
    except Exception:
        pass
    return jsonify({"success": True, "granted": granted, "message": "تم منح صلاحيات الأقساط الأساسية"})
