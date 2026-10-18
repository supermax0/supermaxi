"""Secret encryption and WhatsApp webhook signature verification."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import time

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


META_APP_SECRET_RE = re.compile(r"^[0-9a-f]{32}$")


def meta_app_secret_problem(app_secret: str | None) -> str | None:
    """``None`` when the secret is usable; otherwise ``missing`` or ``malformed`` (Meta app secrets are 32 hex chars)."""
    if not app_secret:
        return "missing"
    if not META_APP_SECRET_RE.fullmatch(app_secret.strip().lower()):
        return "malformed"
    return None


def verify_meta_signature_strict(raw_body: bytes, signature_header: str | None, app_secret: str | None) -> bool:
    """Fail-closed variant: no secret (or an undecryptable one) never verifies."""
    if meta_app_secret_problem(app_secret):
        return False
    return verify_meta_signature(raw_body, signature_header, str(app_secret))


def verify_tiktok_signature(raw_body: bytes, signature_header: str | None, app_secret: str, *, max_age_seconds: int = 300) -> bool:
    """Verify TikTok's `Tiktok-Signature: t=<unix_ts>,s=<hex_hmac_sha256>` header.

    Algorithm per TikTok's Business Messaging webhook docs: HMAC-SHA256 over
    f"{timestamp}.{raw_body}" using the app secret, hex-encoded. Uses the raw
    bytes as received (not a re-serialized copy) since re-serializing JSON can
    silently change key order/whitespace and break the signature.
    """
    if not app_secret:
        return True
    header = (signature_header or "").strip()
    parts = dict(item.split("=", 1) for item in header.split(",") if "=" in item)
    timestamp, signature = parts.get("t", ""), parts.get("s", "")
    if not timestamp or not signature:
        return False
    try:
        age = abs(int(time.time()) - int(timestamp))
    except ValueError:
        return False
    if age > max_age_seconds:
        return False
    signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
    expected = hmac.new(app_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)
