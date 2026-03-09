from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, render_template, request, session, g

from extensions import db
from models.social_account import SocialAccount
from models.social_post import SocialPost
from social_ai.content_generator import create_ai_post


social_ai_bp = Blueprint(
    "social_ai",
    __name__,
    url_prefix="/social-ai",
)


def _current_tenant_slug():
    return getattr(g, "tenant", None)


@social_ai_bp.route("/")
def dashboard():
    """لوحة بسيطة لإدارة منشورات AI (مبدئية)."""
    if not session.get("user_id"):
        # يمكن لاحقاً إعادة التوجيه لواجهة تسجيل الدخول الخاصة بك
        return render_template("401.html"), 401 if False else render_template("autoposter/dashboard.html")
    return render_template("social_ai/dashboard.html")


@social_ai_bp.route("/api/accounts", methods=["GET"])
def api_accounts_list():
    tenant_slug = _current_tenant_slug()
    q = SocialAccount.query
    if tenant_slug:
        q = q.filter_by(tenant_slug=tenant_slug)
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

