"""Core-only media endpoints. Credentials and internal storage paths never reach the desktop."""
from __future__ import annotations

import hashlib
import json

from flask import Response, jsonify, request, send_file
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.ai_sales.models import AISalesMessage
from modules.ai_sales.meta_reliability import record_send_failure, record_send_success
from .api import finora_core_bp, _conv_id
from .auth import current_operator, require
from . import conversations as convs
from .errors import CoreApiError, conflict, not_found, validation_error
from .media import MAX_UPLOAD, attachment, save_upload, send_stored, signer, stored_path
from .models import FcIdempotency
from .store import audit, core_session, emit, msg_ref, use_house


def _message(cid: int, mid: int):
    if convs.get_conversation(cid) is None:
        raise not_found("المحادثة غير موجودة")
    message = AISalesMessage.query.filter_by(id=mid, conversation_id=cid).first()
    if message is None:
        raise not_found("الرسالة غير موجودة")
    return message


def _file_response(item, slug):
    path = stored_path(item, slug)
    mime = str(item.get("mime_type") or "application/octet-stream")
    from .media import KINDS
    safe_mime = mime if mime in KINDS else "application/octet-stream"
    response = send_file(path, mimetype=safe_mime, download_name=path.name, conditional=True,
                         as_attachment=safe_mime == "application/octet-stream", max_age=0)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@finora_core_bp.get("/conversations/<raw_id>/messages/<raw_mid>/attachments/<aid>")
@require("conversations.view")
def get_media(raw_id, raw_mid, aid):
    with use_house() as slug:
        return _file_response(attachment(_message(_conv_id(raw_id), _conv_id(raw_mid)), aid), slug)


@finora_core_bp.get("/media/delivery/<token>")
def deliver_media(token):
    # Meta fetches the bounded asset without a desktop bearer token; the signed capability expires in ten minutes.
    try:
        data = signer().loads(token, max_age=600)
    except (BadSignature, SignatureExpired):
        raise not_found("الرابط غير صالح أو انتهت صلاحيته") from None
    with use_house() as slug:
        if data.get("slug") != slug:
            raise not_found()
        message = _message(int(data["cid"]), int(data["mid"]))
        if message.direction != "outbound" or not message.get_media_metadata().get("core_media"):
            raise not_found()
        item = attachment(message, str(data["aid"]))
        if item.get("sha256") != data.get("hash"):
            raise not_found()
        return _file_response(item, slug)


@finora_core_bp.post("/conversations/<raw_id>/media")
@require("messages.send")
def send_media(raw_id):
    cid = _conv_id(raw_id)
    key = str(request.headers.get("Idempotency-Key") or "").strip()
    if not key or len(key) > 100:
        raise validation_error("Idempotency-Key مطلوب")
    if request.content_length is None or request.content_length > MAX_UPLOAD + 128 * 1024:
        raise CoreApiError("VALIDATION_ERROR", "حجم الطلب أكبر من الحد المسموح للوسائط", 413)
    upload = request.files.get("file")
    if not upload or not upload.filename:
        raise validation_error("اختر المرفق أولاً")
    content = upload.read(MAX_UPLOAD + 1)
    op = current_operator()
    scoped_key = f"{op.superadmin_id}:media:{hashlib.sha256(key.encode()).hexdigest()}"
    fingerprint = "media:" + hashlib.sha256(str(cid).encode() + content + str(upload.mimetype).encode()).hexdigest()
    with core_session() as s:
        prior = s.get(FcIdempotency, scoped_key)
        if prior:
            if prior.route != fingerprint:
                raise conflict("مفتاح الإرسال مستخدم لملف أو محادثة أخرى")
            return Response(prior.response_json, status=prior.status_code, mimetype="application/json")
    with use_house() as slug:
        conv = convs.get_conversation(cid)
        if conv is None:
            raise not_found("المحادثة غير موجودة")
        from .brain.shadow import shadow_enabled
        if convs.control(conv) == "ai" and not shadow_enabled():
            raise conflict("استلم المحادثة أولاً قبل إرسال المرفق")
        if conv.status == "closed":
            raise conflict("المحادثة مغلقة؛ أعد فتحها قبل الإرسال")
        item = save_upload(content, str(upload.mimetype).lower(), upload.filename, slug)
        pending_body = json.dumps({"error": {"code": "CONFLICT", "message": "إرسال هذا المرفق جارٍ؛ حدّث المحادثة قبل المحاولة", "retryable": True}}, ensure_ascii=False)
        try:
            with core_session() as s:
                s.add(FcIdempotency(key=scoped_key, superadmin_id=op.superadmin_id, route=fingerprint,
                                    status_code=409, response_json=pending_body))
                s.commit()
        except IntegrityError:
            stored_path(item, slug).unlink(missing_ok=True)
            raise conflict("إرسال المرفق جارٍ بالفعل") from None
        message = AISalesMessage(conversation_id=cid, channel_account_id=conv.channel_account_id,
                                 direction="outbound", sender_type="employee", message_type=item["kind"],
                                 text_content="", mime_type=item["mime_type"], status="queued")
        message.set_media_metadata({"core_media": True, "attachments": [item]})
        db.session.add(message)
        db.session.commit()  # Meta fetches the signed URL in a separate request and must see the message.
        try:
            record_send_success(message, conv.channel, send_stored(message, slug))
            conv.last_business_message_at = message.sent_at
        except Exception as exc:
            record_send_failure(message, conv.channel, exc)
        db.session.commit()
        dto = convs.message_dto(message)
        status = 502 if message.status == "failed" else 202 if message.status == "retry_scheduled" else 201
    body = {"message": dto}
    if status == 502:
        body["error"] = {"code": "META_SEND_FAILED", "message": "تعذر إرسال المرفق عبر القناة", "retryable": False}
    with core_session() as s:
        prior = s.get(FcIdempotency, scoped_key)
        prior.response_json, prior.status_code = json.dumps(body, ensure_ascii=False), status
        audit(s, actor=op.username, actor_type="human", category="messages" if status != 502 else "errors",
              action="message.media_send", title="إرسال مرفق" if status != 502 else "فشل إرسال المرفق",
              conversation_ref=str(cid), result="failed" if status == 502 else "ok")
        emit(s, "message.sent", {"message": dto}, dedupe_key=f"msg:{msg_ref(dto['id'], dto['at'])}:new")
        s.commit()
    return jsonify(body), status


@finora_core_bp.post("/conversations/<raw_id>/messages/<raw_mid>/attachments/<aid>/analyze")
@require("messages.send")
def analyze_media(raw_id, raw_mid, aid):
    from .media_analysis import analyze
    from .brain.provider import ProviderError
    cid = _conv_id(raw_id)
    with use_house() as slug:
        message = _message(cid, _conv_id(raw_mid))
        try:
            result = analyze(message, aid, slug)
        except ProviderError as exc:
            raise conflict(str(exc)) from exc
        dto = convs.message_dto(message)
    with core_session() as s:
        emit(s, "message.updated", {"message": dto})
        audit(s, actor=current_operator().username, actor_type="human", category="ai",
              action="media.analyze", title="تحليل مرفق", conversation_ref=str(cid),
              result="ok" if result["status"] == "completed" else "failed")
        s.commit()
    return jsonify({"message": dto})
