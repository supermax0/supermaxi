"""Create store_api_key on tenant databases."""

from __future__ import annotations

from sqlalchemy import inspect


def ensure_store_api_schema() -> None:
    from extensions import db
    from modules.store_api.models import StoreApiKey

    bind = db.session.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(StoreApiKey.__tablename__):
        return
    StoreApiKey.__table__.create(bind=bind, checkfirst=True)
