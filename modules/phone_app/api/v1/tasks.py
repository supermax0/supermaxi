"""Follow-up tasks endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import g, request

from extensions import db
from modules.phone_app.api.v1.routes import phone_api_v1_bp, require_phone_auth
from modules.phone_app.models import PhoneFollowupTask
from modules.phone_app.schemas import api_error, api_ok, require_json_fields
from modules.phone_app.services.feature_flags import require_feature
from modules.phone_app.services.followup import can_transition, mark_overdue_tasks
from modules.phone_app.services.permissions import (
    employee_has_phone_perm,
    require_phone_perm,
)
from utils.digits import digits_only


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_dt(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00") if str(value).endswith("Z") else str(value)
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def _serialize(task: PhoneFollowupTask) -> dict:
    return {
        "id": task.id,
        "client_id": task.client_id,
        "title": task.title,
        "phone": task.phone,
        "phone_normalized": getattr(task, "phone_normalized", None),
        "customer_id": task.customer_id,
        "call_id": task.call_id,
        "due_at": task.due_at.isoformat() + "Z" if task.due_at else None,
        "status": task.status,
        "source": task.source,
        "task_type": getattr(task, "task_type", None),
        "attempt_count": getattr(task, "attempt_count", 1),
        "priority": getattr(task, "priority", None) or "normal",
        "reason": getattr(task, "reason", None),
        "resolved_by_call_id": getattr(task, "resolved_by_call_id", None),
        "snoozed_until": (
            task.snoozed_until.isoformat() + "Z"
            if getattr(task, "snoozed_until", None)
            else None
        ),
        "created_at": task.created_at.isoformat() + "Z" if task.created_at else None,
    }


@phone_api_v1_bp.post("/tasks")
@require_phone_auth
def tasks_create():
    body = request.get_json(silent=True) or {}
    missing = require_json_fields(body, "title", "phone", "client_id")
    if missing:
        return api_error(missing, 400, code="validation_error")

    client_id = str(body.get("client_id") or "").strip()
    existing = PhoneFollowupTask.query.filter_by(client_id=client_id).first()
    if existing:
        return api_ok({"created": False, "duplicate": True, "task": _serialize(existing)})

    task = PhoneFollowupTask(
        employee_id=g.phone_employee.id,
        customer_id=int(body["customer_id"]) if body.get("customer_id") else None,
        phone=digits_only(body.get("phone")) or str(body.get("phone")),
        phone_normalized=digits_only(body.get("phone")),
        call_id=int(body["call_id"]) if body.get("call_id") else None,
        title=str(body.get("title") or "").strip(),
        due_at=_parse_dt(body.get("due_at")),
        status=str(body.get("status") or "open"),
        source=str(body.get("source") or "manual"),
        task_type=str(body.get("task_type") or "manual"),
        attempt_count=int(body.get("attempt_count") or 1),
        priority=str(body.get("priority") or "normal"),
        reason=str(body.get("reason") or "") or None,
        client_id=client_id,
    )
    db.session.add(task)
    db.session.commit()
    return api_ok({"created": True, "task": _serialize(task)}, status=201)


@phone_api_v1_bp.patch("/tasks/<int:task_id>")
@require_phone_auth
def tasks_patch(task_id: int):
    task = db.session.get(PhoneFollowupTask, task_id)
    if not task:
        return api_error("Task not found", 404, code="not_found")
    view_team = employee_has_phone_perm(g.phone_employee, "phone.tasks.view_team")
    if task.employee_id != g.phone_employee.id and not view_team:
        return api_error("Task not found", 404, code="not_found")

    body = request.get_json(silent=True) or {}
    if "status" in body:
        new_status = str(body.get("status") or task.status)
        if new_status == "completed":
            perm = require_phone_perm(g.phone_employee, "phone.tasks.complete")
            if perm is not None:
                return perm
        if not can_transition(task.status, new_status):
            return api_error(
                "Invalid status transition",
                409,
                code="invalid_transition",
            )
        task.status = new_status
    if "title" in body:
        task.title = str(body.get("title") or task.title)
    if "due_at" in body:
        task.due_at = _parse_dt(body.get("due_at"))
    if "priority" in body:
        task.priority = str(body.get("priority") or task.priority)
    if "snoozed_until" in body:
        task.snoozed_until = _parse_dt(body.get("snoozed_until"))
        if task.snoozed_until:
            task.due_at = task.snoozed_until
            if task.status == "overdue":
                task.status = "open"
    task.updated_at = _utcnow()
    db.session.commit()
    return api_ok({"task": _serialize(task)})


@phone_api_v1_bp.get("/tasks")
@require_phone_auth
def tasks_list():
    blocked = require_feature("phone_smart_followup_enabled")
    # Soft: still allow list if flag off? Plan says gate APIs — return empty-ish or block.
    if blocked is not None:
        return blocked

    mark_overdue_tasks(g.phone_employee.id)

    status = (request.args.get("status") or "").strip()
    filt = (request.args.get("filter") or "").strip().lower()
    task_type = (request.args.get("task_type") or "").strip()
    priority = (request.args.get("priority") or "").strip()
    employee_id = request.args.get("employee_id")

    view_team = employee_has_phone_perm(g.phone_employee, "phone.tasks.view_team")
    if employee_id and view_team:
        q = PhoneFollowupTask.query.filter_by(employee_id=int(employee_id))
    elif view_team and request.args.get("scope") == "team":
        q = PhoneFollowupTask.query
    else:
        q = PhoneFollowupTask.query.filter_by(employee_id=g.phone_employee.id)

    if status:
        q = q.filter_by(status=status)
    if task_type:
        q = q.filter_by(task_type=task_type)
    if priority:
        q = q.filter_by(priority=priority)

    now = _utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta

    tomorrow = today_start + timedelta(days=1)
    if filt == "today":
        q = q.filter(
            PhoneFollowupTask.due_at.isnot(None),
            PhoneFollowupTask.due_at >= today_start,
            PhoneFollowupTask.due_at < tomorrow,
        )
    elif filt == "overdue":
        q = q.filter(
            PhoneFollowupTask.status.in_(("open", "in_progress", "overdue")),
            PhoneFollowupTask.due_at.isnot(None),
            PhoneFollowupTask.due_at < now,
        )
    elif filt == "high_priority":
        q = q.filter(PhoneFollowupTask.priority.in_(("high", "urgent")))
    elif filt == "missed":
        q = q.filter(
            PhoneFollowupTask.task_type.in_(("missed_call_followup", "missed_call"))
        )
    elif filt == "callback":
        q = q.filter(PhoneFollowupTask.task_type.in_(("callback", "callback_required")))
    elif filt == "complaint":
        q = q.filter(
            (PhoneFollowupTask.task_type == "complaint_followup")
            | (PhoneFollowupTask.reason == "complaint")
        )

    rows = (
        q.order_by(PhoneFollowupTask.id.desc())
        .limit(200)
        .all()
    )
    # Soft sort: due_at ascending with nulls last
    rows.sort(
        key=lambda t: (
            t.due_at is None,
            t.due_at or datetime.max,
            -(t.id or 0),
        )
    )
    return api_ok({"tasks": [_serialize(t) for t in rows]})
