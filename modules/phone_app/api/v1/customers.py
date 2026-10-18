"""Customer CRM endpoints for Finora Phone."""

from __future__ import annotations

from flask import g, request

from extensions import db
from models.customer import Customer
from models.invoice import Invoice
from modules.phone_app.api.v1.routes import phone_api_v1_bp, require_phone_auth
from modules.phone_app.models import PhoneAuditLog, PhoneCallLog, PhoneCallNote
from modules.phone_app.schemas import api_error, api_ok, require_json_fields
from utils.digits import digits_only


def _normalize_phone(raw: str | None) -> str:
    return digits_only(raw or "")


def _phone_variants(phone: str) -> list[str]:
    p = _normalize_phone(phone)
    variants = {p}
    if len(p) >= 10:
        variants.add(p[-10:])
        variants.add(p[-11:] if len(p) >= 11 else p)
    if p.startswith("964") and len(p) > 3:
        variants.add("0" + p[3:])
    if p.startswith("0") and len(p) == 11:
        variants.add("964" + p[1:])
    return [v for v in variants if v]


def _find_customer_by_phone(phone: str) -> Customer | None:
    variants = _phone_variants(phone)
    if not variants:
        return None
    q = Customer.query.filter(
        db.or_(
            Customer.phone.in_(variants),
            Customer.phone2.in_(variants),
        )
    )
    # Also match suffix contains for stored formats
    for v in variants:
        if len(v) >= 10:
            hit = Customer.query.filter(
                db.or_(
                    Customer.phone.endswith(v[-10:]),
                    Customer.phone2.endswith(v[-10:]),
                )
            ).first()
            if hit:
                return hit
    return q.first()


def _customer_card(c: Customer) -> dict:
    invoices = (
        Invoice.query.filter_by(customer_id=c.id)
        .order_by(Invoice.id.desc())
        .limit(20)
        .all()
    )
    total_purchases = 0.0
    open_orders = 0
    last_order = None
    delivery_status = None
    for inv in invoices:
        try:
            total_purchases += float(getattr(inv, "total", 0) or 0)
        except (TypeError, ValueError):
            pass
        status = (getattr(inv, "status", None) or "").strip()
        if status and status not in ("delivered", "cancelled", "returned", "راجعة", "واصلة"):
            open_orders += 1
        if last_order is None:
            last_order = {
                "id": inv.id,
                "total": getattr(inv, "total", None),
                "status": status,
                "created_at": (
                    inv.created_at.isoformat() if getattr(inv, "created_at", None) else None
                ),
            }
            delivery_status = status

    last_note_row = (
        PhoneCallNote.query.filter_by(customer_id=c.id)
        .order_by(PhoneCallNote.id.desc())
        .first()
    )
    balance = None
    try:
        balance = float(getattr(c, "balance", None) or 0)
    except Exception:
        balance = None

    vip = False
    try:
        vip = bool(getattr(c, "vip", False)) or total_purchases >= 1000000 or open_orders >= 3
    except Exception:
        vip = False

    return {
        "id": c.id,
        "name": c.name,
        "phone": c.phone,
        "phone2": c.phone2 or "",
        "city": c.city or "",
        "address": c.address or "",
        "notes": c.notes or "",
        "photo_url": None,
        "level": None,
        "vip": vip,
        "balance": balance,
        "total_purchases": total_purchases,
        "last_order": last_order,
        "open_orders_count": open_orders,
        "delivery_status": delivery_status,
        "last_note": last_note_row.body if last_note_row else (c.notes or None),
        "rating": None,
        "blacklisted": bool(getattr(c, "is_blacklisted", False)),
        "blacklist_reason": getattr(c, "blacklist_reason", None),
    }


@phone_api_v1_bp.get("/customers/by-phone")
@require_phone_auth
def customers_by_phone():
    phone = _normalize_phone(request.args.get("phone"))
    if not phone:
        return api_error("phone required", 400, code="validation_error")
    customer = _find_customer_by_phone(phone)
    if not customer:
        return api_ok({"found": False, "phone": phone, "customer": None})
    return api_ok({"found": True, "phone": phone, "customer": _customer_card(customer)})


@phone_api_v1_bp.get("/customers/search")
@require_phone_auth
def customers_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return api_ok({"customers": []})
    limit = min(int(request.args.get("limit") or 30), 50)
    phone_q = _normalize_phone(q)
    filters = [Customer.name.ilike(f"%{q}%")]
    if len(phone_q) >= 3:
        filters.append(Customer.phone.contains(phone_q))
        filters.append(Customer.phone2.contains(phone_q))
    if "@" not in q and len(q) >= 2:
        filters.append(Customer.city.ilike(f"%{q}%"))
    rows = (
        Customer.query.filter(db.or_(*filters))
        .order_by(Customer.id.desc())
        .limit(limit)
        .all()
    )
    return api_ok({"customers": [_customer_card(c) for c in rows]})


@phone_api_v1_bp.get("/customers/<int:customer_id>")
@require_phone_auth
def customer_get(customer_id: int):
    customer = db.session.get(Customer, customer_id)
    if not customer:
        return api_error("Customer not found", 404, code="not_found")
    return api_ok({"customer": _customer_card(customer)})


@phone_api_v1_bp.get("/customers/<int:customer_id>/timeline")
@require_phone_auth
def customer_timeline(customer_id: int):
    from modules.phone_app.services.feature_flags import require_feature
    from modules.phone_app.services.permissions import (
        employee_has_phone_perm,
        require_phone_perm,
    )
    from modules.phone_app.services.timeline import (
        collect_timeline_events,
        paginate_timeline,
    )

    blocked = require_feature("phone_timeline_enabled")
    if blocked is not None:
        return blocked
    perm = require_phone_perm(g.phone_employee, "phone.timeline.view")
    if perm is not None:
        return perm

    customer = db.session.get(Customer, customer_id)
    if not customer:
        return api_error("Customer not found", 404, code="not_found")

    try:
        limit = min(max(int(request.args.get("limit") or 30), 1), 100)
    except ValueError:
        limit = 30
    cursor = request.args.get("cursor")

    events = collect_timeline_events(
        customer_id,
        employee=g.phone_employee,
        include_financial=employee_has_phone_perm(
            g.phone_employee, "phone.financial.view"
        ),
    )
    page = paginate_timeline(events, cursor=cursor, limit=limit)
    # Back-compat keys for older clients (empty if unused)
    page["customer_id"] = customer_id
    return api_ok(page)


@phone_api_v1_bp.post("/customers")
@require_phone_auth
def customers_create():
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "name", "phone")
    if missing:
        return api_error(missing, 400, code="validation_error")

    name = str(body.get("name") or "").strip()
    phone = _normalize_phone(body.get("phone"))
    phone2 = _normalize_phone(body.get("phone2")) or None
    city = (str(body.get("city") or "").strip() or None)
    address = (str(body.get("address") or "").strip() or None)
    notes = (str(body.get("notes") or "").strip() or None)
    client_id = (str(body.get("client_id") or "").strip() or None)

    if not phone or len(phone) < 10:
        return api_error("رقم الهاتف غير صالح", 400, code="invalid_phone")

    existing = _find_customer_by_phone(phone)
    if existing:
        return api_ok(
            {
                "created": False,
                "duplicate": True,
                "customer": _customer_card(existing),
                "client_id": client_id,
            }
        )

    try:
        from utils.customer_blacklist import is_phone_blacklisted_for_new_customer

        if is_phone_blacklisted_for_new_customer(phone, phone2):
            return api_error(
                "رقم الهاتف في القائمة السوداء",
                400,
                code="blacklisted",
            )
    except Exception:
        pass

    customer = Customer(
        name=name,
        phone=phone,
        phone2=phone2,
        city=city,
        address=address,
        notes=notes,
    )
    db.session.add(customer)
    db.session.add(
        PhoneAuditLog(
            employee_id=g.phone_employee.id,
            action="create_customer",
            detail=f"phone={phone}",
        )
    )
    db.session.commit()
    return api_ok(
        {
            "created": True,
            "customer": _customer_card(customer),
            "client_id": client_id,
        },
        status=201,
    )


@phone_api_v1_bp.patch("/customers/<int:customer_id>")
@require_phone_auth
def customers_patch(customer_id: int):
    customer = db.session.get(Customer, customer_id)
    if not customer:
        return api_error("Customer not found", 404, code="not_found")
    body = request.get_json(silent=True) or {}
    for field in ("name", "city", "address", "notes"):
        if field in body and body[field] is not None:
            setattr(customer, field, str(body[field]).strip())
    if "phone2" in body:
        customer.phone2 = _normalize_phone(body.get("phone2")) or None
    db.session.commit()
    return api_ok({"customer": _customer_card(customer)})
