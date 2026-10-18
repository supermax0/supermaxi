"""Deterministic Arabic (incl. Iraqi dialect) extraction: business facts, contact identifiers and intents.

Two jobs:
1. A safe fallback when the AI provider is unavailable (the brain still understands the basics).
2. Grounding: a numeric fact proposed by the model is only trusted if the customer's own words contain it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize(text: str) -> str:
    """Matching form: no diacritics/tatweel, unified alef/ya/ta-marbuta, ASCII digits, single spaces, lowercase."""
    t = _TASHKEEL.sub("", text or "").translate(_ARABIC_DIGITS)
    t = re.sub("[إأآٱ]", "ا", t).replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    t = t.replace("چ", "ج").replace("گ", "ك").replace("ڤ", "ف").replace("پ", "ب")
    return re.sub(r"\s+", " ", t).strip().lower()


_NUMBER_WORDS = {
    "واحد": 1, "وحده": 1, "وحد": 1, "اثنين": 2, "ثنين": 2, "اثنان": 2, "اثنتين": 2, "ثلاث": 3, "ثلاثه": 3, "ثلث": 3,
    "اربع": 4, "اربعه": 4, "خمس": 5, "خمسه": 5, "ست": 6, "سته": 6, "سبع": 7, "سبعه": 7, "ثمان": 8, "ثمانيه": 8,
    "ثمن": 8, "تسع": 9, "تسعه": 9, "عشر": 10, "عشره": 10,
}
_NUM = r"(\d{1,4}|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")"

# noun stems (normalized). Duals ("طبيبين", "فرعين") imply 2 when no number is given.
_COUNT_NOUNS = {
    "doctors": (r"(?:اطباء|طبيب|طبيبه|دكاتره|دكتور|دكتوره|اطبا)", r"(?:طبيبين|دكتورين)"),
    "employees": (r"(?:موظفين|موظف|موظفه|موظفات|موضف|موضفه|عمال|عامل|كادر|سكرتير|سكرتيره|استقبال)", r"(?:موظفتين)"),
    "branches": (r"(?:فروع|فرع)", r"(?:فرعين)"),
}

_BUSINESS = [
    (r"(?:محل|بياع|بايع|بيع|متجر)\s+(?:ال)?(?:ورد|زهور)|(?:ورد|زهور)\s+وهدايا", "starter_business", None),
    # (pattern, businessType, specialty)
    (r"(?:عياده|عيادات|مركز|طب|طبيب|دكتور)\s+(?:ال)?اسنان|اسنان", "clinic", "dentistry"),
    (r"(?:عياده|مركز)\s+(?:ال)?جلديه|جلديه|تجميل\s+طبي", "clinic", "dermatology"),
    (r"(?:عياده|مركز)\s+(?:ال)?نساييه|نساييه\s+وتوليد|توليد", "clinic", "gynecology"),
    (r"(?:عياده|مركز)\s+(?:ال)?اطفال|طب\s+اطفال", "clinic", "pediatrics"),
    (r"(?:عياده|مركز)\s+(?:ال)?قلبيه|امراض\s+القلب", "clinic", "cardiology"),
    (r"(?:عياده|مركز)\s+(?:ال)?باطنيه", "clinic", "internal_medicine"),
    (r"عياده|عيادات|مجمع\s+طبي|مستوصف", "clinic", None),
    (r"مركز\s+تجميل|صالون|بيوتي|سبا", "beauty_center", None),
    (r"موارد\s+(?:ال)?بشريه|شوون\s+الموظفين|اداره\s+الموظفين", "hr_management", None),
    (r"اعمال\s+(?:مبسطه|بسيطه)|نشاط\s+مبسط", "starter_business", None),
    (r"شركه\s+عامه|نشاط\s+عام", "general", None),
    (r"مواد\s+غذاييه|سوبر\s*ماركت|ماركت|بقاله|اسواق", "food_wholesale_retail", None),
    (r"جمله|تجاره\s+جمله|مخزن\s+جمله", "wholesale", None),
    (r"صيدليه", "pharmacy", None),
    (r"مطعم|كافيه|مطاعم", "restaurant", None),
    (r"ملابس|بوتيك|احذيه|اكسسوارات|متجر|محل|اونلاين", "commerce", None),
]

_PHONE = re.compile(r"(?<!\d)(?:\+?964|00964|0)?\s?(7[3-9]\d)[\s-]?(\d{3})[\s-]?(\d{4})(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,180}\.[A-Za-z]{2,24}")
_PERCENT = re.compile(r"(\d{1,3})\s*(?:%|٪|بالميه|في\s*الميه|بالميه)")

INTENTS = (
    "greeting", "pricing", "feature_question", "business_setup", "clinic_setup", "commerce_setup",
    "technical_support", "account_creation", "training_request", "subscription", "complaint",
    "human_request", "discount_request", "unknown",
)

# Patterns are written in normalize() form (ي not ى/ئ, ه not ة, ا not أ/إ) — they match normalized text.
_INTENT_RULES: list[tuple[str, str]] = [
    ("greeting", r"^(?:السلام|سلام|مرحبا|هلو|هلا|اهلا|صباح|مساء|hi\b|hello\b)"),
    ("pricing", r"سعر|اسعار|بكم|كم\s+(?:يكلف|يكلفني|السعر|سعره|الاشتراك|المبلغ)|كلفه|الباقات|باقه|price|cost"),
    ("discount_request", r"خصم|تخفيض|تنزيل\s+(?:بالسعر|السعر)|عرض\s+خاص|discount"),
    ("account_creation", r"(?:افتح|سوو?(?:لي)?|سوي(?:لي)?|اعمل|اسوي|انشي|انشاء|ابي|اريد|جهز(?:لي)?)\s+(?:لي\s+)?حساب|حساب\s+تجريبي|اجرب|تجربه|trial|سجلني"),
    ("training_request", r"شلون\s+|كيف\s+|وين\s+(?:اضيف|القي|اسوي|الكه|احصل)|علمني|تعليم|خطوات|how\s+(?:do|can|to)|show\s+me"),
    ("technical_support", r"ما\s*(?:يشتغل|يفتح|يحفظ|يطلع|تظهر|تفتح|تشتغل|القي|الكه)|القسم\s+مختفي|مشكله\s+(?:ب|في)|خطا|error|عطل|علق|ما\s*اكدر\s+(?:ادخل|افتح)"),
    ("subscription", r"اشتراك|تجديد|اجدد|الدفع|ادفع|فاتوره\s+الاشتراك|subscription"),
    ("complaint", r"شكوي|زعلان|سيء|خايس|ما\s*عاجبني|نصب|احتيال|complain"),
    ("human_request", r"(?:اريد|ابي|اكدر)\s+(?:احجي|اتكلم|احكي)|موظف\s+حقيقي|انسان|(?<![؀-ۿ])(?:ال)?بشري(?![؀-ۿ])|رقمكم|اتصلو(?:ا)?\s+بي|كلموني|اتصل\s+بيه|human|agent"),
    ("feature_question", r"هل\s+(?:النظام|البرنامج|يدعم|يوجد|يكدر|اكدر)|يدعم|فيه\s+(?:خاصيه|ميزه)|يصير\s+(?:اسوي|اربط)|ممكن\s+(?:اسوي|اربط|اضيف)"),
]


@dataclass
class Extraction:
    facts: dict[str, Any] = field(default_factory=dict)
    intents: dict[str, float] = field(default_factory=dict)
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    discount_percent: int | None = None


def _num(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token)


def extract(text: str, *, waiting: str | None = None) -> Extraction:
    t = normalize(text)
    out = Extraction()
    # "اسم المحل ..." supplies a name; it does not change the already-known business activity.
    business_text = re.split(r"(?:اسم\s+(?:(?:ال)?(?:عياده|محل|شركه|متجر|مركز|نشاط))|اسمها|اسمه)\s", t, maxsplit=1)[0]
    if re.search(_BUSINESS[0][0], business_text):
        out.facts["businessProfile"] = "flowers"
    for key, (noun, dual) in _COUNT_NOUNS.items():
        value = None
        other_nouns = "|".join(pattern for other, (pattern, _) in _COUNT_NOUNS.items() if other != key)
        m = re.search(rf"{_NUM}\s*(?:من\s+)?(?:ال)?{noun}(?![؀-ۿ])", t) or re.search(
            rf"(?:ال)?{noun}\s*(?:عددهم|عدد|عدنا)?\s*{_NUM}(?![؀-ۿ\d])(?!\s*(?:من\s+)?(?:ال)?(?:{other_nouns})(?![؀-ۿ]))", t
        )
        if m:
            value = _num(m.group(1))
        elif re.search(rf"(?<![؀-ۿ])(?:و|ب)?(?:ال)?{dual}(?![؀-ۿ])", t):  # "وفرعين"
            value = 2
        elif key == "branches" and re.search(r"(?<![؀-ۿ])فرع\s+واحد", t):
            value = 1
        elif key == "employees" and re.search(r"(?<![؀-ۿ])(?:موظف|موضف|موظفه|موضفه)\s+استقبال(?![؀-ۿ])", t):
            value = 1
        if value is not None and 0 < value <= (500 if key != "branches" else 200):
            out.facts[key] = value
    for pattern, btype, specialty in _BUSINESS:
        if re.search(pattern, business_text):
            out.facts["businessType"] = btype
            if specialty:
                out.facts["specialty"] = specialty
            break
    for m in _PHONE.finditer(text.translate(_ARABIC_DIGITS)):
        out.phones.append(f"+964{m.group(1)}{m.group(2)}{m.group(3)}")
    out.emails = [e.lower() for e in _EMAIL.findall(text)]
    # Literal location answers are reliable profile data, not low-confidence sales questions.
    if re.fullmatch(r"(?:الدوله\s+)?(?:العراق|عراق)(?:\s+بغداد)?[.!،]?", t):
        out.facts["country"] = "العراق"
    for city in ("بغداد", "البصره", "النجف", "كربلاء", "الموصل", "اربيل", "السليمانيه", "دهوك", "كركوك", "الناصريه", "الحله", "الديوانيه", "الكوت", "العماره", "الرمادي", "بعقوبه", "تكريت", "السماوه"):
        stated = re.fullmatch(rf"(?:العراق\s+)?(?:في\s+|ب)?{city}[.!،]?", t) or re.search(
            rf"(?:مدينتي|مدينه|المدينه|محافظتي|موقعي|عنواني|موقعنا|بال|احنا في|احنه في)\s*[:：]?\s+{city}(?![؀-ۿ])", t)
        if stated and not re.search(rf"(?:مو|ليس|مش|غير)\s+{city}", t):
            out.facts["city"] = city
            break
    name = re.search(r"(?:اسم\s+(?:(?:ال)?(?:عياده|محل|شركه|متجر|مركز|نشاط))|اسمها|اسمه)\s*[:：]?\s+(.+?)(?=\s+(?:ورقمي|رقمي|وهاتفي|هاتفي|واريد|وسوولي|وسويلي)|$)", t)
    if name and not re.search(r"[؟?]|^(?:شنو|ما|ليش|شو|كيف|شلون)\b", t):
        out.facts["businessName"] = name.group(1).strip(" .،")[:150]
    elif waiting == "businessName" and not out.phones and not out.emails and not re.fullmatch(r"[\d\s+.-]+", t) and 1 < len(text.strip()) <= 150 and not re.search(r"[؟?\n]|^(?:لا|نعم|تمام|مرحبا|هلا|كمل)\b|سويلي|سوولي|حساب|شلون|مشكله|مو\s", t):
        out.facts["businessName"] = text.strip()
    if "businessName" in out.facts and re.search(r"https?://|\b(?:sk|pk|rk)-[A-Za-z0-9_-]{10,}|\b[0-9]{5,20}:[A-Za-z0-9_-]{20,200}\b", out.facts["businessName"]):
        out.facts.pop("businessName")
    if m := _PERCENT.search(t):
        out.discount_percent = int(m.group(1))
    for intent, pattern in _INTENT_RULES:
        if re.search(pattern, t):
            out.intents[intent] = 0.75
    if "account_creation" in out.intents and re.search(r"(?:لا|ما|مو)\s+(?:تسوي|تسوولي|تسويلي|تجهز|تفتح|اريد)|الغ[ياء]?\s+(?:ال)?(?:حساب|طلب)", t):
        out.intents.pop("account_creation")
    if out.facts.get("businessType") and re.search(r"عندي|عدنا|عدي|لدي|لدينا|اريد\s+نظام|ابي\s+نظام", t):
        setup = {"clinic": "clinic_setup"}.get(out.facts["businessType"], "commerce_setup"
                                               if out.facts["businessType"] in {"commerce", "food_wholesale_retail", "wholesale", "restaurant", "pharmacy"}
                                               else "business_setup")
        out.intents[setup] = 0.8
    if not out.intents:
        out.intents["unknown"] = 0.3
    return out


def number_grounded(value: Any, text: str) -> bool:
    """True if the customer's text literally contains the number (digits or Arabic word, or a dual form for 2)."""
    if not isinstance(value, int):
        return False
    t = normalize(text)
    if re.search(rf"(?<!\d){value}(?!\d)", t):
        return True
    words = [w for w, n in _NUMBER_WORDS.items() if n == value]
    if any(re.search(rf"(?<![؀-ۿ]){w}(?![؀-ۿ])", t) for w in words):
        return True
    return value == 2 and bool(re.search(r"(?:طبيبين|دكتورين|موظفتين|فرعين)", t))
