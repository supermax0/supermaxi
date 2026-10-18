"""Call notes endpoints."""

from __future__ import annotations

from flask import g, request

from extensions import db
from modules.phone_app.api.v1.routes import phone_api_v1_bp, require_phone_auth
from modules.phone_app.models import PhoneCallLog, PhoneCallNote
from modules.phone_app.schemas import api_error, api_ok, require_json_fields


@phone_api_v1_bp.post("/notes")
@require_phone_auth
def notes_create():
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "body", "client_id")
    if missing:
        return api_error(missing, 400, code="validation_error")

    client_id = str(body.get("client_id") or "").strip()
    existing = PhoneCallNote.query.filter_by(client_id=client_id).first()
    if existing:
        return api_ok(
            {
                "created": False,
                "duplicate": True,
                "note": {
                    "id": existing.id,
                    "client_id": existing.client_id,
                    "body": existing.body,
                },
            }
        )

    call_id = body.get("call_id")
    call_client_id = body.get("call_client_id")
    if call_id is None and call_client_id:
        call = PhoneCallLog.query.filter_by(client_id=str(call_client_id)).first()
        call_id = call.id if call else None

    note = PhoneCallNote(
        call_id=int(call_id) if call_id else None,
        employee_id=g.phone_employee.id,
        customer_id=int(body["customer_id"]) if body.get("customer_id") else None,
        body=str(body.get("body") or "").strip(),
        client_id=client_id,
    )
    db.session.add(note)
    db.session.commit()
    return api_ok(
        {
            "created": True,
            "note": {
                "id": note.id,
                "client_id": note.client_id,
                "body": note.body,
                "call_id": note.call_id,
                "customer_id": note.customer_id,
            },
        },
        status=201,
    )
