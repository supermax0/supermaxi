"""Persistence models for the tenant-scoped Finora Sales AI module."""
from __future__ import annotations

import json
import secrets
from datetime import datetime

from extensions import db


def _loads(value, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _dumps(value) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


class AISalesChannelAccount(db.Model):
    __tablename__ = "ai_sales_channel_account"

    id = db.Column(db.Integer, primary_key=True)
    channel_type = db.Column(db.String(30), default="whatsapp", nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    phone_number = db.Column(db.String(40))
    phone_number_id = db.Column(db.String(100), index=True)
    waba_id = db.Column(db.String(100))
    parent_channel_id = db.Column(db.Integer, db.ForeignKey("ai_sales_channel_account.id"), index=True)
    external_account_id = db.Column(db.String(128), index=True)
    page_id = db.Column(db.String(128), index=True)
    platform_username = db.Column(db.String(150))
    profile_picture_url = db.Column(db.String(800))
    reply_mode = db.Column(db.String(20), default="ai", nullable=False, index=True)
    comments_enabled = db.Column(db.Boolean, default=False, nullable=False, index=True)
    comments_reply_mode = db.Column(db.String(20), default="inbox", nullable=False, index=True)
    comments_private_reply = db.Column(db.Boolean, default=True, nullable=False)
    comments_public_text = db.Column(db.String(300), default="تم الرد على الخاص", nullable=False)
    default_employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), index=True)
    webhook_key = db.Column(db.String(64), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(24))
    access_token_encrypted = db.Column(db.Text)
    app_secret_encrypted = db.Column(db.Text)
    verify_token_encrypted = db.Column(db.Text)
    api_version = db.Column(db.String(20), default="v23.0", nullable=False)
    connection_status = db.Column(db.String(30), default="draft", nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=False, nullable=False, index=True)
    last_webhook_at = db.Column(db.DateTime)
    last_sync_at = db.Column(db.DateTime)
    sync_blocked_until = db.Column(db.DateTime, index=True)
    calling_status = db.Column(db.String(30), default="unknown", nullable=False, index=True)
    calling_settings_json = db.Column(db.Text)
    calling_last_checked_at = db.Column(db.DateTime)
    last_error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversations = db.relationship("AISalesConversation", back_populates="channel", lazy=True)
    default_employee = db.relationship("Employee", foreign_keys=[default_employee_id], lazy=True)

    def get_calling_settings(self) -> dict:
        return _loads(self.calling_settings_json, {})

    def set_calling_settings(self, value: dict | None) -> None:
        self.calling_settings_json = _dumps(value)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "channel_type": self.channel_type,
            "name": self.name,
            "phone_number": self.phone_number or "",
            "phone_number_id": self.phone_number_id or "",
            "waba_id": self.waba_id or "",
            "parent_channel_id": self.parent_channel_id,
            "external_account_id": self.external_account_id or "",
            "page_id": self.page_id or "",
            "platform_username": self.platform_username or "",
            "profile_picture_url": self.profile_picture_url or "",
            "reply_mode": self.reply_mode or "ai",
            "comments_enabled": bool(self.comments_enabled),
            "comments_reply_mode": self.comments_reply_mode or "inbox",
            "comments_private_reply": bool(self.comments_private_reply),
            "comments_public_text": self.comments_public_text or "تم الرد على الخاص",
            "default_employee_id": self.default_employee_id,
            "default_employee": self.default_employee.name if self.default_employee else "",
            "webhook_key": self.webhook_key,
            "api_version": self.api_version,
            "connection_status": self.connection_status,
            "is_active": bool(self.is_active),
            "has_access_token": bool(self.access_token_encrypted),
            "has_app_secret": bool(self.app_secret_encrypted),
            "has_verify_token": bool(self.verify_token_encrypted),
            "last_webhook_at": self.last_webhook_at.isoformat() if self.last_webhook_at else None,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "sync_blocked_until": self.sync_blocked_until.isoformat() if self.sync_blocked_until else None,
            "calling_status": self.calling_status or "unknown",
            "calling_settings": self.get_calling_settings(),
            "calling_last_checked_at": self.calling_last_checked_at.isoformat() if self.calling_last_checked_at else None,
            "last_error": self.last_error or "",
        }


class AISalesSocialPost(db.Model):
    __tablename__ = "ai_sales_social_post"
    __table_args__ = (
        db.UniqueConstraint("channel_account_id", "external_post_id", name="uq_ai_sales_social_post"),
    )

    id = db.Column(db.Integer, primary_key=True)
    channel_account_id = db.Column(db.Integer, db.ForeignKey("ai_sales_channel_account.id"), nullable=False, index=True)
    external_post_id = db.Column(db.String(180), nullable=False, index=True)
    message = db.Column(db.Text)
    story = db.Column(db.Text)
    permalink_url = db.Column(db.String(1000))
    media_url = db.Column(db.String(1000))
    media_type = db.Column(db.String(30))
    comments_count = db.Column(db.Integer, default=0, nullable=False)
    published_at = db.Column(db.DateTime, index=True)
    raw_payload_json = db.Column(db.Text)
    last_synced_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    channel = db.relationship("AISalesChannelAccount", lazy=True)
    comments = db.relationship(
        "AISalesSocialComment",
        back_populates="post",
        cascade="all, delete-orphan",
        lazy=True,
    )

    def set_raw_payload(self, value: dict | None) -> None:
        self.raw_payload_json = _dumps(value)

    def to_dict(self, *, include_channel: bool = True) -> dict:
        row = {
            "id": self.id,
            "channel_account_id": self.channel_account_id,
            "external_post_id": self.external_post_id,
            "message": self.message or "",
            "story": self.story or "",
            "permalink_url": self.permalink_url or "",
            "media_url": self.media_url or "",
            "media_type": self.media_type or "",
            "comments_count": int(self.comments_count or 0),
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_channel:
            row.update({
                "channel_name": self.channel.name if self.channel else "",
                "channel_picture_url": self.channel.profile_picture_url if self.channel else "",
            })
        return row


class AISalesSocialComment(db.Model):
    __tablename__ = "ai_sales_social_comment"
    __table_args__ = (
        db.UniqueConstraint("channel_account_id", "external_comment_id", name="uq_ai_sales_social_comment"),
    )

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("ai_sales_social_post.id"), nullable=False, index=True)
    channel_account_id = db.Column(db.Integer, db.ForeignKey("ai_sales_channel_account.id"), nullable=False, index=True)
    external_comment_id = db.Column(db.String(180), nullable=False, index=True)
    parent_external_comment_id = db.Column(db.String(180), index=True)
    external_user_id = db.Column(db.String(180), index=True)
    user_name = db.Column(db.String(180))
    user_picture_url = db.Column(db.String(1000))
    message = db.Column(db.Text)
    attachment_url = db.Column(db.String(1000))
    permalink_url = db.Column(db.String(1000))
    status = db.Column(db.String(30), default="new", nullable=False, index=True)
    public_reply_text = db.Column(db.Text)
    public_reply_external_id = db.Column(db.String(180))
    public_reply_status = db.Column(db.String(30))
    private_reply_text = db.Column(db.Text)
    private_reply_external_id = db.Column(db.String(180))
    private_reply_status = db.Column(db.String(30))
    failure_message = db.Column(db.Text)
    raw_payload_json = db.Column(db.Text)
    commented_at = db.Column(db.DateTime, index=True)
    replied_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    post = db.relationship("AISalesSocialPost", back_populates="comments", lazy=True)
    channel = db.relationship("AISalesChannelAccount", lazy=True)

    def set_raw_payload(self, value: dict | None) -> None:
        self.raw_payload_json = _dumps(value)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "post_id": self.post_id,
            "channel_account_id": self.channel_account_id,
            "external_comment_id": self.external_comment_id,
            "parent_external_comment_id": self.parent_external_comment_id or "",
            "external_user_id": self.external_user_id or "",
            "user_name": self.user_name or "مستخدم فيسبوك",
            "user_picture_url": self.user_picture_url or "",
            "message": self.message or "",
            "attachment_url": self.attachment_url or "",
            "permalink_url": self.permalink_url or "",
            "status": self.status or "new",
            "public_reply_text": self.public_reply_text or "",
            "public_reply_external_id": self.public_reply_external_id or "",
            "public_reply_status": self.public_reply_status or "",
            "private_reply_text": self.private_reply_text or "",
            "private_reply_external_id": self.private_reply_external_id or "",
            "private_reply_status": self.private_reply_status or "",
            "failure_message": self.failure_message or "",
            "commented_at": self.commented_at.isoformat() if self.commented_at else None,
            "replied_at": self.replied_at.isoformat() if self.replied_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AISalesConversation(db.Model):
    __tablename__ = "ai_sales_conversation"
    __table_args__ = (
        db.UniqueConstraint("channel_account_id", "external_contact_id", name="uq_ai_sales_channel_contact"),
    )

    id = db.Column(db.Integer, primary_key=True)
    channel_account_id = db.Column(db.Integer, db.ForeignKey("ai_sales_channel_account.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), index=True)
    external_contact_id = db.Column(db.String(100), nullable=False, index=True)
    external_phone = db.Column(db.String(40), index=True)
    contact_name = db.Column(db.String(150))
    contact_profile_picture_url = db.Column(db.String(800))
    status = db.Column(db.String(30), default="open", nullable=False, index=True)
    sales_stage = db.Column(db.String(40), default="new", nullable=False, index=True)
    lead_temperature = db.Column(db.String(20), default="cold", nullable=False, index=True)
    lead_score = db.Column(db.Integer, default=0, nullable=False)
    assigned_employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), index=True)
    ai_enabled = db.Column(db.Boolean, default=True, nullable=False)
    human_takeover = db.Column(db.Boolean, default=False, nullable=False, index=True)
    ai_paused_until = db.Column(db.DateTime, index=True)
    handoff_reason = db.Column(db.String(300))
    context_json = db.Column(db.Text)
    summary = db.Column(db.Text)
    last_customer_message_at = db.Column(db.DateTime)
    last_business_message_at = db.Column(db.DateTime)
    service_window_expires_at = db.Column(db.DateTime)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    closed_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    channel = db.relationship("AISalesChannelAccount", back_populates="conversations", lazy=True)
    customer = db.relationship("Customer", lazy=True)
    assigned_employee = db.relationship("Employee", lazy=True)
    messages = db.relationship("AISalesMessage", back_populates="conversation", cascade="all, delete-orphan", lazy=True)
    read_receipts = db.relationship("AISalesConversationRead", back_populates="conversation", cascade="all, delete-orphan", lazy=True)

    def get_context(self) -> dict:
        return _loads(self.context_json, {})

    def set_context(self, value: dict | None) -> None:
        self.context_json = _dumps(value)

    def to_dict(self) -> dict:
        channel = self.channel
        context = self.get_context()
        return {
            "id": self.id,
            "channel_account_id": self.channel_account_id,
            "channel_type": channel.channel_type if channel else "",
            "channel_name": channel.name if channel else "",
            "channel_username": channel.platform_username if channel else "",
            "channel_profile_picture_url": channel.profile_picture_url if channel else "",
            "customer_id": self.customer_id,
            "external_contact_id": self.external_contact_id,
            "external_phone": self.external_phone or "",
            "contact_name": self.contact_name or "",
            "contact_profile_picture_url": self.contact_profile_picture_url or "",
            "status": self.status,
            "sales_stage": self.sales_stage,
            "lead_temperature": self.lead_temperature,
            "lead_score": int(self.lead_score or 0),
            "assigned_employee_id": self.assigned_employee_id,
            "assigned_employee": self.assigned_employee.name if self.assigned_employee else "",
            "ai_enabled": bool(self.ai_enabled),
            "human_takeover": bool(self.human_takeover),
            "ai_paused_until": self.ai_paused_until.isoformat() if self.ai_paused_until else None,
            "handoff_reason": self.handoff_reason or "",
            "summary": self.summary or "",
            "order_customer_data": context.get("order_customer_data") or {},
            "ad_context": context.get("ad_context") or {},
            "pending_order": context.get("pending_order") or {},
            "created_order_id": context.get("created_order_id"),
            "last_customer_message_at": self.last_customer_message_at.isoformat() if self.last_customer_message_at else None,
            "last_business_message_at": self.last_business_message_at.isoformat() if self.last_business_message_at else None,
            "service_window_expires_at": self.service_window_expires_at.isoformat() if self.service_window_expires_at else None,
        }


class AISalesMessage(db.Model):
    __tablename__ = "ai_sales_message"
    __table_args__ = (
        db.UniqueConstraint("channel_account_id", "external_message_id", name="uq_ai_sales_external_message"),
    )

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("ai_sales_conversation.id"), nullable=False, index=True)
    channel_account_id = db.Column(db.Integer, db.ForeignKey("ai_sales_channel_account.id"), nullable=False, index=True)
    external_message_id = db.Column(db.String(180), index=True)
    reply_to_external_id = db.Column(db.String(180))
    direction = db.Column(db.String(20), nullable=False, index=True)
    sender_type = db.Column(db.String(20), nullable=False, index=True)
    message_type = db.Column(db.String(30), default="text", nullable=False, index=True)
    text_content = db.Column(db.Text)
    transcription = db.Column(db.Text)
    transcription_model = db.Column(db.String(100))
    transcription_status = db.Column(db.String(30))
    transcription_error = db.Column(db.Text)
    external_media_id = db.Column(db.String(180))
    mime_type = db.Column(db.String(100))
    media_path = db.Column(db.String(600))
    media_metadata_json = db.Column(db.Text)
    status = db.Column(db.String(30), default="received", nullable=False, index=True)
    failure_code = db.Column(db.String(100))
    failure_message = db.Column(db.Text)
    raw_payload_json = db.Column(db.Text)
    sent_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)
    read_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    conversation = db.relationship("AISalesConversation", back_populates="messages", lazy=True)

    def set_raw_payload(self, value: dict | None) -> None:
        self.raw_payload_json = _dumps(value)

    def set_media_metadata(self, value: dict | None) -> None:
        self.media_metadata_json = _dumps(value)

    def get_media_metadata(self) -> dict:
        return _loads(self.media_metadata_json, {})

    def to_dict(self) -> dict:
        metadata = self.get_media_metadata()
        from .links import extract_link_previews

        deleted_local = bool(metadata.get("deleted_local"))
        can_edit = bool(
            not deleted_local
            and self.direction == "outbound"
            and self.sender_type == "employee"
            and self.message_type == "text"
            and (self.status in {"queued", "failed"} or str(self.external_message_id or "").startswith("sim-"))
        )
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "external_message_id": self.external_message_id,
            "direction": self.direction,
            "sender_type": self.sender_type,
            "message_type": self.message_type,
            "text_content": "" if deleted_local else self.text_content or "",
            "transcription": "" if deleted_local else self.transcription or "",
            "transcription_model": self.transcription_model or "",
            "transcription_status": self.transcription_status or "",
            "transcription_error": self.transcription_error or "",
            "external_media_id": self.external_media_id or "",
            "mime_type": self.mime_type or "",
            "media_url": "" if deleted_local else (
                f"/ai-sales/api/messages/{self.id}/media"
                if self.media_path
                else self.external_media_id
                if str(self.external_media_id or "").startswith(("https://", "http://"))
                else ""
            ),
            "status": self.status,
            "failure_code": self.failure_code or "",
            "failure_message": self.failure_message or "",
            "is_deleted": deleted_local,
            "deleted_at": metadata.get("deleted_at") or "",
            "edited_at": metadata.get("edited_at") or "",
            "original_filename": metadata.get("original_filename") or "",
            "file_size": int(metadata.get("file_size") or 0),
            "link_previews": [] if deleted_local else (
                metadata.get("link_previews")
                or extract_link_previews(self.text_content or self.transcription or "")
            ),
            "ad_context": {} if deleted_local else metadata.get("ad_context") or {},
            "meta_context": {} if deleted_local else metadata.get("meta_context") or {},
            "training": {} if deleted_local else metadata.get("training") or {},
            "thread_opener": bool(metadata.get("thread_opener")),
            "ad_opener": bool(metadata.get("ad_opener") or metadata.get("synced_empty_opener")),
            "actions": {
                "can_copy": not deleted_local,
                "can_edit": can_edit,
                "can_delete_local": not deleted_local,
                "can_delete_everyone": False,
            },
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "delivered_at": self.delivered_at.isoformat() if self.delivered_at else None,
            "read_at": self.read_at.isoformat() if self.read_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AISalesConversationRead(db.Model):
    __tablename__ = "ai_sales_conversation_read"
    __table_args__ = (
        db.UniqueConstraint("conversation_id", "employee_id", name="uq_ai_sales_conversation_employee_read"),
    )

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("ai_sales_conversation.id"), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    last_read_message_id = db.Column(db.Integer, db.ForeignKey("ai_sales_message.id"), index=True)
    last_read_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    conversation = db.relationship("AISalesConversation", back_populates="read_receipts", lazy=True)


class AISalesCall(db.Model):
    """A redacted audit trail for WhatsApp Calling API webhook events."""

    __tablename__ = "ai_sales_call"
    __table_args__ = (
        db.UniqueConstraint("channel_account_id", "external_call_id", name="uq_ai_sales_channel_call"),
    )

    id = db.Column(db.Integer, primary_key=True)
    channel_account_id = db.Column(db.Integer, db.ForeignKey("ai_sales_channel_account.id"), nullable=False, index=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("ai_sales_conversation.id"), index=True)
    external_call_id = db.Column(db.String(180), nullable=False, index=True)
    external_contact_id = db.Column(db.String(180), index=True)
    direction = db.Column(db.String(30), nullable=False, index=True)
    event = db.Column(db.String(30), nullable=False, index=True)
    status = db.Column(db.String(30), default="ringing", nullable=False, index=True)
    from_number = db.Column(db.String(80))
    to_number = db.Column(db.String(80))
    sdp_type = db.Column(db.String(20))
    duration_seconds = db.Column(db.Integer, default=0)
    failure_code = db.Column(db.String(100))
    failure_message = db.Column(db.Text)
    raw_payload_json = db.Column(db.Text)
    started_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    channel = db.relationship("AISalesChannelAccount", lazy=True)
    conversation = db.relationship("AISalesConversation", lazy=True)

    def set_raw_payload(self, value: dict | None) -> None:
        self.raw_payload_json = _dumps(value)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "channel_account_id": self.channel_account_id,
            "conversation_id": self.conversation_id,
            "external_call_id": self.external_call_id,
            "external_contact_id": self.external_contact_id or "",
            "direction": self.direction,
            "event": self.event,
            "status": self.status,
            "from_number": self.from_number or "",
            "to_number": self.to_number or "",
            "sdp_type": self.sdp_type or "",
            "duration_seconds": int(self.duration_seconds or 0),
            "failure_code": self.failure_code or "",
            "failure_message": self.failure_message or "",
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AISalesLead(db.Model):
    __tablename__ = "ai_sales_lead"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("ai_sales_conversation.id"), nullable=False, unique=True, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), index=True)
    status = db.Column(db.String(30), default="new", nullable=False, index=True)
    temperature = db.Column(db.String(20), default="cold", nullable=False, index=True)
    score = db.Column(db.Integer, default=0, nullable=False)
    purchase_probability = db.Column(db.Integer, default=0)
    estimated_budget = db.Column(db.Integer)
    main_need = db.Column(db.Text)
    primary_objection = db.Column(db.String(120))
    next_action = db.Column(db.String(220))
    followup_at = db.Column(db.DateTime)
    won_order_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), index=True)
    lost_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation = db.relationship("AISalesConversation", lazy=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "customer_id": self.customer_id,
            "product_id": self.product_id,
            "status": self.status,
            "temperature": self.temperature,
            "score": int(self.score or 0),
            "purchase_probability": int(self.purchase_probability or 0),
            "estimated_budget": self.estimated_budget,
            "main_need": self.main_need or "",
            "primary_objection": self.primary_objection or "",
            "next_action": self.next_action or "",
            "followup_at": self.followup_at.isoformat() if self.followup_at else None,
            "won_order_id": self.won_order_id,
        }


class AISalesAgentProfile(db.Model):
    __tablename__ = "ai_sales_agent_profile"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), default="Finora Sales AI", nullable=False)
    language = db.Column(db.String(20), default="ar", nullable=False)
    dialect = db.Column(db.String(40), default="iraqi", nullable=False)
    tone = db.Column(db.String(40), default="friendly_confident", nullable=False)
    sales_style = db.Column(db.String(40), default="consultative", nullable=False)
    intelligence_level = db.Column(db.String(30), default="expert", nullable=False)
    persuasion_style = db.Column(db.String(30), default="balanced", nullable=False)
    max_reply_length = db.Column(db.Integer, default=650, nullable=False)
    emoji_level = db.Column(db.String(20), default="low", nullable=False)
    text_model = db.Column(db.String(80), default="gpt-5.6-sol", nullable=False)
    tts_model = db.Column(db.String(100), default="gpt-4o-mini-tts", nullable=False)
    transcription_model = db.Column(db.String(100), default="gpt-4o-mini-transcribe", nullable=False)
    realtime_model = db.Column(db.String(100), default="gpt-realtime-2.1", nullable=False)
    voice_enabled = db.Column(db.Boolean, default=True, nullable=False)
    voice_reply_mode = db.Column(db.String(30), default="match_customer", nullable=False)
    voice_name = db.Column(db.String(80), default="marin")
    audio_format = db.Column(db.String(20), default="opus", nullable=False)
    voice_speed = db.Column(db.Float, default=0.96, nullable=False)
    audio_quality = db.Column(db.String(30), default="professional", nullable=False)
    voice_instructions = db.Column(db.Text)
    max_context_messages = db.Column(db.Integer, default=18, nullable=False)
    max_audio_size_mb = db.Column(db.Integer, default=25, nullable=False)
    human_takeover_minutes = db.Column(db.Integer, default=30, nullable=False)
    ai_response_delay_ms = db.Column(db.Integer, default=0, nullable=False)
    auto_escalation = db.Column(db.Boolean, default=True, nullable=False)
    continuous_learning_enabled = db.Column(db.Boolean, default=True, nullable=False)
    learn_from_employee_replies = db.Column(db.Boolean, default=True, nullable=False)
    learning_min_quality = db.Column(db.Integer, default=76, nullable=False)
    system_instructions = db.Column(db.Text)
    handoff_threshold = db.Column(db.Integer, default=45, nullable=False)
    max_products = db.Column(db.Integer, default=3, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "language": self.language,
            "dialect": self.dialect,
            "tone": self.tone,
            "sales_style": self.sales_style,
            "intelligence_level": self.intelligence_level or "expert",
            "persuasion_style": self.persuasion_style or "balanced",
            "max_reply_length": self.max_reply_length,
            "emoji_level": self.emoji_level,
            "text_model": self.text_model,
            "tts_model": self.tts_model or "gpt-4o-mini-tts",
            "transcription_model": self.transcription_model or "gpt-4o-mini-transcribe",
            "realtime_model": self.realtime_model or "gpt-realtime-2.1",
            "voice_enabled": bool(self.voice_enabled),
            "voice_reply_mode": self.voice_reply_mode,
            "voice_name": self.voice_name or "marin",
            "audio_format": self.audio_format or "opus",
            "voice_speed": float(self.voice_speed or 0.96),
            "audio_quality": self.audio_quality or "professional",
            "voice_instructions": self.voice_instructions or "",
            "max_context_messages": int(self.max_context_messages or 18),
            "max_audio_size_mb": int(self.max_audio_size_mb or 25),
            "human_takeover_minutes": int(self.human_takeover_minutes or 30),
            "ai_response_delay_ms": int(self.ai_response_delay_ms or 0),
            "auto_escalation": bool(self.auto_escalation),
            "continuous_learning_enabled": bool(self.continuous_learning_enabled),
            "learn_from_employee_replies": bool(self.learn_from_employee_replies),
            "learning_min_quality": int(self.learning_min_quality or 76),
            "system_instructions": self.system_instructions or "",
            "handoff_threshold": self.handoff_threshold,
            "max_products": self.max_products,
            "is_active": bool(self.is_active),
        }


class AISalesReplyExample(db.Model):
    """Sanitized, tenant-local examples learned from verified employee replies."""

    __tablename__ = "ai_sales_reply_example"
    __table_args__ = (
        db.UniqueConstraint("signature", name="uq_ai_sales_reply_example_signature"),
    )

    id = db.Column(db.Integer, primary_key=True)
    intent = db.Column(db.String(40), nullable=False, index=True)
    customer_example = db.Column(db.Text, nullable=False)
    employee_example = db.Column(db.Text, nullable=False)
    normalized_customer = db.Column(db.Text, nullable=False)
    keywords_json = db.Column(db.Text)
    signature = db.Column(db.String(64), nullable=False, index=True)
    quality_score = db.Column(db.Integer, default=0, nullable=False, index=True)
    occurrence_count = db.Column(db.Integer, default=1, nullable=False)
    source_conversation_id = db.Column(db.Integer, index=True)
    source_customer_message_id = db.Column(db.Integer, index=True)
    source_employee_message_id = db.Column(db.Integer, index=True)
    source_type = db.Column(db.String(30), default="employee_history", nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), index=True)
    rating_source = db.Column(db.String(40), index=True)
    approved_by_employee_id = db.Column(db.Integer, index=True)
    approved_at = db.Column(db.DateTime)
    curation_status = db.Column(db.String(20), default="pending", nullable=False, index=True)
    curation_reason = db.Column(db.String(300))
    reviewed_at = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = db.relationship("Product", lazy=True)

    def get_keywords(self) -> list[str]:
        return _loads(self.keywords_json, [])

    def set_keywords(self, values: list[str]) -> None:
        self.keywords_json = json.dumps(values or [], ensure_ascii=False)

    def to_prompt_dict(self) -> dict:
        return {
            "intent": self.intent,
            "product_id": self.product_id,
            "product_name": self.product.name if self.product else "",
            "customer": self.customer_example,
            "employee_style": self.employee_example,
        }


class AISalesProductProfile(db.Model):
    __tablename__ = "ai_sales_product_profile"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, unique=True, index=True)
    marketing_name = db.Column(db.String(200))
    aliases_json = db.Column(db.Text)
    selling_points_json = db.Column(db.Text)
    ideal_for_json = db.Column(db.Text)
    objections_json = db.Column(db.Text)
    warranty_text = db.Column(db.String(220))
    delivery_text = db.Column(db.String(220))
    colors_json = db.Column(db.Text)
    width_cm = db.Column(db.Float)
    height_cm = db.Column(db.Float)
    depth_cm = db.Column(db.Float)
    ai_notes = db.Column(db.Text)
    allow_price = db.Column(db.Boolean, default=True, nullable=False)
    allow_recommendation = db.Column(db.Boolean, default=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = db.relationship("Product", lazy=True)

    def get_aliases(self) -> list:
        return _loads(self.aliases_json, [])

    def get_selling_points(self) -> list:
        return _loads(self.selling_points_json, [])

    def get_ideal_for(self) -> list:
        return _loads(self.ideal_for_json, [])

    def get_objections(self) -> dict:
        return _loads(self.objections_json, {})

    def get_colors(self) -> list:
        return _loads(self.colors_json, [])


class AISalesKnowledgeEntry(db.Model):
    """Verified business knowledge supplied manually or through a workbook."""

    __tablename__ = "ai_sales_knowledge_entry"
    __table_args__ = (
        db.UniqueConstraint("signature", name="uq_ai_sales_knowledge_entry_signature"),
    )

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(40), default="problem_solution", nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), index=True)
    title = db.Column(db.String(220))
    problem = db.Column(db.Text, nullable=False)
    solution = db.Column(db.Text, nullable=False)
    keywords_json = db.Column(db.Text)
    diagnostic_questions_json = db.Column(db.Text)
    escalation_text = db.Column(db.Text)
    signature = db.Column(db.String(64), nullable=False, index=True)
    source_type = db.Column(db.String(30), default="manual", nullable=False, index=True)
    source_name = db.Column(db.String(255))
    source_row = db.Column(db.Integer)
    quality_score = db.Column(db.Integer, default=100, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = db.relationship("Product", lazy=True)

    def get_keywords(self) -> list[str]:
        return _loads(self.keywords_json, [])

    def set_keywords(self, values: list[str]) -> None:
        self.keywords_json = _dumps(values or [])

    def get_diagnostic_questions(self) -> list[str]:
        return _loads(self.diagnostic_questions_json, [])

    def set_diagnostic_questions(self, values: list[str]) -> None:
        self.diagnostic_questions_json = _dumps(values or [])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "product_id": self.product_id,
            "product_name": self.product.name if self.product else "",
            "title": self.title or "",
            "problem": self.problem or "",
            "solution": self.solution or "",
            "keywords": self.get_keywords(),
            "diagnostic_questions": self.get_diagnostic_questions(),
            "escalation": self.escalation_text or "",
            "source_type": self.source_type,
            "source_name": self.source_name or "",
            "source_row": self.source_row,
            "quality_score": int(self.quality_score or 0),
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_prompt_dict(self) -> dict:
        return {
            "type": self.kind,
            "product_id": self.product_id,
            "product_name": self.product.name if self.product else "",
            "problem": self.problem,
            "diagnostic_questions": self.get_diagnostic_questions(),
            "approved_solution": self.solution,
            "handoff_when": self.escalation_text or "",
        }


class AISalesLearningImport(db.Model):
    __tablename__ = "ai_sales_learning_import"

    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(255), nullable=False)
    file_hash = db.Column(db.String(64), nullable=False, index=True)
    status = db.Column(db.String(30), default="processing", nullable=False, index=True)
    product_rows = db.Column(db.Integer, default=0, nullable=False)
    problem_rows = db.Column(db.Integer, default=0, nullable=False)
    skipped_rows = db.Column(db.Integer, default=0, nullable=False)
    error_count = db.Column(db.Integer, default=0, nullable=False)
    errors_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime)

    def get_errors(self) -> list[str]:
        return _loads(self.errors_json, [])

    def set_errors(self, values: list[str]) -> None:
        self.errors_json = _dumps(values or [])

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "file_name": self.file_name,
            "status": self.status,
            "product_rows": int(self.product_rows or 0),
            "problem_rows": int(self.problem_rows or 0),
            "skipped_rows": int(self.skipped_rows or 0),
            "error_count": int(self.error_count or 0),
            "errors": self.get_errors(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class ProductMediaAsset(db.Model):
    __tablename__ = "product_media_asset"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    media_type = db.Column(db.String(30), nullable=False, index=True)
    storage_path = db.Column(db.String(600), nullable=False)
    public_url = db.Column(db.String(800))
    title = db.Column(db.String(220))
    tags_json = db.Column(db.Text)
    mime_type = db.Column(db.String(100))
    file_size = db.Column(db.Integer, default=0)
    sort_order = db.Column(db.Integer, default=0)
    ai_approved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship("Product", lazy=True)

    def get_tags(self) -> list:
        return _loads(self.tags_json, [])


class AISalesToolCall(db.Model):
    __tablename__ = "ai_sales_tool_call"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("ai_sales_conversation.id"), index=True)
    message_id = db.Column(db.Integer, db.ForeignKey("ai_sales_message.id"), index=True)
    tool_name = db.Column(db.String(120), nullable=False, index=True)
    input_json = db.Column(db.Text)
    output_json = db.Column(db.Text)
    status = db.Column(db.String(30), default="success", nullable=False)
    duration_ms = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_input(self, value) -> None:
        self.input_json = _dumps(value)

    def set_output(self, value) -> None:
        self.output_json = _dumps(value)


class AISalesUsageLog(db.Model):
    __tablename__ = "ai_sales_usage_log"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("ai_sales_conversation.id"), index=True)
    message_id = db.Column(db.Integer, db.ForeignKey("ai_sales_message.id"), index=True)
    provider = db.Column(db.String(40), default="openai", nullable=False)
    model = db.Column(db.String(100), nullable=False)
    operation = db.Column(db.String(40), nullable=False, index=True)
    input_tokens = db.Column(db.Integer, default=0)
    output_tokens = db.Column(db.Integer, default=0)
    audio_input_seconds = db.Column(db.Float, default=0)
    audio_output_seconds = db.Column(db.Float, default=0)
    image_count = db.Column(db.Integer, default=0)
    estimated_cost_micros = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
