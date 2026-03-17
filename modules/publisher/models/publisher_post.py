import json
from datetime import datetime
from extensions import db


class PublisherPost(db.Model):
    """منشور في نظام الناشر."""

    __tablename__ = "publisher_posts"

    id = db.Column(db.Integer, primary_key=True)
    tenant_slug = db.Column(db.String(100), nullable=True, index=True)

    text = db.Column(db.Text, nullable=True)

    # JSON lists
    _media_ids = db.Column("media_ids", db.Text, nullable=True)
    _page_ids = db.Column("page_ids", db.Text, nullable=True)
    _facebook_post_ids = db.Column("facebook_post_ids", db.Text, nullable=True)  # {page_id: fb_post_id}

    status = db.Column(db.String(30), default="draft", nullable=False)
    # draft | queued | scheduled | publishing | published | partial | failed

    publish_type = db.Column(db.String(20), default="now", nullable=False)  # now | scheduled
    publish_time = db.Column(db.DateTime, nullable=True, index=True)
    visibility = db.Column(db.String(20), default="public", nullable=False)  # public | hidden

    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ── JSON helpers ──────────────────────────────────────────────────────────
    @property
    def media_ids(self):
        try:
            return json.loads(self._media_ids) if self._media_ids else []
        except Exception:
            return []

    @media_ids.setter
    def media_ids(self, value):
        self._media_ids = json.dumps(value) if value else None

    @property
    def page_ids(self):
        try:
            return json.loads(self._page_ids) if self._page_ids else []
        except Exception:
            return []

    @page_ids.setter
    def page_ids(self, value):
        self._page_ids = json.dumps(value) if value else None

    @property
    def facebook_post_ids(self):
        try:
            return json.loads(self._facebook_post_ids) if self._facebook_post_ids else {}
        except Exception:
            return {}

    @facebook_post_ids.setter
    def facebook_post_ids(self, value):
        self._facebook_post_ids = json.dumps(value) if value else None

    def to_dict(self):
        return {
            "id": self.id,
            "tenant_slug": self.tenant_slug,
            "text": self.text,
            "media_ids": self.media_ids,
            "page_ids": self.page_ids,
            "facebook_post_ids": self.facebook_post_ids,
            "status": self.status,
            "publish_type": self.publish_type,
            "publish_time": self.publish_time.isoformat() if self.publish_time else None,
            "visibility": self.visibility or "public",
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
