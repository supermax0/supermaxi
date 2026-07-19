"""Tenant-safe product tools exposed to the sales agent."""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import or_

from extensions import db
from models.product import Product
from models.product_color_variant import ProductColorVariant
from .message_guard import ProductKnowledgeService, classify_customer_message, preferred_fridge_size
from .models import AISalesProductProfile, AISalesToolCall, ProductMediaAsset


def _terms(query: str) -> list[str]:
    stop = {
        "عندكم", "اريد", "أريد", "اكو", "أكو", "سعر", "شنو", "هذا", "هاي", "منتج",
        "بحدود", "حدود", "تقريبا", "تقريباً", "اقل", "أقل", "تحت", "ضمن", "ميزانية", "الميزانية",
        "الف", "ألف", "مليون", "غالي", "غالية", "ارخص", "أرخص", "بديل", "بدائل", "خيار", "خيارات",
        "زين", "جيد", "افضل", "أفضل", "انسب", "أنسب", "حبيبي", "اخوية", "أخوية", "لو", "موجود",
        "متوفر", "متوفرة", "اريده", "أريده", "اخذه", "آخذه", "ثبت", "ثبته", "ويا", "عندي",
        "للبيت", "للمحل", "استخدام", "استخدامي", "شلون", "ليش", "بس", "بعد", "همين",
        "السلام", "عليكم", "هلا", "هلو", "مرحبا", "اهلا", "أهلا", "شكرا", "شكراً", "تمام",
        "اي", "إي", "نعم", "اوكي", "أوكي", "هو", "هي",
        "قارن", "قارنلي", "قارنها", "مقارنة", "مقارنه", "اعتمد", "أعتمد", "رشح", "رشحلي", "اختار", "اختر",
        "الحجم", "بالحجم", "والحجم", "المقاس", "بالمقاس", "والمقاس", "السعر", "بالسعر", "والسعر",
        "الغرفة", "غرفة", "غرفه", "متوسطة", "متوسطه", "صغيرة", "صغيره", "كبيرة", "كبيره",
        "المسافة", "مسافة", "مسافه", "المشاهدة", "مشاهدة", "مشاهده", "متر", "بوصة", "بوصه", "انج",
        "الجودة", "جودة", "الدقة", "دقة", "الدقه", "وضوح",
        "وسط", "متوسط", "متوسطه", "متوسطة", "معقول", "معقوله", "معقولة", "عادي", "عاديه", "عادية",
        "مواصفات", "المواصفات", "مواصفه", "المواصفه", "مواصفة", "المواصفة", "أيضا", "ايضا", "ايضاً", "أيضاً",
        "صورة", "صور", "صورته", "صورتها", "فيديو", "فديو", "مقطع", "صوت", "فويس",
        "ضمان", "ضمانه", "ضمانها", "توصيل", "سعره", "سعرها", "كم", "حجم", "قياس", "مقاس",
        "نفس", "نفسه", "نفسها", "ابو",
        "بي", "بيه", "مجال", "اخر", "آخر", "نهائي", "نهائية", "ينقص", "تنقص", "تخفض", "تراعي",
        # Price-question fillers that otherwise pollute product name search
        "شكد", "بشكد", "بكم", "بيش", "قدم", "قدام", "ft",
    }
    values = re.findall(r"[\w\u0600-\u06ff]+", query or "")
    normalized_stop = {_normalize(value) for value in stop}

    def is_stop(value: str) -> bool:
        normalized = _normalize(value)
        variants = {normalized}
        if len(normalized) > 3 and normalized[0] in "وبل":
            variants.add(normalized[1:])
        return any(variant in normalized_stop for variant in variants)

    return [value for value in values if len(value) > 1 and not is_stop(value) and not value.isdigit()][:8]


def has_product_query(query: str) -> bool:
    return bool(_terms(query) or _requested_size(query) or _requested_foot_size(query))


def _normalize(value: str) -> str:
    table = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
    return re.sub(r"\s+", " ", (value or "").translate(table).lower()).strip()


def filter_products_by_manager_instructions(
    products: list[dict[str, Any]],
    customer_message: str,
    instructions: str | None,
) -> list[dict[str, Any]]:
    """Apply simple manager rules like: if customer asks X, do not mention Y."""
    rows = list(products or [])
    instruction_text = str(instructions or "").strip()
    if not rows or not instruction_text:
        return rows
    normalized_message = _normalize(customer_message)
    if not normalized_message:
        return rows
    active_forbidden: set[str] = set()
    for line in re.split(r"[\r\n؛;]+", instruction_text):
        normalized_line = _normalize(line)
        if not normalized_line or "لا تذكر" not in normalized_line:
            continue
        before, after = normalized_line.split("لا تذكر", 1)
        if not re.search(r"\b(اذا|إذا|لو|عند|من)\b", before) or not re.search(r"\b(طلب|سأل|سال|يسأل|يريد|ذكر|كتب)\b", before):
            continue
        trigger_numbers = re.findall(r"\d+", before)
        trigger_words = [
            token for token in re.findall(r"[\w\u0600-\u06ff]+", before)
            if len(token) >= 2 and token not in {"اذا", "إذا", "لو", "عند", "من", "طلب", "سأل", "سال", "يسأل", "يريد", "ذكر", "كتب"}
        ]
        triggers = trigger_numbers or trigger_words[-4:]
        if not any(trigger and trigger in normalized_message for trigger in triggers):
            continue
        forbidden_numbers = re.findall(r"\d+", after)
        forbidden_words = [
            token for token in re.findall(r"[\w\u0600-\u06ff]+", after)
            if len(token) >= 2 and token not in {"موديل", "نموذج", "منتج", "هذا", "هاي", "ذلك"}
        ][:4]
        active_forbidden.update(forbidden_numbers or forbidden_words)
    if not active_forbidden:
        return rows

    def product_text(row: dict[str, Any]) -> str:
        values = [
            row.get("name"),
            row.get("official_name"),
            row.get("model"),
            row.get("description"),
            " ".join(str(value) for value in row.get("selling_points") or []),
        ]
        return _normalize(" ".join(str(value or "") for value in values))

    return [
        row for row in rows
        if not any(forbidden and forbidden in product_text(row) for forbidden in active_forbidden)
    ]


_FOOT_WORD_SIZES = {
    "ثلاث": 3, "ثلاثه": 3, "ثلاثة": 3,
    "اربع": 4, "اربعه": 4, "اربعة": 4, "أربع": 4, "أربعه": 4, "أربعة": 4,
    "خمس": 5, "خمسه": 5, "خمسة": 5,
    "ست": 6, "سته": 6, "ستة": 6,
    "سبع": 7, "سبعه": 7, "سبعة": 7,
    "ثمان": 8, "ثمانيه": 8, "ثمانية": 8,
    "تسع": 9, "تسعه": 9, "تسعة": 9,
    "عشر": 10, "عشره": 10, "عشرة": 10,
    "احدعش": 11, "إحدعش": 11, "احدعشر": 11,
    "اثنعش": 12, "اثنعشر": 12,
}


def _requested_size(query: str) -> int | None:
    translated = (query or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))
    values = [int(value) for value in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", translated)]
    return next((value for value in values if 20 <= value <= 100), None)


_FRIDGE_FEATURE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("two_door", r"(?:ابو\s+)?بابين|بابين\s+منفصل|دبل\s*دور|دوور\s*دبل|two\s*door"),
    ("single_door", r"باب\s+واحد|باب\s+وحيد|single\s*door"),
)

_FEATURE_SEARCH_TERMS: dict[str, tuple[str, ...]] = {
    "two_door": ("بابين", "بابين منفصل", "دبل دور"),
    "single_door": ("باب واحد", "باب وحيد"),
}


def requested_product_features(query: str) -> list[str]:
    normalized = _normalize((query or "").replace(".", " "))
    return [key for key, pattern in _FRIDGE_FEATURE_PATTERNS if re.search(pattern, normalized)]


def product_knowledge_blob(product: dict[str, Any]) -> str:
    metadata = product.get("metadata") or product.get("meta_json") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return _normalize(" ".join([
        str(product.get("official_name") or product.get("name") or ""),
        str(product.get("category") or product.get("catalog_category") or ""),
        str(product.get("brand") or metadata.get("brand") or ""),
        str(product.get("model") or metadata.get("model") or ""),
        str(metadata.get("product_type") or metadata.get("family") or ""),
        str(product.get("description") or ""),
        " ".join(str(value) for value in product.get("selling_points") or []),
        " ".join(str(value) for value in product.get("ideal_for") or []),
        " ".join(str(value) for value in product.get("aliases") or []),
        str(product.get("sales_notes") or ""),
        str(product.get("warranty") or ""),
    ]))


def product_matches_requested_features(product: dict[str, Any], features: list[str]) -> bool:
    if not features:
        return True
    blob = product_knowledge_blob(product)
    for feature in features:
        if feature == "two_door":
            if not any(term in blob for term in _FEATURE_SEARCH_TERMS["two_door"]):
                return False
        elif feature == "single_door":
            if any(term in blob for term in _FEATURE_SEARCH_TERMS["two_door"]):
                return False
    return True


def filter_products_by_features(products: list[dict[str, Any]], features: list[str]) -> list[dict[str, Any]]:
    if not features:
        return list(products or [])
    matched = [row for row in products or [] if product_matches_requested_features(row, features)]
    return matched or list(products or [])


def relevant_selling_point(product: dict[str, Any], query: str, features: list[str] | None = None) -> str:
    points = [str(value).strip() for value in (product.get("selling_points") or []) if str(value).strip()]
    if not points:
        return ""
    normalized_query = _normalize((query or "").replace(".", " "))
    for point in points:
        normalized_point = _normalize(point)
        if "بابين" in normalized_query and "بابين" in normalized_point:
            return point
        if normalized_point and normalized_point in normalized_query:
            return point
    if features:
        for feature in features:
            for term in _FEATURE_SEARCH_TERMS.get(feature, ()):
                for point in points:
                    if term in _normalize(point):
                        return point
    return points[0]


def is_redundant_spec_point(point: str, product_name: str) -> bool:
    """Skip selling points that only restate the product name or size already in the title."""
    normalized_point = _normalize(point)
    normalized_name = _normalize(product_name)
    if not normalized_point:
        return True
    if normalized_name and (
        normalized_point == normalized_name
        or normalized_point in normalized_name
        or normalized_name in normalized_point
    ):
        remainder = normalized_point.replace(normalized_name, " ")
        remainder = re.sub(r"(?:قياس|حجم|مقاس|بوصه|انج|قدم|قدام|ft|\d+)", " ", remainder)
        remainder = re.sub(r"\s+", " ", remainder).strip(" .-–—،,")
        if len(remainder) < 4:
            return True
    name_size = _requested_size(product_name) or _requested_foot_size(product_name)
    if name_size:
        size_only = re.fullmatch(
            rf"(?:شاشة|شاشه|ثلاجه|ثلاجة|منتج)?\s*(?:قياس|حجم|مقاس)?\s*{name_size}\s*(?:بوصه|انج|قدم|قدام|ft)?",
            normalized_point,
        )
        if size_only:
            return True
    return False


def unique_selling_points(product: dict[str, Any], *, limit: int = 4) -> list[str]:
    name = str(product.get("name") or product.get("official_name") or "").strip()
    selected: list[str] = []
    seen: set[str] = set()
    for raw in product.get("selling_points") or []:
        value = str(raw or "").strip()
        if not value or is_redundant_spec_point(value, name):
            continue
        key = _normalize(value)
        if key in seen:
            continue
        seen.add(key)
        selected.append(value)
        if len(selected) >= max(1, int(limit or 4)):
            break
    return selected


def parse_foot_size(value: str) -> int | None:
    """Extract fridge/freezer foot size from digits or Arabic words like سبعة قدم."""
    translated = (value or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789"))
    translated = re.sub(r"[.,؛]+", " ", translated)
    # قدام is a common typo for قدم in customer chats
    digit = re.search(r"(?<!\d)(\d{1,2})\s*(?:قدم|قدام|ft)\b", translated, re.IGNORECASE)
    if digit:
        size = int(digit.group(1))
        return size if 3 <= size <= 20 else None
    normalized = _normalize(translated)
    word_pattern = "|".join(sorted((re.escape(word) for word in _FOOT_WORD_SIZES), key=len, reverse=True))
    spoken = re.search(rf"(?:^|[^\w])({word_pattern})\s*(?:قدم|قدام|ft)\b", normalized, re.IGNORECASE)
    if spoken:
        return _FOOT_WORD_SIZES.get(spoken.group(1))
    return None


def _requested_foot_size(query: str) -> int | None:
    return parse_foot_size(query)


def _product_size(name: str) -> int | None:
    values = [int(value) for value in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", name or "")]
    explicit = next((value for value in values if 20 <= value <= 100), None)
    if explicit is not None:
        return explicit
    normalized = _normalize(name or "")
    screen_markers = ("شاشة", "شاشه", "شاشات", "تلفزيون", "تلفاز", "tv")
    if any(marker in normalized for marker in screen_markers):
        model_match = re.search(r"(?:موديل|model)\s*([2-9]\d)00\b", normalized, re.IGNORECASE)
        if model_match is None:
            model_match = re.search(r"\b([2-9]\d)00\b", normalized)
        if model_match:
            inferred = int(model_match.group(1))
            if 20 <= inferred <= 100:
                return inferred
    return None


def _product_foot_size(name: str) -> int | None:
    return parse_foot_size(name)


def _looks_like_refrigerator_name(name: str) -> bool:
    normalized = _normalize(name or "")
    if re.search(r"ثلاجه|ثلاجات|فريزر", normalized):
        return True
    if re.search(r"براد", normalized) and re.search(r"قدم|ft|\b[3-9]\b|1[0-9]", normalized):
        return True
    return False


def _term_variants(term: str) -> set[str]:
    normalized = _normalize(term)
    variants = {term, normalized}
    if normalized in {"شاشه", "شاشات", "تلفزيون", "تلفاز", "tv", "شاسة", "شاسه"}:
        variants.update({"شاشة", "شاشه", "شاسة", "شاسه", "شاشات", "تلفزيون", "تلفاز", "TV", "tv"})
    elif normalized in {"ثلاجه", "ثلاجات", "براد", "برادات", "فريزر"}:
        variants.update({"ثلاجة", "ثلاجه", "ثلاجات", "براد", "برادات", "فريزر"})
    return {value for value in variants if value}


def _is_two_ton_split_ac(product: Product) -> bool:
    blob = _normalize(" ".join([
        str(product.name or ""),
        str(product.catalog_category or ""),
        str(product.description or ""),
    ]))
    return bool(re.search(r"سبلت|split", blob) and re.search(r"2\s*طن|طنين|2طن", blob))


def _default_warranty_text(profile: AISalesProductProfile | None) -> str:
    if profile and str(profile.warranty_text or "").strip():
        return str(profile.warranty_text).strip()
    return ProductKnowledgeService.default_warranty()


def _default_delivery_text(product: Product, profile: AISalesProductProfile | None) -> str:
    if profile and str(profile.delivery_text or "").strip():
        return str(profile.delivery_text).strip()
    if _is_two_ton_split_ac(product):
        return "بغداد توصيل مجاني، والمحافظات 15 ألف"
    return ProductKnowledgeService.default_delivery(str(product.name or ""))


def _serialize_product(product: Product, profile: AISalesProductProfile | None) -> dict[str, Any]:
    allow_price = not profile or bool(profile.allow_price)
    colors = profile.get_colors() if profile else []
    variant_colors = [
        str(row.color_name or "").strip()
        for row in ProductColorVariant.query.filter_by(product_id=product.id).filter(ProductColorVariant.quantity > 0).all()
        if str(row.color_name or "").strip()
    ]
    for color in variant_colors:
        if color not in colors:
            colors.append(color)
    if not colors:
        normalized_name = _normalize(product.name or "")
        for label, pattern in (("أبيض", r"\bابيض\b"), ("أسود", r"\bاسود\b"), ("فضي", r"\bفضي\b")):
            if re.search(pattern, normalized_name):
                colors.append(label)
    metadata = product.meta_json or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    category = str(product.catalog_category or metadata.get("category") or metadata.get("product_type") or "")
    brand = str(metadata.get("brand") or "")
    model = str(metadata.get("model") or "")
    return {
        "product_id": product.id,
        "name": (profile.marketing_name if profile and profile.marketing_name else product.name),
        "official_name": product.name,
        "category": category,
        "catalog_category": category,
        "brand": brand,
        "model": model,
        "metadata": metadata,
        "price": int(product.sale_price or 0) if allow_price else None,
        "price_visible": allow_price,
        "stock": int(product.quantity or 0),
        "available_for_reservation": bool(product.active),
        "can_reserve": bool(product.active),
        "description": product.description or "",
        "selling_points": profile.get_selling_points() if profile else [],
        "aliases": profile.get_aliases() if profile else [],
        "ideal_for": profile.get_ideal_for() if profile else [],
        "objection_guidance": profile.get_objections() if profile else {},
        "sales_notes": profile.ai_notes if profile else "",
        "warranty": _default_warranty_text(profile),
        "delivery": _default_delivery_text(product, profile),
        "colors": colors,
        "dimensions": {
            "width_cm": float(profile.width_cm) if profile and profile.width_cm is not None else None,
            "height_cm": float(profile.height_cm) if profile and profile.height_cm is not None else None,
            "depth_cm": float(profile.depth_cm) if profile and profile.depth_cm is not None else None,
        },
        "image_url": product.image_url or "",
    }


def get_products_by_ids(product_ids: list[int], *, in_stock_only: bool = True) -> list[dict[str, Any]]:
    ordered_ids = []
    for value in product_ids or []:
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            continue
        if product_id not in ordered_ids:
            ordered_ids.append(product_id)
    if not ordered_ids:
        return []
    q = Product.query.filter(Product.id.in_(ordered_ids), Product.active.is_(True))
    if in_stock_only:
        q = q.filter(Product.quantity > 0)
    products = {product.id: product for product in q.all()}
    profiles = {
        row.product_id: row
        for row in AISalesProductProfile.query.filter(AISalesProductProfile.product_id.in_(ordered_ids)).all()
    }
    rows = []
    for product_id in ordered_ids:
        product = products.get(product_id)
        profile = profiles.get(product_id)
        if not product or (profile and (not profile.is_active or not profile.allow_recommendation)):
            continue
        rows.append(_serialize_product(product, profile))
    return rows


def get_available_screen_products(*, size: int | None = None, limit: int = 10, in_stock_only: bool = True) -> list[dict[str, Any]]:
    """Return live screen alternatives without depending on a requested brand."""
    q = Product.query.outerjoin(
        AISalesProductProfile,
        AISalesProductProfile.product_id == Product.id,
    ).filter(
        Product.active.is_(True),
        or_(
            Product.name.ilike("%شاشه%"),
            Product.name.ilike("%شاشة%"),
            Product.name.ilike("%تلفزيون%"),
            Product.name.ilike("%TV%"),
        ),
    )
    if in_stock_only:
        q = q.filter(Product.quantity > 0)
    candidates = q.order_by(Product.sale_price.asc(), Product.quantity.desc()).limit(300).all()
    profiles = {
        row.product_id: row
        for row in AISalesProductProfile.query.filter(
            AISalesProductProfile.product_id.in_([product.id for product in candidates])
        ).all()
    } if candidates else {}
    rows = []
    for product in candidates:
        profile = profiles.get(product.id)
        if profile and (not profile.is_active or not profile.allow_recommendation):
            continue
        if size is not None and _product_size(product.name) != int(size):
            continue
        rows.append(_serialize_product(product, profile))
        if len(rows) >= min(max(int(limit), 1), 20):
            break
    return rows


def get_fridge_products(*, foot_size: int | None = None, limit: int = 10, in_stock_only: bool = False) -> list[dict[str, Any]]:
    """Return refrigerator candidates, allowing reservation even when stock is zero."""
    q = Product.query.outerjoin(
        AISalesProductProfile,
        AISalesProductProfile.product_id == Product.id,
    ).filter(
        Product.active.is_(True),
        or_(
            Product.name.ilike("%ثلاجه%"),
            Product.name.ilike("%ثلاجة%"),
            Product.name.ilike("%ثلاجات%"),
            Product.name.ilike("%براد%"),
            Product.name.ilike("%فريزر%"),
            AISalesProductProfile.marketing_name.ilike("%ثلاجه%"),
            AISalesProductProfile.marketing_name.ilike("%ثلاجة%"),
            AISalesProductProfile.aliases_json.ilike("%براد%"),
        ),
    )
    if in_stock_only:
        q = q.filter(Product.quantity > 0)
    candidates = q.order_by(Product.sale_price.asc(), Product.quantity.desc()).limit(400).all()
    profiles = {
        row.product_id: row
        for row in AISalesProductProfile.query.filter(
            AISalesProductProfile.product_id.in_([product.id for product in candidates])
        ).all()
    } if candidates else {}
    filtered = []
    for product in candidates:
        normalized_name = _normalize(product.name or "")
        if not _looks_like_refrigerator_name(product.name or ""):
            continue
        if re.search(r"مبرد|كولر|هواء|ماء|كهربائي|كهربائيه|كهربائية", normalized_name) and not re.search(r"ثلاجه|ثلاجة|فريزر", normalized_name):
            continue
        profile = profiles.get(product.id)
        if profile and (not profile.is_active or not profile.allow_recommendation):
            continue
        filtered.append(product)
    if foot_size is not None:
        target_foot_size = preferred_fridge_size(int(foot_size)) or int(foot_size)
        sized = [(product, _product_foot_size(product.name)) for product in filtered]
        sized = [(product, size) for product, size in sized if size is not None]
        if sized:
            available_sizes = sorted({int(size) for _, size in sized})
            chosen_size = min(
                available_sizes,
                key=lambda size: (abs(size - target_foot_size), 0 if size >= target_foot_size else 1, size),
            )
            filtered = [product for product, size in sized if size == chosen_size]
    selected = sorted(filtered, key=lambda product: (int(product.sale_price or 0), -int(product.quantity or 0), str(product.name or "")))
    return [
        _serialize_product(product, profiles.get(product.id))
        for product in selected[: min(max(int(limit or 10), 1), 20)]
    ]


def search_products(
    query: str,
    *,
    max_price: int | None = None,
    in_stock_only: bool = True,
    limit: int = 3,
    exclude_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    q = Product.query.outerjoin(AISalesProductProfile, AISalesProductProfile.product_id == Product.id).filter(Product.active.is_(True))
    excluded = {int(value) for value in exclude_ids or [] if str(value).isdigit()}

    def constrained(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for row in rows:
            if max_price and int(row.get("price") or 0) > int(max_price):
                continue
            if in_stock_only and int(row.get("stock") or 0) <= 0:
                continue
            if int(row.get("product_id") or 0) in excluded:
                continue
            result.append(row)
        return result[: min(max(int(limit or 3), 1), 20)]

    guard = classify_customer_message(query)
    if guard.family == "screen" and guard.screen_size and not guard.requested_brand and not guard.is_accessory_request:
        direct_screen_rows = constrained(get_available_screen_products(
            size=guard.screen_size,
            in_stock_only=in_stock_only,
            limit=20,
        ))
        if direct_screen_rows:
            return direct_screen_rows
    if guard.family == "refrigerator" and (guard.foot_size or guard.preferred_foot_size):
        direct_fridge_rows = constrained(get_fridge_products(
            foot_size=guard.foot_size or guard.preferred_foot_size,
            in_stock_only=False,
            limit=20,
        ))
        if direct_fridge_rows:
            return direct_fridge_rows
    terms = _terms(query)
    wanted_size = _requested_size(query)
    wanted_foot_size = _requested_foot_size(query)
    if not terms and wanted_size is None and wanted_foot_size is None:
        return []
    if wanted_foot_size is not None and not terms and wanted_size is None:
        return constrained(get_fridge_products(
            foot_size=wanted_foot_size,
            in_stock_only=in_stock_only,
            limit=20,
        ))
    if terms:
        variants = {variant for term in terms for variant in _term_variants(term)}
        search_columns = []
        for variant in variants:
            search_columns.extend([
                Product.name.ilike(f"%{variant}%"),
                AISalesProductProfile.marketing_name.ilike(f"%{variant}%"),
                AISalesProductProfile.aliases_json.ilike(f"%{variant}%"),
                AISalesProductProfile.selling_points_json.ilike(f"%{variant}%"),
                AISalesProductProfile.ai_notes.ilike(f"%{variant}%"),
            ])
        q = q.filter(or_(*search_columns))
    if max_price and int(max_price) > 0:
        q = q.filter(Product.sale_price <= int(max_price))
    if in_stock_only:
        q = q.filter(Product.quantity > 0)
    if excluded:
        q = q.filter(~Product.id.in_(list(excluded)))
    candidates = q.order_by(Product.sale_price.asc(), Product.quantity.desc()).limit(300).all()
    candidate_profiles = {
        row.product_id: row
        for row in AISalesProductProfile.query.filter(AISalesProductProfile.product_id.in_([p.id for p in candidates])).all()
    } if candidates else {}
    hidden_candidates = [
        product for product in candidates
        if candidate_profiles.get(product.id)
        and (not candidate_profiles[product.id].is_active or not candidate_profiles[product.id].allow_recommendation)
    ]
    candidates = [
        product for product in candidates
        if not candidate_profiles.get(product.id)
        or (candidate_profiles[product.id].is_active and candidate_profiles[product.id].allow_recommendation)
    ]
    if not candidates and hidden_candidates:
        hidden_product = hidden_candidates[0]
        hidden_foot_size = _product_foot_size(hidden_product.name or "")
        hidden_screen_size = _product_size(hidden_product.name or "")
        if hidden_foot_size is not None or _looks_like_refrigerator_name(hidden_product.name or ""):
            return get_fridge_products(
                foot_size=hidden_foot_size or wanted_foot_size,
                in_stock_only=in_stock_only,
                limit=limit,
            )
        if hidden_screen_size is not None:
            return get_available_screen_products(
                size=hidden_screen_size or wanted_size,
                in_stock_only=in_stock_only,
                limit=limit,
            )
    normalized_terms = [_normalize(term) for term in terms]
    if wanted_foot_size is not None:
        sized_candidates = [
            (product, _product_foot_size(product.name))
            for product in candidates
            if _product_foot_size(product.name) is not None
        ]
        if sized_candidates:
            available_sizes = sorted({int(size) for _, size in sized_candidates})
            chosen_size = min(
                available_sizes,
                key=lambda size: (abs(size - wanted_foot_size), 0 if size >= wanted_foot_size else 1, size),
            )
            candidates = [product for product, size in sized_candidates if size == chosen_size]
        elif not candidates:
            # Price questions like "شكد السعر 7 قدام" leave no useful brand terms;
            # fall back to the fridge catalog by foot size.
            return get_fridge_products(
                foot_size=wanted_foot_size,
                in_stock_only=in_stock_only,
                limit=limit,
            )
    if wanted_size is not None and not terms:
        exact_size_candidates = [
            product for product in candidates
            if _product_size(product.name) == wanted_size
        ]
        if exact_size_candidates:
            candidates = exact_size_candidates

    requested_features = requested_product_features(query)
    if requested_features:
        serialized = [_serialize_product(product, candidate_profiles.get(product.id)) for product in candidates]
        filtered = filter_products_by_features(serialized, requested_features)
        if filtered:
            matched_ids = {int(row.get("product_id") or 0) for row in filtered}
            candidates = [product for product in candidates if product.id in matched_ids]

    def rank(product):
        profile = candidate_profiles.get(product.id)
        searchable = " ".join([
            product.name or "",
            (profile.marketing_name or "") if profile else "",
            " ".join(str(value) for value in profile.get_aliases()) if profile else "",
            " ".join(str(value) for value in profile.get_selling_points()) if profile else "",
            (profile.ai_notes or "") if profile else "",
        ])
        name = _normalize(searchable)
        text_matches = sum(1 for term in normalized_terms if term and term in name)
        feature_match = int(product_matches_requested_features(
            _serialize_product(product, profile),
            requested_features,
        )) if requested_features else 0
        size = _product_size(product.name)
        foot_size = _product_foot_size(product.name)
        size_distance = abs(size - wanted_size) if wanted_size is not None and size is not None else 999
        foot_distance = abs(foot_size - wanted_foot_size) if wanted_foot_size is not None and foot_size is not None else 999
        missing_size = 1 if wanted_size is not None and size is None else 0
        missing_foot_size = 1 if wanted_foot_size is not None and foot_size is None else 0
        return (
            -feature_match,
            -text_matches,
            missing_foot_size,
            foot_distance,
            missing_size,
            size_distance,
            int(product.sale_price or 0),
            -int(product.quantity or 0),
        )

    products = sorted(candidates, key=rank)[: min(max(limit, 1), 10)]
    return [_serialize_product(product, candidate_profiles.get(product.id)) for product in products]


def find_nearest_smaller_foot_products(reference: dict[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    """Return the closest smaller in-stock size from the same appliance family."""
    reference_name = str(reference.get("official_name") or reference.get("name") or "")
    reference_size = _product_foot_size(reference_name)
    if reference_size is None:
        return []
    normalized = _normalize(reference_name)
    q = Product.query.filter(Product.active.is_(True), Product.quantity > 0)
    if re.search(r"ثلاجه|ثلاجات", normalized):
        q = q.filter(or_(Product.name.ilike("%ثلاجه%"), Product.name.ilike("%ثلاجة%")))
    else:
        return []
    candidates = []
    for product in q.limit(300).all():
        size = _product_foot_size(product.name)
        if size is not None and size < reference_size:
            candidates.append((product, size))
    if not candidates:
        return []
    nearest_size = max(size for _, size in candidates)
    selected = sorted(
        (product for product, size in candidates if size == nearest_size),
        key=lambda product: (int(product.sale_price or 0), str(product.name or "")),
    )[: max(1, min(int(limit or 3), 10))]
    profiles = {
        row.product_id: row
        for row in AISalesProductProfile.query.filter(
            AISalesProductProfile.product_id.in_([product.id for product in selected])
        ).all()
    } if selected else {}
    return [
        _serialize_product(product, profiles.get(product.id))
        for product in selected
        if not profiles.get(product.id)
        or (profiles[product.id].is_active and profiles[product.id].allow_recommendation)
    ]


def get_product_media(product_id: int, media_type: str, tags: list[str] | None = None, limit: int = 3) -> list[dict]:
    profile = AISalesProductProfile.query.filter_by(product_id=product_id).first()
    if profile and (not profile.is_active or not profile.allow_recommendation):
        return []
    q = ProductMediaAsset.query.filter_by(product_id=product_id, media_type=media_type.lower(), ai_approved=True)
    rows = q.order_by(ProductMediaAsset.is_primary.desc(), ProductMediaAsset.sort_order.asc()).limit(20).all()
    wanted = {tag.strip().lower() for tag in tags or [] if tag.strip()}
    if wanted:
        rows = [row for row in rows if wanted.intersection({tag.lower() for tag in row.get_tags()})]
    result = [
        {
            "media_id": row.id,
            "media_type": row.media_type,
            "title": row.title or "",
            "public_url": row.public_url or "",
            "storage_path": row.storage_path,
            "mime_type": row.mime_type or "",
            "tags": row.get_tags(),
        }
        for row in rows[:limit]
    ]
    if not result and media_type.lower() == "image":
        product = Product.query.get(product_id)
        if product and (product.image_url or "").strip():
            result.append(
                {
                    "media_id": None,
                    "media_type": "image",
                    "title": product.name,
                    "public_url": product.image_url.strip(),
                    "storage_path": "",
                    "mime_type": "image/jpeg",
                    "tags": ["primary"],
                }
            )
    return result


def log_product_search(conversation_id: int, message_id: int, query: str, results: list[dict]) -> None:
    call = AISalesToolCall(
        conversation_id=conversation_id,
        message_id=message_id,
        tool_name="search_products",
        status="success",
    )
    call.set_input({"query": query})
    call.set_output({
        "count": len(results),
        "product_ids": [row["product_id"] for row in results],
        "ranking": [
            {
                "product_id": row["product_id"],
                "score": row.get("recommendation_score"),
                "knowledge_score": row.get("knowledge_score"),
                "reasons": row.get("recommendation_reasons") or [],
            }
            for row in results
        ],
    })
    db.session.add(call)
