"""FINORA CORE desktop API — ``/api/v1/finora-core`` (contract: docs/finora-core-architecture.md §5)."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Any

from flask import Blueprint, Response, g, jsonify, request, stream_with_context

from extensions import db
from modules.ai_sales.models import AISalesMessage

from . import conversations as convs
from .auth import (
    check_login_allowed,
    clear_login_failures,
    current_operator,
    issue_tokens,
    record_login_failure,
    require,
    revoke,
    rotate_refresh,
)
from .errors import CoreApiError, conflict, not_found, validation_error
from .models import FcAuditLog, FcConversationRead, FcEvent, FcIdempotency, FcNote
from .store import (
    KILL_SWITCH_KEY,
    activity_dto,
    audit,
    automation_paused,
    core_session,
    emit,
    environment,
    house_slug,
    iso,
    msg_ref,
    new_correlation_id,
    set_setting,
    use_house,
)
from .sync import run_house_maintenance, sync_house
from .transport import loopback_enabled, send_text
from modules.ai_sales.meta_reliability import record_send_failure, record_send_success

logger = logging.getLogger(__name__)

finora_core_bp = Blueprint("finora_core", __name__, url_prefix="/api/v1/finora-core")

DEFAULT_ORIGINS = "http://tauri.localhost,tauri://localhost,https://tauri.localhost,http://localhost:5174"
STREAM_LIFETIME_SECONDS = 300
MAX_TEXT = 2000


# ───────────────────────────── plumbing ─────────────────────────────


def _allowed_origins() -> set[str]:
    raw = os.environ.get("FINORA_CORE_ALLOWED_ORIGINS") or DEFAULT_ORIGINS
    return {o.strip() for o in raw.split(",") if o.strip()}


@finora_core_bp.after_request
def _cors(response: Response) -> Response:
    origin = request.headers.get("Origin")
    if origin and origin in _allowed_origins():
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, Idempotency-Key, Last-Event-ID, MCP-Protocol-Version"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
        response.headers["Access-Control-Max-Age"] = "600"
    response.headers["Cache-Control"] = "no-store"
    return response


@finora_core_bp.before_request
def _preflight():
    if request.method == "OPTIONS":
        return Response(status=204)
    return None


@finora_core_bp.errorhandler(CoreApiError)
def _core_error(exc: CoreApiError):
    return exc.response()


@finora_core_bp.errorhandler(Exception)
def _unexpected(exc: Exception):
    if hasattr(exc, "code") and isinstance(getattr(exc, "code"), int) and exc.code < 500:  # werkzeug HTTPException
        return CoreApiError("VALIDATION_ERROR", "طلب غير صالح", exc.code).response()
    logger.exception("finora_core unexpected error on %s", request.path)
    return CoreApiError("UNKNOWN_ERROR", "حدث خطأ غير متوقع في الخادم", 500, retryable=True).response()


def _json() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise validation_error("صيغة الطلب غير صالحة")
    return data


def _json_optional() -> dict[str, Any]:
    """Body for action endpoints whose payload is optional (verify, publish, revert…)."""
    if not request.get_data(cache=True):
        return {}
    return _json()


def _conv_id(raw: str) -> int:
    if not raw.isdigit() or len(raw) > 12:
        raise not_found("المحادثة غير موجودة")
    return int(raw)


def _read_map(s, ids: list[str] | None = None) -> dict[str, int]:
    q = s.query(FcConversationRead).filter_by(superadmin_id=current_operator().superadmin_id)
    if ids is not None:
        q = q.filter(FcConversationRead.conversation_ref.in_(ids))
    return {r.conversation_ref: r.last_read_message_id for r in q.all()}


def _actor() -> str:
    return current_operator().username


# ───────────────────────────── auth ─────────────────────────────


@finora_core_bp.post("/auth/login")
def login():
    from models.core.super_admin import SuperAdmin

    data = _json()
    username = str(data.get("username") or "").strip()[:50]
    password = str(data.get("password") or "")
    if not username or not password:
        raise validation_error("أدخل اسم المستخدم وكلمة المرور")
    check_login_allowed(username)
    with core_session() as s:
        admin = s.query(SuperAdmin).filter_by(username=username).first()
        if admin is None or not admin.check_password(password):
            record_login_failure(username)
            audit(s, actor=username, actor_type="human", category="errors", action="auth.failed",
                  title="محاولة دخول فاشلة", result="failed")
            s.commit()
            raise CoreApiError("AUTH_ERROR", "بيانات الدخول غير صحيحة", 401)
        clear_login_failures(username)
        tokens = issue_tokens(s, superadmin_id=admin.id, username=admin.username)
        audit(s, actor=admin.username, actor_type="human", category="ai", action="auth.login", title="تسجيل دخول إلى FINORA CORE")
        s.commit()
    return jsonify(tokens)


@finora_core_bp.post("/auth/refresh")
def refresh():
    token = str(_json().get("refreshToken") or "")
    if not token:
        raise validation_error("رمز التحديث مفقود")
    return jsonify(rotate_refresh(token))


@finora_core_bp.post("/auth/logout")
@require()
def logout():
    revoke(current_operator().session_id, "logout")
    return jsonify({"ok": True})


@finora_core_bp.get("/me")
@require()
def me():
    return jsonify(current_operator().to_dict())


# ───────────────────────────── status ─────────────────────────────


@finora_core_bp.get("/status")
@require()
def status():
    from .brain.shadow import shadow_enabled

    with core_session() as s:
        paused = automation_paused(s)
    configured = house_slug() is not None
    if configured:
        with use_house():
            channels = convs.channel_health()
            agent = convs.agent_status()
            count = convs.conversation_count()
    else:
        channels = {"instagram": "unknown", "facebook": "unknown", "telegram": "unknown"}
        agent = {"state": "idle", "label": None, "conversationId": None, "channel": None}
        count = 0
    return jsonify(
        {
            "environment": environment(),
            "channels": channels,
            "automationPaused": paused,
            "shadowMode": shadow_enabled(),
            "agent": agent,
            "conversationCount": count,
            "houseConfigured": configured,
            "devLoopback": loopback_enabled(),
        }
    )


@finora_core_bp.post("/automation")
@require("settings.manage")
def set_automation():
    data = _json()
    paused = bool(data.get("paused"))
    reason = str(data.get("reason") or "").strip()[:300]
    if paused and not reason:
        raise validation_error("سبب الإيقاف مطلوب")
    with core_session() as s:
        set_setting(s, KILL_SWITCH_KEY, "1" if paused else "0", _actor())
        audit(s, actor=_actor(), actor_type="human", category="ai", action="automation.pause" if paused else "automation.resume",
              title="تم إيقاف كل الأتمتة" if paused else "تم استئناف الأتمتة", input_summary=reason or None)
        s.commit()
    body = status().get_json()
    with core_session() as s:
        emit(s, "status", {"status": {k: v for k, v in body.items() if k not in ("houseConfigured", "devLoopback")}})
        s.commit()
    return jsonify(body)


# ───────────────────────────── conversations ─────────────────────────────


@finora_core_bp.get("/conversations")
@require("conversations.view")
def list_conversations():
    channel = request.args.get("channel", "all")
    filter_ = request.args.get("filter", "all")
    if channel not in ("all", "instagram", "facebook", "telegram"):
        raise validation_error("قناة غير صالحة")
    if filter_ not in ("all", "unread", "ai_active", "human", "qualified", "needs_approval", "onboarding"):
        raise validation_error("تصفية غير صالحة")
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 100))
        offset = max(0, int(request.args.get("cursor", 0)))
    except ValueError as exc:
        raise validation_error("قيمة غير صالحة") from exc
    with core_session() as s:
        read_map = _read_map(s)
    with use_house():
        items, next_cursor = convs.list_conversations(
            channel=channel, filter_=filter_, search=request.args.get("q", ""), limit=limit, offset=offset, read_map=read_map
        )
    from .brain.enrich import enrich_conversations

    with core_session() as s:
        items = enrich_conversations(s, items)
    return jsonify({"items": items, "nextCursor": next_cursor})


@finora_core_bp.get("/conversations/<raw_id>")
@require("conversations.view")
def get_conversation(raw_id: str):
    cid = _conv_id(raw_id)
    with core_session() as s:
        read_map = _read_map(s, [str(cid)])
    with use_house():
        conv = convs.get_conversation(cid)
        if conv is None:
            raise not_found("المحادثة غير موجودة")
        dto = convs.build_dtos([conv], read_map)[0]
    from .brain.enrich import enrich_conversations

    with core_session() as s:
        return jsonify(enrich_conversations(s, [dto])[0])


@finora_core_bp.get("/conversations/<raw_id>/messages")
@require("conversations.view")
def list_messages(raw_id: str):
    cid = _conv_id(raw_id)
    before = request.args.get("before")
    limit = max(1, min(int(request.args.get("limit", 60) or 60), 200))
    with use_house():
        if convs.get_conversation(cid) is None:
            raise not_found("المحادثة غير موجودة")
        items = convs.list_messages(cid, before=int(before) if before and before.isdigit() else None, limit=limit)
    return jsonify({"items": items})


@finora_core_bp.post("/conversations/<raw_id>/read")
@require("conversations.view")
def mark_read(raw_id: str):
    cid = _conv_id(raw_id)
    with use_house():
        if convs.get_conversation(cid) is None:
            raise not_found("المحادثة غير موجودة")
        latest = convs.latest_message_id(cid)
    with core_session() as s:
        key = {"superadmin_id": current_operator().superadmin_id, "conversation_ref": str(cid)}
        row = s.get(FcConversationRead, key)
        if row is None:
            s.add(FcConversationRead(**key, last_read_message_id=latest))
        else:
            row.last_read_message_id = max(row.last_read_message_id, latest)
        s.commit()
    return jsonify({"ok": True})


def _set_control(cid: int, target: str) -> dict[str, Any]:
    from modules.ai_sales.engine import pause_conversation_for_human
    from modules.ai_sales.routes import _apply_conversation_channel_policy

    corr = new_correlation_id()
    with use_house():
        conv = convs.get_conversation(cid)
        if conv is None:
            raise not_found("المحادثة غير موجودة")
        if target == "human":
            pause_conversation_for_human(conv, reason=f"استلام من FINORA CORE ({_actor()})", indefinite=True)
        else:
            _apply_conversation_channel_policy(conv)
            conv.ai_paused_until = None
            conv.handoff_reason = None
        db.session.commit()
        with core_session() as s:
            dto = convs.build_dtos([conv], _read_map(s, [str(cid)]))[0]
            if target == "ai" and dto["control"] != "ai":
                logger.info("conversation %s channel is in employee mode; AI stays off", cid)
            audit(s, actor=_actor(), actor_type="human", category="ai",
                  action="conversation.takeover" if target == "human" else "conversation.resume",
                  title="استلام المحادثة يدوياً" if target == "human" else "إعادة تشغيل FINORA CORE",
                  customer=dto["customerName"], conversation_ref=str(cid), correlation_id=corr)
            emit(s, "conversation.updated", {"conversation": dto})
            s.commit()
    return dto


@finora_core_bp.post("/conversations/<raw_id>/takeover")
@require("ai.takeover")
def takeover(raw_id: str):
    return jsonify(_set_control(_conv_id(raw_id), "human"))


@finora_core_bp.post("/conversations/<raw_id>/resume")
@require("ai.takeover")
def resume(raw_id: str):
    return jsonify(_set_control(_conv_id(raw_id), "ai"))


@finora_core_bp.post("/conversations/<raw_id>/messages")
@require("messages.send")
def send_message(raw_id: str):
    cid = _conv_id(raw_id)
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if not key or len(key) > 100:
        raise validation_error("Idempotency-Key مطلوب")
    text = str(_json().get("text") or "").strip()
    if not text:
        raise validation_error("اكتب الرسالة")
    if len(text) > MAX_TEXT:
        raise validation_error("الرسالة طويلة جداً")
    op = current_operator()
    scoped_key = f"{op.superadmin_id}:{key}"
    with core_session() as s:
        prior = s.get(FcIdempotency, scoped_key)
        if prior is not None:
            return Response(prior.response_json, status=prior.status_code, mimetype="application/json")

    corr = new_correlation_id()
    with use_house():
        conv = convs.get_conversation(cid)
        if conv is None:
            raise not_found("المحادثة غير موجودة")
        # Response safety (spec §12, §74): no manual reply while FINORA CORE drives the thread. In Shadow Mode the
        # agent never sends, so humans answer every conversation.
        from .brain.shadow import shadow_enabled

        shadow = shadow_enabled()
        if convs.control(conv) == "ai" and not shadow:
            raise conflict("استلم المحادثة أولاً قبل الإرسال اليدوي")
        message = AISalesMessage(
            conversation_id=conv.id,
            channel_account_id=conv.channel_account_id,
            direction="outbound",
            sender_type="employee",
            message_type="text",
            text_content=text,
            status="queued",
        )
        db.session.add(message)
        db.session.flush()
        failure: str | None = None
        try:
            record_send_success(message, conv.channel, send_text(conv, text))
            conv.last_business_message_at = message.sent_at
        except Exception as exc:  # classified; never reported as success
            meta_failure = record_send_failure(message, conv.channel, exc)
            logger.warning("finora_core manual send %s conversation=%s corr=%s kind=%s",
                           message.status, cid, corr, meta_failure.kind)
            if message.status == "failed":
                failure = "تعذر إرسال الرسالة عبر القناة"
        db.session.commit()
        dto = convs.message_dto(message)
        customer = conv.contact_name
    # 201 sent · 202 accepted and queued for retry (rate limit / Meta 5xx) · 502 failed
    status_code = 502 if failure else (202 if dto["delivery"] == "sending" else 201)
    body = {"message": dto} if failure is None else {
        "message": dto,
        "error": {"code": "META_SEND_FAILED", "message": failure, "retryable": True},
    }
    with core_session() as s:
        audit(s, actor=op.username, actor_type="human", category="messages" if failure is None else "errors",
              action="message.manual_send", title="تم إرسال رد يدوي" if failure is None else "فشل إرسال رد يدوي",
              customer=customer, conversation_ref=str(cid), result="ok" if failure is None else "failed",
              correlation_id=corr, dedupe_key=f"audit:msg:{msg_ref(dto['id'], dto['at'])}")
        emit(s, "message.sent", {"message": dto}, dedupe_key=f"msg:{msg_ref(dto['id'], dto['at'])}:new")
        s.add(FcIdempotency(key=scoped_key, superadmin_id=op.superadmin_id, route="send_message",
                            status_code=status_code, response_json=json.dumps(body, ensure_ascii=False)))
        s.commit()
    if shadow and failure is None:
        from .brain.shadow import record_human_reply

        payload = _json()
        record_human_reply(conversation_ref=str(cid), message_id=int(dto["id"]) if str(dto["id"]).isdigit() else 0,
                           text=text, actor=op.username, proposal_id=str(payload.get("proposalId") or "") or None,
                           used_proposal=bool(payload.get("usedProposal")))
    return jsonify(body), status_code


# ───────────────────────────── customer profile + notes ─────────────────────────────


FACT_LABELS = {
    "businessType": {"clinic": "عيادة", "beauty_center": "مركز تجميل", "food_wholesale_retail": "مواد غذائية",
                     "wholesale": "تجارة جملة", "commerce": "تجارة / متجر", "restaurant": "مطعم", "pharmacy": "صيدلية",
                     "general": "شركة عامة", "hr_management": "موارد بشرية", "starter_business": "أعمال مبسطة"},
    "specialty": {"dentistry": "أسنان", "dermatology": "جلدية", "gynecology": "نسائية وتوليد", "pediatrics": "أطفال",
                  "cardiology": "قلبية", "internal_medicine": "باطنية", "general": "عام"},
}
PROFILE_KEYS = ("businessType", "specialty", "doctors", "employees", "branches", "country", "city", "phone", "email")


def _customer_for(s, cid: int):
    from .brain.models import FcConversationCustomer, FcCustomer

    link = s.get(FcConversationCustomer, str(cid))
    if link is None:
        return None
    customer = s.get(FcCustomer, link.customer_id)
    while customer is not None and customer.merged_into_id:
        customer = s.get(FcCustomer, customer.merged_into_id)
    return customer


def _profile(cid: int) -> dict[str, Any]:
    from .brain import memory
    from .brain.models import FcOnboardingStep
    from .brain.onboarding import STEPS

    with use_house():
        conv = convs.get_conversation(cid)
        if conv is None:
            raise not_found("ملف العميل غير موجود")
        dto = convs.build_dtos([conv], {})[0]
        phone = (conv.external_phone or "").strip()
    facts: dict[str, Any] = {k: None for k in PROFILE_KEYS}
    if phone:
        facts["phone"] = {"value": phone, "confidence": 1.0, "source": "channel"}
    with core_session() as s:
        notes = s.query(FcNote).filter_by(conversation_ref=str(cid)).order_by(FcNote.id.desc()).limit(50).all()
        customer = _customer_for(s, cid)
        plan = None
        project = None
        steps: list[dict[str, Any]] = []
        stage = dto["leadStage"]
        tenant = None
        customer_id = dto["customerId"]
        if customer is not None:
            from .brain import project_consultation
            project = project_consultation.dto(project_consultation.load(s, customer, str(cid)))
            known = memory.active_facts(s, customer.id)  # only facts at or above the display confidence
            for key in PROFILE_KEYS:
                if key in known:
                    value = known[key]["value"]
                    facts[key] = {**known[key], "value": FACT_LABELS.get(key, {}).get(value, value)}
            if "recommendedPlan" in known:
                plan = {"name": str(known["recommendedPlan"]["value"]), "tier": "مقترحة"}
            rows = {r.step: r for r in s.query(FcOnboardingStep).filter_by(customer_id=customer.id).all()}
            if rows:
                steps = [{"key": k, "label": label, "done": bool(rows.get(k) and rows[k].done)} for k, label in STEPS]
            stage, tenant, customer_id = customer.lead_stage, customer.tenant_slug, f"fc{customer.id}"
    return {
        "customerId": customer_id,
        "name": dto["customerName"],
        "avatarUrl": dto["avatarUrl"],
        "channel": dto["channel"],
        "leadStage": stage,
        # Unknown stays unknown (null → "غير محدد"); low-confidence facts are never shown as known.
        "facts": facts,
        "recommendedPlan": plan,
        "project": project,
        "finoraTenantId": tenant,
        "onboarding": steps,
        "notes": [{"id": str(n.id), "author": n.author, "body": n.body, "at": iso(n.created_at)} for n in notes],
    }


@finora_core_bp.get("/customers/<raw_id>")
@require("conversations.view")
def get_customer(raw_id: str):
    return jsonify(_profile(_conv_id(raw_id)))


@finora_core_bp.post("/customers/<raw_id>/notes")
@require("notes.write")
def add_note(raw_id: str):
    cid = _conv_id(raw_id)
    body = str(_json().get("body") or "").strip()
    if not body:
        raise validation_error("اكتب الملاحظة")
    if len(body) > 1000:
        raise validation_error("الملاحظة طويلة جداً")
    with use_house():
        if convs.get_conversation(cid) is None:
            raise not_found("ملف العميل غير موجود")
    with core_session() as s:
        s.add(FcNote(conversation_ref=str(cid), author=_actor(), body=body))
        audit(s, actor=_actor(), actor_type="human", category="ai", action="note.add", title="ملاحظة داخلية", conversation_ref=str(cid))
        s.commit()
    return jsonify(_profile(cid)), 201


# ───────────────────────────── activity + approvals ─────────────────────────────


@finora_core_bp.get("/activity")
@require("audit.view")
def activity():
    category = request.args.get("category", "all")
    with core_session() as s:
        q = s.query(FcAuditLog)
        if category != "all":
            if category not in ("messages", "ai", "finora", "errors", "approvals"):
                raise validation_error("تصنيف غير صالح")
            q = q.filter(FcAuditLog.category == category)
        rows = q.order_by(FcAuditLog.id.desc()).limit(200).all()
        return jsonify({"items": [activity_dto(r) for r in rows]})


@finora_core_bp.post("/channels/health-check")
@require("settings.manage")
def channels_health_check():
    """Live Graph check of every house channel (token, permissions, webhook subscription)."""
    from .meta_house import run_health_checks

    report = run_health_checks()
    with core_session() as s:
        audit(s, actor=_actor(), actor_type="human", category="finora", action="channels.health_check",
              title="فحص صحة قنوات Meta", input_summary=", ".join(f"{r['type']}:{r['status']}" for r in report)[:500])
        s.commit()
    with use_house():
        health = convs.channel_health()
    return jsonify({"channels": health, "details": report})


@finora_core_bp.get("/approvals")
@require("conversations.view")
def approvals():
    from .brain.approvals import approval_dto
    from .brain.models import FcApproval, FcCustomer

    with core_session() as s:
        query = s.query(FcApproval).filter_by(status="pending")
        if "settings.manage" not in current_operator().permissions:
            query = query.filter(FcApproval.action.notin_(["configure_tenant", "publish_project_quote", "confirm_project_deposit"]))
        rows = query.order_by(FcApproval.created_at.desc()).limit(50).all()
        names = {c.id: c.display_name for c in s.query(FcCustomer).filter(
            FcCustomer.id.in_([r.customer_id for r in rows] or [0])).all()}
        return jsonify({"items": [approval_dto(r, names.get(r.customer_id, "عميل")) for r in rows]})


def _notify_customer(conversation_ref: str | None, text: str) -> dict[str, Any] | None:
    """Post-decision message to the customer through the normal Meta send path (respects the kill switch)."""
    if not conversation_ref or not conversation_ref.isdigit():
        return
    from modules.ai_sales.channels import channel_client, outbound_message_id
    from modules.ai_sales.meta_reliability import record_send_failure, record_send_success

    from .killswitch import automation_paused_for_current_tenant

    with use_house():
        conv = convs.get_conversation(int(conversation_ref))
        if conv is None or automation_paused_for_current_tenant():
            return
        message = AISalesMessage(conversation_id=conv.id, channel_account_id=conv.channel_account_id, direction="outbound",
                                 sender_type="ai", message_type="text", text_content=text, status="queued")
        db.session.add(message)
        db.session.flush()
        try:
            record_send_success(message, conv.channel, send_text(conv, text))
            conv.last_business_message_at = message.sent_at
        except Exception as exc:
            record_send_failure(message, conv.channel, exc)
        db.session.commit()
        return {"id": message.id, "status": message.status}


@finora_core_bp.post("/approvals/<approval_id>/decision")
@require("approvals.decide")
def decide(approval_id: str):
    from .brain import approvals as approval_engine
    from .brain.models import FcApproval
    from .brain.tools import ToolError

    decision = str(_json().get("decision") or "")
    if decision not in ("approved", "rejected"):
        raise validation_error("قرار غير صالح")
    if not approval_id.isdigit():
        raise not_found("طلب الموافقة غير موجود")
    with core_session() as s:
        approval = s.get(FcApproval, int(approval_id))
        if approval is None:
            raise not_found("طلب الموافقة غير موجود")
        try:
            outcome = approval_engine.decide(s, approval, decision, actor=_actor(),
                                             plan_hash_seen=str(_json().get("planHash") or "") or None,
                                             operator_permissions=current_operator().permissions)
        except ToolError as exc:
            if approval.action in {"configure_tenant", "start_trial"}:
                from .brain.support import report
                from .brain.models import FcCustomer
                target = s.get(FcCustomer, approval.customer_id)
                if target is not None:
                    report(s, target, approval.conversation_ref, kind="configuration_error", details=f"{exc.code}: {exc}", source=f"approval:{approval.id}", verified=True)
            s.commit()  # persist the failed status / superseding plan + audit rows
            if exc.code in {"CONFLICT", "PLAN_MISMATCH", "PLAN_CHANGED", "PLAN_TAMPERED", "PLAN_MISSING", "ADVICE_CHANGED", "ADVICE_INCOMPLETE", "ADVICE_SCOPE", "PROJECT_CHANGED", "PROJECT_CONSENT", "PROJECT_SCOPE", "PAYMENT_UNVERIFIED"}:
                raise conflict(str(exc)) from exc
            if exc.code == "PERMISSION":
                raise CoreApiError("FORBIDDEN", str(exc), 403) from exc
            raise CoreApiError("FINORA_API_ERROR", "تعذر تنفيذ الإجراء — راجع سجل النشاط", 502, retryable=False) from exc
        s.commit()
        body = {"approval": approval_engine.approval_dto(outcome.approval, outcome.customer.display_name),
                "credentials": None}
        secret = outcome.result.secret if outcome.result else None
        if secret:
            from flask import current_app

            base = (current_app.config.get("BASE_URL") or "").rstrip("/")
            # Shown once to the approving operator; never stored, logged or sent to the customer chat or an LLM.
            body["credentials"] = {"tenantSlug": secret["tenant_slug"], "username": secret["username"],
                                   "password": secret["password"], "loginUrl": f"{base}/login" if base else None}
        action, conv_ref, new_value = outcome.approval.action, outcome.approval.conversation_ref, outcome.approval.new_value
        project_notice = None
        if action in {"publish_project_quote", "confirm_project_deposit"}:
            from .brain import project_consultation
            draft = project_consultation.load(s, outcome.customer, conv_ref, lock=True)
            if decision == "approved":
                project_notice = (project_consultation.quote_text(draft) if action == "publish_project_quote" else
                                  "تأكد وصول العربون من فريق فينورا ✓ خطتك جاهزة لفريق التطوير. نحسب المدة بعد استكمال المعلومات والصلاحيات المتفق عليها؛ الربط البرمجي التلقائي بعده مو مفعّل.")
            else:
                draft["phase"] = "quote_rejected" if action == "publish_project_quote" else "awaiting_deposit"
                draft["paymentReference"] = None
                project_consultation.save(s, outcome.customer, conv_ref, draft, _actor())
            s.commit()
    if project_notice:
        deliveries = [_notify_customer(conv_ref, part) for part in project_consultation.chunks(project_notice)]
        if action == "publish_project_quote":
            with core_session() as s:
                from .brain.models import FcCustomer
                target = s.get(FcCustomer, outcome.customer.id)
                draft = project_consultation.load(s, target, conv_ref, lock=True)
                if draft["phase"] == "quote_ready" and draft["revision"] == outcome.result.data["revision"]:
                    draft["quoteMessages"] = [delivery["id"] for delivery in deliveries if delivery]
                    draft["quoteExpectedParts"] = len(deliveries)
                    if all(deliveries) and all(delivery["status"] == "sent" for delivery in deliveries):
                        draft["phase"] = "quote_sent"
                    project_consultation.save(s, target, conv_ref, draft)
                    s.commit()
    if decision == "approved" and action == "start_trial":
        _notify_customer(conv_ref, "تم تجهيز حسابك التجريبي على FINORA ✓ راح يتواصل وياك الفريق هسه لتسليم بيانات الدخول بشكل آمن.")
    elif decision == "approved" and action == "configure_tenant":
        _notify_customer(conv_ref, "تم تطبيق التعديلات المعتمدة على حساب شركتك وحده ✓ حدّث صفحة النظام حتى تشوف الإعدادات الجديدة.")
    elif action == "request_discount":
        _notify_customer(conv_ref, f"تمت الموافقة على خصم {new_value} على اشتراكك ✓" if decision == "approved"
                         else "راجعنا طلب الخصم، وللأسف ما نكدر نوافق عليه حالياً. إذا تحب أوضحلك الباقات المتاحة.")
    return jsonify(body)


@finora_core_bp.get("/merge-suggestions")
@require("conversations.view")
def merge_suggestions():
    from .brain.customers import suggestion_dto
    from .brain.models import FcMergeSuggestion

    status = request.args.get("status", "pending")
    if status not in ("pending", "merged", "separate", "dismissed", "unmerged", "all"):
        raise validation_error("حالة غير صالحة")
    with core_session() as s:
        q = s.query(FcMergeSuggestion)
        if status != "all":
            q = q.filter_by(status=status)
        rows = q.order_by(FcMergeSuggestion.id.desc()).limit(50).all()
        return jsonify({"items": [suggestion_dto(s, r) for r in rows]})


@finora_core_bp.post("/merge-suggestions/<suggestion_id>/decision")
@require("settings.manage")
def merge_decision(suggestion_id: str):
    from .brain.customers import dismiss, keep_separate, merge, suggestion_dto
    from .brain.models import FcMergeSuggestion

    decision = str(_json().get("decision") or "")
    decision = {"reject": "dismiss"}.get(decision, decision)
    if decision not in ("merge", "separate", "dismiss") or not suggestion_id.isdigit():
        raise validation_error("قرار غير صالح")
    with core_session() as s:
        row = s.get(FcMergeSuggestion, int(suggestion_id))
        if row is None or row.status != "pending":
            raise not_found("الاقتراح غير موجود")
        kept = None
        try:
            if decision == "merge":
                kept = merge(s, row, actor=_actor())
            elif decision == "separate":
                keep_separate(s, row, actor=_actor())
            else:
                dismiss(s, row, actor=_actor())
        except ValueError as exc:
            raise conflict(str(exc)) from exc
        titles = {"merge": "دمج ملفي عميل", "separate": "إبقاء ملفين منفصلين", "dismiss": "تجاهل اقتراح دمج"}
        audit(s, actor=_actor(), actor_type="human", category="finora", action=f"customer.merge.{decision}",
              title=titles[decision], input_summary=f"{row.reason} (#{row.customer_id} ↔ #{row.candidate_id})")
        emit(s, "customer.updated", {"customerId": str(row.customer_id)})
        s.commit()
        return jsonify({"ok": True, "customerId": kept.id if kept else None, "mergeId": row.merge_id,
                        "suggestion": suggestion_dto(s, row)})


@finora_core_bp.post("/merges/<merge_id>/revert")
@require("settings.manage")
def merge_revert(merge_id: str):
    from .brain.customers import unmerge

    if not merge_id.isdigit():
        raise not_found("عملية الدمج غير موجودة")
    with core_session() as s:
        try:
            restored = unmerge(s, int(merge_id), actor=_actor())
        except ValueError as exc:
            raise conflict(str(exc)) from exc
        audit(s, actor=_actor(), actor_type="human", category="finora", action="customer.unmerge",
              title="التراجع عن دمج ملفي عميل", input_summary=f"merge #{merge_id} → customer #{restored.id} restored")
        emit(s, "customer.updated", {"customerId": str(restored.id)})
        s.commit()
        return jsonify({"ok": True, "customerId": restored.id})


# ───────────────────────────── memory (evidence, corrections) ─────────────────────────────


def _customer_id_for(s, cid: int) -> int:
    customer = _customer_for(s, cid)
    if customer is None:
        raise not_found("ملف العميل غير موجود")
    return customer.id


@finora_core_bp.get("/customers/<raw_id>/memory")
@require("conversations.view")
def customer_memory(raw_id: str):
    from .brain import memory

    cid = _conv_id(raw_id)
    with core_session() as s:
        customer_id = _customer_id_for(s, cid)
        return jsonify({"items": memory.history(s, customer_id, request.args.get("key") or None)})


@finora_core_bp.post("/customers/<raw_id>/memory/correct")
@require("notes.write")
def customer_memory_correct(raw_id: str):
    from .brain import memory

    cid = _conv_id(raw_id)
    data = _json()
    key, reason = str(data.get("key") or ""), str(data.get("reason") or "").strip()
    with core_session() as s:
        customer_id = _customer_id_for(s, cid)
        result = memory.correct(s, customer_id, key, data.get("value"), actor=_actor(), reason=reason)
        if result.outcome == "rejected":
            raise validation_error(f"تصحيح غير صالح: {result.detail}")
        audit(s, actor=_actor(), actor_type="human", category="ai", action="memory.correct",
              title="تصحيح معلومة في ملف العميل", conversation_ref=str(cid), input_summary=f"{key}: {reason}"[:300])
        emit(s, "customer.updated", {"customerId": str(customer_id)})
        s.commit()
        return jsonify({"outcome": result.outcome, "items": memory.history(s, customer_id, key)})


@finora_core_bp.post("/customers/<raw_id>/memory/<fact_id>/<action>")
@require("notes.write")
def customer_memory_action(raw_id: str, fact_id: str, action: str):
    from .brain import memory

    cid = _conv_id(raw_id)
    if action not in ("verify", "retract") or not fact_id.isdigit():
        raise not_found("الإجراء غير موجود")
    reason = str(_json_optional().get("reason") or "").strip()
    with core_session() as s:
        customer_id = _customer_id_for(s, cid)
        try:
            if action == "verify":
                row = memory.verify(s, customer_id, int(fact_id), actor=_actor())
            else:
                row = memory.retract(s, customer_id, int(fact_id), actor=_actor(), reason=reason)
        except LookupError as exc:
            raise not_found("المعلومة غير موجودة") from exc
        except ValueError as exc:
            raise validation_error(str(exc)) from exc
        audit(s, actor=_actor(), actor_type="human", category="ai", action=f"memory.{action}",
              title="توثيق معلومة" if action == "verify" else "سحب معلومة خاطئة", conversation_ref=str(cid),
              input_summary=f"{row.key}{(': ' + reason) if reason else ''}"[:300])
        emit(s, "customer.updated", {"customerId": str(customer_id)})
        s.commit()
        return jsonify({"items": memory.history(s, customer_id, row.key)})


# ───────────────────────────── shadow mode ─────────────────────────────


@finora_core_bp.get("/conversations/<raw_id>/shadow")
@require("conversations.view")
def conversation_shadow(raw_id: str):
    from .brain.models import FcShadowProposal
    from .brain.runtime import proposal_dto
    from .brain.shadow import reconcile, shadow_enabled

    cid = _conv_id(raw_id)
    reconcile(str(cid))
    with core_session() as s:
        rows = (s.query(FcShadowProposal).filter_by(conversation_ref=str(cid))
                .order_by(FcShadowProposal.id.desc()).limit(20).all())
        return jsonify({"enabled": shadow_enabled(), "items": [proposal_dto(r) for r in rows]})


@finora_core_bp.get("/shadow/proposals")
@require("audit.view")
def shadow_proposals():
    from .brain.models import FcShadowProposal
    from .brain.runtime import proposal_dto
    from .brain.shadow import reconcile, stats

    status = request.args.get("status", "all")
    if status not in ("all", "pending", "answered", "superseded"):
        raise validation_error("حالة غير صالحة")
    reconcile()
    with core_session() as s:
        q = s.query(FcShadowProposal)
        if status != "all":
            q = q.filter_by(status=status)
        rows = q.order_by(FcShadowProposal.id.desc()).limit(100).all()
        return jsonify({"stats": stats(), "items": [proposal_dto(r) for r in rows]})


@finora_core_bp.post("/shadow/proposals/<proposal_id>/review")
@require("messages.send")
def shadow_review(proposal_id: str):
    from .brain.runtime import proposal_dto
    from .brain.shadow import review

    if not proposal_id.isdigit():
        raise not_found("الاقتراح غير موجود")
    try:
        row = review(int(proposal_id), escalation_decision=str(_json().get("escalation") or ""), actor=_actor())
    except LookupError as exc:
        raise not_found("الاقتراح غير موجود") from exc
    except ValueError as exc:
        raise validation_error(str(exc)) from exc
    return jsonify(proposal_dto(row))


# ───────────────────────────── knowledge workflow ─────────────────────────────


@finora_core_bp.get("/knowledge")
@require("conversations.view")
def knowledge_list():
    from .brain.knowledge import doc_dto
    from .brain.models import FcKnowledgeDoc
    from .brain.observability import knowledge_version

    with core_session() as s:
        rows = s.query(FcKnowledgeDoc).order_by(FcKnowledgeDoc.doc_key, FcKnowledgeDoc.version.desc()).all()
        return jsonify({"knowledgeVersion": knowledge_version(s), "items": [doc_dto(r) for r in rows]})


@finora_core_bp.get("/knowledge/<doc_key>")
@require("conversations.view")
def knowledge_doc(doc_key: str):
    from .brain.knowledge import doc_dto, revisions
    from .brain.models import FcKnowledgeDoc

    with core_session() as s:
        rows = s.query(FcKnowledgeDoc).filter_by(doc_key=doc_key).order_by(FcKnowledgeDoc.version.desc()).all()
        if not rows:
            raise not_found("المستند غير موجود")
        return jsonify({"versions": [doc_dto(r) for r in rows], "revisions": revisions(s, doc_key)})


@finora_core_bp.post("/knowledge")
@require("settings.manage")
def knowledge_draft():
    from .brain.knowledge import KnowledgeError, doc_dto, save_draft

    d = _json()
    with core_session() as s:
        try:
            row = save_draft(s, doc_key=str(d.get("docKey") or ""), category=str(d.get("category") or ""),
                             title=str(d.get("title") or ""), body=str(d.get("body") or ""),
                             source=str(d.get("source") or ""), author=_actor(),
                             business_type=d.get("businessType") or None, module=d.get("module") or None,
                             feature=d.get("feature") or None, supported_plans=list(d.get("supportedPlans") or []),
                             effective_from=d.get("effectiveFrom"), effective_until=d.get("effectiveUntil"),
                             revision_note=d.get("revisionNote") or None)
        except KnowledgeError as exc:
            raise validation_error(str(exc)) from exc
        audit(s, actor=_actor(), actor_type="human", category="finora", action="knowledge.draft",
              title="مسودة معرفة FINORA", input_summary=f"{row.doc_key} v{row.version}: {row.title}"[:300])
        s.commit()
        return jsonify(doc_dto(row)), 201


@finora_core_bp.post("/knowledge/<doc_key>/<version>/<action>")
@require("settings.manage")
def knowledge_transition(doc_key: str, version: str, action: str):
    from .brain import knowledge as kb

    handlers = {"submit": kb.submit, "publish": kb.publish, "reject": kb.reject, "retire": kb.retire}
    if action not in handlers or not version.isdigit():
        raise not_found("الإجراء غير موجود")
    note = str(_json_optional().get("note") or "").strip() or None
    with core_session() as s:
        try:
            row = handlers[action](s, doc_key, int(version), actor=_actor(), note=note)
        except kb.KnowledgeError as exc:
            raise conflict(str(exc)) from exc
        audit(s, actor=_actor(), actor_type="human", category="finora", action=f"knowledge.{action}",
              title={"submit": "إرسال معرفة للمراجعة", "publish": "نشر معرفة FINORA", "reject": "إرجاع مسودة معرفة",
                     "retire": "سحب معرفة منشورة"}[action],
              input_summary=f"{row.doc_key} v{row.version}"[:300])
        s.commit()
        return jsonify(kb.doc_dto(row))


# ───────────────────────────── observability ─────────────────────────────


@finora_core_bp.get("/agent-runs")
@require("audit.view")
def agent_runs():
    from .brain.models import FcAgentRun
    from .brain.observability import run_dto

    with core_session() as s:
        q = s.query(FcAgentRun)
        if request.args.get("conversationId"):
            q = q.filter_by(conversation_ref=str(_conv_id(request.args["conversationId"])))
        if request.args.get("mode") in ("live", "shadow"):
            q = q.filter_by(mode=request.args["mode"])
        rows = q.order_by(FcAgentRun.id.desc()).limit(100).all()
        return jsonify({"items": [run_dto(r) for r in rows]})


@finora_core_bp.get("/agent-runs/<run_id>")
@require("audit.view")
def agent_run(run_id: str):
    from .brain.models import FcAgentRun, FcToolCall
    from .brain.observability import run_dto

    if not run_id.isdigit():
        raise not_found("التشغيل غير موجود")
    with core_session() as s:
        run = s.get(FcAgentRun, int(run_id))
        if run is None:
            raise not_found("التشغيل غير موجود")
        calls = s.query(FcToolCall).filter_by(run_id=run.id).order_by(FcToolCall.id).all()
        body = run_dto(run)
        body["toolCalls"] = [{"tool": c.tool, "riskClass": c.risk_class, "status": c.status, "verified": c.verified,
                              "actorType": c.actor_type, "error": c.error} for c in calls]
        return jsonify(body)


@finora_core_bp.get("/tools/registry")
@require("audit.view")
def tool_registry():
    from .brain.registry import describe

    return jsonify({"items": describe()})


@finora_core_bp.get("/automation/flags")
@require("settings.manage")
def get_flags():
    from .brain.policy import all_flags

    with core_session() as s:
        return jsonify(all_flags(s))


@finora_core_bp.post("/automation/flags")
@require("settings.manage")
def set_flags():
    from .brain.policy import FLAGS, all_flags

    data = _json()
    allowed = {"AI_SHADOW_MODE": {"on", "off"}, "AI_AUTO_REPLY": {"on", "off"}, "AI_AUTO_LEAD": {"on", "off"},
               "AI_ACCOUNT_CREATION": {"approval", "off"},
               "AI_TENANT_CONFIGURATION": {"approval", "off"}, "AI_AUTOMATIC_ONBOARDING": {"on", "off"}}
    with core_session() as s:
        for name, value in data.items():
            if name not in FLAGS:
                raise validation_error(f"علم غير معروف: {name}")
            value = str(value).strip().lower()
            if name == "AGENT_DISCOUNT_LIMIT":
                if not value.isdigit() or int(value) > 50:
                    raise validation_error("حد الخصم يجب أن يكون بين 0 و 50")
            elif value not in allowed[name]:
                raise validation_error(f"قيمة غير صالحة لـ {name}")
            set_setting(s, f"flag:{name}", value, _actor())
            audit(s, actor=_actor(), actor_type="human", category="ai", action="flag.set", title=f"تعديل {name}",
                  input_summary=f"{name}={value}")
        s.commit()
        return jsonify(all_flags(s))


# ───────────────────────────── realtime (SSE) ─────────────────────────────


@finora_core_bp.get("/events/stream")
@require()
def stream():
    raw = request.headers.get("Last-Event-ID") or request.args.get("after") or ""
    with core_session() as s:
        latest = int(s.query(db.func.max(FcEvent.seq)).scalar() or 0)
    after = int(raw) if raw.isdigit() else latest  # fresh clients start at "now"; reconnects replay
    owner_inbox = "settings.manage" in current_operator().permissions

    def generate():
        last = after
        started = time.monotonic()
        last_beat = 0.0
        yield f"retry: 3000\n: connected {last}\n\n"
        while time.monotonic() - started < STREAM_LIFETIME_SECONDS:
            run_house_maintenance()
            sync_house()
            with core_session() as s:
                rows = s.query(FcEvent).filter(FcEvent.seq > last).order_by(FcEvent.seq.asc()).limit(200).all()
            for row in rows:
                last = row.seq
                if row.type == "support.issue" and not owner_inbox:
                    continue
                if not owner_inbox and row.type in {"approval.required", "approval.resolved"}:
                    preview = (json.loads(row.payload_json).get("approval") or {}).get("preview") or {}
                    if preview.get("accountScope"):
                        continue
                yield f"id: {row.seq}\nevent: {row.type}\ndata: {row.payload_json}\n\n"
            if time.monotonic() - last_beat > 15:
                last_beat = time.monotonic()
                yield ": ping\n\n"
            time.sleep(0.25 if rows else 1.0)

    headers = {"Content-Type": "text/event-stream", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    g.fc_stream = True
    return Response(stream_with_context(generate()), headers=headers)
