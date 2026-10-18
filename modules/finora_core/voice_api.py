"""Short GPT-Live announcement sessions for authenticated desktop operators."""
from __future__ import annotations

import hashlib
import json
import time

import requests
from flask import jsonify

from .api import _json, finora_core_bp
from .auth import current_operator, require
from .errors import CoreApiError, conflict, not_found, permission_error, validation_error
from .models import FcDesktopSession
from .settings import cloud_key
from .store import core_session, get_setting, set_setting, use_house

ANNOUNCEMENTS = {
    "approval": "عدك طلب موافقة جديد في فينورا. افتح الإشعارات وراجع التفاصيل.",
    "support": "عدك تنبيه مهم يحتاج مراجعتك في فينورا. افتح الإشعارات وشوف التفاصيل.",
    "delivery": "تعذر إرسال رسالة لأحد العملاء. افتح المحادثة وراجع حالة الإرسال.",
    "test": "هلا بيك. هذا صوت إشعارات فينورا. راح أنبهك عند طلب موافقة أو حدث مهم.",
}


def _announcement(s, kind, ref):
    if kind == "test":
        return ANNOUNCEMENTS[kind]
    if not isinstance(ref, str) or not ref.isdigit() or len(ref) > 12:
        raise validation_error("الإشعار غير صالح")
    if kind == "approval":
        if "approvals.decide" not in current_operator().permissions:
            raise permission_error()
        from .brain.models import FcApproval
        row = s.get(FcApproval, int(ref))
        if row is None:
            raise not_found()
        if row.status != "pending":
            raise conflict("تمت مراجعة طلب الموافقة")
    elif kind == "support":
        from .brain.support import FcSupportIssue
        row = s.get(FcSupportIssue, int(ref))
        if row is None:
            raise not_found()
        if row.status != "open":
            raise conflict("تمت معالجة التنبيه")
    elif kind == "delivery":
        from .conversations import get_conversation
        from modules.ai_sales.models import AISalesMessage
        from extensions import db
        with use_house():
            row = db.session.get(AISalesMessage, int(ref))
            if row is None or get_conversation(row.conversation_id) is None:
                raise not_found()
            if row.direction != "outbound" or row.status != "failed":
                raise conflict("حالة الإرسال تغيّرت")
    return ANNOUNCEMENTS[kind]


def _reserve(s):
    operator = current_operator()
    # Serialize across workers and sessions for this operator without a schema migration.
    s.query(FcDesktopSession).filter_by(superadmin_id=operator.superadmin_id).order_by(FcDesktopSession.id).with_for_update().first()
    key = f"voice.rate:{operator.superadmin_id}"
    now = time.time()
    recent = [at for at in json.loads(get_setting(s, key, "[]")) if now - at < 60]
    if len(recent) >= 6:
        raise CoreApiError("RATE_LIMITED", "تنبيهات صوتية كثيرة؛ انتظر لحظة", 429)
    set_setting(s, key, json.dumps(recent + [now]), "FINORA voice")
    s.commit()


@finora_core_bp.post("/voice/notifications/session")
@require("conversations.view")
def create_notification_session():
    data = _json()
    if set(data) - {"kind", "ref", "sdp"}:
        raise validation_error("حقول تنبيه غير صالحة")
    kind, sdp = data.get("kind"), data.get("sdp")
    if not isinstance(kind, str) or kind not in ANNOUNCEMENTS:
        raise validation_error("نوع التنبيه غير صالح")
    if not isinstance(sdp, str) or not sdp.startswith("v=0") or len(sdp.encode()) > 65536:
        raise validation_error("طلب الاتصال الصوتي غير صالح")
    with core_session() as s:
        announcement = _announcement(s, kind, data.get("ref"))
        key = cloud_key(s)
        if not key:
            raise CoreApiError("VOICE_UNAVAILABLE", "أضف المفتاح السحابي حتى يعمل GPT Live", 503)
        _reserve(s)
    try:
        response = requests.post("https://api.openai.com/v1/live/sessions", timeout=20,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "OpenAI-Safety-Identifier": hashlib.sha256(f"finora-operator:{current_operator().superadmin_id}".encode()).hexdigest()},
            json={"session": {"model": "gpt-live-1", "store": False,
                  "audio": {"output": {"voice": "marin"}},
                  "instructions": "You are the FINORA notification voice. Speak one short announcement in clear Iraqi Arabic when instructed, then stay silent. Do not greet spontaneously, ask questions, use tools, or invent details. Never read customer names, contact details, passwords or tokens."},
                  "transport": {"type": "webrtc", "sdp": sdp}})
        if not response.ok:
            raise CoreApiError("VOICE_UNAVAILABLE", "تعذر تشغيل GPT Live؛ تأكد من إتاحته للمفتاح السحابي", 502)
        result = response.json()
        session_id, answer = result["session"]["id"], result["transport"]["sdp"]
        if not isinstance(session_id, str) or not isinstance(answer, str) or not answer.startswith("v=0"):
            raise ValueError("Invalid Live session response")
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise CoreApiError("VOICE_UNAVAILABLE", "الاتصال بالصوت المباشر غير متاح حالياً", 502, retryable=True) from None
    return jsonify({"session": {"id": session_id}, "transport": {"type": "webrtc", "sdp": answer},
                    "announcement": announcement, "model": "gpt-live-1"}), 201
