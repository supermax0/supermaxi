"""Tutorial registry: loads and strictly validates JSON tutorial definitions."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from modules.ai_tutor.facts import FACT_NAMES, OPERATORS, SPECIALTY_ALIASES

TUTORIALS_DIR = Path(__file__).parent / "tutorials"

STEP_TYPES = frozenset({
    "navigate", "highlight", "explain", "wait_click", "wait_input", "wait_select",
    "wait_modal", "wait_api_success", "wait_state", "complete", "error", "branch",
})
TARGET_KINDS = ("page", "section", "action", "field")
STATUSES = frozenset({"verified", "needs_review", "broken", "draft", "disabled"})
RUNNABLE_STATUS = "verified"
TARGET_REQUIRED = frozenset({"wait_click", "wait_input", "wait_select", "wait_modal", "wait_api_success"})


CURRICULUM_GROUPS = frozenset({"setup", "operations", "collections"})
RECONCILE_KINDS = ("ui", "backend")
UI_PREDICATES = ("page", "visible")

# Availability contract (distinct from `requires_permissions`, which gates whether a user may ever run a lesson
# at all): a lesson can additionally declare conditions on the *tenant's* setup. None of this is checked by the
# chat directly — the chat only ever asks `registry.is_available()` / `registry.availability_reason()`.
AVAILABILITY_KEYS = frozenset({"required_pages", "required_features", "required_specialty", "required_permissions", "required_context"})
# Known per-tenant capability flags. Today every clinic has all of them (there is no module toggle yet), so this
# exists for the architecture the task asked for: a lesson can declare `required_features` and the check is real,
# not a no-op hardcoded in the chat. An unknown feature name is simply never available.
AVAILABLE_FEATURES = frozenset({"appointments", "billing", "patients", "visits", "clinical", "services", "schedules", "staff", "reception", "inventory"})


class TutorialError(ValueError):
    pass


def _check_fact_rule(rule: Any, where: str) -> None:
    if (not isinstance(rule, dict) or rule.get("name") not in FACT_NAMES or rule.get("op") not in OPERATORS
            or not isinstance(rule.get("value"), int)):
        raise TutorialError(f"{where}: invalid fact rule {rule!r}")


def _check_availability(availability: Any, tutorial_id: str) -> None:
    """`availability`: tenant-setup conditions, separate from `requires_permissions` (which gates the user)."""
    if availability is None:
        return
    where = f"{tutorial_id}:availability"
    if not isinstance(availability, dict) or not availability or set(availability) - AVAILABILITY_KEYS:
        raise TutorialError(f"{where}: unknown key(s), allowed are {sorted(AVAILABILITY_KEYS)}")
    for key in ("required_pages", "required_features", "required_permissions"):
        value = availability.get(key)
        if value is not None and (not isinstance(value, list) or not all(isinstance(v, str) and v for v in value)):
            raise TutorialError(f"{where}.{key}: must be a list of strings")
    specialty = availability.get("required_specialty")
    if specialty is not None and not (isinstance(specialty, str) and specialty):
        raise TutorialError(f"{where}.required_specialty: must be a non-empty string")
    context = availability.get("required_context")
    if context is not None:
        if not isinstance(context, list) or not context:
            raise TutorialError(f"{where}.required_context: must be a non-empty list of fact rules")
        for rule in context:
            _check_fact_rule(rule, f"{where}.required_context")


def _check_reconcile(step: dict, where: str) -> None:
    """Explicit auto-skip policy. UI facts may skip safe steps; irreversible ones need a backend validator."""
    rec = step.get("reconcile")
    if rec is None:
        return
    kind = rec.get("kind") if isinstance(rec, dict) else None
    if kind not in RECONCILE_KINDS:
        raise TutorialError(f"{where}: reconcile.kind must be one of {RECONCILE_KINDS}")
    if kind == "ui":
        when = rec.get("when")
        if not isinstance(when, dict) or len(when) != 1 or next(iter(when)) not in UI_PREDICATES:
            raise TutorialError(f"{where}: reconcile.when must be exactly one of {UI_PREDICATES}")
        if "visible" in when:
            _check_target(when["visible"], where)
        if step["type"] in {"wait_api_success", "wait_state", "complete"}:
            raise TutorialError(f"{where}: {step['type']} may only be reconciled from backend state")
    elif not rec.get("validator"):
        raise TutorialError(f"{where}: backend reconcile needs a validator")


def _check_target(ref: Any, where: str) -> None:
    if not isinstance(ref, dict) or len(ref) != 1:
        raise TutorialError(f"{where}: target must have exactly one of {TARGET_KINDS}")
    kind, value = next(iter(ref.items()))
    if kind not in TARGET_KINDS or not isinstance(value, str) or not value:
        raise TutorialError(f"{where}: invalid target {ref!r}")


def target_refs(step: dict) -> list[dict]:
    """Every UI identifier a step depends on (used by the source verification test)."""
    refs = []
    for key in ("target", "watch"):
        if step.get(key):
            refs.append(step[key])
    refs.extend(step.get("reveal") or [])
    if isinstance(step.get("if"), dict) and step["if"].get("exists"):
        refs.append(step["if"]["exists"])
    return refs


def validate_definition(d: Any) -> dict:
    if not isinstance(d, dict):
        raise TutorialError("definition must be an object")
    for key in ("id", "version", "status", "title_ar", "steps"):
        if key not in d:
            raise TutorialError(f"missing {key}")
    if d["status"] not in STATUSES:
        raise TutorialError(f"invalid status {d['status']!r}")
    if not isinstance(d["version"], int) or d["version"] < 1:
        raise TutorialError("version must be a positive integer")
    steps = d["steps"]
    if not isinstance(steps, list) or not steps:
        raise TutorialError("steps must be a non-empty list")
    ids = [s.get("id") for s in steps if isinstance(s, dict)]
    if len(ids) != len(steps) or len(set(ids)) != len(ids) or not all(isinstance(i, str) and i for i in ids):
        raise TutorialError("every step needs a unique string id")
    for step in steps:
        where = f"{d['id']}:{step['id']}"
        stype = step.get("type")
        if stype not in STEP_TYPES:
            raise TutorialError(f"{where}: unsupported step type {stype!r}")
        if stype in TARGET_REQUIRED and "target" not in step:
            raise TutorialError(f"{where}: {stype} requires a target")
        for ref in target_refs(step):
            _check_target(ref, where)
        if stype == "navigate" and not str(step.get("route", "")).startswith("/"):
            raise TutorialError(f"{where}: navigate needs a route")
        if stype == "wait_api_success" and not isinstance(step.get("match"), dict):
            raise TutorialError(f"{where}: wait_api_success needs match")
        if stype == "wait_state" and not step.get("validator"):
            raise TutorialError(f"{where}: wait_state needs a validator")
        for key in ("recovery_message_ar", "recovery_retry_label_ar"):
            if key in step and not (isinstance(step[key], str) and step[key]):
                raise TutorialError(f"{where}: {key} must be a non-empty string")
        if stype == "branch":
            for key in ("then", "else"):
                if step.get(key) not in ids:
                    raise TutorialError(f"{where}: branch {key} must reference an existing step")
            if not isinstance(step.get("if"), dict):
                raise TutorialError(f"{where}: branch needs an if condition")
        _check_reconcile(step, where)
        if "allow_back" in step and not isinstance(step["allow_back"], bool):
            raise TutorialError(f"{where}: allow_back must be boolean")
        if stype in {"complete", "error"} and not step.get("message_ar"):
            raise TutorialError(f"{where}: {stype} needs message_ar")
    if not any(s["type"] == "complete" for s in steps):
        raise TutorialError("tutorial needs a complete step")
    for dep in d.get("dependencies", []):
        where = f"{d['id']}:dependency"
        _check_fact_rule(dep.get("fact"), where)
        for key in ("tutorial", "message_ar", "action_label_ar"):
            if not isinstance(dep.get(key), str) or not dep[key]:
                raise TutorialError(f"{where}: missing {key}")
    if "next_lessons" in d and (not isinstance(d["next_lessons"], list) or not all(isinstance(i, str) and i for i in d["next_lessons"])):
        raise TutorialError(f"{d['id']}: next_lessons must be a list of tutorial ids")
    curriculum = d.get("curriculum")
    if curriculum is not None and (
        not isinstance(curriculum, dict) or curriculum.get("group") not in CURRICULUM_GROUPS
        or not isinstance(curriculum.get("order"), int)
    ):
        raise TutorialError(f"{d['id']}: curriculum needs group in {sorted(CURRICULUM_GROUPS)} and an integer order")
    if "title_first_when" in d:
        _check_fact_rule(d["title_first_when"], f"{d['id']}:title_first_when")
        if not d.get("title_first_ar"):
            raise TutorialError(f"{d['id']}: title_first_ar required with title_first_when")
    _check_availability(d.get("availability"), d["id"])
    return d


@lru_cache(maxsize=1)
def load_all() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for path in sorted(TUTORIALS_DIR.glob("*.json")):
        definition = validate_definition(json.loads(path.read_text(encoding="utf-8")))
        if definition["id"] in result:
            raise TutorialError(f"duplicate tutorial id {definition['id']}")
        result[definition["id"]] = definition
    seen_slots: dict[tuple, str] = {}
    for definition in result.values():
        for dep in definition.get("dependencies", []):
            if dep["tutorial"] not in result or dep["tutorial"] == definition["id"]:
                raise TutorialError(f"{definition['id']}: dependency tutorial {dep['tutorial']!r} is not a valid other tutorial")
        spec = definition.get("curriculum")
        if spec:
            slot = (spec["group"], spec["order"])
            if slot in seen_slots:
                raise TutorialError(f"{definition['id']}: curriculum slot {slot} is already used by {seen_slots[slot]}")
            seen_slots[slot] = definition["id"]
        for nxt in definition.get("next_lessons", []):
            if nxt not in result or nxt == definition["id"]:
                raise TutorialError(f"{definition['id']}: next lesson {nxt!r} is not a valid other tutorial")
    return result


def get(tutorial_id: str) -> dict | None:
    return load_all().get(tutorial_id)


def is_runnable_status(definition: dict) -> bool:
    """Declared status only (no analyzer involved)."""
    return definition["status"] == RUNNABLE_STATUS


def is_runnable(definition: dict) -> bool:
    """Only verified tutorials run for users; authors may opt in to drafts locally.

    A tutorial the system analyzer found broken (and whose snapshot still matches the sources) is withheld.
    """
    if definition["status"] == RUNNABLE_STATUS:
        from modules.ai_tutor.analyzer import snapshot  # lazy: analyzer imports this module

        return definition["id"] not in snapshot.broken_tutorial_ids()
    return definition["status"] == "draft" and os.environ.get("AI_TUTOR_ALLOW_DRAFT") == "1"


def _specialty_fact_key(code: str) -> str:
    return f"{SPECIALTY_ALIASES.get(code, code)}_active"


def availability_reason(definition: dict, has_permission: Callable[[str], bool], facts: dict[str, int] | None = None) -> str | None:
    """None when the lesson is available; otherwise why, for the chat to pick the right wording:
    "permission" (requires_permissions, including availability.required_permissions), "page", "feature",
    "specialty:<code>" or "context". This is the single source of truth — the chat never re-derives it.
    """
    if not is_runnable(definition):
        return "unavailable"
    if not all(has_permission(p) for p in definition.get("requires_permissions", [])):
        return "permission"
    availability = definition.get("availability") or {}
    if availability.get("required_permissions") and not all(has_permission(p) for p in availability["required_permissions"]):
        return "permission"
    if availability.get("required_pages"):
        from modules.ai_tutor.analyzer.static_scan import page_config

        known = page_config()
        if not all(p in known for p in availability["required_pages"]):
            return "page"
    if availability.get("required_features") and not all(f in AVAILABLE_FEATURES for f in availability["required_features"]):
        return "feature"
    specialty = availability.get("required_specialty")
    if specialty:
        if facts is None or not facts.get(_specialty_fact_key(specialty)):
            return f"specialty:{specialty}"
    context = availability.get("required_context")
    if context:
        from modules.ai_tutor.facts import fact_met

        if facts is None or not all(fact_met(rule, facts) for rule in context):
            return "context"
    return None


def is_available(definition: dict, has_permission: Callable[[str], bool], facts: dict[str, int] | None = None) -> bool:
    return availability_reason(definition, has_permission, facts) is None


def next_lessons(definition: dict, has_permission: Callable[[str], bool], completed: frozenset[str] = frozenset(),
                  facts: dict[str, int] | None = None) -> list[dict]:
    """Recommended next lessons from the registry graph: only runnable, permitted, available, not yet completed ones."""
    result = []
    for lesson_id in definition.get("next_lessons", []):
        target = get(lesson_id)
        if target and lesson_id not in completed and is_available(target, has_permission, facts):
            result.append({"id": lesson_id, "title_ar": target["title_ar"]})
    return result


def summary(definition: dict) -> dict:
    return {k: definition.get(k) for k in ("id", "version", "level", "title_ar", "description_ar", "onboarding_order")}


def onboarding_title(definition: dict, facts: dict[str, int]) -> str:
    """Onboarding wording only: "first doctor" when the tenant has none yet."""
    from modules.ai_tutor.facts import fact_met

    rule = definition.get("title_first_when")
    if rule and fact_met(rule, facts):
        return definition["title_first_ar"]
    return definition["title_ar"]
