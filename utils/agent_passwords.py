"""Delivery agent password hashing helpers."""

from werkzeug.security import check_password_hash, generate_password_hash


def hash_agent_password(password: str) -> str:
    return generate_password_hash(str(password or "").strip())


def verify_agent_password(stored: str | None, provided: str) -> bool:
    raw_stored = str(stored or "")
    raw_provided = str(provided or "")
    if not raw_stored or not raw_provided:
        return False
    if raw_stored.startswith("pbkdf2:") or raw_stored.startswith("scrypt:"):
        return check_password_hash(raw_stored, raw_provided)
    return raw_stored == raw_provided


def needs_password_rehash(stored: str | None) -> bool:
    raw = str(stored or "")
    return bool(raw) and not (raw.startswith("pbkdf2:") or raw.startswith("scrypt:"))
