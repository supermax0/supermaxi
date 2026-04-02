# telegram_bot/fsm_handlers.py — ربط FSM بويب هوك الوورك فلو
from __future__ import annotations

from typing import Optional

from services.session_manager import handle_message as fsm_handle_message


def process_booking_fsm_reply(
    *,
    message_text: str,
    chat_id: str,
    workflow_id: int,
    tenant_slug: Optional[str],
) -> Optional[str]:
    """
    إن وُجدت إجابة نصية من FSM يُعاد النص ليُرسل للزبون ويُتخطى مسار الـ AI.
    إن عاد None يُكمل المسار العادي (workflow).
    """
    from flask import current_app

    if not current_app.config.get("TELEGRAM_BOOKING_FSM_ENABLED"):
        return None
    text = (message_text or "").strip()
    if not text:
        return None
    return fsm_handle_message(str(chat_id), text, workflow_id, tenant_slug)
