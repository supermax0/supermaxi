"""Lightweight guards for customer messages before product lookup or AI reply."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


_DIGIT_TABLE = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_AR_TABLE = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})


def normalize_digits(value: str) -> str:
    return (value or "").translate(_DIGIT_TABLE)


def normalize_arabic(value: str) -> str:
    value = normalize_digits(value).translate(_AR_TABLE).lower()
    value = re.sub(r"[،؛]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def preferred_fridge_size(size: int | None) -> int | None:
    if size is None:
        return None
    if size == 6:
        return 7
    if size in {9, 10, 11, 13, 15}:
        return 12
    return size


@dataclass(frozen=True)
class PriceReference:
    raw: str
    compact: int | None = None
    amount_iqd: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"raw": self.raw, "compact": self.compact, "amount_iqd": self.amount_iqd}


@dataclass
class MessageGuardResult:
    raw_text: str
    normalized_text: str
    intent: str = "general"
    family: str = ""
    screen_size: int | None = None
    foot_size: int | None = None
    preferred_foot_size: int | None = None
    requested_brand: str = ""
    mentioned_price: PriceReference | None = None
    is_generic_price_request: bool = False
    is_ad_price_reference: bool = False
    needs_product_context: bool = False
    is_gratitude: bool = False
    is_greeting: bool = False
    is_decline: bool = False
    is_media_request: bool = False
    is_accessory_request: bool = False
    confidence: float = 0.5
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "intent": self.intent,
            "family": self.family,
            "screen_size": self.screen_size,
            "foot_size": self.foot_size,
            "preferred_foot_size": self.preferred_foot_size,
            "requested_brand": self.requested_brand,
            "mentioned_price": self.mentioned_price.as_dict() if self.mentioned_price else None,
            "is_generic_price_request": self.is_generic_price_request,
            "is_ad_price_reference": self.is_ad_price_reference,
            "needs_product_context": self.needs_product_context,
            "is_gratitude": self.is_gratitude,
            "is_greeting": self.is_greeting,
            "is_decline": self.is_decline,
            "is_media_request": self.is_media_request,
            "is_accessory_request": self.is_accessory_request,
            "confidence": self.confidence,
            "notes": list(self.notes),
        }


def parse_price_reference(value: str) -> PriceReference | None:
    text = normalize_digits(value)
    match = re.search(r"(?<!\d)(\d{1,3})(?:[.,](\d{3}))?\s*(?:الف|ألف|k)?(?!\d)", text, re.IGNORECASE)
    if not match:
        return None
    whole = int(match.group(1))
    tail = match.group(2)
    raw = match.group(0).strip()
    if tail:
        amount = int(f"{whole}{tail}")
        return PriceReference(raw=raw, compact=whole, amount_iqd=amount)
    if re.search(r"(?:الف|ألف|k)", raw, re.IGNORECASE) or whole < 1000:
        return PriceReference(raw=raw, compact=whole, amount_iqd=whole * 1000)
    return PriceReference(raw=raw, compact=whole, amount_iqd=whole)


def _extract_screen_size(text: str) -> int | None:
    values = [int(raw) for raw in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", text)]
    return next((size for size in values if 20 <= size <= 100), None)


def _extract_foot_size(text: str) -> int | None:
    match = re.search(r"(?<!\d)(\d{1,2})\s*(?:قدم|قدام|ft)\b", text)
    if match:
        size = int(match.group(1))
        if 3 <= size <= 25:
            return size
    match = re.search(r"(?:ثلاجه|ثلاجات|براد|فريزر)\D{0,8}(?<!\d)(\d{1,2})(?!\d)", text)
    if match:
        size = int(match.group(1))
        if 3 <= size <= 25:
            return size
    words = {
        "خمس": 5, "خمسه": 5, "ست": 6, "سته": 6, "سبع": 7, "سبعه": 7,
        "تسع": 9, "تسعه": 9, "عشر": 10, "عشره": 10, "اثنعش": 12, "اثنعشر": 12,
    }
    for word, size in words.items():
        if re.search(rf"\b{word}\b.{0,8}(?:قدم|قدام)", text):
            return size
    return None


def _context_family(context: dict[str, Any] | None) -> str:
    if not context:
        return ""
    for key in ("product_family", "current_product_family", "active_product_family"):
        family = str(context.get(key) or "").strip().lower()
        if family:
            return family
    last_guard = context.get("last_message_guard") or {}
    if isinstance(last_guard, dict):
        family = str(last_guard.get("family") or "").strip().lower()
        if family:
            return family
    facts = context.get("customer_facts") or {}
    if isinstance(facts, dict):
        family = str(facts.get("product_family") or "").strip().lower()
        if family:
            return family
    return ""


def _bare_context_foot_size(text: str) -> int | None:
    match = re.fullmatch(r"(?:حجم|قياس|مقاس)?\s*(\d{1,2})\s*", text)
    if not match:
        return None
    size = int(match.group(1))
    if 3 <= size <= 25:
        return size
    return None


class CustomerMessageGuard:
    """Classifies raw customer text into safe product-search signals."""

    def classify(self, message: str, context: dict[str, Any] | None = None) -> MessageGuardResult:
        normalized = normalize_arabic(message)
        result = MessageGuardResult(raw_text=message or "", normalized_text=normalized)
        result.is_gratitude = bool(re.fullmatch(
            r"(?:تمام\s*)?(?:شكرا|شكراً|مشكور|تسلم|تسلمون|يعطيك العافيه|الله يعافيك)(?:\s+(?:الكم|لكم|حبيبي|حبي|عيني))?[\s!.؟]*",
            normalized,
        ))
        result.is_greeting = bool(re.fullmatch(r"(?:السلام عليكم|سلام عليكم|هلا|هلو|مرحبا|اهلا|صباح الخير|مساء الخير)[\s!.؟]*", normalized))
        result.is_decline = bool(re.fullmatch(
            r"(?:اعتذر|اني اعتذر|لا شكرا|لا مشكور|مو لازم|خلاص|ما اريد|الغيت|الغاء)[\s!.؟]*",
            normalized,
        ))
        result.is_media_request = bool(re.search(r"صوره|صور|فيديو|فديو|مقطع|دزلي|ارسل", normalized))
        price_word = bool(re.search(r"سعر|سعره|سعرها|بكم|بشكد|شكد|بيش|كم|ناشر|ناشره|ناشرها|ناشرين|ناشرينها|منشور|نشر|اعلان|اعلانكم|بالاعلان", normalized))
        result.mentioned_price = parse_price_reference(normalized) if price_word else None
        result.is_ad_price_reference = bool(result.mentioned_price and re.search(r"ناشر|ناشره|ناشرها|ناشرين|ناشرينها|منشور|اعلان|اعلانكم|بوست|بالاعلان", normalized))

        if re.search(r"\bt\s*c\s*l\b|تي\s*سي\s*ال|تيسيال", normalized):
            result.requested_brand = "TCL"
        elif re.search(r"سامسونج|سامسونك|سامسونگ", normalized):
            result.requested_brand = "Samsung"
        elif re.search(r"\bl\s*g\b|ال\s*جي|الجي", normalized):
            result.requested_brand = "LG"
        elif re.search(r"جنرال", normalized):
            result.requested_brand = "جنرال"

        result.is_accessory_request = bool(re.search(r"ستاند|حامل|ريموت|قاعده|كيبل", normalized))
        water_or_air_cooler = bool(re.search(
            r"براد\s+ماء|براده\s+ماء|مبرد\s+ماء|براد\s+هواء|براد\s+كهرمان(?:ه|ة)|مبرده|مبرد|كولر",
            normalized,
        ))
        fridge_word = bool(
            re.search(r"ثلاجه|ثلاجة|ثلاجات|تلاجه|تلاجة|تلاجات|فريزر", normalized)
            or (re.search(r"براد", normalized) and not water_or_air_cooler)
        )
        screen_word = bool(re.search(r"شاشه|شاشات|تلفزيون|تلفاز|\btv\b", normalized))

        context_family = _context_family(context)
        result.foot_size = _extract_foot_size(normalized)
        if result.foot_size is None and context_family == "refrigerator":
            result.foot_size = _bare_context_foot_size(normalized)
            if result.foot_size is not None:
                result.notes.append("bare_fridge_size_from_context")
        result.preferred_foot_size = preferred_fridge_size(result.foot_size)
        result.screen_size = _extract_screen_size(normalized)

        if result.is_accessory_request and not screen_word and not fridge_word:
            result.family = "accessory"
            result.intent = "product_search" if not price_word else "price_inquiry"
        elif water_or_air_cooler:
            result.family = "cooler"
            result.intent = "price_inquiry" if price_word else "product_search"
        elif fridge_word or result.foot_size:
            result.family = "refrigerator"
            result.intent = "price_inquiry" if price_word else "product_search"
        elif screen_word or (result.screen_size and not result.foot_size and not water_or_air_cooler):
            result.family = "screen"
            result.intent = "price_inquiry" if price_word or result.screen_size else "product_search"
        elif price_word:
            result.intent = "price_inquiry"
            result.needs_product_context = True
            result.is_generic_price_request = not result.requested_brand

        if result.is_gratitude:
            result.intent = "gratitude"
        elif result.is_greeting:
            result.intent = "greeting"
        elif result.is_decline:
            result.intent = "decline"
        if result.family or result.intent not in {"general", "greeting"}:
            result.confidence = 0.9
        return result


class IntentClassifier(CustomerMessageGuard):
    pass


class ProductResolverGuard:
    def resolve(self, message: str, context: dict[str, Any] | None = None) -> MessageGuardResult:
        return CustomerMessageGuard().classify(message, context)


class ProductKnowledgeService:
    @staticmethod
    def default_warranty() -> str:
        return "ضمان سنة"

    @staticmethod
    def default_delivery(product_name: str = "") -> str:
        name = normalize_arabic(product_name)
        if re.search(r"سبلت|سبلت|split", name) and re.search(r"2\s*طن|طنين|2طن", name):
            return "بغداد توصيل مجاني، والمحافظات 15 ألف"
        return "توصيل مجاني"


class AIProductContextService:
    def extract_context(self, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return CustomerMessageGuard().classify(message, context).as_dict()


def classify_customer_message(message: str, context: dict[str, Any] | None = None) -> MessageGuardResult:
    return CustomerMessageGuard().classify(message, context)
