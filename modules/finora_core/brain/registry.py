"""FINORA tool risk registry (Phase 9 / Priority 4).

Every tool FINORA CORE knows about declares its contract here: input schema, output schema, the operator permission
needed to authorize it, a risk class, idempotency behaviour, a verification function and audit behaviour.

The Policy Engine (``policy.decide``) and the executor (``tools.run_tool``) read ONLY this registry to authorize an
action. The model's output is a proposal; it never carries authority. Risk classes:

- READ_ONLY       no state change — the agent may run it.
- LOW_RISK        reversible, internal state (CRM lead, recommendation, handoff) — the agent may run it when the
                  matching automation flag is on.
- MEDIUM_RISK     visible to the customer or creates resources — always an approved, immutable plan.
- HIGH_RISK       money, accounts or credentials — always an approved, immutable plan.
- NEVER_AUTOMATIC never executed by FINORA CORE (no plan, no approval can trigger it); humans use the normal admin UI.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

READ_ONLY = "READ_ONLY"
LOW_RISK = "LOW_RISK"
MEDIUM_RISK = "MEDIUM_RISK"
HIGH_RISK = "HIGH_RISK"
NEVER_AUTOMATIC = "NEVER_AUTOMATIC"
RISK_CLASSES = (READ_ONLY, LOW_RISK, MEDIUM_RISK, HIGH_RISK, NEVER_AUTOMATIC)
AGENT_EXECUTABLE = frozenset({READ_ONLY, LOW_RISK})
APPROVAL_REQUIRED = frozenset({MEDIUM_RISK, HIGH_RISK})
LEGACY_RISK = {READ_ONLY: "low", LOW_RISK: "low", MEDIUM_RISK: "medium", HIGH_RISK: "high", NEVER_AUTOMATIC: "high"}

# Idempotency behaviours
PER_CUSTOMER = "per_customer"  # one successful execution per customer (key: "<tool>:<customer id>")
PER_APPROVAL = "per_approval"  # one execution per approval (key: "approval:<id>")
NATURAL = "natural"  # re-running converges to the same state (set-style operations)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    risk: str
    permission: str  # operator permission (modules/finora_core/permissions.py) needed to authorize / run it
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    idempotency: str
    verify: Callable[..., bool] | None
    audit_fields: tuple[str, ...] = ()  # result keys allowed in the audit summary (everything else is withheld)
    flag: str | None = None  # automation flag that must be on for the agent to run it
    secret_output: bool = False  # produces one-time credentials (never stored / logged / shown to a model)
    implemented: bool = True
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def agent_executable(self) -> bool:
        return self.risk in AGENT_EXECUTABLE and self.implemented

    @property
    def needs_approval(self) -> bool:
        return self.risk in APPROVAL_REQUIRED


def _obj(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(required), "properties": properties}


# ───────────────────────────── verification functions ─────────────────────────────
# Each returns True only when the real post-condition holds in the system of record (not the tool's own return value).


def _verify_lead(s: Session, customer, args, data, **_) -> bool:
    from models.core.leads.models import BusinessLead

    return bool(customer.lead_id) and s.get(BusinessLead, customer.lead_id) is not None


def _verify_recommendation(s: Session, customer, args, data, **_) -> bool:
    from . import memory

    fact = memory.active_facts(s, customer.id, min_confidence=0).get("recommendedPlan") or {}
    return fact.get("value") == data.get("plan_name")


def _verify_handoff(s: Session, customer, args, data, conversation=None, **_) -> bool:
    return conversation is None or bool(conversation.human_takeover)


def _verify_trial(s: Session, customer, args, data, **_) -> bool:
    from flask import current_app

    from models.core.tenant import Tenant

    slug = data.get("tenant_slug")
    if not slug or customer.tenant_slug != slug:
        return False
    tenant = s.query(Tenant).filter_by(slug=slug).first()
    path = os.path.join(current_app.root_path, "tenants", f"{slug}.db")
    return tenant is not None and tenant.is_active and os.path.exists(path)


def _verify_discount(s: Session, customer, args, data, **_) -> bool:
    from . import memory

    commitments = (memory.active_facts(s, customer.id, min_confidence=0).get("commitments") or {}).get("value") or []
    return any(f"{int(data.get('discount_percent', -1))}%" in c for c in commitments)


def _verify_configuration(*args, **kwargs):
    from .tenant_setup import verified
    return verified(*args, **kwargs)


def _verify_project(*args, **kwargs):
    from .project_consultation import verified
    return verified(*args, **kwargs)


# ───────────────────────────── the registry ─────────────────────────────

_TRIAL_PLAN = _obj({
    "advice_ref": {"type": ["string", "null"]}, "advice_version": {"type": ["string", "null"]},
    "setup_profile": {"type": ["string", "null"], "enum": [None, "general", "starter_business", "beauty_center", "hr_management", "flowers", "wholesale", "grocery", "clinic", "dental_clinic"]},
    "business_type": {"type": "string", "pattern": "^[a-z_]{2,40}$"},
    "business_name": {"type": "string", "minLength": 1, "maxLength": 150},
    "contact_name": {"type": ["string", "null"], "maxLength": 120},
    "phone": {"type": ["string", "null"], "pattern": r"^\+\d{8,15}$"},
    "email": {"type": ["string", "null"], "maxLength": 254},
    "plan_key": {"type": "string", "pattern": "^[a-z0-9_-]{1,50}$"},
    "trial_days": {"type": "integer", "minimum": 1, "maximum": 30},
}, ("business_type", "business_name", "plan_key", "trial_days"))

REGISTRY: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        *[ToolSpec(
            name=name, title=title, risk=HIGH_RISK, permission="settings.manage",
            input_schema=_obj({"conversation_ref": {"type": "string", "pattern": "^[0-9]+$"},
                               "revision": {"type": "integer", "minimum": 1},
                               "state_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                               "payment_reference": {"type": ["string", "null"], "maxLength": 200}},
                              ("conversation_ref", "revision", "state_hash", "payment_reference")),
            output_schema=_obj({"conversation_ref": {"type": "string"}, "revision": {"type": "integer"}, "phase": {"type": "string"}},
                               ("conversation_ref", "revision", "phase")),
            idempotency=PER_APPROVAL, verify=_verify_project, audit_fields=("conversation_ref", "revision", "phase"),
        ) for name, title in (("publish_project_quote", "اعتماد عرض تطوير مخصص"), ("confirm_project_deposit", "تأكيد وصول عربون المشروع"))],
        ToolSpec(
            name="lookup_knowledge", title="بحث في معرفة FINORA", risk=READ_ONLY, permission="conversations.view",
            input_schema=_obj({"query": {"type": "string", "maxLength": 500}}, ("query",)),
            output_schema=_obj({"items": {"type": "array"}}), idempotency=NATURAL, verify=None,
            notes="retrieval over published knowledge; runs inside the pipeline, no state change", implemented=False,
        ),
        ToolSpec(
            name="create_lead", title="تسجيل العميل في CRM", risk=LOW_RISK, permission="messages.send",
            input_schema=_obj({}),
            output_schema=_obj({"lead_id": {"type": "integer"}, "linked_existing": {"type": "boolean"}}, ("lead_id",)),
            idempotency=PER_CUSTOMER, verify=_verify_lead, audit_fields=("lead_id", "linked_existing"),
            flag="AI_AUTO_LEAD",
        ),
        ToolSpec(
            name="recommend_plan", title="اقتراح باقة", risk=LOW_RISK, permission="messages.send",
            input_schema=_obj({"plan_key": {"type": "string", "pattern": "^[a-z0-9_-]{1,50}$"}}, ("plan_key",)),
            output_schema=_obj({"plan_key": {"type": "string"}, "plan_name": {"type": "string"}}, ("plan_key", "plan_name")),
            idempotency=NATURAL, verify=_verify_recommendation, audit_fields=("plan_key", "plan_name"),
        ),
        ToolSpec(
            name="handoff_human", title="تحويل المحادثة لفريق FINORA", risk=LOW_RISK, permission="ai.takeover",
            input_schema=_obj({"reason": {"type": "string", "maxLength": 300}}, ("reason",)),
            output_schema=_obj({"handed_off": {"type": "boolean"}}, ("handed_off",)),
            idempotency=NATURAL, verify=_verify_handoff, audit_fields=("handed_off",),
        ),
        ToolSpec(
            name="start_trial", title="إنشاء حساب تجريبي", risk=HIGH_RISK, permission="tenants.create",
            input_schema=_TRIAL_PLAN,
            output_schema=_obj({"tenant_slug": {"type": "string"}, "business_type": {"type": "string"},
                                "trial_days": {"type": "integer"}}, ("tenant_slug",)),
            idempotency=PER_APPROVAL, verify=_verify_trial, audit_fields=("tenant_slug", "business_type", "trial_days"),
            flag="AI_ACCOUNT_CREATION", secret_output=True,
            notes="creates a tenant + admin with one-time credentials (services/tenant_provisioning.py)",
        ),
        ToolSpec(
            name="grant_discount", title="اعتماد خصم", risk=HIGH_RISK, permission="approvals.decide",
            input_schema=_obj({"discount_percent": {"type": "integer", "minimum": 1, "maximum": 100}},
                              ("discount_percent",)),
            output_schema=_obj({"discount_percent": {"type": "integer"}}, ("discount_percent",)),
            idempotency=PER_APPROVAL, verify=_verify_discount, audit_fields=("discount_percent",),
            notes="records an approved commitment; never touches billing",
        ),
        ToolSpec(
            name="change_subscription", title="تغيير اشتراك", risk=NEVER_AUTOMATIC, permission="settings.manage",
            input_schema=_obj({"plan_key": {"type": "string"}}), output_schema=_obj({}), idempotency=NATURAL,
            verify=None, implemented=False, notes="billing changes are made by humans in Super Admin only",
        ),
        ToolSpec(
            name="configure_tenant", title="ترتيب حساب العميل", risk=HIGH_RISK, permission="settings.manage",
            input_schema=_obj({
                "customer_id": {"type": "integer"}, "tenant_slug": {"type": "string"}, "expected_version": {"type": "string"},
                "operation": {"enum": ["profile", "feature", "permissions", "advisory"]}, "profile": {"type": ["string", "null"]},
                "advice_ref": {"type": ["string", "null"]}, "advice_version": {"type": ["string", "null"]},
                "feature": {"type": ["string", "null"]}, "enabled": {"type": ["boolean", "null"]}, "employee_id": {"type": ["integer", "null"]},
                "permission_preset": {"type": ["string", "null"]}, "role_ids": {"type": ["array", "null"], "items": {"type": "integer"}},
                "feature_updates": {"type": "object", "additionalProperties": {"type": "boolean"}},
                "permission_updates": {"type": "object", "additionalProperties": {"type": "boolean"}}, "title": {"type": "string"}, "changes": {"type": "array"},
                "employee_name": {"type": ["string", "null"]}, "permission_changes": {"type": "array"}, "role_changes": {"type": ["object", "null"]},
                "unavailable_features": {"type": "array"},
                "business_type": {"type": ["string", "null"]}, "business_change": {"type": ["object", "null"]},
            }, ("customer_id", "tenant_slug", "expected_version", "operation", "feature_updates", "permission_updates")),
            output_schema={"type": "object", "required": ["tenant_slug", "operation", "version"]},
            idempotency=PER_APPROVAL, verify=_verify_configuration, audit_fields=("tenant_slug", "operation", "employee_id"), flag="AI_TENANT_CONFIGURATION",
        ),
        ToolSpec(
            name="delete_tenant", title="حذف شركة", risk=NEVER_AUTOMATIC, permission="settings.manage",
            input_schema=_obj({"tenant_slug": {"type": "string"}}), output_schema=_obj({}), idempotency=NATURAL,
            verify=None, implemented=False,
        ),
        ToolSpec(
            name="reveal_credentials", title="عرض بيانات الدخول", risk=NEVER_AUTOMATIC, permission="settings.manage",
            input_schema=_obj({}), output_schema=_obj({}), idempotency=NATURAL, verify=None, implemented=False,
            notes="credentials are never revealed — only reset (services/tenant_provisioning.reset_admin_password)",
        ),
        ToolSpec(
            name="export_customer_data", title="تصدير بيانات العملاء", risk=NEVER_AUTOMATIC, permission="settings.manage",
            input_schema=_obj({}), output_schema=_obj({}), idempotency=NATURAL, verify=None, implemented=False,
        ),
    )
}

# Plan action types (planner.ACTION_TYPES) → the tool they would run. Anything else is not a FINORA action.
ACTION_TOOL = {
    "publish_project_quote": "publish_project_quote",
    "confirm_project_deposit": "confirm_project_deposit",
    "create_lead": "create_lead",
    "recommend_plan": "recommend_plan",
    "handoff_human": "handoff_human",
    "start_trial": "start_trial",
    "request_discount": "grant_discount",
    "configure_tenant": "configure_tenant",
}


def spec_for(name: str) -> ToolSpec | None:
    return REGISTRY.get(name)


def tool_for_action(action_type: str | None) -> ToolSpec | None:
    name = ACTION_TOOL.get(action_type or "")
    return REGISTRY.get(name) if name else None


def describe() -> list[dict[str, Any]]:
    """Public registry view (desktop / docs): no functions, no secrets."""
    return [{"name": t.name, "title": t.title, "risk": t.risk, "permission": t.permission, "idempotency": t.idempotency,
             "agentExecutable": t.agent_executable, "needsApproval": t.needs_approval, "implemented": t.implemented,
             "verified": t.verify is not None, "flag": t.flag, "inputSchema": t.input_schema,
             "outputSchema": t.output_schema} for t in REGISTRY.values()]
