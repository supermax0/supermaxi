"""Kill switch check used by the ai_sales worker (spec §71): stops new automatic replies for the FINORA house
tenant while inbound messages keep being collected."""
from __future__ import annotations

import logging

from flask import g

from .store import automation_paused, core_session, house_slug

logger = logging.getLogger(__name__)


def automation_paused_for_current_tenant() -> bool:
    slug = house_slug()
    if not slug or getattr(g, "tenant", None) != slug:
        return False
    try:
        with core_session() as s:
            return automation_paused(s)
    except Exception:
        # Fail closed: if we cannot read the switch, do not let the AI act on FINORA's own customers.
        logger.exception("finora_core kill switch unreadable; holding automatic reply")
        return True
