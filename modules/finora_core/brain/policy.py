"""Policy engine (spec §23, §70): registry risk classes + feature flags. Plans propose; policy decides what may run."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ..store import get_setting

# Feature flags (fc_settings). Values are strings; defaults are the safe ones.
FLAGS = {
    "AI_SHADOW_MODE": "off",             # on | off — on: think + propose for every message, never send or execute
    "AI_AUTO_REPLY": "on",               # on | off — off: FINORA CORE stores messages but never answers
    "AI_AUTO_LEAD": "on",                # on | off — create / update CRM leads automatically (low risk)
    "AI_ACCOUNT_CREATION": "approval",   # approval | off — trial accounts always need a human approval
    "AI_TENANT_CONFIGURATION": "approval",    # approval | off — bound customer only
    "AI_AUTOMATIC_ONBOARDING": "on",     # on | off — onboarding checklist + training answers
    "AGENT_DISCOUNT_LIMIT": "0",         # percent the agent may promise without approval (it never applies billing)
}

def _legacy_risks() -> dict[str, str]:
    from . import registry

    return {action: registry.LEGACY_RISK[registry.REGISTRY[tool].risk] for action, tool in registry.ACTION_TOOL.items()}


RISK = _legacy_risks()  # back-compat view; the registry is the source of truth


def flag(s: Session, name: str) -> str:
    return (get_setting(s, f"flag:{name}", FLAGS[name]) or FLAGS[name]).strip().lower()


def all_flags(s: Session) -> dict[str, str]:
    return {name: flag(s, name) for name in FLAGS}


@dataclass
class Decision:
    action: dict[str, Any]
    verdict: str  # execute | approval | ask | reject
    risk: str  # legacy short risk (low | medium | high)
    note: str = ""
    risk_class: str = "NEVER_AUTOMATIC"
    tool: str | None = None

    def trace(self) -> dict[str, Any]:
        return {"action": self.action.get("type"), "tool": self.tool, "riskClass": self.risk_class,
                "verdict": self.verdict, "note": self.note}


def decide(s: Session, action: dict[str, Any], *, facts: dict[str, Any]) -> Decision:
    """Final authorization of one proposed action. Inputs from the model are only the action type + arguments; the
    risk class, permission and approval requirement come from the registry and the flags, never from the model."""
    from . import registry

    kind = action.get("type")
    spec = registry.tool_for_action(kind if isinstance(kind, str) else None)
    if spec is None:
        return Decision(action, "reject", "high", "not a FINORA action")
    base = {"risk_class": spec.risk, "tool": spec.name}
    legacy = registry.LEGACY_RISK[spec.risk]
    if spec.risk == registry.NEVER_AUTOMATIC or not spec.implemented:
        return Decision(action, "reject", legacy, "never automatic", **base)
    if spec.agent_executable:
        if spec.flag and flag(s, spec.flag) != "on":
            return Decision(action, "reject", legacy, f"{spec.flag} off", **base)
        return Decision(action, "execute", legacy, **base)
    if kind == "start_trial":
        if flag(s, "AI_ACCOUNT_CREATION") == "off":
            return Decision(action, "reject", legacy, "AI_ACCOUNT_CREATION off", **base)
        missing = [k for k in ("businessType",) if k not in facts and not (action.get("advice_ref") and action.get("advice_version"))]
        if "phone" not in facts and "email" not in facts:
            missing.append("phone")
        if missing:
            return Decision(action, "ask", legacy, ",".join(missing), **base)
        return Decision(action, "approval", legacy, "trial accounts require human approval", **base)
    if kind == "request_discount":
        pct = action.get("discount_percent")
        limit = int(flag(s, "AGENT_DISCOUNT_LIMIT") or 0)
        if pct is None:
            return Decision(action, "ask", legacy, "discount_percent", **base)
        # Even within the limit no billing change is executed by the agent; a human approves every discount.
        return Decision(action, "approval", legacy, f"agent limit {limit}%", **base)
    if kind == "configure_tenant" and flag(s, "AI_TENANT_CONFIGURATION") == "off":
        return Decision(action, "reject", legacy, "AI_TENANT_CONFIGURATION off", **base)
    if spec.needs_approval:
        return Decision(action, "approval", legacy, "approval required", **base)
    return Decision(action, "reject", legacy, "no rule", **base)
