"""
posts_api.py
------------
API endpoints for creating / scheduling / listing publisher posts.

IMPORTANT: Routes NEVER publish directly.
They write PublisherPost to DB → scheduler worker handles actual FB publishing.
"""

from datetime import datetime
import traceback

from flask import Blueprint, jsonify, request, session, g, current_app

from extensions import db
from modules.publisher.models.publisher_post import PublisherPost
from modules.publisher.services.schema_guard import ensure_publisher_schema

posts_api_bp = Blueprint("publisher_posts_api", __name__)


def _tenant():
    return getattr(g, "tenant", None) or session.get("tenant_slug")


@posts_api_bp.route("/api/posts", methods=["GET"])
def list_posts():
    try:
        ensure_publisher_schema()
        tenant = _tenant()
        status = request.args.get("status")
        q = PublisherPost.query.filter_by(tenant_slug=tenant)
        if status:
            q = q.filter_by(status=status)
        posts = q.order_by(PublisherPost.created_at.desc()).limit(100).all()
        return jsonify({"success": True, "posts": [p.to_dict() for p in posts]})
    except Exception as e:
        current_app.logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": str(e)}), 500


@posts_api_bp.route("/api/posts/create", methods=["POST"])
def create_post():
    """
    Create a post for immediate publishing (queued → scheduler handles it).
    Body:
      text: str
      page_ids: [str, ...]
      media_ids: [int, ...]   (optional)
    """
    try:
        ensure_publisher_schema()
        data = request.get_json() or {}
        text = (data.get("text") or "").strip()
        page_ids = data.get("page_ids") or []
        media_ids = data.get("media_ids") or []

        if not text and not media_ids:
            return jsonify({"success": False, "message": "يجب كتابة نص أو اختيار وسيط"}), 400
        if not page_ids:
            return jsonify({"success": False, "message": "يجب اختيار صفحة واحدة على الأقل"}), 400

        post = PublisherPost(
            tenant_slug=_tenant(),
            text=text,
            status="queued",
            publish_type="now",
        )
        post.page_ids = page_ids
        post.media_ids = media_ids
        db.session.add(post)
        db.session.commit()

        return jsonify({"success": True, "post": post.to_dict(),
                        "message": "تم إضافة المنشور إلى قائمة الانتظار — سيُنشر خلال دقيقة"})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": str(e)}), 500


@posts_api_bp.route("/api/posts/schedule", methods=["POST"])
def schedule_post():
    """
    Save a post for future publishing.
    Body:
      text: str
      page_ids: [str, ...]
      media_ids: [int, ...]
      publish_time: ISO-8601 string (e.g. "2024-06-01T15:30:00")
    """
    try:
        ensure_publisher_schema()
        data = request.get_json() or {}
        text = (data.get("text") or "").strip()
        page_ids = data.get("page_ids") or []
        media_ids = data.get("media_ids") or []
        publish_time_str = (data.get("publish_time") or "").strip()

        if not text and not media_ids:
            return jsonify({"success": False, "message": "يجب كتابة نص أو اختيار وسيط"}), 400
        if not page_ids:
            return jsonify({"success": False, "message": "يجب اختيار صفحة واحدة على الأقل"}), 400
        if not publish_time_str:
            return jsonify({"success": False, "message": "وقت النشر مطلوب"}), 400

        try:
            publish_time = datetime.fromisoformat(publish_time_str.replace("Z", "+00:00"))
            # Strip tz info for naive datetime storage
            publish_time = publish_time.replace(tzinfo=None)
        except Exception:
            return jsonify({"success": False, "message": "صيغة وقت النشر غير صحيحة"}), 400

        if publish_time <= datetime.utcnow():
            return jsonify({"success": False, "message": "يجب أن يكون وقت النشر في المستقبل"}), 400

        post = PublisherPost(
            tenant_slug=_tenant(),
            text=text,
            status="scheduled",
            publish_type="scheduled",
            publish_time=publish_time,
        )
        post.page_ids = page_ids
        post.media_ids = media_ids
        db.session.add(post)
        db.session.commit()

        return jsonify({"success": True, "post": post.to_dict(),
                        "message": f"تمت جدولة المنشور بنجاح في {publish_time.strftime('%Y-%m-%d %H:%M')}"})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(traceback.format_exc())
        return jsonify({"success": False, "message": str(e)}), 500
