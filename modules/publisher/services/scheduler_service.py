"""
scheduler_service.py
--------------------
Background APScheduler worker for scheduled posts.

Gunicorn-safe: uses a file lock so only ONE worker runs the scheduler
even under multi-process gunicorn deployments.
"""

from __future__ import annotations

import fcntl
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

_scheduler = None
_lock_fd = None

LOCK_FILE = "/tmp/publisher_scheduler.lock"
LOG_FILE = "logs/publisher.log"


def _resolve_media_file_path(app, media_obj):
    """Build a local absolute path for PublisherMedia regardless of stored url_path format."""
    media_root = app.config.get("PUBLISHER_MEDIA_ROOT") or os.path.join(app.root_path, "media")
    tenant_dir = media_obj.tenant_slug or "default"
    sub = "images" if media_obj.media_type == "image" else "videos"
    return os.path.join(media_root, tenant_dir, sub, media_obj.filename)


def _publish_single_post_record(*, app, db, post, PublisherPage, PublisherMedia, fb, decrypt_token, logger):
    """Publish one PublisherPost now and persist final status."""
    post.status = "publishing"
    db.session.commit()

    fb_post_ids = {}
    errors = []

    for page_id in (post.page_ids or []):
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

        text = post.text or ""
        result = {"success": False, "message": "no media"}

        media_list = []
        if post.media_ids:
            media_list = PublisherMedia.query.filter(
                PublisherMedia.id.in_(post.media_ids)
            ).all()

        if not media_list:
            result = fb.publish_text_post(page_id, token, text)
        else:
            m = media_list[0]
            file_path = _resolve_media_file_path(app, m)
            if m.media_type == "image":
                result = fb.publish_photo_post(page_id, token, text, file_path)
            else:
                result = fb.publish_video_post(page_id, token, text, file_path)

        if result.get("success"):
            fb_post_ids[page_id] = (result.get("data") or {}).get("id", "")
            logger.info("Published post %d → page %s", post.id, page_id)
        else:
            errors.append(f"{page_id}: {result.get('message')}")
            logger.error("Failed post %d → page %s: %s", post.id, page_id, result.get("message"))

    post.facebook_post_ids = fb_post_ids
    if errors:
        post.status = "partial" if fb_post_ids else "failed"
        post.error_message = "; ".join(errors)
    else:
        post.status = "published"
        post.error_message = None
    db.session.commit()
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
            from extensions import db
            from modules.publisher.models.publisher_post import PublisherPost
            from modules.publisher.models.publisher_page import PublisherPage
            from modules.publisher.models.publisher_media import PublisherMedia
            from modules.publisher.services import facebook_service as fb
            from modules.publisher.services.token_utils import decrypt_token

            now = datetime.now(timezone.utc).replace(tzinfo=None)

            # Fetch queued (publish_type=now) + due scheduled posts
            posts = PublisherPost.query.filter(
                PublisherPost.status.in_(["queued", "scheduled"]),
            ).all()

            due = [
                p for p in posts
                if p.publish_type == "now"
                or (p.publish_time and p.publish_time <= now)
            ]

            if not due:
                return

            logger.info("Scheduler: %d post(s) to publish", len(due))

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


def publish_single_post_now(app, post_id: int):
    """
    Publish one queued post immediately (used by POST /api/posts/create for direct publishing).
    """
    logger = logging.getLogger("publisher")
    try:
        with app.app_context():
            from extensions import db
            from modules.publisher.models.publisher_post import PublisherPost
            from modules.publisher.models.publisher_page import PublisherPage
            from modules.publisher.models.publisher_media import PublisherMedia
            from modules.publisher.services import facebook_service as fb
            from modules.publisher.services.token_utils import decrypt_token

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
