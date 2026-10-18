"""Tutor API (/api/clinic/ai-tutor/*). Every route is gated server-side."""
from __future__ import annotations

import re
from datetime import datetime

from flask import Blueprint, jsonify, request, session

from extensions import db
from modules.ai_tutor import registry
from modules.ai_tutor.chat import context as chat_context
from modules.ai_tutor.chat import knowledge as chat_knowledge
from modules.ai_tutor.chat import ratelimit, service as chat_service
from modules.ai_tutor.chat.provider import get_provider
from modules.ai_tutor.facts import collect_facts
from modules.ai_tutor.models import (
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED,
    STATUS_PAUSED,
    TrainingActivityLog,
    UserTrainingProgress,
)
from modules.ai_tutor.schema import ensure_ai_tutor_schema
from modules.ai_tutor.validators import VALIDATORS
from services import feature_service as fs

ai_tutor_bp = Blueprint("ai_tutor", __name__, url_prefix="/api/clinic/ai-tutor")

PROGRESS_EVENTS = {"step_completed", "rewind", "paused", "abandoned", "target_missing", "step_failed"}
ONBOARDING_ID = "_onboarding"  # progress row: completed = the user dismissed/used the welcome card


def _tenant_id() -> int:
    from modules.clinics.guards import current_tenant_id

    return current_tenant_id()


def _user_id() -> int:
    return int(session["user_id"])


def _has_permission(permission: str) -> bool:
    from modules.clinics.guards import can_use_clinics

    return can_use_clinics(permission)


@ai_tutor_bp.before_request
def _gate():
    if not session.get("user_id") or not fs.current_tenant_slug():
        return jsonify({"error": "AUTH_REQUIRED"}), 401
    if not fs.is_enabled_for_slug(fs.current_tenant_slug(), fs.AI_TUTOR):
        return jsonify({"error": "FEATURE_NOT_ENABLED", "feature": fs.AI_TUTOR}), 403
    ensure_ai_tutor_schema()
    return None


def _bad(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def _definition_or_error(tutorial_id: str):
    definition = registry.get(tutorial_id)
    if definition is None or not registry.is_runnable(definition):
        return None, _bad("tutorial not found", 404)
    if not registry.is_available(definition, _has_permission, collect_facts(_tenant_id())):
        return None, _bad("tutorial not permitted", 403)
    return definition, None


def _progress(tutorial_id: str) -> UserTrainingProgress | None:
    return UserTrainingProgress.query.filter_by(
        tenant_id=_tenant_id(), user_id=_user_id(), tutorial_id=tutorial_id
    ).first()


DETAIL_TOKEN = re.compile(r"^[A-Za-z0-9_.:\-]{1,80}$")


def _log(definition: dict, event: str, step_id: str | None = None, detail: str | None = None) -> None:
    # Privacy: only short machine tokens (error codes, ids) are ever stored; free text (could be patient data) is dropped.
    detail = detail if detail and DETAIL_TOKEN.match(detail) else None
    db.session.add(TrainingActivityLog(
        tenant_id=_tenant_id(), user_id=_user_id(), tutorial_id=definition["id"],
        tutorial_version=definition["version"], step_id=step_id, event=event,
        detail=detail,
    ))


def _progress_dict(p: UserTrainingProgress | None) -> dict | None:
    if p is None:
        return None
    return {
        "tutorial_id": p.tutorial_id, "tutorial_version": p.tutorial_version,
        "current_step": p.current_step, "step_index": p.step_index, "status": p.status,
        "started_at": p.started_at.isoformat() if p.started_at else None,
        "completed_at": p.completed_at.isoformat() if p.completed_at else None,
        "parent": ({"tutorial_id": p.parent_tutorial_id, "step_id": p.parent_step_id}
                   if p.parent_tutorial_id else None),
    }


@ai_tutor_bp.get("/tutorials")
def list_tutorials():
    facts_now = collect_facts(_tenant_id())
    rows = []
    for definition in registry.load_all().values():
        if registry.is_available(definition, _has_permission, facts_now):
            rows.append({**registry.summary(definition), "progress": _progress_dict(_progress(definition["id"]))})
    return jsonify({"ok": True, "tutorials": rows})


@ai_tutor_bp.get("/facts")
def facts():
    return jsonify({"ok": True, "facts": collect_facts(_tenant_id())})


@ai_tutor_bp.get("/tutorials/<tutorial_id>")
def get_tutorial(tutorial_id):
    definition, error = _definition_or_error(tutorial_id)
    if error:
        return error
    return jsonify({"ok": True, "tutorial": definition, "progress": _progress_dict(_progress(tutorial_id))})


@ai_tutor_bp.get("/active")
def active():
    p = (
        UserTrainingProgress.query.filter(
            UserTrainingProgress.tenant_id == _tenant_id(),
            UserTrainingProgress.user_id == _user_id(),
            UserTrainingProgress.status == STATUS_IN_PROGRESS,
            UserTrainingProgress.tutorial_id != ONBOARDING_ID,
        ).order_by(UserTrainingProgress.last_activity_at.desc()).first()
    )
    if p is None:
        return jsonify({"ok": True, "active": None})
    definition = registry.get(p.tutorial_id)
    if definition is None or not registry.is_available(definition, _has_permission, collect_facts(_tenant_id())):
        return jsonify({"ok": True, "active": None})
    if definition["version"] != p.tutorial_version:
        # The tutorial changed since this run started: never resume a stale step graph.
        p.status = STATUS_NOT_STARTED
        db.session.commit()
        return jsonify({"ok": True, "active": None})
    return jsonify({"ok": True, "active": {"tutorial": definition, "progress": _progress_dict(p)}})


def _parent_from_body(tutorial_id: str, data: dict):
    """Validate an optional {"parent": {tutorial_id, step_id}} naming the tutorial that needs this one."""
    parent = data.get("parent")
    if parent is None:
        return None, None
    if not isinstance(parent, dict):
        return None, _bad("invalid parent")
    parent_def, error = _definition_or_error(str(parent.get("tutorial_id")))
    if error:
        return None, error
    if parent.get("step_id") not in [s["id"] for s in parent_def["steps"]]:
        return None, _bad("unknown parent step")
    parent_row = _progress(parent_def["id"])
    if parent_row is None or parent_row.status != STATUS_IN_PROGRESS:
        return None, _bad("parent tutorial is not in progress", 409)
    if not any(dep["tutorial"] == tutorial_id for dep in parent_def.get("dependencies", [])):
        return None, _bad("parent does not depend on this tutorial", 409)
    return (parent_def, parent_row, parent["step_id"]), None


@ai_tutor_bp.post("/tutorials/<tutorial_id>/start")
def start(tutorial_id):
    definition, error = _definition_or_error(tutorial_id)
    if error:
        return error
    parent, error = _parent_from_body(tutorial_id, request.get_json(silent=True) or {})
    if error:
        return error
    now = datetime.utcnow()
    p = _progress(tutorial_id)
    if p is None:
        p = UserTrainingProgress(tenant_id=_tenant_id(), user_id=_user_id(), tutorial_id=tutorial_id)
        db.session.add(p)
    p.tutorial_version = definition["version"]
    p.status = STATUS_IN_PROGRESS
    p.step_index = 0
    p.current_step = definition["steps"][0]["id"]
    p.started_at, p.completed_at, p.last_activity_at = now, None, now
    p.parent_tutorial_id = p.parent_step_id = None
    if parent:
        parent_def, parent_row, parent_step = parent
        # Only one tutorial is active at a time: park the parent until this dependency is done.
        parent_row.status, parent_row.last_activity_at = STATUS_PAUSED, now
        p.parent_tutorial_id, p.parent_step_id = parent_def["id"], parent_step
        _log(parent_def, "dependency_started", parent_step, tutorial_id)
    _log(definition, "tutorial_started", p.current_step)
    db.session.commit()
    return jsonify({"ok": True, "tutorial": definition, "progress": _progress_dict(p)})


@ai_tutor_bp.post("/tutorials/<tutorial_id>/progress")
def progress(tutorial_id):
    definition, error = _definition_or_error(tutorial_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    event = data.get("event")
    step_id = data.get("step_id")
    ids = [s["id"] for s in definition["steps"]]
    if event not in PROGRESS_EVENTS:
        return _bad("invalid event")
    if step_id not in ids:
        return _bad("unknown step")
    p = _progress(tutorial_id)
    if p is None or p.status == STATUS_COMPLETED:
        return _bad("tutorial not started", 409)
    if p.tutorial_version != definition["version"]:
        return _bad("tutorial version changed", 409)

    detail = data.get("detail") if isinstance(data.get("detail"), str) else None
    if event == "step_completed":
        next_id = data.get("next_step_id")
        if next_id not in ids:
            return _bad("unknown next step")
        # Progress only moves forward here; a late/duplicated request cannot rewind it.
        if ids.index(next_id) >= p.step_index:
            p.step_index, p.current_step = ids.index(next_id), next_id
        p.status = STATUS_IN_PROGRESS
    elif event == "rewind":
        # Explicit user-approved recovery: the only way to move backwards.
        p.step_index, p.current_step, p.status = ids.index(step_id), step_id, STATUS_IN_PROGRESS
    elif event == "abandoned":
        p.status = STATUS_NOT_STARTED
        p.parent_tutorial_id = p.parent_step_id = None
    else:  # paused / target_missing / step_failed
        p.status = STATUS_PAUSED
    p.last_activity_at = datetime.utcnow()
    _log(definition, {"step_completed": "step_completed", "abandoned": "tutorial_abandoned"}.get(event, event),
         step_id, detail)
    db.session.commit()
    return jsonify({"ok": True, "progress": _progress_dict(p)})


@ai_tutor_bp.post("/tutorials/<tutorial_id>/resume")
def resume(tutorial_id):
    definition, error = _definition_or_error(tutorial_id)
    if error:
        return error
    p = _progress(tutorial_id)
    if p is None or p.status != STATUS_PAUSED or p.tutorial_version != definition["version"]:
        return _bad("nothing to resume", 409)
    ids = [s["id"] for s in definition["steps"]]
    step_id = (request.get_json(silent=True) or {}).get("step_id")
    if step_id is not None:
        if step_id not in ids:
            return _bad("unknown step")
        p.step_index, p.current_step = ids.index(step_id), step_id
    p.status, p.last_activity_at = STATUS_IN_PROGRESS, datetime.utcnow()
    _log(definition, "tutorial_resumed", p.current_step)
    db.session.commit()
    return jsonify({"ok": True, "tutorial": definition, "progress": _progress_dict(p)})


def _declared_validators(definition: dict) -> set[str]:
    declared = {s["validator"] for s in definition["steps"] if s.get("validator")}
    declared |= {s["reconcile"]["validator"] for s in definition["steps"]
                 if (s.get("reconcile") or {}).get("kind") == "backend"}
    if definition.get("completion_validator"):
        declared.add(definition["completion_validator"])
    return declared


@ai_tutor_bp.post("/tutorials/<tutorial_id>/verify")
def verify(tutorial_id):
    definition, error = _definition_or_error(tutorial_id)
    if error:
        return error
    name = (request.get_json(silent=True) or {}).get("validator")
    if name not in _declared_validators(definition) or name not in VALIDATORS:
        return _bad("unknown validator")
    p = _progress(tutorial_id)
    if p is None or p.status != STATUS_IN_PROGRESS:
        return _bad("tutorial not in progress", 409)
    return jsonify({"ok": True, "verified": bool(VALIDATORS[name](_tenant_id(), p))})


@ai_tutor_bp.post("/tutorials/<tutorial_id>/complete")
def complete(tutorial_id):
    definition, error = _definition_or_error(tutorial_id)
    if error:
        return error
    p = _progress(tutorial_id)
    if p is None or p.status != STATUS_IN_PROGRESS:
        return _bad("tutorial not in progress", 409)
    validator = definition.get("completion_validator")
    if validator and not VALIDATORS[validator](_tenant_id(), p):
        return _bad("result could not be verified", 422)
    now = datetime.utcnow()
    parent = ({"tutorial_id": p.parent_tutorial_id, "step_id": p.parent_step_id}
              if p.parent_tutorial_id else None)
    p.status, p.completed_at, p.last_activity_at = STATUS_COMPLETED, now, now
    p.parent_tutorial_id = p.parent_step_id = None
    _log(definition, "tutorial_completed", next(s["id"] for s in definition["steps"] if s["type"] == "complete"))
    db.session.commit()
    completed = frozenset(
        row.tutorial_id for row in UserTrainingProgress.query.filter_by(
            tenant_id=_tenant_id(), user_id=_user_id(), status=STATUS_COMPLETED))
    # Recommendation only: the user decides whether to start the next lesson.
    suggestions = [] if parent else registry.next_lessons(definition, _has_permission, completed, collect_facts(_tenant_id()))
    return jsonify({"ok": True, "progress": _progress_dict(p), "parent": parent, "next_lessons": suggestions})


# ------------------------------------------------------------------ onboarding

def _onboarding_row() -> UserTrainingProgress | None:
    return _progress(ONBOARDING_ID)


@ai_tutor_bp.get("/onboarding")
def onboarding():
    """First-login welcome data. Wording adapts to the clinic ("first doctor" only when none exists)."""
    facts_now = collect_facts(_tenant_id())
    items = sorted(
        (d for d in registry.load_all().values()
         if d.get("onboarding_order") and registry.is_available(d, _has_permission, facts_now)),
        key=lambda d: d["onboarding_order"],
    )
    config = fs.get_status(fs.current_tenant_slug(), fs.AI_TUTOR)["configuration"]
    seen = _onboarding_row() is not None
    return jsonify({
        "ok": True,
        "show": bool(config.get("show_on_first_login")) and not seen and bool(items),
        "suggestions": [{"id": d["id"], "title_ar": registry.onboarding_title(d, facts_now)} for d in items],
    })


@ai_tutor_bp.post("/onboarding/dismiss")
def onboarding_dismiss():
    """Stores that the welcome card was dealt with. "Later" is handled client-side (this session only)."""
    if not (request.get_json(silent=True) or {}).get("forever"):
        return jsonify({"ok": True, "stored": False})
    now = datetime.utcnow()
    row = _onboarding_row() or UserTrainingProgress(
        tenant_id=_tenant_id(), user_id=_user_id(), tutorial_id=ONBOARDING_ID)
    row.tutorial_version, row.status, row.completed_at, row.last_activity_at = 1, STATUS_COMPLETED, now, now
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "stored": True})


# ------------------------------------------------------------------------ chat

def _permission_names() -> tuple[str, ...]:
    from modules.clinics.guards import CLINICS_PERMISSIONS

    return tuple(CLINICS_PERMISSIONS)


def _employee_role() -> str | None:
    from modules.clinics.guards import current_employee

    employee = current_employee()
    return getattr(employee, "role", None) if employee else None


def _context_from_request(data: dict) -> dict:
    return chat_context.build_context(
        tenant_id=_tenant_id(), user_id=_user_id(), role=_employee_role(),
        page=data.get("page"), route=data.get("route"),
        client_active=data.get("active") if isinstance(data.get("active"), dict) else None,
        invoice_context=data.get("invoice") if isinstance(data.get("invoice"), dict) else None,
        has_permission=_has_permission, permission_names=_permission_names(),
    )


@ai_tutor_bp.post("/ask")
def ask():
    """Natural-language question -> structured, registry-only response (rate limited, feature gated)."""
    allowed, retry_after = ratelimit.check_ask(_tenant_id(), _user_id())
    if not allowed:
        response = jsonify({"ok": False, "error": "RATE_LIMITED", "retry_after": retry_after})
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _bad("invalid body")
    message = data.get("message")
    forced = data.get("intent")
    if message is not None and not isinstance(message, str):
        return _bad("message must be text")
    if forced is not None and not isinstance(forced, str):
        return _bad("intent must be text")
    ctx = _context_from_request(data)
    result = chat_service.answer(message or "", ctx, forced_intent=forced, provider=get_provider())
    return jsonify({"ok": True, "response": result})


@ai_tutor_bp.get("/knowledge")
def knowledge():
    """Quick actions, suggested prompts and setup progress, all generated from the registry (nothing hard-coded in HTML)."""
    kb = chat_knowledge.load()
    facts_now = collect_facts(_tenant_id())
    available = {t["id"]: t for t in registry.load_all().values() if registry.is_available(t, _has_permission, facts_now)}
    group_order = {g["id"]: i for i, g in enumerate(kb.plan["groups"])}

    def curriculum_key(tutorial_id: str):
        spec = available[tutorial_id].get("curriculum") or {}
        return (group_order.get(spec.get("group"), len(group_order)), spec.get("order", 999), tutorial_id)

    entries = [e for e in kb.entries.values() if e.kind == "feature" and e.tutorial in available]
    entries.sort(key=lambda e: curriculum_key(e.tutorial))
    quick, prompts, listed = [], ["شنو هاي الصفحة؟"], set()
    for entry in entries:
        if entry.tutorial in listed:  # several features can be taught by one lesson: list the lesson once
            continue
        listed.add(entry.tutorial)
        quick.append({"tutorial_id": entry.tutorial, "label": entry.title_ar})
        if entry.prompt_ar:
            prompts.append(entry.prompt_ar)
    # The curriculum is generated from the tutorial registry: only lessons that exist AND this user may run (permissions,
    # never the role name). Groups without such lessons are not shown.
    done = {r.tutorial_id for r in UserTrainingProgress.query.filter_by(
        tenant_id=_tenant_id(), user_id=_user_id(), status=STATUS_COMPLETED)}
    groups = []
    for group in kb.plan["groups"]:
        lessons = sorted((t for t in available.values() if (t.get("curriculum") or {}).get("group") == group["id"]),
                         key=lambda t: t["curriculum"]["order"])
        if lessons:
            groups.append({"id": group["id"], "title_ar": group["title_ar"], "items": [
                {"id": t["id"], "title_ar": t["title_ar"], "state": "completed" if t["id"] in done else "available", "tutorial_id": t["id"]}
                for t in lessons]})
    return jsonify({"ok": True, "quick_actions": quick, "suggested_prompts": prompts, "plan": {"groups": groups}})
