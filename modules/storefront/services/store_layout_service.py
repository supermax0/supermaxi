from __future__ import annotations

import uuid

CARD_TEMPLATES: dict[str, dict] = {
    "classic": {
        "label": "كلاسيكي فاخر",
        "description": "بطاقة متوازنة مع صورة مربعة وزر سلة.",
    },
    "compact": {
        "label": "مضغوط",
        "description": "حجم أصغر لعرض أكثر منتجات في الصف.",
    },
    "showcase": {
        "label": "معرض",
        "description": "صورة بارزة وعنوان واضح للمنتجات المميزة.",
    },
    "spotlight": {
        "label": "سبوت لايت",
        "description": "بطاقة كبيرة لإبراز منتج واحد أو عرض خاص.",
    },
    "horizontal": {
        "label": "أفقي",
        "description": "صورة بجانب التفاصيل — مثالي للقوائم.",
    },
    "elegant": {
        "label": "أنيق",
        "description": "تصميم هادئ بحدود ذهبية خفيفة.",
    },
    "overlay": {
        "label": "Overlay",
        "description": "السعر والعنوان فوق الصورة.",
    },
}

CARD_SIZES: dict[str, dict] = {
    "sm": {"label": "صغير", "columns": 4, "span": 1},
    "md": {"label": "متوسط", "columns": 4, "span": 1},
    "lg": {"label": "كبير", "columns": 3, "span": 2},
    "xl": {"label": "عملاق", "columns": 3, "span": 2, "row_span": 2},
}

PRODUCT_MODES = {"all", "discount", "new", "category", "manual"}


def _safe_str(v) -> str:
    return str(v or "").strip()


def _safe_int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def normalize_section(raw: dict, *, sort_order: int = 0) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    template = _safe_str(raw.get("card_template") or raw.get("template") or "classic")
    if template not in CARD_TEMPLATES:
        template = "classic"
    size = _safe_str(raw.get("card_size") or raw.get("size") or "md")
    if size not in CARD_SIZES:
        size = "md"
    mode = _safe_str(raw.get("product_mode") or "all").lower()
    if mode not in PRODUCT_MODES:
        mode = "all"
    columns = _safe_int(raw.get("columns"), CARD_SIZES[size]["columns"])
    columns = max(2, min(columns, 6))
    limit = max(1, min(_safe_int(raw.get("limit"), 12), 48))
    product_ids = []
    for pid in raw.get("product_ids") or []:
        n = _safe_int(pid, 0)
        if n > 0:
            product_ids.append(n)
    section_id = _safe_str(raw.get("id")) or f"sec_{uuid.uuid4().hex[:8]}"
    return {
        "id": section_id,
        "title": _safe_str(raw.get("title")) or "المنتجات",
        "enabled": bool(raw.get("enabled", True)),
        "sort_order": _safe_int(raw.get("sort_order"), sort_order),
        "card_template": template,
        "card_size": size,
        "columns": columns,
        "product_mode": mode,
        "category": _safe_str(raw.get("category")),
        "product_ids": product_ids,
        "limit": limit,
    }


def default_sections(card_style: str = "classic") -> list[dict]:
    template = card_style if card_style in CARD_TEMPLATES else "classic"
    return [
        normalize_section(
            {
                "id": "main_products",
                "title": "المنتجات",
                "enabled": True,
                "sort_order": 0,
                "card_template": template,
                "card_size": "md",
                "columns": 4,
                "product_mode": "all",
                "limit": 48,
            },
            sort_order=0,
        )
    ]


def parse_sections(flags: dict, card_style: str = "classic") -> list[dict]:
    raw = flags.get("storefront_product_sections")
    if not isinstance(raw, list) or not raw:
        return default_sections(card_style)
    sections = [normalize_section(row, sort_order=i) for i, row in enumerate(raw)]
    sections = [s for s in sections if s.get("enabled")]
    sections.sort(key=lambda s: _safe_int(s.get("sort_order"), 0))
    return sections or default_sections(card_style)


def _filter_products(cards: list[dict], section: dict) -> list[dict]:
    mode = section.get("product_mode") or "all"
    if mode == "discount":
        items = [c for c in cards if _safe_int(c.get("discount_percent"), 0) > 0]
    elif mode == "new":
        items = [c for c in cards if c.get("is_new")]
    elif mode == "category":
        cat = _safe_str(section.get("category"))
        items = [
            c for c in cards
            if _safe_str(c.get("category")) == cat or _safe_str(c.get("badge")) == cat
        ]
    elif mode == "manual":
        wanted = {pid: i for i, pid in enumerate(section.get("product_ids") or [])}
        items = [c for c in cards if _safe_int(c.get("id"), 0) in wanted]
        items.sort(key=lambda c: wanted.get(_safe_int(c.get("id"), 0), 999))
    else:
        items = list(cards)
    limit = max(1, _safe_int(section.get("limit"), 12))
    return items[:limit]


def build_store_sections(cards: list[dict], flags: dict, card_style: str = "classic") -> list[dict]:
    sections = parse_sections(flags, card_style)
    built: list[dict] = []
    used_ids: set[int] = set()
    for section in sections:
        pool = cards
        if section.get("product_mode") != "manual":
            pool = [c for c in cards if _safe_int(c.get("id"), 0) not in used_ids]
        products = _filter_products(pool, section)
        for p in products:
            used_ids.add(_safe_int(p.get("id"), 0))
        size_meta = CARD_SIZES.get(section.get("card_size") or "md", CARD_SIZES["md"])
        built.append(
            {
                **section,
                "products": products,
                "grid_columns": section.get("columns") or size_meta["columns"],
                "span": size_meta.get("span", 1),
                "row_span": size_meta.get("row_span", 1),
                "template_label": CARD_TEMPLATES.get(section.get("card_template"), {}).get("label", ""),
            }
        )
    return [s for s in built if s.get("products")]


def card_templates_catalog() -> list[dict]:
    return [{"id": k, **v} for k, v in CARD_TEMPLATES.items()]


def card_sizes_catalog() -> list[dict]:
    return [{"id": k, **v} for k, v in CARD_SIZES.items()]
