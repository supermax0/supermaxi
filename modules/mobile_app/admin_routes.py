"""Finora web admin UI for the mobile social commerce app."""
from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import or_

from extensions import db
from modules.mobile_app.schema_guard import ensure_mobile_app_schema
from modules.mobile_app.services import analytics as analytics_service
from modules.mobile_app.services import design as design_service
from modules.mobile_app.services import feature_flags as flags_service
from modules.mobile_app.services import notifications as notif_service
from modules.mobile_app.services import video_admin as video_admin_service
from utils.permission_checks import check_permission, get_current_employee

mobile_admin_bp = Blueprint(
    "mobile_admin",
    __name__,
    url_prefix="/mobile-app",
)

_ENDPOINT_PERMISSIONS = {
    "dashboard": "mobile_app.view_dashboard",
    "videos_page": "mobile_app.manage_videos",
    "videos_upload": "mobile_app.manage_videos",
    "videos_publish": "mobile_app.manage_videos",
    "videos_hide": "mobile_app.manage_videos",
    "flags_page": "mobile_app.manage_settings",
    "notifications_page": "mobile_app.send_notifications",
    "design_page": "mobile_app.manage_design",
    "analytics_page": "mobile_app.view_analytics",
    "users_page": "mobile_app.manage_users",
    "users_ban": "mobile_app.manage_users",
    "users_unban": "mobile_app.manage_users",
    "comments_page": "mobile_app.manage_comments",
    "rewards_page": "mobile_app.manage_rewards",
    "coupons_page": "mobile_app.manage_coupons",
}


def _require_admin_access():
    if "user_id" not in session and "employee_id" not in session:
        return redirect("/login")
    employee = get_current_employee()
    if employee is None:
        return redirect("/login")
    role = (employee.role or "").strip().lower()
    endpoint = (request.endpoint or "").rsplit(".", 1)[-1]
    required_permission = _ENDPOINT_PERMISSIONS.get(endpoint)
    allowed = role == "admin" or (
        required_permission is not None and check_permission(required_permission)
    )
    if not allowed:
        flash("لا تملك صلاحية إدارة تطبيق الهاتف", "danger")
        return redirect("/")
    g.mobile_staff = employee
    slug = session.get("tenant_slug")
    if slug:
        g.tenant = slug
        ensure_mobile_app_schema()
    return None


@mobile_admin_bp.before_request
def _mobile_admin_guard():
    return _require_admin_access()


@mobile_admin_bp.get("/")
def dashboard():
    from modules.mobile_app.models import MobileUser, MobileVideo
    from modules.mobile_app.models import MobileAnalyticsEvent

    videos_count = MobileVideo.query.count()
    users_count = MobileUser.query.count()
    events_count = MobileAnalyticsEvent.query.count()
    summary = analytics_service.conversion_summary(days=7)
    flags = flags_service.list_feature_flags()
    return render_template(
        "mobile_app/dashboard.html",
        videos_count=videos_count,
        users_count=users_count,
        events_count=events_count,
        summary=summary,
        flags=flags,
        design=design_service.get_design(),
    )


@mobile_admin_bp.get("/videos")
def videos_page():
    rows = video_admin_service.list_admin_videos(limit=50, offset=0)
    return render_template(
        "mobile_app/videos.html",
        videos=rows,
        max_upload_mb=video_admin_service.max_upload_mb(),
    )


@mobile_admin_bp.post("/videos/upload")
def videos_upload():
    upload = request.files.get("file") or request.files.get("video")
    if upload is None or not upload.filename:
        flash("اختر ملف فيديو", "danger")
        return redirect(url_for("mobile_admin.videos_page"))
    title = (request.form.get("title") or "").strip()
    description = (request.form.get("description") or "").strip()
    publish_now = (request.form.get("publish_now") or "1") in {"1", "true", "yes", "on"}
    try:
        video_admin_service.create_video_from_upload(
            tenant_slug=getattr(g, "tenant", None) or session.get("tenant_slug") or "",
            employee_id=getattr(g.mobile_staff, "id", None),
            title=title,
            description=description,
            file_storage=upload,
            publish_now=publish_now,
            product_ids=[],
        )
        flash("تم رفع الفيديو وبدأت المعالجة", "success")
    except Exception as exc:
        flash(f"فشل رفع الفيديو: {exc}", "danger")
    return redirect(url_for("mobile_admin.videos_page"))


@mobile_admin_bp.post("/videos/<int:video_id>/publish")
def videos_publish(video_id: int):
    from modules.mobile_app.models import MobileVideo
    from datetime import datetime

    video = db.session.get(MobileVideo, video_id)
    if video:
        video.status = "published"
        video.published_at = video.published_at or datetime.utcnow()
        db.session.commit()
        flash("تم نشر الفيديو", "success")
    return redirect(url_for("mobile_admin.videos_page"))


@mobile_admin_bp.post("/videos/<int:video_id>/hide")
def videos_hide(video_id: int):
    from modules.mobile_app.models import MobileVideo

    video = db.session.get(MobileVideo, video_id)
    if video:
        video.status = "hidden"
        db.session.commit()
        flash("تم إخفاء الفيديو", "success")
    return redirect(url_for("mobile_admin.videos_page"))


@mobile_admin_bp.route("/flags", methods=["GET", "POST"])
def flags_page():
    if request.method == "POST":
        key = (request.form.get("key") or "").strip()
        enabled = request.form.get("enabled") == "1"
        if key:
            flags_service.set_feature_flag(key, enabled)
            flash(f"تم تحديث {key}", "success")
        return redirect(url_for("mobile_admin.flags_page"))
    return render_template(
        "mobile_app/flags.html", flags=flags_service.list_feature_flags()
    )


@mobile_admin_bp.route("/notifications", methods=["GET", "POST"])
def notifications_page():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        body = (request.form.get("body") or "").strip()
        audience = (request.form.get("audience") or "all").strip()
        user_id_raw = (request.form.get("user_id") or "").strip()
        if not title or not body:
            flash("العنوان والنص مطلوبان", "danger")
            return redirect(url_for("mobile_admin.notifications_page"))
        if user_id_raw.isdigit():
            notif_service.create_user_notification(
                user_id=int(user_id_raw),
                title=title,
                body=body,
                notification_type="admin_broadcast",
            )
            flash("تم إرسال الإشعار للمستخدم", "success")
        else:
            result = notif_service.enqueue_broadcast(
                title=title,
                body=body,
                notification_type="marketing",
                audience=audience,
                created_by=getattr(g.mobile_staff, "id", None),
                tenant_slug=getattr(g, "tenant", None),
            )
            flash(f"تمت جدولة الإشعار ({result.get('status')})", "success")
        return redirect(url_for("mobile_admin.notifications_page"))
    return render_template("mobile_app/notifications.html")


@mobile_admin_bp.route("/design", methods=["GET", "POST"])
def design_page():
    if request.method == "POST":
        design_service.update_design(
            {
                "app_name": request.form.get("app_name"),
                "primary_dark": request.form.get("primary_dark"),
                "surface_dark": request.form.get("surface_dark"),
                "soft_white": request.form.get("soft_white"),
                "gold_accent": request.form.get("gold_accent"),
                "muted_gold": request.form.get("muted_gold"),
                "logo_url": request.form.get("logo_url"),
                "maintenance_mode": request.form.get("maintenance_mode") == "1",
                "maintenance_message": request.form.get("maintenance_message"),
            }
        )
        flash("تم حفظ تصميم التطبيق", "success")
        return redirect(url_for("mobile_admin.design_page"))
    return render_template("mobile_app/design.html", design=design_service.get_design())


@mobile_admin_bp.get("/analytics")
def analytics_page():
    days = int(request.args.get("days") or 7)
    summary = analytics_service.conversion_summary(days=days)
    return render_template("mobile_app/analytics.html", summary=summary, days=days)


@mobile_admin_bp.get("/users")
def users_page():
    from modules.mobile_app.models import MobileUser

    q = (request.args.get("q") or "").strip()
    query = MobileUser.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(MobileUser.phone.ilike(like), MobileUser.name.ilike(like))
        )
    users = query.order_by(MobileUser.id.desc()).limit(100).all()
    return render_template("mobile_app/users.html", users=users, q=q)


@mobile_admin_bp.post("/users/<int:user_id>/ban")
def users_ban(user_id: int):
    from modules.mobile_app.models import MobileUser
    from modules.mobile_app.services.auth import logout_all_sessions
    from datetime import datetime

    user = db.session.get(MobileUser, user_id)
    if user:
        reason = (request.form.get("reason") or "حظر من لوحة التحكم").strip()[:500]
        user.is_active = False
        user.banned_at = datetime.utcnow()
        user.ban_reason = reason
        logout_all_sessions(user_id)
        db.session.commit()
        flash("تم حظر المستخدم", "success")
    return redirect(url_for("mobile_admin.users_page"))


@mobile_admin_bp.post("/users/<int:user_id>/unban")
def users_unban(user_id: int):
    from modules.mobile_app.models import MobileUser

    user = db.session.get(MobileUser, user_id)
    if user:
        user.is_active = True
        user.banned_at = None
        user.ban_reason = None
        db.session.commit()
        flash("تم إلغاء الحظر", "success")
    return redirect(url_for("mobile_admin.users_page"))


@mobile_admin_bp.route("/comments", methods=["GET", "POST"])
def comments_page():
    from modules.mobile_app.models import MobileComment, MobileUser
    from modules.mobile_app.services import comments as comments_service

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        comment_id = int(request.form.get("comment_id") or 0)
        try:
            if action == "hide" and comment_id:
                comments_service.admin_hide_comment(comment_id)
                flash("تم إخفاء التعليق", "success")
            elif action == "pin" and comment_id:
                comments_service.admin_pin_comment(comment_id, pinned=True)
                flash("تم تثبيت التعليق", "success")
            elif action == "unpin" and comment_id:
                comments_service.admin_pin_comment(comment_id, pinned=False)
                flash("تم إلغاء التثبيت", "success")
            elif action == "reply":
                video_id = int(request.form.get("video_id") or 0)
                parent_id_raw = (request.form.get("parent_id") or "").strip()
                body = (request.form.get("body") or "").strip()
                parent_id = int(parent_id_raw) if parent_id_raw.isdigit() else None
                comments_service.admin_company_reply(
                    video_id=video_id,
                    parent_id=parent_id,
                    body=body,
                    employee_id=getattr(g.mobile_staff, "id", None),
                )
                flash("تم إرسال رد الشركة", "success")
        except Exception as exc:
            flash(str(exc), "danger")
        return redirect(url_for("mobile_admin.comments_page"))

    status = (request.args.get("status") or "").strip()
    query = MobileComment.query.filter(MobileComment.deleted_at.is_(None))
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(MobileComment.id.desc()).limit(80).all()
    user_ids = {c.user_id for c in rows if c.user_id}
    users = {
        u.id: u
        for u in MobileUser.query.filter(MobileUser.id.in_(user_ids)).all()
    } if user_ids else {}
    items = []
    for c in rows:
        author = users.get(c.user_id)
        items.append(
            {
                "id": c.id,
                "video_id": c.video_id,
                "body": c.body,
                "status": c.status,
                "is_pinned": c.is_pinned,
                "is_company_reply": c.is_company_reply,
                "reports_count": c.reports_count,
                "author": (author.name if author else "") or (author.phone if author else "شركة"),
            }
        )
    return render_template(
        "mobile_app/comments.html", comments=items, status=status
    )


@mobile_admin_bp.route("/rewards", methods=["GET", "POST"])
def rewards_page():
    from modules.mobile_app.services import rewards as reward_service

    if request.method == "POST":
        user_id_raw = (request.form.get("user_id") or "").strip()
        points_raw = (request.form.get("points") or "").strip()
        direction = (request.form.get("direction") or "credit").strip()
        description = (request.form.get("description") or "تعديل يدوي").strip()
        if user_id_raw.isdigit() and points_raw.isdigit():
            try:
                reward_service.adjust_points(
                    user_id=int(user_id_raw),
                    points=int(points_raw),
                    direction=direction if direction in {"credit", "debit"} else "credit",
                    description=description,
                    staff_id=getattr(g.mobile_staff, "id", None),
                )
                flash("تم تعديل النقاط", "success")
            except Exception as exc:
                flash(str(exc), "danger")
        else:
            flash("معرف المستخدم والنقاط مطلوبان", "danger")
        return redirect(url_for("mobile_admin.rewards_page"))

    return render_template(
        "mobile_app/rewards.html",
        rules=reward_service.list_rules(),
        tiers=reward_service.list_tiers(),
    )


@mobile_admin_bp.route("/coupons", methods=["GET", "POST"])
def coupons_page():
    from modules.mobile_app.models import MobileCoupon
    from modules.mobile_app.services import discounts as discount_service
    from modules.mobile_app.services.discounts import DiscountError

    if request.method == "POST":
        action = (request.form.get("action") or "create").strip()
        if action == "toggle":
            coupon_id = int(request.form.get("coupon_id") or 0)
            row = db.session.get(MobileCoupon, coupon_id)
            if row:
                row.is_active = not bool(row.is_active)
                db.session.commit()
                flash("تم تحديث حالة الكوبون", "success")
            return redirect(url_for("mobile_admin.coupons_page"))
        try:
            value = int(request.form.get("value") or 0)
            min_subtotal = int(request.form.get("min_subtotal") or 0)
            max_uses_raw = (request.form.get("max_uses") or "").strip()
            max_uses = int(max_uses_raw) if max_uses_raw.isdigit() else None
            discount_service.create_coupon(
                code=str(request.form.get("code") or ""),
                name=str(request.form.get("name") or ""),
                discount_type=str(request.form.get("discount_type") or "percent"),
                value=value,
                min_subtotal=min_subtotal,
                max_uses=max_uses,
            )
            flash("تم إنشاء الكوبون", "success")
        except (DiscountError, ValueError) as exc:
            flash(str(getattr(exc, "message", None) or exc), "danger")
        return redirect(url_for("mobile_admin.coupons_page"))

    coupons = MobileCoupon.query.order_by(MobileCoupon.id.desc()).limit(100).all()
    return render_template("mobile_app/coupons.html", coupons=coupons)
