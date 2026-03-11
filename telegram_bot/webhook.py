"""
Flask blueprint لمسارات تيليجرام:
  - POST /telegram/webhook   — استقبال التحديثات من تيليجرام
  - GET  /telegram/setup-webhook — ضبط عنوان الـ webhook عند تيليجرام
  - GET  /telegram/test       — إرسال رسالة تجريبية إلى محادثة معيّنة
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from flask import Blueprint, current_app, jsonify, request

from telegram_bot.ai_agent import generate_ai_reply
from telegram_bot.listener import parse_telegram_update
from telegram_bot.sender import send_telegram_reply

logger = logging.getLogger(__name__)

telegram_bp = Blueprint("telegram", __name__, url_prefix="/telegram")


def _get_bot_token() -> str:
    """قراءة توكن البوت من إعدادات التطبيق (BOT_TOKEN أو TELEGRAM_BOT_TOKEN)."""
    return (
        (current_app.config.get("TELEGRAM_BOT_TOKEN") or "")
        or (current_app.config.get("BOT_TOKEN") or "")
    ).strip()


def _get_openai_key() -> str:
    """قراءة مفتاح OpenAI من الإعدادات."""
    return (current_app.config.get("OPENAI_API_KEY") or "").strip()


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

    logger.debug("Telegram webhook received: keys=%s", list(data.keys()))

    chat_id, message_text = parse_telegram_update(data)

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
