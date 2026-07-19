"""Video / feed engagement models for mobile social commerce (Phase 2)."""
from __future__ import annotations

from datetime import datetime

from extensions import db


class MobileVideo(db.Model):
    __tablename__ = "mobile_video"
    __table_args__ = (
        db.Index(
            "ix_mobile_video_feed_rank",
            "status",
            "processing_status",
            "visibility",
            "is_featured",
            "priority",
            "published_at",
            "id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    creator_employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), index=True)
    title = db.Column(db.String(200), nullable=False, default="")
    description = db.Column(db.Text, default="")
    status = db.Column(db.String(30), nullable=False, default="draft", index=True)
    visibility = db.Column(db.String(30), nullable=False, default="public")
    thumbnail_url = db.Column(db.String(800))
    original_asset_url = db.Column(db.String(800))
    original_path = db.Column(db.String(800))
    hls_master_url = db.Column(db.String(800))
    hls_master_path = db.Column(db.String(800))
    duration_ms = db.Column(db.Integer)
    aspect_ratio = db.Column(db.String(20), default="9:16")
    processing_status = db.Column(db.String(30), nullable=False, default="pending", index=True)
    processing_progress = db.Column(db.Integer, nullable=False, default=0)
    processing_error = db.Column(db.Text)
    allow_comments = db.Column(db.Boolean, nullable=False, default=True)
    allow_sharing = db.Column(db.Boolean, nullable=False, default=True)
    allow_saving = db.Column(db.Boolean, nullable=False, default=True)
    is_featured = db.Column(db.Boolean, nullable=False, default=False, index=True)
    priority = db.Column(db.Integer, nullable=False, default=0, index=True)
    views_count = db.Column(db.Integer, nullable=False, default=0)
    likes_count = db.Column(db.Integer, nullable=False, default=0)
    comments_count = db.Column(db.Integer, nullable=False, default=0)
    shares_count = db.Column(db.Integer, nullable=False, default=0)
    saves_count = db.Column(db.Integer, nullable=False, default=0)
    published_at = db.Column(db.DateTime, index=True)
    scheduled_at = db.Column(db.DateTime, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at = db.Column(db.DateTime)

    assets = db.relationship("MobileVideoAsset", back_populates="video", lazy=True)
    products = db.relationship("MobileVideoProduct", back_populates="video", lazy=True)

    @property
    def playback_hls_url(self) -> str | None:
        url = (self.hls_master_url or "").strip()
        if not url:
            return None
        if url.rstrip("/").endswith("/hls"):
            return f"{url.rstrip('/')}/master.m3u8"
        return url

    def to_admin_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title or "",
            "description": self.description or "",
            "status": self.status,
            "visibility": self.visibility,
            "thumbnail_url": self.thumbnail_url,
            "original_asset_url": self.original_asset_url,
            "hls_master_url": self.playback_hls_url,
            "duration_ms": self.duration_ms,
            "aspect_ratio": self.aspect_ratio or "9:16",
            "processing_status": self.processing_status,
            "processing_progress": int(self.processing_progress or 0),
            "processing_error": self.processing_error,
            "allow_comments": bool(self.allow_comments),
            "allow_sharing": bool(self.allow_sharing),
            "allow_saving": bool(self.allow_saving),
            "is_featured": bool(self.is_featured),
            "priority": int(self.priority or 0),
            "views_count": int(self.views_count or 0),
            "likes_count": int(self.likes_count or 0),
            "comments_count": int(self.comments_count or 0),
            "shares_count": int(self.shares_count or 0),
            "saves_count": int(self.saves_count or 0),
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def to_feed_dict(
        self,
        *,
        liked: bool = False,
        saved: bool = False,
        playback_url: str | None = None,
    ) -> dict:
        return {
            "id": self.id,
            "title": self.title or "",
            "description": self.description or "",
            "thumbnail_url": self.thumbnail_url,
            "playback_url": playback_url
            or self.playback_hls_url
            or self.original_asset_url,
            "hls_master_url": self.playback_hls_url,
            "original_asset_url": self.original_asset_url,
            "duration_ms": self.duration_ms,
            "aspect_ratio": self.aspect_ratio or "9:16",
            "allow_comments": bool(self.allow_comments),
            "allow_sharing": bool(self.allow_sharing),
            "allow_saving": bool(self.allow_saving),
            "is_featured": bool(self.is_featured),
            "views_count": int(self.views_count or 0),
            "likes_count": int(self.likes_count or 0),
            "comments_count": int(self.comments_count or 0),
            "shares_count": int(self.shares_count or 0),
            "saves_count": int(self.saves_count or 0),
            "liked_by_me": liked,
            "saved_by_me": saved,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "products": [p.to_dict() for p in (self.products or [])],
        }


class MobileVideoAsset(db.Model):
    __tablename__ = "mobile_video_asset"

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey("mobile_video.id"), nullable=False, index=True)
    asset_type = db.Column(db.String(30), nullable=False, index=True)  # original|thumbnail|hls|mp4_720
    path = db.Column(db.String(800), nullable=False)
    public_url = db.Column(db.String(800))
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    bitrate_kbps = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    video = db.relationship("MobileVideo", back_populates="assets", lazy=True)


class MobileVideoProduct(db.Model):
    __tablename__ = "mobile_video_product"

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey("mobile_video.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    display_order = db.Column(db.Integer, nullable=False, default=0)
    custom_title = db.Column(db.String(200))
    custom_cta = db.Column(db.String(80))
    special_price = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    video = db.relationship("MobileVideo", back_populates="products", lazy=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "product_id": self.product_id,
            "display_order": int(self.display_order or 0),
            "custom_title": self.custom_title,
            "custom_cta": self.custom_cta,
            "special_price": self.special_price,
        }


class MobileVideoView(db.Model):
    __tablename__ = "mobile_video_view"

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey("mobile_video.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), index=True)
    device_id = db.Column(db.String(128), index=True)
    watch_ms = db.Column(db.Integer, nullable=False, default=0)
    completed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MobileVideoLike(db.Model):
    __tablename__ = "mobile_video_like"
    __table_args__ = (
        db.UniqueConstraint("video_id", "user_id", name="uq_mobile_video_like_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey("mobile_video.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MobileVideoSave(db.Model):
    __tablename__ = "mobile_video_save"
    __table_args__ = (
        db.UniqueConstraint("video_id", "user_id", name="uq_mobile_video_save_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey("mobile_video.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MobileVideoShare(db.Model):
    __tablename__ = "mobile_video_share"

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey("mobile_video.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), index=True)
    channel = db.Column(db.String(40), default="app")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MobileFeedEvent(db.Model):
    __tablename__ = "mobile_feed_event"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("mobile_user.id"), index=True)
    video_id = db.Column(db.Integer, db.ForeignKey("mobile_video.id"), nullable=False, index=True)
    event_type = db.Column(db.String(40), nullable=False, index=True)
    payload_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
