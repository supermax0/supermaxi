"""Outbound delivery for manual (human) replies.

Production: the existing ai_sales Meta client (page-scoped token, server-side only).
Development: ``FINORA_CORE_DEV_LOOPBACK=1`` marks messages as sent without calling Meta, so the desktop flow can be
exercised locally. It is refused outside development and surfaced in ``/status`` so it can never look like real delivery.
"""
from __future__ import annotations

import logging
import os
import uuid

from modules.ai_sales.channels import channel_client, outbound_message_id
from modules.ai_sales.meta_reliability import require_message_id
from modules.ai_sales.models import AISalesConversation

from .store import environment

logger = logging.getLogger(__name__)


def loopback_enabled() -> bool:
    return os.environ.get("FINORA_CORE_DEV_LOOPBACK") == "1" and environment() == "development"


def send_text(conversation: AISalesConversation, text: str) -> str:
    """Returns the provider message id. Raises on provider failure; a success without a message id is a failure too
    (``meta_reliability.require_message_id``)."""
    if loopback_enabled():
        logger.info("finora_core dev loopback: message for conversation %s not sent to Meta", conversation.id)
        return f"loopback-{uuid.uuid4().hex[:12]}"
    recipient = conversation.external_contact_id
    body = channel_client(conversation.channel).send_text(recipient, text)
    return require_message_id(outbound_message_id(body))


def warn_if_misconfigured() -> None:
    if os.environ.get("FINORA_CORE_DEV_LOOPBACK") == "1" and environment() != "development":
        logger.error("FINORA_CORE_DEV_LOOPBACK=1 is ignored outside development (FINORA_ENV=%s)", environment())
