from __future__ import annotations

from collections import deque
import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List
from threading import Lock

from flask import current_app

from extensions import db
from models.ai_agent import AgentExecution, AgentExecutionLog, AgentWorkflow
from models.comment_log import CommentLog, is_comment_already_replied
from models.customer import Customer
from models.invoice import Invoice
from models.order_item import OrderItem
from models.product import Product
from models.social_account import SocialAccount
from models.social_post import SocialPost
from utils.inventory_movements import validate_sale_quantity
from social_ai.ai_engine import generate_caption, generate_comment_reply, get_client
from social_ai.image_generator import generate_image
from social_ai.messaging import send_telegram_message, send_telegram_photo, send_whatsapp_message
from social_ai.publish_manager import publish_post_to_accounts
from services.facebook_service import fetch_comments as fb_fetch_comments, reply_comment as fb_reply_comment
from services.instagram_service import fetch_comments as ig_fetch_comments, reply_comment as ig_reply_comment
from services.tiktok_service import fetch_comments as tiktok_fetch_comments, reply_comment as tiktok_reply_comment

_CHAT_MEMORY_LOCK = Lock()
_CHAT_MEMORY: dict[str, deque[dict[str, str]]] = {}
# أدوار مستخدم/مساعد (كل دور = رسالتان). زيادة عمق الذاكرة للمحادثات الطويلة.
_CHAT_MEMORY_MAX_TURNS = 14

# كلمات مساعدة لتصنيف النية عند فشل JSON (عربي/إنجليزي خفيف)
_INTENT_ORDER_HINTS = frozenset(
    (
        "احجز",
        "حجز",
        "طلب",
        "طلبية",
        "شراء",
        "أريد",
        "اريد",
        "ابغى",
        "ابغي",
        "موعد",
        "order",
        "book",
        "booking",
        "reserve",
    )
)
_INTENT_QUESTION_HINTS = frozenset(
    ("؟", "?", "كيف", "وش", "شنو", "شلون", "هل ", "هل\n", "ماذا", "لماذا", "when", "what", "how ", "why ")
)
_BOOKING_COMMIT_HINTS = frozenset(
    (
        "احجز",
        "احجزل",
        "حجز",
        "تمم",
        "اتمم",
        "أتمم",
        "اكمل",
        "أكمل",
        "نفذ",
        "نفّذ",
        "ثبت الطلب",
        "ثبّت الطلب",
        "finalize",
        "confirm order",
        "book now",
    )
)


def _is_retriable_openai_error(exc: BaseException) -> bool:
    """أخطاء مؤقتة تستحق إعادة المحاولة (معدل، مهلة، خادم)."""
    name = type(exc).__name__
    if any(x in name for x in ("Timeout", "ConnectTimeout", "ReadTimeout", "ConnectionError", "RateLimit")):
        return True
    code = getattr(exc, "status_code", None)
    if code is None and hasattr(exc, "response"):
        try:
            code = getattr(exc.response, "status_code", None)
        except Exception:
            code = None
    if code is not None:
        try:
            c = int(code)
        except (TypeError, ValueError):
            c = 0
        return c in (408, 409, 429, 500, 502, 503, 529)
    return False


def _openai_chat_with_retry(client: Any, *, max_attempts: int, **kwargs: Any) -> Any:
    """استدعاء chat.completions.create مع تراجع أسي + عشوائي خفيف."""
    last: BaseException | None = None
    attempts = max(1, min(int(max_attempts), 8))
    for attempt in range(attempts):
        try:
            return client.chat.completions.create(**kwargs)
        except BaseException as e:
            last = e
            if not _is_retriable_openai_error(e) or attempt >= attempts - 1:
                raise
            delay = (0.45 * (2**attempt)) + random.uniform(0, 0.25)
            current_app.logger.warning(
                "OpenAI chat retry %s/%s after %s: %s",
                attempt + 1,
                attempts,
                round(delay, 2),
                type(e).__name__,
            )
            time.sleep(delay)
    assert last is not None
    raise last


def _heuristic_user_intent(message: str) -> str | None:
    """تخمين نوايا من النص عند غياب JSON صالح."""
    if not message or not str(message).strip():
        return None
    t = _normalize_ar_digits(str(message).lower())
    tokens = set(re.findall(r"[\u0600-\u06FFa-z]+", t))
    if tokens & _INTENT_ORDER_HINTS:
        return "order"
    if any(h in t for h in _INTENT_QUESTION_HINTS):
        return "question"
    return None


def _refine_intent_with_context(message: str, history: str, current: str) -> str:
    """يرفع التصنيف إلى order عند إرسال بيانات تواصل أو إتمام طلب مع سياق منتج/سعر في السجل."""
    if current == "order":
        return current
    msg = (message or "").strip()
    hist = (history or "").strip()
    if _is_booking_commit_message(msg):
        return "order"
    if _extract_local_mobile_phone(msg):
        return "order"
    digits_only = re.sub(r"\D", "", _normalize_ar_digits(msg))
    if len(digits_only) >= 10 and len(msg) >= 6:
        return "order"
    commerce = (
        "شاشة",
        "بوصة",
        "دينار",
        "مخزون",
        "السعر",
        "سعر",
        "المنتج",
        "عرض",
        "موديل",
        "product",
        "price",
    )
    if any(c in hist for c in commerce):
        if any(
            w in msg
            for w in (
                "تمم",
                "تم ",
                "أكمل",
                "اكمل",
                "الاسم",
                "العنوان",
                "الهاتف",
                "رقم",
                "معلومات",
                "أرسل",
                "ارسل",
            )
        ):
            return "order"
        if len(digits_only) >= 10:
            return "order"
        if len(msg) > 30 and re.search(r"\d{5,}", _normalize_ar_digits(msg)):
            return "order"
    return current


def _parse_intent_value(text: str) -> str:
    """يستخرج intent من JSON؛ يعيد unknown إن تعذّر."""
    parsed = _try_parse_booking_dict_from_text(text)
    if isinstance(parsed, dict):
        v = str(parsed.get("intent") or "").strip().lower()
        if v in ("order", "question", "unknown"):
            return v
    return "unknown"


def _strip_booking_json_for_user_display(text: str) -> str:
    """يزيل كتل JSON/``` من رد الحجز حتى لا يظهر للزبون في تيليجرام."""
    if not text or not str(text).strip():
        return ""
    t = str(text).strip()
    t = re.sub(r"```(?:json)?\s*[\s\S]*?```", "", t, flags=re.IGNORECASE)
    t = t.strip()
    for _ in range(4):
        m = re.search(r"\{[\s\S]*\}\s*$", t)
        if not m:
            break
        candidate = m.group(0).strip()
        try:
            j = json.loads(candidate)
        except Exception:
            break
        if not isinstance(j, dict):
            break
        if isinstance(j.get("booking"), dict) or j.get("type") == "order" or any(
            k in j for k in ("product_name", "service", "phone", "name", "quantity")
        ):
            t = t[: m.start()].rstrip()
        else:
            break
    return t.strip()


def _sanitize_quantity_value(val: Any) -> int | None:
    """كمية صحيحة موجبة ومحدودة للحجز."""
    if val is None:
        return None
    s = _normalize_ar_digits(str(val).strip())
    s = re.sub(r"[^\d.]", "", s)
    if not s:
        return None
    try:
        q = int(float(s))
    except (TypeError, ValueError):
        return None
    if q < 1:
        return None
    return min(q, 99_999)


def _clean_extracted_field(text: str, max_len: int = 180) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip(" \t\r\n:;,.،-")
    if len(s) > max_len:
        s = s[:max_len].strip()
    return s


def _extract_name_from_text(text: str) -> str | None:
    if not text or not str(text).strip():
        return None
    src = str(text)
    patterns = [
        r"(?:^|\n|،|,)\s*(?:الاسم(?:\s+الكامل)?|اسمي|اني|أنا)\s*(?:هو|:|-)?\s*([^\n\r,،]{2,100})",
        r"(?:^|\n)\s*name\s*(?:is|:|-)?\s*([A-Za-z\u0600-\u06FF\s]{2,100})",
    ]
    for pat in patterns:
        m = re.search(pat, src, flags=re.IGNORECASE)
        if not m:
            continue
        raw = m.group(1)
        raw = re.split(
            r"(?:\bالعنوان\b|\bعنوان\b|\bالهاتف\b|\bرقم\b|\bphone\b|\baddress\b|\bservice\b|\bproduct\b)",
            raw,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        cand = _clean_extracted_field(raw, max_len=80)
        if not cand:
            continue
        if re.search(r"\d", cand):
            continue
        if cand in {"احجز", "حجز", "نعم", "لا", "تم"}:
            continue
        if len(cand) < 2:
            continue
        return cand
    return None


def _extract_address_from_text(text: str) -> str | None:
    if not text or not str(text).strip():
        return None
    src = str(text)
    patterns = [
        r"(?:^|\n|،|,)\s*(?:العنوان|عنواني|address)\s*(?:هو|:|-)?\s*([^\n\r]{4,220})",
    ]
    for pat in patterns:
        m = re.search(pat, src, flags=re.IGNORECASE)
        if not m:
            continue
        raw = m.group(1)
        raw = re.split(r"(?:\bالرقم\b|\bالهاتف\b|\bphone\b|\bname\b)", raw, maxsplit=1, flags=re.IGNORECASE)[0]
        cand = _clean_extracted_field(raw, max_len=160)
        if len(cand) >= 4:
            return cand
    return None


def _extract_quantity_from_text(text: str) -> int | None:
    if not text or not str(text).strip():
        return None
    t = _normalize_ar_digits(str(text).lower())
    for pat in (
        r"(?:الكمية|كمية|العدد|عدد)\s*(?:هو|:|-)?\s*(\d{1,5})",
        r"(\d{1,5})\s*(?:قطعة|قطع|حبة|حبات|وحدة|وحدات|pcs|pc)\b",
    ):
        m = re.search(pat, t, flags=re.IGNORECASE)
        if not m:
            continue
        q = _sanitize_quantity_value(m.group(1))
        if q is not None:
            return q
    return None


def _is_booking_commit_message(message: str) -> bool:
    if not message or not str(message).strip():
        return False
    t = _normalize_ar_digits(str(message).lower())
    return any(h in t for h in _BOOKING_COMMIT_HINTS)


def _infer_product_from_context(context: Dict[str, Any]) -> None:
    if context.get("product_id") is not None and str(context.get("product_id")).strip() != "":
        return
    if str(context.get("product_name") or context.get("product") or "").strip():
        return
    query_blob = _query_blob_for_match(context)
    if not query_blob.strip():
        return
    try:
        products = Product.query.filter(Product.active == True).limit(1500).all()  # noqa: E712
    except Exception:
        return
    if not products:
        return
    scored: list[tuple[int, Product]] = []
    for p in products:
        s = _score_product_match(p, query_blob)
        if s > 0:
            scored.append((s, p))
    if not scored:
        return
    scored.sort(key=lambda x: (-x[0], x[1].id))
    top_score, top = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0
    # لا نفترض منتجاً إذا التطابق ضعيف/ملتبس.
    if top_score < 6:
        return
    if second_score and (top_score - second_score) < 2:
        return
    context["product_id"] = int(top.id)
    if top.name and not str(context.get("product_name") or context.get("product") or "").strip():
        context["product_name"] = str(top.name)
        context["product"] = str(top.name)


def _infer_booking_fields_from_conversation(context: Dict[str, Any]) -> None:
    blob = "\n".join(
        [
            str(context.get("message_text") or ""),
            str(context.get("conversation_history") or ""),
            str(context.get("conversation_for_booking") or ""),
            str(context.get("booking_parse_source") or ""),
        ]
    ).strip()
    if not blob:
        return

    if not str(context.get("customer_name") or context.get("name") or "").strip():
        nm = _extract_name_from_text(blob)
        if nm:
            context["customer_name"] = nm
            context["name"] = nm

    if not str(context.get("address") or "").strip():
        addr = _extract_address_from_text(blob)
        if addr:
            context["address"] = addr

    if not str(context.get("phone") or "").strip():
        _infer_phone_into_context(context)

    if context.get("quantity") in (None, "", 0):
        q = _extract_quantity_from_text(str(context.get("message_text") or ""))
        if q is None:
            q = _extract_quantity_from_text(blob)
        if q is not None:
            context["quantity"] = q

    msg_now = str(context.get("message_text") or "")
    intent_now = str(context.get("user_intent") or "").strip().lower()
    if (
        intent_now == "order"
        or _is_booking_commit_message(msg_now)
        or _heuristic_user_intent(msg_now) == "order"
    ):
        _infer_product_from_context(context)


def _booking_fields_ready(
    context: Dict[str, Any],
    *,
    require_name: bool,
    require_phone: bool,
    require_address: bool,
) -> bool:
    name_ok = bool(str(context.get("customer_name") or context.get("name") or "").strip())
    phone = str(context.get("phone") or "").strip()
    phone_ok = bool(_extract_local_mobile_phone(phone)) and not _is_placeholder_telegram_phone(phone)
    addr_ok = len(str(context.get("address") or "").strip()) >= 4
    product_ok = bool(
        (context.get("product_id") is not None and str(context.get("product_id")).strip() != "")
        or str(context.get("product_name") or context.get("product") or "").strip()
    )
    if not product_ok:
        return False
    if require_name and not name_ok:
        return False
    if require_phone and not phone_ok:
        return False
    if require_address and not addr_ok:
        return False
    return True


def _missing_booking_fields(
    context: Dict[str, Any],
    *,
    require_name: bool,
    require_phone: bool,
    require_address: bool,
) -> list[str]:
    missing: list[str] = []
    if not (
        (context.get("product_id") is not None and str(context.get("product_id")).strip() != "")
        or str(context.get("product_name") or context.get("product") or "").strip()
    ):
        missing.append("المنتج")
    if require_name and not str(context.get("customer_name") or context.get("name") or "").strip():
        missing.append("الاسم الكامل")
    phone = str(context.get("phone") or "").strip()
    if require_phone and (not _extract_local_mobile_phone(phone) or _is_placeholder_telegram_phone(phone)):
        missing.append("رقم الهاتف")
    if require_address and len(str(context.get("address") or "").strip()) < 4:
        missing.append("العنوان")
    return missing


@dataclass
class NodeDef:
    id: str
    type: str
    data: Dict[str, Any]


def _build_graph(workflow: AgentWorkflow) -> List[NodeDef]:
    """
    Build an execution order for Flask runner.

    - Prefer following `edges` deterministically (start -> next -> ...).
    - Fall back to original nodes list order if edges are missing/invalid.

    Note: Node backend has its own runner; this is only for the Flask fallback.
    """
    graph = workflow.graph_json or {}
    nodes_data = graph.get("nodes") or []
    edges_data = graph.get("edges") or []

    # Build node map first
    nodes_by_id: dict[str, NodeDef] = {}
    linear_nodes: List[NodeDef] = []
    for n in nodes_data if isinstance(nodes_data, list) else []:
        nd = NodeDef(id=str(n.get("id")), type=n.get("type") or "", data=n.get("data") or {})
        nodes_by_id[nd.id] = nd
        linear_nodes.append(nd)

    # If no edges, keep previous behavior
    if not isinstance(edges_data, list) or not edges_data:
        return linear_nodes

    # Build deterministic adjacency and indegree from edges
    next_map: dict[str, List[str]] = {}
    indegree: dict[str, int] = {nid: 0 for nid in nodes_by_id}
    for e in edges_data:
        if not isinstance(e, dict):
            continue
        src = str(e.get("source") or "")
        tgt = str(e.get("target") or "")
        if not src or not tgt:
            continue
        if src not in nodes_by_id or tgt not in nodes_by_id:
            continue
        next_map.setdefault(src, []).append(tgt)
        indegree[tgt] = indegree.get(tgt, 0) + 1

    # Topological sort (Kahn) to ensure upstream nodes run first, especially knowledge_base -> ai
    order_index = {nd.id: idx for idx, nd in enumerate(linear_nodes)}
    queue: List[str] = [
        nd.id
        for nd in linear_nodes
        if indegree.get(nd.id, 0) == 0
    ]
    queue.sort(key=lambda nid: order_index.get(nid, 10**9))

    ordered_ids: List[str] = []
    while queue:
        nid = queue.pop(0)
        ordered_ids.append(nid)
        for nxt in next_map.get(nid, []):
            indegree[nxt] = max(0, indegree.get(nxt, 0) - 1)
            if indegree[nxt] == 0:
                queue.append(nxt)
        queue.sort(key=lambda x: order_index.get(x, 10**9))

    # If graph contains a cycle or invalid wiring, keep remaining nodes in original order.
    if len(ordered_ids) < len(linear_nodes):
        for nd in linear_nodes:
            if nd.id not in ordered_ids:
                ordered_ids.append(nd.id)

    return [nodes_by_id[nid] for nid in ordered_ids if nid in nodes_by_id]


def _render_prompt(template: str, context: Dict[str, Any]) -> str:
    """استبدال {{var}} بقيم من الـ context."""

    def _repl(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        value = context.get(key)
        return "" if value is None else str(value)

    return re.sub(r"\{\{\s*([\w\.]+)\s*\}\}", _repl, template)


def _render_template(template: str, context: Dict[str, Any]) -> str:
    """مساعد بسيط لاستدعاء _render_prompt من اسم أوضح لعقد الإرسال."""
    return _render_prompt(template, context)


def _should_run_node(node: NodeDef, context: Dict[str, Any]) -> bool:
    """تقييم node.data.run_if: 'key:value' أو 'key:!value'. فارغ = تشغيل دائماً."""
    data = node.data or {}
    rf = data.get("run_if")
    if rf is None or str(rf).strip() == "":
        return True
    s = str(rf).strip()
    if s in ("*",):
        return True
    if ":" not in s:
        return True
    key, _, val = s.partition(":")
    key = key.strip()
    val = val.strip()
    if not key:
        return True
    cur = context.get(key)
    cur_s = "" if cur is None else str(cur).strip()
    if val.startswith("!"):
        return cur_s != val[1:].strip()
    return cur_s == val


def _memory_key(context: Dict[str, Any]) -> str | None:
    workflow_id = context.get("workflow_id")
    chat_id = context.get("chat_id")
    if workflow_id is None or chat_id is None:
        return None
    return f"{workflow_id}:{chat_id}"


def _normalize_ar_digits(text: str) -> str:
    if not text:
        return ""
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    return text.translate(trans)


def _extract_local_mobile_phone(text: str) -> str | None:
    """استخراج رقم جوال محلي (مثال عراقي 07xxxxxxxx) من نص حر."""
    if not text or not str(text).strip():
        return None
    t = _normalize_ar_digits(text)
    d = re.sub(r"\D", "", t)
    if not d:
        return None
    m = re.search(r"(07\d{9})", d)
    if m:
        return m.group(1)
    m2 = re.search(r"(7\d{9})", d)
    if m2 and len(m2.group(1)) == 10:
        return "0" + m2.group(1)
    return None


def _infer_phone_into_context(context: Dict[str, Any]) -> None:
    """يملأ context['phone'] من رسالة المستخدم أو سجل المحادثة إن وُجد رقم."""
    if str(context.get("phone") or "").strip():
        return
    parts = [
        str(context.get("message_text") or ""),
        str(context.get("conversation_history") or ""),
    ]
    blob = "\n".join(parts)
    found = _extract_local_mobile_phone(blob)
    if found:
        context["phone"] = found


def _is_placeholder_telegram_phone(phone: str) -> bool:
    p = (phone or "").strip()
    return p.startswith("tg-") or len(re.sub(r"\D", "", p)) < 10


def _tokenize_text(text: str) -> set[str]:
    text = _normalize_ar_digits(text or "")
    tokens = re.findall(r"[\u0600-\u06FFa-zA-Z0-9_]+", text.lower())
    return {t for t in tokens if len(t) >= 3}


def _select_relevant_knowledge(catalog_text: str, query_text: str, max_chars: int = 4000, max_chunks: int = 6) -> str:
    """Pick most relevant catalog chunks for current user message."""
    full = (catalog_text or "").strip()
    if not full:
        return ""
    query = (query_text or "").strip()
    if not query:
        return full[:max_chars]

    query_terms = _tokenize_text(query)
    chunks = [c.strip() for c in re.split(r"\n{2,}", full) if c and c.strip()]
    if not chunks:
        chunks = [line.strip() for line in full.splitlines() if line.strip()]
    if not chunks:
        return full[:max_chars]

    scored: list[tuple[int, str]] = []
    for chunk in chunks:
        terms = _tokenize_text(chunk)
        score = len(query_terms.intersection(terms))
        if score > 0:
            scored.append((score, chunk))

    # fallback: if no lexical match, keep beginning of catalog
    if not scored:
        return full[:max_chars]

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [chunk for _, chunk in scored[:max_chunks]]
    result = "\n\n".join(selected)
    if len(result) > max_chars:
        result = result[:max_chars]
    return result


_AR_STOP = frozenset(
    {
        "هل",
        "ما",
        "في",
        "من",
        "على",
        "عن",
        "هذا",
        "هذه",
        "ذلك",
        "الي",
        "الى",
        "إلى",
        "مع",
        "قد",
        "تم",
        "كل",
        "أي",
        "اي",
        "كم",
        "هل",
    }
)


def _query_blob_for_match(context: Dict[str, Any]) -> str:
    """نص البحث: رسالة المستخدم + ملخص المحادثة."""
    parts = [
        str(context.get("message_text") or ""),
        str(context.get("comment_text") or ""),
        str(context.get("conversation_history") or ""),
    ]
    return _normalize_ar_digits("\n".join(parts)).lower()


def _product_match_blob(p: Product) -> str:
    parts: list[str] = [
        p.name or "",
        p.sku or "",
        p.barcode or "",
        str(p.sale_price or ""),
        str(p.quantity or ""),
        str(p.description or ""),
    ]
    try:
        if (p.meta_json or "").strip():
            meta = json.loads((p.meta_json or "").strip())
            if isinstance(meta, dict):
                for k in ("brand", "category", "size", "color", "unit", "model"):
                    v = meta.get(k)
                    if v is not None and str(v).strip():
                        parts.append(str(v))
    except Exception:
        pass
    return _normalize_ar_digits(" ".join(parts)).lower()


def _score_product_match(p: Product, query_blob: str) -> int:
    if not query_blob.strip():
        return 0
    hay = _product_match_blob(p)
    score = 0
    # كلمات عربية/إنجليزية (2 أحرف فأكثر)
    for w in re.findall(r"[\u0600-\u06ffa-z0-9]{2,}", query_blob):
        if w in _AR_STOP and len(w) <= 3:
            continue
        if len(w) >= 2 and w in hay:
            score += 2
    # أرقام (مقاسات، أسعار)
    for n in re.findall(r"\d+", query_blob):
        if len(n) >= 1 and n in hay:
            score += 4
    return score


def _product_catalog_lines(p: Product) -> list[str]:
    extra = ""
    try:
        meta = json.loads((p.meta_json or "").strip()) if (p.meta_json or "").strip() else {}
        if isinstance(meta, dict) and meta:
            allowed = ["brand", "unit", "category", "shelf", "color", "size"]
            parts = []
            for k in allowed:
                v = meta.get(k)
                if v is not None and str(v).strip():
                    parts.append(f"{k}: {v}")
            if parts:
                extra = " | " + " | ".join(parts)
    except Exception:
        extra = ""

    lines = [
        (
            f"- المنتج: {p.name}"
            f" | SKU: {p.sku or '-'}"
            f" | Barcode: {p.barcode or '-'}"
            f" | سعر البيع: {p.sale_price}"
            f" | سعر الشراء: {p.buy_price}"
            f" | المخزون الحالي: {p.quantity}"
            f" | حد التنبيه: {p.low_stock_threshold}"
            f"{extra}"
        )
    ]
    if p.description:
        desc = str(p.description).strip()
        if desc:
            if len(desc) > 220:
                desc = desc[:220] + "..."
            lines.append(f"  الوصف: {desc}")
    return lines


def _product_image_candidates(p: Product) -> list[str]:
    """جمع مسارات/روابط صور المنتج (URL أو path محلي)."""
    items: list[str] = []

    main = str(p.image_url or "").strip()
    if main and not main.lower().startswith("data:"):
        items.append(main)

    try:
        meta = json.loads((p.meta_json or "").strip()) if (p.meta_json or "").strip() else {}
    except Exception:
        meta = {}

    if isinstance(meta, dict):
        for k in ("image", "image_url", "image_path", "photo", "photo_path", "thumbnail", "thumbnail_path"):
            v = meta.get(k)
            if v is None:
                continue
            s = str(v).strip()
            if s and not s.lower().startswith("data:"):
                items.append(s)
        for lk in ("images", "photos", "gallery"):
            arr = meta.get(lk)
            if isinstance(arr, list):
                for v in arr:
                    s = str(v or "").strip()
                    if s and not s.lower().startswith("data:"):
                        items.append(s)

    dedup: list[str] = []
    seen: set[str] = set()
    for s in items:
        if s in seen:
            continue
        seen.add(s)
        dedup.append(s)
    return dedup


def _build_inventory_catalog(limit: int = 300, include_inactive: bool = False) -> str:
    """
    Build catalog text from company inventory (Product table in tenant DB).
    """
    q = Product.query.order_by(Product.name.asc(), Product.id.asc())
    if not include_inactive:
        q = q.filter(Product.active == True)  # noqa: E712
    products = q.limit(max(1, min(int(limit or 300), 2000))).all()
    if not products:
        return ""

    lines: list[str] = ["كتالوج المنتجات من المخزون:"]
    for p in products:
        lines.extend(_product_catalog_lines(p))

    return "\n".join(lines)


def _build_matched_inventory_catalog(
    context: Dict[str, Any],
    data: Dict[str, Any],
) -> tuple[str, list[str]]:
    """
    يرجع (نص للـ AI، روابط صور للمنتجات المطابقة فقط).
    """
    pool_limit = max(50, min(int(data.get("inventory_pool") or data.get("inventory_limit") or 800), 5000))
    include_inactive = bool(data.get("include_inactive") or False)
    match_limit = max(1, min(int(data.get("match_limit") or 8), 30))
    mode = str(data.get("inventory_mode") or "match").strip().lower()

    q = Product.query.order_by(Product.name.asc(), Product.id.asc())
    if not include_inactive:
        q = q.filter(Product.active == True)  # noqa: E712
    products = q.limit(pool_limit).all()

    if mode == "full":
        text = _build_inventory_catalog(limit=min(pool_limit, 2000), include_inactive=include_inactive)
        imgs: list[str] = []
        for p in products[:5]:
            imgs.extend(_product_image_candidates(p)[:2])
        return text, list(dict.fromkeys(imgs))

    query_blob = _query_blob_for_match(context)
    scored: list[tuple[int, Product]] = []
    for p in products:
        s = _score_product_match(p, query_blob)
        scored.append((s, p))
    scored.sort(key=lambda x: (-x[0], x[1].name or ""))

    matched = [p for s, p in scored if s > 0][:match_limit]
    if not matched:
        hint = (
            "(لا يوجد في المخزون المعروض منتج يطابق كلمات البحث بوضوح. "
            "اسأل العميل عن النوع/المقاس/الميزانية أو اعرض الفئات المتوفرة باختصار دون اختراع أرقام.)"
        )
        return hint, []

    lines: list[str] = [
        "المنتجات المطابقة لسؤال العميل (استخدم فقط هذه البيانات للأسعار والمواصفات):",
    ]
    image_urls: list[str] = []
    for p in matched:
        lines.extend(_product_catalog_lines(p))
        image_urls.extend(_product_image_candidates(p)[:2])

    return "\n".join(lines), list(dict.fromkeys(image_urls))[:5]


def _truncate_history_tail(text: str, max_chars: int = 48000) -> str:
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    return "…" + s[-max_chars:]


def _load_conversation_history_from_inbox(context: Dict[str, Any]) -> str:
    """
    يبني سجل المحادثة من جدول telegram_inbox_messages (نفس البيانات المعروضة في الصندوق).
    يعمل عبر عدة عمال خادم ولا يضيع عند إعادة تشغيل العملية — على عكس deque في الذاكرة.
    """
    wf_id = context.get("workflow_id")
    chat_id = context.get("chat_id")
    if wf_id is None or not chat_id:
        return ""
    try:
        from models.telegram_inbox_message import TelegramInboxMessage

        try:
            cap = int(current_app.config.get("TELEGRAM_INBOX_HISTORY_MAX_ROWS", 250))
        except Exception:
            cap = 250
        cap = max(50, min(cap, 2000))

        rows = (
            TelegramInboxMessage.query.filter_by(
                workflow_id=int(wf_id),
                chat_id=str(chat_id)[:64],
            )
            .order_by(TelegramInboxMessage.id.desc())
            .limit(cap)
            .all()
        )
        rows.reverse()
        lines: list[str] = []
        for r in rows:
            role = (r.role or "").strip().lower()
            body = (r.body or "").strip()
            if not body:
                continue
            if role == "user":
                lines.append(f"المستخدم: {body}")
            elif role in ("bot", "operator"):
                lines.append(f"المساعد: {body}")
        return "\n".join(lines).strip()
    except Exception:
        current_app.logger.debug("telegram inbox history load failed", exc_info=True)
        return ""


def _load_conversation_history(context: Dict[str, Any]) -> str:
    """سجل المحادثة: أولاً من قاعدة البيانات (صندوق تيليجرام)، ثم من الذاكرة المحلية."""
    inbox_text = _load_conversation_history_from_inbox(context)
    if inbox_text.strip():
        return _truncate_history_tail(inbox_text, 48000)

    key = _memory_key(context)
    if not key:
        return ""
    with _CHAT_MEMORY_LOCK:
        history = list(_CHAT_MEMORY.get(key, deque()))
    if not history:
        return ""
    lines: list[str] = []
    for turn in history:
        user_text = (turn.get("user") or "").strip()
        bot_text = (turn.get("assistant") or "").strip()
        if user_text:
            lines.append(f"المستخدم: {user_text}")
        if bot_text:
            lines.append(f"المساعد: {bot_text}")
    return _truncate_history_tail("\n".join(lines).strip(), 48000)


def _append_conversation_turn(context: Dict[str, Any], assistant_reply: str) -> None:
    key = _memory_key(context)
    if not key:
        return
    user_text = str(context.get("message_text") or "").strip()
    bot_text = (assistant_reply or "").strip()
    if not user_text or not bot_text:
        return
    with _CHAT_MEMORY_LOCK:
        history = _CHAT_MEMORY.setdefault(key, deque(maxlen=_CHAT_MEMORY_MAX_TURNS))
        history.append({"user": user_text, "assistant": bot_text})


def run_conversation_context_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    يعيد تحميل سجل المحادثة من الذاكرة (بعد telegram_send يتضمن آخر دورة مستخدم/بوت)
    ويحدّث conversation_history للعقد التالية (مثل AI مهمة حجز ثم sql_save_order).
    """
    data = node.data or {}
    max_chars = max(500, min(int(data.get("max_chars") or 6000), 50000))
    full = _load_conversation_history(context)
    extra: list[str] = []
    if bool(data.get("include_current_message", True)):
        u = str(context.get("message_text") or "").strip()
        if u:
            tail = full or ""
            win = tail[-min(2000, len(tail)) :] if tail else ""
            if u not in win:
                extra.append(f"رسالة الزبون الحالية: {u}")
    if bool(data.get("include_last_reply", True)):
        r = str(
            context.get("telegram_message")
            or context.get("reply_text")
            or context.get("text")
            or ""
        ).strip()
        if r:
            extra.append(f"آخر رد أُرسل للزبون: {r}")
    if extra:
        full = (full + "\n\n" + "\n".join(extra)).strip() if full else "\n".join(extra)
    if len(full) > max_chars:
        full = full[-max_chars:]
    context["conversation_history"] = full
    context["conversation_for_booking"] = full
    preview = full[:500] + ("…" if len(full) > 500 else "")
    return {"conversation_snapshot": preview, "conversation_chars": len(full)}


def run_ai_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """تشغيل عقدة AI مرنة باستخدام إعدادات العقدة."""
    data = node.data or {}

    if context.get("keyword_matched") is False:
        topic = (data.get("topic") or context.get("topic") or "").strip()
        return {
            "text": "",
            "reply_text": "",
            "topic": topic,
            "skipped_keyword_filter": True,
        }
    if context.get("rate_limited"):
        topic = (data.get("topic") or context.get("topic") or "").strip()
        return {
            "text": "",
            "reply_text": "",
            "topic": topic,
            "skipped_rate_limit": True,
        }
    if context.get("already_replied"):
        topic = (data.get("topic") or context.get("topic") or "").strip()
        return {
            "text": "",
            "reply_text": "",
            "topic": topic,
            "skipped_duplicate": True,
        }

    task = data.get("task") or "generate_post"
    msg_in = str(context.get("message_text") or "").strip()
    if task in ("intent", "booking", "reply_comment") and context.get("chat_id") and not msg_in:
        topic = (data.get("topic") or context.get("topic") or "").strip()
        out: Dict[str, Any] = {
            "text": "",
            "reply_text": "",
            "topic": topic,
            "skipped_empty_message": True,
        }
        if task == "intent":
            out["user_intent"] = "unknown"
        return out

    if task in ("intent", "booking"):
        _infer_booking_fields_from_conversation(context)

    if task == "booking":
        smart_require_contact = bool(data.get("smart_require_contact", True))
        require_name = bool(data.get("require_name", smart_require_contact))
        require_phone = bool(data.get("require_phone", smart_require_contact))
        require_address = bool(data.get("require_address", smart_require_contact))

        if _is_booking_commit_message(msg_in):
            missing = _missing_booking_fields(
                context,
                require_name=require_name,
                require_phone=require_phone,
                require_address=require_address,
            )
            if not missing:
                product_label = str(context.get("product_name") or context.get("product") or "المنتج").strip()
                quick_reply = (
                    f"تم ✅ استلام بيانات الحجز لـ {product_label}. "
                    "جاري تثبيت الحجز الآن."
                )
                return {
                    "text": quick_reply,
                    "reply_text": quick_reply,
                    "topic": (data.get("topic") or context.get("topic") or "").strip(),
                    "booking_quick_path": True,
                }
            ask_one = missing[0]
            ask_reply = f"حتى أثبّت الحجز الآن، أحتاج {ask_one} فقط."
            return {
                "text": ask_reply,
                "reply_text": ask_reply,
                "topic": (data.get("topic") or context.get("topic") or "").strip(),
                "booking_pending_fields": missing,
            }

    # إعدادات المهمة
    topic = (data.get("topic") or context.get("topic") or "").strip()
    if not topic and context.get("message_text"):
        topic = (str(context.get("message_text") or ""))[:500]
    base_context = dict(context)
    base_context.setdefault("topic", topic)
    base_context.setdefault(
        "comment_text",
        context.get("comment_text") or context.get("message_text") or "",
    )
    base_context.setdefault("conversation_history", str(context.get("conversation_history") or ""))

    # قالب الـ prompt
    template = data.get("prompt") or ""
    if not template:
        if task == "reply_comment":
            template = "اكتب رداً لبقاً ومهنياً على هذا التعليق:\n\n{{comment_text}}"
        elif task == "write_caption":
            template = "اكتب كابشن تسويقي لمنشور عن {{topic}}"
        elif task == "generate_topic":
            template = "اقترح 5 أفكار لموضوعات منشورات حول {{topic}}"
        elif task == "booking":
            template = (
                "ساعد الزبون على إتمام الحجز اعتماداً على سجل المحادثة والكتالوج.\n"
                "رسالة الزبون الحالية:\n{{message_text}}\n\n"
                "اجمع البيانات من السياق قبل السؤال (الاسم، الهاتف، العنوان، المنتج/الخدمة، الكمية).\n"
                "إذا كانت البيانات مكتملة: اكتب تأكيداً قصيراً ثم أضف JSON فقط في آخر الرد بهذا الشكل:\n"
                '{"booking":{"name":"...","phone":"...","address":"...","product_name":"...","product_id":null,"quantity":1,"price":null}}\n'
                "إذا نقصت معلومة واحدة، اسأل عنها فقط بسؤال واحد موجز ولا تضف JSON."
            )
        elif task == "intent":
            if str(context.get("conversation_history") or "").strip():
                template = (
                    "سياق المحادثة (مهم للتصنيف — لا تتجاهل السياق):\n{{conversation_history}}\n\n"
                    "آخر رسالة من الزبون:\n{{message_text}}\n\n"
                    "صنّف النية: هل يتابع طلباً/حجزاً أم سؤالاً عاماً؟ أجب JSON فقط."
                )
            else:
                template = (
                    "صنّف رسالة المستخدم التالية. أجب JSON فقط بدون أي نص إضافي.\n\n"
                    "{{message_text}}"
                )
        elif context.get("message_text"):
            template = "رد باختصار ومهنية على رسالة المستخدم التالية:\n\n{{message_text}}"
        else:
            template = "أنشئ منشوراً تسويقياً جذاباً عن {{topic}}"

    prompt = _render_prompt(template, base_context)

    # إعدادات النموذج
    model = data.get("model") or current_app.config.get("OPENAI_MODEL", "gpt-4o-mini")
    temperature = float(data.get("temperature") or 0.7)
    max_tokens = int(data.get("max_tokens") or 500)

    # إعدادات المحتوى
    language = data.get("language") or "ar"
    tone = data.get("tone") or "marketing"
    target_audience = data.get("target_audience") or ""

    system_parts = [
        "أنت مساعد خبير في كتابة محتوى للسوشيال ميديا والرد على العملاء.",
        f"اللغة المطلوبة: {'العربية' if language == 'ar' else 'English'}.",
    ]
    if tone:
        system_parts.append(f"الأسلوب: {tone}.")
    if target_audience:
        system_parts.append(f"الجمهور المستهدف: {target_audience}.")

    # ردود تيليجرام / واتساب: احترافية، تماسك مع الذاكرة، بدون حشو
    if (
        task == "reply_comment"
        and context.get("message_text")
        and context.get("chat_id")
    ):
        system_parts.append(
            "أنت ممثل خدمة عملاء ومبيعات محترف في قناة رسائل فورية. "
            "استخدم عربية واضحة ولطيفة (فصحى مبسّطة أو عامية مهنية حسب سياق الزبون). "
            "إذا وُجد سجل محادثة أدناه فاعتمد عليه للتماسك: لا تتناقض مع ما سبق، ولا تكرّر ترحيباً طويلاً أو نفس المقدمة في كل رد. "
            "إذا عاد الزبون لمنتج أو طلب سبق ذكره، التزم بالاسم والسياق دون إعادة نسخ فقرات طويلة. "
            "كن موجزاً عند الاستفسار البسيط، وأكثر وضوحاً عند الشرح أو الطلب. تجنّب العبارات الآلية المكررة مثل الترحيب المبالغ فيه في كل رسالة."
        )

    if context.get("message_text") and str(context.get("knowledge") or "").strip():
        system_parts.append(
            "أنت مندوب مبيعات ودود: قدّم إجابة مقنعة تعتمد فقط على معلومات الكتالوج أدناه؛ "
            "اذكر السعر والمخزون إن وُجدت بالكتالوج، واشرح الفائدة باختصار، وادعُ بلطف لإتمام الطلب أو طلب التفاصيل. "
            "لا تخترع منتجات أو أسعار أو مواصفات غير مذكورة في الكتالوج. إذا لم تتوفر معلومة، قل ذلك صراحة. "
            "إذا عبّر الزبون عن نية الشراء أو الحجز أو إتمام الطلب (مثل: أريد أطلب، أكمل الطلب، احجز لي، اريد اطلب)، "
            "**لا تعِد نسخ وصف المنتج أو السعر كاملاً كما في الرسائل السابقة**. اكتب ردّاً قصيراً (جملة أو جملتان): "
            "أكد استلام رغبته، واطلب الاسم الكامل ورقم الهاتف والعنوان إن لم يذكرها، أو أكد الحجز باختصار إن وُجدت كل البيانات."
        )

    conversation_history = str(context.get("conversation_history") or "").strip()
    if conversation_history:
        if len(conversation_history) > 4200:
            conversation_history = conversation_history[-4200:]
        system_parts.append(
            "سجل المحادثة السابقة (نفس الزبون ونفس المحادثة؛ للتماسك والمرجعية فقط، والأولوية لرسالة الزبون الحالية في طلب المستخدم):\n"
            + conversation_history
        )

    if task == "reply_comment" and conversation_history and context.get("chat_id"):
        system_parts.append(
            "إذا سبق في السياق ذكر منتج أو سعر أو مقاس، والزبون أرسل الآن اسماً أو هاتفاً أو عنواناً فاعتبره إتماماً لطلب سبق، "
            "ولا تسأل من جديد «ما المنتج الذي تريد»؛ أكد الحجز أو اطلب نقصاً واحداً فقط إن وُجد."
        )
        system_parts.append(
            "إذا كانت رسالة الزبون قصيرة جداً (مثل رقم مقاس/كمية: 42 أو 2) فاعتبرها متابعة لأقرب منتج ذُكر في السياق، "
            "وقدّم جواباً مباشراً بدل إعادة فتح الحوار من البداية."
        )

    if task == "booking" and conversation_history:
        system_parts.append(
            "لمهمة الحجز: راجع سجل المحادثة أعلاه؛ الاسم أو الهاتف أو المنتج قد يكون قد ورد في رسالة سابقة وليس في آخر رسالة فقط."
        )
        system_parts.append(
            "لا تسأل «ما المنتج الذي تريد» إذا كان المنتج أو الخدمة أو السعر قد وُضح في سجل المحادثة؛ "
            "اطلب فقط ما ينقص (اسم، هاتف، عنوان، كمية) أو أكد الحجز باختصار."
        )
        system_parts.append(
            "إذا كتب الزبون عبارة إتمام مثل (احجز/أكمل/نفّذ) وكانت البيانات الأساسية متوفرة من السياق، "
            "اعطِ تأكيداً مختصراً وأرفق JSON الحجز مباشرة."
        )

    if task == "intent":
        system_parts = [
            "أنت مصنّف نوايا. أجب بكائن JSON فقط دون أي نص قبله أو بعده (لا تستخدم markdown).",
            'القيم: {"intent":"order"} أو {"intent":"question"} أو {"intent":"unknown"}.',
            "order = حجز أو شراء أو طلب خدمة أو موعد. question = استفسار عام. unknown = غير واضح.",
            f"اللغة: {'العربية' if language == 'ar' else 'English'}.",
        ]
        if conversation_history:
            if len(conversation_history) > 4200:
                conversation_history = conversation_history[-4200:]
            system_parts.append("سجل المحادثة (للتماسك):\n" + conversation_history)
            system_parts.append(
                "إذا سبق ذكر منتج أو سعر أو مقاس في السياق، والرسالة الحالية تحتوي اسمًا أو هاتفًا أو عنوانًا أو عبارة إتمام الطلب، فالنية order."
            )

    knowledge = context.get("knowledge")
    if task != "intent" and isinstance(knowledge, str) and knowledge.strip():
        # نضيف جزء مختصر من الكتالوج إلى الـ system prompt حتى لا يطول كثيراً
        trimmed = knowledge.strip()
        if len(trimmed) > 4000:
            trimmed = trimmed[:4000]
        system_parts.append(
            "الكتالوج / المعرفة المعتمدة (لا تستخدم معلومات خارجها للأسعار والمواصفات):\n" + trimmed
        )

    system_prompt = " ".join(system_parts)

    node_api_key = (data.get("api_key") or "").strip()
    client = get_client(node_api_key or None)
    max_retries = int(data.get("max_retries") or current_app.config.get("OPENAI_CHAT_MAX_RETRIES", 3) or 3)
    resp = _openai_chat_with_retry(
        client,
        max_attempts=max_retries,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    )
    text = (resp.choices[0].message.content or "").strip()

    # إن فشل النموذج بإخراج JSON للنية: إعادة واحدة بدرجة حرارة أقل (بدون حلقة لا نهائية)
    if task == "intent" and text and _parse_intent_value(text) == "unknown":
        low = max(0.0, min(float(temperature), 0.35))
        try:
            resp2 = _openai_chat_with_retry(
                client,
                max_attempts=max_retries,
                model=model,
                temperature=low,
                max_tokens=min(max_tokens, 120),
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                        + " أجب بسطر واحد فقط: JSON صالح مثل {\"intent\":\"question\"} دون أي حرف زائد.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            text2 = (resp2.choices[0].message.content or "").strip()
            if text2 and _parse_intent_value(text2) != "unknown":
                text = text2
        except Exception:
            current_app.logger.debug("intent retry parse skipped", exc_info=True)

    result: Dict[str, Any] = {
        "text": text,
        "topic": topic,
    }

    # تحديث السياق بناءً على نوع المهمة
    if task in {"generate_post", "write_caption"}:
        result["caption"] = text
    if task == "generate_topic" and text:
        result["generated_topics"] = text
    if task == "intent":
        intent = _parse_intent_value(text)
        if intent == "unknown":
            hint = _heuristic_user_intent(str(context.get("message_text") or ""))
            if hint:
                intent = hint
        intent = _refine_intent_with_context(
            str(context.get("message_text") or ""),
            str(context.get("conversation_history") or ""),
            intent,
        )
        result["user_intent"] = intent
        result["reply_text"] = ""
    elif task == "reply_comment":
        result["reply_text"] = text
    elif context.get("message_text") or task == "booking":
        if task == "booking":
            result["booking_parse_source"] = text
            display = _strip_booking_json_for_user_display(text)
            if not display.strip():
                display = text.strip()[:500] or "…"
            result["reply_text"] = display
        else:
            result["reply_text"] = text

    return result


def run_image_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """تشغيل عقدة Image باستخدام مزوّد Nano Banana أو OpenAI."""
    data = node.data or {}
    base_context = dict(context)

    template = data.get("prompt") or "Create a marketing image about {{topic}}"
    prompt = _render_prompt(template, base_context)

    style = data.get("style") or "photorealistic"
    size = data.get("size") or "1024x1024"
    provider = (data.get("provider") or "nanobanana").lower()

    image_url: str

    if provider == "openai":
        client = get_client()
        # نستخدم نموذج الصور الافتراضي ما لم يتم ضبطه في الإعدادات
        model = current_app.config.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
        # تحويل أسماء الـ style إلى نمط OpenAI (vivid/natural) بشكل مبسط
        style_map = {
          "minimal": "natural",
          "photorealistic": "natural",
          "cinematic": "vivid",
          "illustration": "vivid",
          "3d": "vivid",
        }
        oa_style = style_map.get(style, "vivid")

        resp = client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
            style=oa_style,
        )
        # مكتبة openai الجديدة ترجع data[0].url
        image_url = resp.data[0].url  # type: ignore[assignment]
    else:
        # Nano Banana – نمرر الـ prompt، ويمكن استخدام style/size لاحقاً إذا تم توسيع generate_image
        image_url = generate_image(prompt)

    result: Dict[str, Any] = {"image_url": image_url}
    context["image_url"] = image_url
    return result


def run_publisher_node(node: NodeDef, context: Dict[str, Any], execution: AgentExecution) -> Dict[str, Any]:
    """تشغيل عقدة Publisher باستخدام إعدادات المنصات والمحتوى."""
    data = node.data or {}

    # 1) تحديد المنصات
    platforms = data.get("platforms") or ["facebook"]
    if isinstance(platforms, str):
        platforms = [platforms]

    # 2) تحديد نوع المنشور (حالياً نستخدمه فقط للمستقبل)
    post_type = data.get("post_type") or "image_post"

    # 3) caption
    caption_source = data.get("caption_source") or "{{text}}"
    if caption_source == "custom":
        caption_template = data.get("caption_custom") or ""
    else:
        caption_template = caption_source
    caption = _render_prompt(caption_template, context).strip()

    # 4) image url
    image_source = data.get("image_source") or "{{image_url}}"
    if image_source == "custom_url":
        image_template = data.get("image_custom_url") or ""
    else:
        image_template = image_source
    image_url = _render_prompt(image_template, context).strip() or None

    publish_mode = data.get("publish_mode") or "publish_now"

    # 5) اختيار حسابات السوشيال حسب المنصات (واختيارياً قائمة صفحات محددة)
    tenant_slug = getattr(execution.workflow.agent, "tenant_slug", None)
    acc_q = SocialAccount.query
    if tenant_slug:
        acc_q = acc_q.filter_by(tenant_slug=tenant_slug)
    if platforms:
        acc_q = acc_q.filter(SocialAccount.platform.in_(platforms))
    accounts = acc_q.all()
    # إذا وُجدت قائمة account_ids أو page_ids في العقدة، ننشر فقط على هذه الصفحات (تجنب النشر على صفحات غير مرغوبة)
    allowed_ids = data.get("account_ids") or data.get("page_ids")
    if allowed_ids and isinstance(allowed_ids, (list, tuple)):
        allowed_set = {str(x).strip() for x in allowed_ids if x}
        if allowed_set:
            accounts = [a for a in accounts if str(a.account_id).strip() in allowed_set]
    if not accounts:
        raise RuntimeError("لا توجد حسابات سوشيال مطابقة للمنصات المحددة (أو القائمة المختارة). راجع إعدادات العقدة أو ربط الصفحات.")

    # 6) إنشاء SocialPost
    post_status = "draft"
    if publish_mode == "publish_now":
        post_status = "draft"  # سيتم تحديثه بواسطة publish_post_to_accounts / المنصات
    elif publish_mode == "schedule":
        post_status = "scheduled"

    post = SocialPost(
        tenant_slug=tenant_slug,
        user_id=execution.workflow.agent.user_id,
        topic=context.get("topic") or "",
        caption=caption or context.get("caption") or "",
        image_url=image_url,
        status=post_status,
    )
    db.session.add(post)
    db.session.commit()

    publish_result: Dict[str, str] = {}

    if publish_mode == "publish_now":
        # إعادة استخدام مدير النشر ليتكفّل بالتفاصيل والمنصات
        publish_post_to_accounts(post, accounts)
        for acc in accounts:
            publish_result[acc.platform] = "submitted"
    else:
        for acc in accounts:
            publish_result[acc.platform] = publish_mode

    result: Dict[str, Any] = {
        "publish_result": publish_result,
        "post_id": post.id,
        "caption": post.caption,
        "image_url": post.image_url,
    }

    context.update(result)
    return result


def run_caption_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """توليد كابشن اعتماداً على نص مصدر + إعدادات الأسلوب/اللغة."""
    data = node.data or {}

    source = data.get("source") or "{{text}}"
    if source == "custom":
        template = data.get("source_custom") or ""
    else:
        template = source

    base_text = _render_prompt(template, context).strip()

    style = data.get("style") or "marketing"
    language = data.get("language") or "arabic"
    max_length = int(data.get("max_length") or 200)

    # إذا ماكو نص أساس، نستخدم topic كبديل
    if not base_text:
        base_text = str(context.get("topic") or "")

    client = get_client()

    lang_desc = "العربية" if language == "arabic" else "English"
    style_desc = {
        "marketing": "تسويقي جذاب مع دعوة لاتخاذ إجراء",
        "short": "قصير ومباشر",
        "storytelling": "على شكل قصة قصيرة مشوّقة",
        "informative": "معلوماتي يركّز على الفوائد والمواصفات",
    }.get(style, "تسويقي جذاب")

    system_prompt = (
        f"أنت خبير كتابة كابشن لمنشورات السوشيال ميديا. اكتب الكابشن بلغة {lang_desc} "
        f"وبأسلوب {style_desc}. لا تتجاوز تقريباً {max_length} حرفاً."
    )

    user_prompt = f"النص/الفكرة الأساسية للكابشن:\n{base_text}\n"

    cap_retries = int(current_app.config.get("OPENAI_CHAT_MAX_RETRIES", 3) or 3)
    resp = _openai_chat_with_retry(
        client,
        max_attempts=cap_retries,
        model=current_app.config.get("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0.7,
        max_tokens=max_length * 3 // 2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    caption = (resp.choices[0].message.content or "").strip()

    result: Dict[str, Any] = {"caption": caption}
    context["caption"] = caption
    return result


def run_scheduler_node(node: NodeDef, context: Dict[str, Any], execution: AgentExecution) -> Dict[str, Any]:
    """تسجيل إعدادات الجدولة في الـ context (الجدولة الفعلية تتم عبر مجدول خارجي أو APScheduler لاحقاً)."""
    data = node.data or {}
    schedule_type = data.get("schedule_type") or "daily"
    time_str = data.get("time") or "20:00"
    timezone = data.get("timezone") or "Asia/Baghdad"

    result: Dict[str, Any] = {
        "scheduled": True,
        "schedule_type": schedule_type,
        "time": time_str,
        "timezone": timezone,
        "workflow_id": execution.workflow_id,
    }
    context.update(result)
    return result


def run_whatsapp_send_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """إرسال رسالة واتساب باستخدام بيانات العقدة والسياق."""
    data = node.data or {}
    phone_tmpl = str(data.get("phone") or data.get("to") or context.get("from_phone") or "")
    msg_tmpl = str(data.get("message") or data.get("template") or context.get("reply_text") or context.get("message_text") or "")

    phone = _render_template(phone_tmpl, context).strip()
    message = _render_template(msg_tmpl, context).strip()

    if phone and message:
        send_whatsapp_message(phone, message)

    result: Dict[str, Any] = {
        "whatsapp_phone": phone,
        "whatsapp_message": message,
    }
    context.update(result)
    return result


def run_telegram_send_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """إرسال رسالة تيليجرام باستخدام بيانات العقدة والسياق."""
    data = node.data or {}
    if context.get("keyword_matched") is False:
        return {
            "telegram_chat_id": "",
            "telegram_message": "",
            "telegram_photos_sent": 0,
            "skipped": "keyword_not_matched",
        }
    if context.get("rate_limited"):
        return {
            "telegram_chat_id": str(context.get("chat_id") or ""),
            "telegram_message": "",
            "telegram_photos_sent": 0,
            "skipped": "rate_limited",
        }
    if context.get("already_replied"):
        return {
            "telegram_chat_id": str(context.get("chat_id") or ""),
            "telegram_message": "",
            "telegram_photos_sent": 0,
            "skipped": "duplicate_update",
        }
    # عند استقبال رسالة عبر Webhook يكون chat_id في السياق = من كتب للبوت.
    # إذا وُضع رقم ثابت في العقدة (to / chat_id) كان يُرسل لذلك الرقم فقط فيبدو أن البوت «لا يرد» للزبون.
    incoming_chat = str(context.get("chat_id") or "").strip()
    use_fixed_recipient = bool(data.get("send_to_fixed_recipient", False))
    if incoming_chat and not use_fixed_recipient:
        chat_tmpl = incoming_chat
    else:
        chat_tmpl = str(data.get("chat_id") or data.get("to") or incoming_chat or context.get("chat_id") or "")

    # في تدفق المحادثة (وجود message_text) نعطي الأولوية لرد الـ AI
    # حتى لا يبقى نص تجريبي ثابت مثل "test/hello test".
    ai_reply = str(context.get("reply_text") or context.get("text") or "").strip()
    configured_msg = str(data.get("message") or data.get("template") or "").strip()
    has_vars = ("{{" in configured_msg and "}}" in configured_msg)
    if context.get("message_text") and ai_reply:
        msg_tmpl = configured_msg if has_vars else ai_reply
    else:
        msg_tmpl = str(configured_msg or ai_reply or context.get("message_text") or "")

    chat_id = _render_template(chat_tmpl, context).strip()
    message = _render_template(msg_tmpl, context).strip()
    # استخدام توكن البوت من عقدة Listener (السياق) أو من هذه العقدة أو الإعدادات
    bot_token = (data.get("bot_token") or context.get("telegram_bot_token") or "").strip() or None

    if not chat_id:
        current_app.logger.warning(
            "telegram_send: لا يوجد chat_id بعد العرض (incoming=%s send_to_fixed=%s)",
            incoming_chat[:32] if incoming_chat else "",
            use_fixed_recipient,
        )
    elif not message:
        current_app.logger.warning(
            "telegram_send: نص الرسالة فارغ — reply_text=%s text=%s",
            bool(str(context.get("reply_text") or "").strip()),
            bool(str(context.get("text") or "").strip()),
        )

    photos_sent = 0
    if chat_id and message:
        send_telegram_message(chat_id, message, bot_token=bot_token)
        context["_telegram_sent"] = True

    send_imgs = bool(data.get("send_product_images", True))
    max_photos = max(0, min(int(data.get("max_product_photos") or 5), 10))
    urls = context.get("telegram_product_image_urls") or []
    if (
        send_imgs
        and chat_id
        and isinstance(urls, list)
        and urls
        and max_photos > 0
    ):
        for photo_url in urls[:max_photos]:
            if send_telegram_photo(str(chat_id), str(photo_url), bot_token=bot_token):
                photos_sent += 1
                context["_telegram_sent"] = True

    result: Dict[str, Any] = {
        "telegram_chat_id": chat_id,
        "telegram_message": message,
        "telegram_photos_sent": photos_sent,
    }
    context.update(result)
    # صندوق المحادثات: سجّل أي إخراج للبوت (نص و/أو صور). سابقاً كان التسجيل يُتخطى إذا كان النص فارغاً مع وجود صور فقط.
    inbox_body = (message or "").strip()
    if not inbox_body and photos_sent > 0:
        inbox_body = f"[أُرسلت {photos_sent} صورة/صور من الكتالوج]"
    wf_id = context.get("workflow_id")
    if chat_id and inbox_body and wf_id is not None:
        from social_ai.telegram_inbox import record_telegram_inbox_message

        record_telegram_inbox_message(
            context.get("tenant_slug"),
            int(wf_id),
            str(chat_id),
            "bot",
            inbox_body[:12000],
        )
    return result


def _try_parse_booking_dict_from_text(text: str) -> Dict[str, Any] | None:
    """يستخرج كائناً JSON من رد الـ AI (كتلة ```json أو أول {...})."""
    if not text or not str(text).strip():
        return None
    t = str(text).strip()
    for block in re.findall(r"```(?:json)?\s*([\s\S]*?)```", t):
        try:
            j = json.loads(block.strip())
            if isinstance(j, dict):
                return j
        except Exception:
            continue
    m = re.search(r"\{[\s\S]*\}", t)
    if m:
        try:
            j = json.loads(m.group(0))
            if isinstance(j, dict):
                return j
        except Exception:
            return None
    return None


def _merge_booking_from_ai_into_context(context: Dict[str, Any]) -> None:
    """يملأ مفاتيح الحجز من JSON داخل reply_text/text إن وُجد."""
    if context.get("booking") and isinstance(context.get("booking"), dict):
        raw = context["booking"]
    else:
        blob = str(
            context.get("booking_parse_source")
            or context.get("reply_text")
            or context.get("text")
            or ""
        ).strip()
        raw = _try_parse_booking_dict_from_text(blob)
        if not raw:
            return
    inner = raw.get("booking") if isinstance(raw.get("booking"), dict) else raw
    if not isinstance(inner, dict):
        return
    keymap = {
        "customer_name": ("customer_name", "name"),
        "name": ("customer_name", "name"),
        "phone": ("phone",),
        "address": ("address",),
        "product_id": ("product_id",),
        "product_name": ("product_name", "product"),
        "product": ("product_name", "product"),
        "service": ("product_name", "product"),
        "sku": ("sku", "product_sku"),
        "barcode": ("barcode",),
        "quantity": ("quantity",),
        "price": ("price",),
        "channel": ("channel",),
    }
    for src, dests in keymap.items():
        if src not in inner or inner[src] in (None, ""):
            continue
        val = inner[src]
        if src == "product_id":
            try:
                val = int(val)
            except (TypeError, ValueError):
                continue
        if src == "quantity":
            sq = _sanitize_quantity_value(val)
            if sq is None:
                continue
            val = sq
        for d in dests:
            if context.get(d) in (None, ""):
                context[d] = val


def _resolve_product_for_order(context: Dict[str, Any]) -> Product | None:
    pid = context.get("product_id")
    if pid is not None and str(pid).strip() != "":
        try:
            p = Product.query.get(int(pid))
            if p and p.active:
                return p
        except (TypeError, ValueError):
            pass
    sku = str(context.get("sku") or context.get("product_sku") or "").strip()
    if sku:
        p = Product.query.filter(Product.active == True, Product.sku == sku).first()  # noqa: E712
        if p:
            return p
    bc = str(context.get("barcode") or "").strip()
    if bc:
        p = Product.query.filter(Product.active == True, Product.barcode == bc).first()  # noqa: E712
        if p:
            return p
    pname = str(context.get("product_name") or context.get("product") or "").strip()
    if pname:
        p = Product.query.filter(Product.active == True, Product.name == pname).first()  # noqa: E712
        if p:
            return p
        return (
            Product.query.filter(Product.active == True, Product.name.contains(pname))  # noqa: E712
            .order_by(Product.id.asc())
            .first()
        )
    return None


def run_sql_save_order_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    حفظ حجز / طلب في قاعدة شركة المستخدم: زبون + فاتورة (Invoice) + سطر (OrderItem).

    المدخلات من السياق أو من JSON في رد الـ AI (انظر عقدة AI — يُفضّل إخراج JSON في آخر الرسالة).

    عند تفعيل skip_if_incomplete (افتراضي True): إن نقص المنتج أو الهاتف المطلوب لا يُفشل الوورك فلو
    (لا تُرسل رسالة «تعذّر إكمال الطلب» للمستخدم) — يُسجّل تخطي الحجز فقط.
    """
    data = node.data or {}
    skip_incomplete = bool(data.get("skip_if_incomplete", True))

    def _skip(reason: str) -> Dict[str, Any]:
        out = {"booking_skipped": True, "booking_skip_reason": reason}
        context.update(out)
        return out

    _merge_booking_from_ai_into_context(context)
    _infer_booking_fields_from_conversation(context)
    _infer_phone_into_context(context)

    default_name = str(data.get("default_customer_name") or "عميل").strip() or "عميل"
    name = str(context.get("customer_name") or context.get("name") or default_name).strip()
    chat_id = str(context.get("chat_id") or "").strip()
    address = str(context.get("address") or "").strip()

    channel = str(context.get("channel") or data.get("channel_default") or "telegram").strip() or "telegram"
    run_if_rule = str(data.get("run_if") or "").strip()
    is_telegram_intent_flow = channel.lower() == "telegram" and run_if_rule == "user_intent:order"
    smart_require_contact = bool(data.get("smart_require_contact", is_telegram_intent_flow))
    require_name = bool(data.get("require_name", smart_require_contact))
    require_phone = bool(data.get("require_phone", smart_require_contact))
    require_address = bool(data.get("require_address", smart_require_contact))
    allow_placeholder_phone = bool(data.get("allow_placeholder_phone", False))

    phone = str(context.get("phone") or "").strip()
    if not phone and chat_id and allow_placeholder_phone:
        phone = f"tg-{chat_id}"[:20]
        context["phone"] = phone

    if require_name and (not name or name == default_name):
        msg = "يرجى إرسال الاسم الكامل لتأكيد الحجز."
        if skip_incomplete:
            return _skip(msg)
        raise RuntimeError(msg)

    if require_phone and (not phone or _is_placeholder_telegram_phone(phone)):
        msg = "يرجى إرسال رقم الهاتف بصيغة واضحة (مثال 07xxxxxxxx) لتأكيد الحجز."
        if skip_incomplete:
            return _skip(msg)
        raise RuntimeError(msg)

    if require_address and not address:
        msg = "يرجى إرسال العنوان لتأكيد الحجز."
        if skip_incomplete:
            return _skip(msg)
        raise RuntimeError(msg)

    try:
        qty = int(context.get("quantity") or 1)
    except (TypeError, ValueError):
        qty = 1
    if qty < 1:
        qty = 1
    qty = min(qty, 99_999)

    product = _resolve_product_for_order(context)
    if not product:
        msg = (
            "لم يُحدد منتج للحجز: مرّر product_id أو product_name في السياق، "
            "أو أضف JSON في رد الـ AI يحتوي product_id / product_name."
        )
        if skip_incomplete:
            return _skip(msg)
        raise RuntimeError(msg)

    invoice_status = str(data.get("invoice_status") or "حجز").strip() or "حجز"
    deduct_stock = bool(data.get("deduct_stock", True))

    price = context.get("price")
    try:
        unit_price = int(price) if price is not None and str(price).strip() != "" else int(product.sale_price or 0)
    except (TypeError, ValueError):
        unit_price = int(product.sale_price or 0)

    if deduct_stock:
        check = validate_sale_quantity(product.id, qty)
        if not check.get("valid"):
            msg = check.get("message") or "الكمية غير متوفرة في المخزون"
            if skip_incomplete:
                return _skip(msg)
            raise RuntimeError(msg)

    cust = Customer.query.filter_by(phone=phone).first()
    if cust:
        if name and name != default_name:
            cust.name = name
        if address:
            cust.address = address
    else:
        cust = Customer(
            name=name or default_name,
            phone=phone,
            address=address or None,
            tenant_id=getattr(product, "tenant_id", None),
        )
        db.session.add(cust)
        db.session.flush()

    note_parts = [
        f"حجز تلقائي — {channel}",
        f"chat_id={chat_id}" if chat_id else "",
        f"المنتج: {product.name}",
        f"الكمية: {qty}",
    ]
    if not deduct_stock:
        note_parts.append("بدون خصم من المخزون (حجز معلّق)")
    note = " | ".join(p for p in note_parts if p)

    inv = Invoice(
        customer_id=cust.id,
        customer_name=cust.name,
        employee_id=None,
        employee_name=None,
        total=0,
        status=invoice_status,
        payment_status="غير مسدد",
        note=note,
        created_at=datetime.utcnow(),
    )
    db.session.add(inv)
    db.session.flush()

    line_total = int(unit_price * qty)
    oi = OrderItem(
        invoice_id=inv.id,
        product_id=product.id,
        product_name=product.name,
        quantity=qty,
        price=unit_price,
        cost=int(product.buy_price or 0),
        total=line_total,
    )
    db.session.add(oi)

    if deduct_stock:
        product.quantity = int(product.quantity or 0) - qty

    inv.total = line_total
    db.session.commit()

    result = {
        "booking_invoice_id": inv.id,
        "booking_customer_id": cust.id,
        "booking_product_id": product.id,
        "booking_total": line_total,
        "booking_quantity": qty,
        "booking_status": invoice_status,
    }
    context.update(result)
    return result


def run_memory_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """تخزين قيمة معيّنة من السياق (أو من قالب) داخل الـ context تحت مفتاح معيّن."""
    data = node.data or {}
    key = str(data.get("key") or "").strip()
    template = str(data.get("value_template") or data.get("value") or "").strip()
    if not key:
        return {}
    value = _render_template(template or f"{{{{{key}}}}}", context).strip()
    context[key] = value
    return {key: value}


def run_knowledge_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """تحديث كتالوج / قاعدة المعرفة الخاصة بالوكيل داخل الـ context."""
    data = node.data or {}
    source = str(data.get("source") or "manual").strip().lower()
    if source == "inventory":
        new_value, img_urls = _build_matched_inventory_catalog(context, data)
        context["telegram_product_image_urls"] = img_urls
    else:
        catalog = str(data.get("catalog") or "").strip()
        context["telegram_product_image_urls"] = []
        new_value = catalog
    mode = data.get("mode") or "replace"
    rendered = _render_template(new_value, context).strip()

    if not rendered:
        return {}

    if mode == "append" and isinstance(context.get("knowledge"), str):
        merged = (context.get("knowledge") or "") + "\n" + rendered
    else:
        merged = rendered

    query_text = str(context.get("message_text") or context.get("comment_text") or "").strip()
    if source == "inventory" and str(data.get("inventory_mode") or "match").strip().lower() != "full":
        context["knowledge_full"] = merged
        context["knowledge"] = merged[:4000]
    else:
        relevant = _select_relevant_knowledge(merged, query_text, max_chars=4000, max_chunks=6)
        context["knowledge_full"] = merged
        context["knowledge"] = relevant or merged[:4000]
    return {
        "knowledge": context["knowledge"],
        "knowledge_full": context["knowledge_full"],
        "telegram_product_image_urls": context.get("telegram_product_image_urls") or [],
    }

def run_comment_listener_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    جلب تعليق حقيقي من المنصات المدعومة.

    - لفيسبوك: يمر على كل الصفحات المتصلة وكل المنشورات المعروفة (autoposter_posts) ويجلب التعليقات.
    - لإنستغرام/تيك توك: يعتمد على المعرف الممرَّر في سياق الوورك فلو أو إعدادات العقدة (media_id / video_id).

    يرجع أول تعليق جديد (لم يتم الرد عليه سابقاً) ليعالج في هذا التشغيل، وتُعالج باقي التعليقات في تشغيلات لاحقة.
    """
    data = node.data or {}
    platforms = data.get("platforms") or ["facebook"]
    if isinstance(platforms, str):
        platforms = [platforms]
    keywords = data.get("keywords") or []
    mode = data.get("mode") or "keywords_only"

    tenant_slug = context.get("tenant_slug")

    def _matches_keywords(text: str) -> bool:
        if not keywords or mode == "all_comments":
            return True
        lower = (text or "").lower()
        for kw in keywords:
            if isinstance(kw, str) and kw.strip().lower() in lower:
                return True
        return False

    # 1) فيسبوك: معطّل بعد إزالة نظام النشر (Autoposter)
    if "facebook" in platforms:
        pass  # كان يعتمد على AutoposterFacebookPage و AutoposterPost

    # 2) إنستغرام: يعتمد على media_id الممرّر
    if "instagram" in platforms:
        media_id = (data.get("media_id") or context.get("media_id") or "").strip()
        if media_id:
            comments = ig_fetch_comments(media_id=media_id, limit=50)
            for c in comments:
                comment_id = str(c.get("id") or "")
                text = c.get("text") or ""
                username = c.get("username")
                timestamp = c.get("timestamp")
                if not comment_id or not text:
                    continue
                if is_comment_already_replied(tenant_slug, "instagram", comment_id):
                    continue
                if not _matches_keywords(text):
                    continue
                result = {
                    "platform": "instagram",
                    "comment_id": comment_id,
                    "comment_text": text,
                    "username": username,
                    "timestamp": timestamp,
                }
                context.update(result)
                return result

    # 3) تيك توك: يعتمد على video_id الممرّر
    if "tiktok" in platforms:
        video_id = (data.get("video_id") or context.get("video_id") or "").strip()
        if video_id:
            comments = tiktok_fetch_comments(video_id=video_id, limit=50)
            for c in comments:
                comment_id = str(c.get("comment_id") or c.get("id") or "")
                text = c.get("text") or c.get("comment_text") or ""
                username = (c.get("user") or {}).get("display_name") if isinstance(c.get("user"), dict) else c.get("user_name")
                timestamp = c.get("create_time") or c.get("timestamp")
                if not comment_id or not text:
                    continue
                if is_comment_already_replied(tenant_slug, "tiktok", comment_id):
                    continue
                if not _matches_keywords(text):
                    continue
                result = {
                    "platform": "tiktok",
                    "comment_id": comment_id,
                    "comment_text": text,
                    "username": username,
                    "timestamp": timestamp,
                }
                context.update(result)
                return result

    # إذا لم يتم العثور على أي تعليق مناسب، لا نغيّر السياق لكن نرجع حالة فارغة
    return {"platform": None, "comment_id": None, "comment_text": "", "username": None}


def run_auto_reply_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """توليد رد على التعليق (قالب أو AI) وحفظه في الـ context (الإرسال الفعلي عبر واجهات المنصات لاحقاً)."""
    if context.get("keyword_matched") is False:
        return {"reply_text": "", "reply_status": "skipped_no_keyword"}
    data = node.data or {}
    mode = data.get("mode") or "template"
    template = data.get("template") or "شكراً لتعليقك!"
    comment_text = context.get("comment_text") or ""
    tone = data.get("tone") or "friendly"
    language = data.get("language") or "ar"

    if mode == "ai_generated":
        reply_text = generate_comment_reply(
            comment_text,
            context.get("caption"),
            tone=tone,
            language=language,
        )
    else:
        reply_text = _render_prompt(template, context).strip() or template

    result: Dict[str, Any] = {
        "reply_text": reply_text,
        "reply_status": "sent",
    }
    context.update(result)
    return result


def run_keyword_filter_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """فلتر التعليقات حسب كلمات مفتاحية: إذا وُجدت كلمة في النص نمرّر للعقدة التالية وإلا نهمل."""
    data = node.data or {}
    keywords_raw = data.get("keywords") or []
    keywords = [k.strip().lower() for k in (keywords_raw if isinstance(keywords_raw, list) else []) if k]
    text_blob = (
        context.get("comment_text")
        or context.get("message_text")
        or context.get("text")
        or ""
    )
    comment_text = str(text_blob).lower()
    matched = any(kw in comment_text for kw in keywords) if keywords else True
    result: Dict[str, Any] = {"keyword_matched": matched}
    context["keyword_matched"] = matched
    return result


def run_duplicate_protection_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """التحقق من أن التعليق لم يُرد عليه مسبقاً (حماية من التكرار). لتيليجرام: يعتمد telegram_update_id."""
    data = node.data or {}
    tg_uid = str(context.get("telegram_update_id") or "").strip()
    use_tg = bool(data.get("use_telegram_update_id", True)) and tg_uid
    if use_tg:
        platform = "telegram"
        comment_id = tg_uid
    else:
        platform = (context.get("platform") or "facebook").lower()
        comment_id = str(context.get("comment_id") or "")
    tenant_slug = context.get("tenant_slug")
    already = is_comment_already_replied(tenant_slug, platform, comment_id) if comment_id else False
    result: Dict[str, Any] = {"already_replied": already}
    context["already_replied"] = already
    return result


# تخزين بسيط لمحدّد المعدل (في الإنتاج يُفضّل Redis أو جدول)
_rate_limit_last_ts: Dict[str, float] = {}
_rate_limit_count: Dict[str, List[float]] = {}


def run_rate_limiter_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """تأخير بين الردود وحد أقصى للردود في الدقيقة. يمكن تقييد كل محادثة (chat_id) على حدة."""
    data = node.data or {}
    delay_sec = float(data.get("delay_between_replies") or 5)
    max_per_minute = int(data.get("max_replies_per_minute") or 20)
    wf = str(context.get("workflow_id") or "default")
    chat = str(context.get("chat_id") or "").strip()
    per_chat = data.get("per_chat")
    if per_chat is None:
        per_chat = True
    if chat and bool(per_chat):
        key = f"{wf}:{chat}"
    else:
        key = wf
    now = time.time()
    if key in _rate_limit_last_ts and (now - _rate_limit_last_ts[key]) < delay_sec:
        context["rate_limited"] = True
        return {"rate_limited": True}
    times = _rate_limit_count.setdefault(key, [])
    times[:] = [t for t in times if now - t < 60]
    if len(times) >= max_per_minute:
        context["rate_limited"] = True
        return {"rate_limited": True}
    times.append(now)
    _rate_limit_last_ts[key] = now
    context["rate_limited"] = False
    return {"rate_limited": False}


def run_publish_reply_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """نشر الرد على التعليق إلى فيسبوك / إنستغرام / تيك توك."""
    if context.get("keyword_matched") is False:
        return {"published": False, "reason": "keyword_not_matched"}
    if context.get("already_replied") or context.get("rate_limited"):
        return {"published": False, "reason": "skipped"}
    reply_text = context.get("reply_text") or context.get("ai_reply") or ""
    if not reply_text:
        return {"published": False, "reason": "no_reply"}
    platform = (context.get("platform") or "facebook").lower()
    comment_id = str(context.get("comment_id") or "")
    if not comment_id:
        return {"published": False, "reason": "no_comment_id"}
    ok = False
    if platform == "facebook":
        ok = fb_reply_comment(comment_id, reply_text)
    elif platform == "instagram":
        ok = ig_reply_comment(comment_id, reply_text)
    elif platform == "tiktok":
        ok = tiktok_reply_comment(comment_id, reply_text)
    result: Dict[str, Any] = {"published": ok, "platform": platform, "comment_id": comment_id}
    context.update(result)
    return result


def run_logging_node(node: NodeDef, context: Dict[str, Any], execution: AgentExecution) -> Dict[str, Any]:
    """تسجيل الحدث في جدول comment_logs."""
    tg_uid = str(context.get("telegram_update_id") or "").strip()
    platform = (context.get("platform") or ("telegram" if tg_uid else "facebook")).lower()
    ext_id = str(context.get("comment_id") or tg_uid or "")
    if platform == "telegram" and ext_id.strip():
        existing = CommentLog.query.filter_by(platform="telegram", comment_id=ext_id[:128]).first()
        if existing:
            return {"logged": True, "log_id": existing.id, "dedup": True}
    log_row = CommentLog(
        tenant_slug=context.get("tenant_slug"),
        platform=platform,
        comment_id=ext_id[:128],
        username=context.get("username") or (str(context.get("chat_id") or "")[:150] if tg_uid else None),
        comment_text=context.get("comment_text") or context.get("message_text") or context.get("text") or "",
        ai_reply=context.get("reply_text") or context.get("telegram_message") or context.get("ai_reply"),
        execution_id=execution.id,
    )
    db.session.add(log_row)
    db.session.commit()
    return {"logged": True, "log_id": log_row.id}


def _record_telegram_update_processed(
    context: Dict[str, Any],
    execution_id: int | None,
) -> None:
    """
    يمنع معالجة نفس تحديث تيليجرام مرتين (إعادة إرسال Webhook من Telegram).
    يُسجّل صفاً في comment_logs عند نجاح إرسال رد للبوت.
    """
    uid = str(context.get("telegram_update_id") or "").strip()
    if not uid or not context.get("_telegram_sent"):
        return
    try:
        exists = CommentLog.query.filter_by(platform="telegram", comment_id=uid[:128]).first()
        if exists:
            return
        row = CommentLog(
            tenant_slug=context.get("tenant_slug"),
            platform="telegram",
            comment_id=uid[:128],
            username=(str(context.get("chat_id") or "")[:150] or None),
            comment_text=(context.get("message_text") or "")[:2000] or "-",
            ai_reply=(context.get("telegram_message") or context.get("reply_text") or "")[:2000],
            execution_id=execution_id,
        )
        db.session.add(row)
        db.session.commit()
    except Exception:
        current_app.logger.debug("telegram update_id log skipped", exc_info=True)
        try:
            db.session.rollback()
        except Exception:
            pass


def execute_workflow(execution: AgentExecution, initial_context: Dict[str, Any] | None = None) -> None:
    """تنفيذ بسيط للـWorkflow بدعم العقد الأساسية."""
    workflow = execution.workflow
    nodes = _build_graph(workflow)
    context: Dict[str, Any] = dict(initial_context or {})
    context.setdefault("workflow_id", workflow.id)
    context.setdefault("tenant_slug", getattr(workflow.agent, "tenant_slug", None))
    if context.get("chat_id"):
        context["conversation_history"] = _load_conversation_history(context)
        if str(context.get("conversation_history") or "").strip():
            context["has_conversation_memory"] = True

    def log(node: NodeDef, status: str, input_obj: Any = None, output_obj: Any = None, error: str | None = None):
        log_row = AgentExecutionLog(
            execution_id=execution.id,
            node_id=node.id,
            node_type=node.type,
            status=status,
            input_snapshot=input_obj,
            output_snapshot=output_obj,
            error_message=error,
        )
        db.session.add(log_row)
        db.session.commit()

    try:
        for node in nodes:
            node_input = dict(context)
            try:
                if not _should_run_node(node, context):
                    log(
                        node,
                        "skipped",
                        node_input,
                        {"reason": "run_if", "run_if": (node.data or {}).get("run_if")},
                    )
                    continue
                if node.type == "start":
                    context["started_at"] = datetime.now(timezone.utc).isoformat()
                    if (node.data or {}).get("topic"):
                        context["topic"] = (node.data or {}).get("topic", "").strip()
                    log(node, "success", node_input, {"started_at": context.get("started_at"), "topic": context.get("topic")})
                elif node.type == "ai":
                    ai_output = run_ai_node(node, context)
                    # دمج المخرجات مع الـ context
                    context.update(ai_output)
                    log(node, "success", node_input, ai_output)
                elif node.type == "image":
                    img_output = run_image_node(node, context)
                    log(node, "success", node_input, img_output)
                elif node.type == "caption":
                    cap_output = run_caption_node(node, context)
                    log(node, "success", node_input, cap_output)
                elif node.type == "publisher":
                    pub_output = run_publisher_node(node, context, execution)
                    log(node, "success", node_input, pub_output)
                elif node.type == "scheduler":
                    sched_output = run_scheduler_node(node, context, execution)
                    log(node, "success", node_input, sched_output)
                elif node.type == "comment-listener":
                    listener_output = run_comment_listener_node(node, context)
                    log(node, "success", node_input, listener_output)
                elif node.type == "auto-reply":
                    reply_output = run_auto_reply_node(node, context)
                    log(node, "success", node_input, reply_output)
                elif node.type == "keyword-filter":
                    kw_output = run_keyword_filter_node(node, context)
                    log(node, "success", node_input, kw_output)
                elif node.type == "duplicate-protection":
                    dup_output = run_duplicate_protection_node(node, context)
                    log(node, "success", node_input, dup_output)
                elif node.type == "rate-limiter":
                    rl_output = run_rate_limiter_node(node, context)
                    log(node, "success", node_input, rl_output)
                elif node.type == "publish-reply":
                    pub_reply_output = run_publish_reply_node(node, context)
                    log(node, "success", node_input, pub_reply_output)
                elif node.type == "logging":
                    log_output = run_logging_node(node, context, execution)
                    log(node, "success", node_input, log_output)
                elif node.type == "whatsapp_send":
                    wa_output = run_whatsapp_send_node(node, context)
                    log(node, "success", node_input, wa_output)
                elif node.type == "telegram_send":
                    tg_output = run_telegram_send_node(node, context)
                    _append_conversation_turn(context, str(tg_output.get("telegram_message") or ""))
                    log(node, "success", node_input, tg_output)
                elif node.type == "conversation_context":
                    conv_out = run_conversation_context_node(node, context)
                    context.update(conv_out)
                    log(node, "success", node_input, conv_out)
                elif node.type in ("telegram_listener", "whatsapp_listener"):
                    # عقدة استقبال: البيانات (message_text, chat_id) من الـ webhook أو السياق الأولي؛ توكن البوت من بيانات العقدة لاستخدامه في الإرسال
                    if node.type == "telegram_listener" and (node.data or {}).get("bot_token"):
                        context["telegram_bot_token"] = (node.data or {}).get("bot_token", "").strip()
                    log(node, "success", node_input, {"message_text": context.get("message_text"), "chat_id": context.get("chat_id")})
                elif node.type == "memory_store":
                    mem_output = run_memory_node(node, context)
                    log(node, "success", node_input, mem_output)
                elif node.type == "knowledge_base":
                    kb_output = run_knowledge_node(node, context)
                    log(node, "success", node_input, kb_output)
                elif node.type == "end":
                    # حفظ لقطة السياق النهائية في اللوج
                    log(node, "success", node_input, dict(context))
                elif node.type == "sql_save_order":
                    sql_out = run_sql_save_order_node(node, context)
                    context.update(sql_out)
                    log(node, "success", node_input, sql_out)
                else:
                    # عقد غير معروفة – نتجاوزها لكن نسجّل في اللوج
                    log(node, "failed", node_input, None, f"نوع عقدة غير معروف: {node.type}")
            except Exception as e:  # pragma: no cover
                current_app.logger.exception("AI workflow node failed")
                log(node, "failed", node_input, None, str(e))
                execution.status = "failed"
                execution.error_message = str(e)
                db.session.commit()
                return

        execution.status = "success"
        db.session.commit()

        _record_telegram_update_processed(context, execution.id)

        # رد احتياطي لتيليجرام: إذا وُجد رد من الـ AI ولم يُرسل عبر telegram_send
        if not context.get("_telegram_sent"):
            if context.get("rate_limited") or context.get("already_replied"):
                return
            cid = context.get("chat_id")
            tok = (context.get("telegram_bot_token") or "").strip() or None
            reply = (context.get("reply_text") or context.get("text") or "").strip()
            if cid and tok and reply:
                send_telegram_message(str(cid), reply[:4096], bot_token=tok)
                context["_telegram_auto_reply"] = True
                context["telegram_message"] = reply
                _append_conversation_turn(context, reply)
                if context.get("workflow_id") is not None:
                    from social_ai.telegram_inbox import record_telegram_inbox_message

                    record_telegram_inbox_message(
                        context.get("tenant_slug"),
                        int(context["workflow_id"]),
                        str(cid),
                        "bot",
                        reply[:4096],
                    )
    except Exception as e:  # pragma: no cover
        execution.status = "failed"
        execution.error_message = str(e)
        db.session.commit()

