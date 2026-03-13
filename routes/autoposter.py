# Blueprint النشر التلقائي لفيسبوك — يُربط تحت /autoposter
from datetime import datetime
from functools import wraps
from pathlib import Path
import json
from flask import Blueprint, request, session, redirect, url_for, jsonify, render_template, g, current_app

from extensions import db
from models.autoposter_facebook_page import AutoposterFacebookPage
from models.autoposter_post import AutoposterPost
from models.social_account import SocialAccount
from models.autoposter_notification import AutoposterNotification
from models.autoposter_template import AutoposterTemplate
from models.ai_agent import Agent, AgentWorkflow, AgentExecution, AgentExecutionLog, AgentComment
from social_ai.workflow_engine import execute_workflow
from routes.autoposter_facebook import (
    get_oauth_url,
    exchange_code_for_user_token,
    get_long_lived_token,
    get_pages_with_tokens,
)
from services.autoposter_service import (
    publish_now_for_pages,
    schedule_posts_for_pages,
    run_scheduled_posts_for_all_tenants as service_run_scheduled_for_all_tenants,
)
from services.media_service import save_uploaded_file, inspect_media, detect_kind

autoposter_bp = Blueprint("autoposter", __name__, url_prefix="/autoposter", static_folder="../static/autoposter", static_url_path="/static/autoposter")


@autoposter_bp.before_request
def _ensure_autoposter_tables():
    """التأكد من وجود جداول النشر التلقائي وأعمدة فيسبوك في إعدادات النظام."""
    tenant_slug = getattr(g, "tenant", None)
    if not tenant_slug:
        return
    try:
        from extensions_tenant import get_tenant_engine
        from sqlalchemy import inspect, text
        engine = get_tenant_engine(tenant_slug)
        for model in (AutoposterFacebookPage, AutoposterPost, AutoposterNotification, AutoposterTemplate):
            model.__table__.create(engine, checkfirst=True)
        # إضافة أعمدة فيسبوك لجدول system_settings إن وُجد ولم تكن الأعمدة موجودة
        inspector = inspect(engine)
        if "system_settings" in inspector.get_table_names():
            cols = {c["name"] for c in inspector.get_columns("system_settings")}
            with engine.connect() as conn:
                if "facebook_app_id" not in cols:
                    conn.execute(text("ALTER TABLE system_settings ADD COLUMN facebook_app_id VARCHAR(100)"))
                    conn.commit()
                if "facebook_app_secret" not in cols:
                    conn.execute(text("ALTER TABLE system_settings ADD COLUMN facebook_app_secret VARCHAR(255)"))
                    conn.commit()
        if "autoposter_posts" in inspector.get_table_names():
            post_cols = {c["name"] for c in inspector.get_columns("autoposter_posts")}
            with engine.connect() as conn:
                if "image_url" not in post_cols:
                    conn.execute(text("ALTER TABLE autoposter_posts ADD COLUMN image_url VARCHAR(512)"))
                    conn.commit()
                if "video_url" not in post_cols:
                    conn.execute(text("ALTER TABLE autoposter_posts ADD COLUMN video_url VARCHAR(512)"))
                    conn.commit()
                if "post_type" not in post_cols:
                    conn.execute(text("ALTER TABLE autoposter_posts ADD COLUMN post_type VARCHAR(20) DEFAULT 'post'"))
                    conn.commit()
                if "retry_count" not in post_cols:
                    conn.execute(text("ALTER TABLE autoposter_posts ADD COLUMN retry_count INTEGER DEFAULT 0"))
                    conn.commit()
                if "last_attempt_at" not in post_cols:
                    conn.execute(text("ALTER TABLE autoposter_posts ADD COLUMN last_attempt_at DATETIME"))
                    conn.commit()
                if "channel" not in post_cols:
                    conn.execute(text("ALTER TABLE autoposter_posts ADD COLUMN channel VARCHAR(30) DEFAULT 'facebook_page'"))
                    conn.commit()
    except Exception:
        pass


def require_autoposter_login(f):
    @wraps(f)
    def inner(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("index.login") + "?next=" + request.path)
        return f(*args, **kwargs)
    return inner


def _add_notification(title, body=None):
    n = AutoposterNotification(title=title, body=body)
    db.session.add(n)
    db.session.commit()


# --- الصفحات (لوحة واحدة SPA) ---
@autoposter_bp.route("/")
@autoposter_bp.route("/dashboard")
@require_autoposter_login
def dashboard():
    """الصفحة الرئيسية للنشر التلقائي + قائمة وكلاء AI في السايد بار."""
    from models.ai_agent import Agent

    tenant_slug = session.get("tenant_slug")
    q = Agent.query
    if tenant_slug:
        q = q.filter_by(tenant_slug=tenant_slug)
    agents = q.order_by(Agent.created_at.desc()).all()
    return render_template("autoposter/dashboard.html", ai_agents=agents)


@autoposter_bp.route("/pages")
@require_autoposter_login
def pages_view():
    return redirect(url_for("autoposter.dashboard") + "#pages")


@autoposter_bp.route("/create")
@require_autoposter_login
def create_view():
    return redirect(url_for("autoposter.dashboard") + "#create")


@autoposter_bp.route("/upload")
@require_autoposter_login
def upload_view():
    """صفحة مستقلة لرفع فيديوهات الأوتوبوستر."""
    return render_template("autoposter/upload.html")

@autoposter_bp.route("/ai-agent")
def ai_agent_view():
    """واجهة AI Agent / Workflow Builder — بدون تسجيل دخول."""
    return render_template("autoposter/ai_agent.html")


# --- API: المستخدم الحالي (من جلسة المنصة) ---
@autoposter_bp.route("/api/me", methods=["GET"])
@require_autoposter_login
def api_me():
    from models.employee import Employee
    emp = Employee.query.get(session.get("user_id"))
    if not emp:
        return jsonify({"error": "المستخدم غير موجود"}), 401
    return jsonify({
        "id": emp.id,
        "email": getattr(emp, "username", None) or "",
        "display_name": emp.name or "مدير",
    })


# --- API: AI Agents & Workflows ---
@autoposter_bp.route("/api/agents", methods=["GET"])
@require_autoposter_login
def api_agents_list():
    tenant_slug = session.get("tenant_slug")
    user_id = session.get("user_id")
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
    """حذف Workflow واحد وكل ما يتعلّق به من تنفيذات وسجلات حتى لا يحدث خطأ قيود علاقات."""
    w = AgentWorkflow.query.get_or_404(workflow_id)

    # احذف كل عمليات التنفيذ المرتبطة بهذا الوورك فلو مع سجلاتها والتعليقات المرتبطة بها
    executions = list(w.executions)
    for exe in executions:
        # حذف التعليقات المرتبطة بهذا التنفيذ (أو يمكنك فقط فك الارتباط إن أردت الحفاظ عليها)
        AgentComment.query.filter_by(handled_by_execution_id=exe.id).delete()
        # حذف سجلات التنفيذ
        AgentExecutionLog.query.filter_by(execution_id=exe.id).delete()
        # حذف التنفيذ نفسه
        db.session.delete(exe)

    # وأخيراً حذف الوورك فلو
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


# --- API: إحصائيات ---
@autoposter_bp.route("/api/stats", methods=["GET"])
@require_autoposter_login
def api_stats():
    pages_count = AutoposterFacebookPage.query.count()
    published_count = AutoposterPost.query.filter_by(status="published").count()
    scheduled_count = AutoposterPost.query.filter_by(status="scheduled").count()
    return jsonify({
        "pages_connected": pages_count,
        "posts_published": published_count,
        "scheduled": scheduled_count,
        "avg_engagement": 0,
    })


# --- API: الصفحات المتصلة ---
@autoposter_bp.route("/api/pages", methods=["GET"])
@require_autoposter_login
def api_pages_list():
    pages = AutoposterFacebookPage.query.all()
    return jsonify({"pages": [p.to_dict() for p in pages]})


@autoposter_bp.route("/api/pages/<page_id>", methods=["DELETE"])
@require_autoposter_login
def api_page_delete(page_id):
    """حذف صفحة فيسبوك من النظام (تُزال من القائمة ولا يعود النشر عليها حتى يعيد المستخدم ربطها)."""
    page = AutoposterFacebookPage.query.filter_by(page_id=page_id).first()
    if not page:
        return jsonify({"error": "الصفحة غير موجودة"}), 404
    tenant_slug = getattr(g, "tenant", None)
    if tenant_slug:
        SocialAccount.query.filter_by(
            tenant_slug=tenant_slug,
            platform="facebook",
            account_id=page_id,
        ).delete()
    db.session.delete(page)
    db.session.commit()
    return jsonify({"ok": True})


@autoposter_bp.route("/api/pages/<page_id>/disconnect", methods=["POST"])
@require_autoposter_login
def api_page_disconnect(page_id):
    """فك ارتباط الصفحة (مسح التوكن — تبقى في القائمة لكن لا يمكن النشر حتى إعادة الربط)."""
    page = AutoposterFacebookPage.query.filter_by(page_id=page_id).first()
    if not page:
        return jsonify({"error": "الصفحة غير موجودة"}), 404
    page.access_token = ""
    tenant_slug = getattr(g, "tenant", None)
    if tenant_slug:
        for acc in SocialAccount.query.filter_by(
            tenant_slug=tenant_slug,
            platform="facebook",
            account_id=page_id,
        ):
            acc.access_token = ""
    db.session.commit()
    return jsonify({"ok": True})


# --- API: ربط فيسبوك (إرجاع رابط OAuth) ---
@autoposter_bp.route("/api/facebook/connect", methods=["GET"])
@require_autoposter_login
def api_facebook_connect():
    if not getattr(request, "host", None):
        return jsonify({"error": "لم يتم ضبط الاستضافة", "url": None}), 400
    scheme = request.environ.get("HTTP_X_FORWARDED_PROTO") or request.scheme or "https"
    base = f"{scheme}://{request.host}".rstrip("/")
    redirect_uri = f"{base}/autoposter/api/facebook/callback"
    try:
        result = get_oauth_url(redirect_uri=redirect_uri)
        url_str = result[0] if isinstance(result, (list, tuple)) else result
    except Exception:
        return jsonify({"error": "لم يتم ضبط FACEBOOK_APP_ID أو الإعدادات", "url": None}), 400
    if not url_str or "client_id" not in str(url_str):
        return jsonify({"error": "لم يتم ضبط FACEBOOK_APP_ID في الإعدادات", "url": None}), 400
    return jsonify({"url": url_str})


# --- OAuth Callback ---
@autoposter_bp.route("/api/facebook/callback", methods=["GET"])
def api_facebook_callback():
    code = request.args.get("code")
    if not code:
        return redirect(url_for("autoposter.dashboard") + "?facebook=error")
    if not session.get("user_id"):
        return redirect(url_for("index.login") + "?next=/autoposter/")
    # ضروري: تعيين المستأجر من الجلسة حتى تُحفظ الصفحات في قاعدة الشركة وليس Core
    tenant_slug = session.get("tenant_slug")
    if tenant_slug:
        g.tenant = tenant_slug
    scheme = request.environ.get("HTTP_X_FORWARDED_PROTO") or request.scheme or "https"
    base = f"{scheme}://{request.host}".rstrip("/")
    redirect_uri = f"{base}/autoposter/api/facebook/callback"
    try:
        short_token = exchange_code_for_user_token(code, redirect_uri)
        long_token = get_long_lived_token(short_token)
        pages_data = get_pages_with_tokens(long_token)
        for p in pages_data:
            page_id = p["id"]
            page_name = p.get("name", "صفحة")
            page_token = p.get("access_token", "")
            existing = AutoposterFacebookPage.query.filter_by(page_id=page_id).first()
            if existing:
                existing.name = page_name
                existing.access_token = page_token
            else:
                fp = AutoposterFacebookPage(
                    page_id=page_id,
                    name=page_name,
                    access_token=page_token,
                )
                db.session.add(fp)
            # مزامنة مع SocialAccount حتى يستخدمها AI Agent (عقدة Publisher)
            if tenant_slug and page_token:
                acc = SocialAccount.query.filter_by(
                    tenant_slug=tenant_slug,
                    platform="facebook",
                    account_id=page_id,
                ).first()
                if acc:
                    acc.username = page_name
                    acc.access_token = page_token
                else:
                    acc = SocialAccount(
                        tenant_slug=tenant_slug,
                        user_id=session.get("user_id"),
                        platform="facebook",
                        account_id=page_id,
                        username=page_name,
                        access_token=page_token,
                    )
                    db.session.add(acc)
        db.session.commit()
        _add_notification("تم ربط الصفحات", "تم ربط صفحات فيسبوك بنجاح. يمكنك النشر من لوحة التحكم أو من AI Agent.")
    except Exception as e:
        db.session.rollback()
        return redirect(url_for("autoposter.dashboard") + "?facebook=error&msg=" + str(e))
    return redirect(url_for("autoposter.dashboard") + "#pages")


# --- تقديم الفيديو والثمبنايل عبر التطبيق (بديل عن Nginx /uploads/ لتجنب 404 على السيرفر) ---
from flask import send_file
from werkzeug.utils import secure_filename

def _safe_filename(name: str) -> str:
    """اسم ملف آمن بدون مسارات فرعية."""
    return secure_filename(name) or "file"

@autoposter_bp.route("/serve/video/<path:filename>", methods=["GET"])
def serve_video(filename):
    """تقديم ملف فيديو من مجلد الرفع (يعمل بدون إعداد Nginx لـ /uploads/)."""
    from services.media_service import get_video_upload_root
    name = _safe_filename(filename.split("/")[-1] if "/" in filename else filename)
    if not name:
        return jsonify({"error": "اسم ملف غير صالح"}), 400
    root = get_video_upload_root()
    path = root / name
    if not path.exists() or not path.is_file():
        return jsonify({"error": "الملف غير موجود"}), 404
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return jsonify({"error": "مسار غير مسموح"}), 403
    return send_file(path, mimetype="video/mp4", as_attachment=False, max_age=3600)

@autoposter_bp.route("/serve/thumbnail/<path:filename>", methods=["GET"])
def serve_thumbnail(filename):
    """تقديم صورة الثمبنايل من مجلد الرفع."""
    from services.media_service import get_thumbnail_upload_root
    name = _safe_filename(filename.split("/")[-1] if "/" in filename else filename)
    if not name:
        return jsonify({"error": "اسم ملف غير صالح"}), 400
    root = get_thumbnail_upload_root()
    path = root / name
    if not path.exists() or not path.is_file():
        return jsonify({"error": "الملف غير موجود"}), 404
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return jsonify({"error": "مسار غير مسموح"}), 403
    return send_file(path, mimetype="image/jpeg", as_attachment=False, max_age=3600)


# --- API: رفع صورة أو فيديو ---
UPLOAD_ALLOWED = ("image/jpeg", "image/png", "image/gif", "image/webp", "video/mp4", "video/quicktime")
UPLOAD_MAX_MB = 200

@autoposter_bp.route("/api/upload", methods=["POST"])
@require_autoposter_login
def api_upload():
    if "file" not in request.files and "media" not in request.files:
        return jsonify({"ok": False, "error_code": "no_file", "message": "لم يُرفع ملف"}), 400
    file = request.files.get("file") or request.files.get("media")
    if not file or not file.filename:
        return jsonify({"ok": False, "error_code": "no_file", "message": "لم يُرفع ملف"}), 400

    try:
        result = save_uploaded_file(file, max_mb=UPLOAD_MAX_MB)
    except Exception as e:
        current_app.logger.exception("api_upload save_uploaded_file failed: %s", e)
        return jsonify({
            "ok": False,
            "error_code": "save_failed",
            "message": "تعذر معالجة الملف على الخادم. تحقق من مجلد الرفع ووجود ffmpeg إن لزم.",
        }), 500
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


def _media_url_to_static_path(media_url: str):
    """
    تحويل رابط وسائط (كامل أو نسبي) إلى مسار نسبي تحت static (بدون مقطع static/).
    مثال: /static/autoposter/uploads/x.mp4 -> autoposter/uploads/x.mp4
    """
    from urllib.parse import urlparse
    parsed = urlparse(media_url)
    path = (parsed.path or "").strip().lstrip("/")
    if not path:
        return None
    script_root = (request.script_root or "").strip().rstrip("/").lstrip("/")
    if script_root and path.startswith(script_root + "/"):
        path = path[len(script_root) + 1:]
    if path.startswith("static/"):
        path = path[7:]
    if not path.startswith("autoposter/"):
        return None
    return path


def _media_url_to_fs_path(media_url: str):
    """
    إرجاع مسار الملف على القرص من رابط الوسائط، أو None.
    يدعم: /autoposter/serve/video/<name>، /autoposter/serve/thumbnail/<name>، والمسارات تحت static.
    """
    from urllib.parse import urlparse
    from services.media_service import get_video_upload_root, get_thumbnail_upload_root
    parsed = urlparse(media_url)
    path = (parsed.path or "").strip().lstrip("/")
    if not path:
        return None
    script_root = (request.script_root or "").strip().rstrip("/").lstrip("/")
    if script_root and path.startswith(script_root + "/"):
        path = path[len(script_root) + 1:]
    # روابط التقديم عبر التطبيق
    if path.startswith("autoposter/serve/video/"):
        name = path[len("autoposter/serve/video/"):].split("/")[0] or None
        if name and ".." not in name:
            p = get_video_upload_root() / name
            return p if p.exists() and p.is_file() else None
        return None
    if path.startswith("autoposter/serve/thumbnail/"):
        name = path[len("autoposter/serve/thumbnail/"):].split("/")[0] or None
        if name and ".." not in name:
            p = get_thumbnail_upload_root() / name
            return p if p.exists() and p.is_file() else None
        return None
    # مسارات static القديمة
    rel = _media_url_to_static_path(media_url)
    if not rel:
        return None
    root = Path(current_app.root_path)
    fs_path = (root / "static" / rel).resolve()
    static_root = (root / "static").resolve()
    try:
        fs_path.relative_to(static_root)
    except ValueError:
        return None
    return fs_path if fs_path.exists() and fs_path.is_file() else None


# --- API: فحص وسائط قبل النشر (pre-publish check) ---
@autoposter_bp.route("/api/media/check", methods=["POST"])
@require_autoposter_login
def api_media_check():
    """
    فحص ملف (بعد الرفع) قبل تنفيذ النشر الفعلي.

    يتوقع:
    {
      \"image_url\": \"...\" | null,
      \"video_url\": \"...\" | null,
      \"post_type\": \"post\" | \"story\" | \"reels\"
    }
    ويرجع:
    {
      \"ok\": bool,
      \"warnings\": [str],
      \"error_code\": str | null,
      \"message\": str | null,
      \"kind\": \"image\" | \"video\" | null,
      \"size_mb\": float | null,
      \"width\": int | null,
      \"height\": int | null,
      \"duration_sec\": float | null
    }
    """
    try:
        data = request.get_json() or {}
        image_url = (data.get("image_url") or "").strip() or None
        video_url = (data.get("video_url") or "").strip() or None
        post_type = (data.get("post_type") or "post").strip().lower()

        if not image_url and not video_url:
            return jsonify({
                "ok": False,
                "error_code": "no_media",
                "message": "لا يوجد ملف صورة أو فيديو لفحصه.",
                "warnings": [],
            }), 400

        media_url = video_url or image_url
        fs_path = _media_url_to_fs_path(media_url)
        if not fs_path:
            return jsonify({
                "ok": False,
                "error_code": "invalid_url",
                "message": "رابط الملف غير صالح أو لا ينتمي إلى مجلد الرفع.",
                "warnings": [],
            }), 400

        size_bytes = fs_path.stat().st_size
        size_mb = round(size_bytes / (1024 * 1024), 2)

        ext = fs_path.suffix.lower()
        if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            kind = "image"
        elif ext in (".mp4", ".mov", ".webm"):
            kind = "video"
        else:
            kind = None

        width, height, duration = None, None, None
        if kind in ("image", "video"):
            w, h, dur = inspect_media(fs_path, kind=kind)  # type: ignore[arg-type]
            width, height, duration = w, h, dur

        warnings = []
        if kind == "video":
            if size_mb > 80:
                warnings.append("حجم الفيديو كبير (أكثر من 80 ميجا). قد يستغرق الرفع إلى فيسبوك وقتاً طويلاً أو يفشل.")
            if duration and duration > 60 * 5:
                warnings.append("مدة الفيديو أطول من 5 دقائق؛ قد ترفضها بعض أنواع المنشورات أو تؤثر على تجربة المتابعين.")
            if post_type == "reels" and duration and duration > 90:
                warnings.append("مدة الفيديو أطول من 90 ثانية؛ قد لا يُقبل كـ Reels في بعض الإعدادات.")
        elif kind == "image":
            if max(width or 0, height or 0) > 4000:
                warnings.append("أبعاد الصورة كبيرة جداً؛ قد يتم ضغطها بشدة عند النشر.")
            if size_mb > 10:
                warnings.append("حجم الصورة كبير (أكثر من 10 ميجا). يفضّل استخدام صورة مضغوطة.")

        return jsonify({
            "ok": True,
            "error_code": None,
            "message": None,
            "kind": kind,
            "size_mb": size_mb,
            "width": width,
            "height": height,
            "duration_sec": duration,
            "warnings": warnings,
        })
    except Exception as e:
        current_app.logger.exception("api_media_check failed: %s", e)
        return jsonify({
            "ok": False,
            "error_code": "check_failed",
            "message": "فشل فحص الملف. جرّب مرة أخرى أو راجع السجلات.",
            "warnings": [],
        }), 500


def _make_absolute_media_url(url: str | None) -> str | None:
    """تحويل رابط وسائط نسبي إلى رابط مطلق ليُستخدم في استدعاء فيسبوك."""
    if not url or not url.strip():
        return None
    url = url.strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    base = (current_app.config.get("BASE_URL") or "").rstrip("/") or request.url_root.rstrip("/")
    return base + (url if url.startswith("/") else "/" + url)


# --- API: نشر فوري أو مجدول (يدعم صورة/فيديو) ---
@autoposter_bp.route("/api/posts", methods=["POST"])
@require_autoposter_login
def api_posts_create():
    try:
        # يدعم JSON القديم + multipart الجديد
        video_url = None
        image_url = None
        scheduled_at = None
        page_ids = []

        if request.files:
            # -------- Multipart / FormData (يدعم رفع فيديو مباشر) --------
            form = request.form
            text = (form.get("text") or form.get("content") or "").strip()

            # page_ids يمكن أن تصل كقائمة أو JSON أو نص مفصول بفواصل
            raw_page_ids = form.getlist("page_ids[]") or form.getlist("page_ids")
            if not raw_page_ids:
                raw = (form.get("page_ids") or "").strip()
                if raw:
                    try:
                        maybe = json.loads(raw)
                        if isinstance(maybe, list):
                            raw_page_ids = [str(x) for x in maybe if x]
                    except Exception:
                        raw_page_ids = [p.strip() for p in raw.split(",") if p.strip()]
            page_ids = raw_page_ids

            image_url = (form.get("image_url") or "").strip() or None
            scheduled_at = form.get("scheduled_at") or None
            post_type = (form.get("post_type") or "post").strip().lower()

            # حفظ ملف الفيديو عبر خدمة الوسائط (نفس مسار api/upload: تحويل MOV→MP4، thumbnail، مسار موحّد)
            file = request.files.get("video")
            if file and file.filename:
                result = save_uploaded_file(file, max_mb=UPLOAD_MAX_MB)
                if not result.get("ok"):
                    return jsonify({
                        "error": result.get("message") or "فشل رفع الفيديو",
                    }), 400
                video_url = result.get("url") or ""
                if not video_url:
                    return jsonify({"error": "لم يُرجَع رابط الفيديو بعد الرفع"}), 500
        else:
            # -------- JSON (السلوك القديم) --------
            data = request.get_json() or {}
            text = (data.get("text") or data.get("content") or "").strip()
            page_ids = data.get("page_ids") or []
            image_url = (data.get("image_url") or "").strip() or None
            video_url = (data.get("video_url") or "").strip() or None
            scheduled_at = data.get("scheduled_at")
            post_type = (data.get("post_type") or "post").strip().lower()

        if post_type not in ("post", "story", "reels"):
            post_type = "post"
        if post_type == "story" and not image_url and not video_url:
            return jsonify({"error": "الستوري يتطلب صورة أو فيديو"}), 400
        if post_type == "reels" and not video_url:
            return jsonify({"error": "الريلز يتطلب فيديو"}), 400
        if not text and not image_url and not video_url:
            return jsonify({"error": "الرجاء إدخال محتوى أو رفع صورة/فيديو"}), 400
        if not page_ids:
            return jsonify({"error": "اختر صفحة واحدة على الأقل"}), 400

        pages = AutoposterFacebookPage.query.filter(AutoposterFacebookPage.page_id.in_(page_ids)).all()
        if not pages:
            return jsonify({"error": "لم يتم العثور على الصفحات المحددة"}), 400

        content = text or ""
        image_url_abs = _make_absolute_media_url(image_url)
        video_url_abs = _make_absolute_media_url(video_url)

        if scheduled_at:
            try:
                at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            except Exception:
                return jsonify({"error": "صيغة التاريخ غير صحيحة"}), 400
            schedule_posts_for_pages(
                pages=pages,
                content=content,
                image_url=image_url_abs or image_url,
                video_url=video_url_abs or video_url,
                post_type=post_type,
                scheduled_at=at,
            )
            _add_notification("تم جدولة المنشور", f"سيُنشر في {at}")
            return jsonify({"success": True, "scheduled_at": scheduled_at})

        published, errors = publish_now_for_pages(
            pages=pages,
            content=content,
            image_url=image_url_abs,
            video_url=video_url_abs,
            post_type=post_type,
        )
        if errors and not published:
            # جميع الصفحات فشلت
            joined_errors = "; ".join(e.get("error", "") for e in errors)
            return jsonify({"error": joined_errors or "فشل النشر لكل الصفحات", "results": {"published": published, "errors": errors}}), 500

        # إشعار مختصر بالصفحات التي نُشر عليها
        published_names = [p.get("page_name") for p in published if p.get("page_name")]
        if published_names:
            _add_notification("تم نشر المنشور", f"نُشر على: {', '.join(published_names)}")
        return jsonify({
            "success": True,
            "published": published_names,
            "errors": errors if errors else None,
            "results": {
                "published": published,
                "errors": errors,
            },
        })
    except Exception as e:
        current_app.logger.exception("api_posts_create failed: %s", e)
        return jsonify({
            "error": "هناك مشكلة في معالجة المنشور أو الفيديو. جرّب ملفاً آخر أو راجع إعدادات الخادم (مجلد الرفع، ffmpeg).",
        }), 500


# --- API: المنشورات المجدولة ---
@autoposter_bp.route("/api/scheduled", methods=["GET"])
@require_autoposter_login
def api_scheduled_list():
    posts = AutoposterPost.query.filter_by(status="scheduled").order_by(AutoposterPost.scheduled_at.asc()).all()
    return jsonify({"scheduled": [p.to_dict() for p in posts]})


@autoposter_bp.route("/api/scheduled", methods=["POST"])
@require_autoposter_login
def api_scheduled_create():
    data = request.get_json() or {}
    text = (data.get("text") or data.get("content") or "").strip()
    page_ids = data.get("page_ids") or []
    scheduled_at = data.get("scheduled_at")
    image_url = (data.get("image_url") or "").strip() or None
    video_url = (data.get("video_url") or "").strip() or None
    post_type = (data.get("post_type") or "post").strip().lower()
    if post_type not in ("post", "story", "reels"):
        post_type = "post"
    if post_type == "story" and not image_url and not video_url:
        return jsonify({"error": "الستوري يتطلب صورة أو فيديو"}), 400
    if post_type == "reels" and not video_url:
        return jsonify({"error": "الريلز يتطلب فيديو"}), 400
    if not text and not image_url and not video_url:
        return jsonify({"error": "محتوى أو صورة/فيديو مطلوب"}), 400
    if not page_ids or not scheduled_at:
        return jsonify({"error": "صفحات ووقت الجدولة مطلوبة"}), 400
    try:
        at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
    except Exception:
        return jsonify({"error": "صيغة التاريخ غير صحيحة"}), 400

    pages = AutoposterFacebookPage.query.filter(AutoposterFacebookPage.page_id.in_(page_ids)).all()
    if not pages:
        return jsonify({"error": "لم يتم العثور على الصفحات"}), 400

    for page in pages:
        post = AutoposterPost(
            page_id=page.page_id,
            page_name=page.name,
            content=text or "",
            image_url=image_url,
            video_url=video_url,
            post_type=post_type,
            status="scheduled",
            scheduled_at=at,
        )
        db.session.add(post)
    db.session.commit()
    _add_notification("تم جدولة المنشور", f"سيُنشر في {at}")
    return jsonify({"success": True, "scheduled_at": scheduled_at})


# --- API: القوالب (Templates) ---
@autoposter_bp.route("/api/templates", methods=["GET"])
@require_autoposter_login
def api_templates_list():
    items = AutoposterTemplate.query.order_by(AutoposterTemplate.created_at.desc()).all()
    return jsonify({"templates": [t.to_dict() for t in items]})


@autoposter_bp.route("/api/templates", methods=["POST"])
@require_autoposter_login
def api_templates_save():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    content = (data.get("content") or "").strip()
    post_type = (data.get("post_type") or "post").strip().lower()
    if not name or not content:
        return jsonify({"error": "الاسم والمحتوى مطلوبان"}), 400
    if post_type not in ("post", "story", "reels"):
        post_type = "post"
    image_url = (data.get("image_url") or "").strip() or None
    video_url = (data.get("video_url") or "").strip() or None
    template_id = data.get("id")
    if template_id:
        tpl = AutoposterTemplate.query.get(template_id)
        if not tpl:
            return jsonify({"error": "القالب غير موجود"}), 404
        tpl.name = name
        tpl.content = content
        tpl.post_type = post_type
        tpl.image_url = image_url
        tpl.video_url = video_url
    else:
        tpl = AutoposterTemplate(
            name=name,
            content=content,
            post_type=post_type,
            image_url=image_url,
            video_url=video_url,
        )
        db.session.add(tpl)
    db.session.commit()
    return jsonify({"success": True, "template": tpl.to_dict()})


@autoposter_bp.route("/api/templates/<int:template_id>", methods=["DELETE"])
@require_autoposter_login
def api_templates_delete(template_id):
    tpl = AutoposterTemplate.query.get_or_404(template_id)
    db.session.delete(tpl)
    db.session.commit()
    return jsonify({"success": True})


# --- API: المسودات (Drafts) ---
@autoposter_bp.route("/api/drafts", methods=["GET"])
@require_autoposter_login
def api_drafts_list():
    posts = AutoposterPost.query.filter_by(status="draft").order_by(AutoposterPost.created_at.desc()).limit(20).all()
    return jsonify({"drafts": [p.to_dict() for p in posts]})


@autoposter_bp.route("/api/drafts", methods=["POST"])
@require_autoposter_login
def api_drafts_create():
    data = request.get_json() or {}
    text = (data.get("text") or data.get("content") or "").strip()
    page_ids = data.get("page_ids") or []
    image_url = (data.get("image_url") or "").strip() or None
    video_url = (data.get("video_url") or "").strip() or None
    post_type = (data.get("post_type") or "post").strip().lower()
    if post_type not in ("post", "story", "reels"):
        post_type = "post"
    if not text and not image_url and not video_url:
        return jsonify({"error": "لا يمكن حفظ مسودة بدون محتوى أو وسائط"}), 400
    if not page_ids:
        return jsonify({"error": "اختر صفحة واحدة على الأقل للمسودة"}), 400

    pages = AutoposterFacebookPage.query.filter(AutoposterFacebookPage.page_id.in_(page_ids)).all()
    if not pages:
        return jsonify({"error": "لم يتم العثور على الصفحات المحددة"}), 400

    for page in pages:
        post = AutoposterPost(
            page_id=page.page_id,
            page_name=page.name,
            content=text or "",
            image_url=image_url,
            video_url=video_url,
            post_type=post_type,
            status="draft",
        )
        db.session.add(post)
    db.session.commit()
    return jsonify({"success": True})


# --- API: الإشعارات ---
@autoposter_bp.route("/api/notifications", methods=["GET"])
@require_autoposter_login
def api_notifications():
    items = AutoposterNotification.query.order_by(AutoposterNotification.created_at.desc()).limit(50).all()
    unread_count = sum(1 for n in items if not n.read)
    return jsonify({
        "notifications": [n.to_dict() for n in items],
        "unread_count": unread_count,
    })


@autoposter_bp.route("/api/notifications/read", methods=["POST"])
@require_autoposter_login
def api_notifications_read():
    for n in AutoposterNotification.query.all():
        n.read = True
    db.session.commit()
    return jsonify({"success": True})


@autoposter_bp.route("/api/notifications/<int:notif_id>/read", methods=["POST"])
@require_autoposter_login
def api_notification_mark_read(notif_id):
    n = AutoposterNotification.query.get(notif_id)
    if not n:
        return jsonify({"error": "الإشعار غير موجود"}), 404
    n.read = True
    db.session.commit()
    return jsonify({"success": True})


# --- API: التحليلات ---
@autoposter_bp.route("/api/analytics", methods=["GET"])
@require_autoposter_login
def api_analytics():
    # كل المنشورات المنشورة لهذه الشركة (يمكن تضييق الفترة لاحقاً)
    posts = AutoposterPost.query.filter_by(status="published").order_by(AutoposterPost.published_at.desc()).all()
    total = len(posts)
    by_type = {}
    by_page = {}
    for p in posts:
        pt = (getattr(p, "post_type", None) or "post").lower()
        by_type[pt] = by_type.get(pt, 0) + 1
        key = p.page_name or p.page_id or "صفحة غير معروفة"
        by_page[key] = by_page.get(key, 0) + 1

    top_posts = posts[:10]
    top_pages = sorted(by_page.items(), key=lambda kv: kv[1], reverse=True)[:5]

    return jsonify({
        "summary": {
            "total_published": total,
            "by_type": by_type,
            "by_page": [{"page_name": name, "count": count} for name, count in top_pages],
        },
        "top_posts": [
            {
                "content": (p.content or "")[:80],
                "published_at": p.published_at.isoformat() if p.published_at else None,
                "page_name": p.page_name,
                "post_type": (getattr(p, "post_type", None) or "post").lower(),
            }
            for p in top_posts
        ],
    })


# --- API: إعدادات فيسبوك (معرف التطبيق وسر التطبيق) ---
@autoposter_bp.route("/api/settings", methods=["GET"])
@require_autoposter_login
def api_settings_get():
    try:
        from models.system_settings import SystemSettings
        s = SystemSettings.get_settings()
        app_id = (getattr(s, "facebook_app_id", None) or "").strip()
        app_secret = (getattr(s, "facebook_app_secret", None) or "").strip()

        # AI settings (OpenAI / Gemini) are stored inside ui_flags JSON لتجنّب الحاجة لهجرة قاعدة البيانات.
        flags = s.get_ui_flags()
        openai_key = (flags.get("openai_api_key") or "").strip()
        openai_model = (flags.get("openai_model") or "").strip()
        openai_image_model = (flags.get("openai_image_model") or "").strip()
        gemini_key = (flags.get("gemini_api_key") or "").strip()
        gemini_model = (flags.get("gemini_model") or "").strip()

        return jsonify({
            "facebook_app_id": app_id,
            "facebook_app_secret": "••••••••" if app_secret else "",
            "facebook_app_secret_set": bool(app_secret),
            "openai_api_key": "••••••••" if openai_key else "",
            "openai_api_key_set": bool(openai_key),
            "openai_model": openai_model,
            "openai_image_model": openai_image_model,
            "gemini_api_key": "••••••••" if gemini_key else "",
            "gemini_api_key_set": bool(gemini_key),
            "gemini_model": gemini_model,
        })
    except Exception:
        return jsonify({
            "facebook_app_id": "",
            "facebook_app_secret": "",
            "facebook_app_secret_set": False,
            "openai_api_key": "",
            "openai_api_key_set": False,
            "openai_model": "",
            "openai_image_model": "",
            "gemini_api_key": "",
            "gemini_api_key_set": False,
            "gemini_model": "",
        })


@autoposter_bp.route("/api/settings", methods=["POST"])
@require_autoposter_login
def api_settings_post():
    data = request.get_json() or {}
    app_id = (data.get("facebook_app_id") or "").strip()
    app_secret = (data.get("facebook_app_secret") or "").strip()
    openai_key = (data.get("openai_api_key") or "").strip()
    openai_model = (data.get("openai_model") or "").strip()
    openai_image_model = (data.get("openai_image_model") or "").strip()
    gemini_key = (data.get("gemini_api_key") or "").strip()
    gemini_model = (data.get("gemini_model") or "").strip()
    try:
        from models.system_settings import SystemSettings
        s = SystemSettings.get_settings()
        s.facebook_app_id = app_id if app_id else None
        # إذا أرسل سراً جديداً (غير ••••) حدّثه، وإلا احتفظ بالقديم
        if app_secret and app_secret != "••••••••":
            s.facebook_app_secret = app_secret

        # تحديث إعدادات OpenAI / Gemini في ui_flags
        flags = s.get_ui_flags()
        if openai_key:
            # لا نحدّث القيمة إذا أرسل المستخدم placeholder
            if openai_key != "••••••••":
                flags["openai_api_key"] = openai_key
        # إن لم يُرسل المفتاح وسبق تخزين واحد نتركه كما هو
        if openai_model:
            flags["openai_model"] = openai_model
        if openai_image_model:
            flags["openai_image_model"] = openai_image_model
        if gemini_key:
            if gemini_key != "••••••••":
                flags["gemini_api_key"] = gemini_key
        if gemini_model:
            flags["gemini_model"] = gemini_model
        s.set_ui_flags(flags)

        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# --- تسجيل الخروج (من واجهة النشر التلقائي يعيد لصفحة المنصة) ---
@autoposter_bp.route("/api/logout", methods=["POST"])
@require_autoposter_login
def api_logout():
    session.pop("user_id", None)
    session.pop("tenant_slug", None)
    session.pop("role", None)
    return jsonify({"success": True})


# --- جدولة المنشورات (يستدعيها المخطط من app.py) ---
def run_scheduled_posts_for_all_tenants(app):
    """تغليف لاستدعاء خدمة الجدولة من ملف الخدمات (للتوافق مع app.py)."""
    service_run_scheduled_for_all_tenants(app)


# --- Webhooks: WhatsApp / Telegram (تشغيل الوكلاء من الرسائل الواردة) ---
@autoposter_bp.route("/api/webhooks/whatsapp", methods=["POST"])
def whatsapp_webhook():
    """Webhook مبسّط لرسائل واتساب: يتوقع workflow_id في كويري سترنج ويشغّل الوكيل."""
    data = request.get_json() or {}
    workflow_id = request.args.get("workflow_id", type=int)
    if not workflow_id:
        return jsonify({"success": False, "error": "workflow_id مطلوب في مسار الاستدعاء"}), 400

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
        return jsonify({"success": False, "error": "workflow_id مطلوب في مسار الاستدعاء"}), 400

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
