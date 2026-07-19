"""Populate grounded Finora Sales AI knowledge for every product in a tenant DB."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _json(value, fallback):
    try:
        parsed = json.loads(value or "")
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _unique(values) -> list[str]:
    result = []
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip(" -،")
        if text and text not in result:
            result.append(text)
    return result


def _normalized_name(name: str) -> str:
    replacements = {
        "شاشه": "شاشة",
        "غساله": "غسالة",
        "مكنسه": "مكنسة",
        "ثلاجه": "ثلاجة",
        "مبرده": "مبردة",
        "مكوى": "مكواة",
        "سامسونك": "سامسونگ",
        "الجي": "LG",
        "ال جي": "LG",
    }
    normalized = re.sub(r"\s+", " ", (name or "").strip())
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def _number_before(name: str, units: tuple[str, ...]) -> int | None:
    translated = (name or "").translate(ARABIC_DIGITS)
    unit_pattern = "|".join(re.escape(unit) for unit in units)
    match = re.search(rf"(?<!\d)(\d{{1,3}})\s*(?:{unit_pattern})", translated, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _tv_size(name: str) -> int | None:
    translated = (name or "").translate(ARABIC_DIGITS)
    match = re.search(r"(?:حجم|قياس)\s*(\d{2,3})(?!\d)", translated)
    if match and 20 <= int(match.group(1)) <= 100:
        return int(match.group(1))
    values = [int(value) for value in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", translated)]
    return next((value for value in values if 20 <= value <= 100), None)


def _model(name: str) -> str:
    match = re.search(r"موديل\s*([\w-]+)", (name or "").translate(ARABIC_DIGITS), re.IGNORECASE)
    return match.group(1) if match else ""


def _kind(name: str, meta: dict) -> str:
    text = f"{name} {meta.get('category', '')} {meta.get('subcategory', '')}".lower()
    if "رسوم الشحن" in text:
        return "system_fee"
    if "منتج موقت" in text or "منتج مؤقت" in text:
        return "temporary"
    if any(term in text for term in ("شاش", "تلفزيون")):
        return "tv"
    if "غسال" in text:
        return "washer"
    if any(term in text for term in ("سبلت", "مكيف")):
        return "ac"
    if "ثلاج" in text:
        return "fridge"
    if "براد" in text:
        return "cooler"
    if "مكنس" in text:
        return "vacuum"
    if "مبرد" in text:
        return "air_cooler"
    if "مكوى" in text or "مكواة" in text:
        return "iron"
    if "ريمونت" in text or "ريموت" in text:
        return "remote"
    if "ستاند" in text:
        return "stand"
    return "other"


def _brand(name: str, meta: dict) -> str:
    aliases = {
        "SAMASONG": "سامسونگ",
        "CRUWN": "كراون",
        "HITASHI": "هيتاشي",
        "GENERAL": "جنرال",
        "PROMAX": "بروماكس",
        "SHARBO": "شاربو",
        "LG": "LG",
    }
    lowered = (name or "").lower()
    known = (
        (("ال جي", "الجي"), "LG"),
        (("سامسونك", "سامسونگ"), "سامسونگ"),
        (("هيتاشي",), "هيتاشي"),
        (("جنرال",), "جنرال"),
        (("برو ماكس", "بروماكس"), "بروماكس"),
        (("كراون",), "كراون"),
        (("اريتون",), "اريتون"),
        (("دنكا",), "دنكا"),
        (("نوال",), "نوال"),
        (("جبسون",), "جبسون"),
        (("كهرمانه",), "كهرمانه"),
        (("شاربو",), "شاربو"),
        (("ايفولي",), "ايفولي"),
        (("بلازمه",), "بلازمه"),
        (("كري",), "كري"),
        (("سوبر امبريال",), "سوبر امبريال"),
        (("one live",), "one live"),
    )
    explicit = next((label for terms, label in known if any(term in lowered for term in terms)), "")
    if explicit:
        return explicit
    raw = str(meta.get("brand") or "").strip()
    return aliases.get(raw.upper(), raw) if raw else ""


def _delivery_text(meta: dict) -> str:
    fees = meta.get("delivery_by_province")
    if not isinstance(fees, dict) or not fees:
        return "تفاصيل التوصيل غير مسجلة؛ تُؤكد حسب عنوان الزبون قبل تثبيت الطلب."
    numeric = {str(key): int(value or 0) for key, value in fees.items() if str(value or "0").lstrip("-").isdigit()}
    if not numeric:
        return "تفاصيل التوصيل غير مسجلة؛ تُؤكد حسب عنوان الزبون قبل تثبيت الطلب."
    baghdad = numeric.get("بغداد")
    outside = {value for key, value in numeric.items() if key != "بغداد"}
    if baghdad == 0 and any(value > 0 for value in outside):
        return "التوصيل داخل بغداد بلا أجور مسجلة، وباقي المحافظات حسب الأجور المحددة في Finora."
    return "التوصيل متاح، وتُؤكد أجوره حسب المحافظة والمنطقة قبل تثبيت الطلب."


def _warranty_text(meta: dict) -> str:
    warranty = str(meta.get("warranty") or "").strip().lower()
    if warranty in {"1y", "1 year", "year", "سنة", "سنه"}:
        return "ضمان سنة واحدة حسب البيانات المسجلة."
    if warranty:
        return f"الضمان المسجل: {warranty}."
    return "مدة الضمان غير مسجلة؛ يجب تأكيدها قبل إتمام الطلب."


def _aliases(name: str, marketing_name: str, kind: str, size: int | None, feet: int | None, capacity: int | None) -> list[str]:
    aliases = [name, marketing_name]
    if kind == "tv" and size:
        aliases.extend((f"شاشة {size}", f"تلفزيون {size}", f"{size} بوصة"))
    elif kind == "fridge" and feet:
        aliases.extend((f"ثلاجة {feet} قدم", f"براد {feet} قدم"))
    elif kind == "washer" and capacity:
        aliases.extend((f"غسالة {capacity} كيلو", f"غسالة سعة {capacity} كيلو"))
    elif kind == "ac" and capacity:
        aliases.extend((f"سبلت {capacity} طن", f"مكيف {capacity} طن"))
    return _unique(aliases)


def _knowledge(product: sqlite3.Row) -> dict:
    name = str(product["name"] or "").strip()
    meta = _json(product["meta_json"], {})
    kind = _kind(name, meta)
    marketing_name = _normalized_name(name)
    brand = _brand(name, meta)
    size = _tv_size(name) if kind == "tv" else None
    feet = _number_before(name, ("قدم", "ft")) if kind == "fridge" else None
    capacity = None
    if kind == "washer":
        capacity = _number_before(name, ("كيلو", "ك", "kg"))
    elif kind == "ac":
        capacity = _number_before(name, ("طن",))
    model = _model(name)
    features = []
    lowered = name.lower()
    if size:
        features.append(f"قياس {size} بوصة كما هو مسجل")
    if feet:
        features.append(f"حجم {feet} قدم كما هو مسجل")
    if capacity and kind == "washer":
        features.append(f"سعة {capacity} كيلوغرام كما هي مسجلة")
    if capacity and kind == "ac":
        features.append(f"سعة {capacity} طن كما هي مسجلة")
    if model:
        features.append(f"موديل {model}")
    if "ضد الكسر" in lowered:
        features.append("مذكور في بيانات المنتج: ضد الكسر")
    if "ستلايت داخلي" in lowered:
        features.append("ستلايت داخلي")
    if "سمارت" in lowered or "smart" in lowered:
        features.append("سمارت حسب الاسم المسجل")
    if "حار بارد" in lowered:
        features.append("حار وبارد")
    if "بخار" in lowered:
        features.append("خاصية البخار حسب الاسم المسجل")
    if "ابيض" in lowered:
        features.append("لون أبيض")
    if "اسود" in lowered:
        features.append("لون أسود")
    if brand:
        features.insert(0, f"العلامة المسجلة: {brand}")

    category_labels = {
        "tv": "شاشة تلفزيون",
        "washer": "غسالة ملابس",
        "ac": "جهاز تكييف",
        "fridge": "ثلاجة",
        "cooler": "براد",
        "vacuum": "مكنسة كهربائية",
        "air_cooler": "مبردة هواء",
        "iron": "مكواة",
        "remote": "ريموت تحكم",
        "stand": "ستاند",
        "other": "منتج",
    }
    category = category_labels.get(kind, "منتج")
    if kind == "system_fee":
        return {
            "marketing_name": name,
            "aliases": [name],
            "description": product["description"] or "بند نظامي لاحتساب رسوم التوصيل، وليس منتجاً للبيع.",
            "selling_points": ["بند داخلي لاحتساب رسوم التوصيل"],
            "ideal_for": ["الاستخدام الداخلي في الطلبات والفواتير فقط"],
            "warranty": "لا ينطبق؛ هذا بند نظامي وليس منتجاً للبيع.",
            "delivery": "يُستخدم لحساب أجور التوصيل داخل النظام.",
            "objections": {"طلب شراء": "لا تعرض هذا البند للزبائن."},
            "notes": "بند نظامي. ممنوع عرضه أو اقتراحه أو تسعيره للزبون.",
            "allow_recommendation": False,
            "is_active": False,
        }
    if kind == "temporary":
        return {
            "marketing_name": name,
            "aliases": [name],
            "description": product["description"] or "منتج مؤقت لم تكتمل بياناته بعد.",
            "selling_points": ["بيانات المنتج ما زالت قيد الاستكمال"],
            "ideal_for": ["الاستخدام الداخلي فقط حتى استكمال البيانات"],
            "warranty": "مدة الضمان غير مسجلة.",
            "delivery": _delivery_text(meta),
            "objections": {"ما مواصفاته؟": "حوّل السؤال إلى الموظف لأن بيانات المنتج غير مكتملة."},
            "notes": "منتج مؤقت. ممنوع عرضه أو اقتراحه للزبون حتى استكمال بياناته.",
            "allow_recommendation": False,
            "is_active": False,
        }

    description_features = [
        value.replace(" كما هو مسجل", "").replace(" كما هي مسجلة", "").replace("مذكور في بيانات المنتج: ", "").replace(" حسب الاسم المسجل", "")
        for value in features
        if not value.startswith("العلامة المسجلة:")
    ]
    description = marketing_name
    if description_features:
        description += ". " + "، ".join(description_features)
    description += "."
    if not features:
        features.append(f"مصنف كـ{category} حسب الاسم المسجل")

    if kind == "tv":
        if size and size <= 43:
            ideal_for = ["غرف النوم والمساحات الصغيرة أو المتوسطة", "المحلات والاستخدام اليومي"]
        elif size and size <= 58:
            ideal_for = ["غرف المعيشة والمساحات المتوسطة", "المشاهدة المنزلية اليومية"]
        elif size:
            ideal_for = ["الصالات والغرف الواسعة", "المشاهدة من مسافة أبعد بعد التأكد من مساحة المكان"]
        else:
            ideal_for = ["الاستخدام المنزلي أو التجاري بعد تحديد القياس المطلوب"]
    elif kind == "washer":
        ideal_for = ["غسيل الملابس المنزلي", "اختيار السعة بحسب حجم العائلة وكمية الغسيل"]
    elif kind == "ac":
        ideal_for = ["المنازل أو المكاتب والمحلات", "يُحدد ملاءمته بعد معرفة مساحة المكان"]
    elif kind == "fridge":
        ideal_for = ["حفظ الأطعمة والمشروبات", "يُحدد ملاءمته حسب المساحة والسعة المطلوبة"]
    elif kind in {"cooler", "air_cooler"}:
        ideal_for = ["التبريد والتهوية", "يُحدد ملاءمته حسب مساحة المكان"]
    elif kind == "vacuum":
        ideal_for = ["تنظيف المنزل والأرضيات", "الاستخدام المنزلي اليومي"]
    elif kind == "iron":
        ideal_for = ["كي الملابس في المنزل", "الاستخدام المنزلي اليومي"]
    elif kind == "remote":
        ideal_for = ["التحكم بالأجهزة المتوافقة", "يجب تأكيد توافقه مع جهاز الزبون قبل البيع"]
    elif kind == "stand":
        ideal_for = ["تركيب الجهاز المناسب", "يجب تأكيد المقاس والتوافق قبل البيع"]
    else:
        ideal_for = ["يُحدد الاستخدام المناسب بعد تأكيد حاجة الزبون"]

    delivery = _delivery_text(meta)
    warranty = _warranty_text(meta)
    objections = {
        "غالي": "اعرض بدائل من نفس الفئة ضمن ميزانية الزبون من الأسعار الحالية فقط.",
        "أكو أرخص؟": "ابحث عن بديل أقل سعراً من المخزون الحالي بدون تغيير أي سعر.",
        "الضمان": warranty,
        "التوصيل": delivery,
        "متوفر؟": "تحقق من المخزون الحالي قبل التأكيد، ولا تذكر عدد القطع للزبون.",
    }
    notes = (
        "لا تذكر كمية المخزون بالأرقام. لا تضف مواصفات غير مسجلة. "
        "اعرض السعر الحالي من Finora فقط، واسأل سؤالاً واحداً يساعد على اختيار المنتج. "
        "استخدم بيانات الضمان والتوصيل المسجلة، واجمع الاسم والهاتف والعنوان فقط عند نية الشراء."
    )
    return {
        "marketing_name": marketing_name,
        "aliases": _aliases(name, marketing_name, kind, size, feet, capacity),
        "description": product["description"] or description,
        "selling_points": _unique(features),
        "ideal_for": _unique(ideal_for),
        "warranty": warranty,
        "delivery": delivery,
        "objections": objections,
        "notes": notes,
        "allow_recommendation": bool(product["active"]),
        "is_active": bool(product["active"]),
    }


def _merge_list(existing: str | None, generated: list[str]) -> list[str]:
    return _unique([*_json(existing, []), *generated])


def _merge_points(existing: str | None, generated: list[str]) -> list[str]:
    stored = _json(existing, [])
    if any(value.startswith("العلامة المسجلة:") for value in generated):
        stored = [value for value in stored if not str(value).startswith("العلامة المسجلة:")]
    return _unique([*stored, *generated])


def _merge_dict(existing: str | None, generated: dict[str, str]) -> dict[str, str]:
    merged = dict(generated)
    merged.update(_json(existing, {}))
    return merged


def populate(database: Path, *, dry_run: bool = False) -> dict:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    products = connection.execute("SELECT * FROM product ORDER BY id").fetchall()
    existing_profiles = {
        row["product_id"]: row
        for row in connection.execute("SELECT * FROM ai_sales_product_profile").fetchall()
    }
    created = updated = descriptions = disabled = 0
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")
    for product in products:
        generated = _knowledge(product)
        profile = existing_profiles.get(product["id"])
        if not str(product["description"] or "").strip():
            connection.execute("UPDATE product SET description = ? WHERE id = ?", (generated["description"], product["id"]))
            descriptions += 1

        values = {
            "marketing_name": (profile["marketing_name"] if profile and str(profile["marketing_name"] or "").strip() else generated["marketing_name"]),
            "aliases_json": _dump(_merge_list(profile["aliases_json"] if profile else None, generated["aliases"])),
            "selling_points_json": _dump(_merge_points(profile["selling_points_json"] if profile else None, generated["selling_points"])),
            "ideal_for_json": _dump(_merge_list(profile["ideal_for_json"] if profile else None, generated["ideal_for"])),
            "objections_json": _dump(_merge_dict(profile["objections_json"] if profile else None, generated["objections"])),
            "warranty_text": (profile["warranty_text"] if profile and str(profile["warranty_text"] or "").strip() else generated["warranty"]),
            "delivery_text": (profile["delivery_text"] if profile and str(profile["delivery_text"] or "").strip() else generated["delivery"]),
            "ai_notes": (profile["ai_notes"] if profile and str(profile["ai_notes"] or "").strip() else generated["notes"]),
            "allow_price": int(profile["allow_price"] if profile else True),
            "allow_recommendation": int(generated["allow_recommendation"] if not profile else profile["allow_recommendation"] and generated["allow_recommendation"]),
            "is_active": int(generated["is_active"] if not profile else profile["is_active"] and generated["is_active"]),
            "updated_at": now,
        }
        if not values["allow_recommendation"]:
            disabled += 1
        if profile:
            assignments = ", ".join(f"{column} = ?" for column in values)
            connection.execute(
                f"UPDATE ai_sales_product_profile SET {assignments} WHERE product_id = ?",
                (*values.values(), product["id"]),
            )
            updated += 1
        else:
            columns = ["product_id", *values]
            placeholders = ", ".join("?" for _ in columns)
            connection.execute(
                f"INSERT INTO ai_sales_product_profile ({', '.join(columns)}) VALUES ({placeholders})",
                (product["id"], *values.values()),
            )
            created += 1
    if dry_run:
        connection.rollback()
    else:
        connection.commit()
    connection.close()
    return {
        "products": len(products),
        "created_profiles": created,
        "updated_profiles": updated,
        "filled_descriptions": descriptions,
        "recommendation_disabled": disabled,
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.database.is_file():
        raise SystemExit(f"Database not found: {args.database}")
    print(json.dumps(populate(args.database, dry_run=args.dry_run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
