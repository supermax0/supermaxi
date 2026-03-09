# Blueprint النشر التلقائي لفيسبوك — يُربط تحت /autoposter
from datetime import datetime
from functools import wraps
from flask import Blueprint, request, session, redirect, url_for, jsonify, render_template, g

from extensions import db
from models.autoposter_facebook_page import AutoposterFacebookPage
from models.autoposter_post import AutoposterPost
from models.autoposter_notification import AutoposterNotification
from routes.autoposter_facebook import (
    get_oauth_url,
    exchange_code_for_user_token,
    get_long_lived_token,
    get_pages_with_tokens,
    publish_post,
)

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
        for model in (AutoposterFacebookPage, AutoposterPost, AutoposterNotification):
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
    return render_template("autoposter/dashboard.html")


@autoposter_bp.route("/pages")
@require_autoposter_login
def pages_view():
    return redirect(url_for("autoposter.dashboard") + "#pages")


@autoposter_bp.route("/create")
@require_autoposter_login
def create_view():
    return redirect(url_for("autoposter.dashboard") + "#create")


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
            existing = AutoposterFacebookPage.query.filter_by(page_id=p["id"]).first()
            if existing:
                existing.name = p.get("name", existing.name)
                existing.access_token = p.get("access_token", existing.access_token)
            else:
                fp = AutoposterFacebookPage(
                    page_id=p["id"],
                    name=p.get("name", "صفحة"),
                    access_token=p.get("access_token", ""),
                )
                db.session.add(fp)
        db.session.commit()
        _add_notification("تم ربط الصفحات", "تم ربط صفحات فيسبوك بنجاح.")
    except Exception as e:
        db.session.rollback()
        return redirect(url_for("autoposter.dashboard") + "?facebook=error&msg=" + str(e))
    return redirect(url_for("autoposter.dashboard") + "#pages")


# --- API: رفع صورة أو فيديو ---
UPLOAD_ALLOWED = ("image/jpeg", "image/png", "image/gif", "image/webp", "video/mp4", "video/quicktime")
UPLOAD_MAX_MB = 100

@autoposter_bp.route("/api/upload", methods=["POST"])
@require_autoposter_login
def api_upload():
    if "file" not in request.files and "media" not in request.files:
        return jsonify({"error": "لم يُرفع ملف"}), 400
    file = request.files.get("file") or request.files.get("media")
    if not file or not file.filename:
        return jsonify({"error": "لم يُرفع ملف"}), 400
    ct = (file.content_type or "").split(";")[0].strip().lower()
    if ct not in UPLOAD_ALLOWED:
        return jsonify({"error": "نوع الملف غير مدعوم. استخدم صورة (jpg, png, gif, webp) أو فيديو (mp4)."}), 400
    import uuid
    import os
    from flask import current_app
    ext = os.path.splitext(file.filename)[1] or (".mp4" if "video" in ct else ".jpg")
    if ext.lower() not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov"):
        ext = ".jpg" if "image" in ct else ".mp4"
    name = f"{uuid.uuid4().hex}{ext}"
    upload_dir = os.path.join(current_app.root_path, "static", "autoposter", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, name)
    try:
        file.save(path)
        size_mb = os.path.getsize(path) / (1024 * 1024)
        if size_mb > UPLOAD_MAX_MB:
            os.remove(path)
            return jsonify({"error": f"حجم الملف أكبر من {UPLOAD_MAX_MB} ميجا"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    url = f"{request.script_root or ''}/static/autoposter/uploads/{name}"
    if request.url_root:
        from urllib.parse import urljoin
        url = urljoin(request.url_root, url.lstrip("/"))
    return jsonify({"url": url, "type": "video" if "video" in ct else "image"})


# --- API: نشر فوري أو مجدول (يدعم صورة/فيديو) ---
@autoposter_bp.route("/api/posts", methods=["POST"])
@require_autoposter_login
def api_posts_create():
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

    if scheduled_at:
        try:
            at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        except Exception:
            return jsonify({"error": "صيغة التاريخ غير صحيحة"}), 400
        for page in pages:
            post = AutoposterPost(
                page_id=page.page_id,
                page_name=page.name,
                content=content,
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

    published = []
    errors = []
    for page in pages:
        post = AutoposterPost(
            page_id=page.page_id,
            page_name=page.name,
            content=content,
            image_url=image_url,
            video_url=video_url,
            post_type=post_type,
            status="publishing",
        )
        db.session.add(post)
        db.session.commit()
        try:
            result = publish_post(
                page.access_token,
                content,
                photo_url=image_url,
                video_url=video_url,
                post_type=post_type,
                page_id=page.page_id,
            )
            post.status = "published"
            post.published_at = datetime.utcnow()
            post.facebook_post_id = result.get("id") or result.get("post_id")
            db.session.commit()
            published.append(post.page_name)
        except Exception as e:
            post.status = "failed"
            post.error_message = str(e)
            db.session.commit()
            errors.append(f"{page.name}: {e}")

    if errors and not published:
        return jsonify({"error": "; ".join(errors)}), 500
    _add_notification("تم نشر المنشور", f"نُشر على: {', '.join(published)}")
    return jsonify({"success": True, "published": published, "errors": errors if errors else None})


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


# --- API: الإشعارات ---
@autoposter_bp.route("/api/notifications", methods=["GET"])
@require_autoposter_login
def api_notifications():
    items = AutoposterNotification.query.order_by(AutoposterNotification.created_at.desc()).limit(50).all()
    return jsonify({"notifications": [n.to_dict() for n in items]})


@autoposter_bp.route("/api/notifications/read", methods=["POST"])
@require_autoposter_login
def api_notifications_read():
    for n in AutoposterNotification.query.all():
        n.read = True
    db.session.commit()
    return jsonify({"success": True})


# --- API: التحليلات ---
@autoposter_bp.route("/api/analytics", methods=["GET"])
@require_autoposter_login
def api_analytics():
    posts = AutoposterPost.query.filter_by(status="published").order_by(AutoposterPost.published_at.desc()).limit(10).all()
    return jsonify({
        "engagement": [],
        "growth": [],
        "top_posts": [
            {"content": (p.content or "")[:50], "published_at": p.published_at.isoformat() if p.published_at else None}
            for p in posts
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
        return jsonify({
            "facebook_app_id": app_id,
            "facebook_app_secret": "••••••••" if app_secret else "",
            "facebook_app_secret_set": bool(app_secret),
        })
    except Exception:
        return jsonify({"facebook_app_id": "", "facebook_app_secret": "", "facebook_app_secret_set": False})


@autoposter_bp.route("/api/settings", methods=["POST"])
@require_autoposter_login
def api_settings_post():
    data = request.get_json() or {}
    app_id = (data.get("facebook_app_id") or "").strip()
    app_secret = (data.get("facebook_app_secret") or "").strip()
    try:
        from models.system_settings import SystemSettings
        s = SystemSettings.get_settings()
        s.facebook_app_id = app_id if app_id else None
        # إذا أرسل سراً جديداً (غير ••••) حدّثه، وإلا احتفظ بالقديم
        if app_secret and app_secret != "••••••••":
            s.facebook_app_secret = app_secret
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
    """تشغيل المنشورات المجدولة لكل الشركات النشطة."""
    with app.app_context():
        from flask import g
        from models.core.tenant import Tenant as CoreTenant
        from datetime import datetime

        g.tenant = None
        try:
            tenants = CoreTenant.query.filter_by(is_active=True).all()
        except Exception:
            tenants = []
        for t in tenants:
            slug = getattr(t, "slug", None)
            if not slug:
                continue
            g.tenant = slug
            try:
                now = datetime.utcnow()
                posts = AutoposterPost.query.filter(
                    AutoposterPost.status == "scheduled",
                    AutoposterPost.scheduled_at <= now,
                ).all()
                for post in posts:
                    post.status = "publishing"
                    db.session.commit()
                    try:
                        page = AutoposterFacebookPage.query.filter_by(page_id=post.page_id).first()
                        if not page or not page.access_token:
                            post.status = "failed"
                            post.error_message = "صفحة غير متصلة أو انتهى التوكن"
                            db.session.commit()
                            continue
                        result = publish_post(
                            page.access_token,
                            post.content,
                            photo_url=getattr(post, "image_url", None),
                            video_url=getattr(post, "video_url", None),
                            post_type=getattr(post, "post_type", None) or "post",
                            page_id=page.page_id,
                        )
                        post.status = "published"
                        post.published_at = datetime.utcnow()
                        post.facebook_post_id = result.get("id") or result.get("post_id")
                        post.error_message = None
                        db.session.commit()
                    except Exception as e:
                        post.status = "failed"
                        post.error_message = str(e)
                        db.session.commit()
            except Exception:
                db.session.rollback()
            finally:
                g.tenant = None
