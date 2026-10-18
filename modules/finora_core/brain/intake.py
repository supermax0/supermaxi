"""Conversation-scoped consent and missing details for reviewed account requests."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from ..store import get_setting, set_setting
from .extract import normalize
from .models import FcConversationCustomer
from .tenant_setup import digest, error


def _key(s, customer, ref):
    link = s.get(FcConversationCustomer, str(ref))
    if not link or link.customer_id != customer.id:
        raise error("INTAKE_SCOPE", "طلب الحساب لازم يكون من محادثة العميل نفسه")
    return f"intake:{customer.id}:{digest(str(ref))[:24]}"


def load(s, customer, ref):
    raw = get_setting(s, _key(s, customer, ref))
    data = json.loads(raw) if raw else None
    if not isinstance(data, dict) or data.get("expires", 0) < datetime.now(timezone.utc).timestamp():
        return None
    return data


def save(s, customer, ref, data):
    set_setting(s, _key(s, customer, ref), json.dumps(data, ensure_ascii=False), "FINORA CORE")
    s.flush()


def finish(s, customer, ref):
    save(s, customer, ref, None)


def prepare(s, customer, ref, text, extraction, plan, facts, pending, *, message_id):
    """Remember explicit consent, accept details, and ask one missing field before requesting approval."""
    value = normalize(text)
    canceled = bool(re.search(r"(?:لا|ما|مو)\s+(?:تسوي|تسوولي|تسويلي|تجهز|تفتح|اريد)|الغ[ياء]?\s+(?:ال)?(?:حساب|طلب)", value))
    action = next((a for a in plan.actions if a["type"] == "start_trial"), None)
    if canceled and (pending or action):
        finish(s, customer, ref)
        plan.actions = [a for a in plan.actions if a["type"] != "start_trial"]
        plan.needs_human, plan.handoff_reason = False, None
        plan.reply_text = "وقفت تجهيز طلب الحساب من هالمحادثة. من تحب تكمل، گلي."
        return
    if customer.tenant_slug or {"human_request", "complaint", "technical_support", "pricing", "training_request"} & extraction.intents.keys():
        return
    if plan.needs_human:
        return
    answered = bool(extraction.facts or extraction.phones or extraction.emails)
    if action is None and "account_creation" in extraction.intents and re.search(r"(?:سويلي|سوولي|افتح|جهز|انشاء|اريد)\s+(?:لي\s+)?حساب", value):
        action = {"type": "start_trial", "reason": "customer explicitly requested an account", "plan_key": None, "discount_percent": None}
    if action and "account_creation" not in extraction.intents:
        # A model action alone is not customer consent. Continuation comes from this conversation's saved request.
        plan.actions = [a for a in plan.actions if a["type"] != "start_trial"]
        action = None
    if action is None and pending and answered:
        action = pending["action"]
    if action is None:
        return
    # Only deterministic explicit facts and remembered customer evidence fill the request.
    values = {key: row["value"] for key, row in facts.items()}
    values.update(extraction.facts)
    if extraction.phones:
        values["phone"] = extraction.phones[0]
    if extraction.emails:
        values["email"] = extraction.emails[0]
    missing = next((key for key in ("businessType", "businessName", "phone")
                    if not values.get(key) and not (key == "businessType" and action.get("advice_ref"))
                    and not (key == "phone" and values.get("email"))), None)
    data = {"action": action, "waiting": missing, "request_message_id": (pending or {}).get("request_message_id", str(message_id)),
            "expires": (pending or {}).get("expires", datetime.now(timezone.utc).timestamp() + 86400)}
    save(s, customer, ref, data)
    plan.actions = [a for a in plan.actions if a["type"] not in {"start_trial", "handoff_human"}]
    plan.needs_human, plan.handoff_reason = False, None
    if missing:
        questions = {"businessType": "حتى أجهز طلب الحساب، شنو نوع نشاطك؟",
                     "businessName": "شنو اسم العيادة أو النشاط اللي تريد نسجّل الحساب باسمه؟",
                     "phone": "حتى أرسل طلب حسابك للمراجعة، شنو رقم هاتفك أو بريدك الإلكتروني؟"}
        english = {"businessType": "What kind of business is this account for?",
                   "businessName": "What business name should we use for your account?",
                   "phone": "What phone number or email should we use for your account request?"}
        plan.reply_text = (english if plan.language == "en" else questions)[missing]
    else:
        plan.actions.append(action)
        plan.reply_text = ("Your details are complete; I'll submit the account request for FINORA review."
                           if plan.language == "en" else "بياناتك اكتملت؛ راح أرسل طلب حسابك لمراجعة مشرف فينورا.")
