"""Backward-compatible, per-tenant schema bootstrap."""
from __future__ import annotations

from flask import g
import os

from extensions import db
from modules.finora_ai.models import AI_TABLES, FinoraAISettings


def ensure_finora_ai_schema() -> None:
    tenant = getattr(g, "tenant", None)
    if not tenant:
        return
    db.Model.metadata.create_all(bind=db.session.get_bind(), tables=list(AI_TABLES), checkfirst=True)
    if FinoraAISettings.query.first() is None:
        provider = "openai" if os.environ.get("OPENAI_API_KEY") else "builtin"
        settings = FinoraAISettings(provider=provider, model="gpt-4.1-mini" if provider == "openai" else None)
        settings.set_flags({})
        db.session.add(settings)
        db.session.commit()
