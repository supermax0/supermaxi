"""استيراد أسماء البيجات من صورة جدول (OCR + OpenAI Vision)."""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from extensions import db
from models.page import Page

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_BULK_NAMES = 200
MIN_GOOD_NAMES = 3
MAX_NAME_LEN = 150

HEADER_KEYWORDS = {
    "اسم البيج",
    "اسم بيج",
    "البيج",
    "الموظفين",
    "الموظف",
    "الطلبات",
    "الطلبات الكلية",
    "عدد الراجع",
    "عدد الواصل",
    "الراجع",
    "الواصل",
    "كاشير",
    "أدمن",
    "ادمن",
    "الإجراءات",
    "الاجراءات",
    "pages",
    "page name",
    "employees",
    "actions",
    "total orders",
    "delivered",
    "returns",
}

VISION_PROMPT = """استخرج أسماء البيجات فقط من صورة جدول عربي.
تجاهل عناوين الأعمدة والأرقام والإحصائيات وأعمدة الموظفين.
أرجع JSON فقط بهذا الشكل:
{"names": ["اسم 1", "اسم 2"]}
لا تضف أي نص خارج JSON."""


def _normalize_key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def _has_arabic(text: str) -> bool:
    return any("\u0600" <= c <= "\u06FF" for c in text)


def _is_header_line(text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", text.strip())
    lowered = cleaned.casefold()
    if lowered in {k.casefold() for k in HEADER_KEYWORDS}:
        return True
    for keyword in HEADER_KEYWORDS:
        if lowered == keyword.casefold():
            return True
    return False


def _is_numeric_only(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return bool(re.fullmatch(r"[\d\s.,:;%+\-]+", stripped))


def _pick_name_from_line(line: str) -> Optional[str]:
    line = line.strip()
    if not line or _is_header_line(line) or _is_numeric_only(line):
        return None

    parts = re.split(r"\t+|\s{2,}", line)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return None

    candidates = []
    for part in parts:
        if _is_numeric_only(part) or _is_header_line(part):
            continue
        if len(part) < 2:
            continue
        score = len(part)
        if _has_arabic(part):
            score += 50
        candidates.append((score, part))

    if not candidates:
        only = parts[0]
        if len(only) >= 2 and not _is_numeric_only(only):
            return only[:MAX_NAME_LEN]
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1][:MAX_NAME_LEN]


def parse_page_names_from_text(raw_text: str) -> List[str]:
    """تحويل نص OCR خام إلى قائمة أسماء بيجات."""
    if not raw_text:
        return []

    seen: Set[str] = set()
    names: List[str] = []
    for line in raw_text.splitlines():
        name = _pick_name_from_line(line)
        if not name:
            continue
        key = _normalize_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        names.append(name.strip())
    return names


def extract_page_names_tesseract(image_bytes: bytes) -> Tuple[List[str], str, List[str]]:
    warnings: List[str] = []
    raw_text = ""
    try:
        from ai.ocr import extract_text

        raw_text = extract_text(image_bytes) or ""
    except Exception as exc:
        warnings.append(f"فشل OCR المحلي: {exc}")
        return [], raw_text, warnings

    names = parse_page_names_from_text(raw_text)
    if raw_text and not names:
        warnings.append("تم قراءة النص لكن لم يُعثر على أسماء بيجات واضحة.")
    return names, raw_text, warnings


def _parse_json_names(content: str) -> List[str]:
    if not content:
        return []
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return []
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []

    if isinstance(payload, list):
        raw_names = payload
    elif isinstance(payload, dict):
        raw_names = payload.get("names") or payload.get("pages") or []
    else:
        return []

    names: List[str] = []
    seen: Set[str] = set()
    for item in raw_names:
        if not isinstance(item, str):
            continue
        name = item.strip()[:MAX_NAME_LEN]
        if len(name) < 2:
            continue
        key = _normalize_key(name)
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def extract_page_names_vision(image_bytes: bytes) -> Tuple[List[str], List[str]]:
    warnings: List[str] = []
    try:
        from social_ai.ai_engine import get_client
    except Exception as exc:
        warnings.append(f"تعذر تحميل عميل OpenAI: {exc}")
        return [], warnings

    try:
        client = get_client()
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:image/jpeg;base64,{b64}"
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            max_tokens=1200,
            temperature=0.1,
        )
        content = ""
        if response.choices:
            content = (response.choices[0].message.content or "").strip()
        names = _parse_json_names(content)
        if not names:
            warnings.append("لم يُرجع الذكاء الاصطناعي أسماء صالحة.")
        return names, warnings
    except RuntimeError as exc:
        warnings.append(str(exc))
        return [], warnings
    except Exception as exc:
        warnings.append(f"فشل استخراج الصورة بالذكاء الاصطناعي: {exc}")
        return [], warnings


def get_existing_page_names() -> Tuple[List[str], Set[str]]:
    existing = [p.name for p in Page.query.all()]
    keys = {_normalize_key(name) for name in existing}
    return existing, keys


def mark_existing_names(names: List[str], existing_keys: Set[str]) -> List[str]:
    return [n for n in names if _normalize_key(n) in existing_keys]


def extract_page_names_hybrid(
    image_bytes: bytes,
    *,
    force_ai: bool = False,
) -> Dict[str, Any]:
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return {
            "success": False,
            "error": "حجم الصورة كبير جداً (الحد الأقصى 8 ميغابايت).",
            "names": [],
            "existing": [],
            "source": None,
            "raw_text": "",
            "warnings": [],
        }

    names: List[str] = []
    raw_text = ""
    warnings: List[str] = []
    source = "tesseract"

    if not force_ai:
        names, raw_text, tesseract_warnings = extract_page_names_tesseract(image_bytes)
        warnings.extend(tesseract_warnings)

    good_enough = len(names) >= MIN_GOOD_NAMES
    if force_ai or not good_enough:
        ai_names, ai_warnings = extract_page_names_vision(image_bytes)
        warnings.extend(ai_warnings)
        if ai_names:
            names = ai_names
            source = "openai"
        elif force_ai:
            source = "openai"

    existing_list, existing_keys = get_existing_page_names()
    existing_matches = mark_existing_names(names, existing_keys)

    if not names:
        return {
            "success": False,
            "error": "لم يُعثر على أسماء بيجات في الصورة.",
            "names": [],
            "existing": existing_matches,
            "source": source,
            "raw_text": raw_text,
            "warnings": warnings,
        }

    return {
        "success": True,
        "names": names,
        "existing": existing_matches,
        "source": source,
        "raw_text": raw_text,
        "warnings": warnings,
    }


def bulk_create_pages(names: List[str]) -> Dict[str, Any]:
    cleaned: List[str] = []
    seen: Set[str] = set()
    for item in names or []:
        if not isinstance(item, str):
            continue
        name = re.sub(r"\s+", " ", item.strip())[:MAX_NAME_LEN]
        if len(name) < 2:
            continue
        key = _normalize_key(name)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(name)

    if len(cleaned) > MAX_BULK_NAMES:
        return {
            "success": False,
            "error": f"الحد الأقصى {MAX_BULK_NAMES} اسم في المرة الواحدة.",
            "added": 0,
            "skipped": [],
            "created_names": [],
        }

    _, existing_keys = get_existing_page_names()
    created_names: List[str] = []
    skipped: List[str] = []

    for name in cleaned:
        key = _normalize_key(name)
        if key in existing_keys:
            skipped.append(name)
            continue
        page = Page(name=name)
        db.session.add(page)
        created_names.append(name)
        existing_keys.add(key)

    if created_names:
        db.session.commit()
    else:
        db.session.rollback()

    return {
        "success": True,
        "added": len(created_names),
        "skipped": skipped,
        "created_names": created_names,
        "message": f"تمت إضافة {len(created_names)} بيج، وتم تخطي {len(skipped)} مكرر.",
    }
