"""
posts_api.py
------------
API endpoints for creating / scheduling / listing publisher posts.
"""

from datetime import datetime
import traceback

from flask import Blueprint, request, session, g, current_app
from sqlalchemy import func

from extensions import db
from modules.publisher.api.response_utils import error_response, ok_response
from modules.publisher.api.validation_utils import parse_pagination, parse_publish_time_utc
from modules.publisher.models.publisher_media import PublisherMedia
from modules.publisher.models.publisher_page import PublisherPage
from modules.publisher.models.publisher_post import PublisherPost
from modules.publisher.services.schema_guard import ensure_publisher_schema
from modules.publisher.services.scheduler_service import publish_single_post_now

posts_api_bp = Blueprint("publisher_posts_api", __name__)


def _tenant():
    return getattr(g, "tenant", None) or session.get("tenant_slug")


def _normalize_list(value):
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _normalize_page_ids(raw):
    values = []
    for item in _normalize_list(raw):
        text = str(item).strip()
        if text and text not in values:
            values.append(text)
    return values


def _normalize_media_ids(raw):
    values = []
    for item in _normalize_list(raw):
        try:
            media_id = int(item)
            if media_id not in values:
                values.append(media_id)
        except Exception:
            continue
    return values


def _validate_post_payload(payload, tenant, *, require_publish_time=False):
    fields = {}

    raw_text = payload.get("text")
    if raw_text is None:
        text = ""
    elif isinstance(raw_text, str):
        text = raw_text
    else:
        text = str(raw_text)
    text_for_validation = text.strip()
    if not text_for_validation:
        text = ""
    page_ids = _normalize_page_ids(payload.get("page_ids"))
    media_ids = _normalize_media_ids(payload.get("media_ids"))

    if not text_for_validation and not media_ids:
        fields["text"] = "يجب كتابة نص أو اختيار وسيط"
    if not page_ids:
        fields["page_ids"] = "يجب اختيار صفحة واحدة على الأقل"

    if page_ids:
        existing_pages = PublisherPage.query.filter_by(tenant_slug=tenant).filter(
            PublisherPage.page_id.in_(page_ids)
        ).all()
        existing_page_ids = {str(row.page_id) for row in existing_pages}
        missing_pages = [page_id for page_id in page_ids if page_id not in existing_page_ids]
        if missing_pages:
            fields["page_ids"] = f"صفحات غير مرتبطة أو غير صالحة: {', '.join(missing_pages)}"

    if media_ids:
        existing_media = PublisherMedia.query.filter_by(tenant_slug=tenant).filter(
            PublisherMedia.id.in_(media_ids)
        ).all()
        existing_media_ids = {int(row.id) for row in existing_media}
        missing_media = [str(media_id) for media_id in media_ids if media_id not in existing_media_ids]
        if missing_media:
            fields["media_ids"] = f"وسائط غير موجودة أو لا تخص هذا الحساب: {', '.join(missing_media)}"

    publish_time_utc = None
    if require_publish_time:
        publish_time_utc, parse_error = parse_publish_time_utc(payload)
        if parse_error:
            fields["publish_time"] = parse_error
        elif publish_time_utc and publish_time_utc <= datetime.utcnow():
            fields["publish_time"] = "يجب أن يكون وقت النشر في المستقبل"

    if fields:
        return None, None, None, None, fields
    return text, page_ids, media_ids, publish_time_utc, None


@posts_api_bp.route("/api/posts", methods=["GET"])
def list_posts():
    try:
        ensure_publisher_schema()
        tenant = _tenant()

        status_param = (request.args.get("status") or "").strip()
        statuses = [part.strip() for part in status_param.split(",") if part.strip()]
        search_query = (request.args.get("q") or "").strip()

        sort_by = (request.args.get("sort_by") or "created_at").strip()
        if sort_by not in {"created_at", "publish_time", "status"}:
            sort_by = "created_at"
        order = (request.args.get("order") or "desc").strip().lower()
        if order not in {"asc", "desc"}:
            order = "desc"

        page, per_page = parse_pagination(default_per_page=20, max_per_page=200)

        query = PublisherPost.query.filter_by(tenant_slug=tenant)
        if statuses:
            query = query.filter(PublisherPost.status.in_(statuses))
        if search_query:
            query = query.filter(PublisherPost.text.ilike(f"%{search_query}%"))

        sort_col = getattr(PublisherPost, sort_by)
        query = query.order_by(sort_col.asc() if order == "asc" else sort_col.desc())

        total = query.count()
        offset = (page - 1) * per_page
        posts = query.offset(offset).limit(per_page).all()

        status_rows = (
            db.session.query(PublisherPost.status, func.count(PublisherPost.id))
            .filter(PublisherPost.tenant_slug == tenant)
            .group_by(PublisherPost.status)
            .all()
        )
        by_status = {row[0]: int(row[1]) for row in status_rows}

        items = [post.to_dict() for post in posts]
        meta = {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": max(1, (total + per_page - 1) // per_page),
            "by_status": by_status,
        }
        return ok_response(
            data={"items": items},
            meta=meta,
            legacy={"posts": items},
        )
    except Exception as exc:
        current_app.logger.error(traceback.format_exc())
        return error_response(
            code="posts_list_failed",
            message=str(exc),
            status_code=500,
        )


@posts_api_bp.route("/api/posts/create", methods=["POST"])
def create_post():
    """
    Create a post for immediate publishing.
    """
    try:
        ensure_publisher_schema()
        data = request.get_json() or {}
        tenant = _tenant()

        text, page_ids, media_ids, _, fields = _validate_post_payload(data, tenant)
        if fields:
            return error_response(
                code="validation_error",
                message="بيانات المنشور غير صالحة",
                fields=fields,
                status_code=422,
            )

        post = PublisherPost(
            tenant_slug=tenant,
            text=text,
            status="queued",
            publish_type="now",
        )
        post.page_ids = page_ids
        post.media_ids = media_ids
        db.session.add(post)
        db.session.commit()

        # Immediate publish attempt (scheduler still handles fallback cases).
        publish_result = publish_single_post_now(
            current_app._get_current_object(),
            post.id,
            tenant_slug=post.tenant_slug or tenant,
        )
        db.session.refresh(post)
        post_data = post.to_dict()

        if post.status == "published":
            return ok_response(
                data=post_data,
                message="تم النشر الفوري بنجاح",
                legacy={"post": post_data},
            )
        if post.status == "partial":
            return ok_response(
                data=post_data,
                message="تم النشر جزئياً على بعض الصفحات. راجع الحالة.",
                legacy={"post": post_data},
            )
        if post.status == "failed":
            return error_response(
                code="publish_failed",
                message=post.error_message or "فشل النشر الفوري. راجع إعدادات الصفحة/التوكن.",
                status_code=400,
                legacy={"post": post_data},
            )

        if publish_result.get("success"):
            return ok_response(
                data=post_data,
                message="تمت إضافة المنشور ومعالجته",
                legacy={"post": post_data},
            )

        publish_errors = publish_result.get("errors") or []
        details = " | ".join([str(error) for error in publish_errors if error])[:450]
        return error_response(
            code="publish_pending",
            message=(
                "لم يكتمل النشر الفوري. تم وضع المنشور في الانتظار وسيُعاد نشره عبر المجدول."
                + (f" السبب: {details}" if details else "")
            ),
            status_code=202,
            legacy={"post": post_data, "status": post.status},
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(traceback.format_exc())
        return error_response(
            code="post_create_failed",
            message=str(exc),
            status_code=500,
        )


@posts_api_bp.route("/api/posts/schedule", methods=["POST"])
def schedule_post():
    """
    Save a post for future publishing.
    """
    try:
        ensure_publisher_schema()
        data = request.get_json() or {}
        tenant = _tenant()

        text, page_ids, media_ids, publish_time_utc, fields = _validate_post_payload(
            data, tenant, require_publish_time=True
        )
        if fields:
            return error_response(
                code="validation_error",
                message="بيانات الجدولة غير صالحة",
                fields=fields,
                status_code=422,
            )

        post = PublisherPost(
            tenant_slug=tenant,
            text=text,
            status="scheduled",
            publish_type="scheduled",
            publish_time=publish_time_utc,
        )
        post.page_ids = page_ids
        post.media_ids = media_ids
        db.session.add(post)
        db.session.commit()

        post_data = post.to_dict()
        return ok_response(
            data=post_data,
            message=f"تمت جدولة المنشور بنجاح في {publish_time_utc.strftime('%Y-%m-%d %H:%M UTC')}",
            legacy={"post": post_data},
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(traceback.format_exc())
        return error_response(
            code="post_schedule_failed",
            message=str(exc),
            status_code=500,
        )
