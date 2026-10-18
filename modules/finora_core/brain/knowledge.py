"""Controlled FINORA knowledge (spec §19): the agent answers product facts ONLY from these sources.

Sources (each item carries its source so answers are traceable):
- ``plan:*``     live ``SubscriptionPlan`` rows (Core DB) — the only source of prices.
- ``vertical:*`` business types FINORA actually provisions (routes/superadmin.BUSINESS_TYPES).
- ``howto:*``    verified AI-Tutor explanations (modules/ai_tutor/knowledge/features.json, clinic vertical).
- ``feature:*`` live feature catalog; existence only, never assumed enabled for a customer.
- ``guide:*``   reviewed product instructions with repository source references.
- ``activity:*`` reviewed activity needs from the tenant-setup registry; not account availability.
- ``doc:*``      published, versioned FcKnowledgeDoc rows (human-authored; drafts are never used).

Knowledge workflow (Phase 9 / Priority 7): draft → in_review → published → retired. Only ``published`` documents inside
their effective window (``effective_from`` ≤ now < ``effective_until``) and matching the customer's business type are
customer-facing. Every transition is an ``FcKnowledgeEvent`` and bumps the global knowledge version that each agent
run records. FINORA CORE never writes knowledge content itself: text must come from a verified FINORA source, named
in ``source``.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from math import log1p
from typing import Any, Iterable

from sqlalchemy.orm import Session

from ..store import get_setting, set_setting
from .extract import normalize
from .models import FcKnowledgeDoc, FcKnowledgeEvent

CATEGORIES = {
    "commerce", "clinics", "dental", "food", "pos", "orders", "inventory", "customers", "suppliers", "shipping",
    "accounting", "employees", "permissions", "subscriptions", "pricing", "tutorials", "troubleshooting", "policies",
    "capabilities",
}
CURRENCY = "د.ع"


@dataclass(frozen=True)
class KnowledgeItem:
    id: str
    category: str
    title: str
    text: str
    source: str
    business_type: str | None = None  # FINORA tenant business type the item applies to; None = all
    search_text: str = ""  # Topic labels/aliases, separate from generic instruction wording.


# ───────────────────────────── sources ─────────────────────────────


def plan_items(s: Session) -> list[KnowledgeItem]:
    from models.core.subscription_plan import SubscriptionPlan

    items = []
    for p in s.query(SubscriptionPlan).order_by(SubscriptionPlan.price_monthly.asc()).all():
        limits = []
        if p.max_users:
            limits.append(f"حتى {p.max_users} مستخدمين")
        if p.max_orders_monthly:
            limits.append(f"حتى {p.max_orders_monthly} طلب شهرياً")
        text = f"باقة {p.name}: {p.price_monthly:,} {CURRENCY} شهرياً"
        if p.price_yearly:
            text += f" أو {p.price_yearly:,} {CURRENCY} سنوياً"
        if limits:
            text += " (" + "، ".join(limits) + ")"
        items.append(KnowledgeItem(f"plan:{p.plan_key}", "pricing", f"باقة {p.name}", text, "subscription_plans"))
    return items


def plan_prices(s: Session) -> set[int]:
    from models.core.subscription_plan import SubscriptionPlan

    prices: set[int] = set()
    for p in s.query(SubscriptionPlan).all():
        prices.update(v for v in (p.price_monthly, p.price_yearly, p.original_price_monthly, p.original_price_yearly) if v)
    return prices


def vertical_items() -> list[KnowledgeItem]:
    from routes.superadmin import BUSINESS_TYPES

    names = "، ".join(BUSINESS_TYPES.values())
    return [KnowledgeItem("vertical:all", "policies", "أنواع الأنشطة التي يدعمها FINORA",
                          f"FINORA يجهز أنظمة لهذه الأنشطة: {names}.", "routes/superadmin.BUSINESS_TYPES")]


@lru_cache(maxsize=1)
def _tutor_features() -> tuple[KnowledgeItem, ...]:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, "ai_tutor", "knowledge", "features.json")
    with open(path, encoding="utf-8") as fh:
        features = json.load(fh)["features"]
    items = []
    for f in features:
        aliases = " ".join(f.get("aliases_ar") or [])
        items.append(
            KnowledgeItem(
                f"howto:{f['id']}", "tutorials", f["title_ar"],
                f"{f['explain_ar']}\n[{aliases}]", "ai_tutor/features.json (verified)", "clinics",
                search_text=f"{f['title_ar']} {aliases}",
            )
        )
    return tuple(items)


def howto_items() -> list[KnowledgeItem]:
    return list(_tutor_features())


def _in_window(r: FcKnowledgeDoc, now: datetime) -> bool:
    return (r.effective_from is None or r.effective_from <= now) and (r.effective_until is None or now < r.effective_until)


def published_docs(s: Session, *, business_type: str | None = None, plan_key: str | None = None,
                   now: datetime | None = None) -> list[KnowledgeItem]:
    """Customer-facing documents: published, inside the effective window, for this business type (and plan)."""
    now = now or datetime.utcnow()
    rows = s.query(FcKnowledgeDoc).filter_by(status="published").all()
    latest: dict[str, FcKnowledgeDoc] = {}
    for r in rows:
        if not _in_window(r, now):
            continue
        if r.business_type and r.business_type != business_type:
            continue
        plans = json.loads(r.supported_plans_json or "[]")
        if plans and plan_key and plan_key not in plans:
            continue
        if r.doc_key not in latest or r.version > latest[r.doc_key].version:
            latest[r.doc_key] = r
    items = []
    for r in latest.values():
        plans = json.loads(r.supported_plans_json or "[]")
        text = r.body + (f"\n(متاح في الباقات: {'، '.join(plans)})" if plans else "")
        items.append(KnowledgeItem(f"doc:{r.doc_key}@v{r.version}", r.category, r.title, text, r.source, r.business_type))
    return items


# ───────────────────────────── authoring (versioned workflow) ─────────────────────────────


class KnowledgeError(ValueError):
    pass


def _bump(s: Session, actor: str) -> int:
    from .observability import KNOWLEDGE_VERSION_KEY

    raw = get_setting(s, KNOWLEDGE_VERSION_KEY, "0") or "0"
    version = (int(raw) if raw.isdigit() else 0) + 1
    set_setting(s, KNOWLEDGE_VERSION_KEY, str(version), actor)
    return version


def _event(s: Session, row: FcKnowledgeDoc, action: str, actor: str, note: str | None, *, bump: bool) -> None:
    from .observability import knowledge_version

    kv = _bump(s, actor) if bump else knowledge_version(s)
    s.add(FcKnowledgeEvent(doc_key=row.doc_key, version=row.version, action=action, actor=actor[:120],
                           note=(note or None) and note[:300], knowledge_version=kv))


def _parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise KnowledgeError("invalid date") from exc


def save_draft(s: Session, *, doc_key: str, category: str, title: str, body: str, source: str,
               author: str = "system", business_type: str | None = None, module: str | None = None,
               feature: str | None = None, supported_plans: list[str] | None = None, effective_from: Any = None,
               effective_until: Any = None, revision_note: str | None = None) -> FcKnowledgeDoc:
    if category not in CATEGORIES:
        raise KnowledgeError(f"unknown category {category!r}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,79}", doc_key or ""):
        raise KnowledgeError("invalid doc_key")
    if not (title or "").strip() or not (body or "").strip():
        raise KnowledgeError("title and body are required")
    if not (source or "").strip():
        raise KnowledgeError("a verified FINORA source is required")
    if business_type:
        from routes.superadmin import BUSINESS_TYPES

        if business_type not in BUSINESS_TYPES:
            raise KnowledgeError(f"unknown business type {business_type!r}")
    plans = [p for p in (supported_plans or []) if p]
    if plans:
        from models.core.subscription_plan import SubscriptionPlan

        known = {p.plan_key for p in s.query(SubscriptionPlan).all()}
        unknown = [p for p in plans if p not in known]
        if unknown:
            raise KnowledgeError(f"unknown plans: {', '.join(unknown)}")
    start, end = _parse_dt(effective_from), _parse_dt(effective_until)
    if start and end and end <= start:
        raise KnowledgeError("effective_until must be after effective_from")
    last = s.query(FcKnowledgeDoc).filter_by(doc_key=doc_key).order_by(FcKnowledgeDoc.version.desc()).first()
    row = FcKnowledgeDoc(doc_key=doc_key, version=(last.version + 1) if last else 1, category=category,
                         title=title.strip()[:200], body=body.strip(), status="draft", source=source.strip()[:200],
                         business_type=business_type or None, module=(module or None) and module[:60],
                         feature=(feature or None) and feature[:80],
                         supported_plans_json=json.dumps(plans) if plans else None, effective_from=start,
                         effective_until=end, author=author[:120],
                         revision_note=(revision_note or None) and revision_note[:300])
    s.add(row)
    s.flush()
    _event(s, row, "draft", author, revision_note, bump=False)
    return row


def _get(s: Session, doc_key: str, version: int) -> FcKnowledgeDoc:
    row = s.query(FcKnowledgeDoc).filter_by(doc_key=doc_key, version=version).first()
    if row is None:
        raise KnowledgeError("no such document version")
    return row


def submit(s: Session, doc_key: str, version: int, *, actor: str, note: str | None = None) -> FcKnowledgeDoc:
    row = _get(s, doc_key, version)
    if row.status != "draft":
        raise KnowledgeError("only drafts can be submitted for review")
    row.status = "in_review"
    _event(s, row, "submit", actor, note, bump=False)
    return row


def publish(s: Session, doc_key: str, version: int, *, actor: str, note: str | None = None) -> FcKnowledgeDoc:
    row = _get(s, doc_key, version)
    if row.status not in {"draft", "in_review"}:
        raise KnowledgeError("only drafts or documents in review can be published")
    for other in s.query(FcKnowledgeDoc).filter_by(doc_key=doc_key, status="published").all():
        other.status = "retired"
        _event(s, other, "retire", actor, f"replaced by v{row.version}", bump=False)
    row.status = "published"
    row.published_by = actor
    row.reviewed_by = actor
    row.published_at = datetime.utcnow()
    _event(s, row, "publish", actor, note, bump=True)
    return row


def reject(s: Session, doc_key: str, version: int, *, actor: str, note: str) -> FcKnowledgeDoc:
    row = _get(s, doc_key, version)
    if row.status != "in_review":
        raise KnowledgeError("only documents in review can be rejected")
    if not (note or "").strip():
        raise KnowledgeError("a rejection needs a note")
    row.status = "draft"
    _event(s, row, "reject", actor, note, bump=False)
    return row


def retire(s: Session, doc_key: str, version: int, *, actor: str, note: str | None = None) -> FcKnowledgeDoc:
    row = _get(s, doc_key, version)
    if row.status != "published":
        raise KnowledgeError("only published documents can be retired")
    row.status = "retired"
    _event(s, row, "retire", actor, note, bump=True)
    return row


def doc_dto(r: FcKnowledgeDoc) -> dict[str, Any]:
    def iso(v):
        return v.isoformat() + "Z" if v else None

    return {"docKey": r.doc_key, "version": r.version, "category": r.category, "title": r.title, "body": r.body,
            "status": r.status, "source": r.source, "businessType": r.business_type, "module": r.module,
            "feature": r.feature, "supportedPlans": json.loads(r.supported_plans_json or "[]"),
            "effectiveFrom": iso(r.effective_from), "effectiveUntil": iso(r.effective_until), "author": r.author,
            "revisionNote": r.revision_note, "reviewedBy": r.reviewed_by, "publishedBy": r.published_by,
            "createdAt": iso(r.created_at), "publishedAt": iso(r.published_at)}


def revisions(s: Session, doc_key: str) -> list[dict[str, Any]]:
    rows = s.query(FcKnowledgeEvent).filter_by(doc_key=doc_key).order_by(FcKnowledgeEvent.id.asc()).all()
    return [{"version": e.version, "action": e.action, "actor": e.actor, "note": e.note,
             "knowledgeVersion": e.knowledge_version, "at": e.created_at.isoformat() + "Z"} for e in rows]


# ───────────────────────────── retrieval ─────────────────────────────

_STOP = {"في", "من", "على", "الى", "عن", "هل", "شو", "شنو", "كم", "و", "او", "ما", "مع", "انا", "اريد", "ابي", "هذا", "هاي",
         "شلون", "كيف", "وين", "اضيف", "اسوي", "اعمل", "اسجل", "اطلع", "افتح", "استخدم", "علمني", "ممكن", "اكدر",
         "النظام", "البرنامج", "فينورا", "finora", "the", "how", "can", "do", "i", "to", "a", "add", "use", "my"}
_STOP.update({"عندي", "عدنا", "عدي", "لدينا", "عندنا", "لدي", "have", "has", "does", "what", "where"})
_STOP.update({"الي", "اللي", "هاي", "هذا", "اريدها", "عليه", "علي", "بيها", "بيه", "لو", "بس", "حتى", "بعد", "اكدر", "اقدر"})

# Search vocabulary only: these aliases never establish that a feature exists or is enabled.
_TOPIC_WORDS = (
    {"مخزن", "مخزون", "مخازن"}, {"مصروف", "مصروفات", "مصاريف"},
    {"زبون", "زبائن", "زبونك", "عميل", "عملاء"}, {"مورد", "موردين", "موردون"},
    {"قسط", "اقساط", "تقسيط"}, {"راتب", "رواتب"}, {"صلاحيات", "صلاحية", "صلاحيه"},
)


def _terms(text: str) -> set[str]:
    # Arabic punctuation is inside U+0600..06FF; it must not become part of the topic token.
    words = re.findall(r"[^\W_]+", normalize(text))
    out = set()
    for w in words:
        if w in _STOP or len(w) < 2:
            continue
        out.add(w)
        if w.startswith("ال") and len(w) > 4:
            out.add(w[2:])
        for prefix in ("بال", "وال", "لل"):
            if w.startswith(prefix) and len(w) > len(prefix) + 2:
                out.add(w[len(prefix):])
    for group in _TOPIC_WORDS:
        if out & group:
            out.difference_update(group)
            out.add(min(group))  # One concept gets one vote, regardless of how many synonyms it has.
    return out


def retrieve(items: Iterable[KnowledgeItem], query: str, *, categories: set[str] | None = None,
             limit: int = 5) -> list[KnowledgeItem]:
    q = _terms(query)
    if not q:
        return []
    documents = [(item, _terms(item.search_text or f"{item.title} {item.text}"), _terms(item.title))
                 for item in items if not categories or item.category in categories]
    frequencies = Counter(term for _, terms, _ in documents for term in terms)
    scored = []
    for item, doc_terms, title in documents:
        matched = q & doc_terms
        if matched:
            # Specific terms such as debt/payment outrank the common customer/topic word.
            score = sum(log1p((len(documents) + 1) / (frequencies[term] + 0.5))
                        * (1.35 if term in title else 1) for term in matched) / (len(q) ** 0.5)
            if item.category == "tutorials":
                score += 0.15
            # Match specific task phrases before a general guide sharing only a topic word.
            if len(title) > 1 and title <= q:
                score += 0.5
            scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]


def retrieval_query(text: str, recent: list[dict[str, str]]) -> str:
    """Short lesson follow-ups retain the last customer topic, without using another customer's data."""
    followup = r"(?:تمام[ ،]*|سويت[ ،]*|خلصت[ ،]*)?(?:شنو\s+بعدها|بعدها|شنو\s+التالي|الخطوه\s+التاليه|كمل|next|done|continue|تمام|سويت|خلصت|ما (?:لقيت|لكيت|شفت) (?:الزر|الخيار)|(?:و?اذا )?(?:ما ظهر|ما طلع)|شلون (?:اعدلها|اغيرها|احفظها)|مو واضح|وضحلي اكثر)[ ؟?!.،]*"
    if len(text) > 100 or not re.fullmatch(followup, normalize(text)):
        return text
    from .extract import extract

    for message in reversed(recent):
        previous = message["text"]
        if message["role"] != "customer" or previous.strip() == text.strip() or re.fullmatch(followup, normalize(previous)):
            continue
        if "training_request" in extract(previous).intents:
            return f"{previous}\n{text}"
        # A newer customer topic supersedes the older lesson; don't revive stale instructions.
        if previous.strip():
            break
    return text


def all_items(s: Session, *, business_type: str | None = None, plan_key: str | None = None) -> list[KnowledgeItem]:
    """Everything the agent may cite for this customer (business type = FINORA tenant type, when known)."""
    from .product_knowledge import activity_items, catalog_items, guide_items

    tutor = howto_items() if business_type in (None, "clinics") else []
    return (plan_items(s) + vertical_items() + catalog_items(business_type=business_type)
            + guide_items(business_type=business_type) + tutor
            + activity_items(business_type=business_type)
            + published_docs(s, business_type=business_type, plan_key=plan_key))
