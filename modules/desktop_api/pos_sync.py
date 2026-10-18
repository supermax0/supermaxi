"""A reserved POS invoice, collection and replay receipt share one transaction."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from uuid import UUID

from flask import jsonify, request
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.invoice import Invoice
from models.treasury_account import TreasuryAccount
from modules.desktop_api.routes import desktop_api_bp
from modules.desktop_api.stock import _context, _fingerprint, _positive, consume_reserved_stock
from modules.desktop_api.sync import DesktopSyncReceipt, _receipt_response
from services.pos_checkout import PosCheckoutError, create_pos_order
from utils.desktop_stock_reservations import ensure_reservation_schema
from utils.permission_checks import check_permission, get_current_employee


@desktop_api_bp.post("/sync/pos-sale")
def synchronize_pos_sale():
    try:
        employee_id, branch_id = _context()
    except PermissionError as exc:
        return jsonify(success=False, error=str(exc)), 403
    if not check_permission("view_pos"):
        return jsonify(success=False, error="غير مصرح بالبيع من نقطة البيع"), 403
    from modules.order_installment_lifecycle.service import is_installment_mode_on
    if is_installment_mode_on():
        return jsonify(success=False, error="دورة الأقساط تحتاج مسارها الخاص؛ البيع المحلي غير مفعّل لها بعد"), 409
    body = request.get_json(silent=True)
    try:
        required = {"device_id", "operation_id", "branch_id", "sale" , "reservations"}
        if not isinstance(body, dict) or not required <= set(body) or set(body) - required - {"created_at", "local_invoice_no"} or type(body["branch_id"]) is not int or body["branch_id"] != branch_id:
            raise ValueError("بيانات المزامنة أو الفرع غير صحيحة")
        device, operation = str(UUID(body["device_id"])), str(UUID(body["operation_id"]))
        created_at = None
        if "created_at" in body:
            if type(body["created_at"]) is not int or not 0 < body["created_at"] < 10000000000000:
                raise ValueError("وقت البيع المحلي غير صحيح")
            created_at = datetime.utcfromtimestamp(body["created_at"] / 1000)
            if created_at > datetime.utcnow() + timedelta(minutes=5):
                raise ValueError("ساعة الجهاز متقدمة؛ راجع وقت البيع المحلي")
        local_number = body.get("local_invoice_no", "")
        if not isinstance(local_number, str) or (local_number and not re.fullmatch(rf"OFF-{device.replace('-', '')}-[0-9]{{6,16}}", local_number)):
            raise ValueError("رقم الإيصال المحلي لا يطابق الجهاز")
        sale = body["sale"]
        if not isinstance(sale, dict) or set(sale) != {"kind", "customerId", "customerName", "items", "discount", "total", "accountId", "payment"} or sale["kind"] != "pos":
            raise ValueError("بيانات البيع غير صحيحة")
        _positive(sale["customerId"])
        _positive(sale["total"])
        if type(sale["discount"]) is not int or not 0 <= sale["discount"] <= 2147483647:
            raise ValueError("الخصم غير صحيح")
        if not isinstance(sale["customerName"], str) or not 1 <= len(sale["customerName"]) <= 150:
            raise ValueError("اسم الزبون غير صحيح")
        if sale["payment"] not in ("cash", "bank", "credit"):
            raise ValueError("طريقة الدفع غير صحيحة")
        if sale["payment"] != "credit":
            _positive(sale["accountId"])
            if not check_permission("pay_orders"):
                return jsonify(success=False, error="غير مصرح بالتحصيل"), 403
        elif sale["accountId"] is not None:
            raise ValueError("البيع الآجل لا يتضمن حساب تحصيل")
        items = sale["items"]
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise ValueError("أصناف البيع غير صحيحة")
        subtotal = 0
        for item in items:
            if not isinstance(item, dict) or set(item) - {"product_id", "qty", "price", "variant_color"}:
                raise ValueError("بيانات صنف البيع غير صحيحة")
            for key in ("product_id", "qty", "price"):
                _positive(item.get(key))
            if not isinstance(item.get("variant_color", ""), str) or len(item.get("variant_color", "")) > 80:
                raise ValueError("اللون غير صحيح")
            subtotal += item["qty"] * item["price"]
        if subtotal > 2147483647 or sale["discount"] >= subtotal or sale["total"] != subtotal - sale["discount"]:
            raise ValueError("قيمة البيع لا تطابق الأصناف والخصم")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return jsonify(success=False, error=str(exc) or "بيانات البيع غير صحيحة"), 400

    # Schema repair/default-account creation must never commit a replay receipt.
    from utils.product_schema_guard import ensure_customer_blacklist_columns
    from utils.treasury_schema_guard import ensure_treasury_schema
    from utils.payment_ledger import ensure_invoice_payment_ledger_table, append_payment_ledger_delta
    from utils.stock_movement_guard import ensure_stock_movement_schema
    ensure_customer_blacklist_columns()
    ensure_treasury_schema()
    ensure_invoice_payment_ledger_table()
    ensure_stock_movement_schema()
    ensure_reservation_schema()
    DesktopSyncReceipt.__table__.create(db.session.connection(), checkfirst=True)
    fingerprint = _fingerprint({"kind": "pos-sale", "sale": sale, "reservations": body["reservations"],
        **{key: body[key] for key in ("created_at", "local_invoice_no") if key in body}})
    query = DesktopSyncReceipt.query.filter_by(device_id=device, operation_id=operation)
    receipt = query.first()
    if receipt:
        return _receipt_response(receipt, employee_id, branch_id, fingerprint)
    try:
        receipt = DesktopSyncReceipt(device_id=device, operation_id=operation, employee_id=employee_id,
            branch_id=branch_id, fingerprint=fingerprint)
        db.session.add(receipt)
        db.session.flush()
        account = None
        if sale["payment"] != "credit":
            account = TreasuryAccount.query.execution_options(skip_branch_scope=True).filter_by(
                id=sale["accountId"], branch_id=branch_id, is_active=True).first()
            if not account or (account.account_type.lower() == "cash") != (sale["payment"] == "cash"):
                raise ValueError("حساب التحصيل غير مفعّل أو لا يتبع الفرع وطريقة الدفع")
        consume_reserved_stock(body["reservations"], items, device, employee_id, branch_id)
        created = create_pos_order(employee=get_current_employee(), customer_id=sale["customerId"],
            items=items, branch_id=branch_id, discount_amount=sale["discount"],
            note=f"بيع محلي · {local_number}" if local_number else None,
            source="web_pos", raw_data={"discount_amount": sale["discount"]}, commit=False)
        if created["stock_locked"]:
            raise ValueError("تعذّر تنفيذ المخزون المحجوز؛ راجع العملية")
        invoice = db.session.get(Invoice, created["invoice_id"])
        if created_at:
            invoice.created_at = created_at
        if int(invoice.total or 0) != sale["total"]:
            raise ValueError("تغيّر السعر المعتمد؛ راجع الفاتورة المحلية قبل مزامنتها")
        from utils.order_stock_policy import deduct_order_stock
        deduct_order_stock(invoice)  # Credit sales also represent goods handed over offline.
        invoice.status = "تم التوصيل"
        if account:
            invoice.payment_status = "مسدد"
            invoice.paid_amount = invoice.total
            append_payment_ledger_delta(invoice.id, invoice.total, account.id,
                recorded_at=created_at, source_module="desktop_pos", payment_method=sale["payment"], note=local_number or None)
        from utils.payroll_service import sync_commission_line_for_invoice
        sync_commission_line_for_invoice(invoice)
        response = {"success": True, "invoice_no": str(invoice.id), "invoice_id": invoice.id,
            "total": int(invoice.total), "payment_status": invoice.payment_status}
        receipt.response_json = json.dumps(response, ensure_ascii=False)
        db.session.commit()
        return jsonify(response)
    except IntegrityError:
        db.session.rollback()
        receipt = query.first()
        if receipt:
            return _receipt_response(receipt, employee_id, branch_id, fingerprint)
        raise
    except (ValueError, PosCheckoutError) as exc:
        db.session.rollback()
        return jsonify(success=False, error=str(exc)), 409
    except Exception:
        db.session.rollback()
        raise
