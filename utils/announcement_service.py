"""خدمة إرسال الإعلانات والنشرة الأسبوعية."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from extensions import db
from flask import g


def _get_announcement(announcement_id: int):
    from models.core.platform_announcement import PlatformAnnouncement

    old_tenant = getattr(g, "tenant", None)
    g.tenant = None
    try:
        return PlatformAnnouncement.query.get(announcement_id)
    finally:
        g.tenant = old_tenant


def set_weekly_announcement(announcement_id: int) -> tuple[bool, str]:
    from models.core.platform_announcement import PlatformAnnouncement

    old_tenant = getattr(g, "tenant", None)
    g.tenant = None
    try:
        ann = PlatformAnnouncement.query.get(announcement_id)
        if not ann:
            return False, "الإعلان غير موجود"
        PlatformAnnouncement.query.filter(PlatformAnnouncement.is_weekly_active.is_(True)).update(
            {PlatformAnnouncement.is_weekly_active: False},
            synchronize_session=False,
        )
        ann.is_weekly_active = True
        db.session.commit()
        return True, "تم تعيين الإعلان للإرسال الأسبوعي"
    except Exception as e:
        db.session.rollback()
        return False, str(e)
    finally:
        g.tenant = old_tenant


def _send_to_recipient(announcement, recipient: dict) -> bool:
    from models.core.announcement_send_log import AnnouncementSendLog
    from utils.email_helper import build_unsubscribe_url, send_announcement_email

    email = recipient["email"]
    token = recipient.get("unsubscribe_token")
    unsub_url = build_unsubscribe_url(token) if token else None

    try:
        ok = send_announcement_email(
            to_email=email,
            contact_name=recipient.get("contact_name") or "",
            subject=announcement.subject,
            body_html=announcement.body_html,
            body_plain=announcement.body_plain,
            unsubscribe_url=unsub_url,
        )
        log = AnnouncementSendLog(
            announcement_id=announcement.id,
            tenant_slug=recipient.get("slug") or "",
            email=email,
            success=ok,
            error_message=None if ok else "فشل الإرسال",
        )
        db.session.add(log)
        if ok:
            announcement.send_count = (announcement.send_count or 0) + 1
        return ok
    except Exception as e:
        log = AnnouncementSendLog(
            announcement_id=announcement.id,
            tenant_slug=recipient.get("slug") or "",
            email=email,
            success=False,
            error_message=str(e)[:500],
        )
        db.session.add(log)
        return False


def send_announcement_to_all(announcement_id: int) -> tuple[int, int, str]:
    """إرسال لجميع المشتركين. يُرجع (نجاح، فشل، رسالة)."""
    from utils.tenant_emails import iter_marketing_recipients

    old_tenant = getattr(g, "tenant", None)
    g.tenant = None
    try:
        ann = _get_announcement(announcement_id)
        if not ann:
            return 0, 0, "الإعلان غير موجود"

        recipients = iter_marketing_recipients()
        if not recipients:
            return 0, 0, "لا يوجد مستلمون موافقون على النشرة"

        success = failed = 0
        for recipient in recipients:
            if _send_to_recipient(ann, recipient):
                success += 1
            else:
                failed += 1
            db.session.commit()
            time.sleep(0.5)

        ann.status = "sent"
        ann.last_sent_at = datetime.utcnow()
        db.session.commit()
        return success, failed, f"تم الإرسال: {success} نجاح، {failed} فشل"
    except Exception as e:
        db.session.rollback()
        return 0, 0, str(e)
    finally:
        g.tenant = old_tenant


def send_announcement_to_tenant(announcement_id: int, slug: str) -> tuple[bool, str]:
    from utils.tenant_emails import get_tenant_email_recipient

    old_tenant = getattr(g, "tenant", None)
    g.tenant = None
    try:
        ann = _get_announcement(announcement_id)
        if not ann:
            return False, "الإعلان غير موجود"

        recipient = get_tenant_email_recipient(slug)
        if not recipient:
            return False, "لا يوجد بريد مسجّل لهذه الشركة"

        ok = _send_to_recipient(ann, recipient)
        ann.status = "sent"
        ann.last_sent_at = datetime.utcnow()
        db.session.commit()
        return ok, "تم الإرسال بنجاح" if ok else "فشل الإرسال"
    except Exception as e:
        db.session.rollback()
        return False, str(e)
    finally:
        g.tenant = old_tenant


def run_weekly_announcement_job() -> None:
    """مهمة مجدولة: إرسال الإعلان الأسبوعي النشط."""
    from models.core.global_setting import GlobalSetting
    from models.core.platform_announcement import PlatformAnnouncement

    old_tenant = getattr(g, "tenant", None)
    g.tenant = None
    try:
        if GlobalSetting.get_setting("WEEKLY_ANNOUNCEMENT_ENABLED", "1") != "1":
            return

        ann = PlatformAnnouncement.query.filter_by(is_weekly_active=True).first()
        if not ann:
            return

        send_announcement_to_all(ann.id)
    except Exception:
        try:
            from flask import current_app
            current_app.logger.exception("weekly announcement job failed")
        except Exception:
            pass
    finally:
        g.tenant = old_tenant
