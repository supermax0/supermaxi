"""Pluggable SMS OTP providers for mobile auth."""
from __future__ import annotations

import logging
import os
from typing import Protocol

from flask import current_app, has_app_context

logger = logging.getLogger(__name__)


class SmsProvider(Protocol):
    def send_otp(self, phone: str, code: str) -> bool: ...


class LogSmsProvider:
    """Dev/default — logs OTP (never use as sole channel in production)."""

    def send_otp(self, phone: str, code: str) -> bool:
        logger.info("mobile_otp_sms provider=log phone=%s code=%s", phone, code)
        return True


class UnavailableSmsProvider:
    """Fail closed when production SMS delivery is not configured."""

    def send_otp(self, phone: str, code: str) -> bool:
        logger.error(
            "mobile_otp_sms unavailable: configure MOBILE_SMS_WEBHOOK_URL"
        )
        return False


class HttpSmsProvider:
    """Generic HTTP SMS gateway via MOBILE_SMS_WEBHOOK_URL."""

    def __init__(self, webhook_url: str, api_key: str | None = None):
        self.webhook_url = webhook_url
        self.api_key = api_key

    def send_otp(self, phone: str, code: str) -> bool:
        import requests

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "phone": phone,
            "message": f"رمز التحقق من Finora: {code}",
            "code": code,
        }
        try:
            resp = requests.post(
                self.webhook_url, json=payload, headers=headers, timeout=12
            )
            ok = 200 <= resp.status_code < 300
            if not ok:
                logger.warning(
                    "mobile_otp_sms provider=http status=%s body=%s",
                    resp.status_code,
                    (resp.text or "")[:200],
                )
            return ok
        except Exception:
            logger.exception("mobile_otp_sms provider=http failed")
            return False


def get_sms_provider() -> SmsProvider:
    url = (os.environ.get("MOBILE_SMS_WEBHOOK_URL") or "").strip()
    if url:
        return HttpSmsProvider(
            url, api_key=(os.environ.get("MOBILE_SMS_API_KEY") or "").strip() or None
        )
    allow_log = (os.environ.get("MOBILE_ALLOW_LOG_SMS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if has_app_context():
        allow_log = allow_log or bool(current_app.testing or current_app.debug)
    return LogSmsProvider() if allow_log else UnavailableSmsProvider()


def deliver_otp(phone: str, code: str) -> bool:
    return get_sms_provider().send_otp(phone, code)
