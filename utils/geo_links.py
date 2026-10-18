"""Parse a customer pin from coordinates or a map link."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse


@dataclass
class ParsedLocation:
    lat: float | None = None
    lng: float | None = None
    url: str | None = None
    label: str | None = None
    error: str | None = None


_COORD_RE = re.compile(
    r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)\s*$"
)
_AT_RE = re.compile(r"@(-?\d{1,3}(?:\.\d+)?),(-?\d{1,3}(?:\.\d+)?)")
_D3_RE = re.compile(r"!3d(-?\d{1,3}(?:\.\d+)?)!4d(-?\d{1,3}(?:\.\d+)?)")


def _valid_pair(lat: float, lng: float) -> bool:
    return -90 <= lat <= 90 and -180 <= lng <= 180


def _pair_from_text(text: str) -> tuple[float, float] | None:
    match = _COORD_RE.match(text or "")
    if not match:
        return None
    lat, lng = float(match.group(1)), float(match.group(2))
    if not _valid_pair(lat, lng):
        return None
    return lat, lng


def parse_location(raw: str | None, label: str | None = None) -> ParsedLocation:
    text = (raw or "").strip()
    clean_label = (label or "").strip()[:120] or None
    if not text:
        return ParsedLocation(label=clean_label)

    pair = _pair_from_text(text)
    if pair:
        return ParsedLocation(lat=pair[0], lng=pair[1], url=text[:500], label=clean_label)

    if text.lower().startswith("geo:"):
        body = text[4:]
        coords, _, query = body.partition("?")
        found = _pair_from_text(coords.replace(";", ","))
        if not found and query:
            params = parse_qs(query)
            q = unquote((params.get("q") or [""])[0])
            found = _pair_from_text(q)
        if not found:
            return ParsedLocation(error="تعذر قراءة إحداثيات الرابط", label=clean_label)
        return ParsedLocation(lat=found[0], lng=found[1], url=text[:500], label=clean_label)

    if not text.lower().startswith(("http://", "https://")):
        return ParsedLocation(error="الرابط يجب أن يبدأ بـ http أو https أو يكون إحداثيات", label=clean_label)

    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if host in {"maps.app.goo.gl", "goo.gl", "maps.app.goo.gl."} or host.endswith(".goo.gl"):
        return ParsedLocation(url=text[:500], label=clean_label)

    query = parse_qs(parsed.query)
    candidates: list[str] = []
    for key in ("q", "query", "ll", "destination"):
        candidates.extend(query.get(key) or [])
    if "mlat" in query and "mlon" in query:
        candidates.append(f"{query['mlat'][0]},{query['mlon'][0]}")
    fragment = parsed.fragment or ""
    if fragment.startswith("map="):
        parts = fragment.split("/")
        if len(parts) >= 3:
            candidates.append(f"{parts[1]},{parts[2]}")
    decoded_path = unquote(parsed.path or "")
    candidates.append(decoded_path)
    candidates.append(unquote(parsed.query or ""))

    for candidate in candidates:
        found = _pair_from_text(candidate)
        if not found:
            at = _AT_RE.search(candidate)
            if at:
                lat, lng = float(at.group(1)), float(at.group(2))
                found = (lat, lng) if _valid_pair(lat, lng) else None
        if not found:
            d3 = _D3_RE.search(candidate)
            if d3:
                lat, lng = float(d3.group(1)), float(d3.group(2))
                found = (lat, lng) if _valid_pair(lat, lng) else None
        if found:
            return ParsedLocation(lat=found[0], lng=found[1], url=text[:500], label=clean_label)

    return ParsedLocation(url=text[:500], label=clean_label)


def apply_invoice_location(invoice, data: dict | None) -> str | None:
    """Write location columns when the payload includes them. Returns an error string."""
    if not isinstance(data, dict):
        return None
    if not any(key in data for key in ("location_url", "location_lat", "location_lng", "location_label")):
        return None

    raw = str(data.get("location_url") or "").strip()
    label = data.get("location_label")
    parsed = parse_location(raw, None if label is None else str(label))
    if parsed.error:
        return parsed.error

    lat = data.get("location_lat")
    lng = data.get("location_lng")
    try:
        lat_f = float(lat) if lat not in (None, "") else None
        lng_f = float(lng) if lng not in (None, "") else None
    except (TypeError, ValueError):
        lat_f = lng_f = None
    if lat_f is not None and lng_f is not None and _valid_pair(lat_f, lng_f):
        invoice.location_lat = lat_f
        invoice.location_lng = lng_f
    elif parsed.lat is not None and parsed.lng is not None:
        invoice.location_lat = parsed.lat
        invoice.location_lng = parsed.lng
    else:
        invoice.location_lat = None
        invoice.location_lng = None
    invoice.location_url = parsed.url
    if "location_label" in data:
        invoice.location_label = parsed.label
    return None
