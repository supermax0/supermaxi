"""Unit tests for call recording upload constraints."""

from __future__ import annotations

from modules.phone_app.api.v1.recordings import (
    ALLOWED_EXTENSIONS,
    MAX_RECORDING_BYTES,
    MIME_BY_EXT,
)


def test_recording_extensions_cover_xiaomi_formats():
    # MIUI/HyperOS call recorder produces mp3 / m4a / aac.
    for ext in ("mp3", "m4a", "aac", "amr", "wav"):
        assert ext in ALLOWED_EXTENSIONS
    assert "exe" not in ALLOWED_EXTENSIONS
    assert "apk" not in ALLOWED_EXTENSIONS


def test_recording_mime_map_complete():
    for ext in ALLOWED_EXTENSIONS:
        assert ext in MIME_BY_EXT


def test_recording_size_limit_reasonable():
    assert 10 * 1024 * 1024 <= MAX_RECORDING_BYTES <= 500 * 1024 * 1024
