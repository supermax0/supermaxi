"""Collapse model-level washer sections into one store category."""

from __future__ import annotations

from functools import lru_cache

_DISHWASHER_MARKERS = (
    "غسالات صحون",
    "غسالة صحون",
    "غساله صحون",
    "جلاية",
    "جلايه",
    "غسالة اطباق",
    "غسالة أطباق",
    "غساله اطباق",
    "غساله أطباق",
    "dishwasher",
    "dish washer",
)

_WASHER_MARKERS = (
    "غسالة ملابس",
    "غساله ملابس",
    "غسالات ملابس",
    "غسالة",
    "غساله",
    "غسالات",
    "نشافة",
    "نشافه",
    "دراير",
    "washer",
    "washing machine",
    "dryer",
)
_DISHWASHER_FOLDED = tuple(m.casefold() for m in _DISHWASHER_MARKERS)
_WASHER_FOLDED = tuple(m.casefold() for m in _WASHER_MARKERS)


@lru_cache(maxsize=8192)
def _fold(probe: str) -> str | None:
    folded = probe.casefold()
    if any(marker in folded for marker in _DISHWASHER_FOLDED):
        return "غسالات صحون"
    if any(marker in folded for marker in _WASHER_FOLDED):
        return "غسالات"
    return None


def merge_washer_category(category: object, name: object = "") -> str:
    """Fold individual washer listings into غسالات.

    A short unrelated section such as أجهزة منزلية stays as stored.
    Dishwashers stay in غسالات صحون.
    (Memoised on the probed text: a catalogue repeats a handful of categories over thousands of products.)
    """

    raw = str(category or "").strip()
    title = str(name or "").strip()
    probe = raw
    if title and (not raw or raw.casefold() == title.casefold() or len(raw) > 40):
        probe = f"{raw} {title}".strip()
    return _fold(probe) or raw
