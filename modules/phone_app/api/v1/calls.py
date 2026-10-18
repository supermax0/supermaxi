"""Call CDR sync endpoints with call_status / sync_status separation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import g, request
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.phone_app.api.v1.routes import phone_api_v1_bp, require_phone_auth
from modules.phone_app.models import PhoneAuditLog, PhoneCallLog, PhoneFollowupTask
from modules.phone_app.schemas import api_error, api_ok
from modules.phone_app.services.rate_limit import enforce_rate_limit
from utils.digits import digits_only

ALLOWED_CALL_STATUS = {
    "detected",
    "ringing",
    "dialing",
    "answered",
    "ended",
    "missed",
    "rejected",
    "failed",
    "cancelled",
}
# Legacy clients may still send "synced" as a call status — map to ended + sync.
ALLOWED_SYNC_STATUS = {"pending", "syncing", "synced", "failed", "permanently_failed"}
ALLOWED_DIRECTION = {"inbound", "outbound"}

# Soft alias for older tests/imports
ALLOWED_STATUS = ALLOWED_CALL_STATUS | {"synced"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_dt(value) -> datetime | None:
    """Parse ISO-8601 (prefer …Z) into naive UTC for storage."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def _iso_z(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _followup_minutes() -> int:
    """Company setting for missed-call follow-up delay (5 / 15 / 30)."""
    try:
        from models.system_settings import SystemSettings

        row = SystemSettings.query.filter_by(key="phone_missed_followup_minutes").first()
        if row and row.value:
            m = int(str(row.value).strip())
            if m in (5, 15, 30, 60):
                return m
    except Exception:
        pass
    return 30


def _serialize_call(row: PhoneCallLog) -> dict:
    call_status = getattr(row, "call_status", None) or "detected"
    sync_status = getattr(row, "sync_status", None) or "pending"
    return {
        "id": row.id,
        "client_id": row.client_id,
        "local_call_uuid": getattr(row, "local_call_uuid", None),
        "idempotency_key": row.idempotency_key,
        "phone": row.phone_e164,
        "phone_normalized": getattr(row, "phone_normalized", None),
        "direction": row.direction,
        "call_status": call_status,
        "sync_status": sync_status,
        # Back-compat: status mirrors call_status (never "synced" alone)
        "status": call_status,
        "customer_id": row.customer_id,
        "started_at": _iso_z(row.started_at),
        "ended_at": _iso_z(row.ended_at),
        "detected_at": _iso_z(row.detected_at),
        "ringing_at": _iso_z(row.ringing_at),
        "dialing_at": _iso_z(getattr(row, "dialing_at", None)),
        "answered_at": _iso_z(row.answered_at),
        "cancelled_at": _iso_z(getattr(row, "cancelled_at", None)),
        "failed_at": _iso_z(getattr(row, "failed_at", None)),
        "server_received_at": _iso_z(getattr(row, "server_received_at", None)),
        "duration_sec": row.duration_sec,
        "device_id": row.device_id,
        "sim_slot": row.sim_slot,
        "synced_note": row.synced_note,
        "outcome": getattr(row, "outcome", None),
        "outcome_note": getattr(row, "outcome_note", None),
        "follow_up_required": bool(getattr(row, "follow_up_required", False)),
        "follow_up_at": _iso_z(getattr(row, "follow_up_at", None)),
        "outcome_recorded_at": _iso_z(getattr(row, "outcome_recorded_at", None)),
        "outcome_recorded_by": getattr(row, "outcome_recorded_by", None),
        "outcome_client_id": getattr(row, "outcome_client_id", None),
        "has_recording": bool(getattr(row, "recording_path", None)),
        "recording_duration_sec": getattr(row, "recording_duration_sec", None),
        "server_time": _iso_z(_utcnow()),
    }


def _find_existing(
    client_id: str,
    idem: str | None,
    *,
    tenant_id: int | None,
    local_call_uuid: str | None,
) -> PhoneCallLog | None:
    if idem:
        q = PhoneCallLog.query.filter_by(idempotency_key=idem)
        if tenant_id is not None:
            q = q.filter_by(tenant_id=tenant_id)
        hit = q.first()
        if hit:
            return hit
    if local_call_uuid:
        hit = PhoneCallLog.query.filter_by(local_call_uuid=local_call_uuid).first()
        if hit:
            return hit
    return PhoneCallLog.query.filter_by(client_id=client_id).first()


def _resolve_answered_tasks(
    phone_normalized: str, employee_id: int, *, resolved_by_call_id: int | None = None
) -> None:
    """Mark open missed-call tasks resolved when customer answers again."""
    if not phone_normalized:
        return
    open_tasks = (
        PhoneFollowupTask.query.filter(
            PhoneFollowupTask.employee_id == employee_id,
            PhoneFollowupTask.status.in_(("open", "in_progress", "overdue")),
        )
        .filter(
            (PhoneFollowupTask.phone_normalized == phone_normalized)
            | (PhoneFollowupTask.phone == phone_normalized)
        )
        .all()
    )
    for task in open_tasks:
        if (task.task_type or task.source or "") in (
            "missed_call_followup",
            "missed_call",
            "callback",
            "callback_required",
        ):
            task.status = "resolved_by_answered_call"
            if resolved_by_call_id and hasattr(task, "resolved_by_call_id"):
                task.resolved_by_call_id = resolved_by_call_id
            task.updated_at = _utcnow()


def _ensure_missed_task(row: PhoneCallLog, employee_id: int, *, tenant_id: int | None) -> None:
    from modules.phone_app.services.feature_flags import is_feature_enabled
    from modules.phone_app.services.followup import priority_for_customer

    if not is_feature_enabled("phone_smart_followup_enabled"):
        return
    if (getattr(row, "call_status", None) or "") != "missed":
        return
    # Future: skip spam/blocked classifications when available.
    if getattr(row, "synced_note", None) and "spam" in str(row.synced_note).lower():
        return

    task_type = "missed_call_followup"
    # One task per tenant + call + type
    if row.id:
        existing_by_call = PhoneFollowupTask.query.filter_by(
            call_id=row.id, task_type=task_type
        ).first()
        if existing_by_call:
            return

    phone_norm = getattr(row, "phone_normalized", None) or digits_only(row.phone_e164)
    window_start = _utcnow() - timedelta(minutes=15)
    coalesce = (
        PhoneFollowupTask.query.filter_by(
            employee_id=employee_id,
            status="open",
            task_type=task_type,
        )
        .filter(PhoneFollowupTask.created_at >= window_start)
        .filter(
            (PhoneFollowupTask.phone_normalized == phone_norm)
            | (PhoneFollowupTask.phone == row.phone_e164)
        )
        .order_by(PhoneFollowupTask.id.desc())
        .first()
    )
    if coalesce is not None and coalesce.call_id != row.id:
        coalesce.attempt_count = (coalesce.attempt_count or 1) + 1
        coalesce.updated_at = _utcnow()
        customer = None
        if coalesce.customer_id:
            try:
                from models.customer import Customer

                customer = db.session.get(Customer, coalesce.customer_id)
            except Exception:
                pass
        coalesce.priority = priority_for_customer(
            customer, attempt_count=coalesce.attempt_count or 1
        )
        return

    task_client = f"missed-{row.idempotency_key or row.client_id}"
    if PhoneFollowupTask.query.filter_by(client_id=task_client).first():
        return

    minutes = _followup_minutes()
    customer = None
    if row.customer_id:
        try:
            from models.customer import Customer

            customer = db.session.get(Customer, row.customer_id)
        except Exception:
            pass
    priority = priority_for_customer(customer, attempt_count=1)
    db.session.add(
        PhoneFollowupTask(
            tenant_id=tenant_id,
            employee_id=employee_id,
            customer_id=row.customer_id,
            phone=row.phone_e164,
            phone_normalized=phone_norm,
            call_id=row.id,
            title="متابعة مكالمة فائتة",
            due_at=_utcnow() + timedelta(minutes=minutes),
            status="open",
            source="missed_call",
            task_type=task_type,
            attempt_count=1,
            priority=priority,
            reason="missed_call",
            client_id=task_client,
        )
    )


def _normalize_call_status(raw: str | None, sync_hint: str | None) -> tuple[str, str]:
    status = str(raw or "detected").strip().lower()
    sync = str(sync_hint or "pending").strip().lower()
    if status == "synced":
        # Legacy: synced was a call state — split it.
        return "ended", "synced"
    if status not in ALLOWED_CALL_STATUS:
        status = "detected"
    if sync not in ALLOWED_SYNC_STATUS:
        sync = "pending"
    return status, sync


def _upsert_call(payload: dict, employee_id: int) -> tuple[PhoneCallLog, bool, bool]:
    """Returns (row, created, duplicate). Duplicate is soft-success."""
    client_id = str(
        payload.get("client_id")
        or payload.get("idempotency_key")
        or request.headers.get("Idempotency-Key")
        or ""
    ).strip()
    local_call_uuid = str(payload.get("local_call_uuid") or "").strip() or None
    idem = str(
        payload.get("idempotency_key")
        or request.headers.get("Idempotency-Key")
        or (f"{payload.get('device_id')}:{local_call_uuid}" if local_call_uuid and payload.get("device_id") else "")
        or client_id
    ).strip() or None
    if not client_id:
        raise ValueError("client_id required")

    tenant_id = None
    try:
        tenant_id = int(getattr(g, "tenant_id", None) or 0) or None
    except (TypeError, ValueError):
        tenant_id = None

    existing = _find_existing(
        client_id, idem, tenant_id=tenant_id, local_call_uuid=local_call_uuid
    )
    phone = digits_only(payload.get("phone") or payload.get("phone_e164") or "")
    phone_norm = digits_only(payload.get("phone_normalized") or phone)
    started = _parse_dt(payload.get("started_at")) or _utcnow()
    ended = _parse_dt(payload.get("ended_at"))
    call_status, sync_status = _normalize_call_status(
        payload.get("call_status") or payload.get("status"),
        payload.get("sync_status"),
    )
    # Client upload that reached the server is at least syncing→synced on accept
    if sync_status == "pending":
        sync_status = "synced"

    direction = str(payload.get("direction") or "inbound").strip().lower()
    if direction not in ALLOWED_DIRECTION:
        direction = "inbound"
    duration = payload.get("duration_sec")
    customer_id = payload.get("customer_id")
    device_id = payload.get("device_id")
    note = payload.get("synced_note")
    sim_slot = payload.get("sim_slot")
    detected_at = _parse_dt(payload.get("detected_at"))
    ringing_at = _parse_dt(payload.get("ringing_at"))
    dialing_at = _parse_dt(payload.get("dialing_at"))
    answered_at = _parse_dt(payload.get("answered_at"))
    cancelled_at = _parse_dt(payload.get("cancelled_at"))
    failed_at = _parse_dt(payload.get("failed_at"))
    received_at = _utcnow()

    if existing:
        existing.call_status = call_status
        existing.sync_status = sync_status
        existing.server_received_at = received_at
        if ended:
            existing.ended_at = ended
        if duration is not None:
            try:
                existing.duration_sec = max(0, int(duration))
            except (TypeError, ValueError):
                pass
        if customer_id:
            existing.customer_id = int(customer_id)
        if note:
            existing.synced_note = str(note)[:4000]
        if device_id:
            existing.device_id = str(device_id)[:128]
        if sim_slot is not None:
            try:
                existing.sim_slot = int(sim_slot)
            except (TypeError, ValueError):
                pass
        if detected_at:
            existing.detected_at = detected_at
        if ringing_at:
            existing.ringing_at = ringing_at
        if dialing_at:
            existing.dialing_at = dialing_at
        if answered_at:
            existing.answered_at = answered_at
        if cancelled_at:
            existing.cancelled_at = cancelled_at
        if failed_at:
            existing.failed_at = failed_at
        if not existing.idempotency_key and idem:
            existing.idempotency_key = idem
        if not existing.local_call_uuid and local_call_uuid:
            existing.local_call_uuid = local_call_uuid
        if phone_norm:
            existing.phone_normalized = phone_norm
        if call_status == "answered":
            _resolve_answered_tasks(
                phone_norm or existing.phone_normalized or "",
                employee_id,
                resolved_by_call_id=existing.id,
            )
        _ensure_missed_task(existing, employee_id, tenant_id=tenant_id)
        return existing, False, True

    row = PhoneCallLog(
        tenant_id=tenant_id,
        employee_id=employee_id,
        customer_id=int(customer_id) if customer_id else None,
        phone_e164=phone or "unknown",
        phone_normalized=phone_norm or phone or None,
        direction=direction,
        call_status=call_status,
        sync_status=sync_status,
        started_at=started,
        ended_at=ended,
        duration_sec=int(duration) if duration is not None else None,
        detected_at=detected_at,
        ringing_at=ringing_at,
        dialing_at=dialing_at,
        answered_at=answered_at,
        cancelled_at=cancelled_at,
        failed_at=failed_at,
        server_received_at=received_at,
        client_id=client_id[:128],
        local_call_uuid=(local_call_uuid[:64] if local_call_uuid else None),
        idempotency_key=(idem[:191] if idem else None),
        device_id=str(device_id)[:128] if device_id else None,
        sim_slot=int(sim_slot) if sim_slot is not None else None,
        synced_note=str(note)[:4000] if note else None,
    )
    db.session.add(row)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        again = _find_existing(
            client_id, idem, tenant_id=tenant_id, local_call_uuid=local_call_uuid
        )
        if again:
            return again, False, True
        raise
    if call_status == "answered":
        _resolve_answered_tasks(
            phone_norm or "", employee_id, resolved_by_call_id=row.id
        )
    _ensure_missed_task(row, employee_id, tenant_id=tenant_id)
    return row, True, False


@phone_api_v1_bp.post("/calls")
@require_phone_auth
def calls_upsert():
    limited = enforce_rate_limit("calls_upsert", limit=120, window_seconds=60)
    if limited is not None:
        return limited
    body = request.get_json(silent=True) or {}
    if (
        not body.get("client_id")
        and not body.get("idempotency_key")
        and not request.headers.get("Idempotency-Key")
    ):
        return api_error(
            "client_id or Idempotency-Key required", 400, code="validation_error"
        )
    if not body.get("phone") and not body.get("phone_e164"):
        return api_error("phone required", 400, code="validation_error")
    try:
        row, created, duplicate = _upsert_call(body, g.phone_employee.id)
        db.session.add(
            PhoneAuditLog(
                employee_id=g.phone_employee.id,
                device_id=body.get("device_id"),
                action="call_upsert",
                detail=f"created={created};dup={duplicate}",
            )
        )
        db.session.commit()
    except ValueError as exc:
        return api_error(str(exc), 400, code="validation_error")
    except IntegrityError:
        db.session.rollback()
        row = _find_existing(
            str(body.get("client_id") or ""),
            str(body.get("idempotency_key") or "") or None,
            tenant_id=None,
            local_call_uuid=str(body.get("local_call_uuid") or "") or None,
        )
        if row:
            return api_ok(
                {"created": False, "duplicate": True, "call": _serialize_call(row)}
            )
        return api_error("Conflict", 409, code="conflict")
    return api_ok(
        {"created": created, "duplicate": duplicate, "call": _serialize_call(row)},
        status=201 if created else 200,
    )


@phone_api_v1_bp.post("/calls/batch")
@require_phone_auth
def calls_batch():
    limited = enforce_rate_limit("calls_batch", limit=30, window_seconds=60)
    if limited is not None:
        return limited
    body = request.get_json(silent=True) or {}
    items = body.get("calls") or body.get("items") or []
    if not isinstance(items, list):
        return api_error("calls must be a list", 400, code="validation_error")
    if len(items) > 100:
        return api_error("Max 100 calls per batch", 400, code="validation_error")
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            row, created, duplicate = _upsert_call(item, g.phone_employee.id)
            results.append(
                {
                    "created": created,
                    "duplicate": duplicate,
                    "call": _serialize_call(row),
                    "ok": True,
                }
            )
        except Exception as exc:
            results.append(
                {"ok": False, "error": str(exc), "client_id": item.get("client_id")}
            )
    db.session.commit()
    return api_ok({"results": results, "server_time": _iso_z(_utcnow())})


@phone_api_v1_bp.get("/calls")
@require_phone_auth
def calls_list():
    since = _parse_dt(request.args.get("since"))
    try:
        limit = min(max(int(request.args.get("limit") or 50), 1), 200)
        offset = max(int(request.args.get("offset") or 0), 0)
    except ValueError:
        return api_error("Invalid pagination", 400, code="validation_error")
    q = PhoneCallLog.query.filter_by(employee_id=g.phone_employee.id)
    if since:
        q = q.filter(PhoneCallLog.updated_at >= since)
    total = q.count()
    rows = q.order_by(PhoneCallLog.started_at.desc()).offset(offset).limit(limit).all()
    return api_ok(
        {
            "calls": [_serialize_call(r) for r in rows],
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total": total,
                "next_offset": offset + limit if offset + limit < total else None,
            },
            "server_time": _iso_z(_utcnow()),
        }
    )


def _has_linked_order(row: PhoneCallLog) -> bool:
    if not row.customer_id:
        return False
    try:
        from modules.phone_app.models import PhoneOrderDraft

        if PhoneOrderDraft.query.filter_by(
            customer_id=row.customer_id, status="confirmed"
        ).first():
            return True
    except Exception:
        pass
    try:
        from models.invoice import Invoice

        if Invoice.query.filter_by(customer_id=row.customer_id).first():
            return True
    except Exception:
        pass
    return False


def _apply_outcome_side_effects(row: PhoneCallLog, outcome: str, employee_id: int) -> None:
    from modules.phone_app.services.call_outcomes import should_create_followup
    from modules.phone_app.services.feature_flags import is_feature_enabled
    from modules.phone_app.services.followup import priority_for_customer

    if not should_create_followup(outcome):
        return
    if not is_feature_enabled("phone_smart_followup_enabled"):
        return
    task_type = "complaint_followup" if outcome == "complaint" else "callback"
    client_id = f"outcome-{row.outcome_client_id or row.client_id}-{task_type}"
    if PhoneFollowupTask.query.filter_by(client_id=client_id).first():
        return
    existing_open = (
        PhoneFollowupTask.query.filter_by(
            employee_id=employee_id,
            status="open",
            task_type=task_type,
            customer_id=row.customer_id,
        ).first()
        if row.customer_id
        else None
    )
    if existing_open is None:
        phone_norm = getattr(row, "phone_normalized", None) or digits_only(row.phone_e164)
        existing_open = (
            PhoneFollowupTask.query.filter_by(
                employee_id=employee_id, status="open", task_type=task_type
            )
            .filter(
                (PhoneFollowupTask.phone_normalized == phone_norm)
                | (PhoneFollowupTask.phone == row.phone_e164)
            )
            .first()
        )
    if existing_open:
        existing_open.attempt_count = (existing_open.attempt_count or 1) + 1
        existing_open.due_at = row.follow_up_at or existing_open.due_at
        existing_open.updated_at = _utcnow()
        return

    customer = None
    if row.customer_id:
        try:
            from models.customer import Customer

            customer = db.session.get(Customer, row.customer_id)
        except Exception:
            pass
    title = "متابعة شكوى" if outcome == "complaint" else "إعادة اتصال"
    db.session.add(
        PhoneFollowupTask(
            tenant_id=row.tenant_id,
            employee_id=employee_id,
            customer_id=row.customer_id,
            phone=row.phone_e164,
            phone_normalized=getattr(row, "phone_normalized", None),
            call_id=row.id,
            title=title,
            due_at=row.follow_up_at or (_utcnow() + timedelta(minutes=_followup_minutes())),
            status="open",
            source="call_outcome",
            task_type=task_type,
            attempt_count=1,
            priority=priority_for_customer(
                customer,
                attempt_count=1,
                is_complaint=(outcome == "complaint"),
            ),
            reason=outcome,
            client_id=client_id,
        )
    )


@phone_api_v1_bp.get("/calls/outcomes/catalog")
@require_phone_auth
def calls_outcomes_catalog():
    from modules.phone_app.services.call_outcomes import outcome_catalog
    from modules.phone_app.services.feature_flags import require_feature

    blocked = require_feature("phone_call_outcomes_enabled")
    if blocked is not None:
        return blocked
    return api_ok(outcome_catalog())


@phone_api_v1_bp.get("/calls/unclassified")
@require_phone_auth
def calls_unclassified():
    from modules.phone_app.services.feature_flags import require_feature

    blocked = require_feature("phone_call_outcomes_enabled")
    if blocked is not None:
        return blocked
    try:
        limit = min(max(int(request.args.get("limit") or 50), 1), 200)
    except ValueError:
        limit = 50
    rows = (
        PhoneCallLog.query.filter_by(employee_id=g.phone_employee.id)
        .filter(PhoneCallLog.call_status.in_(("answered", "ended")))
        .filter(
            (PhoneCallLog.outcome.is_(None)) | (PhoneCallLog.outcome == "")
        )
        .order_by(PhoneCallLog.started_at.desc())
        .limit(limit)
        .all()
    )
    return api_ok({"calls": [_serialize_call(r) for r in rows]})


@phone_api_v1_bp.post("/calls/<int:call_id>/outcome")
@require_phone_auth
def calls_set_outcome(call_id: int):
    from modules.phone_app.services.call_outcomes import (
        resolve_follow_up_at,
        validate_outcome,
    )
    from modules.phone_app.services.feature_flags import require_feature
    from modules.phone_app.services.permissions import require_phone_perm

    blocked = require_feature("phone_call_outcomes_enabled")
    if blocked is not None:
        return blocked
    perm = require_phone_perm(g.phone_employee, "phone.outcomes.create")
    if perm is not None:
        return perm

    row = db.session.get(PhoneCallLog, call_id)
    if not row or row.employee_id != g.phone_employee.id:
        return api_error("Call not found", 404, code="not_found")

    body = request.get_json(silent=True) or {}
    outcome = str(body.get("outcome") or "").strip().lower()
    outcome_client_id = str(body.get("outcome_client_id") or "").strip() or None

    # Idempotent retry
    if outcome_client_id:
        prior = PhoneCallLog.query.filter_by(outcome_client_id=outcome_client_id).first()
        if prior and prior.id == row.id:
            return api_ok({"created": False, "duplicate": True, "call": _serialize_call(row)})
        if prior:
            return api_ok(
                {"created": False, "duplicate": True, "call": _serialize_call(prior)}
            )

    follow_up_at = resolve_follow_up_at(outcome, _parse_dt(body.get("follow_up_at")))
    err = validate_outcome(
        outcome=outcome,
        call_status=getattr(row, "call_status", None),
        follow_up_at=follow_up_at,
        has_linked_order=_has_linked_order(row)
        or bool(body.get("has_linked_order")),
    )
    if err:
        return api_error(err, 400, code=err)

    is_update = bool(row.outcome)
    if is_update:
        upd = require_phone_perm(g.phone_employee, "phone.outcomes.update")
        if upd is not None:
            return upd
        # Conflict: keep newer recorded_at
        incoming_at = _parse_dt(body.get("outcome_recorded_at")) or _utcnow()
        if row.outcome_recorded_at and incoming_at < row.outcome_recorded_at:
            return api_ok(
                {"created": False, "stale": True, "call": _serialize_call(row)}
            )

    old = row.outcome
    row.outcome = outcome
    row.outcome_note = str(body.get("outcome_note") or "")[:4000] or None
    row.follow_up_required = bool(
        body.get("follow_up_required")
        if "follow_up_required" in body
        else outcome in ("callback_required", "complaint")
    )
    row.follow_up_at = follow_up_at
    row.outcome_recorded_at = _parse_dt(body.get("outcome_recorded_at")) or _utcnow()
    row.outcome_recorded_by = g.phone_employee.id
    if outcome_client_id:
        row.outcome_client_id = outcome_client_id[:64]

    db.session.add(
        PhoneAuditLog(
            employee_id=g.phone_employee.id,
            device_id=getattr(g, "phone_device", None)
            and getattr(g.phone_device, "device_uuid", None),
            action="call_outcome_update" if is_update else "call_outcome_create",
            detail=f"call={row.id};old={old};new={outcome}",
        )
    )
    _apply_outcome_side_effects(row, outcome, g.phone_employee.id)
    db.session.commit()
    return api_ok(
        {"created": not is_update, "duplicate": False, "call": _serialize_call(row)},
        status=200 if is_update else 201,
    )
