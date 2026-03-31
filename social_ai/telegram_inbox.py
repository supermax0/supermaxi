# social_ai/telegram_inbox.py — تسجيل رسائل تيليجرام واستخراج توكن البوت من الرسم
from __future__ import annotations

from typing import Any

from flask import current_app

from extensions import db
from sqlalchemy import inspect, text


def ensure_telegram_inbox_table_for_current_bind() -> None:
    """
    ينشئ جدول telegram_inbox_messages على **نفس قاعدة البيانات** التي تستخدمها الجلسة الحالية.
    مهم عند تعدد المستأجرين (كل شركة ملف SQLite منفصل): لا تستخدم db.engine وحده
    لأنه يشير غالباً للقاعدة الرئيسية بينما الاستعلامات تذهب لقاعدة المستأجر.
    """
    try:
        from models.telegram_inbox_message import TelegramInboxMessage

        bind = db.session.get_bind(mapper=TelegramInboxMessage.__mapper__)
        TelegramInboxMessage.__table__.create(bind=bind, checkfirst=True)

        # Migration-safe: add channel column if table existed before this update.
        insp = inspect(bind)
        cols = {c.get("name") for c in insp.get_columns(TelegramInboxMessage.__tablename__)}
        if "channel" not in cols:
            with bind.begin() as conn:
                conn.execute(text("ALTER TABLE telegram_inbox_messages ADD COLUMN channel VARCHAR(20) DEFAULT 'telegram'"))
    except Exception as exc:
        current_app.logger.warning("telegram_inbox ensure table: %s", exc)


def record_telegram_inbox_message(
    tenant_slug: str | None,
    workflow_id: int,
    chat_id: str,
    role: str,
    body: str,
) -> None:
    """يحفظ رسالة في جدول صندوق المحادثات؛ لا يرفع استثناءً إذا فشل الحفظ."""
    record_inbox_message(
        tenant_slug=tenant_slug,
        workflow_id=workflow_id,
        channel="telegram",
        chat_id=chat_id,
        role=role,
        body=body,
    )


def record_inbox_message(
    tenant_slug: str | None,
    workflow_id: int,
    channel: str,
    chat_id: str,
    role: str,
    body: str,
) -> None:
    """Generic inbox recorder for telegram/whatsapp."""
    if not workflow_id or not chat_id or not (body or "").strip():
        return
    role = (role or "user").strip().lower()
    if role not in ("user", "bot", "operator"):
        role = "user"
    channel = (channel or "telegram").strip().lower()
    if channel not in ("telegram", "whatsapp"):
        channel = "telegram"
    try:
        ensure_telegram_inbox_table_for_current_bind()
        from models.telegram_inbox_message import TelegramInboxMessage

        row = TelegramInboxMessage(
            tenant_slug=(tenant_slug or None),
            workflow_id=int(workflow_id),
            channel=channel,
            chat_id=str(chat_id)[:64],
            role=role[:20],
            body=(body or "")[:12000],
        )
        db.session.add(row)
        db.session.commit()
    except Exception as exc:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.warning(
            "inbox record skipped (tenant=%s workflow_id=%s channel=%s chat_id=%s role=%s): %s",
            tenant_slug,
            workflow_id,
            channel,
            (chat_id or "")[:24],
            role,
            exc,
            exc_info=True,
        )


def extract_telegram_bot_token_from_workflow_graph(graph: dict[str, Any] | None) -> str:
    """يقرأ أول bot_token من عقدة telegram_listener في الرسم."""
    if not isinstance(graph, dict):
        return ""
    for n in graph.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        if (n.get("type") or "") != "telegram_listener":
            continue
        tok = ((n.get("data") or {}).get("bot_token") or "").strip()
        if tok:
            return tok
    return ""


def extract_whatsapp_credentials_from_workflow_graph(graph: dict[str, Any] | None) -> tuple[str, str]:
    """Read first (token, phone_id) from whatsapp_listener node in graph."""
    if not isinstance(graph, dict):
        return "", ""
    for n in graph.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        if (n.get("type") or "") != "whatsapp_listener":
            continue
        data = n.get("data") or {}
        token = str(data.get("access_token") or "").strip()
        phone_id = str(data.get("phone_id") or "").strip()
        if token and phone_id:
            return token, phone_id
    return "", ""
