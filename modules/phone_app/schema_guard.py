"""Ensure phone_app schema via versioned migrations (not bare create_all)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SCHEMA_READY: set[str] = set()


def ensure_phone_app_schema() -> None:
    from flask import g

    from modules.phone_app.migrations import ensure_phone_app_schema as run_migrations

    slug = getattr(g, "tenant", None) or "_core"
    if slug in _SCHEMA_READY:
        return
    try:
        version = run_migrations()
        _SCHEMA_READY.add(slug)
        logger.debug("phone_app schema v%s ready for tenant=%s", version, slug)
    except Exception:
        logger.exception("phone_app migration failed for tenant=%s", slug)
        raise
