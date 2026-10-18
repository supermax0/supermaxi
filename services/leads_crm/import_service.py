"""Excel/CSV import wizard service."""
from __future__ import annotations

import io
import json
from typing import Any

import pandas as pd

from extensions import db
from models.core.leads.models import LeadImportBatch, LeadImportRow
from services.leads_crm.deduplication import detect_duplicate
from services.leads_crm.lead_service import create_lead
from services.leads_crm.merge_service import merge_leads
from utils.leads_crm.name_normalize import normalize_business_name
from utils.leads_crm.phone_normalize import normalize_iraq_phone


IMPORT_FIELDS = [
    "business_name", "phone", "owner_name", "governorate", "city",
    "district", "area", "full_address", "instagram_url", "facebook_url",
    "website", "source_primary",
]


from services.leads_crm.helpers import actor_superadmin_id as _actor_id

# أسماء أعمدة Excel الشائعة (عربي / إنجليزي) → حقول Lead
COLUMN_ALIASES: dict[str, list[str]] = {
    "business_name": ["اسم المحل", "اسم الشركة", "اسم النشاط", "business_name", "company", "name", "store", "shop"],
    "phone": ["رقم الهاتف", "الهاتف", "phone", "mobile", "tel", "جوال", "رقم الجوال"],
    "owner_name": ["اسم المالك", "المالك", "owner_name", "owner"],
    "governorate": ["المحافظة", "governorate"],
    "city": ["المدينة", "city"],
    "district": ["المنطقة", "district"],
    "area": ["الحي", "area"],
    "full_address": ["العنوان الكامل", "العنوان", "full_address", "address"],
    "instagram_url": ["instagram", "instagram_url", "انستagram", "انستغرام"],
    "facebook_url": ["facebook", "facebook_url", "فيسبوك"],
    "website": ["website", "الموقع", "url", "رابط", "موقع"],
    "source_primary": ["المصدر", "source", "source_primary"],
}

# كلمات مفتاحية للمطابقة الجزئية (يُستخدم العمود مرة واحدة فقط)
FIELD_KEYWORDS: dict[str, list[str]] = {
    "business_name": ["اسم المحل", "اسم الشركه", "اسم الشركة", "company", "store", "shop", "business", "محل"],
    "phone": ["رقم الهاتف", "الهاتف", "phone", "mobile", "tel", "جوال"],
    "owner_name": ["اسم المالك", "المالك", "owner"],
    "governorate": ["المحافظه", "المحافظة", "governorate"],
    "city": ["المدينه", "المدينة", "city"],
    "district": ["المنطقه", "المنطقة", "district"],
    "area": ["الحي", "area"],
    "full_address": ["العنوان الكامل", "full address", "address", "العنوان"],
    "instagram_url": ["instagram", "insta", "انست"],
    "facebook_url": ["facebook", "fb", "فيس"],
    "website": ["website", "url", "رابط", "موقع"],
    "source_primary": ["المصدر", "source"],
}


def _normalize_column_name(value: str) -> str:
    s = str(value or "").strip().lower()
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")):
        s = s.replace(a, b)
    return " ".join(s.split())


def guess_mapping(columns: list[str]) -> dict[str, str]:
    """ربط تلقائي لأعمدة Excel بحقول Lead (تطابق تام ثم جزئي)."""
    if not columns:
        return {}

    clean_columns = [str(c).strip() for c in columns if str(c).strip()]
    norm_columns = [(col, _normalize_column_name(col)) for col in clean_columns]
    used_columns: set[str] = set()
    mapping: dict[str, str] = {}

    # 1) تطابق تام مع aliases
    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            norm_alias = _normalize_column_name(alias)
            for col, norm_col in norm_columns:
                if col in used_columns:
                    continue
                if norm_col == norm_alias:
                    mapping[field] = col
                    used_columns.add(col)
                    break
            if field in mapping:
                break

    # 2) تطابق جزئي بالكلمات المفتاحية (أطول تطابق يفوز)
    for field, keywords in FIELD_KEYWORDS.items():
        if field in mapping:
            continue
        best_col = None
        best_score = 0
        for col, norm_col in norm_columns:
            if col in used_columns:
                continue
            for keyword in keywords:
                norm_kw = _normalize_column_name(keyword)
                if not norm_kw:
                    continue
                if norm_kw == norm_col:
                    score = 100 + len(norm_kw)
                elif norm_kw in norm_col:
                    score = 50 + len(norm_kw)
                elif norm_col in norm_kw:
                    score = 40 + len(norm_col)
                else:
                    continue
                if score > best_score:
                    best_score = score
                    best_col = col
        if best_col:
            mapping[field] = best_col
            used_columns.add(best_col)

    return mapping


def apply_auto_mapping(batch_id: int, columns: list[str] | None = None) -> dict[str, str]:
    """يحفظ ربط الأعمدة تلقائياً إذا وُجد اسم محل/شركة."""
    batch = LeadImportBatch.query.get(batch_id)
    if not batch:
        return {}
    if batch.mapping_json:
        return json.loads(batch.mapping_json)
    if columns is None:
        preview = preview_batch(batch_id, limit=1)
        columns = preview.get("columns") or []
    mapping = guess_mapping(columns)
    if mapping.get("business_name"):
        batch.mapping_json = json.dumps(mapping, ensure_ascii=False)
        batch.status = "mapped"
        db.session.commit()
    return mapping


def ensure_batch_mapping(batch_id: int) -> dict[str, str]:
    return apply_auto_mapping(batch_id)


def parse_upload(file_bytes: bytes, filename: str) -> pd.DataFrame:
    if filename.lower().endswith(".csv"):
        return pd.read_csv(io.BytesIO(file_bytes))
    return pd.read_excel(io.BytesIO(file_bytes))


def create_batch_from_upload(
    file_bytes: bytes,
    filename: str,
    *,
    activity_id: int | None = None,
    source_label: str | None = None,
) -> LeadImportBatch:
    df = parse_upload(file_bytes, filename)
    batch = LeadImportBatch(
        filename=filename,
        activity_id=activity_id,
        source_label=source_label,
        status="preview",
        created_by=_actor_id(),
    )
    db.session.add(batch)
    db.session.flush()

    for idx, row in df.iterrows():
        raw = {str(k): ("" if pd.isna(v) else str(v)) for k, v in row.items()}
        db.session.add(
            LeadImportRow(
                batch_id=batch.id,
                row_number=int(idx) + 2,
                raw_json=json.dumps(raw, ensure_ascii=False),
            )
        )
    db.session.flush()
    columns = [str(c).strip() for c in df.columns]
    mapping = guess_mapping(columns)
    if mapping.get("business_name"):
        batch.mapping_json = json.dumps(mapping, ensure_ascii=False)
        batch.status = "mapped"
    db.session.commit()
    return batch


def preview_batch(batch_id: int, limit: int = 20) -> dict[str, Any]:
    batch = LeadImportBatch.query.get(batch_id)
    if not batch:
        return {"error": "Batch غير موجود"}
    rows = batch.rows.order_by(LeadImportRow.row_number).limit(limit).all()
    columns = []
    if rows:
        columns = list(json.loads(rows[0].raw_json).keys())
    return {
        "batch_id": batch.id,
        "filename": batch.filename,
        "columns": columns,
        "rows": [{"row_number": r.row_number, "data": json.loads(r.raw_json)} for r in rows],
        "total_rows": batch.rows.count(),
    }


def apply_mapping(batch_id: int, mapping: dict[str, str]) -> dict[str, Any]:
    batch = LeadImportBatch.query.get(batch_id)
    if not batch:
        return {"error": "Batch غير موجود"}
    batch.mapping_json = json.dumps(mapping, ensure_ascii=False)
    batch.status = "mapped"
    db.session.commit()
    return {"ok": True}


def normalize_and_validate_batch(batch_id: int) -> dict[str, Any]:
    batch = LeadImportBatch.query.get(batch_id)
    if not batch:
        return {"error": "Batch غير موجود"}
    mapping = json.loads(batch.mapping_json or "{}")
    if not mapping.get("business_name"):
        mapping = ensure_batch_mapping(batch_id)
    if not mapping.get("business_name"):
        return {"error": "يجب ربط عمود اسم الشركة / اسم المحل قبل التحقق"}
    stats = {"valid": 0, "invalid": 0, "exact_dup": 0, "possible_dup": 0}

    for row in batch.rows.all():
        raw = json.loads(row.raw_json)
        normalized = {}
        errors = []

        for field, col in mapping.items():
            if col and col in raw:
                normalized[field] = raw[col].strip()

        name = normalized.get("business_name", "")
        if not name:
            errors.append("اسم الشركة مطلوب")

        phone = normalized.get("phone")
        if phone:
            norm_phone = normalize_iraq_phone(phone)
            if not norm_phone:
                errors.append("رقم هاتف غير صالح")
            else:
                normalized["phone_normalized"] = norm_phone

        if name:
            normalized["normalized_business_name"] = normalize_business_name(name)

        row.normalized_json = json.dumps(normalized, ensure_ascii=False)
        row.validation_errors = json.dumps(errors, ensure_ascii=False) if errors else None

        if errors:
            stats["invalid"] += 1
            continue
        stats["valid"] += 1

    batch.status = "validated"
    db.session.commit()
    return {"ok": True, "stats": stats}


def detect_duplicates_in_batch(batch_id: int) -> dict[str, Any]:
    batch = LeadImportBatch.query.get(batch_id)
    if not batch:
        return {"error": "Batch غير موجود"}

    stats = {"exact": 0, "strong": 0, "possible": 0, "clean": 0}

    for row in batch.rows.all():
        if row.validation_errors:
            continue
        data = json.loads(row.normalized_json or "{}")
        dup = detect_duplicate(
            business_name=data.get("business_name", ""),
            phone=data.get("phone"),
            governorate=data.get("governorate"),
            district=data.get("district"),
            full_address=data.get("full_address"),
        )
        row.duplicate_level = dup.level
        row.duplicate_lead_id = dup.lead_id
        row.duplicate_score = dup.score
        row.duplicate_reason = dup.reason

        if dup.level == "EXACT":
            row.commit_action = "merge"
            stats["exact"] += 1
        elif dup.level == "STRONG":
            row.commit_action = "review"
            stats["strong"] += 1
        elif dup.level == "POSSIBLE":
            row.commit_action = "review"
            stats["possible"] += 1
        else:
            row.commit_action = "create"
            stats["clean"] += 1

    batch.status = "deduped"
    db.session.commit()
    return {"ok": True, "stats": stats}


def import_batch_summary(batch_id: int) -> dict[str, Any]:
    batch = LeadImportBatch.query.get(batch_id)
    if not batch:
        return {"error": "Batch غير موجود"}

    rows = batch.rows.all()
    stats = {
        "total": len(rows),
        "valid": 0,
        "invalid": 0,
        "exact": 0,
        "strong": 0,
        "possible": 0,
        "clean": 0,
        "merged": 0,
        "created": 0,
        "review": 0,
        "errors": 0,
    }
    validated = batch.status in ("validated", "deduped", "committed")
    for row in rows:
        if row.validation_errors:
            stats["invalid"] += 1
            continue
        if not validated or not row.normalized_json:
            continue
        stats["valid"] += 1
        level = row.duplicate_level or "NONE"
        if level == "EXACT":
            stats["exact"] += 1
        elif level == "STRONG":
            stats["strong"] += 1
        elif level == "POSSIBLE":
            stats["possible"] += 1
        else:
            stats["clean"] += 1
        action = row.commit_action or ""
        if action == "merged":
            stats["merged"] += 1
        elif action == "created":
            stats["created"] += 1
        elif action == "review":
            stats["review"] += 1
        elif action == "error":
            stats["errors"] += 1

    return {"ok": True, "batch_id": batch_id, "status": batch.status, "stats": stats}


def commit_batch(batch_id: int, *, merge_exact: bool = True, mapping: dict[str, str] | None = None) -> dict[str, Any]:
    batch = LeadImportBatch.query.get(batch_id)
    if not batch:
        return {"error": "Batch غير موجود"}

    if mapping:
        apply_mapping(batch_id, mapping)

    if batch.status in ("preview", "mapped"):
        ensure_batch_mapping(batch_id)
        val = normalize_and_validate_batch(batch_id)
        if val.get("error"):
            return val
        batch = LeadImportBatch.query.get(batch_id)

    if batch.status == "validated":
        ded = detect_duplicates_in_batch(batch_id)
        if ded.get("error"):
            return ded
        batch = LeadImportBatch.query.get(batch_id)

    if not batch.mapping_json:
        return {"error": "يجب ربط الأعمدة قبل الاستيراد"}

    results = {"created": 0, "merged": 0, "skipped": 0, "review": 0, "errors": 0}

    for row in batch.rows.all():
        if row.validation_errors:
            results["errors"] += 1
            continue

        data = json.loads(row.normalized_json or "{}")
        if batch.activity_id:
            data["activity_id"] = batch.activity_id
        if batch.source_label:
            data["source_primary"] = batch.source_label

        if row.duplicate_level == "EXACT" and row.duplicate_lead_id:
            if merge_exact:
                from models.core.leads.models import BusinessLead, LeadSourceRecord
                from services.leads_crm.audit_service import log_lead_action

                target = BusinessLead.query.get(row.duplicate_lead_id)
                if target:
                    updates = {}
                    for field in ("full_address", "instagram_url", "facebook_url", "district", "area", "city"):
                        val = data.get(field)
                        if val and (not getattr(target, field) or field in ("full_address", "instagram_url")):
                            setattr(target, field, val)
                            updates[field] = val
                    if batch.source_label:
                        existing = {s.source_name for s in target.sources}
                        if batch.source_label not in existing:
                            db.session.add(LeadSourceRecord(
                                lead_id=target.id,
                                source_name=batch.source_label,
                                source_detail=f"import row {row.row_number}",
                                import_batch_id=batch.id,
                            ))
                            updates["source"] = batch.source_label
                    log_lead_action(
                        target.id,
                        "import_exact_duplicate_merged",
                        _actor_id(),
                        {"row_number": row.row_number, "updates": updates},
                    )
                    row.result_lead_id = target.id
                    row.commit_action = "merged"
                    results["merged"] += 1
                else:
                    results["skipped"] += 1
            else:
                row.commit_action = "skipped"
                results["skipped"] += 1
            continue

        if row.duplicate_level in ("STRONG", "POSSIBLE"):
            row.commit_action = "review"
            results["review"] += 1
            continue

        lead, resp = create_lead(data, allow_possible_duplicate=True)
        if lead:
            row.result_lead_id = lead.id
            row.commit_action = "created"
            results["created"] += 1
        else:
            row.commit_action = "error"
            row.validation_errors = json.dumps([resp.get("error", "خطأ غير معروف")], ensure_ascii=False)
            results["errors"] += 1

    batch.status = "committed"
    batch.stats_json = json.dumps(results, ensure_ascii=False)
    db.session.commit()
    return {"ok": True, "results": results}
