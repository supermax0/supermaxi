"""Deterministic sales decisions that keep the language model grounded."""
from __future__ import annotations

import math
import re
from typing import Any


OBJECTION_LABELS = {
    "none": "",
    "price": "السعر",
    "quality": "الجودة",
    "warranty": "الضمان",
    "delivery": "التوصيل",
    "trust": "الثقة",
    "competitor": "المقارنة مع منافس",
    "hesitation": "التردد",
    "payment": "الدفع",
    "human_request": "طلب موظف",
    "complaint": "شكوى أو غضب",
}

PRIORITY_LABELS = {
    "picture_quality": "جودة الصورة",
    "sound_quality": "جودة الصوت",
    "price": "السعر الاقتصادي",
    "warranty": "الضمان",
    "size": "الحجم",
    "smart_features": "الميزات الذكية والتطبيقات",
    "coverage_speed": "قوة التغطية والسرعة",
}

PRIORITY_TERMS = {
    "picture_quality": ("صورة", "الصوره", "دقة", "الدقه", "4k", "uhd", "full hd", "وضوح"),
    "sound_quality": ("صوت", "ستيريو", "سماعة", "السماعه"),
    "warranty": ("ضمان", "كفالة", "كفاله"),
    "smart_features": ("سمارت", "تطبيق", "نتفلكس", "يوتيوب", "واي فاي"),
    "coverage_speed": ("تغطية", "تغطيه", "سرعة", "سرعه", "5g", "4g", "wifi", "واي فاي"),
}

USAGE_LABELS = {
    "home": "البيت",
    "business": "المحل أو الاستخدام التجاري",
}

ROOM_LABELS = {
    "small": "غرفة صغيرة",
    "medium": "غرفة متوسطة",
    "large": "غرفة أو صالة كبيرة",
}

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _normalize(value: str) -> str:
    table = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
    value = (value or "").translate(_DIGITS).translate(table).lower()
    value = re.sub(r"[\u064b-\u065f\u0670ـ]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _customer_turns(history: list[dict]) -> list[str]:
    return [
        str(row.get("content") or "")
        for row in history or []
        if row.get("role") == "user" and row.get("content")
    ]


def _first_matching_source(message: str, history: list[dict], pattern: str) -> re.Match | None:
    sources = [message, *reversed(_customer_turns(history))]
    for source in sources:
        match = re.search(pattern, _normalize(source))
        if match:
            return match
    return None


def update_customer_facts(
    message: str,
    history: list[dict],
    existing: dict | None = None,
    *,
    budget: int | None = None,
) -> dict[str, Any]:
    """Merge confirmed customer facts, preferring the newest customer turn."""
    facts = dict(existing or {})
    normalized = _normalize(message)
    if budget:
        facts["budget"] = int(budget)

    usage = _first_matching_source(
        message,
        history,
        r"(?:لل|بال|ل)?بيت\b|للمنزل|بالمنزل|منزلي|(?:لل|بال|ل)?محل\b|للمتجر|بالمتجر|تجاري",
    )
    if usage:
        facts["usage"] = "business" if re.search(r"محل|متجر|تجاري", usage.group(0)) else "home"

    room = _first_matching_source(
        message,
        history,
        r"(?:غرفه|صاله|مكان).{0,16}(صغيره|صغير|متوسطه|متوسط|كبيره|كبير)",
    )
    if room:
        descriptor = room.group(1)
        facts["room_size"] = "small" if descriptor.startswith("صغير") else "large" if descriptor.startswith("كبير") else "medium"

    distance = _first_matching_source(
        message,
        history,
        r"(?:مسافه|بعد).{0,16}?(\d+(?:[.,]\d+)?)\s*(?:متر|م\b)",
    )
    if distance:
        try:
            meters = float(distance.group(1).replace(",", "."))
        except (TypeError, ValueError):
            meters = 0
        if 0.5 <= meters <= 10:
            facts["viewing_distance_m"] = int(meters) if meters.is_integer() else round(meters, 1)

    size = _first_matching_source(
        message,
        history,
        r"(?:حجم|مقاس|شاشه)\s*(\d{2})\b|\b(\d{2})\s*(?:بوصه|انج)",
    )
    if size:
        facts["requested_size"] = int(size.group(1) or size.group(2))
        facts.pop("requested_foot_size", None)

    foot_size = _first_matching_source(
        message,
        history,
        r"(?<!\d)(\d{1,2})\s*(?:قدم|قدام|ft)\b",
    )
    if not foot_size:
        from .product_tools import parse_foot_size
        spoken = parse_foot_size(message) or next(
            (
                parse_foot_size(str(row.get("content") or ""))
                for row in reversed(history or [])
                if row.get("role") == "user" and parse_foot_size(str(row.get("content") or ""))
            ),
            None,
        )
        if spoken:
            facts["requested_foot_size"] = int(spoken)
            facts.pop("requested_size", None)
    elif foot_size:
        facts["requested_foot_size"] = int(foot_size.group(1))
        facts.pop("requested_size", None)

    from .product_tools import requested_product_features
    requested_features = requested_product_features(message)
    if not requested_features:
        for row in reversed(history or []):
            if row.get("role") != "user":
                continue
            prior = requested_product_features(str(row.get("content") or ""))
            if prior:
                requested_features = prior
                break
    if requested_features:
        facts["requested_features"] = requested_features

    brand = re.search(r"(?:ماركه|براند)\s+([\w\u0600-\u06ff-]{2,30}(?:\s+[\w\u0600-\u06ff-]{2,30})?)", normalized)
    if brand:
        facts["preferred_brand"] = brand.group(1).strip()

    priority_patterns = (
        ("picture_quality", r"(?:اهم|المهم|اريد|افضل).{0,24}(?:الصوره|الدقه|وضوح)|(?:الصوره|الدقه).{0,18}(?:زين|واضح|جود|افضل)"),
        ("sound_quality", r"(?:اهم|المهم|اريد|افضل).{0,24}(?:الصوت)|الصوت.{0,18}(?:زين|واضح|قوي|جود)"),
        ("coverage_speed", r"(?:اهم|المهم|اريد|افضل).{0,24}(?:التغطيه|السرعه|الواي فاي)|(?:تغطيه|سرعه).{0,18}(?:قوي|زين|افضل)"),
        ("warranty", r"(?:اهم|المهم|اريد).{0,20}الضمان|ضمان.{0,12}(?:طويل|اهم|مهم)"),
        ("smart_features", r"(?:اهم|المهم|اريد).{0,24}(?:سمارت|تطبيقات|نتفلكس|يوتيوب)"),
        ("size", r"(?:اهم|المهم|اريد).{0,18}(?:الحجم|المقاس)|(?:حجم|مقاس).{0,12}(?:اكبر|كبير)"),
        ("price", r"(?:اهم|المهم).{0,18}(?:السعر|رخيص|اقتصادي)|اريد.{0,18}(?:ارخص|اوفر)"),
    )
    sources = [normalized, *[_normalize(value) for value in reversed(_customer_turns(history))]]
    for source in sources:
        matched = next((key for key, pattern in priority_patterns if re.search(pattern, source)), None)
        if matched:
            facts["priority"] = matched
            break

    if re.search(
        r"(?:قارن|اعتمد|رشح|اختار).{0,30}(?:الحجم|المقاس).{0,20}(?:السعر|الميزانيه)"
        r"|(?:قارن|اعتمد|رشح|اختار).{0,30}(?:السعر|الميزانيه).{0,20}(?:الحجم|المقاس)",
        normalized,
    ):
        facts["decision_basis"] = "size_price"

    return {key: value for key, value in facts.items() if value not in (None, "", [])}


def facts_for_prompt(facts: dict | None) -> dict[str, Any]:
    facts = facts or {}
    result: dict[str, Any] = {}
    if facts.get("budget"):
        result["الميزانية"] = int(facts["budget"])
    if facts.get("usage"):
        result["الاستخدام"] = USAGE_LABELS.get(str(facts["usage"]), str(facts["usage"]))
    if facts.get("priority"):
        result["الأولوية"] = PRIORITY_LABELS.get(str(facts["priority"]), str(facts["priority"]))
    if facts.get("requested_size"):
        result["الحجم المطلوب"] = int(facts["requested_size"])
    if facts.get("requested_foot_size"):
        result["القياس المطلوب"] = f"{int(facts['requested_foot_size'])} قدم"
    if facts.get("requested_features"):
        labels = {
            "two_door": "بابين",
            "single_door": "باب واحد",
        }
        result["المواصفة المطلوبة"] = "، ".join(
            labels.get(str(value), str(value))
            for value in facts["requested_features"]
        )
    if facts.get("room_size"):
        result["حجم المكان"] = ROOM_LABELS.get(str(facts["room_size"]), str(facts["room_size"]))
    if facts.get("viewing_distance_m"):
        result["مسافة المشاهدة"] = f"{facts['viewing_distance_m']} متر"
    if facts.get("preferred_brand"):
        result["الماركة المفضلة"] = str(facts["preferred_brand"])
    if facts.get("decision_basis") == "size_price":
        result["أساس القرار"] = "الحجم والسعر"
    return result


def classify_objection(message: str) -> str:
    text = _normalize(message)
    patterns = (
        ("human_request", r"(?:اريد|حولني|خليني|احجي|اكلم).{0,20}(?:موظف|انسان|مسؤول|مدير)"),
        ("complaint", r"نصب|احتيال|كذاب|سيئ|زفت|معصب|شكوى|اشتكي|ما تحترمون|خربان"),
        ("price", r"غالي|غاليه|سعره عالي|سعرها عالي|ارخص|نزل بالسعر|فوق الميزانيه|ما اكدر|ما اقدر|بي(?:ه)? مجال|اكو مجال|مجال بالسعر|اخر سعر|سعر(?:ه|ها|نا|كم|ك)? نهائي|يصير اقل|تنقص|تخفض|تراعي"),
        ("warranty", r"ضمان|كفاله|يتصلح|صيانه"),
        ("delivery", r"عندكم.{0,12}توصيل|اكو.{0,12}توصيل|توصيل.{0,16}(?:مجاني|بكم|شكد|متوفر)|شكد.{0,12}يوصل|متى.{0,12}يوصل|التاخير|تاخير|اجور النقل"),
        ("quality", r"الجوده|نوعيته|اصلي|تقليد|يخرب|يتحمل|الصوره مو زينه"),
        ("trust", r"اثق|مضمون|شلون اضمن|مو واثق|مجرب"),
        ("competitor", r"غيركم|محل ثاني|صفحه ثانيه|عندهم ارخص|المنافس"),
        ("payment", r"تقسيط|دفع|فيزا|بطاقه|تحويل|عربون"),
        ("hesitation", r"افكر|اشوف|بعدين|مو هسه|اتردد|ما ادري|محتار|استشير"),
    )
    return next((kind for kind, pattern in patterns if re.search(pattern, text)), "none")


def product_knowledge_score(product: dict) -> int:
    score = 0
    if str(product.get("description") or "").strip():
        score += 20
    if product.get("selling_points"):
        score += 25
    if product.get("ideal_for"):
        score += 15
    if str(product.get("warranty") or "").strip():
        score += 10
    if str(product.get("delivery") or "").strip():
        score += 10
    if product.get("objection_guidance"):
        score += 10
    if str(product.get("sales_notes") or "").strip():
        score += 5
    if str(product.get("image_url") or "").strip():
        score += 5
    return min(score, 100)


def _product_size(name: str) -> int | None:
    values = [int(value) for value in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", _normalize(name))]
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
    match = re.search(r"(?<!\d)(\d{1,2})\s*(?:قدم|ft)\b", _normalize(name))
    return int(match.group(1)) if match else None


def _product_searchable_knowledge(product: dict) -> str:
    from .product_tools import product_knowledge_blob
    return product_knowledge_blob(product)


def priority_evidence_available(products: list[dict], priority: str) -> bool:
    terms = PRIORITY_TERMS.get(priority, ())
    return bool(terms) and any(
        any(term in _product_searchable_knowledge(product) for term in terms)
        for product in products or []
    )


def rank_products_for_customer(products: list[dict], facts: dict | None) -> list[dict]:
    """Rank live candidates and attach internal, grounded recommendation signals."""
    facts = facts or {}
    budget = int(facts.get("budget") or 0)
    requested_size = int(facts.get("requested_size") or 0)
    requested_foot_size = int(facts.get("requested_foot_size") or 0)
    requested_features = list(facts.get("requested_features") or [])
    room_size = str(facts.get("room_size") or "")
    viewing_distance = float(facts.get("viewing_distance_m") or 0)
    priority = str(facts.get("priority") or "")
    room_target = {"small": 43, "medium": 50, "large": 65}.get(room_size, 0)
    distance_target = 43 if 0 < viewing_distance <= 2.2 else 50 if viewing_distance <= 3.2 and viewing_distance else 65 if viewing_distance else 0
    target_size = requested_size or distance_target or room_target
    ranked = []
    for index, source in enumerate(products or []):
        row = dict(source)
        score = max(10.0, 40.0 - index)
        reasons: list[str] = []
        price = int(row.get("price") or 0)
        stock = int(row.get("stock") or 0)
        size = _product_size(str(row.get("name") or ""))
        foot_size = _product_foot_size(str(row.get("name") or ""))
        knowledge = product_knowledge_score(row)

        if budget and price:
            if price <= budget:
                score += 18
                reasons.append("ضمن الميزانية")
                score += min(max(((budget - price) / budget) * 6, 0), 6)
            else:
                score -= min(((price - budget) / budget) * 60, 50)
        if target_size and size:
            distance = abs(size - target_size)
            if distance == 0:
                score += 30 if requested_size else 22
                reasons.append("الحجم المطلوب مطابق" if requested_size else "حجمه مناسب لمسافة المشاهدة أو حجم الغرفة")
            elif distance <= 5:
                score += 14
                reasons.append("حجمه قريب من المطلوب" if requested_size else "حجمه قريب من المناسب للمكان")
            else:
                score -= min(distance, 20)
        if requested_foot_size:
            if foot_size == requested_foot_size:
                score += 35
                reasons.append(f"القياس المطلوب مطابق: {requested_foot_size} قدم")
            elif foot_size:
                score -= min(abs(foot_size - requested_foot_size) * 20, 60)
        if requested_features:
            from .product_tools import product_matches_requested_features
            if product_matches_requested_features(row, requested_features):
                score += 45
                reasons.append("يطابق المواصفة المطلوبة")
            else:
                score -= 70
        searchable = _product_searchable_knowledge(row)
        matched_priority = priority and any(term in searchable for term in PRIORITY_TERMS.get(priority, ()))
        if matched_priority:
            score += 20
            reasons.append(f"يطابق أولوية {PRIORITY_LABELS.get(priority, priority)}")
        if facts.get("usage") == "home" and any(term in searchable for term in ("منزل", "البيت", "غرفه", "صاله")):
            score += 8
            reasons.append("مناسب للاستخدام المنزلي")
        if stock > 0:
            score += min(2 + math.log2(stock + 1), 8)
        score += knowledge * 0.12
        if knowledge >= 60:
            reasons.append("بياناته ومزاياه موثقة")

        row["knowledge_score"] = knowledge
        row["recommendation_score"] = round(max(0, min(score, 100)), 1)
        row["recommendation_reasons"] = reasons[:4]
        ranked.append(row)
    return sorted(
        ranked,
        key=lambda row: (
            -float(row.get("recommendation_score") or 0),
            int(row.get("price") or 0),
            -int(row.get("stock") or 0),
        ),
    )


def next_best_action(
    facts: dict,
    objection: str,
    *,
    purchase_intent: bool,
    products: list[dict],
) -> str:
    if objection in {"human_request", "complaint"}:
        return "تحويل المحادثة إلى موظف مختص"
    if purchase_intent:
        return "جمع الاسم ورقم الهاتف وعنوان مختصر أو رابط موقع ثم عرض ملخص الطلب للتأكيد"
    objection_actions = {
        "price": "عرض بديل أوفر حقيقي وشرح الفرق باختصار",
        "quality": "شرح دليل الجودة المسجل أو التصريح بأن المعلومة غير مسجلة",
        "warranty": "توضيح الضمان المسجل للمنتج فقط",
        "delivery": "توضيح سياسة التوصيل المسجلة أو تحويل السؤال لموظف",
        "trust": "تقليل المخاطرة بحقائق الضمان والسياسة المسجلة من دون وعود",
        "competitor": "عمل مقارنة واقعية بالحقائق المتاحة من دون مهاجمة المنافس",
        "hesitation": "تلخيص أفضل خيارين وتقليل القرار إلى سؤال واحد",
        "payment": "توضيح طرق الدفع المسجلة أو تحويل الطلب لموظف",
    }
    if objection in objection_actions:
        return objection_actions[objection]
    if not products:
        return "تحديد المنتج المطلوب بسؤال واحد واضح"
    if len(products) == 1 and (facts.get("requested_size") or facts.get("requested_foot_size")):
        return "تأكيد المنتج المطابق وجمع الاسم ورقم الهاتف وعنوان مختصر أو رابط موقع تدريجياً"
    if not facts.get("usage"):
        return "معرفة مكان أو نوع الاستخدام"
    if len(products) > 1 and not facts.get("budget"):
        return "معرفة الميزانية القصوى"
    if len(products) > 1 and not facts.get("priority"):
        return "عرض ميزات المنتج المتوفرة حالياً ثم سؤال هل يناسب الزبون"
    product_names = " ".join(str(row.get("name") or "") for row in products)
    if (
        len(products) > 1
        and re.search(r"شاشه|تلفزيون|تلفاز", _normalize(product_names))
        and not facts.get("requested_size")
        and not facts.get("room_size")
        and not facts.get("viewing_distance_m")
    ):
        return "معرفة حجم الغرفة أو مسافة المشاهدة قبل التوصية النهائية"
    priority = str(facts.get("priority") or "")
    if (
        priority in PRIORITY_TERMS
        and facts.get("decision_basis") != "size_price"
        and not priority_evidence_available(products, priority)
    ):
        label = PRIORITY_LABELS.get(priority, priority)
        return f"توضيح أن مواصفات {label} غير مسجلة والمقارنة بالحجم والسعر فقط"
    if len(products) > 1:
        return "مقارنة أفضل خيارين وتقديم توصية مبررة"
    return "تأكيد ملاءمة الخيار وطلب خطوة الشراء التالية"


def calculate_lead_state(
    previous_score: int,
    facts: dict,
    products: list[dict],
    *,
    objection: str,
    purchase_intent: bool,
    model_intent: str = "",
) -> tuple[int, str]:
    score = 12
    if products:
        score += 18
    score += 12 if facts.get("budget") else 0
    score += 6 if facts.get("usage") else 0
    score += 6 if facts.get("priority") else 0
    score += 6 if facts.get("requested_size") else 0
    score += 6 if facts.get("requested_foot_size") else 0
    score += 4 if facts.get("room_size") or facts.get("viewing_distance_m") else 0
    score += 3 if facts.get("decision_basis") else 0
    score += 5 if facts.get("preferred_brand") else 0
    if objection not in {"none", "human_request", "complaint"}:
        score += 10
    if model_intent in {"comparison", "product_question", "price_objection"}:
        score += 8
    if purchase_intent or model_intent in {"purchase", "order_details"}:
        score = max(score + 25, 82)
    if objection == "complaint":
        score = min(score, 30)
    score = max(score, max(int(previous_score or 0) - 3, 0))
    score = max(0, min(int(score), 100))
    temperature = "hot" if score >= 70 else "warm" if score >= 35 else "cold"
    return score, temperature


def adaptive_reasoning_effort(
    level: str,
    message: str,
    *,
    objection: str = "none",
    purchase_intent: bool = False,
    history_count: int = 0,
    fact_count: int = 0,
) -> str:
    level = (level or "expert").lower()
    if level == "fast":
        return "minimal"
    if level == "professional":
        return "low"
    text = _normalize(message)
    complex_turn = (
        objection != "none"
        or purchase_intent
        or history_count >= 8
        or fact_count >= 3
        or bool(re.search(r"ميزاني|بحدود\s+\d|حدي\s+\d", text))
        or bool(re.search(r"قارن|مقارنه|الفرق|شنو الافضل|اي واحد افضل", text))
    )
    if level == "elite":
        return "medium" if complex_turn else "low"
    return "medium" if complex_turn else "low"
