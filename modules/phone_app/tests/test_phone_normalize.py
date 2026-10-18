"""Tests for Finora Phone staff API helpers."""

from __future__ import annotations

from modules.phone_app.api.v1.customers import _phone_variants


def test_phone_variants_iraqi_local():
    variants = _phone_variants("07701234567")
    assert "07701234567" in variants
    assert "7701234567" in variants


def test_phone_variants_with_country():
    variants = _phone_variants("9647701234567")
    assert "7701234567" in variants
    assert any(v.startswith("0") for v in variants)
