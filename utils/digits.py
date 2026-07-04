# -*- coding: utf-8 -*-
"""Normalize numeric strings to Western digits (0-9)."""

from __future__ import annotations

_EASTERN = "٠١٢٣٤٥٦٧٨٩"
_WESTERN = "0123456789"
_PERSIAN = "۰۱۲۳۴۵۶۷۸۹"
_DIGIT_TRANS = str.maketrans(_EASTERN + _PERSIAN, _WESTERN * 2)


def to_english_digits(value) -> str:
    if value is None:
        return ""
    return str(value).translate(_DIGIT_TRANS)


def digits_only(value) -> str:
    return "".join(ch for ch in to_english_digits(value) if ch.isdigit())
