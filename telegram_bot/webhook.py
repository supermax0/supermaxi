"""
Flask blueprint لمسارات تيليجرام:
  - POST /telegram/webhook   — استقبال التحديثات من تيليجرام
  - GET  /telegram/setup-webhook — ضبط عنوان الـ webhook عند تيليجرام
  - GET  /telegram/test       — إرسال رسالة تجريبية إلى محادثة معيّنة
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

import requests
from flask import Blueprint, current_app, g, jsonify, request, session

from telegram_bot.agent_templates import (
    create_agent_from_template,
    list_templates,
    get_template,
)
from telegram_bot.ai_agent import generate_ai_reply
from telegram_bot.listener import parse_telegram_update
from telegram_bot.ready_agent import ensure_telegram_agent
from telegram_bot.sender import send_telegram_reply

logger = logging.getLogger(__name__)

telegram_bp = Blueprint("telegram", __name__, url_prefix="/telegram")


def _get_bot_token() -> str:
    """قراءة توكن البوت من الإعدادات أو من متغيرات البيئة (BOT_TOKEN / TELEGRAM_BOT_TOKEN)."""
    return (
        (current_app.config.get("TELEGRAM_BOT_TOKEN") or "")
        or (current_app.config.get("BOT_TOKEN") or "")
        or (os.getenv("BOT_TOKEN") or "")
        or (os.getenv("TELEGRAM_BOT_TOKEN") or "")
    ).strip()


def _get_openai_key() -> str:
    """قراءة مفتاح OpenAI من الإعدادات أو من متغير البيئة OPENAI_API_KEY."""
    api_key = (
        (current_app.config.get("OPENAI_API_KEY") or "")
        or (os.getenv("OPENAI_API_KEY") or "")
    ).strip()

    if api_key:
        return api_key

    # fallback: GlobalSetting (whole system)
    try:
        from models.core.global_setting import GlobalSetting
        old_tenant = getattr(g, "tenant", None)
        g.tenant = None  # force core DB
        api_key = (GlobalSetting.get_setting("OPENAI_API_KEY", "") or "").strip()
    except Exception:
        api_key = ""
    finally:
        try:
            g.tenant = old_tenant  # type: ignore[name-defined]
        except Exception:
            pass
    return api_key


def _get_openai_model() -> str:
    return current_app.config.get("OPENAI_MODEL") or "gpt-4o-mini"


@telegram_bp.route("/webhook", methods=["POST"])
def webhook():
    """
    استقبال التحديثات من تيليجرام (POST من Telegram Bot API).

    المسار: استخراج chat_id و message_text → توليد رد بالـ AI → إرسال الرد → إرجاع {"status":"ok"}.
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception as e:
        logger.warning("Telegram webhook: invalid JSON body: %s", e)
        return jsonify({"status": "ok"}), 200

    logger.info("Telegram webhook: received update, keys=%s", list(data.keys()))

    chat_id, message_text = parse_telegram_update(data)
    logger.info("Telegram webhook: chat_id=%s has_text=%s", chat_id, bool(message_text))

    # إذا لا يوجد نص (مثلاً المستخدم أرسل صورة فقط)، نرد بجملة قصيرة
    if not message_text:
        message_text = ""
    if not chat_id:
        logger.debug("Telegram webhook: no chat_id, skipping reply")
        return jsonify({"status": "ok"}), 200

    # توليد الرد بالذكاء الاصطناعي
    api_key = _get_openai_key()
    model = _get_openai_model()
    ai_reply = generate_ai_reply(message_text, api_key=api_key, model=model)

    if not ai_reply:
        ai_reply = "عذراً، لم أستطع توليد رد الآن. جرّب لاحقاً."

    # إرسال الرد إلى تيليجرام
    bot_token = _get_bot_token()
    if not bot_token:
        logger.error("Telegram webhook: BOT_TOKEN not set; cannot send reply")
        return jsonify({"status": "ok"}), 200

    send_telegram_reply(bot_token, chat_id, ai_reply)

    return jsonify({"status": "ok"}), 200


@telegram_bp.route("/webhook/<tenant_slug>/<int:workflow_id>", methods=["POST"])
def webhook_for_workflow(tenant_slug: str, workflow_id: int):
    """
    Webhook مرتبط بوورك فلو محدد: يحمّل التوكن من عقدة telegram_listener في الرسم
    وينفّذ الـ workflow (بدون الاعتماد على BOT_TOKEN في البيئة).
    """
    from api_workflows import _run_workflow_in_background
    from extensions import db
    from models.ai_agent import AgentExecution, AgentWorkflow

    tenant_slug = (tenant_slug or "").strip()
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception as e:
        logger.warning("Telegram workflow webhook: invalid JSON: %s", e)
        return jsonify({"ok": True}), 200

    chat_id, message_text = parse_telegram_update(data)
    if not chat_id:
        return jsonify({"ok": True}), 200

    old_tenant = getattr(g, "tenant", None)
    g.tenant = tenant_slug
    try:
        wf = AgentWorkflow.query.get(workflow_id)
        if not wf or (wf.agent and (wf.agent.tenant_slug or "") != tenant_slug):
            logger.warning(
                "Telegram workflow webhook: workflow %s not found or tenant mismatch",
                workflow_id,
            )
            return jsonify({"ok": True}), 200

        bot_token = ""
        for n in (wf.graph_json or {}).get("nodes") or []:
            if (n.get("type") or "") == "telegram_listener":
                bot_token = ((n.get("data") or {}).get("bot_token") or "").strip()
                if bot_token:
                    break
        if not bot_token:
            logger.error(
                "Telegram workflow webhook: no bot_token on telegram_listener for workflow %s",
                workflow_id,
            )
            return jsonify({"ok": True}), 200

        initial_context: dict[str, Any] = {
            "message_text": message_text or "",
            "chat_id": str(chat_id),
            "telegram_bot_token": bot_token,
            "workflow_id": wf.id,
            "tenant_slug": (wf.agent.tenant_slug if wf.agent else None),
        }

        try:
            from social_ai.telegram_inbox import record_telegram_inbox_message

            if (message_text or "").strip():
                record_telegram_inbox_message(
                    (wf.agent.tenant_slug if wf.agent else None),
                    wf.id,
                    str(chat_id),
                    "user",
                    message_text or "",
                )
        except Exception:
            logger.debug("telegram inbox user record skipped", exc_info=True)

        exe = AgentExecution(workflow_id=wf.id, status="running")
        db.session.add(exe)
        db.session.commit()

        app_obj = current_app._get_current_object()
        threading.Thread(
            target=_run_workflow_in_background,
            args=(app_obj, exe.id, tenant_slug, initial_context),
            daemon=True,
        ).start()
    finally:
        g.tenant = old_tenant

    return jsonify({"ok": True}), 200


@telegram_bp.route("/setup-webhook", methods=["GET"])
def setup_webhook():
    """
    ضبط عنوان الـ webhook عند تيليجرام بحيث يرسل التحديثات إلى هذا السيرفر.

    يجب أن يكون التطبيق متاحاً عبر HTTPS على النطاق الذي تضعه في الـ URL.
    """
    bot_token = _get_bot_token()
    if not bot_token:
        return jsonify({"ok": False, "error": "BOT_TOKEN or TELEGRAM_BOT_TOKEN not set"}), 500

    # بناء رابط الـ webhook: استخدام BASE_URL أو طلب الحالي
    base = current_app.config.get("BASE_URL") or ""
    if not base:
        base = request.url_root.rstrip("/")
    webhook_url = f"{base}/telegram/webhook"

    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    try:
        resp = requests.post(url, json={"url": webhook_url}, timeout=10)
        body = resp.json() if resp.text else {}
        if not resp.ok:
            return jsonify({"ok": False, "telegram_response": body}), 400
        return jsonify({"ok": True, "webhook_url": webhook_url, "telegram_response": body}), 200
    except Exception as e:
        logger.exception("setup-webhook error: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@telegram_bp.route("/agent-templates", methods=["GET"])
def agent_templates_list():
    """قائمة قوالب الوكلاء الجاهزة (تيليجرام، واتساب، رد التعليقات)."""
    return jsonify({"ok": True, "templates": list_templates()}), 200


@telegram_bp.route("/create-from-template", methods=["POST"])
def create_from_template():
    """
    إنشاء وكيل جديد + workflow من قالب.
    Body: { "template_id": "telegram" | "whatsapp" | "comment_reply", "agent_name": "اختياري", "workflow_name": "اختياري" }
    """
    try:
        data = request.get_json() or {}
        template_id = (data.get("template_id") or "").strip()
        if not template_id:
            return jsonify({"ok": False, "error": "template_id مطلوب"}), 400
        if not get_template(template_id):
            return jsonify({"ok": False, "error": f"قالب غير موجود: {template_id}"}), 400

        tenant_slug = getattr(g, "tenant", None)
        user_id = data.get("user_id") or session.get("user_id")

        agent, workflow = create_agent_from_template(
            template_id,
            tenant_slug=tenant_slug,
            user_id=user_id,
            agent_name=(data.get("agent_name") or "").strip() or None,
            workflow_name=(data.get("workflow_name") or "").strip() or None,
        )
        return jsonify({
            "ok": True,
            "agent_id": agent.id,
            "workflow_id": workflow.id,
            "agent": agent.to_dict(),
            "workflow": workflow.to_dict(),
        }), 201
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("create_from_template failed: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@telegram_bp.route("/ensure-agent", methods=["GET"])
def ensure_agent():
    """
    إنشاء وكيل تيليجرام جاهز (Agent + Workflow) إن لم يكن موجوداً.
    مفيد لاستخدامه مع مسار الـ webhook الذي يتطلب workflow_id (مثلاً من لوحة Autoposter).
    """
    try:
        tenant_slug = getattr(g, "tenant", None)
        agent, workflow = ensure_telegram_agent(tenant_slug=tenant_slug)
        return jsonify({
            "ok": True,
            "agent_id": agent.id,
            "workflow_id": workflow.id,
            "message": "الوكيل جاهز. استخدم workflow_id في استدعاء webhook مع workflow_id.",
        }), 200
    except Exception as e:
        logger.exception("ensure_agent failed: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500


@telegram_bp.route("/test", methods=["GET"])
def test():
    """
    إرسال رسالة تجريبية إلى محادثة معيّنة.
    استخدم: /telegram/test?chat_id=123456789
    """
    bot_token = _get_bot_token()
    if not bot_token:
        return jsonify({"ok": False, "error": "BOT_TOKEN not set"}), 500

    chat_id = request.args.get("chat_id", "").strip()
    if not chat_id:
        return jsonify({"ok": False, "error": "chat_id query parameter required"}), 400

    test_message = "هذه رسالة تجريبية من بوت تيليجرام. البوت يعمل بشكل صحيح."
    success = send_telegram_reply(bot_token, chat_id, test_message)
    if not success:
        return jsonify({"ok": False, "error": "Failed to send message"}), 500
    return jsonify({"ok": True, "message": "Test message sent", "chat_id": chat_id}), 200
