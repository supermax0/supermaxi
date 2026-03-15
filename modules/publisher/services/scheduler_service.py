"""
scheduler_service.py
--------------------
Background APScheduler worker for scheduled posts.

Gunicorn-safe: uses a file lock so only ONE worker runs the scheduler
even under multi-process gunicorn deployments.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from modules.publisher.services.schema_guard import ensure_publisher_schema

try:
    import fcntl  # type: ignore
except Exception:  # pragma: no cover - Windows fallback
    fcntl = None

_scheduler = None
_lock_fd = None

LOCK_FILE = os.path.join(tempfile.gettempdir(), "publisher_scheduler.lock")
LOG_FILE = "logs/publisher.log"
INTER_PAGE_PUBLISH_DELAY_SECONDS = 5


def _resolve_media_file_path(app, media_obj):
    """Build a local absolute path for PublisherMedia regardless of stored url_path format."""
    media_root = app.config.get("PUBLISHER_MEDIA_ROOT") or os.path.join(app.root_path, "media")
    tenant_dir = media_obj.tenant_slug or "default"
    sub = "images" if media_obj.media_type == "image" else "videos"
    return os.path.join(media_root, tenant_dir, sub, media_obj.filename)


def _is_token_expired_result(result: dict) -> bool:
    if not isinstance(result, dict):
        return False
    code = result.get("error_code")
    msg = str(result.get("message") or "").lower()
    if code == 190:
        return True
    return ("error validating access token" in msg) or ("session has expired" in msg) or ("invalid oauth access token" in msg)


def _refresh_page_token_for_page(
    *,
    tenant_slug,
    page_id,
    page,
    db,
    fb,
    decrypt_token,
    encrypt_token,
    PublisherSettings,
    logger,
):
    """
    Try refreshing page token using stored user token in PublisherSettings.
    Returns (new_page_token | None, error_message | None).
    """
    try:
        tenant_key = tenant_slug or "default"
        settings = PublisherSettings.get(tenant_key)
        if not settings or not settings.fb_user_token:
            return None, "لا يوجد User Token محفوظ للتجديد التلقائي."

        try:
            user_token = decrypt_token(settings.fb_user_token)
        except Exception:
            user_token = settings.fb_user_token

        pages_result = fb.get_user_pages(user_token)
        if not pages_result.get("success"):
            return None, f"فشل تحديث Page Token: {pages_result.get('message')}"

        pages = pages_result.get("pages") or []
        matched = next((p for p in pages if str(p.get("id") or "") == str(page_id)), None)
        if not matched:
            return None, "لم يتم العثور على الصفحة ضمن الصفحات المرتبطة بعد تحديث التوكن."

        new_token = (matched.get("access_token") or "").strip()
        if not new_token:
            return None, "لم يرجع فيسبوك Page Token صالح بعد التحديث."

        page.page_token = encrypt_token(new_token)
        page.page_name = matched.get("name") or page.page_name
        db.session.commit()
        return new_token, None
    except Exception as exc:
        db.session.rollback()
        logger.exception("Auto token refresh failed for page %s: %s", page_id, exc)
        return None, str(exc)


def _publish_single_post_record(*, app, db, post, PublisherPage, PublisherMedia, fb, decrypt_token, logger):
    """Publish one PublisherPost now and persist final status."""
    try:
        ensure_publisher_schema()
        post.status = "publishing"
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("Failed to switch post %s to publishing: %s", getattr(post, "id", "?"), exc)
        return {
            "success": False,
            "status": "queued",
            "errors": [f"db_prepare_error: {exc}"],
            "facebook_post_ids": {},
        }

    fb_post_ids = {}
    errors = []

    from modules.publisher.models.publisher_settings import PublisherSettings
    from modules.publisher.services.token_utils import encrypt_token

    def _publish_with_token(page_id, token, text, media_list):
        if not media_list:
            return fb.publish_text_post(page_id, token, text)
        m = media_list[0]
        file_path = _resolve_media_file_path(app, m)
        if m.media_type == "image":
            return fb.publish_photo_post(page_id, token, text, file_path)
        return fb.publish_video_post(page_id, token, text, file_path)

    page_ids = post.page_ids or []
    total_pages = len(page_ids)
    base_text = post.text or ""
    use_ai_variants = bool(base_text.strip()) and total_pages > 1
    ai_variation_available = True

    for index, page_id in enumerate(page_ids):
        try:
            page = PublisherPage.query.filter_by(
                tenant_slug=post.tenant_slug, page_id=page_id
            ).first()
            if not page:
                errors.append(f"page {page_id} not found")
                continue

            try:
                token = decrypt_token(page.page_token)
            except Exception as exc:
                errors.append(f"token decrypt error for {page_id}: {exc}")
                continue

            media_list = []
            if post.media_ids:
                media_list = PublisherMedia.query.filter(
                    PublisherMedia.id.in_(post.media_ids)
                ).filter(
                    PublisherMedia.tenant_slug == post.tenant_slug
                ).all()

            text = base_text
            if use_ai_variants and index > 0 and ai_variation_available:
                try:
                    from modules.publisher.services import ai_service

                    text = ai_service.create_page_caption_variant(
                        base_text,
                        page_name=page.page_name or page_id,
                        variant_index=index + 1,
                        total_variants=total_pages,
                    )
                    logger.info(
                        "Generated AI caption variant for post %s page %s",
                        post.id,
                        page_id,
                    )
                except Exception as exc:
                    # Fallback to original caption if AI key/package is unavailable.
                    ai_variation_available = False
                    text = base_text
                    logger.warning(
                        "AI caption variation unavailable for post %s: %s. "
                        "Continuing with original caption.",
                        post.id,
                        exc,
                    )
            result = _publish_with_token(page_id, token, text, media_list)

            # Auto-refresh page token once on token-expired errors, then retry publish.
            if not result.get("success") and _is_token_expired_result(result):
                new_token, refresh_err = _refresh_page_token_for_page(
                    tenant_slug=post.tenant_slug,
                    page_id=page_id,
                    page=page,
                    db=db,
                    fb=fb,
                    decrypt_token=decrypt_token,
                    encrypt_token=encrypt_token,
                    PublisherSettings=PublisherSettings,
                    logger=logger,
                )
                if new_token:
                    result = _publish_with_token(page_id, new_token, text, media_list)
                else:
                    errors.append(f"{page_id}: انتهت صلاحية التوكن وتعذر تجديده تلقائياً. {refresh_err}")
                    logger.error("Token refresh failed for page %s: %s", page_id, refresh_err)
                    continue

            if result.get("success"):
                fb_post_ids[page_id] = (result.get("data") or {}).get("id", "")
                logger.info("Published post %d → page %s", post.id, page_id)
            else:
                errors.append(f"{page_id}: {result.get('message')}")
                logger.error("Failed post %d → page %s: %s", post.id, page_id, result.get("message"))
        finally:
            if index < total_pages - 1:
                logger.info(
                    "Waiting %ds before publishing next page for post %s",
                    INTER_PAGE_PUBLISH_DELAY_SECONDS,
                    post.id,
                )
                time.sleep(INTER_PAGE_PUBLISH_DELAY_SECONDS)

    post.facebook_post_ids = fb_post_ids
    if errors:
        post.status = "partial" if fb_post_ids else "failed"
        post.error_message = "; ".join(errors)
    else:
        post.status = "published"
        post.error_message = None
    try:
        ensure_publisher_schema()
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("Failed final commit for post %s: %s", getattr(post, "id", "?"), exc)
        # محاولة أخيرة لوضع الحالة failed حتى لا يبقى queued
        try:
            ensure_publisher_schema()
            post.status = "failed"
            post.error_message = f"db_finalize_error: {exc}"
            db.session.commit()
        except Exception:
            db.session.rollback()
        return {
            "success": False,
            "status": "failed",
            "errors": [f"db_finalize_error: {exc}"],
            "facebook_post_ids": fb_post_ids,
        }
    return {
        "success": post.status in ("published", "partial"),
        "status": post.status,
        "errors": errors,
        "facebook_post_ids": fb_post_ids,
    }


def setup_logger():
    """Configure the publisher rotating file logger."""
    os.makedirs("logs", exist_ok=True)
    logger = logging.getLogger("publisher")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    # Also log to stdout in dev
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    logger.addHandler(ch)
    return logger


def _acquire_lock() -> bool:
    """Try to acquire a non-blocking exclusive file lock. Returns True if acquired."""
    global _lock_fd
    try:
        _lock_fd = open(LOCK_FILE, "w")
        if fcntl is not None:
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        # Another worker already holds the lock
        if _lock_fd:
            _lock_fd.close()
            _lock_fd = None
        return False


def _publish_due_posts(app):
    """Job: find queued/scheduled posts whose time has come and publish them."""
    logger = logging.getLogger("publisher")
    try:
        with app.app_context():
            from flask import g
            from extensions import db
            from modules.publisher.models.publisher_post import PublisherPost
            from modules.publisher.models.publisher_page import PublisherPage
            from modules.publisher.models.publisher_media import PublisherMedia
            from modules.publisher.services import facebook_service as fb
            from modules.publisher.services.token_utils import decrypt_token
            from models.core.tenant import Tenant as CoreTenant

            now = datetime.now(timezone.utc).replace(tzinfo=None)

            tenant_slugs = []
            try:
                tenant_slugs = [t.slug for t in CoreTenant.query.filter_by(is_active=True).all() if t.slug]
            except Exception:
                logger.exception("Could not load tenant list for scheduler")

            # fallback for single-db/dev mode
            if not tenant_slugs:
                tenant_slugs = [None]

            total_due = 0

            for tenant_slug in tenant_slugs:
                g.tenant = tenant_slug
                ensure_publisher_schema()
                query = PublisherPost.query.filter(
                    PublisherPost.status.in_(["queued", "scheduled"]),
                )
                if tenant_slug:
                    query = query.filter_by(tenant_slug=tenant_slug)
                posts = query.all()

                due = [
                    p for p in posts
                    if p.publish_type == "now"
                    or (p.publish_time and p.publish_time <= now)
                ]

                if not due:
                    continue

                total_due += len(due)
                for post in due:
                    _publish_single_post_record(
                        app=app,
                        db=db,
                        post=post,
                        PublisherPage=PublisherPage,
                        PublisherMedia=PublisherMedia,
                        fb=fb,
                        decrypt_token=decrypt_token,
                        logger=logger,
                    )

            if total_due:
                logger.info("Scheduler processed %d due post(s)", total_due)

    except Exception as exc:
        logging.getLogger("publisher").exception("Scheduler job error: %s", exc)


def start_scheduler(app):
    """
    Start the APScheduler background job.
    Safe to call at import time — only one worker wins the file lock.
    """
    global _scheduler

    logger = setup_logger()

    if not _acquire_lock():
        logger.info("Scheduler lock not acquired — another worker is running it.")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler(daemon=True)
        _scheduler.add_job(
            _publish_due_posts,
            trigger="interval",
            seconds=60,
            args=[app],
            id="publish_due_posts",
        )
        _scheduler.start()
        logger.info("Publisher scheduler started (PID %d)", os.getpid())
    except Exception as exc:
        logger.error("Could not start scheduler: %s", exc)


def publish_single_post_now(app, post_id: int, tenant_slug: str | None = None):
    """
    Publish one queued post immediately (used by POST /api/posts/create for direct publishing).
    """
    logger = logging.getLogger("publisher")
    try:
        with app.app_context():
            from flask import g
            from extensions import db
            from modules.publisher.models.publisher_post import PublisherPost
            from modules.publisher.models.publisher_page import PublisherPage
            from modules.publisher.models.publisher_media import PublisherMedia
            from modules.publisher.services import facebook_service as fb
            from modules.publisher.services.token_utils import decrypt_token

            g.tenant = tenant_slug
            ensure_publisher_schema()
            post = PublisherPost.query.get(post_id)
            if not post:
                return {"success": False, "status": "failed", "errors": [f"post {post_id} not found"]}

            if post.status not in {"queued", "scheduled", "publishing"}:
                return {"success": post.status in {"published", "partial"}, "status": post.status, "errors": []}

            return _publish_single_post_record(
                app=app,
                db=db,
                post=post,
                PublisherPage=PublisherPage,
                PublisherMedia=PublisherMedia,
                fb=fb,
                decrypt_token=decrypt_token,
                logger=logger,
            )
    except Exception as exc:
        logger.exception("publish_single_post_now error: %s", exc)
        return {"success": False, "status": "failed", "errors": [str(exc)]}
