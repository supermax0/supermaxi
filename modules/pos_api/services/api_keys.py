"""Create, hash, and resolve long-lived POS API keys."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from extensions import db
from modules.pos_api.models import PosApiKey
from modules.pos_api.schema_guard import ensure_pos_api_schema

TOKEN_PREFIX = "finora_pos_"


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_api_key(raw: str) -> tuple[str, str] | None:
    token = (raw or "").strip()
    if not token.startswith(TOKEN_PREFIX):
        return None
    rest = token[len(TOKEN_PREFIX) :]
    if "." not in rest:
        return None
    slug, secret = rest.split(".", 1)
    slug = slug.strip().lower()
    if not slug or not secret:
        return None
    return slug, token


def issue_api_key(*, employee_id: int, tenant_slug: str, name: str | None = None) -> tuple[str, PosApiKey]:
    ensure_pos_api_schema()
    secret = secrets.token_urlsafe(32)
    raw = f"{TOKEN_PREFIX}{tenant_slug}.{secret}"
    row = PosApiKey(
        employee_id=int(employee_id),
        name=(name or "Core Assistant").strip() or "Core Assistant",
        token_hash=hash_token(raw),
        token_prefix=raw[:28],
    )
    db.session.add(row)
    db.session.commit()
    return raw, row


def find_api_key(raw: str) -> PosApiKey | None:
    ensure_pos_api_schema()
    parsed = parse_api_key(raw)
    if not parsed:
        return None
    row = PosApiKey.query.filter_by(token_hash=hash_token(raw), revoked_at=None).first()
    if row is None:
        return None
    row.last_used_at = datetime.utcnow()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return row


def list_api_keys() -> list[PosApiKey]:
    ensure_pos_api_schema()
    return (
        PosApiKey.query.filter(PosApiKey.revoked_at.is_(None))
        .order_by(PosApiKey.created_at.desc())
        .all()
    )


def revoke_api_key(key_id: int) -> bool:
    ensure_pos_api_schema()
    row = db.session.get(PosApiKey, int(key_id))
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.utcnow()
    db.session.commit()
    return True


def serialize_key(row: PosApiKey) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "token_prefix": row.token_prefix + "…",
        "employee_id": row.employee_id,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        "last_used_at": row.last_used_at.isoformat() + "Z" if row.last_used_at else None,
    }
