from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import requests
from flask import Blueprint, jsonify, render_template, request, session, g, send_from_directory, current_app, redirect
from werkzeug.exceptions import NotFound

from sqlalchemy import or_

from extensions import db
from models.ai_agent import Agent, AgentWorkflow
from models.social_account import SocialAccount
from models.social_post import SocialPost
from models.telegram_inbox_message import TelegramInboxMessage
from services.facebook_service import fetch_comments as fb_fetch_comments
from services.instagram_service import fetch_comments as ig_fetch_comments
from services.tiktok_service import fetch_comments as tiktok_fetch_comments
from social_ai.content_generator import create_ai_post


# url_prefix يُمرَّر عند التسجيل في app (register_blueprint(..., url_prefix="/social-ai")).
# لا تضع url_prefix هنا أيضاً — يتكرر المسار فيصبح /social-ai/social-ai/... ويُرجع 404 للصفحات الفرعية.
social_ai_bp = Blueprint(
    "social_ai",
    __name__,
)


def _current_tenant_slug():
    return getattr(g, "tenant", None)


def _ai_agent_dist_dir() -> Path:
    return Path(current_app.root_path) / "static" / "ai_agent_frontend" / "dist"


@social_ai_bp.route("/")
def dashboard():
    """AI Agent Builder standalone page (served from Vite build output)."""
    if not session.get("user_id"):
        return redirect("/", code=302)

    dist_dir = _ai_agent_dist_dir()
    index_file = dist_dir / "index.html"
    if index_file.exists():
        return send_from_directory(str(dist_dir), "index.html")

    # Fallback when dist is missing locally
    return render_template("social_ai/dashboard.html")


@social_ai_bp.route("/assets/<path:filename>")
def ai_builder_assets(filename: str):
    """Serve built assets for /social-ai/ page. No auth so CSS/JS load correctly (page itself requires login)."""
    assets_dir = _ai_agent_dist_dir() / "assets"
    if not assets_dir.is_dir():
        return ("assets dir missing", 404, {"Content-Type": "text/plain"})
    try:
        return send_from_directory(str(assets_dir), filename)
    except NotFound:
        return ("not found", 404, {"Content-Type": "text/plain"})


@social_ai_bp.route("/api/accounts", methods=["GET"])
def api_accounts_list():
    tenant_slug = _current_tenant_slug()
    q = SocialAccount.query
    if tenant_slug:
        q = q.filter_by(tenant_slug=tenant_slug)
    platform = (request.args.get("platform") or "").strip().lower()
    if platform:
        q = q.filter_by(platform=platform)
    items = q.order_by(SocialAccount.created_at.desc()).all()
    return jsonify({"accounts": [a.to_dict() for a in items]})


@social_ai_bp.route("/api/posts", methods=["GET"])
def api_posts_list():
    tenant_slug = _current_tenant_slug()
    status = (request.args.get("status") or "").strip() or None
    q = SocialPost.query
    if tenant_slug:
        q = q.filter_by(tenant_slug=tenant_slug)
    if status:
        q = q.filter_by(status=status)
    posts = q.order_by(SocialPost.created_at.desc()).limit(50).all()
    return jsonify({"posts": [p.to_dict() for p in posts]})


@social_ai_bp.route("/api/comments/preview", methods=["POST"])
def api_comments_preview():
    """
    واجهة بسيطة لعقدة Comment Listener:
    - تجلب تعليقات منشور واحد من المنصة المحددة.
    - تُستخدم فقط للمعاينة في واجهة العقدة (بوكس التعليقات).
    يعتمد نوع المعرف حسب المنصة:
    - Facebook: post_id
    - Instagram: media_id
    - TikTok: video_id
    """
    data = request.get_json() or {}
    platform = (data.get("platform") or "facebook").strip().lower()
    limit = int(data.get("limit") or 10)

    post_id = (data.get("post_id") or "").strip()
    media_id = (data.get("media_id") or "").strip()
    video_id = (data.get("video_id") or "").strip()

    # نختار المعرف المناسب لكل منصة
    try:
        comments_raw: list[dict] = []
        if platform == "facebook":
            if not post_id:
                return jsonify({"success": False, "error": "post_id مطلوب لفيسبوك"}), 400
            comments_raw = fb_fetch_comments(post_id=post_id, limit=limit)
        elif platform == "instagram":
            if not media_id:
                return jsonify({"success": False, "error": "media_id مطلوب لإنستغرام"}), 400
            comments_raw = ig_fetch_comments(media_id=media_id, limit=limit)
        elif platform == "tiktok":
            if not video_id:
                return jsonify({"success": False, "error": "video_id مطلوب لتيك توك"}), 400
            comments_raw = tiktok_fetch_comments(video_id=video_id, limit=limit)
        else:
            return jsonify({"success": False, "error": f"منصة غير مدعومة: {platform}"}), 400

        # توحيد شكل البيانات لعقدة الـ UI
        normalized: list[dict] = []
        for c in comments_raw:
            if platform == "facebook":
                normalized.append(
                    {
                        "platform": "facebook",
                        "comment_id": c.get("id"),
                        "username": (c.get("from") or {}).get("name"),
                        "text": c.get("message") or "",
                        "timestamp": c.get("created_time"),
                    }
                )
            elif platform == "instagram":
                normalized.append(
                    {
                        "platform": "instagram",
                        "comment_id": c.get("id"),
                        "username": c.get("username"),
                        "text": c.get("text") or "",
                        "timestamp": c.get("timestamp"),
                    }
                )
            else:  # tiktok
                normalized.append(
                    {
                        "platform": "tiktok",
                        "comment_id": c.get("comment_id") or c.get("id"),
                        "username": (c.get("user") or {}).get("display_name")
                        if isinstance(c.get("user"), dict)
                        else c.get("user_name"),
                        "text": c.get("text") or c.get("comment_text") or "",
                        "timestamp": c.get("create_time") or c.get("timestamp"),
                    }
                )

        return jsonify({"success": True, "platform": platform, "comments": normalized})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@social_ai_bp.route("/api/generate", methods=["POST"])
def api_generate_post():
    data = request.get_json() or {}
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"success": False, "error": "الرجاء إدخال موضوع للمنشور."}), 400
    user_id = session.get("user_id")
    try:
        post = create_ai_post(topic, user_id=user_id, auto=False)
        return jsonify({"success": True, "post": post.to_dict()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _extract_text_from_upload(file_storage):
    """استخراج نص من ملف مرفوع (PDF، Excel، نص، CSV). يُرجع النص أو يرفع استثناء."""
    if not file_storage or not file_storage.filename:
        raise ValueError("لم يُرفع أي ملف")
    fn = (file_storage.filename or "").lower()
    ext = "." in fn and fn.rsplit(".", 1)[-1] or ""

    if ext == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ValueError("تثبيت pypdf مطلوب لقراءة PDF: pip install pypdf")
        reader = PdfReader(file_storage)
        parts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
        return "\n".join(parts) if parts else ""

    if ext == "xlsx":
        import pandas as pd
        df = pd.read_excel(file_storage, engine="openpyxl")
        return df.to_string(index=False)
    if ext == "xls":
        import pandas as pd
        try:
            df = pd.read_excel(file_storage, engine="xlrd")
        except ImportError:
            raise ValueError("لقراءة ملفات .xls ثبّت: pip install xlrd")
        return df.to_string(index=False)

    if ext in ("txt", "csv"):
        data = file_storage.read()
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("cp1256", errors="replace")

    raise ValueError("نوع الملف غير مدعوم. استخدم: PDF، xlsx، xls، txt، csv.")


@social_ai_bp.route("/api/knowledge/extract", methods=["POST"])
def api_knowledge_extract():
    """استخراج نص من ملف (PDF / Excel / txt / csv) لاستخدامه كقاعدة معرفة في عقدة المعرفة."""
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "يجب تسجيل الدخول"}), 401
    file = request.files.get("file")
    try:
        text = _extract_text_from_upload(file)
        return jsonify({"success": True, "catalog": text or ""})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        current_app.logger.exception("knowledge extract")
        return jsonify({"success": False, "error": str(e)}), 500


def _telegram_webhook_base(data=None):
    """
    عنوان أصل التطبيق (بدون مسار) لاستقبال webhook تيليجرام.
    الأولوية: base_url من الطلب → BASE_URL من الإعدادات → request.host_url.
    تيليجرام يقبل فقط HTTPS (ما عدا localhost للتطوير).
    """
    data = data or {}
    base = (data.get("base_url") or "").strip()
    if not base:
        base = (current_app.config.get("BASE_URL") or "").strip()
    if not base and request:
        # استخدم أصل المضيف فقط (بدون مسار مثل /social-ai/) حتى يكون الرابط صحيحاً
        base = (request.host_url or "").rstrip("/")
    return base.rstrip("/") if base else ""


@social_ai_bp.route("/api/telegram/set-webhook", methods=["POST"])
def api_telegram_set_webhook():
    """تفعيل Webhook تيليجرام من الصفحة: تسجيل عنوان الاستقبال عند Telegram باستخدام التوكن المرسل."""
    if not session.get("user_id"):
        return jsonify({"ok": False, "error": "يجب تسجيل الدخول"}), 401
    data = request.get_json() or {}
    bot_token = (data.get("bot_token") or "").strip()
    if not bot_token:
        return jsonify({"ok": False, "error": "Bot Token مطلوب"}), 400

    tenant_slug = _current_tenant_slug()
    if not tenant_slug:
        return jsonify({
            "ok": False,
            "error": "تعذّر تحديد شركة المستخدم (tenant). سجّل الدخول من رابط الشركة ثم افتح بناء الوكلاء.",
        }), 400

    workflow_id_raw = data.get("workflow_id")
    try:
        workflow_id = int(workflow_id_raw)
    except (TypeError, ValueError):
        return jsonify({
            "ok": False,
            "error": "احفظ الوورك فلو أولاً (يُنشأ رقم workflow_id) ثم فعّل Webhook من جديد.",
        }), 400

    from models.ai_agent import AgentWorkflow

    wf = AgentWorkflow.query.get(workflow_id)
    if not wf or (wf.agent and (wf.agent.tenant_slug or "") != tenant_slug):
        return jsonify({"ok": False, "error": "الوورك فلو غير موجود أو لا يخص شركتك."}), 404

    base = _telegram_webhook_base(data)
    if not base:
        return jsonify({
            "ok": False,
            "error": "تعذّر تحديد عنوان السيرفر. ضع BASE_URL في الإعدادات أو أدخل «عنوان السيرفر» في العقدة (مثال: https://finora.company)",
        }), 400
    # مسار يتضمن الشركة + الوورك فلو حتى يُحمَّل التوكن من العقدة عند استقبال التحديث
    webhook_url = f"{base}/telegram/webhook/{tenant_slug}/{workflow_id}"
    if not webhook_url.startswith("https://") and not webhook_url.startswith("http://127.0.0.1") and "localhost" not in webhook_url:
        return jsonify({
            "ok": False,
            "error": "تيليجرام يقبل فقط عنوان HTTPS. استخدم عنواناً يبدأ بـ https:// أو شغّل على localhost للتطوير.",
        }), 400
    log = logging.getLogger(__name__)
    log.info("Telegram setWebhook: url=%s", webhook_url)
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    try:
        resp = requests.post(url, json={"url": webhook_url}, timeout=10)
        body = resp.json() if resp.text else {}
        if not resp.ok:
            log.warning("Telegram setWebhook failed: %s", body)
            desc = (body.get("description") or "").strip()
            if "resolve host" in desc.lower() or "name resolution" in desc.lower():
                return jsonify({
                    "ok": False,
                    "error": "تيليجرام لا يستطيع الوصول إلى هذا النطاق (فشل في حل الاسم). استخدم نفس عنوان الموقع الذي يفتح في المتصفح (مثلاً مع www: https://www.finora.company أو بدونه)، وتأكد أن النطاق عام ومتاح من الإنترنت.",
                    "telegram_response": body,
                }), 400
            return jsonify({"ok": False, "error": desc or "فشل تفعيل Webhook", "telegram_response": body}), 400
        return jsonify({"ok": True, "webhook_url": webhook_url, "telegram_response": body}), 200
    except Exception as e:
        log.exception("telegram set-webhook")
        return jsonify({"ok": False, "error": str(e)}), 500


@social_ai_bp.route("/api/telegram/delete-webhook", methods=["POST"])
def api_telegram_delete_webhook():
    """إلغاء تفعيل Webhook تيليجرام من الصفحة."""
    if not session.get("user_id"):
        return jsonify({"ok": False, "error": "يجب تسجيل الدخول"}), 401
    data = request.get_json() or {}
    bot_token = (data.get("bot_token") or "").strip()
    if not bot_token:
        return jsonify({"ok": False, "error": "Bot Token مطلوب"}), 400
    url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
    try:
        resp = requests.post(url, timeout=10)
        body = resp.json() if resp.text else {}
        if not resp.ok:
            return jsonify({"ok": False, "error": body.get("description", "فشل إلغاء Webhook"), "telegram_response": body}), 400
        return jsonify({"ok": True, "telegram_response": body}), 200
    except Exception as e:
        logging.getLogger(__name__).exception("telegram delete-webhook")
        return jsonify({"ok": False, "error": str(e)}), 500


def _normalize_webhook_url(u: str) -> str:
    """مقارنة آمنة بين عنوانين (شرطات، مسافات)."""
    return (u or "").strip().rstrip("/")


@social_ai_bp.route("/api/telegram/webhook-info", methods=["POST"])
def api_telegram_webhook_info():
    """
    جلب WebhookInfo من Telegram.
    إذا وُجد workflow_id + مستأجر في الجلسة: يُحسب الرابط المتوقع ويُرجع url_matches.
    """
    if not session.get("user_id"):
        return jsonify({"ok": False, "error": "يجب تسجيل الدخول"}), 401
    data = request.get_json() or {}
    bot_token = (data.get("bot_token") or "").strip()
    if not bot_token:
        return jsonify({"ok": False, "error": "Bot Token مطلوب"}), 400
    url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    try:
        resp = requests.get(url, timeout=10)
        body = resp.json() if resp.text else {}
        if not resp.ok:
            return jsonify({"ok": False, "error": body.get("description", "فشل جلب WebhookInfo"), "telegram_response": body}), 400
        result = body.get("result") if isinstance(body, dict) else None
        tg_url = ""
        last_err = ""
        pending = 0
        if isinstance(result, dict):
            tg_url = str(result.get("url") or "").strip()
            last_err = str(result.get("last_error_message") or "").strip()
            try:
                pending = int(result.get("pending_update_count") or 0)
            except (TypeError, ValueError):
                pending = 0

        expected_webhook_url = ""
        url_matches = None
        tenant_slug = _current_tenant_slug()
        wf_raw = data.get("workflow_id")
        if tenant_slug and wf_raw is not None and str(wf_raw).strip() != "":
            try:
                wf_id = int(wf_raw)
                base = _telegram_webhook_base(data)
                if base:
                    expected_webhook_url = f"{base.rstrip('/')}/telegram/webhook/{tenant_slug}/{wf_id}"
                    url_matches = bool(
                        tg_url
                        and _normalize_webhook_url(tg_url) == _normalize_webhook_url(expected_webhook_url)
                    )
            except (TypeError, ValueError):
                pass

        out = {
            "ok": True,
            "telegram_response": body,
            "current_url": tg_url,
            "last_error_message": last_err,
            "pending_update_count": pending,
            "expected_webhook_url": expected_webhook_url or None,
            "url_matches": url_matches,
        }
        return jsonify(out), 200
    except Exception as e:
        logging.getLogger(__name__).exception("telegram webhook-info")
        return jsonify({"ok": False, "error": str(e)}), 500


@social_ai_bp.route("/api/schedule", methods=["POST"])
def api_schedule_post():
    data = request.get_json() or {}
    post_id = data.get("post_id")
    when = (data.get("publish_time") or "").strip()
    if not post_id or not when:
        return jsonify({"success": False, "error": "post_id و publish_time مطلوبان."}), 400

    post = SocialPost.query.get(post_id)
    if not post:
        return jsonify({"success": False, "error": "المنشور غير موجود."}), 404
    try:
        dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except Exception:
        return jsonify({"success": False, "error": "صيغة التاريخ غير صحيحة."}), 400

    tenant_slug = _current_tenant_slug()
    post.tenant_slug = tenant_slug
    post.publish_time = dt
    post.status = "scheduled"
    db.session.commit()
    return jsonify({"success": True, "post": post.to_dict()})


def _inbox_workflow_query():
    """وورك فلوهات يملكها المستخدم الحالي (نفس منطق واجهة الوكلاء)."""
    tenant_slug = _current_tenant_slug()
    user_id = session.get("user_id")
    q = AgentWorkflow.query.join(Agent, Agent.id == AgentWorkflow.agent_id)
    if tenant_slug:
        q = q.filter(Agent.tenant_slug == tenant_slug)
    if user_id:
        q = q.filter(or_(Agent.user_id == user_id, Agent.user_id.is_(None)))
    return q


def _graph_has_telegram_listener(graph_json) -> bool:
    if not isinstance(graph_json, dict):
        return False
    for n in graph_json.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        if (n.get("type") or "") == "telegram_listener":
            return True
    return False


def _graph_has_whatsapp_listener(graph_json) -> bool:
    if not isinstance(graph_json, dict):
        return False
    for n in graph_json.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        if (n.get("type") or "") == "whatsapp_listener":
            return True
    return False


def _get_workflow_for_inbox(workflow_id: int) -> AgentWorkflow | None:
    return _inbox_workflow_query().filter(AgentWorkflow.id == workflow_id).first()


def _ensure_telegram_inbox_table() -> None:
    """ينشئ الجدول على bind الجلسة الحالية (مستأجر أو رئيسية)."""
    from social_ai.telegram_inbox import ensure_telegram_inbox_table_for_current_bind

    ensure_telegram_inbox_table_for_current_bind()


def _inbox_fail_json(exc: Exception, status: int = 200) -> tuple:
    """يرجع JSON بدل صفحة HTML عند الخطأ حتى لا يكسر الواجهة (Unexpected token '<')."""
    current_app.logger.exception("telegram inbox api")
    err = str(exc)
    low = err.lower()
    if "no such table" in low or "does not exist" in low or "undefinedtable" in low:
        err = (
            "جدول محادثات تيليجرام غير موجود على السيرفر. "
            "أعد تشغيل التطبيق بعد التحديث أو نفّذ إنشاء الجداول (db.create_all)."
        )
    return jsonify({"success": False, "error": err}), status


@social_ai_bp.route("/telegram/inbox")
def telegram_inbox_page():
    """لوحة محادثات تيليجرام والرد اليدوي."""
    if not session.get("user_id"):
        return redirect("/", code=302)
    return render_template("social_ai/telegram_inbox.html", inbox_channel="telegram")


@social_ai_bp.route("/whatsapp/inbox")
def whatsapp_inbox_page():
    """لوحة محادثات واتساب والرد اليدوي."""
    if not session.get("user_id"):
        return redirect("/", code=302)
    return render_template("social_ai/telegram_inbox.html", inbox_channel="whatsapp")


@social_ai_bp.route("/api/telegram/inbox/workflows", methods=["GET"])
def api_telegram_inbox_workflows():
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "يجب تسجيل الدخول"}), 401
    try:
        rows = _inbox_workflow_query().order_by(AgentWorkflow.updated_at.desc()).all()
        workflows = []
        for wf in rows:
            if not _graph_has_telegram_listener(wf.graph_json):
                continue
            ag = wf.agent
            workflows.append(
                {
                    "id": wf.id,
                    "name": wf.name or f"Workflow {wf.id}",
                    "agent_name": (ag.name if ag else "") or "",
                }
            )
        return jsonify({"success": True, "workflows": workflows})
    except Exception as exc:
        return _inbox_fail_json(exc)


@social_ai_bp.route("/api/whatsapp/inbox/workflows", methods=["GET"])
def api_whatsapp_inbox_workflows():
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "يجب تسجيل الدخول"}), 401
    try:
        rows = _inbox_workflow_query().order_by(AgentWorkflow.updated_at.desc()).all()
        workflows = []
        for wf in rows:
            if not _graph_has_whatsapp_listener(wf.graph_json):
                continue
            ag = wf.agent
            workflows.append(
                {
                    "id": wf.id,
                    "name": wf.name or f"Workflow {wf.id}",
                    "agent_name": (ag.name if ag else "") or "",
                }
            )
        return jsonify({"success": True, "workflows": workflows})
    except Exception as exc:
        return _inbox_fail_json(exc)


@social_ai_bp.route("/api/telegram/inbox/chats", methods=["GET"])
def api_telegram_inbox_chats():
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "يجب تسجيل الدخول"}), 401
    try:
        wf_id = int(request.args.get("workflow_id") or 0)
    except (TypeError, ValueError):
        wf_id = 0
    if not wf_id or not _get_workflow_for_inbox(wf_id):
        return jsonify({"success": False, "error": "وورك فلو غير موجود أو غير مسموح"}), 404

    _ensure_telegram_inbox_table()
    try:
        # آخر رسالة لكل محادثة (نزولاً حسب التاريخ)
        recent = (
            TelegramInboxMessage.query.filter(
                TelegramInboxMessage.workflow_id == wf_id,
                or_(TelegramInboxMessage.channel == "telegram", TelegramInboxMessage.channel.is_(None)),
            )
            .order_by(TelegramInboxMessage.created_at.desc())
            .limit(600)
            .all()
        )
        seen: dict[str, dict] = {}
        for r in recent:
            if r.chat_id in seen:
                continue
            seen[r.chat_id] = {
                "chat_id": r.chat_id,
                "last_at": r.created_at.isoformat() if r.created_at else None,
                "preview": (r.body or "")[:180],
            }
        chats = sorted(seen.values(), key=lambda x: x.get("last_at") or "", reverse=True)
        return jsonify({"success": True, "chats": chats})
    except Exception as exc:
        return _inbox_fail_json(exc)


@social_ai_bp.route("/api/whatsapp/inbox/chats", methods=["GET"])
def api_whatsapp_inbox_chats():
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "يجب تسجيل الدخول"}), 401
    try:
        wf_id = int(request.args.get("workflow_id") or 0)
    except (TypeError, ValueError):
        wf_id = 0
    if not wf_id or not _get_workflow_for_inbox(wf_id):
        return jsonify({"success": False, "error": "وورك فلو غير موجود أو غير مسموح"}), 404

    _ensure_telegram_inbox_table()
    try:
        recent = (
            TelegramInboxMessage.query.filter_by(workflow_id=wf_id, channel="whatsapp")
            .order_by(TelegramInboxMessage.created_at.desc())
            .limit(600)
            .all()
        )
        seen: dict[str, dict] = {}
        for r in recent:
            if r.chat_id in seen:
                continue
            seen[r.chat_id] = {
                "chat_id": r.chat_id,
                "last_at": r.created_at.isoformat() if r.created_at else None,
                "preview": (r.body or "")[:180],
            }
        chats = sorted(seen.values(), key=lambda x: x.get("last_at") or "", reverse=True)
        return jsonify({"success": True, "chats": chats})
    except Exception as exc:
        return _inbox_fail_json(exc)


@social_ai_bp.route("/api/telegram/inbox/messages", methods=["GET"])
def api_telegram_inbox_messages():
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "يجب تسجيل الدخول"}), 401
    try:
        wf_id = int(request.args.get("workflow_id") or 0)
    except (TypeError, ValueError):
        wf_id = 0
    chat_id = (request.args.get("chat_id") or "").strip()
    if not wf_id or not chat_id:
        return jsonify({"success": False, "error": "workflow_id و chat_id مطلوبان"}), 400
    if not _get_workflow_for_inbox(wf_id):
        return jsonify({"success": False, "error": "وورك فلو غير موجود أو غير مسموح"}), 404

    _ensure_telegram_inbox_table()
    try:
        q = (
            TelegramInboxMessage.query.filter(
                TelegramInboxMessage.workflow_id == wf_id,
                TelegramInboxMessage.chat_id == chat_id,
                or_(TelegramInboxMessage.channel == "telegram", TelegramInboxMessage.channel.is_(None)),
            )
            .order_by(TelegramInboxMessage.created_at.asc())
            .limit(500)
        )
        return jsonify({"success": True, "messages": [m.to_dict() for m in q]})
    except Exception as exc:
        return _inbox_fail_json(exc)


@social_ai_bp.route("/api/whatsapp/inbox/messages", methods=["GET"])
def api_whatsapp_inbox_messages():
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "يجب تسجيل الدخول"}), 401
    try:
        wf_id = int(request.args.get("workflow_id") or 0)
    except (TypeError, ValueError):
        wf_id = 0
    chat_id = (request.args.get("chat_id") or "").strip()
    if not wf_id or not chat_id:
        return jsonify({"success": False, "error": "workflow_id و chat_id مطلوبان"}), 400
    if not _get_workflow_for_inbox(wf_id):
        return jsonify({"success": False, "error": "وورك فلو غير موجود أو غير مسموح"}), 404

    _ensure_telegram_inbox_table()
    try:
        q = (
            TelegramInboxMessage.query.filter_by(workflow_id=wf_id, channel="whatsapp", chat_id=chat_id)
            .order_by(TelegramInboxMessage.created_at.asc())
            .limit(500)
        )
        return jsonify({"success": True, "messages": [m.to_dict() for m in q]})
    except Exception as exc:
        return _inbox_fail_json(exc)


@social_ai_bp.route("/api/telegram/inbox/send", methods=["POST"])
def api_telegram_inbox_send():
    """إرسال رد يدوي إلى تيليجرام وتسجيله كـ operator."""
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "يجب تسجيل الدخول"}), 401
    data = request.get_json() or {}
    try:
        wf_id = int(data.get("workflow_id") or 0)
    except (TypeError, ValueError):
        wf_id = 0
    chat_id = (data.get("chat_id") or "").strip()
    text = (data.get("text") or "").strip()
    if not wf_id or not chat_id or not text:
        return jsonify({"success": False, "error": "workflow_id و chat_id والنص مطلوبة"}), 400

    wf = _get_workflow_for_inbox(wf_id)
    if not wf:
        return jsonify({"success": False, "error": "وورك فلو غير موجود أو غير مسموح"}), 404

    from social_ai.telegram_inbox import extract_telegram_bot_token_from_workflow_graph, record_telegram_inbox_message

    bot_token = extract_telegram_bot_token_from_workflow_graph(wf.graph_json)
    if not bot_token:
        return jsonify({"success": False, "error": "لا يوجد Bot Token في عقدة Telegram Listener لهذا الوورك فلو"}), 400

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text[:4096]},
            timeout=15,
        )
        body = resp.json() if resp.text else {}
        if resp.status_code >= 400 or not body.get("ok", True):
            err = (body.get("description") if isinstance(body, dict) else None) or (resp.text or "")[:300]
            return jsonify({"success": False, "error": err or "فشل إرسال تيليجرام"}), 400
    except Exception as e:
        current_app.logger.exception("telegram inbox send")
        return jsonify({"success": False, "error": str(e)}), 200

    _ensure_telegram_inbox_table()
    try:
        tenant_slug = _current_tenant_slug()
        if wf.agent and wf.agent.tenant_slug:
            tenant_slug = wf.agent.tenant_slug
        record_telegram_inbox_message(tenant_slug, wf_id, chat_id, "operator", text[:4096])
    except Exception as exc:
        return _inbox_fail_json(exc)
    return jsonify({"success": True})


@social_ai_bp.route("/api/whatsapp/inbox/send", methods=["POST"])
def api_whatsapp_inbox_send():
    """إرسال رد يدوي إلى واتساب كلاود وتسجيله كـ operator."""
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "يجب تسجيل الدخول"}), 401
    data = request.get_json() or {}
    try:
        wf_id = int(data.get("workflow_id") or 0)
    except (TypeError, ValueError):
        wf_id = 0
    chat_id = (data.get("chat_id") or "").strip()
    text = (data.get("text") or "").strip()
    if not wf_id or not chat_id or not text:
        return jsonify({"success": False, "error": "workflow_id و chat_id والنص مطلوبة"}), 400

    wf = _get_workflow_for_inbox(wf_id)
    if not wf:
        return jsonify({"success": False, "error": "وورك فلو غير موجود أو غير مسموح"}), 404

    from social_ai.telegram_inbox import extract_whatsapp_credentials_from_workflow_graph, record_inbox_message

    access_token, phone_id = extract_whatsapp_credentials_from_workflow_graph(wf.graph_json)
    if not access_token or not phone_id:
        return jsonify({"success": False, "error": "لا يوجد access_token/phone_id في عقدة WhatsApp Listener"}), 400

    url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": chat_id,
        "type": "text",
        "text": {"body": text[:4096]},
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        body = resp.json() if resp.text else {}
        if resp.status_code >= 400:
            err = (body.get("error", {}) if isinstance(body, dict) else {}).get("message") or (resp.text or "")[:300]
            return jsonify({"success": False, "error": err or "فشل إرسال واتساب"}), 400
    except Exception as e:
        current_app.logger.exception("whatsapp inbox send")
        return jsonify({"success": False, "error": str(e)}), 200

    _ensure_telegram_inbox_table()
    try:
        tenant_slug = _current_tenant_slug()
        if wf.agent and wf.agent.tenant_slug:
            tenant_slug = wf.agent.tenant_slug
        record_inbox_message(tenant_slug, wf_id, "whatsapp", chat_id, "operator", text[:4096])
    except Exception as exc:
        return _inbox_fail_json(exc)
    return jsonify({"success": True})

