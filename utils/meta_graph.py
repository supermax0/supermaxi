"""Shared Meta Graph API version used by Facebook integrations.

Keep the default on a supported, stable Graph release.  Deployments can pin a
different supported release with ``FACEBOOK_API_VERSION`` without editing each
Facebook feature separately.
"""
from __future__ import annotations

import os
import re


DEFAULT_GRAPH_API_VERSION = "v25.0"
_VERSION_RE = re.compile(r"^v\d+\.\d+$")


def graph_api_version() -> str:
    value = str(os.environ.get("FACEBOOK_API_VERSION") or DEFAULT_GRAPH_API_VERSION).strip()
    return value if _VERSION_RE.fullmatch(value) else DEFAULT_GRAPH_API_VERSION


GRAPH_API_VERSION = graph_api_version()
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
