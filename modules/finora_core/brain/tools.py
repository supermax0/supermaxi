"""FINORA tools (spec §22): typed, validated, authorized, idempotent, verified and audited.

The model never calls these directly: plans → policy → (approval) → tool. No raw SQL or URLs come from the model.
Every contract (schemas, permission, risk class, idempotency, verification, audit) lives in ``registry.py``; this
executor re-checks it on every call, so a tool can never run on the model's word alone (defense in depth behind the
Policy Engine). Credentials produced by a tool are returned to the calling human once and are never stored, logged or
shown to an LLM.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import secrets
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterator

import jsonschema
from flask import g
from sqlalchemy.orm import Session

from extensions import db

from ..store import audit, new_correlation_id
from . import memory, registry
from .models import FcCustomer, FcLeadTransition, FcToolCall

# Set while a Shadow Mode run is in progress: no state-changing tool may execute (Phase 9 / Priority 2).
SHADOW_RUN: contextvars.ContextVar[bool] = contextvars.ContextVar("finora_core_shadow_run", default=False)

logger = logging.getLogger(__name__)

TRIAL_DAYS = 14
TENANT_BUSINESS_TYPE = {  # FINORA CORE businessType → routes/superadmin.BUSINESS_TYPES key
    "clinic": "clinics", "beauty_center": "beauty_center", "food_wholesale_retail": "food_wholesale_retail",
    "wholesale": "wholesale", "hr_management": "hr_management", "starter_business": "starter_business",
}
LEAD_ACTIVITY = {"food_wholesale_retail": "grocery", "wholesale": "wholesale", "restaurant": "restaurants",
                 "pharmacy": "pharmacy", "commerce": "clothing"}
LEAD_STATUS = {"new": "NEW", "engaged": "REPLIED", "qualified": "INTERESTED", "proposal": "INTERESTED",
               "trial": "TRIAL", "account_created": "TRIAL", "setup": "TRIAL", "onboarding": "TRIAL",
               "active_customer": "SUBSCRIBED", "lost": "LOST"}
STAGE_ORDER = ["new", "engaged", "qualified", "proposal", "trial", "account_created", "setup", "onboarding",
               "active_customer"]


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)  # safe, stored, may be shown to the model
    secret: dict[str, Any] | None = None  # returned to the approving human ONCE; never stored / logged / to LLM
    reused: bool = False


@contextmanager
def core_scope(s: Session) -> Iterator[None]:
    """Run Core-DB services that use ``db.session`` (leads CRM) from FINORA CORE code.

    - Finora routes ``db.session`` by ``g.tenant``: house work is committed first and ``g.tenant`` is lifted.
    - FINORA CORE's own Core session ``s`` is committed first too, so the two never hold interleaved write
      transactions on the Core DB (deadlock on SQLite, needless contention on PostgreSQL).
    - ``db.session`` is committed on exit so no transaction is left open behind ``s``.
    """
    s.commit()
    previous = getattr(g, "tenant", None)
    if previous is not None:
        db.session.commit()
        g.pop("tenant", None)
    try:
        yield
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        if previous is not None:
            g.tenant = previous


# ───────────────────────────── lead stage ─────────────────────────────


def move_stage(s: Session, customer: FcCustomer, to: str, *, actor: str, actor_type: str, reason: str) -> bool:
    """Forward-only automatic moves (humans may move anywhere through the CRM). Every move is recorded."""
    current = customer.lead_stage
    if current == to:
        return False
    if actor_type == "ai" and to in STAGE_ORDER and current in STAGE_ORDER and STAGE_ORDER.index(to) < STAGE_ORDER.index(current):
        return False
    s.add(FcLeadTransition(customer_id=customer.id, from_stage=current, to_stage=to, actor=actor,
                           actor_type=actor_type, reason=reason[:300]))
    customer.lead_stage = to
    if customer.lead_id and to in LEAD_STATUS:
        with core_scope(s):
            from services.leads_crm.lead_service import update_lead

            _, info = update_lead(customer.lead_id, {"status": LEAD_STATUS[to]})
            if info.get("error"):
                logger.warning("lead %s status sync failed: %s", customer.lead_id, info["error"])
    return True


# ───────────────────────────── tools ─────────────────────────────

def _create_lead(s: Session, customer: FcCustomer, args: dict[str, Any]) -> ToolResult:
    if customer.lead_id:
        return ToolResult(True, {"lead_id": customer.lead_id}, reused=True)
    facts = memory.active_facts(s, customer.id)
    btype = (facts.get("businessType") or {}).get("value")
    with core_scope(s):
        from models.core.leads.models import BusinessActivity
        from services.leads_crm.lead_service import create_lead

        activity = BusinessActivity.query.filter_by(slug=LEAD_ACTIVITY.get(btype, "other")).first() or \
            BusinessActivity.query.filter_by(slug="other").first()
        if activity is None:
            raise ToolError("CONFIG", "leads CRM activities are not seeded")
        phone = (facts.get("phone") or {}).get("value")
        lead, info = create_lead({
            "business_name": (facts.get("businessName") or {}).get("value") or customer.display_name,
            "activity_id": activity.id,
            "owner_name": (facts.get("contactName") or {}).get("value") or customer.display_name,
            "phone": phone,
            "city": (facts.get("city") or {}).get("value"),
            "notes": "أُنشئ بواسطة FINORA CORE من محادثة Instagram/Messenger",
        }, allow_possible_duplicate=True)
        if lead is None and info.get("error") == "duplicate_phone" and info.get("existing_lead"):
            customer.lead_id = int(info["existing_lead"]["id"])  # same business already in the CRM: link, never duplicate
            return ToolResult(True, {"lead_id": customer.lead_id, "linked_existing": True})
        if lead is None:
            raise ToolError("LEAD_REJECTED", str(info.get("error") or "lead not created"))
        customer.lead_id = lead.id
    return ToolResult(True, {"lead_id": customer.lead_id})


def _recommend_plan(s: Session, customer: FcCustomer, args: dict[str, Any]) -> ToolResult:
    from models.core.subscription_plan import SubscriptionPlan

    plan = s.query(SubscriptionPlan).filter_by(plan_key=args["plan_key"]).first()
    if plan is None:
        raise ToolError("NOT_FOUND", "unknown plan")
    memory.remember(s, customer.id, "recommendedPlan", plan.name, confidence=1.0, source="tool")
    return ToolResult(True, {"plan_key": plan.plan_key, "plan_name": plan.name})


def _slug_for(s: Session, customer: FcCustomer) -> str:
    from models.core.tenant import Tenant

    for _ in range(10):
        slug = f"fc{customer.id}-{secrets.token_hex(2)}"
        if s.query(Tenant).filter_by(slug=slug).first() is None:
            return slug
    raise ToolError("SLUG", "could not allocate a tenant slug")


def _start_trial(s: Session, customer: FcCustomer, args: dict[str, Any]) -> ToolResult:
    """Provision the trial tenant described by the APPROVED plan (args), through the shared provisioning service."""
    from models.core.tenant import Tenant
    from services.tenant_provisioning import ProvisioningError, provision_tenant

    if customer.tenant_slug:
        return ToolResult(True, {"tenant_slug": customer.tenant_slug}, reused=True)
    slug = _slug_for(s, customer)
    try:
        result = provision_tenant(
            name=args["business_name"], slug=slug, business_type=args["business_type"], source="finora_core_trial",
            core=s, contact_name=args.get("contact_name") or args["business_name"],
            contact_email=args.get("email"), contact_phone=args.get("phone"),
            subscription_days=int(args["trial_days"]), plan_key=args["plan_key"],
        )
    except ProvisioningError as exc:
        raise ToolError("PROVISION_FAILED", "tenant provisioning failed and was rolled back") from exc
    tenant = s.get(Tenant, result.tenant_id)
    customer.tenant_slug = slug
    if args.get("setup_profile") or args.get("advice_ref"):
        from .tenant_setup import build_configuration, apply_configuration
        try:
            action = ({"operation": "advisory", "advice_ref": args["advice_ref"], "advice_version": args["advice_version"]}
                      if args.get("advice_ref") else {"operation": "profile", "profile": args["setup_profile"]})
            configuration = build_configuration(s, customer, action)
            apply_configuration(s, customer, configuration)
        except Exception as exc:
            from services.tenant_provisioning import compensate
            customer.tenant_slug = None
            compensate(s, slug)
            raise ToolError("PROVISION_FAILED", "تعذر ترتيب الحساب الجديد؛ أُلغيت عملية الإنشاء") from exc
    if customer.lead_id and tenant is not None:
        from models.core.leads.models import BusinessLead

        lead = s.get(BusinessLead, customer.lead_id)
        if lead is not None:
            lead.finora_company_id = tenant.id
            lead.trial_started_at = datetime.utcnow()
            lead.trial_ends_at = tenant.subscription_end_date
    # Credentials leave only through ``secret`` (returned once to the approving operator, never persisted).
    return ToolResult(True, {"tenant_slug": slug, "business_type": args["business_type"],
                             "trial_days": int(args["trial_days"])},
                      secret={"tenant_slug": slug, "username": result.username, "password": result.password})


def _grant_discount(s: Session, customer: FcCustomer, args: dict[str, Any]) -> ToolResult:
    pct = int(args["discount_percent"])
    existing = memory.active_facts(s, customer.id, min_confidence=0).get("commitments", {}).get("value") or []
    note = f"خصم {pct}% معتمد من الإدارة"
    memory.remember(s, customer.id, "commitments", (existing + [note])[-10:], confidence=1.0, source="human")
    return ToolResult(True, {"discount_percent": pct})


def _handoff_human(s: Session, customer: FcCustomer, args: dict[str, Any], conversation=None) -> ToolResult:
    if conversation is not None:
        from modules.ai_sales.engine import pause_conversation_for_human

        pause_conversation_for_human(conversation, reason=f"FINORA CORE: {args['reason']}"[:300], indefinite=True)
    return ToolResult(True, {"handed_off": True})


def _configure_tenant(s, customer, args):
    from .tenant_setup import apply_configuration
    return ToolResult(True, apply_configuration(s, customer, args))


def _publish_project_quote(s, customer, args):
    from .project_consultation import apply
    return ToolResult(True, apply(s, customer, args))


def _confirm_project_deposit(s, customer, args):
    from .project_consultation import apply
    return ToolResult(True, apply(s, customer, args, payment=True))


IMPLEMENTATIONS: dict[str, Callable[..., ToolResult]] = {
    "publish_project_quote": _publish_project_quote,
    "confirm_project_deposit": _confirm_project_deposit,
    "create_lead": _create_lead,
    "recommend_plan": _recommend_plan,
    "start_trial": _start_trial,
    "grant_discount": _grant_discount,
    "handoff_human": _handoff_human,
    "configure_tenant": _configure_tenant,
}
# Back-compat views derived from the registry (single source of truth).
RISK = {name: registry.LEGACY_RISK[spec.risk] for name, spec in registry.REGISTRY.items()}
AI_ALLOWED = frozenset(name for name, spec in registry.REGISTRY.items() if spec.agent_executable)
TOOL_TITLES = {name: spec.title for name, spec in registry.REGISTRY.items()}


def authorize(s: Session, name: str, args: dict[str, Any], *, actor_type: str, approval_id: int | None) -> registry.ToolSpec:
    """Final authorization from the registry + policy state. The model's plan is never a source of authority."""
    spec = registry.spec_for(name)
    if spec is None or name not in IMPLEMENTATIONS or not spec.implemented:
        raise ToolError("UNKNOWN_TOOL", name)
    if spec.risk == registry.NEVER_AUTOMATIC:
        raise ToolError("FORBIDDEN", f"{name} is never executed by FINORA CORE")
    if SHADOW_RUN.get() and spec.risk != registry.READ_ONLY:
        raise ToolError("SHADOW_MODE", f"{name} is not executed in Shadow Mode")
    if actor_type == "ai":
        if not spec.agent_executable:
            raise ToolError("PERMISSION", f"{name} requires human approval")
        if spec.flag:
            from .policy import flag

            if flag(s, spec.flag) != "on":
                raise ToolError("PERMISSION", f"{spec.flag} is off")
    elif actor_type == "human":
        if spec.needs_approval:
            from .approvals import approved_plan_matches

            if approval_id is None or not approved_plan_matches(s, approval_id, name, args):
                raise ToolError("APPROVAL_REQUIRED", f"{name} runs only from an approved, unchanged plan")
    else:
        raise ToolError("PERMISSION", "unknown actor type")
    return spec


def run_tool(s: Session, name: str, args: dict[str, Any], *, customer: FcCustomer, actor: str, actor_type: str,
             run_id: int | None = None, approval_id: int | None = None, idempotency_key: str | None = None,
             conversation=None, correlation_id: str | None = None) -> ToolResult:
    if approval_id is not None:
        from .models import FcApproval
        approval = s.get(FcApproval, approval_id)
        if approval is not None and approval.customer_id != customer.id:
            raise ToolError("PERMISSION", "الموافقة تخص عميلاً آخر")
    spec = authorize(s, name, args, actor_type=actor_type, approval_id=approval_id)
    from .channel_roles import ACCOUNT_ACTIONS, PROJECT_ACTIONS, require
    action = "request_discount" if name == "grant_discount" else name
    if action in ACCOUNT_ACTIONS | PROJECT_ACTIONS:
        from .models import FcAgentRun
        run = s.get(FcAgentRun, run_id) if run_id is not None else None
        source = s.get(FcApproval, approval_id) if approval_id is not None else run
        require(s, customer, source.conversation_ref if source is not None else None, action)
    try:
        jsonschema.validate(args, spec.input_schema)
    except jsonschema.ValidationError as exc:
        raise ToolError("INVALID_INPUT", exc.message[:200]) from exc
    if idempotency_key is None and spec.idempotency == registry.PER_CUSTOMER:
        idempotency_key = f"{name}:{customer.id}"
    if idempotency_key is None and spec.idempotency == registry.PER_APPROVAL and approval_id is not None:
        idempotency_key = f"approval:{approval_id}"
    if idempotency_key:
        prior = s.query(FcToolCall).filter_by(idempotency_key=idempotency_key).first()
        if prior is not None:
            from .models import FcApproval, FcAgentRun
            owner = s.get(FcApproval, prior.approval_id) if prior.approval_id else s.get(FcAgentRun, prior.run_id) if prior.run_id else None
            if prior.tool != name or (owner is not None and owner.customer_id != customer.id):
                raise ToolError("PERMISSION", "نتيجة التنفيذ السابق تخص إجراء أو عميلاً آخر")
            if owner is None and not (spec.idempotency == registry.PER_CUSTOMER and idempotency_key == f"{name}:{customer.id}"):
                raise ToolError("PERMISSION", "تعذر التحقق من ملكية التنفيذ السابق")
        if prior is not None and prior.status == "ok":
            if not _same_input(prior.input_summary, _redact_args(args)):
                raise ToolError("INVALID_INPUT", "طلب التنفيذ السابق يختلف عن الطلب الحالي")
            try:
                data = json.loads(prior.result_json or "{}")
                jsonschema.validate(data, spec.output_schema)
            except (jsonschema.ValidationError, ValueError) as exc:
                raise ToolError("INVALID_OUTPUT", "نتيجة التنفيذ السابق غير صالحة") from exc
            if spec.verify is not None and not spec.verify(s, customer, args, data, conversation=conversation):
                raise ToolError("VERIFY_FAILED", "نتيجة التنفيذ السابق لم تعد مؤكدة؛ تحتاج مراجعة")
            return ToolResult(True, data, reused=True)
        if prior is not None:  # a failed attempt may be retried under the same key
            prior.idempotency_key = None
            s.flush()
    summary = _redact_args(args)
    call = FcToolCall(run_id=run_id, approval_id=approval_id, tool=name, risk=registry.LEGACY_RISK[spec.risk],
                      risk_class=spec.risk, actor=actor[:120], actor_type=actor_type, input_summary=summary,
                      idempotency_key=idempotency_key)
    s.add(call)
    s.flush()
    try:
        impl = IMPLEMENTATIONS[name]
        # These tools mutate only this Core session. Provisioning, tenant setup and CRM
        # cross stores/commit internally and retain their existing compensation paths.
        atomic = name in {"recommend_plan", "grant_discount", "publish_project_quote", "confirm_project_deposit"}
        with s.begin_nested() if atomic else nullcontext():
            result = impl(s, customer, args, conversation) if name == "handoff_human" else impl(s, customer, args)
            if not isinstance(result, ToolResult) or not result.ok:
                raise ToolError("EXECUTION_FAILED", f"{name} did not report success")
            try:
                jsonschema.validate(result.data, spec.output_schema)
            except jsonschema.ValidationError as exc:
                raise ToolError("INVALID_OUTPUT", exc.message[:200]) from exc
            verified = True if spec.verify is None else bool(spec.verify(s, customer, args, result.data,
                                                                          conversation=conversation))
            call.verified = verified
            if not verified:
                raise ToolError("VERIFY_FAILED", f"{name} post-condition not met")
    except Exception as exc:
        if not isinstance(exc, ToolError):
            if not atomic:
                raise  # Cross-store tools own their compensation/error contract.
            exc = ToolError("EXECUTION_FAILED", f"{name} failed; its Core changes were rolled back")
        call.verified = False
        call.status, call.error, call.finished_at = "failed", f"{exc.code}: {exc}"[:500], datetime.utcnow()
        audit(s, actor=actor, actor_type=actor_type, category="errors", action=f"tool.{name}",
              title=f"فشل تنفيذ {name}", customer=customer.display_name, input_summary=str(exc)[:200], result="failed",
              correlation_id=correlation_id)
        raise exc
    call.status = "ok"
    call.result_json = json.dumps(result.data, ensure_ascii=False)
    call.finished_at = datetime.utcnow()
    audit(s, actor=actor, actor_type=actor_type, category="finora", action=f"tool.{name}", title=spec.title,
          customer=customer.display_name, input_summary=_safe_summary(result.data, spec.audit_fields),
          correlation_id=correlation_id or new_correlation_id())
    return result


_SENSITIVE_ARG = re.compile(r"pass|secret|token|phone|email", re.I)


def _same_input(before, after):
    try:
        return json.loads(before) == json.loads(after)
    except (ValueError, TypeError):
        return before == after  # Legacy bounded summaries can be truncated JSON.


def _redact_args(args: dict[str, Any]) -> str:
    return json.dumps({k: ("[redacted]" if _SENSITIVE_ARG.search(k) and v else v) for k, v in args.items()},
                      ensure_ascii=False)[:500]


def _safe_summary(data: dict[str, Any], fields: tuple[str, ...] = ()) -> str:
    return ", ".join(f"{k}={v}" for k, v in data.items()
                     if (not fields or k in fields) and not re.search(r"pass|secret|token", k, re.I))[:300]
