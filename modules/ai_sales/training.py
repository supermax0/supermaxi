"""Training-only reply generation for the reset Sales AI."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy import or_

from extensions import db
from models.product import Product
from .learning import extract_keywords, normalize_text
from .models import AISalesMessage, AISalesProductProfile, AISalesReplyExample


TRAINING_SOURCE_LIKE = "training_like"
TRAINING_SOURCE_CORRECTION = "training_correction"
APPROVED_TRAINING_SOURCES = (TRAINING_SOURCE_LIKE, TRAINING_SOURCE_CORRECTION)


def archive_old_reply_examples() -> int:
    return AISalesReplyExample.query.filter(
        AISalesReplyExample.rating_source.is_(None),
        AISalesReplyExample.is_active.is_(True),
        AISalesReplyExample.curation_status != "archived_old_ai",
    ).update(
        {
            "is_active": False,
            "curation_status": "archived_old_ai",
            "curation_reason": "Archived when Sales AI was reset to training-only mode.",
        },
        synchronize_session=False,
    )


def generate_training_reply(question: str, product_id: int | None = None) -> dict:
    question = str(question or "").strip()
    if not question:
        raise ValueError("اكتب سؤال التدريب أولاً")
    product = _resolve_product(question, product_id)
    examples = _approved_examples(question, product.id if product else None, limit=3)
    reply = _compose_reply(question, product, examples)
    raw_payload = {
        "training": True,
        "question": question,
        "product_id": product.id if product else None,
        "reply": reply,
        "used_example_ids": [row.id for row in examples],
    }
    return {
        "reply": reply,
        "matched_product": _product_payload(product),
        "used_examples_count": len(examples),
        "needs_product_selection": product is None,
        "raw_payload": raw_payload,
    }


def approve_training_feedback(
    message_id: int,
    rating: str,
    product_id: int | None,
    corrected_reply: str,
    employee_id: int | None,
) -> AISalesReplyExample:
    rating = str(rating or "").strip().lower()
    if rating not in {"like", "dislike"}:
        raise ValueError("التقييم يجب أن يكون لايك أو دسلايك")
    message = AISalesMessage.query.get(int(message_id or 0))
    if not message or message.sender_type != "ai":
        raise ValueError("رد التدريب غير موجود")
    payload = message.get_media_metadata().get("training") or {}
    question = str(payload.get("question") or "").strip()
    ai_reply = str(payload.get("reply") or message.text_content or "").strip()
    if not question:
        raise ValueError("لا يوجد سؤال مرتبط بهذا الرد")
    final_reply = ai_reply if rating == "like" else str(corrected_reply or "").strip()
    if rating == "dislike" and not final_reply:
        raise ValueError("اكتب الرد الصحيح حتى يتعلم عليه النظام")
    resolved_product_id = int(product_id or payload.get("product_id") or 0) or None
    if rating == "dislike" and not resolved_product_id:
        raise ValueError("اختيار المنتج مطلوب عند تصحيح الرد")
    source = TRAINING_SOURCE_LIKE if rating == "like" else TRAINING_SOURCE_CORRECTION
    row = _upsert_training_example(
        question=question,
        reply=final_reply,
        product_id=resolved_product_id,
        source=source,
        message=message,
        employee_id=employee_id,
    )
    payload["rating"] = rating
    payload["approved_example_id"] = row.id
    if rating == "dislike":
        payload["corrected_reply"] = final_reply
    message.set_media_metadata({"training": payload})
    return row


def _upsert_training_example(
    *,
    question: str,
    reply: str,
    product_id: int | None,
    source: str,
    message: AISalesMessage,
    employee_id: int | None,
) -> AISalesReplyExample:
    normalized_customer = normalize_text(question)
    signature = hashlib.sha256(f"training\n{product_id or 0}\n{normalized_customer}\n{normalize_text(reply)}".encode("utf-8")).hexdigest()
    row = AISalesReplyExample.query.filter_by(signature=signature).first()
    if not row:
        row = AISalesReplyExample(signature=signature, occurrence_count=0)
        db.session.add(row)
    row.intent = _intent(question)
    row.customer_example = question
    row.employee_example = reply
    row.normalized_customer = normalized_customer
    row.set_keywords(extract_keywords(question + " " + reply, limit=12))
    row.quality_score = 100
    row.occurrence_count = int(row.occurrence_count or 0) + 1
    row.source_conversation_id = message.conversation_id
    row.source_customer_message_id = None
    row.source_employee_message_id = message.id
    row.source_type = "training_chat"
    row.product_id = product_id
    row.rating_source = source
    row.approved_by_employee_id = employee_id
    row.approved_at = datetime.utcnow()
    row.reviewed_at = row.approved_at
    row.curation_status = "approved"
    row.curation_reason = "Approved from training chat feedback."
    row.is_active = True
    return row


def _compose_reply(question: str, product: Product | None, examples: list[AISalesReplyExample]) -> str:
    if examples:
        best = examples[0].employee_example.strip()
        if best:
            return best[:650]
    if not product:
        return "حددلي المنتج المقصود حتى أجاوبك بسعر ومواصفات صحيحة من النظام."
    profile = AISalesProductProfile.query.filter_by(product_id=product.id, is_active=True).first()
    parts = [f"{product.name} متوفر ضمن بيانات Finora."]
    if getattr(product, "sale_price", None):
        parts.append(f"• السعر: {int(product.sale_price):,} د.ع")
    if product.description:
        parts.append(f"• المواصفات: {_shorten(product.description, 170)}")
    if profile and profile.warranty_text:
        parts.append(f"• الضمان: {profile.warranty_text}")
    if profile and profile.delivery_text:
        parts.append(f"• التوصيل: {profile.delivery_text}")
    points = profile.get_selling_points() if profile else []
    if points:
        parts.append(f"• يفيدك بـ: {_shorten(str(points[0]), 120)}")
    parts.append("تحب أعتمد هذا المنتج لو تريد أقارنلك ببديل؟")
    return "\n".join(parts)[:650]


def _approved_examples(question: str, product_id: int | None, limit: int) -> list[AISalesReplyExample]:
    normalized = normalize_text(question)
    query = AISalesReplyExample.query.filter(
        AISalesReplyExample.is_active.is_(True),
        AISalesReplyExample.curation_status == "approved",
        AISalesReplyExample.rating_source.in_(APPROVED_TRAINING_SOURCES),
    )
    if product_id:
        query = query.filter(or_(AISalesReplyExample.product_id == product_id, AISalesReplyExample.product_id.is_(None)))
    rows = query.order_by(AISalesReplyExample.quality_score.desc(), AISalesReplyExample.updated_at.desc()).limit(150).all()
    scored = []
    for row in rows:
        score = SequenceMatcher(None, normalized, row.normalized_customer or "").ratio()
        keyword_bonus = sum(0.08 for keyword in row.get_keywords() if keyword and keyword in normalized)
        product_bonus = 0.2 if product_id and row.product_id == product_id else 0
        scored.append((score + keyword_bonus + product_bonus, row))
    return [row for score, row in sorted(scored, key=lambda item: item[0], reverse=True)[:limit] if score >= 0.18]


def _resolve_product(question: str, product_id: int | None) -> Product | None:
    if product_id:
        return Product.query.get(product_id)
    normalized = normalize_text(question)
    if not normalized:
        return None
    terms = [token for token in normalized.split() if len(token) >= 2][:6]
    query = Product.query
    filters = []
    for term in terms:
        like = f"%{term}%"
        filters.extend([Product.name.ilike(like), Product.sku.ilike(like), Product.barcode.ilike(like)])
    rows = query.filter(or_(*filters)).limit(30).all() if filters else []
    if not rows:
        return None
    scored = []
    for product in rows:
        haystack = normalize_text(" ".join(str(value or "") for value in (product.name, product.sku, product.barcode, product.description)))
        score = SequenceMatcher(None, normalized, haystack[: max(len(normalized), 1)]).ratio()
        score += sum(0.15 for term in terms if term in haystack)
        scored.append((score, product))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1] if scored and scored[0][0] >= 0.25 else None


def _product_payload(product: Product | None) -> dict | None:
    if not product:
        return None
    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku or "",
        "barcode": product.barcode or "",
        "sale_price": int(product.sale_price or 0),
    }


def _intent(value: str) -> str:
    normalized = normalize_text(value)
    if re.search(r"سعر|بكم|شكد|بيش|كم", normalized):
        return "price"
    if re.search(r"مواصفات|حجم|قدم|قياس|ضمان", normalized):
        return "specifications"
    return "general"


def _shorten(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"
