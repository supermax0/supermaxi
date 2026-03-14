from functools import wraps

from flask import Blueprint, jsonify, render_template, request, session, current_app

from extensions import db
from models.ai_agent import (
    Agent,
    AgentWorkflow,
    AgentExecution,
    AgentExecutionLog,
    AgentComment,
)
from models.employee import Employee
from social_ai.workflow_engine import execute_workflow


autoposter_bp = Blueprint(
    "autoposter",
    __name__,
    url_prefix="/autoposter",
)


def require_autoposter_login(f):
    @wraps(f)
    def inner(*args, **kwargs):
        if not session.get("user_id"):
            from flask import url_for, redirect

            return redirect(url_for("index.login") + "?next=" + request.path)
        return f(*args, **kwargs)

    return inner


# ============== صفحات واجهة AI Agent Builder ==============


@autoposter_bp.route("/")
@autoposter_bp.route("/dashboard")
def dashboard_view():
    """لوحة التحكم الرئيسية للأوتوبوستر — نفس السايدبار لجميع الصفحات."""
    return render_template("autoposter/dashboard.html")


@autoposter_bp.route("/upload")
@require_autoposter_login
def upload_page():
    """صفحة رفع وسائط (صورة/فيديو) ثم استخدامها في المنشور."""
    return render_template("autoposter/upload.html")


@autoposter_bp.route("/ai-agent")
def ai_agent_view():
    """واجهة AI Agent / Workflow Builder — بدون أي منطق نشر أو ربط صفحات."""
    return render_template("autoposter/ai_agent.html")


@autoposter_bp.route("/pages")
@require_autoposter_login
def pages_view():
    """صفحة إدارة صفحات فيسبوك المتصلة."""
    return render_template("autoposter/pages.html")


@autoposter_bp.route("/settings")
@require_autoposter_login
def settings_view():
    """صفحة إعدادات فيسبوك (معرف التطبيق، إلخ)."""
    return render_template("autoposter/settings.html")


# ============== API: معلومات المستخدم الحالي ==============


# ============== API: رفع الوسائط (صورة / فيديو) ==============


def _register_autoposter_media(public_url: str, media_type: str, filename: str, size_bytes: int):
    """تسجيل الوسائط في جدول مكتبة الأوتوبوستر ليُختار منها عند النشر.

    ملاحظة مهمة: في الإنتاج قد لا يكون جدول autoposter_media منشأً بعد (خاصة على السيرفر القديم)،
    لذلك نحاول إنشاء الجداول تلقائياً عند أول فشل من نوع OperationalError، حتى لا يفشل الرفع بصمت.
    """
    from models.autoposter_media import AutoposterMedia
    from sqlalchemy.exc import OperationalError
    try:
        tenant_slug = session.get("tenant_slug")
        rec = AutoposterMedia(
            tenant_slug=tenant_slug,
            public_url=public_url,
            media_type=media_type,
            filename=filename,
            size_bytes=size_bytes,
        )
        db.session.add(rec)
        db.session.commit()
        return rec.id
    except OperationalError as e:
        # في حال لم يكن جدول autoposter_media موجوداً بعد على قاعدة بيانات الإنتاج
        current_app.logger.exception("autoposter _register_autoposter_media OperationalError, trying create_all: %s", e)
        db.session.rollback()
        try:
            db.create_all()
            db.session.add(rec)
            db.session.commit()
            return rec.id
        except Exception as e2:
            current_app.logger.exception("autoposter _register_autoposter_media failed after create_all: %s", e2)
            db.session.rollback()
            return None
    except Exception as e:
        current_app.logger.exception("autoposter _register_autoposter_media failed: %s", e)
        db.session.rollback()
        return None


@autoposter_bp.route("/api/upload", methods=["POST"])
@require_autoposter_login
def api_upload():
    """
    رفع ملف وسائط (صورة أو فيديو) عبر multipart/form-data.
    المفتاح: file. حد الحجم 100MB. الصيغ: jpg, png, webp, mp4, mov.
    يُخزّن الملف على السيرفر ويُسجّل في مكتبة الوسائط.
    """
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"ok": False, "message": "لم يُرفع ملف", "error": "media missing"}), 400
    from services.media_service import save_uploaded_file

    result = save_uploaded_file(file, max_mb=100)
    if not result.get("ok"):
        return jsonify({
            "ok": False,
            "message": result.get("message", "فشل رفع الملف"),
            "error": result.get("error_code", "upload_failed"),
        }), 400
    public_url = result.get("url") or ""
    size_mb = result.get("size_mb") or 0
    size_bytes = int(size_mb * 1024 * 1024) if size_mb else None
    media_id = _register_autoposter_media(
        public_url,
        result.get("type") or "video",
        file.filename or "",
        size_bytes or 0,
    )
    # تحويل الرابط إلى مطلق إن لزم (للاستخدام من الواجهة)
    url = public_url
    if url.startswith("/") and request.url_root:
        base = (request.url_root or "").rstrip("/")
        url = base + url
    out = {
        "ok": True,
        "url": url,
        "type": result.get("type"),
        "thumbnail_url": result.get("thumbnail_url"),
        "size_mb": result.get("size_mb"),
        "width": result.get("width"),
        "height": result.get("height"),
        "duration_sec": result.get("duration_sec"),
    }
    if media_id:
        out["media_id"] = media_id
    return jsonify(out)


@autoposter_bp.route("/api/upload/json", methods=["POST"])
@require_autoposter_login
def api_upload_json():
    """
    رفع وسائط عبر JSON: { "filename": "x.mp4", "data": "base64..." }.
    بديل عند صعوبة multipart (بعض الشبكات أو الوكلاء).
    حد الحجم 100MB.
    """
    data = request.get_json(silent=True) or {}
    b64 = data.get("data") or ""
    filename = (data.get("filename") or "").strip() or "video.mp4"
    content_type = (data.get("content_type") or "").strip()
    if not b64:
        return jsonify({"ok": False, "message": "المحتوى (data) مطلوب بصيغة base64", "error": "data missing"}), 400
    import base64
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        return jsonify({"ok": False, "message": "المحتوى ليس base64 صالحاً", "error": "invalid_base64"}), 400
    if not content_type:
        content_type = "video/mp4" if filename.lower().endswith((".mp4", ".mov", ".webm")) else "image/jpeg"
    from services.media_service import save_uploaded_bytes
    result = save_uploaded_bytes(raw, filename, content_type, max_mb=100)
    if not result.get("ok"):
        return jsonify({
            "ok": False,
            "message": result.get("message", "فشل حفظ الملف"),
            "error": result.get("error_code", "upload_failed"),
        }), 400
    public_url = result.get("url") or ""
    size_mb = result.get("size_mb") or 0
    size_bytes = int(size_mb * 1024 * 1024) if size_mb else len(raw)
    media_id = _register_autoposter_media(
        public_url,
        result.get("type") or "video",
        filename,
        size_bytes,
    )
    url = public_url
    if url.startswith("/") and request.url_root:
        url = (request.url_root or "").rstrip("/") + url
    out = {
        "ok": True,
        "url": url,
        "type": result.get("type"),
        "thumbnail_url": result.get("thumbnail_url"),
        "size_mb": result.get("size_mb"),
        "width": result.get("width"),
        "height": result.get("height"),
        "duration_sec": result.get("duration_sec"),
    }
    if media_id:
        out["media_id"] = media_id
    return jsonify(out)


@autoposter_bp.route("/api/media", methods=["GET"])
@require_autoposter_login
def api_media_list():
    """قائمة الوسائط المخزنة (صور/فيديو) للشركة الحالية — لاختيار واحدة عند النشر."""
    from models.autoposter_media import AutoposterMedia
    from sqlalchemy.exc import OperationalError
    tenant_slug = session.get("tenant_slug")
    try:
        q = AutoposterMedia.query.order_by(AutoposterMedia.created_at.desc()).limit(100)
        if tenant_slug:
            q = q.filter_by(tenant_slug=tenant_slug)
        items = q.all()
        return jsonify({"success": True, "media": [m.to_dict() for m in items]})
    except OperationalError as e:
        current_app.logger.exception("autoposter /api/media OperationalError, trying create_all: %s", e)
        db.session.rollback()
        try:
            db.create_all()
        except Exception:
            db.session.rollback()
        return jsonify({"success": False, "media": []})
    except Exception as e:
        current_app.logger.exception("autoposter /api/media failed: %s", e)
        db.session.rollback()
        return jsonify({"success": False, "media": []})


@autoposter_bp.route("/api/me", methods=["GET"])
@require_autoposter_login
def api_me():
    emp = Employee.query.get(session.get("user_id"))
    if not emp:
        return jsonify({"error": "المستخدم غير موجود"}), 401
    return jsonify(
        {
            "id": emp.id,
            "email": getattr(emp, "username", None) or "",
            "display_name": emp.name or "مدير",
        }
    )


# ============== API: لوحة التحكم (stats, scheduled, drafts, templates, analytics, notifications, settings) ==============


@autoposter_bp.route("/api/stats", methods=["GET"])
@require_autoposter_login
def api_stats():
    """إحصائيات لوحة التحكم: صفحات متصلة، منشورات منشورة، مجدولة، تفاعل."""
    from datetime import datetime as dt
    from models.autoposter_facebook_page import AutoposterFacebookPage
    from models.autoposter_post import AutoposterPost
    tenant_slug = session.get("tenant_slug")
    try:
        pages_q = AutoposterFacebookPage.query.filter(AutoposterFacebookPage.access_token.isnot(None))
        if tenant_slug and hasattr(AutoposterFacebookPage, "tenant_slug"):
            pages_q = pages_q.filter_by(tenant_slug=tenant_slug)
        pages_connected = pages_q.count()
        posts_q = AutoposterPost.query.filter(AutoposterPost.status == "published")
        if tenant_slug and hasattr(AutoposterPost, "tenant_slug"):
            posts_q = posts_q.filter_by(tenant_slug=tenant_slug)
        posts_published = posts_q.count()
        now = dt.utcnow()
        scheduled_q = AutoposterPost.query.filter(
            AutoposterPost.scheduled_at.isnot(None),
            AutoposterPost.scheduled_at > now,
        )
        if tenant_slug and hasattr(AutoposterPost, "tenant_slug"):
            scheduled_q = scheduled_q.filter_by(tenant_slug=tenant_slug)
        scheduled = scheduled_q.count()
    except Exception as e:
        current_app.logger.exception("autoposter api_stats: %s", e)
        pages_connected = posts_published = scheduled = 0
    return jsonify({
        "pages_connected": pages_connected,
        "posts_published": posts_published,
        "scheduled": scheduled,
        "avg_engagement": 0,
    })


@autoposter_bp.route("/api/scheduled", methods=["GET"])
@require_autoposter_login
def api_scheduled():
    """قائمة المنشورات المجدولة (للعرض في لوحة التحكم)."""
    from datetime import datetime as dt
    from models.autoposter_post import AutoposterPost
    tenant_slug = session.get("tenant_slug")
    try:
        now = dt.utcnow()
        q = AutoposterPost.query.filter(
            AutoposterPost.scheduled_at.isnot(None),
            AutoposterPost.scheduled_at > now,
        ).order_by(AutoposterPost.scheduled_at.asc()).limit(50)
        if tenant_slug and hasattr(AutoposterPost, "tenant_slug"):
            q = q.filter_by(tenant_slug=tenant_slug)
        posts = q.all()
        scheduled = [p.to_dict() for p in posts]
    except Exception as e:
        current_app.logger.exception("autoposter api_scheduled: %s", e)
        scheduled = []
    return jsonify({"scheduled": scheduled})


@autoposter_bp.route("/api/drafts", methods=["GET"])
@require_autoposter_login
def api_drafts():
    """قائمة المسودات."""
    from models.autoposter_post import AutoposterPost
    tenant_slug = session.get("tenant_slug")
    try:
        q = AutoposterPost.query.filter(AutoposterPost.status == "draft").order_by(AutoposterPost.created_at.desc()).limit(50)
        if tenant_slug and hasattr(AutoposterPost, "tenant_slug"):
            q = q.filter_by(tenant_slug=tenant_slug)
        drafts = [p.to_dict() for p in q.all()]
    except Exception as e:
        current_app.logger.exception("autoposter api_drafts: %s", e)
        drafts = []
    return jsonify({"drafts": drafts})


@autoposter_bp.route("/api/templates", methods=["GET"])
@require_autoposter_login
def api_templates():
    """قوالب المنشورات (إن وُجدت — وإلا قائمة فارغة)."""
    return jsonify({"templates": []})


@autoposter_bp.route("/api/analytics", methods=["GET"])
@require_autoposter_login
def api_analytics():
    """تحليلات النشر (هيكل افتراضي للواجهة)."""
    return jsonify({
        "summary": {
            "by_type": {},
            "by_page": [],
        },
        "top_posts": [],
    })


@autoposter_bp.route("/api/notifications", methods=["GET"])
@require_autoposter_login
def api_notifications():
    """قائمة إشعارات الأوتوبوستر."""
    from models.autoposter_notification import AutoposterNotification
    try:
        q = AutoposterNotification.query.order_by(AutoposterNotification.created_at.desc()).limit(50)
        if session.get("tenant_slug") and hasattr(AutoposterNotification, "tenant_slug"):
            q = q.filter_by(tenant_slug=session.get("tenant_slug"))
        notifications = [n.to_dict() for n in q.all()]
    except Exception as e:
        current_app.logger.exception("autoposter api_notifications: %s", e)
        notifications = []
    return jsonify({"notifications": notifications})


@autoposter_bp.route("/api/notifications/read", methods=["POST"])
@require_autoposter_login
def api_notifications_read_all():
    """تعليم كل الإشعارات كمقروءة."""
    from models.autoposter_notification import AutoposterNotification
    try:
        q = AutoposterNotification.query.filter_by(read=False)
        if session.get("tenant_slug") and hasattr(AutoposterNotification, "tenant_slug"):
            q = q.filter_by(tenant_slug=session.get("tenant_slug"))
        for n in q:
            n.read = True
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("autoposter api_notifications_read_all: %s", e)
    return jsonify({"ok": True})


@autoposter_bp.route("/api/notifications/<int:notif_id>/read", methods=["POST"])
@require_autoposter_login
def api_notification_mark_read(notif_id):
    """تعليم إشعار واحد كمقروء."""
    from models.autoposter_notification import AutoposterNotification
    try:
        n = AutoposterNotification.query.get(notif_id)
        if n:
            n.read = True
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("autoposter api_notification_mark_read: %s", e)
    return jsonify({"ok": True})


@autoposter_bp.route("/api/settings", methods=["GET"])
@require_autoposter_login
def api_settings():
    """إعدادات فيسبوك وواجهات أخرى (للوحة التحكم)."""
    try:
        from models.publish_config import PublishConfig
        tenant_slug = session.get("tenant_slug")
        q = PublishConfig.query
        if tenant_slug:
            q = q.filter_by(tenant_slug=tenant_slug)
        cfg = q.first()
        if cfg:
            return jsonify({
                "facebook_app_id": getattr(cfg, "facebook_app_id", None) or "",
                "facebook_app_secret_set": bool(getattr(cfg, "facebook_app_secret", None)),
                "openai_api_key_set": False,
                "openai_model": "",
                "gemini_api_key_set": False,
                "gemini_model": "",
            })
    except Exception as e:
        current_app.logger.exception("autoposter api_settings: %s", e)
    return jsonify({
        "facebook_app_id": "",
        "facebook_app_secret_set": False,
        "openai_api_key_set": False,
        "openai_model": "",
        "gemini_api_key_set": False,
        "gemini_model": "",
    })


# ============== API: AI Agents ==============


@autoposter_bp.route("/api/agents", methods=["GET"])
@require_autoposter_login
def api_agents_list():
    tenant_slug = session.get("tenant_slug")
    q = Agent.query
    if tenant_slug:
        q = q.filter_by(tenant_slug=tenant_slug)
    agents = q.order_by(Agent.created_at.desc()).all()
    return jsonify({"agents": [a.to_dict() for a in agents]})


@autoposter_bp.route("/api/agents", methods=["POST"])
@require_autoposter_login
def api_agents_create():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "الاسم مطلوب"}), 400
    tenant_slug = session.get("tenant_slug")
    user_id = session.get("user_id")
    agent = Agent(
        tenant_slug=tenant_slug,
        user_id=user_id,
        name=name,
        description=(data.get("description") or "").strip() or None,
        default_model=(data.get("default_model") or "").strip() or None,
        instructions=(data.get("instructions") or "").strip() or None,
    )
    db.session.add(agent)
    db.session.commit()
    return jsonify({"success": True, "agent": agent.to_dict()})


# ============== API: Workflows ==============


@autoposter_bp.route("/workflows", methods=["GET"])
@autoposter_bp.route("/api/workflows", methods=["GET"])
@require_autoposter_login
def api_workflows_list():
    workflow_id = request.args.get("workflow_id", type=int)
    if workflow_id is not None:
        w = AgentWorkflow.query.get(workflow_id)
        if not w:
            return jsonify({"error": "workflow not found"}), 404
        return jsonify({"workflow": w.to_dict()})

    agent_id = request.args.get("agent_id", type=int)
    q = AgentWorkflow.query
    if agent_id:
        q = q.filter_by(agent_id=agent_id)
    workflows = q.order_by(AgentWorkflow.created_at.desc()).all()
    return jsonify({"workflows": [w.to_dict() for w in workflows]})


@autoposter_bp.route("/api/workflows/<int:workflow_id>", methods=["GET"])
@require_autoposter_login
def api_workflows_get(workflow_id: int):
    w = AgentWorkflow.query.get_or_404(workflow_id)
    return jsonify({"workflow": w.to_dict()})


@autoposter_bp.route("/api/workflows", methods=["POST"])
@require_autoposter_login
def api_workflows_create():
    data = request.get_json() or {}
    agent_id = data.get("agent_id")
    name = (data.get("name") or "").strip()
    if not agent_id or not name:
        return jsonify({"success": False, "error": "agent_id والاسم مطلوبان"}), 400
    graph = data.get("graph") or {}
    w = AgentWorkflow(
        agent_id=agent_id,
        name=name,
        description=(data.get("description") or "").strip() or None,
        is_active=bool(data.get("is_active", True)),
        graph_json=graph,
    )
    db.session.add(w)
    db.session.commit()
    return jsonify({"success": True, "workflow": w.to_dict()})


@autoposter_bp.route("/api/workflows/<int:workflow_id>", methods=["PUT"])
@require_autoposter_login
def api_workflows_update(workflow_id: int):
    data = request.get_json() or {}
    w = AgentWorkflow.query.get_or_404(workflow_id)
    if "name" in data:
        w.name = (data.get("name") or "").strip() or w.name
    if "description" in data:
        w.description = (data.get("description") or "").strip() or None
    if "is_active" in data:
        w.is_active = bool(data.get("is_active"))
    if "graph" in data:
        w.graph_json = data.get("graph") or {}
    db.session.commit()
    return jsonify({"success": True, "workflow": w.to_dict()})


@autoposter_bp.route("/api/workflows/<int:workflow_id>", methods=["DELETE"])
@require_autoposter_login
def api_workflows_delete(workflow_id: int):
    """حذف Workflow واحد وكل ما يتعلّق به من تنفيذات وسجلات وتعليقات."""
    w = AgentWorkflow.query.get_or_404(workflow_id)

    executions = list(w.executions)
    for exe in executions:
        AgentComment.query.filter_by(handled_by_execution_id=exe.id).delete()
        AgentExecutionLog.query.filter_by(execution_id=exe.id).delete()
        db.session.delete(exe)

    db.session.delete(w)
    db.session.commit()
    return jsonify({"success": True})


@autoposter_bp.route("/api/workflows/<int:workflow_id>/run", methods=["POST"])
@require_autoposter_login
def api_workflows_run(workflow_id: int):
    """تشغيل Workflow باستخدام محرّك العقد الأساسي."""
    w = AgentWorkflow.query.get_or_404(workflow_id)
    exe = AgentExecution(workflow_id=w.id, status="running")
    db.session.add(exe)
    db.session.commit()
    execute_workflow(exe)
    db.session.refresh(exe)
    return jsonify({"success": True, "execution": exe.to_dict()})


# ============== API: Webhooks (WhatsApp / Telegram) ==============


@autoposter_bp.route("/api/webhooks/whatsapp", methods=["POST"])
def whatsapp_webhook():
    """Webhook مبسّط لرسائل واتساب: يتوقع workflow_id في كويري سترنج ويشغّل الوكيل."""
    data = request.get_json() or {}
    workflow_id = request.args.get("workflow_id", type=int)
    if not workflow_id:
        return (
            jsonify(
                {"success": False, "error": "workflow_id مطلوب في مسار الاستدعاء"}
            ),
            400,
        )

    w = AgentWorkflow.query.get_or_404(workflow_id)

    message_text = (
        data.get("message_text")
        or data.get("text")
        or data.get("body")
        or ""
    )
    from_phone = data.get("from_phone") or data.get("from") or ""
    message_id = data.get("message_id") or data.get("id") or ""

    exe = AgentExecution(workflow_id=w.id, status="running")
    db.session.add(exe)
    db.session.commit()

    ctx = {
        "message_text": message_text,
        "from_phone": from_phone,
        "message_id": message_id,
        "platform": "whatsapp",
    }

    execute_workflow(exe, initial_context=ctx)
    db.session.refresh(exe)
    return jsonify({"success": True, "execution": exe.to_dict()})


@autoposter_bp.route("/api/webhooks/telegram", methods=["POST"])
def telegram_webhook():
    """Webhook مبسّط لرسائل تيليجرام: يتوقع workflow_id في كويري سترنج ويشغّل الوكيل."""
    data = request.get_json() or {}
    workflow_id = request.args.get("workflow_id", type=int)
    if not workflow_id:
        return (
            jsonify(
                {"success": False, "error": "workflow_id مطلوب في مسار الاستدعاء"}
            ),
            400,
        )

    w = AgentWorkflow.query.get_or_404(workflow_id)

    message = data.get("message") or {}
    message_text = message.get("text") or data.get("message_text") or ""
    chat = message.get("chat") or {}
    chat_id = chat.get("id") or data.get("chat_id") or ""
    username = chat.get("username") or data.get("username") or ""

    exe = AgentExecution(workflow_id=w.id, status="running")
    db.session.add(exe)
    db.session.commit()

    ctx = {
        "message_text": message_text,
        "chat_id": chat_id,
        "username": username,
        "platform": "telegram",
    }

    execute_workflow(exe, initial_context=ctx)
    db.session.refresh(exe)
    return jsonify({"success": True, "execution": exe.to_dict()})


# ============== API: تسجيل الخروج من واجهة النشر القديمة ==============


@autoposter_bp.route("/api/logout", methods=["POST"])
@require_autoposter_login
def api_logout():
    session.pop("user_id", None)
    session.pop("tenant_slug", None)
    session.pop("role", None)
    return jsonify({"success": True})

