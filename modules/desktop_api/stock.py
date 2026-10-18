"""Explicit, idempotent inventory grants and device-driven quota returns."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from uuid import UUID, uuid4

from flask import jsonify, request, session
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.desktop_api.routes import desktop_api_bp
from utils.desktop_stock_reservations import (
    DesktopStockGrant, DesktopStockAllocation, DesktopStockReturn, StockReservationError,
    GUARD_ERROR, GUARD_MESSAGE, ensure_reservation_schema,
)
from utils.permission_checks import check_permission, get_current_employee


def _fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _uuid(value):
    return str(UUID(str(value)))


def _positive(value):
    if type(value) is not int or not 0 < value <= 2147483647:
        raise StockReservationError("الكمية والمعرّف يجب أن يكونا عددين صحيحين أكبر من صفر")
    return value


def _context():
    from utils.branch_context import init_branch_context, current_branch_id
    from utils.branch_migration import get_default_branch
    if not session.get("user_id") or not get_current_employee():
        raise PermissionError("سجّل الدخول أولاً")
    if not (check_permission("can_manage_suppliers") or check_permission("view_pos")):
        raise PermissionError("غير مصرح بحجز مخزون للبيع")
    init_branch_context()
    branch_id = current_branch_id()
    if not branch_id:
        branch = get_default_branch()
        branch_id = branch.id if branch else None
    if not branch_id:
        raise StockReservationError("حدد فرعاً صالحاً")
    return int(session["user_id"]), int(branch_id)


def _owner(row, device, employee, branch):
    if row.device_id != device or row.employee_id != employee or row.branch_id != branch:
        raise PermissionError("الحصة تخص جهازاً أو مستخدماً أو فرعاً آخر")


@desktop_api_bp.errorhandler(StockReservationError)
def invalid_reservation(error):
    db.session.rollback()
    return jsonify(success=False, error=str(error)), 409


@desktop_api_bp.errorhandler(IntegrityError)
def reservation_integrity_error(error):
    db.session.rollback()
    if GUARD_ERROR in str(error):
        return jsonify(success=False, error=GUARD_MESSAGE), 409
    raise error


@desktop_api_bp.post("/stock/reserve")
def reserve_stock():
    from models.product import Product
    from models.product_color_variant import ProductColorVariant
    from utils.branch_stock_service import get_or_create_branch_stock, _branch_product_id, set_branch_stock
    from utils.product_color_service import product_has_colors, effective_color_sale_price
    try:
        employee, branch = _context()
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"id", "device_id", "branch_id", "items"}:
            raise StockReservationError("بيانات طلب الحجز غير صحيحة")
        grant_id, device = _uuid(body["id"]), _uuid(body["device_id"])
        if type(body["branch_id"]) is not int or body["branch_id"] != branch:
            raise PermissionError("تغيّر الفرع؛ لم يتم الحجز")
        if not isinstance(body["items"], list) or not 1 <= len(body["items"]) <= 100:
            raise StockReservationError("احجز من صنف واحد إلى 100 صنف")
        ensure_reservation_schema()
        fingerprint = _fingerprint(body["items"])
        existing = db.session.get(DesktopStockGrant, grant_id)
        if existing:
            _owner(existing, device, employee, branch)
            if existing.fingerprint != fingerprint:
                raise StockReservationError("لا يمكن تغيير طلب حجز سبق إرساله بنفس المعرّف")
            return jsonify(json.loads(existing.response_json))
        allocations, rows, keys = [], [], set()
        for item in body["items"]:
            if not isinstance(item, dict) or set(item) - {"product_id", "qty", "variant_color"}:
                raise StockReservationError("بيانات صنف الحجز غير صحيحة")
            requested_id, qty = _positive(item.get("product_id")), _positive(item.get("qty"))
            color = item.get("variant_color", "")
            if not isinstance(color, str) or len(color) > 80:
                raise StockReservationError("اللون غير صحيح")
            color = color.strip()
            requested = Product.query.filter_by(id=requested_id, active=True).first()
            if not requested:
                raise StockReservationError("المنتج غير موجود في الفرع الحالي")
            product_id = _branch_product_id(branch, requested_id)
            product = Product.query.execution_options(skip_branch_scope=True).get(product_id)
            from utils.desktop_stock_reservations import require_general_stock
            require_general_stock(product_id)
            if product.branch_id and product.branch_id != branch:
                raise StockReservationError("هذا المنتج لا يملك رصيداً في الفرع المختار")
            stock = get_or_create_branch_stock(branch, product_id)
            variant = None
            if product_has_colors(product):
                variant = ProductColorVariant.query.filter_by(product_id=product_id, color_name=color).first()
                if not variant:
                    raise StockReservationError("اختر لوناً صالحاً للحجز")
                color_total = db.session.query(db.func.sum(ProductColorVariant.quantity)).filter_by(product_id=product_id).scalar()
                if int(stock.quantity or 0) != int(color_total or 0):
                    set_branch_stock(branch, product_id, int(color_total or 0))
            elif color:
                raise StockReservationError("المنتج لا يملك هذا اللون")
            key = (stock.id, variant.id if variant else 0)
            if key in keys:
                raise StockReservationError("اجمع الكميات المكررة في صنف واحد")
            keys.add(key)
            allocation = DesktopStockAllocation(id=str(uuid4()), grant_id=grant_id, product_id=product_id,
                requested_product_id=requested_id, branch_id=branch, stock_id=stock.id,
                variant_id=variant.id if variant else 0, color=color, quantity=qty, consumed=0, returned=0)
            allocations.append(allocation)
            rows.append({"id": allocation.id, "product_id": requested_id, "name": requested.name,
                         "variant_color": color, "quantity": qty,
                         "sale_price": effective_color_sale_price(product, variant=variant) if variant else int(product.sale_price or 0)})
        result = {"success": True, "id": grant_id, "device_id": device, "employee_id": employee,
                  "branch_id": branch, "allocations": rows}
        db.session.add(DesktopStockGrant(id=grant_id, device_id=device, employee_id=employee,
                          branch_id=branch, fingerprint=fingerprint, response_json=json.dumps(result, ensure_ascii=False)))
        db.session.add_all(allocations)
        db.session.commit()
        return jsonify(result)
    except IntegrityError:
        db.session.rollback()
        existing = db.session.get(DesktopStockGrant, grant_id)
        if existing:
            try:
                _owner(existing, device, employee, branch)
            except PermissionError as exc:
                return jsonify(success=False, error=str(exc)), 403
            if existing.fingerprint == fingerprint:
                return jsonify(json.loads(existing.response_json))
            raise StockReservationError("لا يمكن تغيير طلب حجز سبق إرساله بنفس المعرّف")
        raise
    except PermissionError as exc:
        db.session.rollback()
        return jsonify(success=False, error=str(exc)), 403
    except (ValueError, TypeError, AttributeError) as exc:
        if isinstance(exc, StockReservationError):
            raise
        raise StockReservationError("معرّفات الحجز غير صحيحة") from exc


def _parts(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 1000:
        raise StockReservationError("توزيع حصة الجهاز غير صحيح")
    seen = set()
    for part in raw:
        if not isinstance(part, dict) or set(part) != {"id", "qty"}:
            raise StockReservationError("بيانات حصة الجهاز غير صحيحة")
        allocation_id, qty = _uuid(part["id"]), _positive(part["qty"])
        if allocation_id in seen:
            raise StockReservationError("حصة مكررة في نفس العملية")
        seen.add(allocation_id)
        yield allocation_id, qty


def consume_reserved_stock(parts, items, device, employee, branch):
    """Caller owns receipt + quota consumption + business document transaction."""
    from utils.branch_stock_service import _branch_product_id
    expected, consumed = defaultdict(int), defaultdict(int)
    if not isinstance(items, list):
        raise StockReservationError("أصناف البيع غير صحيحة")
    for item in items:
        product = _branch_product_id(branch, _positive(item.get("product_id")))
        from utils.desktop_stock_reservations import require_general_stock
        require_general_stock(product)
        color = item.get("variant_color", "")
        if not isinstance(color, str):
            raise StockReservationError("اللون غير صحيح")
        expected[(product, color.strip())] += _positive(item.get("qty"))
    for allocation_id, qty in _parts(parts):
        allocation = db.session.get(DesktopStockAllocation, allocation_id)
        if not allocation:
            raise StockReservationError("الحصة غير موجودة")
        grant = db.session.get(DesktopStockGrant, allocation.grant_id)
        _owner(grant, device, employee, branch)
        consumed[(allocation.product_id, allocation.color)] += qty
        updated = DesktopStockAllocation.query.filter(
            DesktopStockAllocation.id == allocation_id,
            DesktopStockAllocation.quantity - DesktopStockAllocation.consumed - DesktopStockAllocation.returned >= qty,
        ).update({DesktopStockAllocation.consumed: DesktopStockAllocation.consumed + qty}, synchronize_session=False)
        if updated != 1:
            raise StockReservationError("الحصة مستهلكة أو مُعادة؛ لم يُسجل البيع")
    if dict(expected) != dict(consumed):
        raise StockReservationError("كمية أو لون البيع لا يطابق الحصة المحجوزة")


@desktop_api_bp.post("/stock/return")
def return_stock():
    try:
        employee, branch = _context()
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"id", "device_id", "branch_id", "parts"}:
            raise StockReservationError("بيانات إعادة الحصة غير صحيحة")
        return_id, device = _uuid(body["id"]), _uuid(body["device_id"])
        if type(body["branch_id"]) is not int or body["branch_id"] != branch:
            raise PermissionError("تغيّر الفرع؛ لم تتم الإعادة")
        ensure_reservation_schema()
        fingerprint = _fingerprint(body["parts"])
        existing = db.session.get(DesktopStockReturn, return_id)
        if existing:
            _owner(existing, device, employee, branch)
            if existing.fingerprint != fingerprint:
                raise StockReservationError("لا يمكن تغيير طلب إعادة سبق إرساله بنفس المعرّف")
            return jsonify(json.loads(existing.response_json))
        for allocation_id, qty in _parts(body["parts"]):
            allocation = db.session.get(DesktopStockAllocation, allocation_id)
            if not allocation:
                raise StockReservationError("الحصة غير موجودة")
            _owner(db.session.get(DesktopStockGrant, allocation.grant_id), device, employee, branch)
            updated = DesktopStockAllocation.query.filter(
                DesktopStockAllocation.id == allocation_id,
                DesktopStockAllocation.quantity - DesktopStockAllocation.consumed - DesktopStockAllocation.returned >= qty,
            ).update({DesktopStockAllocation.returned: DesktopStockAllocation.returned + qty}, synchronize_session=False)
            if updated != 1:
                raise StockReservationError("الكمية المراد إعادتها مستهلكة أو مُعادة")
        result = {"success": True, "id": return_id}
        db.session.add(DesktopStockReturn(id=return_id, device_id=device, employee_id=employee, branch_id=branch,
                            fingerprint=fingerprint, response_json=json.dumps(result)))
        db.session.commit()
        return jsonify(result)
    except IntegrityError:
        db.session.rollback()
        existing = db.session.get(DesktopStockReturn, return_id)
        if existing:
            try:
                _owner(existing, device, employee, branch)
            except PermissionError as exc:
                return jsonify(success=False, error=str(exc)), 403
            if existing.fingerprint == fingerprint:
                return jsonify(json.loads(existing.response_json))
            raise StockReservationError("لا يمكن تغيير طلب إعادة سبق إرساله بنفس المعرّف")
        raise
    except PermissionError as exc:
        db.session.rollback()
        return jsonify(success=False, error=str(exc)), 403
    except (ValueError, TypeError, AttributeError) as exc:
        if isinstance(exc, StockReservationError):
            raise
        raise StockReservationError("معرّفات إعادة الحصة غير صحيحة") from exc
