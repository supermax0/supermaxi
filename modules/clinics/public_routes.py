"""Public online booking routes — no login required."""
from __future__ import annotations

from flask import Blueprint, abort, g, jsonify, render_template, request

from extensions import db
from models.core.tenant import Tenant as CoreTenant
from models.tenant import Tenant
from modules.clinics.schema import ensure_clinics_schema
from modules.clinics.service import _parse_date, _today
from modules.clinics.service_booking import (
    _tenant_id,
    available_slots,
    create_online_booking,
    create_public_chat,
    first_available_doctor,
    public_clinic_info,
    public_chat_messages,
    public_cancel,
    public_manage_info,
    public_reschedule,
    send_public_chat_message,
)

clinics_public_bp = Blueprint("clinics_public", __name__, url_prefix="/book")
clinics_public_api_bp = Blueprint("clinics_public_api", __name__, url_prefix="/api/public/clinics")


@clinics_public_bp.before_request
@clinics_public_api_bp.before_request
def _bind_tenant():
    slug = (request.view_args or {}).get("tenant_slug")
    if not slug:
        return
    slug = str(slug).strip().lower()
    # Staff sessions set g.tenant first; CoreTenant lives on the shared DB only.
    previous_tenant = getattr(g, "tenant", None)
    g.tenant = None
    try:
        core = CoreTenant.query.filter(db.func.lower(CoreTenant.slug) == slug).first()
    finally:
        g.tenant = previous_tenant
    if not core or not core.is_active:
        abort(404)
    g.tenant = slug
    ensure_clinics_schema()


def _ok(data=None, **extra):
    payload = {"ok": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return jsonify(payload)


def _error(exc, status=400):
    db.session.rollback()
    return jsonify({"ok": False, "error": str(exc)}), status


@clinics_public_bp.route("/<tenant_slug>")
def booking_page(tenant_slug: str):
    try:
        info = public_clinic_info(_tenant_id())
    except Exception as exc:
        return render_template("clinics/public_booking.html", error=str(exc), clinic=None, tenant_slug=tenant_slug)
    return render_template(
        "clinics/public_booking.html",
        clinic=info,
        tenant_slug=tenant_slug,
        error=None,
    )


@clinics_public_bp.get("/<tenant_slug>/api/info")
@clinics_public_api_bp.get("/<tenant_slug>")
def api_info(tenant_slug: str):
    try:
        return _ok(public_clinic_info(_tenant_id()))
    except Exception as exc:
        return _error(exc, 404 if "غير مفعّل" in str(exc) else 400)


@clinics_public_api_bp.get("/<tenant_slug>/doctors")
def api_public_doctors(tenant_slug: str):
    try:
        doctors = public_clinic_info(_tenant_id())["doctors"]
        specialty_id = int(request.args.get("specialty_id") or 0)
        if specialty_id:
            doctors = [row for row in doctors if specialty_id in (row.get("specialty_ids") or [])]
        return _ok(doctors)
    except Exception as exc:
        return _error(exc, 404)


@clinics_public_api_bp.get("/<tenant_slug>/specialties")
def api_public_specialties(tenant_slug: str):
    try:
        return _ok(public_clinic_info(_tenant_id())["specialties"])
    except Exception as exc:
        return _error(exc, 404)


@clinics_public_api_bp.get("/<tenant_slug>/services")
def api_public_services(tenant_slug: str):
    try:
        from modules.clinics.service import service_matches
        return _ok([row for row in public_clinic_info(_tenant_id())["services"]
                    if service_matches(row, request.args.get("specialty_id"), request.args.get("doctor_id"))])
    except Exception as exc:
        return _error(exc, 404)


@clinics_public_bp.get("/<tenant_slug>/api/slots")
@clinics_public_api_bp.get("/<tenant_slug>/available-slots")
def api_slots(tenant_slug: str):
    try:
        doctor_id = int(request.args.get("doctor_id") or 0)
        service_id = int(request.args["service_id"]) if request.args.get("service_id") else None
        day = _parse_date(request.args.get("date") or _today().isoformat(), "التاريخ")
        specialty_id = int(request.args["specialty_id"]) if request.args.get("specialty_id") else None
        exclude_id = int(request.args["exclude_appointment_id"]) if request.args.get("exclude_appointment_id") else None
        return _ok(
            available_slots(
                _tenant_id(),
                doctor_id,
                day,
                service_id,
                exclude_appointment_id=exclude_id,
                specialty_id=specialty_id,
            )
        )
    except Exception as exc:
        return _error(exc)


@clinics_public_bp.post("/<tenant_slug>/api/book")
@clinics_public_api_bp.post("/<tenant_slug>/bookings")
def api_book(tenant_slug: str):
    try:
        result = create_online_booking(_tenant_id(), request.get_json(silent=True) or {})
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        try:
            from modules.clinics.service_booking import _log_booking_attempt

            _log_booking_attempt(_tenant_id(), (request.get_json(silent=True) or {}).get("phone", ""), False)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return _error(exc)


@clinics_public_bp.post("/<tenant_slug>/api/otp")
def api_otp(tenant_slug: str):
    try:
        from modules.clinics.service_extras import request_booking_otp

        payload = request.get_json(silent=True) or {}
        result = request_booking_otp(_tenant_id(), payload.get("phone") or "")
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@clinics_public_bp.get("/<tenant_slug>/api/first-available")
@clinics_public_api_bp.get("/<tenant_slug>/first-available")
def api_first_available(tenant_slug: str):
    try:
        service_id = int(request.args["service_id"]) if request.args.get("service_id") else None
        day = _parse_date(request.args.get("date") or _today().isoformat(), "التاريخ")
        return _ok(first_available_doctor(_tenant_id(), service_id, day, request.args.get("specialty_id", type=int)))
    except Exception as exc:
        return _error(exc)


@clinics_public_bp.post("/<tenant_slug>/api/chat")
@clinics_public_api_bp.post("/<tenant_slug>/conversations")
def api_public_chat(tenant_slug: str):
    payload = request.get_json(silent=True) or {}
    try:
        result = create_public_chat(_tenant_id(), payload)
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        try:
            from modules.clinics.service_booking import _log_booking_attempt
            _log_booking_attempt(_tenant_id(), payload.get("phone") or "", False)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return _error(exc)


@clinics_public_bp.get("/<tenant_slug>/api/chat/<token>/messages")
@clinics_public_api_bp.get("/<tenant_slug>/conversations/<token>/messages")
def api_public_chat_messages(tenant_slug: str, token: str):
    try:
        return _ok(public_chat_messages(_tenant_id(), token))
    except Exception as exc:
        return _error(exc, 404)


@clinics_public_bp.post("/<tenant_slug>/api/chat/<token>/messages")
@clinics_public_api_bp.post("/<tenant_slug>/conversations/<token>/messages")
def api_public_chat_send(tenant_slug: str, token: str):
    try:
        result = send_public_chat_message(_tenant_id(), token, request.get_json(silent=True) or {})
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@clinics_public_bp.get("/<tenant_slug>/manage/<token>")
def manage_page(tenant_slug: str, token: str):
    try:
        appointment = public_manage_info(_tenant_id(), token)
        clinic = public_clinic_info(_tenant_id())
        return render_template("clinics/public_manage.html", clinic=clinic, appointment=appointment, tenant_slug=tenant_slug, token=token, error=None)
    except Exception as exc:
        return render_template("clinics/public_manage.html", clinic=None, appointment=None, tenant_slug=tenant_slug, token=token, error=str(exc)), 404


@clinics_public_bp.get("/<tenant_slug>/api/manage/<token>")
def api_manage(tenant_slug: str, token: str):
    try:
        return _ok(public_manage_info(_tenant_id(), token))
    except Exception as exc:
        return _error(exc, 404)


@clinics_public_bp.post("/<tenant_slug>/api/manage/<token>/reschedule")
def api_manage_reschedule(tenant_slug: str, token: str):
    try:
        result = public_reschedule(_tenant_id(), token, request.get_json(silent=True) or {})
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)


@clinics_public_bp.post("/<tenant_slug>/api/manage/<token>/cancel")
def api_manage_cancel(tenant_slug: str, token: str):
    try:
        payload = request.get_json(silent=True) or {}
        result = public_cancel(_tenant_id(), token, payload.get("reason") or "")
        db.session.commit()
        return _ok(result)
    except Exception as exc:
        return _error(exc)
