import os
from typing import Any

import requests
from flask import Blueprint, current_app, jsonify, render_template, request

from models.ai_agent import AgentWorkflow


whatsapp_webhook_bp = Blueprint("whatsapp_webhook", __name__)


def _send_whatsapp_reply(to_phone: str, text: str) -> tuple[bool, Any]:
    token = (os.getenv("WHATSAPP_TOKEN") or "").strip()
    phone_number_id = (os.getenv("PHONE_NUMBER_ID") or "").strip()

    if not token or not phone_number_id:
        return False, "WHATSAPP_TOKEN أو PHONE_NUMBER_ID غير مضبوط"

    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": text},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        body = resp.json() if resp.text else {}
        if not resp.ok:
            return False, body
        return True, body
    except Exception as e:
        return False, str(e)


def _extract_incoming_message(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    يدعم شكل Webhook الخاص بـ WhatsApp Cloud API.
    يرجع (sender_phone, message_text)
    """
    try:
        entries = payload.get("entry") or []
        for entry in entries:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                for msg in value.get("messages") or []:
                    sender = msg.get("from")
                    text_obj = msg.get("text") or {}
                    text = text_obj.get("body")
                    if sender and text:
                        return str(sender), str(text)
    except Exception:
        return None, None
    return None, None


def _extract_phone_number_id(payload: dict[str, Any]) -> str:
    try:
        entries = payload.get("entry") or []
        for entry in entries:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                metadata = value.get("metadata") or {}
                pid = str(metadata.get("phone_number_id") or "").strip()
                if pid:
                    return pid
    except Exception:
        return ""
    return ""


def _guess_workflow_id_for_whatsapp(phone_number_id: str) -> int | None:
    """Try matching workflow that has whatsapp_listener with same phone_id."""
    if not phone_number_id:
        return None
    try:
        rows = AgentWorkflow.query.order_by(AgentWorkflow.updated_at.desc()).limit(500).all()
        for wf in rows:
            graph = wf.graph_json or {}
            for n in graph.get("nodes") or []:
                if not isinstance(n, dict):
                    continue
                if (n.get("type") or "") != "whatsapp_listener":
                    continue
                data = n.get("data") or {}
                pid = str(data.get("phone_id") or "").strip()
                if pid and pid == phone_number_id:
                    return int(wf.id)
    except Exception:
        return None
    return None


@whatsapp_webhook_bp.route("/webhook", methods=["GET", "POST"])
def whatsapp_webhook():
    verify_token = (os.getenv("VERIFY_TOKEN") or "75428468").strip()

    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        # فتح /webhook مباشرة من المتصفح بدون باراميترات
        if not mode and not token and not challenge:
            return jsonify({"status": "ok", "message": "Webhook Running"})

        # وضع اختبار بسيط من الواجهة
        if request.args.get("test") == "1":
            return jsonify({"status": "ok", "message": "Webhook Running"})

        # نقبل التحقق الرسمي (mode=subscribe) وأيضاً الروابط اليدوية التي ترسل token+challenge فقط.
        if ((mode == "subscribe") or (mode is None and challenge is not None)) and token == verify_token:
            current_app.logger.info("WhatsApp webhook verified successfully.")
            return challenge or "", 200
        current_app.logger.warning("WhatsApp webhook verification failed.")
        return jsonify({"error": "Verification failed"}), 403

    # POST
    payload = request.get_json(silent=True) or {}
    current_app.logger.info("Incoming WhatsApp webhook payload: %s", payload)

    sender, message_text = _extract_incoming_message(payload)
    if not sender or not message_text:
        return jsonify({"status": "ignored", "reason": "no_message"}), 200

    current_app.logger.info("Incoming message from %s: %s", sender, message_text)

    # Store incoming WhatsApp message in unified inbox (if matching workflow is found).
    try:
        from social_ai.telegram_inbox import record_inbox_message

        phone_number_id = _extract_phone_number_id(payload)
        wf_id = _guess_workflow_id_for_whatsapp(phone_number_id)
        if wf_id:
            record_inbox_message(None, wf_id, "whatsapp", sender, "user", message_text[:4096])
    except Exception:
        current_app.logger.exception("whatsapp inbox store failed")

    ok, result = _send_whatsapp_reply(sender, "هلا 👋 تم استلام رسالتك")
    if not ok:
        current_app.logger.error("WhatsApp reply failed: %s", result)
        return jsonify({"status": "received", "reply_sent": False, "error": result}), 200

    return jsonify({"status": "received", "reply_sent": True, "result": result}), 200


@whatsapp_webhook_bp.route("/webhook-ui", methods=["GET"])
def whatsapp_webhook_ui():
    return render_template("webhook_index.html")

