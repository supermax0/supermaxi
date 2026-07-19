"""Schema and default-data guard for deployments without migrations."""
from __future__ import annotations

import secrets

from sqlalchemy import inspect, text

from extensions import db
from .models import (
    AISalesAgentProfile,
    AISalesChannelAccount,
    AISalesCall,
    AISalesConversation,
    AISalesConversationRead,
    AISalesLead,
    AISalesKnowledgeEntry,
    AISalesLearningImport,
    AISalesMessage,
    AISalesProductProfile,
    AISalesReplyExample,
    AISalesSocialComment,
    AISalesSocialPost,
    AISalesToolCall,
    AISalesUsageLog,
    ProductMediaAsset,
)


TABLES = (
    AISalesChannelAccount.__table__,
    AISalesConversation.__table__,
    AISalesMessage.__table__,
    AISalesCall.__table__,
    AISalesConversationRead.__table__,
    AISalesLead.__table__,
    AISalesAgentProfile.__table__,
    AISalesReplyExample.__table__,
    AISalesSocialPost.__table__,
    AISalesSocialComment.__table__,
    AISalesKnowledgeEntry.__table__,
    AISalesLearningImport.__table__,
    AISalesProductProfile.__table__,
    ProductMediaAsset.__table__,
    AISalesToolCall.__table__,
    AISalesUsageLog.__table__,
)


def ensure_ai_sales_schema() -> None:
    bind = db.session.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)
    inspector = inspect(bind)
    changed = False
    channel_columns = {column["name"] for column in inspector.get_columns("ai_sales_channel_account")}
    additive_columns = {
        "parent_channel_id": "INTEGER",
        "external_account_id": "VARCHAR(128)",
        "page_id": "VARCHAR(128)",
        "platform_username": "VARCHAR(150)",
        "profile_picture_url": "VARCHAR(800)",
        "reply_mode": "VARCHAR(20) NOT NULL DEFAULT 'ai'",
        "comments_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
        "comments_reply_mode": "VARCHAR(20) NOT NULL DEFAULT 'inbox'",
        "comments_private_reply": "BOOLEAN NOT NULL DEFAULT TRUE",
        "comments_public_text": "VARCHAR(300) NOT NULL DEFAULT 'تم الرد على الخاص'",
        "default_employee_id": "INTEGER",
        "last_sync_at": "TIMESTAMP",
        "sync_blocked_until": "TIMESTAMP",
        "calling_status": "VARCHAR(30) NOT NULL DEFAULT 'unknown'",
        "calling_settings_json": "TEXT",
        "calling_last_checked_at": "TIMESTAMP",
    }
    for name, definition in additive_columns.items():
        if name not in channel_columns:
            db.session.execute(text(f"ALTER TABLE ai_sales_channel_account ADD COLUMN {name} {definition}"))
    conversation_columns = {column["name"] for column in inspector.get_columns("ai_sales_conversation")}
    conversation_additive_columns = {
        "contact_profile_picture_url": "VARCHAR(800)",
        "ai_paused_until": "TIMESTAMP",
        "handoff_reason": "VARCHAR(300)",
    }
    for name, definition in conversation_additive_columns.items():
        if name not in conversation_columns:
            db.session.execute(text(f"ALTER TABLE ai_sales_conversation ADD COLUMN {name} {definition}"))
    profile_columns = {column["name"] for column in inspector.get_columns("ai_sales_agent_profile")}
    profile_additive_columns = {
        "intelligence_level": "VARCHAR(30) NOT NULL DEFAULT 'expert'",
        "persuasion_style": "VARCHAR(30) NOT NULL DEFAULT 'balanced'",
        "tts_model": "VARCHAR(100) NOT NULL DEFAULT 'gpt-4o-mini-tts'",
        "transcription_model": "VARCHAR(100) NOT NULL DEFAULT 'gpt-4o-mini-transcribe'",
        "realtime_model": "VARCHAR(100) NOT NULL DEFAULT 'gpt-realtime-2.1'",
        "audio_format": "VARCHAR(20) NOT NULL DEFAULT 'opus'",
        "voice_speed": "FLOAT NOT NULL DEFAULT 0.96",
        "audio_quality": "VARCHAR(30) NOT NULL DEFAULT 'professional'",
        "voice_instructions": "TEXT",
        "max_context_messages": "INTEGER NOT NULL DEFAULT 18",
        "max_audio_size_mb": "INTEGER NOT NULL DEFAULT 25",
        "human_takeover_minutes": "INTEGER NOT NULL DEFAULT 30",
        "ai_response_delay_ms": "INTEGER NOT NULL DEFAULT 0",
        "auto_escalation": "BOOLEAN NOT NULL DEFAULT TRUE",
        "continuous_learning_enabled": "BOOLEAN NOT NULL DEFAULT TRUE",
        "learn_from_employee_replies": "BOOLEAN NOT NULL DEFAULT TRUE",
        "learning_min_quality": "INTEGER NOT NULL DEFAULT 76",
    }
    for name, definition in profile_additive_columns.items():
        if name not in profile_columns:
            db.session.execute(text(f"ALTER TABLE ai_sales_agent_profile ADD COLUMN {name} {definition}"))
    product_profile_columns = {column["name"] for column in inspector.get_columns("ai_sales_product_profile")}
    product_profile_additive_columns = {
        "colors_json": "TEXT",
        "width_cm": "FLOAT",
        "height_cm": "FLOAT",
        "depth_cm": "FLOAT",
    }
    for name, definition in product_profile_additive_columns.items():
        if name not in product_profile_columns:
            db.session.execute(text(f"ALTER TABLE ai_sales_product_profile ADD COLUMN {name} {definition}"))
    message_columns = {column["name"] for column in inspector.get_columns("ai_sales_message")}
    message_additive_columns = {
        "transcription_model": "VARCHAR(100)",
        "transcription_status": "VARCHAR(30)",
        "transcription_error": "TEXT",
    }
    for name, definition in message_additive_columns.items():
        if name not in message_columns:
            db.session.execute(text(f"ALTER TABLE ai_sales_message ADD COLUMN {name} {definition}"))
    reply_example_columns = {column["name"] for column in inspector.get_columns("ai_sales_reply_example")}
    reply_example_additive_columns = {
        "curation_status": "VARCHAR(20) NOT NULL DEFAULT 'pending'",
        "curation_reason": "VARCHAR(300)",
        "reviewed_at": "TIMESTAMP",
        "product_id": "INTEGER",
        "rating_source": "VARCHAR(40)",
        "approved_by_employee_id": "INTEGER",
        "approved_at": "TIMESTAMP",
    }
    for name, definition in reply_example_additive_columns.items():
        if name not in reply_example_columns:
            db.session.execute(text(f"ALTER TABLE ai_sales_reply_example ADD COLUMN {name} {definition}"))
    archived_old_examples = AISalesReplyExample.query.filter(
        AISalesReplyExample.rating_source.is_(None),
        AISalesReplyExample.is_active.is_(True),
        AISalesReplyExample.curation_status != "archived_old_ai",
    ).update(
        {
            "is_active": False,
            "curation_status": "archived_old_ai",
            "curation_reason": "Archived when Sales AI was reset to training-only mode.",
        },
        synchronize_session=False,
    )
    if archived_old_examples:
        changed = True
    db.session.flush()
    if not AISalesAgentProfile.query.first():
        db.session.add(AISalesAgentProfile())
        changed = True
    channels_without_verify = AISalesChannelAccount.query.filter(
        (AISalesChannelAccount.verify_token_encrypted.is_(None))
        | (AISalesChannelAccount.verify_token_encrypted == "")
    ).all()
    if channels_without_verify:
        from .security import encrypt_secret

        for channel in channels_without_verify:
            channel.verify_token_encrypted = encrypt_secret(secrets.token_urlsafe(24))
        changed = True
    if changed:
        db.session.commit()
