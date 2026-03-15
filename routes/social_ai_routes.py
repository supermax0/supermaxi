from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request, session, g, send_from_directory, current_app, redirect

from extensions import db
from models.social_account import SocialAccount
from models.social_post import SocialPost
from services.facebook_service import fetch_comments as fb_fetch_comments
from services.instagram_service import fetch_comments as ig_fetch_comments
from services.tiktok_service import fetch_comments as tiktok_fetch_comments
from social_ai.content_generator import create_ai_post


social_ai_bp = Blueprint(
    "social_ai",
    __name__,
    url_prefix="/social-ai",
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
    """Serve built assets for /social-ai/ page."""
    if not session.get("user_id"):
        return ("", 401)

    assets_dir = _ai_agent_dist_dir() / "assets"
    return send_from_directory(str(assets_dir), filename)


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

