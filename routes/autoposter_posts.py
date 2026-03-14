# إنشاء المنشورات والجدولة — Autoposter Create Post
# Routes: /autoposter/create, /autoposter/api/posts (create/schedule)
from datetime import datetime
from flask import Blueprint, jsonify, render_template, request, session
from extensions import db
from models.autoposter_facebook_page import AutoposterFacebookPage
from models.autoposter_media import AutoposterMedia
from models.autoposter_post import AutoposterPost
from services.autoposter_service import publish_now_for_pages, schedule_posts_for_pages

autoposter_posts_bp = Blueprint("autoposter_posts", __name__, url_prefix="/autoposter")

POST_TYPES = ("post", "video", "reel", "story")


def _require_login(f):
    from functools import wraps
    @wraps(f)
    def inner(*args, **kwargs):
        if not session.get("user_id"):
            from flask import redirect, url_for
            return redirect(url_for("index.login") + "?next=" + request.path)
        return f(*args, **kwargs)
    return inner


def _resolve_media_urls(media_id, request_root):
    """من media_id نرجع image_url و video_url و media_type للاستخدام في النشر."""
    if not media_id:
        return None, None, None
    rec = AutoposterMedia.query.get(media_id)
    if not rec:
        return None, None, None
    url = rec.public_url or ""
    if url.startswith("/") and request_root:
        url = (request_root or "").rstrip("/") + url
    if rec.media_type == "image":
        return url, None, "image"
    if rec.media_type == "video":
        return None, url, "video"
    return None, None, None


@autoposter_posts_bp.route("/create")
@_require_login
def create_post_page():
    """صفحة إنشاء منشور: نص، اختيار وسائط من المكتبة، صفحات، جدولة."""
    return render_template("autoposter/create_post.html")


@autoposter_posts_bp.route("/api/pages", methods=["GET"])
def api_pages_list():
    """قائمة صفحات فيسبوك المتصلة (لاختيار الصفحات عند النشر)."""
    if not session.get("user_id"):
        return jsonify({"error": "unauthorized"}), 401
    tenant_slug = session.get("tenant_slug")
    q = AutoposterFacebookPage.query.filter(AutoposterFacebookPage.access_token.isnot(None))
    if tenant_slug and hasattr(AutoposterFacebookPage, "tenant_slug"):
        q = q.filter_by(tenant_slug=tenant_slug)
    pages = q.all()
    return jsonify({
        "pages": [
            {"id": p.page_id, "name": p.name or p.page_id, "access_token": "***"}
            for p in pages
        ]
    })


@autoposter_posts_bp.route("/api/posts/create", methods=["POST"])
def api_posts_create():
    """
    إنشاء منشور (فوري أو مجدول).
    JSON أو form: caption (نص)، media_id (اختياري)، page_ids[]، post_type، scheduled_at (اختياري).
    """
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or request.form
    if not data and request.form:
        data = request.form
    caption = (data.get("caption") or data.get("content") or data.get("text") or "").strip()
    media_id = data.get("media_id")
    if media_id is not None:
        try:
            media_id = int(media_id)
        except (TypeError, ValueError):
            media_id = None
    page_ids = data.get("page_ids") or data.get("page_ids[]") or []
    if isinstance(page_ids, str):
        page_ids = [page_ids] if page_ids else []
    post_type = (data.get("post_type") or "post").strip().lower()
    if post_type not in POST_TYPES:
        post_type = "post"
    scheduled_at = None
    if data.get("scheduled_at"):
        try:
            scheduled_at = datetime.fromisoformat(data.get("scheduled_at").replace("Z", "+00:00"))
        except Exception:
            pass
    if not page_ids:
        return jsonify({"success": False, "error": "اختر صفحة واحدة على الأقل"}), 400
    if not caption and not media_id:
        return jsonify({"success": False, "error": "أدخل نصاً أو اختر وسيطاً من المكتبة"}), 400
    request_root = request.url_root
    image_url, video_url, _ = _resolve_media_urls(media_id, request_root)
    content = caption or ""
    tenant_slug = session.get("tenant_slug")
    q = AutoposterFacebookPage.query.filter(
        AutoposterFacebookPage.page_id.in_(page_ids),
        AutoposterFacebookPage.access_token.isnot(None),
    )
    if tenant_slug and hasattr(AutoposterFacebookPage, "tenant_slug"):
        q = q.filter_by(tenant_slug=tenant_slug)
    pages = list(q.all())
    if not pages:
        return jsonify({"success": False, "error": "لم تُعثر على صفحات متصلة"}), 400
    if scheduled_at:
        count = schedule_posts_for_pages(
            pages=pages,
            content=content,
            image_url=image_url,
            video_url=video_url,
            post_type=post_type,
            scheduled_at=scheduled_at,
            media_id=media_id,
            caption=caption or None,
        )
        return jsonify({"success": True, "scheduled": True, "count": count})
    published, errors = publish_now_for_pages(
        pages=pages,
        content=content,
        image_url=image_url,
        video_url=video_url,
        post_type=post_type,
        media_id=media_id,
        caption=caption or None,
    )
    if errors and not published:
        return jsonify({"success": False, "error": errors[0].get("error", "فشل النشر")}), 500
    return jsonify({"success": True, "published": published, "errors": errors})
