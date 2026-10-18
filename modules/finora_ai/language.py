"""Bounded Arabic fallback helpers; not a substitute for a language model."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text)).lower()
    text = text.translate(str.maketrans("أإآٱى٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "ااااي01234567890123456789"))
    text = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", text)
    return re.sub(r"\s+", " ", text).strip(" ؟?!.،")


def balance_question(text: str) -> bool:
    return any(word in normalize(text) for word in ("باقي", "عليه", "عليهم", "حساب", "ذم", "مستحق", "balance", "كشف"))


def name_query(text: str, entity: str) -> str:
    # Keep the original spelling for DB lookup, remove conversational framing.
    aliases = {"agent": "المندوب|مندوب|المندوبين|مندوبين|agent", "customer": "الزبون|زبون|العميل|عميل|customer", "supplier": "المورد|مورد|supplier", "product": "المنتج|منتج|المادة|مادة|product"}[entity]
    match = re.search(r"(?:" + aliases + r")\s*(?:اسمه|اسمها|اسمو|اسم|رقم)?\s+(.+)$", text, re.I)
    if not match:
        match = re.search(r"(?:اسمه|اسمها|اسمو)\s+(.+)$", text)
    if not match:
        return ""
    value = match.group(1).strip(" ؟?!.،")
    value = re.sub(r"\s+(?:شكد|كم|شنو|شنهي|اشكد|اليوم|امس|أمس|هسه|حاليا|حالياً|باقي|عليه|حسابه|حساب).*?$", "", value)
    return "" if normalize(value) in {"التوصيل", "توصيل", "الي", "اللي"} else value[:150]


def period_args(text: str, now: datetime | None = None) -> dict:
    today = (now or datetime.now(ZoneInfo("Asia/Baghdad"))).date()
    low = normalize(text)
    start = end = None
    if any(word in low for word in ("امس", "البارحة", "البارحه", "yesterday")):
        start = end = today - timedelta(days=1)
    elif any(word in low for word in ("الشهر الماضي", "الشهر الفات", "last month")):
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
    elif any(word in low for word in ("هذا الشهر", "هالشهر", "الشهر الحالي", "this month")):
        start, end = today.replace(day=1), today
    elif any(word in low for word in ("هذا الاسبوع", "هالاسبوع", "this week")):
        # Sunday-based week, explicit in backend context.
        start, end = today - timedelta(days=(today.weekday() + 1) % 7), today
    elif any(word in low for word in ("الاسبوع الماضي", "الاسبوع الفات", "last week")):
        end = today - timedelta(days=(today.weekday() + 1) % 7 + 1)
        start = end - timedelta(days=6)
    elif (days := re.search(r"(?:اخر|last)\s+(\d{1,3})\s*(?:ايام|يوم|days)", low)):
        count = int(days[1])
        if count <= 0:
            return {}
        start, end = today - timedelta(days=count - 1), today
    else:
        dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", low)
        if dates:
            start, end = dates[0], dates[-1]
    return {"date_from": str(start), "date_to": str(end)} if start is not None else {}


def unresolved_period(text: str) -> bool:
    low = normalize(text)
    return not period_args(text) and (bool(re.search(r"(?:اخر|last)\s+\d+\s*(?:ايام|يوم|days)", low)) or any(word in low for word in ("اسبوع", "الشهر", "السنه", "السنة", "قبل", "منذ", "الفات", "الماضي", "باجر", "غدا", "من ", "الى ")))


def selected_candidate(text: str, candidates: list[dict]) -> dict | None:
    low = normalize(text)
    names = [item for item in candidates if low == normalize(item.get("name", ""))]
    if names:
        return names[0] if len(names) == 1 else None
    ordinal = {"الاول": 0, "اول واحد": 0, "الثاني": 1, "ثاني واحد": 1, "الثالث": 2}
    if low in ordinal and ordinal[low] < len(candidates):
        return candidates[ordinal[low]]
    match = re.fullmatch(r"(?:رقم\s*)?(\d+)", low)
    if match:
        matches = [item for item in candidates if int(item.get("id", -1)) == int(match[1])]
        return matches[0] if len(matches) == 1 else None
    return None
