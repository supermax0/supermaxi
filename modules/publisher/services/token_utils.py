"""
token_utils.py
--------------
Fernet-based encryption/decryption for Facebook page access tokens.

Set FERNET_KEY in .env:
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import os
import logging

logger = logging.getLogger("publisher")

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.environ.get("FERNET_KEY", "").strip()
    if not key:
        logger.warning("FERNET_KEY not set — tokens stored as plain text (dev mode)")
        return None
    try:
        from cryptography.fernet import Fernet
        _fernet = Fernet(key.encode())
        return _fernet
    except Exception as exc:
        logger.error("Fernet init error: %s", exc)
        return None


def encrypt_token(token: str) -> str:
    """Encrypt a page access token. Returns cipher text (str)."""
    f = _get_fernet()
    if not f:
        return token  # plain text fallback
    return f.encrypt(token.encode()).decode()


def decrypt_token(cipher: str) -> str:
    """Decrypt a stored page access token. Returns plain text."""
    f = _get_fernet()
    if not f:
        return cipher  # plain text fallback
    try:
        return f.decrypt(cipher.encode()).decode()
    except Exception:
        # May already be plain text (migration from unencrypted)
        return cipher
