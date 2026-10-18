"""Durable supplier-sale replay. Business document and deduplication receipt commit together."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID

from flask import jsonify, request, session
from sqlalchemy.exc import IntegrityError, OperationalError

from extensions import db
from modules.desktop_api.routes import desktop_api_bp
from utils.permission_checks import check_permission, get_current_employee
from utils.plan_guard import feature_required


class DesktopSyncReceipt(db.Model):
    __tablename__ = "desktop_sync_receipt"
    __table_args__ = (db.UniqueConstraint("device_id", "operation_id", name="_desktop_sync_operation_uc"),)
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(36), nullable=False)
    operation_id = db.Column(db.String(36), nullable=False)
    employee_id = db.Column(db.Integer, nullable=False)
    branch_id = db.Column(db.Integer, nullable=False)
    fingerprint = db.Column(db.String(64), nullable=False)
    response_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


@desktop_api_bp.errorhandler(OperationalError)
def temporary_database_failure(error):
    db.session.rollback()
    return jsonify(success=False, error="قاعدة البيانات مشغولة مؤقتاً؛ أعد المحاولة بنفس معرّف العملية"), 503


def _receipt_response(receipt, employee_id, branch_id, fingerprint):
    if receipt.employee_id != employee_id or receipt.branch_id != branch_id:
        return jsonify(success=False, error="معرّف العملية يتبع مستخدماً أو فرعاً آخر"), 403
    if receipt.fingerprint != fingerprint:
        return jsonify(success=False, error="لا يمكن تغيير بيانات عملية أُرسلت بنفس المعرّف"), 409
    if not receipt.response_json:
        return jsonify(success=False, error="العملية قيد التسجيل؛ أعد المزامنة بنفس المعرّف"), 503
    return jsonify(json.loads(receipt.response_json))


@desktop_api_bp.post("/sync/supplier-sale")
@feature_required("suppliers")
def synchronize_supplier_sale():
    from routes.suppliers import _create_management_supplier_sale, _ensure_supplier_schema
    from utils.branch_context import current_branch_id, init_branch_context
    from utils.branch_migration import get_default_branch
    from utils.inventory_audit_trail import ensure_inventory_audit_schema
    from utils.supplier_payment_allocation import ensure_supplier_payment_allocation_schema
    from utils.supplier_sale_service import SupplierSaleError, ensure_supplier_sale_schema

    if not session.get("user_id") or not get_current_employee():
        return jsonify(success=False, error="سجّل الدخول إلى FINORA أولاً"), 401
    if not check_permission("can_manage_suppliers"):
        return jsonify(success=False, error="غير مصرح"), 403
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(success=False, error="بيانات المزامنة غير صحيحة"), 400
    try:
        device_id = str(UUID(str(body.get("device_id", ""))))
        operation_id = str(UUID(str(body.get("operation_id", ""))))
        supplier_id = int(body.get("supplier_id", 0))
        if isinstance(body.get("supplier_id"), bool) or supplier_id <= 0 or supplier_id != body.get("supplier_id"):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        return jsonify(success=False, error="معرّفات المزامنة غير صحيحة"), 400
    init_branch_context()
    branch_id = current_branch_id()
    if not branch_id:
        branch = get_default_branch()
        branch_id = branch.id if branch else None
    if not branch_id:
        return jsonify(success=False, error="حدد فرعاً صالحاً للمزامنة"), 400
    if "branch_id" in body and body["branch_id"] != branch_id:
        return jsonify(success=False, error="تغيّر الفرع منذ حفظ المسودة؛ لم تُسجّل الفاتورة"), 403
    employee_id = int(session["user_id"])
    payload = {"supplier_id": supplier_id, "items": body.get("items"), "note": body.get("note", "")}
    if "reservations" in body:
        payload["reservations"] = body["reservations"]
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    # All schema preparation precedes the receipt/business transaction.
    _ensure_supplier_schema()
    ensure_supplier_sale_schema()
    ensure_supplier_payment_allocation_schema()
    ensure_inventory_audit_schema()
    DesktopSyncReceipt.__table__.create(bind=db.session.connection(), checkfirst=True)
    query = DesktopSyncReceipt.query.filter_by(device_id=device_id, operation_id=operation_id)
    receipt = query.first()
    if receipt:
        return _receipt_response(receipt, employee_id, branch_id, fingerprint)
    receipt = DesktopSyncReceipt(device_id=device_id, operation_id=operation_id, employee_id=employee_id,
                                 branch_id=branch_id, fingerprint=fingerprint)
    db.session.add(receipt)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        receipt = query.first()
        if receipt:
            return _receipt_response(receipt, employee_id, branch_id, fingerprint)
        return jsonify(success=False, error="تعذّرت مزامنة العملية؛ أعد المحاولة بنفس المعرّف"), 503
    try:
        if "reservations" in body:
            from modules.desktop_api.stock import consume_reserved_stock
            consume_reserved_stock(body["reservations"], body.get("items"), device_id, employee_id, branch_id)
        sale = _create_management_supplier_sale(supplier_id, payload)
        response = {"success": True, "invoice_no": sale.invoice_no, "sale_id": sale.id,
                    "grand_total": int(sale.grand_total or 0)}
        receipt.response_json = json.dumps(response, ensure_ascii=False)
        db.session.commit()
    except (ValueError, SupplierSaleError) as exc:
        db.session.rollback()
        return jsonify(success=False, error=str(exc)), 409
    except Exception:
        db.session.rollback()
        raise
    return jsonify(response)
