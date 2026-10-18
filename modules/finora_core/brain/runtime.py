"""FINORA CORE brain runtime: one run per claimed inbound burst in the house tenant (spec §17 pipeline).

Called by ``ai_sales.engine.process_inbound_message`` AFTER the existing Meta pipeline has deduplicated, ordered and
atomically claimed the messages and AFTER the kill switch / takeover checks. Runs inside the house-tenant context
(``g.tenant``); FINORA CORE state lives in the Core DB (explicit ``core_session``).

Pipeline: resolve customer → memory → extract + intents → knowledge → plan (model, else rules) → verify → policy →
tools / approvals → onboarding → response safety → send → audit.

Shadow Mode (``mode="shadow"``, Phase 9): the same pipeline up to the plan + policy verdicts, then the proposal is
stored for operators — nothing is sent, no tool runs, no approval is created, no lead stage moves. Only safe memory
(customer facts, identities, merge *suggestions*) is updated.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import Any

from flask import current_app

from extensions import db

from ..store import audit, core_session, emit, iso, msg_ref, new_correlation_id
from . import approvals, memory, onboarding, policy
from .customers import attach_contact, resolve_for_conversation
from .extract import extract
from .knowledge import all_items, plan_prices, retrieve, retrieval_query
from .models import FcAgentRun, FcCustomer, FcShadowProposal
from .observability import estimate_cost, knowledge_version, redact
from .planner import PROMPT_VERSION, Plan, build_user_payload, plan_with_model, plan_with_rules, verify_plan
from .provider import ProviderError, RequestProvider, get_provider
from .tools import SHADOW_RUN, ToolError, move_stage, run_tool

logger = logging.getLogger(__name__)

RUN_TIMEOUT_SECONDS = 75.0  # bounded interpretation + response; newer-message/takeover guards still apply
PROJECT_TIMEOUT_SECONDS = 210.0
WORKING_LABELS = {
    "reading": None,
    "thinking": "يحلل احتياج العميل",
    "searching": "يبحث في معرفة FINORA",
    "executing": "ينفذ الإجراء",
    "replying": "يجهز الرد",
}


def _status(s, state: str, conversation, label: str | None = None) -> None:
    from ..conversations import channel_of
    channel = channel_of(conversation)
    emit(s, "agent.status", {"status": {"state": state, "label": label if label is not None else WORKING_LABELS.get(state),
                                        "conversationId": str(conversation.id), "channel": channel}})
    s.commit()


def _recent(conversation, limit: int = 12) -> list[dict[str, str]]:
    from modules.ai_sales.models import AISalesMessage

    rows = (
        AISalesMessage.query.filter(AISalesMessage.conversation_id == conversation.id)
        .order_by(AISalesMessage.created_at.desc(), AISalesMessage.id.desc())
        .limit(limit)
        .all()
    )
    out = []
    for m in reversed(rows):
        text = (m.text_content or m.transcription or "").strip()
        if text:
            # Keep the question/confirmation at the end of long replies as well as their opening context.
            excerpt = text if len(text) <= 600 else text[:400] + "\n…\n" + text[-200:]
            out.append({"role": "customer" if m.direction == "inbound" else "finora", "text": excerpt, "messageId": str(m.id)})
    return out


def _fact_value(key: str, raw: Any) -> Any:
    if key in {"doctors", "employees", "branches"}:
        return int(raw)
    if key in {"interests", "pendingQuestions", "commitments"}:
        return raw if isinstance(raw, list) else [str(raw)]
    return str(raw).strip()


def _top_confidence(intents: list[dict[str, Any]]) -> float | None:
    values = [float(i.get("confidence") or 0) for i in intents or []]
    return round(max(values), 3) if values else None


def handle_house_message(inbound, burst: list, *, send_external: bool = True, mode: str = "live"):
    if mode == "shadow":
        token = SHADOW_RUN.set(True)
        try:
            return _run(inbound, burst, send_external=False, shadow=True)
        finally:
            SHADOW_RUN.reset(token)
    return _run(inbound, burst, send_external=send_external, shadow=False)


def _run(inbound, burst: list, *, send_external: bool, shadow: bool):
    conversation = inbound.conversation
    from . import channel_roles
    channel = conversation.channel.channel_type
    accounts_enabled = channel in channel_roles.SOCIAL_CHANNELS
    projects_enabled = channel == "telegram"
    started = time.monotonic()
    correlation = new_correlation_id()
    customer_text = "\n".join((m.text_content or m.transcription or "").strip() for m in burst if m.direction == "inbound")
    customer_text = customer_text.strip()
    newest = max(burst, key=lambda m: m.id)
    newest_burst_id = newest.id
    trigger_ref = f"shadow:{msg_ref(newest.id, iso(newest.created_at))}"
    handed_off = False
    training_given = False
    trace: dict[str, Any] = {"proposedActions": [], "policy": [], "executedTools": [], "approvals": [], "guards": []}

    with core_session() as s:
        if shadow:
            if s.query(FcShadowProposal.id).filter_by(trigger_ref=trigger_ref).first() is not None:
                return None  # this burst already has a proposal (re-dispatch)
        elif policy.flag(s, "AI_AUTO_REPLY") != "on":
            for m in burst:
                m.status = "received"  # stored, unanswered, visible to humans
            db.session.commit()
            return None
        from ..media_analysis import inbound_context
        from ..store import house_slug
        media_observations, media_incomplete = inbound_context(burst, house_slug())
        # Media decoding has its own bounded deadlines. Keep the text/tool budget independent.
        reply_started = time.monotonic()
        from ..conversations import message_dto
        for message in burst:
            if message.get_media_metadata().get("attachments"):
                emit(s, "message.updated", {"message": message_dto(message)})
        customer_text = "\n".join((m.text_content or m.transcription or "").strip() for m in burst if m.direction == "inbound").strip()
        customer = resolve_for_conversation(
            s, conversation_ref=str(conversation.id), channel_type=conversation.channel.channel_type,
            contact_id=conversation.external_contact_id, display_name=conversation.contact_name or "عميل",
        )
        run = FcAgentRun(conversation_ref=str(conversation.id), customer_id=customer.id, trigger_message_id=inbound.id,
                         prompt_version=PROMPT_VERSION, correlation_id=correlation, mode="shadow" if shadow else "live",
                         knowledge_version=knowledge_version(s))
        s.add(run)
        _status(s, "reading", conversation)

        # identifiers + memory (every fact keeps the message it came from and when the customer said it)
        evidence = {"source_message_id": str(inbound.id), "observed_at": inbound.created_at}
        from . import intake
        pending_intake = intake.load(s, customer, str(conversation.id)) if accounts_enabled else None
        extraction = extract(customer_text, waiting=(pending_intake or {}).get("waiting"))
        for phone in extraction.phones:
            attach_contact(s, customer, kind="phone", value=phone, source=f"message:{inbound.id}")
            memory.remember(s, customer.id, "phone", phone, confidence=0.95, source="customer_message",
                            source_ref=str(inbound.id), **evidence)
        for email in extraction.emails:
            attach_contact(s, customer, kind="email", value=email, source=f"message:{inbound.id}")
            memory.remember(s, customer.id, "email", email, confidence=0.95, source="customer_message",
                            source_ref=str(inbound.id), **evidence)
        facts_before = memory.active_facts(s, customer.id)

        _status(s, "thinking", conversation)
        btype = extraction.facts.get("businessType") or (facts_before.get("businessType") or {}).get("value")
        tenant_type = _tenant_business_type(customer.tenant_slug)
        from .tools import TENANT_BUSINESS_TYPE

        items = all_items(s, business_type=tenant_type or TENANT_BUSINESS_TYPE.get(btype, "general" if btype else None))
        recent = _recent(conversation)
        media_query = " ".join(f"{item['summary']} {item['details']}" for item in media_observations)[:2000]
        knowledge_query = retrieval_query(customer_text or media_query, recent)
        if knowledge_query != customer_text and not {"human_request", "complaint"} & set(extraction.intents):
            extraction.intents["training_request"] = 0.9
            extraction.intents.pop("unknown", None)
        relevant = retrieve(items, knowledge_query, limit=6)
        if "pricing" in extraction.intents:
            relevant += [i for i in items if i.category == "pricing" and i not in relevant]
        if extraction.facts.get("businessType") or "businessType" in facts_before:
            relevant += [i for i in items if i.id == "vertical:all" and i not in relevant]
        # Scope filtering happens before retrieval, so other verticals cannot consume the result limit.
        prices = plan_prices(s)
        plan_keys = {i.id.split(":", 1)[1] for i in items if i.id.startswith("plan:")}

        _status(s, "searching", conversation)
        plan: Plan | None = None
        from ..settings import apply_reply_policy, read_settings, reply_prompt

        reply_config = read_settings(s)
        from .tenant_setup import inspect_account, propose, missing_profile_request, digest
        from .support import report, FcSupportIssue
        missing_template = missing_profile_request(customer_text) if accounts_enabled and not media_incomplete else None
        if accounts_enabled and not missing_template and not media_incomplete and extraction.facts.get("businessType") in {"commerce", "restaurant", "pharmacy"}:
            missing_template = missing_profile_request(f"نشاطي {customer_text[:160]}")
        if accounts_enabled and not missing_template and not media_incomplete and "account_creation" in extraction.intents and not extraction.facts.get("businessType"):
            pending_template = s.query(FcSupportIssue).filter_by(customer_id=customer.id, conversation_ref=str(conversation.id),
                                                               kind="missing_template", status="open").order_by(FcSupportIssue.id.desc()).first()
            if pending_template and pending_template.details.startswith("النشاط المذكور: "):
                activity = pending_template.details.splitlines()[0].removeprefix("النشاط المذكور: ")
                missing_template = missing_profile_request(f"نشاطي {activity}")
        account_context = None
        if accounts_enabled and customer.tenant_slug:
            try:
                account_context = inspect_account(s, customer)
                account_context.pop("overrides", None)
            except ToolError as exc:
                if not shadow:
                    report(s, customer, str(conversation.id), kind="configuration_error", details=str(exc), source=f"message:{newest.id}", verified=True)
        provider = get_provider()
        if provider is not None:
            provider = RequestProvider(provider)
        from . import project_consultation
        from .planner import detect_language
        from .understanding import analyze
        import jsonschema
        project_draft = (project_consultation.load(s, customer, str(conversation.id)) or project_consultation.pending_context(s, customer, str(conversation.id))) if projects_enabled else None
        if project_draft:
            project_draft = {**project_draft, "pendingRequests": project_consultation.pending_evidence(s, customer, str(conversation.id))}
        understanding, interpretation_usage = None, None
        if customer_text and not media_incomplete:
            if provider is not None and getattr(provider, "supports_understanding", False):
                _status(s, "thinking", conversation, label="يحلل الرسالة ويراجع سياق الحوار")
            try:
                analysis_value = (newest.text_content or newest.transcription or "").strip() if shadow else customer_text
                understanding, interpretation_usage = analyze(provider, value=analysis_value, recent=recent,
                    facts=facts_before, project=project_draft if project_draft and project_draft["phase"] != "cancelled" else None,
                    account=account_context, knowledge=items, media=media_observations)
            except (ProviderError, jsonschema.ValidationError) as exc:
                code = exc.code if isinstance(exc, ProviderError) else "interpretation_schema"
                trace["understanding"] = {"status": "unavailable", "code": code}
                logger.warning("finora_core message interpretation unavailable (%s); original-message guards retained", code)
            if understanding:
                trace["understanding"] = {"status": "ready", **understanding, "model": interpretation_usage.model,
                    "inputCount": interpretation_usage.input_tokens, "outputCount": interpretation_usage.output_tokens}
                search_queries = understanding["searchQueries"] if understanding["confidence"] >= .85 else []
                if search_queries:
                    _status(s, "searching", conversation)
                    semantic_items = retrieve(items, "\n".join(search_queries), limit=8)
                    relevant = semantic_items + [item for item in relevant if item.id not in {k.id for k in semantic_items}]
                    relevant = relevant[:12]
        project_result = None
        project_context = project_consultation.active(s, customer, str(conversation.id), customer_text, understanding=understanding) if projects_enabled and customer_text and not media_incomplete else False
        norm = project_consultation.normalize(customer_text)
        semantic_custom = bool(understanding and understanding.get("topic") == "custom_project" and understanding.get("confidence", 0) >= .85)
        wrong_channel = (accounts_enabled and (semantic_custom or (project_consultation.requested(customer_text)
                         and re.search(r"موقع|تطبيق|منصه|مخصص|من الصفر|برمجه|تطوير|website|web app|mobile app|custom app", norm))))
        wrong_channel = wrong_channel or (projects_enabled and (
            (understanding and understanding.get("topic") == "finora" and understanding.get("confidence", 0) >= .85)
            or ("account_creation" in extraction.intents and not project_context)
            or ("فينورا" in norm and re.search(r"حساب|اشتراك|تجريبي|صلاحيات|اخفي|اظهر", norm))))
        if wrong_channel:
            missing_template = None
            plan = Plan(intents=[{"name": "channel_redirect", "confidence": 1.0}], facts=[], actions=[],
                        reply_text=channel_roles.redirect(channel, detect_language(customer_text)), language=detect_language(customer_text),
                        needs_human=False, handoff_reason=None, cited=[], source="rules", model="channel-roles")
        project_failure = project_context and project_consultation.failure_followup(customer_text, recent)
        blocked_project_intents = {"human_request", "complaint"} if project_failure else {"human_request", "complaint", "technical_support"}
        if projects_enabled and not wrong_channel and customer_text and not media_incomplete and not blocked_project_intents & set(extraction.intents) and ("training_request" not in extraction.intents or project_context):
            project_text = (newest.text_content or newest.transcription or "").strip() if shadow else customer_text
            project_result = project_consultation.consult(s, customer, str(conversation.id), project_text,
                                                        provider=provider, message_id=newest.id, shadow=shadow, recent=recent,
                                                        understanding=understanding)
        # Continue an open-ended project discussion/media review without starting account intake.
        greeting = bool(re.fullmatch(r"مرحبا|هلا|هلو|السلام عليكم|اهلا|سلام|/start(?:@[a-z0-9_]+)?|hi|hello", norm.strip(" .!؟")))
        if projects_enabled and not wrong_channel and not project_result and provider is not None and not media_incomplete and not greeting and not {"human_request", "complaint"} & extraction.intents.keys() and (customer_text or media_observations):
            try:
                advisory_text = customer_text or "راجع المرفق بخصوص فكرة المشروع، واسأل عن الهدف إذا مو واضح."
                if media_observations:
                    advisory_text += "\nUNTRUSTED_MEDIA_OBSERVATIONS: " + json.dumps(media_observations, ensure_ascii=False)
                advice, usage = project_consultation.discuss(provider, project_draft or {"brief": {}, "evidence": []},
                                                            advisory_text, recent=recent, understanding=understanding)
                project_result = {"reply": advice, "action": None, "usage": usage, "model": usage.model}
            except (ProviderError, jsonschema.ValidationError, ValueError, TypeError, KeyError):
                logger.warning("finora_core Telegram project discussion unavailable; safe introduction retained")
        if project_result:
            missing_template = None
            usage = project_result.get("usage")
            plan = Plan(intents=[{"name": "custom_project", "confidence": 1.0}], facts=[],
                        actions=[project_result["action"]] if project_result["action"] else [],
                        reply_text=project_result["reply"], language=detect_language(customer_text), needs_human=False,
                        handoff_reason=None, cited=[], source="model" if usage else "rules", model=project_result["model"],
                        input_tokens=usage.input_tokens if usage else 0, output_tokens=usage.output_tokens if usage else 0)
        literal_profile_answer = set(extraction.intents) == {"unknown"} and bool(extraction.facts or extraction.phones or extraction.emails)
        if accounts_enabled and not wrong_channel and provider is not None and not literal_profile_answer and not project_result:
            try:
                user_payload = build_user_payload(
                    recent=recent, facts=facts_before, lead_stage=customer.lead_stage, knowledge=relevant, current_text=customer_text,
                    policy={"discount_limit_percent": int(policy.flag(s, "AGENT_DISCOUNT_LIMIT") or 0),
                            "account_creation": policy.flag(s, "AI_ACCOUNT_CREATION")},
                    understanding=understanding,
                )
                if media_observations or account_context:
                    payload = json.loads(user_payload)
                    if media_observations:
                        payload["UNTRUSTED_MEDIA_OBSERVATIONS"] = media_observations
                    if account_context:
                        payload["CUSTOMER_ACCOUNT"] = account_context
                    user_payload = json.dumps(payload, ensure_ascii=False)
                plan = plan_with_model(provider, user_payload=user_payload, style_prompt=reply_prompt(reply_config) +
                    "\nCHANNEL_ROLE: Instagram/Facebook is for existing FINORA subscriptions, support and company account setup. Custom website/app development consultation is available only through FINORA's Telegram bot. Redirect those requests; never design a custom project or promise its quote here.")
            except ProviderError as exc:
                logger.warning("finora_core model plan unavailable (%s); rules planner used", exc.code)
                audit(s, actor="FINORA CORE", actor_type="system", category="errors", action="ai.provider_error",
                      title="تعذر الوصول لنموذج الذكاء — استُخدم المخطط الآمن", customer=customer.display_name,
                      input_summary=exc.code, result="failed", correlation_id=correlation)
        if plan is None:
            if projects_enabled:
                wants_human = bool({"human_request", "complaint"} & extraction.intents.keys())
                plan = Plan(intents=[{"name": "custom_project", "confidence": 1.0}], facts=[], actions=[],
                            reply_text=("راح أحوّل المحادثة لفريق فينورا حتى يتابع طلبك." if wants_human else
                                        "وصلني المرفق. شنو تريد نراجعه بخصوص مشروعك؟" if media_observations else
                                        "هلا بيك، هنا نرتّب فكرة موقعك أو تطبيقك ونناقش ميزاته. شنو فكرة المشروع ومنو راح يستخدمه؟"),
                            language="ar-iq", needs_human=wants_human, handoff_reason="طلب العميل متابعة بشرية" if wants_human else None,
                            cited=[], source="rules", model="channel-roles")
            else:
                plan = plan_with_rules(extraction=extraction, text=customer_text, facts=facts_before, knowledge=relevant,
                                       plan_keys=plan_keys, language=reply_config["language"] if reply_config["language"] != "auto" else None)
        own_contacts = {str(facts_before[k]["value"]) for k in ("phone", "email") if k in facts_before}
        # Explicit customer answers must survive provider failures or a model omitting profile fields.
        for key, value in (extraction.facts.items() if accounts_enabled and not wrong_channel and not project_result else []):
            plan.facts = [fact for fact in plan.facts if fact["key"] != key]
            plan.facts.append({"key": key, "value": value, "confidence": 0.9, "evidence": customer_text[:300]})
        if accounts_enabled and not wrong_channel and not project_result:
            plan = verify_plan(plan, customer_text=customer_text, extraction=extraction, knowledge=relevant,
                               plan_prices=prices, plan_keys=plan_keys, allowed_contacts=own_contacts)
            plan = apply_reply_policy(plan, reply_config, extraction)
        plan.facts = [fact for fact in plan.facts if fact["key"] != "businessProfile" or extraction.facts.get("businessProfile") == fact["value"]]
        if any(item["kind"] != "audio" for item in media_observations):
            plan.facts = [fact for fact in plan.facts if extraction.facts.get(fact["key"]) == fact["value"]]
            visual_action_intents = {"start_trial": {"account_creation"}, "request_discount": {"discount_request"},
                                     "create_lead": {"business_setup", "clinic_setup", "commerce_setup"}}
            plan.actions = [action for action in plan.actions if action["type"] not in visual_action_intents
                            or bool(visual_action_intents[action["type"]] & extraction.intents.keys())]
            if not customer_text:
                plan.actions = [action for action in plan.actions if action["type"] == "handoff_human"]
        if media_incomplete:
            plan.needs_human, plan.handoff_reason = True, "المرفق يحتاج مراجعة الفريق"
            plan.actions = []
            plan.reply_text = ("I received your attachment. The FINORA team will review the unclear details."
                               if plan.language == "en" else "وصلني المرفق، راح أخلي فريق فينورا يراجع التفاصيل اللي ما كانت واضحة.")
        setup_request = None
        advisor_result = None
        if accounts_enabled and not wrong_channel and not project_result and customer_text and not media_incomplete and not {"human_request", "complaint", "technical_support", "discount_request"} & set(extraction.intents):
            from .setup_advisor import consult
            # Shadow bursts include older unanswered messages; positional replies belong to the newest question.
            advisor_text = (newest.text_content or newest.transcription or "").strip() if shadow else customer_text
            advisor_result = consult(s, customer, str(conversation.id), advisor_text, activity=missing_template,
                                     state=account_context, shadow=shadow)
            if advisor_result:
                missing_template = advisor_result.get("custom_activity") or missing_template
                plan.actions = [advisor_result["action"]] if advisor_result["action"] else []
                plan.needs_human, plan.handoff_reason = False, None
                plan.reply_text = advisor_result["reply"]
        if accounts_enabled and not wrong_channel and not project_result and customer_text and not media_incomplete:
            if advisor_result:
                setup_request = advisor_result["action"]
            elif account_context:
                setup_request = propose(customer_text, account_context) if not {"human_request", "complaint"} & set(extraction.intents) else None
                if missing_template and setup_request and setup_request.get("operation") == "profile":
                    setup_request = None
                if setup_request:
                    # This grounded request replaces the planner's unknown-feature fallback/handoff.
                    plan.actions = [setup_request]
            elif re.search(r"رتب|جهز|صلاحيات|اخف|اظهر|فع[ّل]*", customer_text):
                if not shadow:
                    report(s, customer, str(conversation.id), kind="account_link", details=customer_text, source=f"message:{newest.id}")
            if not shadow:
                if missing_template:
                    report(s, customer, str(conversation.id), kind="missing_template",
                           details=f"النشاط المذكور: {missing_template}\nطلب إضافة قالب مناسب لهذا النشاط.\nكلام العميل: {customer_text[:1200]}",
                           source=f"template:{conversation.id}:{digest(missing_template)[:32]}")
                if re.search(r"خلل|عطل|خط[اأ]|ما\s*(?:يشتغل|يفتح|يحفظ|يخزن|يظهر)|لا يعمل|متوقف|\b(?:error|broken|crash)\b", customer_text, re.I):
                    report(s, customer, str(conversation.id), kind="bug", details=customer_text, source=f"message:{newest.id}")
                elif re.search(r"ميزة.*(?:ماكو|غير موجود)|خاصية.*غير موجود|ما يدعم", customer_text) or (not advisor_result and not setup_request and any("factual answer without" in note or "no verified instructions" in note for note in plan.guard_notes)):
                    report(s, customer, str(conversation.id), kind="missing_feature", details=customer_text, source=f"message:{newest.id}")
            if missing_template and not advisor_result:
                # An unknown activity must not silently become a generic trial or a different profile.
                plan.actions = [action for action in plan.actions if action["type"] != "start_trial"
                                and not (action["type"] == "configure_tenant" and action.get("operation") == "profile")]
                if not {"human_request", "complaint"} & set(extraction.intents):
                    plan.actions = [action for action in plan.actions if action["type"] != "handoff_human"]
                    plan.needs_human, plan.handoff_reason = False, None
                plan.guard_notes.append("Activity needs a reviewed business template; automatic profile/trial withheld")
        if accounts_enabled and not wrong_channel and not project_result and not media_incomplete and (not missing_template or advisor_result):
            intake_text = (newest.text_content or newest.transcription or "").strip() if shadow else customer_text
            intake_extraction = extract(intake_text, waiting=(pending_intake or {}).get("waiting")) if shadow else extraction
            intake.prepare(s, customer, str(conversation.id), intake_text, intake_extraction, plan,
                           facts_before, pending_intake, message_id=newest.id)
        plan.actions = [action for action in plan.actions if channel_roles.allowed(channel, action["type"])]
        run.model = plan.model
        run.input_tokens = plan.input_tokens + (interpretation_usage.input_tokens if interpretation_usage else 0)
        run.output_tokens = plan.output_tokens + (interpretation_usage.output_tokens if interpretation_usage else 0)
        run.intents_json = json.dumps(plan.intents, ensure_ascii=False)
        run.confidence = _top_confidence(plan.intents)
        trace["proposedActions"] = redact([{k: a.get(k) for k in ("type", "plan_key", "discount_percent", "reason")}
                                           for a in plan.actions])
        trace["guards"] = list(plan.guard_notes)
        trace["cited"] = list(plan.cited)
        if plan.guard_notes:
            audit(s, actor="FINORA CORE", actor_type="system", category="ai", action="ai.guard",
                  title="تصحيح آلي لخطة الرد", customer=customer.display_name,
                  input_summary="; ".join(plan.guard_notes)[:500], correlation_id=correlation)

        # memory updates (safe in both modes: evidence only, never overwrites)
        updated = []
        for f in plan.facts:
            try:
                value = _fact_value(f["key"], f["value"])
            except (TypeError, ValueError):
                continue
            outcome = memory.remember(s, customer.id, f["key"], value, confidence=f["confidence"],
                                      source="customer_message", source_ref=str(inbound.id), **evidence)
            if outcome.outcome in {"created", "superseded"}:
                updated.append(f"{f['key']}={value}")
        if plan.needs_human and plan.handoff_reason:
            pending = (memory.active_facts(s, customer.id, min_confidence=0).get("pendingQuestions") or {}).get("value") or []
            memory.remember(s, customer.id, "pendingQuestions", (pending + [customer_text[:200]])[-10:],
                            confidence=1.0, source="ai_inference", source_ref=str(inbound.id), **evidence)
        if updated:
            audit(s, actor="FINORA CORE", actor_type="ai", category="ai", action="memory.update",
                  title="تحديث ملف العميل", customer=customer.display_name, input_summary=", ".join(updated),
                  correlation_id=correlation)
            emit(s, "customer.updated", {"customerId": str(customer.id)})  # desktop profile refreshes live
        facts = memory.active_facts(s, customer.id)

        # actions → policy (final authority) → tools / approvals
        _status(s, "executing", conversation)
        extra_questions: list[str] = []
        proposed_escalation = bool(plan.needs_human)
        escalation_reason = plan.handoff_reason if plan.needs_human else None

        def execute(name: str, args: dict[str, Any], **kw):
            try:
                result = run_tool(s, name, args, customer=customer, actor="FINORA CORE", actor_type="ai", run_id=run.id,
                                  correlation_id=correlation, **kw)
            except ToolError as exc:
                trace["executedTools"].append({"tool": name, "status": "failed", "error": exc.code})
                raise
            trace["executedTools"].append({"tool": name, "status": "ok", "reused": result.reused, "verified": True})
            return result

        for action in plan.actions:
            decision = policy.decide(s, action, facts=facts)
            trace["policy"].append(decision.trace())
            if (advisor_result or action["type"] == "start_trial") and decision.verdict == "reject":
                plan.reply_text = "اقتراحك محفوظ، لكن طلب التجهيز الآلي متوقف حالياً بإعدادات فينورا. تواصل مع المشرف حتى يراجعه."
            if decision.verdict == "ask" and "phone" in decision.note:
                if advisor_result:
                    plan.reply_text = "اقتراحك محفوظ. حتى أرسل طلب إنشاء الحساب للمراجعة، أحتاج وسيلة تواصل منك."
                extra_questions.append("حتى أجهز الحساب، شنو رقم هاتفك؟" if plan.language != "en"
                                       else "To prepare your account, what's your phone number?")
            agent_limit = f"{policy.flag(s, 'AGENT_DISCOUNT_LIMIT')}%" if action["type"] == "request_discount" else None
            if shadow:
                if decision.verdict == "approval":
                    would = approvals.build_plan(s, customer, action, agent_limit)
                    trace["approvals"].append({"kind": would["kind"], "riskClass": would["risk"], "wouldRequest": True,
                                               "preview": redact(would["preview"])})
                elif decision.verdict == "execute" and action["type"] == "handoff_human":
                    proposed_escalation = True
                    escalation_reason = escalation_reason or action.get("reason") or "handoff"
                continue
            try:
                if decision.verdict == "execute":
                    if action["type"] == "create_lead":
                        execute("create_lead", {}, idempotency_key=f"create_lead:{customer.id}")
                    elif action["type"] == "recommend_plan":
                        execute("recommend_plan", {"plan_key": action["plan_key"]})
                        move_stage(s, customer, "proposal", actor="FINORA CORE", actor_type="ai", reason="plan recommended")
                    elif action["type"] == "handoff_human":
                        execute("handoff_human", {"reason": action.get("reason") or "handoff"}, conversation=conversation)
                        handed_off = True
                elif decision.verdict == "approval":
                    approval = approvals.request(s, customer=customer, conversation_ref=str(conversation.id),
                                                 run_id=run.id, action=action, risk=decision.risk,
                                                 agent_limit=agent_limit)
                    if action["type"] == "start_trial":
                        intake.finish(s, customer, str(conversation.id))
                    trace["approvals"].append({"id": approval.id, "kind": approval.action,
                                               "riskClass": approval.risk_class, "planVersion": approval.plan_version})
                    run.status = "waiting_approval"
                    if action["type"] == "configure_tenant":
                        plan.reply_text = ("I prepared a configuration proposal for your own account. FINORA will review it before applying changes."
                                           if plan.language == "en" else "جهّزت اقتراح ترتيب لحسابك وحده، وراح يراجعه مشرف فينورا قبل التطبيق.")
                        plan.needs_human, plan.handoff_reason = False, None
            except ToolError as exc:
                logger.warning("finora_core tool %s failed: %s", action["type"], exc.code)
                if project_result:
                    plan.reply_text = "الخطة محفوظة، لكن تعذر إرسال طلب المراجعة. ما اعتمدت عرضاً أو دفعة؛ خلّي مشرف فينورا يراجع الطلب."
                if advisor_result:
                    plan.reply_text = "تعذر إرسال طلب التجهيز للمراجعة. ما تطبقت أي تغييرات؛ خلّي مشرف فينورا يراجع الطلب."
                if action["type"] == "configure_tenant":
                    report(s, customer, str(conversation.id), kind="missing_template" if exc.code == "UNKNOWN_PROFILE" else "missing_feature" if exc.code in {"PLAN_LIMIT", "UNSUPPORTED_FEATURE"} else "configuration_error", details=str(exc), source=f"message:{newest.id}:{exc.code}", verified=True)
                elif not project_result and not advisor_result:
                    plan.reply_text = ("The requested action could not be verified. FINORA needs to review it before confirming completion."
                                       if plan.language == "en" else "تعذر التحقق من تنفيذ الإجراء المطلوب. لازم يراجعه فريق فينورا قبل ما نأكد اكتماله.")
                    report(s, customer, str(conversation.id), kind="configuration_error",
                           details=f"تعذر تنفيذ {action['type']}؛ رمز الفشل: {exc.code}", source=f"action:{newest.id}:{exc.code}", verified=True)

        if missing_template and not advisor_result:
            notice = ("Your business activity needs a dedicated setup template. The FINORA team has the request for review."
                      if plan.language == "en" else "نشاطك يحتاج قالب تجهيز مخصّص. طلب القالب وصل لفريق فينورا حتى يراجعونه ويجهزون المناسب إلك.")
            if shadow:
                notice = ("Your business activity needs a dedicated setup template for FINORA to review."
                          if plan.language == "en" else "نشاطك يحتاج قالب تجهيز مخصّص يراجعه فريق فينورا.")
            plan.reply_text = f"{plan.reply_text}\n{notice}" if setup_request else notice
        if isinstance(provider, RequestProvider) and provider.state.get("lastError"):
            code = provider.state["lastError"]
            trace["providerFailure"] = {"code": code, "stoppedForRequest": bool(provider.state.get("blocked"))}
            if not shadow:
                reason = ("حد الرصيد أو الإنفاق يمنع استخدام الذكاء السحابي؛ يحتاج صاحب الحساب مراجعة الرصيد والحدود."
                          if code == "insufficient_quota" else "تعذر استخدام مزود الذكاء في هذا الطلب؛ راجع الاتصال وإعدادات المزود.")
                report(s, customer, str(conversation.id), kind="provider_error", details=f"{reason} رمز الفشل: {code}",
                       source=f"provider:{conversation.id}:{code}", verified=True)
        from .reply_review import review
        current_ids = {str(message.id) for message in burst}
        review_recent = [row for row in recent if row.get("messageId") not in current_ids]
        reviewed = review("\n".join([plan.reply_text] + extra_questions), current=customer_text, recent=review_recent,
                          generated=plan.source == "model", language=plan.language,
                          allow_repeat=bool(project_result and (project_consultation.full_plan_requested(customer_text)
                                            or project_consultation.commercial_terms_requested(customer_text))))
        plan.reply_text, extra_questions = reviewed.text, []
        trace["replyReview"] = {"status": "needs_review" if reviewed.needs_review else "ready", "issues": reviewed.issues}
        if reviewed.needs_review and not shadow:
            report(s, customer, str(conversation.id), kind="reply_quality", details="; ".join(reviewed.issues),
                   source=f"reply:{newest.id}", verified=True)
        if shadow:
            reply_text = "\n".join([plan.reply_text] + extra_questions).strip()
            proposal = _store_proposal(s, run=run, conversation=conversation, customer=customer, inbound=newest,
                                       trigger_ref=trigger_ref, reply_text=reply_text, plan=plan, trace=trace,
                                       escalation=proposed_escalation, escalation_reason=escalation_reason)
            _finish_run(run, started, trace, status="shadow", outcome="proposed (shadow mode — not sent)")
            audit(s, actor="FINORA CORE", actor_type="ai", category="ai", action="shadow.proposal",
                  title="اقتراح رد (وضع الظل — لم يُرسل)", customer=customer.display_name,
                  conversation_ref=str(conversation.id), correlation_id=correlation)
            emit(s, "shadow.proposal", {"proposal": proposal_dto(proposal)})
            _status(s, "idle", conversation, label=None)
            s.commit()
            return None

        # Stage moves after actions, so a lead created in this run is synced too (forward-only for the AI).
        if accounts_enabled and "businessType" in facts:
            move_stage(s, customer, "engaged", actor="FINORA CORE", actor_type="ai", reason="business identified")
        if accounts_enabled and "businessType" in facts and not memory.qualification_missing(facts):
            move_stage(s, customer, "qualified", actor="FINORA CORE", actor_type="ai", reason="profile complete")
        if plan.needs_human and not handed_off:
            execute("handoff_human", {"reason": plan.handoff_reason or "needs human"}, conversation=conversation)
            handed_off = True
        if handed_off:
            move_stage(s, customer, "needs_human", actor="FINORA CORE", actor_type="ai",
                       reason=plan.handoff_reason or "handoff")
            emit(s, "customer.updated", {"customerId": str(customer.id)})
        training_given = any(c.startswith(("howto:", "guide:")) for c in plan.cited)
        if accounts_enabled and policy.flag(s, "AI_AUTOMATIC_ONBOARDING") == "on":
            onboarding.refresh(s, customer, training_given=training_given)
        reply_text = "\n".join([plan.reply_text] + extra_questions).strip()
        _status(s, "replying", conversation)
        run_id = run.id
        s.commit()

    # ───── response safety (spec §74) — re-read the house state right before sending ─────
    from modules.ai_sales.models import AISalesMessage

    db.session.commit()  # persist our own house-side changes (e.g. handoff) before re-reading for safety checks
    db.session.refresh(conversation)
    newer = AISalesMessage.query.filter(
        AISalesMessage.conversation_id == conversation.id,
        AISalesMessage.direction == "inbound",
        AISalesMessage.id > newest_burst_id,
    ).first()
    taken_by_human = conversation.human_takeover and not handed_off
    timed_out = time.monotonic() - reply_started > (PROJECT_TIMEOUT_SECONDS if project_result else RUN_TIMEOUT_SECONDS)
    paused = _paused()
    outcome = "replied"
    if taken_by_human:
        outcome = "skipped: human took over"
    elif newer is not None:
        outcome = "skipped: newer customer message"
    elif timed_out:
        outcome = "timeout"
    elif paused:
        outcome = "skipped: automation paused"
    else:
        # A settings change while the provider was running must take effect before delivery.
        with core_session() as s:
            if policy.flag(s, "AI_AUTO_REPLY") != "on" or policy.flag(s, "AI_SHADOW_MODE") == "on":
                outcome = "skipped: reply mode changed"

    reply = None
    project_message_ids = []
    delivery_statuses = []
    if outcome == "replied":
        parts = project_consultation.chunks(reply_text) if project_result else [reply_text[:2000]]
        for part in parts:
            reply = AISalesMessage(conversation_id=conversation.id, channel_account_id=conversation.channel_account_id,
                               direction="outbound", sender_type="ai", message_type="text", text_content=reply_text[:2000],
                               status="queued", reply_to_external_id=inbound.external_message_id)
            reply.text_content = part
            db.session.add(reply)
            db.session.flush()
            if project_result:
                project_message_ids.append(reply.id)
            if send_external:
                from modules.ai_sales.meta_reliability import record_send_failure, record_send_success

                from ..transport import send_text

                try:
                    record_send_success(reply, conversation.channel, send_text(conversation, reply.text_content))
                    conversation.last_business_message_at = reply.sent_at
                except Exception as exc:  # classified: retry_scheduled or failed — never reported as sent
                    record_send_failure(reply, conversation.channel, exc)
            else:
                reply.status = "simulated"
            delivery_statuses.append(reply.status)
    for m in burst:
        m.status = "processed" if outcome == "replied" or outcome.startswith("skipped: newer") else (
            "agent_timeout" if outcome == "timeout" else m.status if outcome.startswith("skipped: automation") else "handled_by_human")
    db.session.commit()

    if project_result and project_message_ids:
        with core_session() as s:
            project_customer = s.get(FcCustomer, customer.id)
            draft = project_consultation.load(s, project_customer, str(conversation.id), lock=True)
            if draft and draft["phase"] == "scope_review" and draft["evidence"][-1]["id"] == str(newest.id):
                draft["scopeMessages"] = project_message_ids
                project_consultation.save(s, project_customer, str(conversation.id), draft)
                s.commit()

    with core_session() as s:
        run = s.get(FcAgentRun, run_id)
        run.status = {"replied": "replied", "timeout": "timeout"}.get(outcome, "skipped")
        if handed_off and outcome == "replied":
            run.status = "handed_off"
        delivery_status = ("failed" if any(status not in {"sent", "simulated", "retry_scheduled"} for status in delivery_statuses)
                           else "retry_scheduled" if "retry_scheduled" in delivery_statuses
                           else reply.status if reply is not None else None)
        if outcome == "replied" and delivery_status in {"failed", "retry_scheduled"}:
            run.status = "delivery_failed" if delivery_status == "failed" else "retry_scheduled"
        trace["reply"] = {"status": delivery_status, "parts": delivery_statuses}
        delivery_outcome = f"{outcome}: {run.status}" if run.status in {"delivery_failed", "retry_scheduled"} else outcome
        _finish_run(run, started, trace, status=run.status, outcome=delivery_outcome)
        if reply is not None:
            audit(s, actor="FINORA CORE", actor_type="ai", category="messages", action="message.reply",
                  title="تم إرسال الرد" if delivery_status == "sent" else "الرد بانتظار الإرسال" if delivery_status == "retry_scheduled" else "تعذر إرسال الرد",
                  customer=conversation.contact_name, conversation_ref=str(conversation.id),
                  result="ok" if delivery_status in {"sent", "simulated"} else ("pending" if delivery_status == "retry_scheduled" else "failed"),
                  correlation_id=correlation, dedupe_key=f"audit:msg:{msg_ref(reply.id, iso(reply.created_at))}")
        elif outcome == "timeout":
            audit(s, actor="FINORA CORE", actor_type="system", category="errors", action="agent.timeout",
                  title="انتهت مهلة المعالجة — لم يُرسل رد", customer=conversation.contact_name,
                  conversation_ref=str(conversation.id), result="failed", correlation_id=correlation)
        state = "completed" if outcome == "replied" else ("error" if outcome == "timeout" else "idle")
        label = "تم الرد ✓" if outcome == "replied" else None
        if outcome == "replied" and delivery_status in {"failed", "retry_scheduled"}:
            state, label = ("error", "تعذر إرسال الرد") if delivery_status == "failed" else ("idle", "الرد بانتظار إعادة الإرسال")
        _status(s, state, conversation, label=label)
        s.commit()
    return reply


def _finish_run(run: FcAgentRun, started: float, trace: dict[str, Any], *, status: str, outcome: str) -> None:
    run.status = status
    run.outcome = outcome[:200]
    run.finished_at = datetime.utcnow()
    run.latency_ms = int((time.monotonic() - started) * 1000)
    interpretation = trace.get("understanding", {})
    analysis_input, analysis_output = interpretation.get("inputCount", 0), interpretation.get("outputCount", 0)
    costs = [estimate_cost(run.model, (run.input_tokens or 0) - analysis_input, (run.output_tokens or 0) - analysis_output),
             estimate_cost(interpretation.get("model", ""), analysis_input, analysis_output)]
    run.cost_usd = None if any(cost is None for cost in costs) else sum(costs)
    trace["result"] = outcome[:200]
    run.trace_json = json.dumps(redact(trace), ensure_ascii=False)[:20000]


# ───────────────────────────── shadow mode ─────────────────────────────


def _store_proposal(s, *, run, conversation, customer, inbound, trigger_ref: str, reply_text: str, plan: Plan,
                    trace: dict[str, Any], escalation: bool, escalation_reason: str | None) -> FcShadowProposal:
    for older in s.query(FcShadowProposal).filter_by(conversation_ref=str(conversation.id), status="pending").all():
        older.status = "superseded"  # the customer wrote again before anyone answered
    proposal = FcShadowProposal(
        run_id=run.id, conversation_ref=str(conversation.id), customer_id=customer.id, trigger_message_id=inbound.id,
        trigger_ref=trigger_ref, proposed_reply=reply_text[:2000],
        plan_json=json.dumps(redact({"intents": plan.intents, "actions": trace["proposedActions"],
                                     "policy": trace["policy"], "approvals": trace["approvals"],
                                     "cited": list(plan.cited), "guards": list(plan.guard_notes)}),
                             ensure_ascii=False),
        confidence=_top_confidence(plan.intents), proposed_escalation=bool(escalation),
        escalation_reason=(escalation_reason or None) and escalation_reason[:300], status="pending",
    )
    s.add(proposal)
    s.flush()
    return proposal


def proposal_dto(p: FcShadowProposal) -> dict[str, Any]:
    plan = json.loads(p.plan_json or "{}")
    return {
        "id": str(p.id), "conversationId": p.conversation_ref, "status": p.status,
        "proposedReply": p.proposed_reply, "confidence": p.confidence,
        "intents": plan.get("intents") or [], "actions": plan.get("policy") or [],
        "approvals": plan.get("approvals") or [], "cited": plan.get("cited") or [],
        "escalation": {"proposed": p.proposed_escalation, "reason": p.escalation_reason,
                       "decision": p.escalation_decision},
        "human": None if p.human_reply is None else {
            "reply": p.human_reply, "actor": p.human_actor, "at": iso(p.human_replied_at),
            "usedProposal": p.operator_used, "accepted": p.accepted, "edited": p.edited, "similarity": p.similarity,
        },
        "createdAt": iso(p.created_at),
    }


def _tenant_business_type(slug: str | None) -> str | None:
    if not slug:
        return None
    from models.core.tenant import Tenant

    with core_session() as s:
        tenant = s.query(Tenant).filter_by(slug=slug).first()
        return tenant.business_type if tenant else None


def _paused() -> bool:
    from ..killswitch import automation_paused_for_current_tenant

    try:
        return automation_paused_for_current_tenant()
    except Exception:
        current_app.logger.exception("kill switch check failed before send")
        return True
