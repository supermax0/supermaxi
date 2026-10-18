"""Small, privacy-safe context for the chat. Never the DOM, never patient data."""
from __future__ import annotations

import re
from typing import Callable

from modules.ai_tutor import registry
from modules.ai_tutor.chat import service
from modules.ai_tutor.chat.knowledge import load
from modules.ai_tutor.analyzer.static_scan import page_config
from modules.ai_tutor.facts import collect_facts
from modules.ai_tutor.models import STATUS_IN_PROGRESS, UserTrainingProgress

_ID_SEGMENT = re.compile(r"/\d+")


def safe_route(route) -> str | None:
    """Path only (no query/ids) and only inside the clinics workspace."""
    if not isinstance(route, str):
        return None
    path = _ID_SEGMENT.sub("/:id", route.split("?")[0].split("#")[0])[:120]
    return path if path == "/clinics" or path.startswith("/clinics/") else None


INVOICE_STATUSES = frozenset({"open", "partial", "paid", "void", "cancelled", "refunded"})


def safe_invoice_context(raw) -> dict | None:
    """Numbers/status only, from the invoice drawer the user already has open (never sent to an LLM provider).

    No patient name, phone or treatment details ever pass through here — only what the local engine needs to word
    an honest answer about THIS invoice (e.g. "it's already fully paid").
    """
    if not isinstance(raw, dict):
        return None
    try:
        remaining = int(raw.get("remaining"))
    except (TypeError, ValueError):
        return None
    if remaining < 0:
        return None
    status = raw.get("status")
    return {"remaining": remaining, "status": status if status in INVOICE_STATUSES else None}


def build_context(*, tenant_id: int, user_id: int, role: str | None, page, route, client_active: dict | None,
                  invoice_context: dict | None = None,
                  has_permission: Callable[[str], bool], permission_names: tuple[str, ...]) -> dict:
    kb = load()
    page_id = page if isinstance(page, str) and page in kb.pages else None
    facts = collect_facts(tenant_id)
    runnable = {t["id"] for t in registry.load_all().values() if registry.is_runnable(t)}
    all_tutorials = registry.load_all().values()
    available = {t["id"] for t in all_tutorials if registry.is_available(t, has_permission, facts)}
    # Why a runnable-but-unavailable lesson is hidden (never re-derived by the chat): "permission" | "specialty:<code>" | ...
    unavailable_reasons = {
        t["id"]: registry.availability_reason(t, has_permission, facts)
        for t in all_tutorials if t["id"] in runnable and t["id"] not in available
    }

    # The active tutorial/step comes from the server's own progress row; the client may only add an issue label.
    active = None
    row = (UserTrainingProgress.query.filter(
        UserTrainingProgress.tenant_id == tenant_id, UserTrainingProgress.user_id == user_id,
        UserTrainingProgress.status == STATUS_IN_PROGRESS, UserTrainingProgress.tutorial_id != "_onboarding",
    ).order_by(UserTrainingProgress.last_activity_at.desc()).first())
    if row and row.tutorial_id in available:
        active = {"id": row.tutorial_id, "step_id": row.current_step, "step_index": row.step_index}
    issue = (client_active or {}).get("issue")
    return {
        "page": page_id,
        "route": safe_route(route),
        "user_role": role,
        "permissions": sorted(p for p in permission_names if has_permission(p)),
        "available_tutorials": available,
        "allowed_pages": {pid for pid, (_, permission) in page_config().items() if has_permission(permission)},
        "runnable_tutorials": runnable,
        "unavailable_reasons": unavailable_reasons,
        "invoice_context": safe_invoice_context(invoice_context),
        "active_tutorial": active,
        "issue": issue if issue in service.ISSUES and active else None,
        "facts": facts,
    }


def public_view(ctx: dict) -> dict:
    """The part of the context that is allowed to leave the server (ids and counts only)."""
    return {
        "page": ctx["page"], "route": ctx["route"], "user_role": ctx["user_role"],
        "permissions": ctx["permissions"], "available_tutorials": sorted(ctx["available_tutorials"]),
        "active_tutorial": ctx["active_tutorial"],
    }
