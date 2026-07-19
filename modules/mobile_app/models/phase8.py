"""Notifications, analytics, and app design (Phase 8)."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class MobileNotification(db.Model):
    __tablename__ = "mobile_notification"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), index=True)
    # null user_id = broadcast template / audience job
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False, default="")
    notification_type = db.Column(db.String(60), nullable=False, index=True, default="general")
    data_json = db.Column(db.Text)  # deep-link payload
    audience = db.Column(db.String(40), nullable=False, default="user")
    # user | all | tier_gold | tier_vip | inactive
    status = db.Column(db.String(20), nullable=False, default="queued", index=True)
    # queued | sending | sent | failed
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    scheduled_at = db.Column(db.DateTime)
    sent_at = db.Column(db.DateTime)


class MobileNotificationDelivery(db.Model):
    __tablename__ = "mobile_notification_delivery"
    __table_args__ = (
        db.UniqueConstraint(
            "notification_id",
            "user_id",
            "channel",
            name="uq_mobile_notif_delivery_user_channel",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(
        db.Integer, db.ForeignKey("mobile_notification.id"), nullable=False, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, index=True)
    channel = db.Column(db.String(20), nullable=False, default="in_app")
    # in_app | push
    status = db.Column(db.String(20), nullable=False, default="delivered", index=True)
    read_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MobileNotificationPreference(db.Model):
    __tablename__ = "mobile_notification_preference"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, unique=True, index=True)
    orders_enabled = db.Column(db.Boolean, nullable=False, default=True)
    marketing_enabled = db.Column(db.Boolean, nullable=False, default=True)
    rewards_enabled = db.Column(db.Boolean, nullable=False, default=True)
    comments_enabled = db.Column(db.Boolean, nullable=False, default=True)
    push_enabled = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class MobileAnalyticsEvent(db.Model):
    __tablename__ = "mobile_analytics_event"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), index=True)
    device_id = db.Column(db.String(128), index=True)
    event_name = db.Column(db.String(80), nullable=False, index=True)
    session_id = db.Column(db.String(64), index=True)
    video_id = db.Column(db.Integer, index=True)
    product_id = db.Column(db.Integer, index=True)
    order_id = db.Column(db.Integer, index=True)
    campaign_id = db.Column(db.Integer, index=True)
    properties_json = db.Column(db.Text)
    client_ts = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class MobileAppDesign(db.Model):
    __tablename__ = "mobile_app_design"

    id = db.Column(db.Integer, primary_key=True)
    app_name = db.Column(db.String(120), nullable=False, default="Finora")
    primary_dark = db.Column(db.String(20), nullable=False, default="#08090C")
    surface_dark = db.Column(db.String(20), nullable=False, default="#111318")
    soft_white = db.Column(db.String(20), nullable=False, default="#F7F6F2")
    gold_accent = db.Column(db.String(20), nullable=False, default="#D9A441")
    muted_gold = db.Column(db.String(20), nullable=False, default="#B9872F")
    logo_url = db.Column(db.String(500))
    maintenance_mode = db.Column(db.Boolean, nullable=False, default=False)
    maintenance_message = db.Column(db.String(255))
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
