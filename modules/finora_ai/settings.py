"""Server-side provider settings and secret encryption."""
from __future__ import annotations

import base64
import hashlib
import os

from flask import current_app

from modules.finora_ai.models import FinoraAISettings


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError("cryptography is required to store AI provider secrets") from exc
    source = str(current_app.config.get("FINORA_AI_ENCRYPTION_KEY") or current_app.secret_key or os.environ.get("SECRET_KEY") or "")
    if not source:
        raise RuntimeError("Configure FINORA_AI_ENCRYPTION_KEY before storing provider secrets")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(source.encode("utf-8")).digest()))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    return _fernet().decrypt(value.encode("ascii")).decode("utf-8")


def current_settings() -> FinoraAISettings:
    return FinoraAISettings.query.first() or FinoraAISettings()
