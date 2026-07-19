"""Tenant-scoped persistence models for the mobile social commerce app."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class MobileUser(db.Model):
    __tablename__ = "mobile_user"

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(32), nullable=False, unique=True, index=True)
    name = db.Column(db.String(150), nullable=False, default="")
    email = db.Column(db.String(200))
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    banned_at = db.Column(db.DateTime)
    ban_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    customer = db.relationship("Customer", foreign_keys=[customer_id], lazy=True)
    devices = db.relationship("MobileUserDevice", back_populates="user", lazy=True)
    sessions = db.relationship("MobileUserSession", back_populates="user", lazy=True)

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "phone": self.phone,
            "name": self.name or "",
            "email": self.email or "",
            "customer_id": self.customer_id,
            "is_active": bool(self.is_active),
        }


class MobileUserDevice(db.Model):
    __tablename__ = "mobile_user_device"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, index=True)
    device_id = db.Column(db.String(128), nullable=False, index=True)
    platform = db.Column(db.String(30), nullable=False, default="unknown")
    push_token = db.Column(db.String(512))
    app_version = db.Column(db.String(40))
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("MobileUser", back_populates="devices", lazy=True)


class MobileUserSession(db.Model):
    __tablename__ = "mobile_user_session"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey("mobile_user_device.id"), index=True)
    refresh_token_hash = db.Column(db.String(128), nullable=False, unique=True, index=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    revoked_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("MobileUser", back_populates="sessions", lazy=True)
    device = db.relationship("MobileUserDevice", lazy=True)

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at > datetime.utcnow()


class MobileOtpRequest(db.Model):
    __tablename__ = "mobile_otp_request"

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(32), nullable=False, index=True)
    code_hash = db.Column(db.String(128), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=5)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    consumed_at = db.Column(db.DateTime)
    request_ip = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MobileFeatureFlag(db.Model):
    __tablename__ = "mobile_feature_flag"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), nullable=False, unique=True, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


# Phase 2 video models
from modules.mobile_app.models.videos import (  # noqa: E402
    MobileFeedEvent,
    MobileVideo,
    MobileVideoAsset,
    MobileVideoLike,
    MobileVideoProduct,
    MobileVideoSave,
    MobileVideoShare,
    MobileVideoView,
)

# Phase 3 comment models
from modules.mobile_app.models.comments import (  # noqa: E402
    MobileBlockedUser,
    MobileComment,
    MobileCommentLike,
    MobileCommentReport,
    MobileModerationRule,
)

from modules.mobile_app.models.favorites import MobileFavorite  # noqa: E402
from modules.mobile_app.models.cart import (  # noqa: E402
    MobileCart,
    MobileCartItem,
    MobileOrderAttribution,
)
from modules.mobile_app.models.rewards import (  # noqa: E402
    MobileRewardAccount,
    MobileRewardRedemption,
    MobileRewardRule,
    MobileRewardTier,
    MobileRewardTransaction,
)
from modules.mobile_app.models.discounts import (  # noqa: E402
    MobileCampaign,
    MobileCoupon,
    MobileCouponRedemption,
    MobileDiscount,
)
from modules.mobile_app.models.ai import (  # noqa: E402
    MobileAIConversation,
    MobileAIMessage,
    MobileAIToolExecution,
)
from modules.mobile_app.models.phase8 import (  # noqa: E402
    MobileAnalyticsEvent,
    MobileAppDesign,
    MobileNotification,
    MobileNotificationDelivery,
    MobileNotificationPreference,
)
from modules.mobile_app.models.profile import MobileUserAddress  # noqa: E402

__all__ = [
    "MobileUser",
    "MobileUserDevice",
    "MobileUserSession",
    "MobileOtpRequest",
    "MobileFeatureFlag",
    "MobileVideo",
    "MobileVideoAsset",
    "MobileVideoProduct",
    "MobileVideoView",
    "MobileVideoLike",
    "MobileVideoSave",
    "MobileVideoShare",
    "MobileFeedEvent",
    "MobileComment",
    "MobileCommentLike",
    "MobileCommentReport",
    "MobileBlockedUser",
    "MobileModerationRule",
    "MobileFavorite",
    "MobileCart",
    "MobileCartItem",
    "MobileOrderAttribution",
    "MobileRewardAccount",
    "MobileRewardTransaction",
    "MobileRewardRule",
    "MobileRewardTier",
    "MobileRewardRedemption",
    "MobileCampaign",
    "MobileCoupon",
    "MobileCouponRedemption",
    "MobileDiscount",
    "MobileAIConversation",
    "MobileAIMessage",
    "MobileAIToolExecution",
    "MobileNotification",
    "MobileNotificationDelivery",
    "MobileNotificationPreference",
    "MobileAnalyticsEvent",
    "MobileAppDesign",
    "MobileUserAddress",
]
