# social_ai/telegram_inbox.py — تسجيل رسائل تيليجرام واستخراج توكن البوت من الرسم
from __future__ import annotations

from typing import Any

from flask import current_app

from extensions import db


def record_telegram_inbox_message(
    tenant_slug: str | None,
    workflow_id: int,
    chat_id: str,
    role: str,
    body: str,
) -> None:
    """يحفظ رسالة في جدول صندوق المحادثات؛ لا يرفع استثناءً إذا فشل الحفظ."""
    if not workflow_id or not chat_id or not (body or "").strip():
        return
    role = (role or "user").strip().lower()
    if role not in ("user", "bot", "operator"):
        role = "user"
    try:
        from models.telegram_inbox_message import TelegramInboxMessage

        row = TelegramInboxMessage(
            tenant_slug=(tenant_slug or None),
            workflow_id=int(workflow_id),
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
        current_app.logger.warning("telegram inbox record skipped: %s", exc)


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
