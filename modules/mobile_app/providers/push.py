"""Pluggable push notification providers."""
from __future__ import annotations

import logging
import os
from typing import Protocol

logger = logging.getLogger(__name__)


class PushProvider(Protocol):
    def send(
        self,
        *,
        token: str,
        title: str,
        body: str,
        data: dict | None = None,
    ) -> bool: ...


class LogPushProvider:
    def send(self, *, token: str, title: str, body: str, data: dict | None = None) -> bool:
        logger.info(
            "mobile_push provider=log token=%s… title=%s",
            (token or "")[:12],
            title,
        )
        return True


class HttpPushProvider:
    """Generic webhook (FCM proxy / OneSignal / custom) via MOBILE_PUSH_WEBHOOK_URL."""

    def __init__(self, webhook_url: str, api_key: str | None = None):
        self.webhook_url = webhook_url
        self.api_key = api_key

    def send(self, *, token: str, title: str, body: str, data: dict | None = None) -> bool:
        import requests

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "token": token,
            "title": title,
            "body": body,
            "data": data or {},
        }
        try:
            resp = requests.post(
                self.webhook_url, json=payload, headers=headers, timeout=12
            )
            return 200 <= resp.status_code < 300
        except Exception:
            logger.exception("mobile_push provider=http failed")
            return False


def get_push_provider() -> PushProvider:
    url = (os.environ.get("MOBILE_PUSH_WEBHOOK_URL") or "").strip()
    if url:
        return HttpPushProvider(
            url, api_key=(os.environ.get("MOBILE_PUSH_API_KEY") or "").strip() or None
        )
    return LogPushProvider()


def send_push(*, token: str, title: str, body: str, data: dict | None = None) -> bool:
    if not token:
        return False
    return get_push_provider().send(token=token, title=title, body=body, data=data)
