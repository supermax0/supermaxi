"""Facebook page monitor. Read-only operations center."""
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, render_template, request, send_file, session

from extensions import db
from models.employee import Employee
from utils.meta_graph import GRAPH_BASE

facebook_monitor_bp = Blueprint(
    "facebook_monitor",
    __name__,
    template_folder="../../templates",
)


@facebook_monitor_bp.before_request
def _ensure_schema_before_facebook_monitor():
    # This blueprint (its public /webhooks/facebook route included) reads
    # ai_sales_channel_account directly without ever going through ai_sales_bp's
    # own before_request hook, so a column added to that model (e.g. the
    # TikTok fields) would otherwise 500 here on any database where
    # ai_sales_bp hasn't been hit yet to run its migration. Not session-gated
    # since the webhook route has no session.
    from modules.ai_sales.schema import ensure_ai_sales_schema

    ensure_ai_sales_schema()


def _logged_in_employee():
    if session.get("is_superadmin") or session.get("role") == "admin":
        return True
    if not session.get("user_id"):
        return False
    employee = Employee.query.get(session.get("user_id"))
    return bool(employee and employee.is_active)


def _viewer():
    if not session.get("user_id") and not session.get("is_superadmin"):
        return None, (jsonify({"ok": False, "error": "auth"}), 401)
    if session.get("is_superadmin") or session.get("role") == "admin":
        return {"name": session.get("user_name") or session.get("username") or "المدير", "avatar": ""}, None
    employee = Employee.query.get(session.get("user_id"))
    if not employee:
        return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
    allowed = bool(getattr(employee, "can_see_reports", False))
    if not allowed:
        from utils.permission_checks import employee_can

        allowed = employee_can(employee, "use_employee_desk")
    if not allowed:
        return None, (jsonify({"ok": False, "error": "forbidden"}), 403)
    return {
        "name": employee.name,
        "avatar": ("/" + employee.profile_pic) if employee.profile_pic else "",
    }, None


def _args():
    data = request.args.to_dict(flat=True)
    return data


def _tenant_id():
    try:
        return int(session.get("tenant_id") or 0) or None
    except (TypeError, ValueError):
        return None


def _tenant_slug():
    return session.get("tenant_slug") or None


@facebook_monitor_bp.get("/facebook-monitor")
def monitor_page():
    viewer, error = _viewer()
    if error:
        from flask import redirect
        return redirect("/login")
    return render_template("facebook_monitor/index.html", viewer=viewer)


def _avatar_fallback(letter: str = "ف"):
    import html
    from flask import Response

    mark = html.escape((letter or "ف")[:2])
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
        '<rect width="64" height="64" rx="32" fill="#650016"/>'
        f'<text x="32" y="40" text-anchor="middle" fill="#fff" font-size="26" font-family="Arial, sans-serif">{mark}</text>'
        "</svg>"
    )
    return Response(svg, status=200, content_type="image/svg+xml", headers={"Cache-Control": "private, max-age=300"})


@facebook_monitor_bp.get("/api/facebook-monitor/page-avatar/<page_id>")
def page_avatar(page_id: str):
    """Letter avatar only — Graph picture calls burned the app limit."""
    _, error = _viewer()
    if error:
        return error
    return _avatar_fallback()


def _page_token_only(page_id: str) -> str:
    from modules.publisher.models.publisher_page import PublisherPage
    from modules.publisher.services.token_utils import decrypt_token

    row = PublisherPage.query.filter_by(page_id=page_id).first()
    if row and row.page_token:
        try:
            token = decrypt_token(row.page_token) or ""
            if token:
                return token
        except Exception:
            pass
    from modules.ai_sales.models import AISalesChannelAccount

    channel = AISalesChannelAccount.query.filter(
        AISalesChannelAccount.page_id == page_id,
        AISalesChannelAccount.channel_type.in_(("messenger", "facebook")),
    ).first()
    if channel and channel.access_token_encrypted:
        try:
            token = decrypt_token(channel.access_token_encrypted) or ""
            if token:
                return token
        except Exception:
            pass
        try:
            from modules.ai_sales.security import decrypt_secret

            return decrypt_secret(channel.access_token_encrypted) or ""
        except Exception:
            return ""
    return ""


_AVATAR_BYTES = {}
_AVATAR_BYTES_TTL = 3600
_IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def _allowed_pic_url(url: str) -> str:
    from urllib.parse import urlparse

    value = str(url or "").strip()
    if not value.startswith("https://"):
        return ""
    host = (urlparse(value).hostname or "").lower()
    if not any(host == part or host.endswith("." + part) for part in ("fbcdn.net", "facebook.com", "fbsbx.com", "fb.com")):
        return ""
    return value


def _fetch_image(url: str, token: str = "") -> tuple[bytes, str] | None:
    import requests

    if not url:
        return None
    params = {"access_token": token} if token and "access_token=" not in url else None
    response = requests.get(url, params=params, headers=_IMAGE_HEADERS, timeout=10, allow_redirects=True)
    if response.status_code >= 400 or not response.content or len(response.content) < 80:
        return None
    content_type = response.headers.get("Content-Type") or "image/jpeg"
    if "text/" in content_type or "json" in content_type or "svg" in content_type:
        return None
    return response.content, content_type


def _picture_from_profile(profile: dict | None) -> str:
    if not isinstance(profile, dict) or profile.get("error"):
        return ""
    pic = str(profile.get("profile_pic") or "").strip()
    if pic:
        return pic
    picture = profile.get("picture") or {}
    data = picture.get("data") if isinstance(picture, dict) else {}
    if isinstance(data, dict) and not data.get("is_silhouette"):
        return str(data.get("url") or "").strip()
    return ""


def _remember_conversation_pic(page_id: str, psid: str, url: str) -> None:
    if not url:
        return
    try:
        from modules.facebook_routing.engine import conversation_for_psid

        conversation = conversation_for_psid(page_id, psid)
        if conversation and not conversation.contact_profile_picture_url:
            conversation.contact_profile_picture_url = url[:800]
            from extensions import db

            db.session.commit()
    except Exception:
        pass


@facebook_monitor_bp.get("/api/facebook-monitor/customer-avatar")
def customer_avatar():
    """Proxy a Facebook/Messenger photo URL. Does not call Graph per face (rate limits)."""
    if not _logged_in_employee():
        return _avatar_fallback((request.args.get("letter") or "ف").strip()[:2] or "ف")
    import time
    import re
    from flask import Response
    from modules.facebook_routing.engine import conversation_for_psid

    page_id = re.sub(r"\D", "", str(request.args.get("page_id") or ""))
    psid = re.sub(r"\D", "", str(request.args.get("psid") or ""))
    letter = (request.args.get("letter") or "ف").strip()[:2] or "ف"
    hint = _allowed_pic_url(request.args.get("src") or "")
    if not hint and page_id and psid:
        conversation = conversation_for_psid(page_id, psid)
        hint = _allowed_pic_url(getattr(conversation, "contact_profile_picture_url", "") if conversation else "")
    if not page_id or not psid:
        return _avatar_fallback(letter)
    cached = _AVATAR_BYTES.get(psid)
    if cached and cached[0] > time.time() - _AVATAR_BYTES_TTL:
        data, content_type = cached[1], cached[2]
        return Response(data, status=200, content_type=content_type, headers={"Cache-Control": "private, max-age=3600"})
    if hint:
        fetched = _fetch_image(hint)
        if fetched:
            data, content_type = fetched
            _AVATAR_BYTES[psid] = (time.time(), data, content_type)
            _remember_conversation_pic(page_id, psid, hint)
            return Response(data, status=200, content_type=content_type, headers={"Cache-Control": "private, max-age=3600"})
    return _avatar_fallback(letter)


@facebook_monitor_bp.post("/api/facebook-monitor/pull-conversations")
def pull_conversations():
    _viewer_row, error = _viewer()
    if error:
        return error
    if not (session.get("is_superadmin") or session.get("role") == "admin"):
        return jsonify({"ok": False, "error": "غير مصرح"}), 403
    from modules.facebook_monitor.service import pull_facebook_conversations

    data = request.get_json(silent=True) or {}
    try:
        limit = int(data.get("limit") or 25)
    except (TypeError, ValueError):
        limit = 25
    result = pull_facebook_conversations(limit)
    code = 200 if result.get("ok") else 400
    return jsonify(result), code


@facebook_monitor_bp.get("/api/facebook-monitor/snapshot")
def snapshot():
    viewer, error = _viewer()
    if error:
        return error
    from modules.publisher.services.schema_guard import ensure_publisher_schema
    from modules.facebook_monitor.service import build_snapshot

    try:
        ensure_publisher_schema(force=True)
        payload = build_snapshot(_args(), tenant_id=_tenant_id(), tenant_slug=_tenant_slug())
        payload["viewer"] = viewer
        return jsonify({"ok": True, **payload})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@facebook_monitor_bp.get("/api/facebook-monitor/overview")
def overview():
    viewer, error = _viewer()
    if error:
        return error
    from modules.facebook_monitor.service import build_snapshot

    payload = build_snapshot(_args(), tenant_id=_tenant_id(), tenant_slug=_tenant_slug())
    return jsonify({"ok": True, "overview": payload["overview"], "meta": payload["meta"]})


@facebook_monitor_bp.get("/api/facebook-monitor/pages/<path:page_id>")
def page(page_id: str):
    _, error = _viewer()
    if error:
        return error
    from modules.facebook_monitor.service import page_detail

    detail = page_detail(page_id, {**_args(), "tenant_slug": _tenant_slug()}, tenant_id=_tenant_id())
    if not detail:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "page": detail})


@facebook_monitor_bp.get("/api/facebook-monitor/pages")
def pages():
    _, error = _viewer()
    if error:
        return error
    from modules.facebook_monitor.service import build_snapshot

    payload = build_snapshot(_args(), tenant_id=_tenant_id(), tenant_slug=_tenant_slug())
    return jsonify({"ok": True, "pages": payload["pages"]})


@facebook_monitor_bp.get("/api/facebook-monitor/messages")
def messages():
    _, error = _viewer()
    if error:
        return error
    from modules.facebook_monitor.service import build_snapshot

    payload = build_snapshot(_args(), tenant_id=_tenant_id(), tenant_slug=_tenant_slug())
    return jsonify({
        "ok": True,
        "messages": payload["messages"],
        "next_cursor": payload["next_cursor"],
        "status_counts": payload["status_counts"],
    })


@facebook_monitor_bp.get("/api/facebook-monitor/employees")
def employees():
    _, error = _viewer()
    if error:
        return error
    from modules.facebook_monitor.service import build_snapshot

    payload = build_snapshot(_args(), tenant_id=_tenant_id(), tenant_slug=_tenant_slug())
    return jsonify({"ok": True, "employees": payload["employees"]})


@facebook_monitor_bp.get("/api/facebook-monitor/employees/<int:employee_id>")
def employee(employee_id: int):
    _, error = _viewer()
    if error:
        return error
    from modules.facebook_monitor.service import employee_detail

    detail = employee_detail(employee_id, {**_args(), "tenant_slug": _tenant_slug()}, tenant_id=_tenant_id())
    if not detail:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "employee": detail})


@facebook_monitor_bp.get("/api/facebook-monitor/ads/<path:ad_id>")
def ad(ad_id: str):
    _, error = _viewer()
    if error:
        return error
    from modules.facebook_monitor.service import ad_detail

    detail = ad_detail(ad_id, {**_args(), "tenant_slug": _tenant_slug()}, tenant_id=_tenant_id())
    if not detail:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "ad": detail})


@facebook_monitor_bp.get("/api/facebook-monitor/ads")
def ads():
    _, error = _viewer()
    if error:
        return error
    from modules.facebook_monitor.service import build_snapshot

    payload = build_snapshot(_args(), tenant_id=_tenant_id(), tenant_slug=_tenant_slug())
    return jsonify({"ok": True, "ads": payload["ads"]})


@facebook_monitor_bp.get("/api/facebook-monitor/thread")
def get_thread():
    _, error = _viewer()
    if error:
        return error
    from modules.facebook_monitor.chat import ChatError, fetch_thread

    try:
        data = fetch_thread(
            thread_id=str(request.args.get("thread_id") or ""),
            external_page_id=str(request.args.get("page_id") or ""),
            customer_psid=str(request.args.get("customer_psid") or ""),
        )
        return jsonify({"ok": True, "thread": data})
    except ChatError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@facebook_monitor_bp.post("/api/facebook-monitor/thread/reply")
def reply_thread():
    _, error = _viewer()
    if error:
        return error
    from modules.facebook_monitor.chat import ChatError, send_text

    body = request.get_json(silent=True) or {}
    if not _can_reply_thread(str(body.get("page_id") or ""), str(body.get("customer_psid") or "")):
        return jsonify({"ok": False, "error": "هذه المحادثة ليست مسندة لك"}), 403
    try:
        message = send_text(
            external_page_id=str(body.get("page_id") or ""),
            customer_psid=str(body.get("customer_psid") or ""),
            text=str(body.get("text") or ""),
        )
        return jsonify({"ok": True, "message": message})
    except ChatError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@facebook_monitor_bp.post("/api/facebook-monitor/thread/media")
def reply_thread_media():
    _, error = _viewer()
    if error:
        return error
    from modules.facebook_monitor.chat import ChatError, send_media

    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"ok": False, "error": "اختر صورة أو فيديو أو ملف"}), 400
    if not _can_reply_thread(str(request.form.get("page_id") or ""), str(request.form.get("customer_psid") or "")):
        return jsonify({"ok": False, "error": "هذه المحادثة ليست مسندة لك"}), 403
    try:
        content = upload.read()
        message = send_media(
            external_page_id=str(request.form.get("page_id") or ""),
            customer_psid=str(request.form.get("customer_psid") or ""),
            file_bytes=content,
            mime_type=upload.mimetype or "",
            filename=upload.filename,
        )
        caption = str(request.form.get("caption") or "").strip()
        if caption:
            from modules.facebook_monitor.chat import send_text

            send_text(
                external_page_id=str(request.form.get("page_id") or ""),
                customer_psid=str(request.form.get("customer_psid") or ""),
                text=caption,
            )
            message["text"] = caption
        return jsonify({"ok": True, "message": message})
    except ChatError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@facebook_monitor_bp.get("/api/facebook-monitor/message-media/<int:message_id>")
def message_media(message_id):
    _, error = _viewer()
    if error:
        return error
    from modules.ai_sales.models import AISalesMessage
    from modules.facebook_monitor.chat import ChatError, resolve_message_media

    message = AISalesMessage.query.get(message_id)
    conversation = message.conversation if message else None
    channel = conversation.channel if conversation else None
    page_id = str(getattr(channel, "page_id", "") or "")
    psid = str(getattr(conversation, "external_contact_id", "") or "")
    if not message or (page_id and psid and not _can_reply_thread(page_id, psid)):
        return jsonify({"ok": False, "error": "الوسائط غير متاحة"}), 404
    try:
        payload, mime = resolve_message_media(message_id)
    except ChatError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status
    if isinstance(payload, Path):
        return send_file(payload, mimetype=mime or None, conditional=True, max_age=3600)
    return Response(payload, content_type=mime or "application/octet-stream", headers={"Cache-Control": "private, max-age=3600"})


@facebook_monitor_bp.get("/api/facebook-monitor/media-proxy")
def media_proxy():
    _, error = _viewer()
    if error:
        return error
    from flask import Response
    from modules.facebook_monitor.chat import ChatError, proxy_media

    try:
        data, content_type = proxy_media(
            external_page_id=str(request.args.get("page_id") or ""),
            media_url=str(request.args.get("url") or ""),
        )
        return Response(
            data,
            status=200,
            content_type=content_type,
            headers={"Cache-Control": "private, max-age=600"},
        )
    except ChatError as exc:
        return jsonify({"ok": False, "error": str(exc)}), exc.status
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@facebook_monitor_bp.get("/api/facebook-monitor/filters")
def filters():
    _, error = _viewer()
    if error:
        return error
    from modules.facebook_monitor.service import build_snapshot
    from modules.facebook_monitor.strength import STRENGTH_WEIGHTS

    payload = build_snapshot(_args(), tenant_id=_tenant_id(), tenant_slug=_tenant_slug())
    return jsonify({"ok": True, "options": payload["filter_options"], "weights": STRENGTH_WEIGHTS})


def _can_reply_thread(page_id: str, customer_psid: str) -> bool:
    from modules.facebook_routing.engine import assert_employee_owns, can_view_all, conversation_for_psid
    from utils.permission_checks import get_current_employee

    employee = get_current_employee()
    is_admin = bool(session.get("is_superadmin") or session.get("role") == "admin" or (employee and employee.role == "admin"))
    if can_view_all(employee, is_admin=is_admin):
        return True
    conversation = conversation_for_psid(page_id, customer_psid)
    return assert_employee_owns(conversation, employee, is_admin=is_admin)


def _tenant_key():
    return _tenant_slug() or "default"


def _publisher_settings():
    from modules.publisher.models.publisher_settings import PublisherSettings
    from modules.publisher.services.schema_guard import ensure_publisher_schema

    try:
        ensure_publisher_schema(force=True)
    except TypeError:
        ensure_publisher_schema()
    return PublisherSettings.get(_tenant_key())


MONITOR_APP_ID = "1035171242709728"
MONITOR_APP_NAME = "SUPER MAX"
MONITOR_APIS = [
    {"name": "الصفحات", "method": "GET", "path": "/me/accounts", "fields": "id,name,picture{url},access_token"},
    {"name": "المحادثات", "method": "GET", "path": "/{page-id}/conversations", "fields": "platform=messenger"},
    {"name": "الرسائل", "method": "GET", "path": "/{conversation-id}", "fields": "messages{message,from,created_time}"},
]


def _settings_payload(settings, page_count: int, ads: dict | None = None) -> dict:
    from modules.facebook_monitor.webhook import ensure_verify_token, webhook_url

    ads = ads or {}
    verify = ensure_verify_token(settings)
    expires = getattr(settings, "fb_token_expires_at", None)
    return {
        "fb_app_id": settings.fb_app_id or MONITOR_APP_ID,
        "app_name": MONITOR_APP_NAME,
        "has_secret": bool(settings.fb_app_secret),
        "has_token": bool(settings.fb_user_token),
        "page_count": page_count,
        "apis": MONITOR_APIS,
        "ads_app_id": ads.get("ads_app_id") or "",
        "ads_account_id": ads.get("ads_account_id") or "",
        "has_ads_secret": bool(ads.get("ads_app_secret")),
        "has_ads_token": bool(ads.get("ads_user_token")),
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else "",
        "webhook_url": webhook_url(_tenant_key()),
        "verify_token": verify,
        "webhook_verified": bool(getattr(settings, "fb_webhook_verified", False)),
        "webhook_at": settings.fb_webhook_at.isoformat() if getattr(settings, "fb_webhook_at", None) else "",
        "token_permanent": bool(settings.fb_user_token) and not expires,
        "token_expires_at": expires.isoformat() if expires else "",
        "pages": _linked_pages(),
    }


def _linked_pages() -> list[dict]:
    from modules.publisher.models.publisher_page import PublisherPage

    rows = (
        PublisherPage.query.filter_by(tenant_slug=_tenant_key())
        .order_by(PublisherPage.page_name.asc())
        .all()
    )
    return [
        {
            "id": row.id,
            "page_id": row.page_id,
            "name": row.page_name or row.page_id,
            "has_token": bool(row.page_token),
        }
        for row in rows
    ]


@facebook_monitor_bp.get("/api/facebook-monitor/settings")
def monitor_settings():
    _, error = _viewer()
    if error:
        return error
    from modules.publisher.models.publisher_page import PublisherPage
    settings = _publisher_settings()
    ads = _load_ads(_tenant_key())
    page_count = PublisherPage.query.filter_by(tenant_slug=_tenant_key()).count()
    return jsonify({"ok": True, "settings": _settings_payload(settings, page_count, ads)})


@facebook_monitor_bp.post("/api/facebook-monitor/settings")
def save_monitor_settings():
    viewer, error = _viewer()
    if error:
        return error
    if session.get("role") != "admin" and not session.get("is_superadmin"):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from extensions import db
    from modules.publisher.models.publisher_page import PublisherPage
    from modules.publisher.services.token_utils import encrypt_token

    data = request.get_json(silent=True) or {}
    settings = _publisher_settings()
    app_id = str(data.get("fb_app_id") or "").strip()
    app_secret = str(data.get("fb_app_secret") or "").strip()
    user_token = str(data.get("fb_user_token") or "").strip()
    if app_id:
        settings.fb_app_id = app_id[:50]
    if app_secret and set(app_secret) != {"●"}:
        settings.fb_app_secret = encrypt_token(app_secret)
    if user_token and set(user_token) != {"●"}:
        info = _inspect_token(user_token)
        if info.get("ok") and info.get("type") == "PAGE":
            stored = _store_page_token(user_token, info, settings)
            if not stored.get("ok"):
                return jsonify({"ok": False, "error": stored.get("error") or "ما انحفظ رمز الصفحة"}), 400
        elif info.get("ok"):
            settings.fb_user_token = encrypt_token(user_token)
        else:
            return jsonify({"ok": False, "error": info.get("error") or "فحص الرمز فشل"}), 400
    db.session.commit()
    ads = _save_ads_fields(_tenant_key(), data, encrypt_token)
    page_count = PublisherPage.query.filter_by(tenant_slug=_tenant_key()).count()
    return jsonify({"ok": True, "settings": _settings_payload(settings, page_count, ads), "viewer": viewer})


def _graph_error_text(payload) -> str:
    err = (payload or {}).get("error") or {}
    if not isinstance(err, dict):
        err = {}
    code = err.get("code")
    message = str(err.get("message") or "").strip()
    if code == 190 or "session has expired" in message.lower() or "access token has expired" in message.lower():
        return (
            "رمز الصفحة منتهي. ولّد Page Access Token جديد لهذه الصفحة من Meta، "
            "ثم الصقه هنا واضغط حفظ رمز هذه الصفحة."
        )
    if code == 4 or "request limit" in message.lower():
        return (
            "فيسبوك أوقف الطلبات مؤقتاً (حد التطبيق). الصفحات القديمة باقية وما انمسحت. "
            "انتظر ساعة، لا تضغط ربط أكثر من مرة. بعدين الصق رمز الصفحة الثانية فقط واضغط حفظ وربط الصفحات."
        )
    return message or "تعذر فحص الرمز"


def _inspect_token(token: str) -> dict:
    import requests

    try:
        payload = requests.get(
            f"{GRAPH_BASE}/debug_token",
            params={"input_token": token, "access_token": token},
            timeout=12,
        ).json()
    except Exception as exc:
        text = str(exc)
        if "timed out" in text.lower() or "timeout" in text.lower():
            return {"ok": False, "error": "فيسبوك ما ردّ بالوقت. حد الطلبات شغال. الصفحات القديمة باقية، أعد المحاولة بعد ساعة."}
        return {"ok": False, "error": text}
    data = payload.get("data") or {}
    if payload.get("error"):
        from modules.facebook_monitor.service import _is_limit_error, _mark_graph_limit
        if _is_limit_error(payload.get("error") or {}):
            _mark_graph_limit()
        return {"ok": False, "error": _graph_error_text(payload)}
    if data.get("is_valid") is False:
        return {"ok": False, "error": "الرمز غير صالح أو منتهي"}
    return {
        "ok": True,
        "type": str(data.get("type") or "").upper(),
        "profile_id": str(data.get("profile_id") or data.get("user_id") or ""),
        "scopes": list(data.get("scopes") or []),
        "expires_at": data.get("expires_at") or 0,
    }


def _token_scopes(token: str) -> tuple[list[str], str]:
    info = _inspect_token(token)
    if not info.get("ok"):
        return [], info.get("error") or "تعذر فحص الرمز"
    return info.get("scopes") or [], ""


REQUIRED_PAGE_SCOPES = ("pages_show_list", "pages_messaging")


def _store_page_token(token: str, info: dict, settings) -> dict:
    import requests
    from modules.facebook_monitor.webhook import subscribe_page, sync_messenger_channel
    from modules.publisher.models.publisher_page import PublisherPage
    from modules.publisher.services.token_utils import decrypt_token, encrypt_token

    page_id = str(info.get("profile_id") or "").strip()
    name = ""
    try:
        me = requests.get(
            f"{GRAPH_BASE}/me",
            params={"fields": "id,name", "access_token": token},
            timeout=10,
        ).json()
        page_id = str(me.get("id") or page_id)
        name = str(me.get("name") or "")
    except Exception:
        pass
    if not page_id:
        return {"ok": False, "error": "ما قدرنا نعرف رقم الصفحة من هذا الرمز"}
    row = PublisherPage.query.filter_by(tenant_slug=_tenant_key(), page_id=page_id).first()
    if not row:
        row = PublisherPage(tenant_slug=_tenant_key(), page_id=page_id, page_name=name or page_id, page_token="")
        db.session.add(row)
    row.page_name = name or row.page_name or page_id
    row.page_token = encrypt_token(token)
    secret = decrypt_token(settings.fb_app_secret) if settings.fb_app_secret else ""
    sync_messenger_channel(page_id=page_id, page_name=row.page_name, page_token=token, app_secret=secret)
    subscribe_error = subscribe_page(page_id, token)
    db.session.commit()
    if not subscribe_error:
        _activate_page_routing(page_id)
    return {
        "ok": True,
        "page_id": page_id,
        "page_name": row.page_name,
        "subscribed": 0 if subscribe_error else 1,
        "subscribe_error": subscribe_error,
    }


def _activate_page_routing(page_id: str) -> None:
    """A saved page token means the page should receive routed messages."""
    page_id = str(page_id or "").strip()
    if not page_id:
        return
    try:
        from modules.facebook_routing.models import FacebookPageRouting
        from modules.facebook_routing.schema import ensure_facebook_routing_schema

        ensure_facebook_routing_schema()
        row = FacebookPageRouting.query.filter_by(page_id=page_id).first()
        if not row:
            row = FacebookPageRouting(page_id=page_id, routing_enabled=True, routing_method="LEAST_ACTIVE")
            db.session.add(row)
        else:
            row.routing_enabled = True
            row.routing_method = "LEAST_ACTIVE"
        db.session.commit()
    except Exception:
        db.session.rollback()


def _graph_cooling_safe() -> bool:
    try:
        from modules.facebook_monitor.service import _graph_cooling

        return bool(_graph_cooling())
    except Exception:
        return False


def _store_page_token_direct(token: str, page_id: str, settings, name: str = "") -> dict:
    from modules.facebook_monitor.webhook import sync_messenger_channel
    from modules.publisher.models.publisher_page import PublisherPage
    from modules.publisher.services.token_utils import decrypt_token, encrypt_token

    page_id = str(page_id or "").strip()
    if not page_id or not token:
        return {"ok": False, "error": "رقم الصفحة والرمز مطلوبين"}
    row = PublisherPage.query.filter_by(tenant_slug=_tenant_key(), page_id=page_id).first()
    if not row:
        row = PublisherPage(tenant_slug=_tenant_key(), page_id=page_id, page_name=name or page_id, page_token="")
        db.session.add(row)
    if name:
        row.page_name = name
    row.page_token = encrypt_token(token)
    secret = decrypt_token(settings.fb_app_secret) if settings.fb_app_secret else ""
    sync_messenger_channel(page_id=page_id, page_name=row.page_name or page_id, page_token=token, app_secret=secret)
    subscribe_error = ""
    from modules.facebook_monitor.webhook import subscribe_page
    try:
        subscribe_error = subscribe_page(page_id, token)
    except Exception as exc:
        subscribe_error = str(exc)
    db.session.commit()
    if not subscribe_error:
        _activate_page_routing(page_id)
    return {
        "ok": True,
        "page_id": page_id,
        "page_name": row.page_name or page_id,
        "subscribed": 0 if subscribe_error else 1,
        "subscribe_error": subscribe_error,
    }


@facebook_monitor_bp.post("/api/facebook-monitor/settings/connect")
def connect_monitor_pages():
    _, error = _viewer()
    if error:
        return error
    if session.get("role") != "admin" and not session.get("is_superadmin"):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from modules.publisher.services.page_connect_service import connect_and_store_pages
    from modules.publisher.services.token_utils import decrypt_token, encrypt_token
    from extensions import db

    try:
        data = request.get_json(silent=True) or {}
        settings = _publisher_settings()
        raw_token = str(data.get("fb_user_token") or "").strip()
        app_id = str(data.get("fb_app_id") or "").strip()
        app_secret = str(data.get("fb_app_secret") or "").strip()
        if app_id:
            settings.fb_app_id = app_id[:50]
        if app_secret and set(app_secret) != {"●"}:
            settings.fb_app_secret = encrypt_token(app_secret)
        if raw_token and set(raw_token) != {"●"}:
            token = raw_token
        elif settings.fb_user_token:
            token = decrypt_token(settings.fb_user_token)
        else:
            return jsonify({"ok": False, "error": "أدخل رمز الصفحة الثانية أو User Token"}), 400
        from modules.facebook_monitor.service import _graph_cooling, _LIMIT_HINT
        if _graph_cooling():
            return jsonify({"ok": False, "error": _LIMIT_HINT}), 429

        info = _inspect_token(token)
        if not info.get("ok"):
            return jsonify({"ok": False, "error": info.get("error") or "فحص الرمز فشل"}), 400
        scopes = info.get("scopes") or []
        if info.get("type") == "PAGE":
            stored = _store_page_token(token, info, settings)
            if not stored.get("ok"):
                return jsonify({"ok": False, "error": stored.get("error") or "ما انحفظ رمز الصفحة"}), 400
            from modules.publisher.models.publisher_page import PublisherPage
            rows = PublisherPage.query.filter_by(tenant_slug=_tenant_key()).all()
            return jsonify({
                "ok": True,
                "pages": [{"id": row.page_id, "name": row.page_name or row.page_id} for row in rows],
                "count": len(rows),
                "subscribed": stored.get("subscribed", 0),
                "scopes": scopes,
                "message": f"تم إضافة {stored['page_name']} والصفحات القديمة باقية",
            })
        if raw_token and set(raw_token) != {"●"}:
            settings.fb_user_token = encrypt_token(raw_token)
        missing = [scope for scope in REQUIRED_PAGE_SCOPES if scope not in scopes]
        if missing:
            return jsonify({
                "ok": False,
                "error": (
                    "هذا الرمز مو للرسائل. ناقص: "
                    + ", ".join(missing)
                    + ". من Graph API Explorer اختر تطبيق SUPER MAX وفعّل pages_messaging و pages_show_list ثم Generate Access Token، "
                    "والصق الرمز هنا واضغط حفظ وربط الصفحات. لا تستخدم رمز الإعلانات هنا."
                ),
                "scopes": scopes,
                "missing": missing,
            }), 400

        db.session.commit()
        from modules.facebook_monitor.webhook import (
            ensure_verify_token,
            exchange_long_lived,
            persist_long_lived,
            register_app_subscription,
            subscribe_page,
            sync_messenger_channel,
            webhook_url,
        )
        from modules.publisher.services.token_utils import decrypt_token

        app_id = settings.fb_app_id or MONITOR_APP_ID
        secret = decrypt_token(settings.fb_app_secret) if settings.fb_app_secret else ""
        if secret:
            long_token, expires_in, exchange_error = exchange_long_lived(app_id, secret, token)
            if long_token:
                persist_long_lived(settings, long_token, expires_in)
                token = long_token
            if exchange_error:
                current_app.logger.warning("facebook long-lived exchange: %s", exchange_error)
            db.session.commit()
            verify = ensure_verify_token(settings)
            register_app_subscription(
                app_id=app_id,
                app_secret=secret,
                callback_url=webhook_url(_tenant_key()),
                verify_token=verify,
            )

        result = connect_and_store_pages(tenant_slug=_tenant_key(), user_token=token)
        if not result.get("success"):
            return jsonify({"ok": False, "error": result.get("message") or "فشل ربط الصفحات"}), 400
        from modules.publisher.models.publisher_page import PublisherPage
        rows = PublisherPage.query.filter_by(tenant_slug=_tenant_key()).all()
        subscribed = 0
        for row in rows:
            page_token = decrypt_token(row.page_token) if row.page_token else ""
            if not page_token:
                continue
            sync_messenger_channel(
                page_id=row.page_id,
                page_name=row.page_name or "",
                page_token=page_token,
                app_secret=secret,
            )
            if not subscribe_page(row.page_id, page_token):
                subscribed += 1
        db.session.commit()
        pages = [
            {"id": row.get("page_id") or row.get("id"), "name": row.get("page_name") or row.get("name") or ""}
            for row in (result.get("pages") or [])
        ]
        return jsonify({
            "ok": True,
            "pages": pages,
            "count": len(pages),
            "subscribed": subscribed,
            "scopes": scopes,
            "message": result.get("message") or "تم ربط الصفحات",
        })
    except Exception as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 500


@facebook_monitor_bp.post("/api/facebook-monitor/settings/page-token")
def save_one_page_token():
    _, error = _viewer()
    if error:
        return error
    if session.get("role") != "admin" and not session.get("is_superadmin"):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    from modules.publisher.services.token_utils import encrypt_token

    data = request.get_json(silent=True) or {}
    settings = _publisher_settings()
    token = str(data.get("page_token") or data.get("fb_user_token") or "").strip()
    hint = str(data.get("page_id") or "").strip()
    name = str(data.get("page_name") or "").strip()
    app_id = str(data.get("fb_app_id") or "").strip()
    app_secret = str(data.get("fb_app_secret") or "").strip()
    if app_id:
        settings.fb_app_id = app_id[:50]
    if app_secret and set(app_secret) != {"●"}:
        settings.fb_app_secret = encrypt_token(app_secret)
        db.session.commit()
    if not token or set(token) == {"●"}:
        return jsonify({"ok": False, "error": "الصق رمز هذه الصفحة"}), 400

    cooling = _graph_cooling_safe()
    if cooling and hint:
        stored = _store_page_token_direct(token, hint, settings, name)
        if not stored.get("ok"):
            return jsonify({"ok": False, "error": stored.get("error")}), 400
        if stored.get("subscribe_error"):
            return jsonify({
                "ok": False,
                "pages": _linked_pages(),
                "error": stored["subscribe_error"],
                "message": f"انحفظ الرمز، لكن الربط فشل: {stored['subscribe_error']}",
            }), 400
        return jsonify({
            "ok": True,
            "pages": _linked_pages(),
            "count": len(_linked_pages()),
            "message": f"تم ربط {stored['page_name']} بالرسائل.",
        })
    if cooling:
        return jsonify({"ok": False, "error": "فيسبوك واقف مؤقتاً. اكتب رقم الصفحة مع الرمز حتى ينحفظ بدون فحص."}), 429

    info = _inspect_token(token)
    if not info.get("ok"):
        err = info.get("error") or "فحص الرمز فشل"
        if hint and ("أوقف الطلبات" in err or "request limit" in err.lower()):
            stored = _store_page_token_direct(token, hint, settings, name)
            if stored.get("ok"):
                if stored.get("subscribe_error"):
                    return jsonify({
                        "ok": False,
                        "pages": _linked_pages(),
                        "error": stored["subscribe_error"],
                        "message": f"انحفظ الرمز، لكن الربط فشل: {stored['subscribe_error']}",
                    }), 400
                return jsonify({
                    "ok": True,
                    "pages": _linked_pages(),
                    "count": len(_linked_pages()),
                    "message": f"تم ربط {stored['page_name']} بالرسائل.",
                })
        return jsonify({"ok": False, "error": err}), 400
    if info.get("type") != "PAGE":
        return jsonify({"ok": False, "error": "هذا مو رمز صفحة. من Messenger API ولّد Page Token لهذه الصفحة."}), 400
    stored = _store_page_token(token, info, settings)
    if not stored.get("ok"):
        return jsonify({"ok": False, "error": stored.get("error") or "ما انحفظ الرمز"}), 400
    actual = str(stored.get("page_id") or "")
    note = f"تم حفظ رمز {stored['page_name']} وربطه بالرسائل."
    if stored.get("subscribe_error"):
        note = f"انحفظ رمز {stored['page_name']}، لكن فيسبوك رفض الربط: {stored['subscribe_error']}"
    if hint and actual and hint != actual:
        note = f"هذا الرمز لصفحة {stored['page_name']} مو للصفحة المحددة. انحفظ عليها والأولى ما انمسحت."
    linked = _linked_pages()
    status = 400 if stored.get("subscribe_error") else 200
    return jsonify({
        "ok": not stored.get("subscribe_error"),
        "pages": linked,
        "count": len(linked),
        "message": note,
        "error": stored.get("subscribe_error") or "",
    }), status


def _ads_table():
    from sqlalchemy import text
    from extensions import db

    db.session.execute(text(
        "CREATE TABLE IF NOT EXISTS facebook_monitor_ads ("
        "tenant_slug VARCHAR(100) PRIMARY KEY,"
        "ads_app_id VARCHAR(50),"
        "ads_app_secret TEXT,"
        "ads_user_token TEXT,"
        "ads_account_id VARCHAR(64))"
    ))
    db.session.commit()


def _load_ads(tenant_key: str) -> dict:
    from sqlalchemy import text
    from extensions import db

    _ads_table()
    row = db.session.execute(
        text(
            "SELECT ads_app_id, ads_app_secret, ads_user_token, ads_account_id "
            "FROM facebook_monitor_ads WHERE tenant_slug = :tenant"
        ),
        {"tenant": tenant_key},
    ).mappings().first()
    if not row:
        return {}
    return dict(row)


def _save_ads_fields(tenant_key: str, data, encrypt_token) -> dict:
    from sqlalchemy import text
    from extensions import db

    current = _load_ads(tenant_key)
    ads_app_id = str(data.get("ads_app_id") or "").strip()
    ads_secret = str(data.get("ads_app_secret") or "").strip()
    ads_token = str(data.get("ads_user_token") or "").strip()
    ads_account = str(data.get("ads_account_id") or "").strip()
    if ads_app_id:
        current["ads_app_id"] = ads_app_id[:50]
    if ads_secret and set(ads_secret) != {"●"}:
        current["ads_app_secret"] = encrypt_token(ads_secret)
    if ads_token and set(ads_token) != {"●"}:
        current["ads_user_token"] = encrypt_token(ads_token)
    if ads_account:
        raw = ads_account[:64]
        if not raw.lower().startswith("act_"):
            digits = "".join(ch for ch in raw if ch.isdigit())
            raw = f"act_{digits}" if digits else raw
        current["ads_account_id"] = raw[:64]
    db.session.execute(
        text(
            "INSERT INTO facebook_monitor_ads "
            "(tenant_slug, ads_app_id, ads_app_secret, ads_user_token, ads_account_id) "
            "VALUES (:tenant, :ads_app_id, :ads_app_secret, :ads_user_token, :ads_account_id) "
            "ON CONFLICT(tenant_slug) DO UPDATE SET "
            "ads_app_id = excluded.ads_app_id, "
            "ads_app_secret = excluded.ads_app_secret, "
            "ads_user_token = excluded.ads_user_token, "
            "ads_account_id = excluded.ads_account_id"
        ),
        {
            "tenant": tenant_key,
            "ads_app_id": current.get("ads_app_id") or "",
            "ads_app_secret": current.get("ads_app_secret") or "",
            "ads_user_token": current.get("ads_user_token") or "",
            "ads_account_id": current.get("ads_account_id") or "",
        },
    )
    db.session.commit()
    return current


@facebook_monitor_bp.post("/api/facebook-monitor/settings/connect-ads")
def connect_monitor_ads():
    _, error = _viewer()
    if error:
        return error
    if session.get("role") != "admin" and not session.get("is_superadmin"):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    import requests
    from extensions import db
    from modules.publisher.services.token_utils import decrypt_token, encrypt_token

    try:
        data = request.get_json(silent=True) or {}
        ads = _save_ads_fields(_tenant_key(), data, encrypt_token)
        raw_token = str(data.get("ads_user_token") or "").strip()
        if raw_token and set(raw_token) != {"●"}:
            token = raw_token
        elif ads.get("ads_user_token"):
            token = decrypt_token(ads.get("ads_user_token"))
        else:
            return jsonify({"ok": False, "error": "أدخل رمز تطبيق الإعلانات أولاً"}), 400
        response = requests.get(
            f"{GRAPH_BASE}/me/adaccounts",
            params={"access_token": token, "fields": "id,name,account_status,currency", "limit": 50},
            timeout=20,
        )
        payload = response.json()
        if payload.get("error"):
            return jsonify({"ok": False, "error": (payload.get("error") or {}).get("message") or "فشل جلب حسابات الإعلان"}), 400
        accounts = [
            {
                "id": row.get("id") or "",
                "name": row.get("name") or row.get("id") or "",
                "currency": row.get("currency") or "",
            }
            for row in (payload.get("data") or [])
        ]
        if accounts and not ads.get("ads_account_id"):
            _save_ads_fields(_tenant_key(), {"ads_account_id": accounts[0]["id"]}, encrypt_token)
        return jsonify({"ok": True, "accounts": accounts, "count": len(accounts)})
    except Exception as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 500
