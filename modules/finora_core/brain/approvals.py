"""Approval engine (spec §24 + Phase 9 / Priority 5): restricted actions execute only from an approved, immutable plan.

- ``request`` builds the exact action plan (tool + arguments + a human-readable preview) from the current state and
  stores it with ``plan_hash`` = HMAC-SHA256(server secret, canonical plan) and a ``plan_version``.
- If the plan changes while it is pending (new facts, another business type…), the old approval is ``superseded``
  and a new version is created — an approval only ever authorizes the plan the operator saw.
- ``decide`` requires the operator to quote the hash they reviewed, re-verifies the stored plan against its HMAC
  (tampered rows are refused), re-builds the plan from current state and refuses if it changed, and then executes
  exactly the stored arguments. Decided approvals can never be decided again (no replay).
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from flask import current_app
from sqlalchemy.orm import Session

from ..store import audit, emit, iso
from . import memory, registry
from .models import FcApproval, FcCustomer
from .tools import TENANT_BUSINESS_TYPE, TRIAL_DAYS, ToolError, ToolResult, move_stage, run_tool

APPROVAL_TOOL = {"start_trial": "start_trial", "request_discount": "grant_discount", "configure_tenant": "configure_tenant"}
TITLES = {"start_trial": "إنشاء حساب FINORA تجريبي", "request_discount": "خصم على الاشتراك", "configure_tenant": "ترتيب حساب العميل وصلاحياته"}
APPROVAL_TOOL.update({key: key for key in ("publish_project_quote", "confirm_project_deposit")})
TITLES.update({"publish_project_quote": "اعتماد خطة وعرض تطوير مخصص", "confirm_project_deposit": "التحقق من وصول عربون 20٪"})
TRIAL_PLAN_KEY = "basic"  # same default plan as Super Admin → create tenant


# ───────────────────────────── plans ─────────────────────────────


def _canonical(plan: dict[str, Any]) -> str:
    return json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def plan_hash(plan: dict[str, Any]) -> str:
    key = (current_app.config.get("SECRET_KEY") or "").encode() or b"finora-core-dev"
    return hmac.new(key, ("finora-core-plan:" + _canonical(plan)).encode(), hashlib.sha256).hexdigest()


def _modules_for(business_type: str, profile: str | None = None, feature_overrides=None) -> list[dict[str, Any]]:
    """Modules a new tenant of this type gets by default — read from the real feature catalogue, not invented."""
    from utils.tenant_feature_flags import TENANT_FEATURE_GROUPS, default_feature_enabled

    out = []
    from .tenant_setup import profile_features
    overrides = feature_overrides if feature_overrides is not None else profile_features(profile) if profile else {}
    from utils.plan_limits import get_plan
    available = get_plan(TRIAL_PLAN_KEY).get("features", {})
    for group in TENANT_FEATURE_GROUPS:
        enabled = [k for k, _ in group["features"] if available.get(k, True) and overrides.get(k, default_feature_enabled(k, business_type=business_type))]
        if enabled:
            out.append({"key": group["key"], "label": group["label"], "enabled": len(enabled),
                        "total": len(group["features"])})
    return out


def _plan_row(s: Session, plan_key: str) -> dict[str, Any]:
    from models.core.subscription_plan import SubscriptionPlan

    row = s.query(SubscriptionPlan).filter_by(plan_key=plan_key).first()
    return {"key": plan_key, "name": row.name if row else plan_key,
            "priceMonthly": int(row.price_monthly) if row and row.price_monthly is not None else None}


def build_plan(s: Session, customer: FcCustomer, action: dict[str, Any], agent_limit: str | None = None) -> dict[str, Any]:
    """The exact, reviewable action plan for a restricted action (no secrets, no raw contact data in the preview)."""
    from routes.superadmin import BUSINESS_TYPES

    kind = action["type"]
    facts = memory.active_facts(s, customer.id)
    value = lambda key: (facts.get(key) or {}).get("value")  # noqa: E731
    if kind in {"publish_project_quote", "confirm_project_deposit"}:
        from . import project_consultation as project
        args = project.approval_args(s, customer, action)
        draft = project.load(s, customer, args["conversation_ref"])
        preview = {"customer": {"id": customer.id, "name": customer.display_name}, "project": project.dto(draft),
                   "projectAction": kind, "depositAmount": project.deposit(draft["terms"])}
    elif kind == "start_trial":
        tenant_type = TENANT_BUSINESS_TYPE.get(value("businessType"), "general")
        setup_profile = ({"clinics": "dental_clinic" if value("specialty") == "dentistry" else "clinic", "wholesale": "wholesale", "food_wholesale_retail": "grocery"}.get(tenant_type)
                         or ("flowers" if value("businessProfile") == "flowers" else tenant_type if tenant_type in {"general", "starter_business", "beauty_center", "hr_management"} else None))
        advice = None
        if action.get("advice_ref"):
            from .setup_advisor import recommendation
            advice = recommendation(s, customer, action["advice_ref"], expected=action.get("advice_version"))
            tenant_type, setup_profile = advice["business_type"], None
        args = {
            "setup_profile": setup_profile,
            "business_type": tenant_type,
            "business_name": (value("businessName") or customer.display_name)[:150],
            "contact_name": value("contactName"),
            "phone": value("phone"),
            "email": value("email"),
            "plan_key": TRIAL_PLAN_KEY,
            "trial_days": TRIAL_DAYS,
            **({"advice_ref": str(action["advice_ref"]), "advice_version": advice["version"]} if advice else {}),
        }
        from .tenant_setup import profile_features
        from utils.tenant_feature_flags import TENANT_FEATURE_LABELS
        from utils.plan_limits import get_plan
        available = get_plan(TRIAL_PLAN_KEY).get("features", {})
        unavailable = [{"key": key, "label": TENANT_FEATURE_LABELS[key]} for key, enabled in (profile_features(setup_profile) if setup_profile else {}).items() if enabled and not available.get(key, True)]
        if advice:
            unavailable = advice["unavailable"]
        preview = {
            "unavailableFeatures": unavailable,
            "customer": {"id": customer.id, "name": customer.display_name},
            "businessType": {"key": tenant_type, "label": BUSINESS_TYPES.get(tenant_type, tenant_type)},
            "specialty": value("specialty"),
            "plan": _plan_row(s, TRIAL_PLAN_KEY),
            "size": {"doctors": value("doctors"), "employees": value("employees"), "branches": value("branches")},
            "modules": _modules_for(tenant_type, setup_profile, advice["updates"] if advice else None),
            "tenantActions": [
                {"action": "create_tenant", "label": f"إنشاء شركة جديدة «{args['business_name']}»"},
                {"action": "init_database", "label": "تهيئة قاعدة بيانات الشركة"},
                {"action": "link_customer", "label": "ربط الحساب بملف العميل وعميل CRM"},
            ],
            "users": [{"username": "admin", "role": "admin", "credentials": "كلمة مرور مؤقتة تُعرض مرة واحدة للموافِق",
                       "mustChangePassword": True}],
            "subscription": {"change": "trial", "trialDays": TRIAL_DAYS, "billing": "لا توجد فوترة أثناء التجربة"},
            "contact": {"phone": bool(args["phone"]), "email": bool(args["email"])},  # presence only
        }
        if advice:
            preview["tenantActions"] += [{"action": "configure_tenant", "label": "تجهيز مخصص: " + advice["activity"]}]
            preview["tenantActions"] += [{"action": "recommend_feature", "label": row["label"] + " — " + row["reason"]} for row in advice["recommendations"] if row["available"]]
    elif kind == "request_discount":
        pct = int(action["discount_percent"])
        args = {"discount_percent": pct}
        preview = {
            "customer": {"id": customer.id, "name": customer.display_name},
            "discount": {"percent": pct, "agentLimit": agent_limit},
            "subscription": {"change": "commitment_only", "billing": "لا يتغير الاشتراك أو الفوترة تلقائياً"},
            "plan": {"name": value("recommendedPlan")},
        }
    elif kind == "configure_tenant":
        from .tenant_setup import build_configuration
        args = build_configuration(s, customer, action)
        preview = {"customer": {"id": customer.id, "name": customer.display_name},
                   "accountScope": {"tenantSlug": args["tenant_slug"], "label": "هذا الحساب فقط؛ بقية الشركات لا تتغير"},
                   "changes": args["changes"], "permissionChanges": args["permission_updates"], "employeeId": args["employee_id"], "roleIds": args["role_ids"],
                   "employeeName": args["employee_name"], "permissionDiff": args["permission_changes"], "roleChanges": args["role_changes"],
                   "unavailableFeatures": args["unavailable_features"],
                   "businessTypeChange": args["business_change"],
                   "tenantActions": [{"action": "configure_tenant", "label": args["title"]}],
                   "subscription": {"change": "configuration_only", "billing": "لا تغيير على الاشتراك أو الفوترة"}}
    else:
        raise ToolError("UNKNOWN_ACTION", str(kind))
    spec = registry.REGISTRY[APPROVAL_TOOL[kind]]
    return {"kind": kind, "tool": spec.name, "risk": spec.risk, "customerId": customer.id, "args": args,
            "preview": preview}


def approval_dto(a: FcApproval, customer_name: str) -> dict[str, Any]:
    plan = json.loads(a.plan_json) if a.plan_json else None
    return {
        "id": str(a.id),
        "conversationId": a.conversation_ref,
        "customerName": customer_name,
        "action": a.title,
        "reason": a.reason,
        "oldValue": a.old_value,
        "newValue": a.new_value,
        "agentLimit": a.agent_limit,
        "risk": a.risk,
        "riskClass": a.risk_class,
        "status": a.status if a.status in {"pending", "approved", "rejected", "superseded"} else (
            "approved" if a.status == "executed" else "rejected"),
        "planHash": a.plan_hash,
        "planVersion": a.plan_version,
        "preview": plan["preview"] if plan else None,
        "createdAt": iso(a.created_at),
    }


def request(s: Session, *, customer: FcCustomer, conversation_ref: str, run_id: int | None, action: dict[str, Any],
            risk: str, agent_limit: str | None) -> FcApproval:
    """Idempotent per (customer, action, plan): an identical pending plan is reused; a changed plan supersedes it."""
    kind = action["type"]
    from .channel_roles import require
    require(s, customer, conversation_ref, kind)
    plan = build_plan(s, customer, action, agent_limit)
    digest = plan_hash(plan)
    pending_query = s.query(FcApproval).filter_by(customer_id=customer.id, action=kind, status="pending")
    if kind in {"publish_project_quote", "confirm_project_deposit"}:
        pending_query = pending_query.filter_by(conversation_ref=conversation_ref)
    existing = pending_query.first()
    if existing is not None and existing.plan_hash == digest:
        try:
            require(s, customer, existing.conversation_ref, kind)
        except ToolError as exc:
            if exc.code not in {"CHANNEL_ROLE", "CHANNEL_SCOPE"}:
                raise
            # An old request from a retired channel must not block a valid new request.
        else:
            return existing
    version = 1
    if existing is not None:
        version = (existing.plan_version or 1) + 1
    if kind in {"publish_project_quote", "confirm_project_deposit"}:
        terms = plan["preview"]["project"]["terms"]
        old, new = "غير معتمد", f"{terms['amount']:,} {terms['currency']} · {terms['days']} يوم · عربون 20٪"
    elif kind == "start_trial":
        old, new = None, f"حساب تجريبي {TRIAL_DAYS} يوم"
    elif kind == "configure_tenant":
        old, new = "إعدادات الحساب الحالية", plan["args"]["title"]
    else:
        pct = int(action["discount_percent"])
        old, new = "0%", f"{pct}%"
    spec = registry.REGISTRY[APPROVAL_TOOL[kind]]
    approval = FcApproval(customer_id=customer.id, conversation_ref=conversation_ref, run_id=run_id, action=kind,
                          args_json=json.dumps(plan["args"], ensure_ascii=False), title=TITLES[kind],
                          reason=(action.get("reason") or "")[:500] or TITLES[kind], old_value=old, new_value=new,
                          agent_limit=agent_limit, risk=risk, risk_class=spec.risk, plan_json=_canonical(plan),
                          plan_hash=digest, plan_version=version, status="pending")
    s.add(approval)
    s.flush()
    if existing is not None:
        existing.status, existing.superseded_by_id = "superseded", approval.id
        existing.decided_at, existing.decided_by = datetime.utcnow(), "FINORA CORE (plan changed)"
        emit(s, "approval.resolved", {"approval": approval_dto(existing, customer.display_name)})
    audit(s, actor="FINORA CORE", actor_type="ai", category="approvals", action="approval.requested",
          title="طلب موافقة" if existing is None else "تحديث خطة الموافقة", customer=customer.display_name,
          input_summary=f"{TITLES[kind]}: {new} (v{version})", result="pending", conversation_ref=conversation_ref)
    emit(s, "approval.required", {"approval": approval_dto(approval, customer.display_name)})
    if plan["preview"].get("unavailableFeatures"):
        from .support import report
        report(s, customer, conversation_ref, kind="missing_feature", details="أقسام النشاط خارج باقة العميل: " + "، ".join(row["label"] for row in plan["preview"]["unavailableFeatures"]), source=f"approval:{approval.id}", verified=True)
    return approval


def _stored_plan(approval: FcApproval) -> dict[str, Any]:
    if not approval.plan_json or not approval.plan_hash:
        raise ToolError("PLAN_MISSING", "طلب الموافقة لا يحتوي خطة قابلة للتحقق")
    plan = json.loads(approval.plan_json)
    if not hmac.compare_digest(plan_hash(plan), approval.plan_hash):
        raise ToolError("PLAN_TAMPERED", "خطة الموافقة لا تطابق توقيعها")
    return plan


def approved_plan_matches(s: Session, approval_id: int, tool: str, args: dict[str, Any]) -> bool:
    """Executor-side check: the tool call is exactly the approved, signed plan."""
    approval = s.get(FcApproval, approval_id)
    if approval is None or approval.status != "approved":
        return False
    try:
        plan = _stored_plan(approval)
    except ToolError:
        return False
    return plan["tool"] == tool and _canonical(plan["args"]) == _canonical(args)


# ───────────────────────────── decisions ─────────────────────────────


@dataclass
class DecisionOutcome:
    approval: FcApproval
    customer: FcCustomer
    result: ToolResult | None


def decide(s: Session, approval: FcApproval, decision: str, *, actor: str, plan_hash_seen: str | None = None,
           operator_permissions: frozenset[str] | None = None) -> DecisionOutcome:
    if approval.status != "pending":
        raise ToolError("CONFLICT", "تم البت في هذا الطلب مسبقاً")
    customer = s.get(FcCustomer, approval.customer_id)
    result: ToolResult | None = None
    if decision == "approved":
        from .channel_roles import require
        require(s, customer, approval.conversation_ref, approval.action)
        plan = _stored_plan(approval)
        if not plan_hash_seen or not hmac.compare_digest(plan_hash_seen, approval.plan_hash):
            raise ToolError("PLAN_MISMATCH", "الخطة التي راجعتها ليست الخطة الحالية — حدّث وراجع من جديد")
        spec = registry.REGISTRY[plan["tool"]]
        if operator_permissions is not None and spec.permission not in operator_permissions:
            raise ToolError("PERMISSION", "صلاحياتك لا تسمح بتنفيذ هذا الإجراء")
        if approval.action == "confirm_project_deposit" and not plan["args"].get("payment_reference"):
            raise ToolError("PAYMENT_UNVERIFIED", "سجّل مرجع الدفعة بعد التحقق من وصول العربون قبل الموافقة")
        current = build_plan(s, customer, {"type": approval.action, **(
            {"discount_percent": plan["args"]["discount_percent"]} if approval.action == "request_discount" else plan["args"] if approval.action in {"configure_tenant", "publish_project_quote", "confirm_project_deposit"} else {key: plan["args"][key] for key in ("advice_ref", "advice_version") if key in plan["args"]})},
            approval.agent_limit)
        if plan_hash(current) != approval.plan_hash:
            # The world changed after the plan was shown: this approval must not authorize the new plan.
            replacement = request(s, customer=customer, conversation_ref=approval.conversation_ref,
                                  run_id=approval.run_id, action={"type": approval.action, "reason": approval.reason,
                                                                  **plan["args"]},
                                  risk=approval.risk, agent_limit=approval.agent_limit)
            raise ToolError("PLAN_CHANGED", f"تغيّرت الخطة — راجع النسخة {replacement.plan_version}")
    approval.decided_by = actor
    approval.decided_at = datetime.utcnow()
    if decision == "rejected":
        approval.status = "rejected"
    else:
        approval.status = "approved"
        s.flush()
        try:
            result = run_tool(s, plan["tool"], plan["args"], customer=customer, actor=actor, actor_type="human",
                              approval_id=approval.id, idempotency_key=f"approval:{approval.id}")
        except ToolError as exc:
            approval.status = "failed"
            approval.result_summary = f"{exc.code}: {exc}"[:500]
            raise
        approval.status = "executed"
        approval.result_summary = ", ".join(f"{k}={v}" for k, v in result.data.items())[:500]
        if approval.action == "start_trial":
            move_stage(s, customer, "account_created", actor=actor, actor_type="human", reason="trial approved")
            from .onboarding import refresh

            refresh(s, customer)
    audit(s, actor=actor, actor_type="human", category="approvals", action=f"approval.{decision}",
          title="تمت الموافقة" if decision == "approved" else "تم الرفض", customer=customer.display_name,
          input_summary=f"{approval.title} (v{approval.plan_version})", conversation_ref=approval.conversation_ref,
          approval_id=str(approval.id))
    emit(s, "approval.resolved", {"approval": approval_dto(approval, customer.display_name)})
    return DecisionOutcome(approval, customer, result)
