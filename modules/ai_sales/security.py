"""Secret encryption and WhatsApp webhook signature verification."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _fernet() -> Fernet:
    configured = (os.environ.get("AI_SALES_ENCRYPTION_KEY") or "").strip()
    if configured:
        try:
            key = configured.encode("ascii")
            Fernet(key)
        except (ValueError, TypeError):
            key = base64.urlsafe_b64encode(hashlib.sha256(configured.encode("utf-8")).digest())
    else:
        secret = str(current_app.config.get("SECRET_KEY") or "finora-ai-sales-local-key")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str | None) -> str:
    raw = (value or "").strip()
    return _fernet().encrypt(raw.encode("utf-8")).decode("ascii") if raw else ""


def decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def verify_meta_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    if not app_secret:
        return True
    header = (signature_header or "").strip()
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[7:], expected)
