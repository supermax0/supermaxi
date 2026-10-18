from __future__ import annotations

import re
import unicodedata


_CATEGORY_IMAGE_ROOT = "storefront/images/categories"

_CATEGORY_IMAGE_FILES = {
    "أجهزة منزلية": "home-appliances.webp",
    "اجهزة منزلية": "home-appliances.webp",
    "أخرى": "miscellaneous.webp",
    "اخرى": "miscellaneous.webp",
    "منتجات متنوعة": "miscellaneous.webp",
    "تكييف وتبريد": "cooling.webp",
    "تكييف و تبريد": "cooling.webp",
    "ثلاجات": "refrigerators.webp",
    "ثلاجة": "refrigerators.webp",
    "شاشات": "televisions.webp",
    "تلفزيونات": "televisions.webp",
    "تلفزيونات وشاشات": "televisions.webp",
    "غسالات": "washing-machines.webp",
    "غسالات ملابس": "washing-machines.webp",
    "مايكرويف": "microwaves.webp",
    "مايكروويف": "microwaves.webp",
    "أفران مايكرويف": "microwaves.webp",
    "مكانس": "vacuum-cleaners.webp",
    "مكانس كهربائية": "vacuum-cleaners.webp",
}


def category_image_path(category_name: object) -> str | None:
    """Return the curated storefront image for a known category name."""

    normalized = unicodedata.normalize("NFKC", str(category_name or "")).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    filename = _CATEGORY_IMAGE_FILES.get(normalized)
    return f"{_CATEGORY_IMAGE_ROOT}/{filename}" if filename else None
