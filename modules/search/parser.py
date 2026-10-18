"""Turns a shopper's phrase into intent: category, brand, model code, capacities, features, budget, free terms."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from modules.search import lexicon as L

_MONEY = re.compile(r"(\d+(?:[.,]\d+)?)\s*(الف|الاف|ك|k|مليون|ملايين|m)?")


@dataclass
class Intent:
    raw: str
    text: str
    category: str | None = None
    brand: str | None = None
    codes: list[str] = field(default_factory=list)  # model numbers / barcodes typed as such
    size_inch: float | None = None
    ton: float | None = None
    kg: float | None = None
    features: set[str] = field(default_factory=set)
    max_price: int | None = None
    min_price: int | None = None
    terms: list[str] = field(default_factory=list)


def _money(amount: str, unit: str | None) -> int:
    value = float(amount.replace(",", "."))
    if unit in ("مليون", "ملايين", "m"):
        return int(value * 1_000_000)
    if unit in ("الف", "الاف", "ك", "k") or value < 10_000:
        return int(value * 1000)  # «400» in a budget phrase means 400 thousand dinars
    return int(value)


def _remove(text: str, phrase: str) -> str:
    return re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", " ", text)


def parse(query: str, *, synonyms: dict[str, str] | None = None) -> Intent:
    text = L.normalize(query)
    for word, canonical in (synonyms or {}).items():  # company synonyms first («كاونتر» → «ثلاجه» …)
        text = re.sub(rf"(?<!\w){re.escape(L.normalize(word))}(?!\w)", L.normalize(canonical), text)
    intent = Intent(raw=query, text=text)
    work = f" {text} "

    # budget: «بأقل من 400 الف» / «تحت مليون» / «ضمن 500 الف» / «من 300 الى 600 الف»
    rng = re.search(r"من\s+(\d+(?:[.,]\d+)?)\s*(الف|مليون)?\s+(?:الي|ل|-)\s+(\d+(?:[.,]\d+)?)\s*(الف|الاف|مليون)?", work)
    if rng:
        unit = rng.group(4) or rng.group(2)
        intent.min_price, intent.max_price = _money(rng.group(1), rng.group(2) or unit), _money(rng.group(3), unit)
        work = work.replace(rng.group(0), " ")
    m = re.search(r"(?:باقل من|اقل من|تحت|ما يتجاوز|لا يتجاوز|ضمن|حدود|بحدود|ب حدود|الي|لحد)\s+(\d+(?:[.,]\d+)?)\s*(الف|الاف|مليون|ملايين)?", work)
    if m:
        intent.max_price = _money(m.group(1), m.group(2))
        work = work.replace(m.group(0), " ")
    elif re.search(r"(?:باقل من|اقل من|تحت|ضمن|حدود|بحدود|لحد)\s+(نص مليون|مليونين|مليون)(?!\w)", work):
        m2 = re.search(r"(?:باقل من|اقل من|تحت|ضمن|حدود|بحدود|لحد)\s+(نص مليون|مليونين|مليون)(?!\w)", work)
        intent.max_price = {"نص مليون": 500_000, "مليونين": 2_000_000}.get(m2.group(1), 1_000_000)
        work = work.replace(m2.group(0), " ")
    elif re.search(r"(?<!\d)(مليون|مليونين)(?!\w)", work) and re.search(r"عندي|ميزانيه|بميزانيه|ب ", work):
        intent.max_price = 2_000_000 if "مليونين" in work else 1_000_000
        work = re.sub(r"(?<!\w)(مليون|مليونين)(?!\w)", " ", work)

    # units
    if re.search(r"طن\s*(?:و\s*)?نص|طن\s*ونصف|1\.5\s*طن", work):
        intent.ton = 1.5
    elif re.search(r"(?<!\w)طنين(?!\w)|2\s*طن", work):
        intent.ton = 2.0
    elif re.search(r"(?<!\w)(?:1\s*)?طن(?!\w)", work):
        intent.ton = 1.0
    work = re.sub(r"\d*(?:\.\d+)?\s*(?:طن\s*(?:و\s*)?نصف?|طنين|طن)", " ", work)
    k = re.search(r"(\d+(?:\.\d+)?)\s*(?:كيلو|كغم|كغ|kg|كيلوغرام)", work)
    if k:
        intent.kg = float(k.group(1))
        work = work.replace(k.group(0), " ")
    inch = re.search(r"(\d{2,3})\s*(?:انج|انش|بوصه|inch|\"|in)(?!\w)", work)
    if inch:
        intent.size_inch = float(inch.group(1))
        work = work.replace(inch.group(0), " ")
    for phrase, number in sorted(L.NUMBER_WORDS.items(), key=lambda kv: -len(kv[0])):
        if f" {phrase} " in work:
            intent.size_inch = intent.size_inch or float(number)
            work = _remove(work, phrase)

    # brand (longest spelling first so «ال جي» wins over «ال»)
    for brand, words in L.BRAND_WORDS.items():
        for w in sorted(words, key=len, reverse=True):
            if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", work):
                intent.brand = intent.brand or brand
                work = _remove(work, w)

    # features
    for feature, words in L.FEATURE_WORDS.items():
        for w in words:
            if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", work):
                intent.features.add(feature)
                if feature not in ("twin_tub", "front_load"):
                    work = _remove(work, w)

    # category
    for category, words in L.CATEGORY_WORDS.items():
        for w in sorted(words, key=len, reverse=True):
            if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", work):
                if w in L.GENERIC_ONLY and intent.category:
                    continue
                intent.category = category if not intent.category or len(w) > 4 else intent.category
                work = _remove(work, w)

    # a bare screen size after a TV word: «شاشه 55»
    if intent.category == "شاشات" and intent.size_inch is None:
        bare = re.search(r"(?<![\w.])(24|32|40|42|43|50|55|58|60|65|70|75|85|86|98|100)(?![\w.])", work)
        if bare:
            intent.size_inch = float(bare.group(1))
            work = work.replace(bare.group(0), " ", 1)

    # model numbers / barcodes: mixed letters+digits (55C7K, UA55CU7000) or ≥ 8 digits
    for token in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", work):
        if (re.search(r"[a-z]", token) and re.search(r"\d", token)) or re.fullmatch(r"\d{8,14}", token):
            intent.codes.append(L.compact(token))
            work = work.replace(token, " ", 1)

    intent.terms = [t for t in work.split() if len(t) >= 2 and t not in L.STOP_WORDS and not t.isdigit()]
    return intent


_TON15 = re.compile(r"طن\s*(?:و\s*)?نص|1\.5\s*طن|18000\s*btu|18\s*الف")
_TON2 = re.compile(r"(?<!\w)طنين(?!\w)|2\s*طن|24000\s*btu")
_TON1 = re.compile(r"(?<![\w.])1?\s*طن(?!\w)|12000\s*btu")
_KG = re.compile(r"(\d+(?:\.\d+)?)\s*(?:كيلو|كغم|كغ|kg)")
_INCH = re.compile(r"(\d{2,3})\s*(?:انج|انش|بوصه|inch|\"|in)(?!\w)")
_TV_SIZE = re.compile(r"(?<![\w.])(24|32|40|42|43|50|55|58|60|65|70|75|85|86|98|100)(?![\w.])")


def attributes(normalized_text: str, category: str | None = None) -> Intent:
    """Light extraction for indexing a product (no budget / brand / category parsing — those come from fields)."""
    t = normalized_text
    out = Intent(raw="", text=t)
    if _TON15.search(t):
        out.ton = 1.5
    elif _TON2.search(t):
        out.ton = 2.0
    elif _TON1.search(t):
        out.ton = 1.0
    k = _KG.search(t)
    if k:
        out.kg = float(k.group(1))
    inch = _INCH.search(t)
    if inch:
        out.size_inch = float(inch.group(1))
    elif category == "شاشات":
        bare = _TV_SIZE.search(t)
        if bare:
            out.size_inch = float(bare.group(1))
    for feature, words in L.FEATURE_WORDS.items():
        if any(w in t for w in words):
            out.features.add(feature)
    return out
