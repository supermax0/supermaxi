"""Safe URL extraction and compact preview metadata for sales conversations."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit


_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,،؛;:!?؟)]}»"
_MAP_HOSTS = {
    "maps.app.goo.gl",
    "maps.google.com",
    "maps.apple.com",
    "goo.gl",
    "waze.com",
    "www.waze.com",
}


def _clean_url(value: str) -> str:
    return str(value or "").strip().rstrip(_TRAILING_PUNCTUATION)


def _is_map_url(host: str, path: str) -> bool:
    host = (host or "").lower()
    path = (path or "").lower()
    return bool(
        host in _MAP_HOSTS
        or (host.endswith(".google.com") and path.startswith("/maps"))
        or (host.startswith("maps.google.") and len(host) > len("maps.google."))
        or (host.endswith("waze.com") and ("/live-map" in path or "/ul" in path))
    )


def _coordinates(url: str) -> tuple[float | None, float | None]:
    decoded = unquote(url)
    match = re.search(r"@(-?\d{1,3}(?:\.\d+)?),(-?\d{1,3}(?:\.\d+)?)", decoded)
    if not match:
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        for key in ("q", "query", "ll", "daddr", "destination"):
            raw = str((query.get(key) or [""])[0])
            match = re.search(r"(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)", raw)
            if match:
                break
    if not match:
        return None, None
    latitude, longitude = float(match.group(1)), float(match.group(2))
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None, None
    return latitude, longitude


def extract_link_previews(text: str, *, max_links: int = 5) -> list[dict[str, Any]]:
    """Return display-only metadata without fetching untrusted remote pages."""
    previews: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _URL_RE.finditer(str(text or "")):
        url = _clean_url(match.group(0))
        if not url or url in seen:
            continue
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            continue
        seen.add(url)
        host = parsed.hostname.lower()
        display_host = host[4:] if host.startswith("www.") else host
        is_map = _is_map_url(host, parsed.path)
        latitude, longitude = _coordinates(url) if is_map else (None, None)
        preview: dict[str, Any] = {
            "url": url,
            "type": "map" if is_map else "link",
            "title": "موقع على الخريطة" if is_map else display_host,
            "domain": display_host,
            "description": "فتح موقع التوصيل" if is_map else "فتح الرابط",
        }
        if latitude is not None and longitude is not None:
            preview["latitude"] = latitude
            preview["longitude"] = longitude
        previews.append(preview)
        if len(previews) >= max(1, int(max_links)):
            break
    return previews


def first_map_preview(previews: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    return next((row for row in previews or [] if row.get("type") == "map" and row.get("url")), None)
