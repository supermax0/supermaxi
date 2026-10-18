"""Lazy, idempotent creation of the tutor tables in the active tenant DB."""
from __future__ import annotations

from flask import g

from sqlalchemy import inspect, text

from extensions import db
from modules.ai_tutor.models import AI_TUTOR_MODELS

_ensured: set[tuple] = set()
# Columns added after the first release; created tenant DBs get them lazily.
ADDITIVE_COLUMNS = ("parent_tutorial_id", "parent_step_id")


def ensure_ai_tutor_schema() -> None:
    engine = db.session.get_bind()
    key = (id(engine), getattr(g, "tenant", None))
    if key in _ensured:
        return
    db.metadata.create_all(bind=engine, tables=[m.__table__ for m in AI_TUTOR_MODELS], checkfirst=True)
    existing = {c["name"] for c in inspect(engine).get_columns("user_training_progress")}
    with engine.begin() as connection:
        for column in ADDITIVE_COLUMNS:
            if column not in existing:
                connection.execute(text(f'ALTER TABLE "user_training_progress" ADD COLUMN "{column}" VARCHAR(80)'))
    _ensured.add(key)
