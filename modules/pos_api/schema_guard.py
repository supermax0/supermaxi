"""Create pos_api_key on tenant databases."""
from __future__ import annotations

from sqlalchemy import inspect


def ensure_pos_api_schema() -> None:
    from extensions import db
    from modules.pos_api.models import PosApiKey

    bind = db.session.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(PosApiKey.__tablename__):
        return
    PosApiKey.__table__.create(bind=bind, checkfirst=True)
