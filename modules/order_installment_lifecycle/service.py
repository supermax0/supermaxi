# -*- coding: utf-8 -*-
"""Domain service for order installment lifecycle."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Optional

from flask import session
from sqlalchemy import func

from extensions import db
from modules.order_installment_lifecycle.constants import (
    BASIC_PERMISSIONS,
    ERROR_FEATURE_DISABLED,
    ERROR_PERMISSION_DENIED,
    IDEMPOTENCY_PREFIX,
    PERM_CREATE,
    PERM_MODE_TOGGLE,
    PERM_SETTINGS,
    PERM_VIEW,
    SESSION_MODE_KEY,
    SETTLEABLE_STATUSES,
    STATUS_ACTIVE,
    STATUS_AUTO_SETTLED,
    STATUS_CANCELLED,
    STATUS_MANUALLY_SETTLED,
    STATUS_PARTIALLY_RETURNED,
    STATUS_RETURNED,
)
from modules.order_installment_lifecycle.models import (
    OrderInstallmentEvent,
    OrderInstallmentLifecycle,
    OrderInstallmentSettings,
)
from modules.order_installment_lifecycle.schema_guard import ensure_order_installment_tables


class OrderInstallmentError(Exception):
    def __init__(self, message: str, code: str = ERROR_PERMISSION_DENIED, status_code: int = 403):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def _now() -> datetime:
    return datetime.utcnow()


def _employee_can(employee, permission_name: str) -> bool:
    if employee is None:
        return False
    try:
        from utils.permission_checks import employee_can

        return bool(employee_can(employee, permission_name))
    except Exception:
        return bool(getattr(employee, "has_permission", lambda _: False)(permission_name))


def get_settings(*, create_defaults: bool = True) -> OrderInstallmentSettings:
    ensure_order_installment_tables()
    row = OrderInstallmentSettings.query.order_by(OrderInstallmentSettings.id.asc()).first()
    if row is None and create_defaults:
        row = OrderInstallmentSettings()
        db.session.add(row)
        db.session.flush()
    return row


def settings_dict() -> dict:
    row = get_settings()
    return row.to_dict() if row else {
        "enabled": False,
        "duration_value": 7,
        "duration_unit": "days",
        "auto_settle_enabled": True,
        "allow_return": True,
        "notify_before_due": False,
        "confirm_on_create": True,
        "event_log_enabled": True,
        "cancel_auto_on_full_return": True,
        "cancel_auto_on_cancel": True,
        "cancel_auto_on_manual_settle": True,
    }


def update_settings(payload: dict, *, employee=None) -> dict:
    if employee is not None and not can_manage_settings(employee):
        raise OrderInstallmentError(
            "ليست لديك صلاحية تعديل إعدادات دورة الأقساط",
            code=ERROR_PERMISSION_DENIED,
        )
    row = get_settings()
    if "enabled" in payload:
        row.enabled = bool(payload.get("enabled"))
    if "duration_value" in payload:
        try:
            value = int(payload.get("duration_value") or 7)
        except (TypeError, ValueError):
            value = 7
        row.duration_value = max(1, min(value, 3650))
    if "duration_unit" in payload:
        unit = str(payload.get("duration_unit") or "days").strip().lower()
        row.duration_unit = unit if unit in ("days", "hours") else "days"
    for flag in (
        "auto_settle_enabled",
        "allow_return",
        "notify_before_due",
        "confirm_on_create",
        "event_log_enabled",
        "cancel_auto_on_full_return",
        "cancel_auto_on_cancel",
        "cancel_auto_on_manual_settle",
    ):
        if flag in payload:
            setattr(row, flag, bool(payload.get(flag)))
    row.updated_at = _now()
    if not row.enabled:
        clear_installment_mode()
    db.session.flush()
    return row.to_dict()


def feature_enabled() -> bool:
    row = get_settings(create_defaults=True)
    return bool(row and row.enabled)


def can_view(employee) -> bool:
    return feature_enabled() and _employee_can(employee, PERM_VIEW)


def can_toggle_mode(employee) -> bool:
    return feature_enabled() and _employee_can(employee, PERM_MODE_TOGGLE)


def can_create(employee) -> bool:
    return feature_enabled() and _employee_can(employee, PERM_CREATE)


def can_manage_settings(employee) -> bool:
    return _employee_can(employee, PERM_SETTINGS) or _employee_can(employee, "manage_settings")


def is_installment_mode_on() -> bool:
    return bool(session.get(SESSION_MODE_KEY))


def clear_installment_mode() -> None:
    try:
        session.pop(SESSION_MODE_KEY, None)
    except Exception:
        pass


def set_installment_mode(enabled: bool, *, employee=None) -> bool:
    if enabled:
        if not feature_enabled():
            clear_installment_mode()
            raise OrderInstallmentError(
                "دورة طلب الأقساط غير مفعّلة من الإعدادات",
                code=ERROR_FEATURE_DISABLED,
            )
        if not can_toggle_mode(employee):
            clear_installment_mode()
            raise OrderInstallmentError(
                "ليست لديك صلاحية تفعيل وضع الأقساط",
                code=ERROR_PERMISSION_DENIED,
            )
        session[SESSION_MODE_KEY] = True
        _log_activity_safe(
            "installment_mode_on",
            "تفعيل وضع الأقساط",
            employee=employee,
        )
        return True
    session[SESSION_MODE_KEY] = False
    _log_activity_safe(
        "installment_mode_off",
        "إيقاف وضع الأقساط",
        employee=employee,
    )
    return False


def compute_due_at(started_at: datetime, settings: Optional[OrderInstallmentSettings] = None) -> datetime:
    settings = settings or get_settings()
    value = max(1, int(settings.duration_value or 7))
    unit = (settings.duration_unit or "days").strip().lower()
    if unit == "hours":
        return started_at + timedelta(hours=value)
    return started_at + timedelta(days=value)


def get_lifecycle_for_order(order_id: int) -> Optional[OrderInstallmentLifecycle]:
    ensure_order_installment_tables()
    return (
        OrderInstallmentLifecycle.query.filter_by(order_id=int(order_id))
        .order_by(OrderInstallmentLifecycle.id.desc())
        .first()
    )


def map_lifecycles_for_orders(order_ids: list[int]) -> dict[int, OrderInstallmentLifecycle]:
    if not order_ids:
        return {}
    ensure_order_installment_tables()
    rows = (
        OrderInstallmentLifecycle.query.filter(
            OrderInstallmentLifecycle.order_id.in_([int(i) for i in order_ids])
        ).all()
    )
    by_order: dict[int, OrderInstallmentLifecycle] = {}
    for row in rows:
        existing = by_order.get(row.order_id)
        if existing is None or (row.id or 0) > (existing.id or 0):
            by_order[row.order_id] = row
    return by_order


def start_lifecycle(invoice, employee=None, *, force: bool = False) -> Optional[OrderInstallmentLifecycle]:
    """Create lifecycle for a newly created invoice when installment mode is ON."""
    ensure_order_installment_tables()
    settings = get_settings()
    if not settings.enabled:
        return None
    if not force and not is_installment_mode_on():
        return None
    if not can_create(employee):
        raise OrderInstallmentError(
            "ليست لديك صلاحية إنشاء طلب أقساط",
            code=ERROR_PERMISSION_DENIED,
        )
    existing = get_lifecycle_for_order(invoice.id)
    if existing:
        return existing

    started_at = getattr(invoice, "created_at", None) or _now()
    due_at = compute_due_at(started_at, settings)
    lifecycle = OrderInstallmentLifecycle(
        order_id=invoice.id,
        employee_id=getattr(employee, "id", None) or getattr(invoice, "employee_id", None),
        status=STATUS_ACTIVE,
        started_at=started_at,
        due_at=due_at,
        returned_amount=0,
        settled_amount=0,
        idempotency_key=None,
    )
    db.session.add(lifecycle)
    db.session.flush()
    log_event(
        lifecycle,
        "created",
        old_status=None,
        new_status=STATUS_ACTIVE,
        employee_id=lifecycle.employee_id,
        metadata={
            "due_at": due_at.isoformat(sep=" "),
            "duration_value": settings.duration_value,
            "duration_unit": settings.duration_unit,
        },
    )
    _log_activity_safe(
        "installment_lifecycle_created",
        f"إنشاء طلب أقساط #{invoice.id} — استحقاق {due_at.strftime('%Y-%m-%d %H:%M')}",
        employee=employee,
        entity_id=invoice.id,
        payload=lifecycle.to_dict(),
    )
    return lifecycle


def settlement_amount(lifecycle: OrderInstallmentLifecycle, invoice) -> int:
    total = max(0, int(getattr(invoice, "total", 0) or 0))
    returned = max(0, int(lifecycle.returned_amount or 0))
    paid = max(0, int(getattr(invoice, "paid_amount", 0) or 0))
    return max(0, total - returned - paid)


def log_event(
    lifecycle: OrderInstallmentLifecycle,
    event_type: str,
    *,
    old_status: Optional[str] = None,
    new_status: Optional[str] = None,
    employee_id: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> None:
    settings = get_settings()
    if settings and not settings.event_log_enabled:
        return
    ensure_order_installment_tables()
    event = OrderInstallmentEvent(
        installment_lifecycle_id=lifecycle.id,
        order_id=lifecycle.order_id,
        employee_id=employee_id,
        event_type=event_type,
        old_status=old_status,
        new_status=new_status,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
    )
    db.session.add(event)


def _log_activity_safe(action: str, message: str, *, employee=None, entity_id=None, payload=None):
    try:
        from utils.activity_logger import log_activity

        log_activity(
            action,
            "order_installment_lifecycle",
            message,
            entity_type="invoice",
            entity_id=entity_id,
            payload=payload or {},
        )
    except Exception:
        pass


def on_order_returned(invoice, *, returned_amount: Optional[int] = None, employee_id: Optional[int] = None) -> None:
    lifecycle = get_lifecycle_for_order(getattr(invoice, "id", 0) or 0)
    if not lifecycle or lifecycle.status not in SETTLEABLE_STATUSES:
        return
    settings = get_settings()
    amount = returned_amount
    if amount is None:
        amount = max(0, int(getattr(invoice, "total", 0) or 0))
    old = lifecycle.status
    lifecycle.returned_amount = max(int(lifecycle.returned_amount or 0), int(amount or 0))
    if lifecycle.returned_amount >= int(getattr(invoice, "total", 0) or 0):
        lifecycle.status = STATUS_RETURNED
    else:
        lifecycle.status = STATUS_PARTIALLY_RETURNED
    lifecycle.updated_at = _now()
    log_event(
        lifecycle,
        "returned",
        old_status=old,
        new_status=lifecycle.status,
        employee_id=employee_id,
        metadata={"returned_amount": lifecycle.returned_amount},
    )
    if settings.cancel_auto_on_full_return and lifecycle.status == STATUS_RETURNED:
        log_event(
            lifecycle,
            "auto_settle_cancelled",
            old_status=lifecycle.status,
            new_status=lifecycle.status,
            employee_id=employee_id,
            metadata={"reason": "full_return"},
        )


def on_order_cancelled(invoice, *, employee_id: Optional[int] = None) -> None:
    lifecycle = get_lifecycle_for_order(getattr(invoice, "id", 0) or 0)
    if not lifecycle or lifecycle.status not in SETTLEABLE_STATUSES:
        return
    settings = get_settings()
    if not settings.cancel_auto_on_cancel:
        return
    old = lifecycle.status
    lifecycle.status = STATUS_CANCELLED
    lifecycle.updated_at = _now()
    log_event(
        lifecycle,
        "cancelled",
        old_status=old,
        new_status=STATUS_CANCELLED,
        employee_id=employee_id,
    )


def on_manual_payment(invoice, *, employee_id: Optional[int] = None) -> None:
    lifecycle = get_lifecycle_for_order(getattr(invoice, "id", 0) or 0)
    if not lifecycle or lifecycle.status not in SETTLEABLE_STATUSES:
        return
    settings = get_settings()
    paid = max(0, int(getattr(invoice, "paid_amount", 0) or 0))
    total = max(0, int(getattr(invoice, "total", 0) or 0))
    remaining = settlement_amount(lifecycle, invoice)
    if remaining > 0 and paid < total:
        log_event(
            lifecycle,
            "partial_payment",
            old_status=lifecycle.status,
            new_status=lifecycle.status,
            employee_id=employee_id,
            metadata={"paid_amount": paid, "remaining": remaining},
        )
        return
    if not settings.cancel_auto_on_manual_settle:
        return
    old = lifecycle.status
    lifecycle.status = STATUS_MANUALLY_SETTLED
    lifecycle.manual_settled_at = _now()
    lifecycle.settled_amount = max(int(lifecycle.settled_amount or 0), paid)
    lifecycle.updated_at = _now()
    log_event(
        lifecycle,
        "manually_settled",
        old_status=old,
        new_status=STATUS_MANUALLY_SETTLED,
        employee_id=employee_id,
        metadata={"paid_amount": paid},
    )


def _order_blocks_auto_settle(invoice) -> bool:
    from utils.order_status import is_canceled, is_returned, normalize_status

    if invoice is None:
        return True
    if is_returned(invoice.status, invoice.payment_status):
        return True
    if is_canceled(invoice.status, invoice.payment_status):
        return True
    payment = normalize_status(invoice.payment_status)
    if payment in {"مسدد", "مدفوع"}:
        return True
    return False


def auto_settle_due(lifecycle_id: int) -> dict[str, Any]:
    """Idempotent automatic settlement for a single lifecycle row."""
    ensure_order_installment_tables()
    from models.invoice import Invoice
    from utils.payment_ledger import append_payment_ledger_delta

    settings = get_settings()
    if not settings.enabled or not settings.auto_settle_enabled:
        return {"ok": False, "skipped": "disabled"}

    lifecycle = (
        OrderInstallmentLifecycle.query.filter_by(id=int(lifecycle_id))
        .with_for_update()
        .first()
    )
    if not lifecycle:
        return {"ok": False, "skipped": "missing"}
    if lifecycle.status not in SETTLEABLE_STATUSES:
        return {"ok": False, "skipped": "status", "status": lifecycle.status}
    if lifecycle.due_at and lifecycle.due_at > _now():
        return {"ok": False, "skipped": "not_due"}

    idem_key = f"{IDEMPOTENCY_PREFIX}{lifecycle.id}"
    if lifecycle.idempotency_key == idem_key and lifecycle.status == STATUS_AUTO_SETTLED:
        return {"ok": False, "skipped": "already_settled"}

    invoice = Invoice.query.filter(Invoice.id == lifecycle.order_id).with_for_update().first()
    if _order_blocks_auto_settle(invoice):
        if invoice and _order_blocks_auto_settle(invoice):
            from utils.order_status import is_returned, is_canceled

            if is_returned(invoice.status, invoice.payment_status):
                on_order_returned(invoice)
            elif is_canceled(invoice.status, invoice.payment_status):
                on_order_cancelled(invoice)
            elif (invoice.payment_status or "") in {"مسدد", "مدفوع"}:
                on_manual_payment(invoice)
        return {"ok": False, "skipped": "order_blocked"}

    amount = settlement_amount(lifecycle, invoice)
    if amount <= 0:
        old = lifecycle.status
        lifecycle.status = STATUS_AUTO_SETTLED
        lifecycle.auto_settled_at = _now()
        lifecycle.idempotency_key = idem_key
        lifecycle.updated_at = _now()
        log_event(
            lifecycle,
            "auto_settled_zero",
            old_status=old,
            new_status=STATUS_AUTO_SETTLED,
            metadata={"amount": 0},
        )
        return {"ok": True, "amount": 0}

    # Claim idempotency key before writing ledger so concurrent workers skip.
    existing_claim = (
        OrderInstallmentLifecycle.query.filter_by(idempotency_key=idem_key).first()
    )
    if existing_claim and existing_claim.id != lifecycle.id:
        return {"ok": False, "skipped": "idempotency_taken"}

    lifecycle.idempotency_key = idem_key
    db.session.flush()

    prev_paid = max(0, int(invoice.paid_amount or 0))
    invoice.paid_amount = prev_paid + amount
    invoice.payment_status = "مسدد"
    append_payment_ledger_delta(
        invoice.id,
        amount,
        source_module="order_installment_lifecycle",
        payment_method="automatic_installment_settlement",
        note=f"تسديد تلقائي لدورة الأقساط #{lifecycle.id}",
    )

    old = lifecycle.status
    lifecycle.status = STATUS_AUTO_SETTLED
    lifecycle.auto_settled_at = _now()
    lifecycle.settled_amount = int(lifecycle.settled_amount or 0) + amount
    lifecycle.updated_at = _now()
    try:
        from models.invoice_payment_ledger import InvoicePaymentLedger

        last_ledger = (
            InvoicePaymentLedger.query.filter_by(invoice_id=invoice.id)
            .order_by(InvoicePaymentLedger.id.desc())
            .first()
        )
        if last_ledger:
            lifecycle.settlement_transaction_id = last_ledger.id
    except Exception:
        pass

    log_event(
        lifecycle,
        "auto_settled",
        old_status=old,
        new_status=STATUS_AUTO_SETTLED,
        metadata={"amount": amount},
    )
    _log_activity_safe(
        "installment_auto_settled",
        f"تسديد تلقائي لطلب أقساط #{invoice.id} بمبلغ {amount}",
        entity_id=invoice.id,
        payload={"lifecycle_id": lifecycle.id, "amount": amount},
    )
    return {"ok": True, "amount": amount, "order_id": invoice.id}


def process_due_lifecycles(*, limit: int = 100) -> dict[str, Any]:
    ensure_order_installment_tables()
    settings = get_settings()
    if not settings.enabled or not settings.auto_settle_enabled:
        return {"processed": 0, "settled": 0, "skipped": 0}

    now = _now()
    due_rows = (
        OrderInstallmentLifecycle.query.filter(
            OrderInstallmentLifecycle.status.in_(list(SETTLEABLE_STATUSES)),
            OrderInstallmentLifecycle.due_at <= now,
        )
        .order_by(OrderInstallmentLifecycle.due_at.asc())
        .limit(max(1, min(int(limit or 100), 500)))
        .all()
    )
    settled = 0
    skipped = 0
    for row in due_rows:
        try:
            result = auto_settle_due(row.id)
            db.session.commit()
            if result.get("ok"):
                settled += 1
            else:
                skipped += 1
        except Exception:
            db.session.rollback()
            skipped += 1
    return {"processed": len(due_rows), "settled": settled, "skipped": skipped}


def dashboard_summary() -> dict[str, Any]:
    ensure_order_installment_tables()
    if not feature_enabled():
        return {"active": 0, "due_today": 0, "outstanding_value": 0, "returned_value": 0}

    from models.invoice import Invoice

    now = _now()
    today_end = datetime(now.year, now.month, now.day) + timedelta(days=1)
    today_start = datetime(now.year, now.month, now.day)

    active_rows = OrderInstallmentLifecycle.query.filter(
        OrderInstallmentLifecycle.status.in_(list(SETTLEABLE_STATUSES))
    ).all()
    active = len(active_rows)
    due_today = sum(
        1
        for row in active_rows
        if row.due_at and today_start <= row.due_at < today_end
    )

    outstanding = 0
    for row in active_rows:
        invoice = db.session.get(Invoice, row.order_id)
        if not invoice:
            continue
        outstanding += settlement_amount(row, invoice)

    returned_value = (
        db.session.query(func.coalesce(func.sum(OrderInstallmentLifecycle.returned_amount), 0))
        .filter(OrderInstallmentLifecycle.status.in_([STATUS_RETURNED, STATUS_PARTIALLY_RETURNED]))
        .scalar()
    )
    return {
        "active": active,
        "due_today": due_today,
        "outstanding_value": int(outstanding or 0),
        "returned_value": int(returned_value or 0),
    }


def countdown_label(lifecycle: OrderInstallmentLifecycle) -> str:
    if lifecycle.status == STATUS_AUTO_SETTLED:
        return "تم التسديد تلقائياً"
    if lifecycle.status == STATUS_MANUALLY_SETTLED:
        return "تم التسديد يدوياً"
    if lifecycle.status == STATUS_RETURNED:
        return "مرتجع"
    if lifecycle.status == STATUS_CANCELLED:
        return "ملغي"
    if lifecycle.status == STATUS_PARTIALLY_RETURNED:
        prefix = "مرتجع جزئياً — "
    else:
        prefix = ""
    if not lifecycle.due_at:
        return prefix + "—"
    now = _now()
    delta = lifecycle.due_at - now
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        return prefix + "مستحق الآن"
    hours = seconds // 3600
    if hours < 24:
        return prefix + f"متبقي {max(1, hours)} ساعة"
    days = hours // 24
    if days == 0:
        return prefix + "يستحق اليوم"
    return prefix + f"متبقي {days} أيام"


def ui_context_for_employee(employee) -> dict:
    settings = settings_dict()
    enabled = bool(settings.get("enabled"))
    can_toggle = enabled and can_toggle_mode(employee)
    mode_on = bool(can_toggle and is_installment_mode_on())
    if not enabled or not can_toggle:
        mode_on = False
        if is_installment_mode_on():
            clear_installment_mode()
    return {
        "feature_enabled": enabled,
        "can_toggle": can_toggle,
        "can_view": enabled and can_view(employee),
        "can_create": enabled and can_create(employee),
        "can_settings": can_manage_settings(employee),
        "mode_on": mode_on,
        "settings": settings,
    }


def grant_basic_permissions_to_role(role) -> list[str]:
    """Attach basic installment lifecycle permissions to a role."""
    from models.role import Permission
    from routes.permissions import ensure_default_permissions

    ensure_default_permissions()
    granted = []
    for name in BASIC_PERMISSIONS:
        perm = Permission.query.filter_by(name=name).first()
        if perm and perm not in role.permissions:
            role.permissions.append(perm)
            granted.append(name)
    return granted
