"""Arabic business name normalization and fuzzy matching."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_ARABIC_DIACRITICS = re.compile(
    r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]"
)
_TATWEEL = re.compile(r"\u0640")
_NON_WORD = re.compile(r"[^\w\s\u0600-\u06FF]", re.UNICODE)
_MULTI_SPACE = re.compile(r"\s+")

_ALEF_VARIANTS = str.maketrans({
    "\u0622": "\u0627",
    "\u0623": "\u0627",
    "\u0625": "\u0627",
    "\u0671": "\u0627",
})


def normalize_business_name(raw: str | None) -> str:
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", str(raw).strip())
    text = _ARABIC_DIACRITICS.sub("", text)
    text = _TATWEEL.sub("", text)
    text = text.translate(_ALEF_VARIANTS)
    text = _NON_WORD.sub(" ", text)
    text = _MULTI_SPACE.sub(" ", text).strip().lower()
    return text


def name_similarity_score(a: str | None, b: str | None) -> float:
    na = normalize_business_name(a)
    nb = normalize_business_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def token_similarity_score(a: str | None, b: str | None) -> float:
    na = set(normalize_business_name(a).split())
    nb = set(normalize_business_name(b).split())
    if not na or not nb:
        return 0.0
    intersection = na & nb
    union = na | nb
    return len(intersection) / len(union)
