from __future__ import annotations

from collections import deque
import json
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
_CHAT_MEMORY_MAX_TURNS = 8


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
            u = (p.image_url or "").strip()
            if u.startswith(("http://", "https://")):
                imgs.append(u)
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
        u = (p.image_url or "").strip()
        if u.startswith(("http://", "https://")):
            image_urls.append(u)

    return "\n".join(lines), list(dict.fromkeys(image_urls))[:5]


def _load_conversation_history(context: Dict[str, Any]) -> str:
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
    return "\n".join(lines).strip()


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

    # إعدادات المهمة
    task = data.get("task") or "generate_post"
    topic = (data.get("topic") or context.get("topic") or "").strip()
    if not topic and context.get("message_text"):
        topic = (str(context.get("message_text") or ""))[:500]
    base_context = dict(context)
    base_context.setdefault("topic", topic)
    base_context.setdefault(
        "comment_text",
        context.get("comment_text") or context.get("message_text") or "",
    )

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
                "ساعد الزبون على إتمام حجز المنتج اعتماداً على معرفة الكتالوج إن وُجدت.\n"
                "رسالة الزبون:\n{{message_text}}\n\n"
                "إذا توفّر (الاسم، رقم الهاتف، المنتج أو معرفه، الكمية) بشكل واضح، "
                "أكمل الرد بجملة تأكيد ثم أضف في آخر الرسالة كتلة JSON فقط بهذا الشكل:\n"
                '{"booking":{"name":"...","phone":"...","product_name":"...","product_id":null,"quantity":1,"price":null}}\n'
                "استخدم product_id إذا عرفته من السياق، وإلا product_name. إذا نقصت معلومات، اسأل عنها ولا تضف JSON."
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

    if context.get("message_text") and str(context.get("knowledge") or "").strip():
        system_parts.append(
            "أنت مندوب مبيعات ودود: قدّم إجابة مقنعة تعتمد فقط على معلومات الكتالوج أدناه؛ "
            "اذكر السعر والمخزون إن وُجدت بالكتالوج، واشرح الفائدة باختصار، وادعُ بلطف لإتمام الطلب أو طلب التفاصيل. "
            "لا تخترع منتجات أو أسعار أو مواصفات غير مذكورة في الكتالوج. إذا لم تتوفر معلومة، قل ذلك صراحة."
        )

    conversation_history = str(context.get("conversation_history") or "").strip()
    if conversation_history:
        if len(conversation_history) > 2500:
            conversation_history = conversation_history[-2500:]
        system_parts.append(
            "هذا ملخص آخر الرسائل في نفس المحادثة. استخدمه لفهم المنتج المقصود ولا تتناقض معه:\n"
            + conversation_history
        )

    knowledge = context.get("knowledge")
    if isinstance(knowledge, str) and knowledge.strip():
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
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
    )
    text = (resp.choices[0].message.content or "").strip()

    result: Dict[str, Any] = {
        "text": text,
        "topic": topic,
    }

    # تحديث السياق بناءً على نوع المهمة
    if task in {"generate_post", "write_caption"}:
        result["caption"] = text
    if task == "generate_topic" and text:
        result["generated_topics"] = text
    if task == "reply_comment":
        result["reply_text"] = text
    elif context.get("message_text") or task == "booking":
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

    resp = client.chat.completions.create(
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
    chat_tmpl = str(data.get("chat_id") or data.get("to") or context.get("chat_id") or "")

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
        raw = _try_parse_booking_dict_from_text(
            str(context.get("reply_text") or context.get("text") or "")
        )
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
            try:
                val = int(val)
            except (TypeError, ValueError):
                continue
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
    """
    data = node.data or {}
    _merge_booking_from_ai_into_context(context)
    _infer_phone_into_context(context)

    default_name = str(data.get("default_customer_name") or "عميل").strip() or "عميل"
    name = str(context.get("customer_name") or context.get("name") or default_name).strip()
    chat_id = str(context.get("chat_id") or "").strip()
    phone = str(context.get("phone") or "").strip()
    if not phone and chat_id:
        phone = f"tg-{chat_id}"[:20]
        context["phone"] = phone

    require_phone = bool(data.get("require_phone", False))
    if require_phone and _is_placeholder_telegram_phone(phone):
        raise RuntimeError(
            "يرجى إرسال رقم الهاتف بصيغة واضحة (مثال 07xxxxxxxx) لتأكيد الحجز."
        )

    address = str(context.get("address") or "").strip()

    qty = int(context.get("quantity") or 1)
    if qty < 1:
        qty = 1

    product = _resolve_product_for_order(context)
    if not product:
        raise RuntimeError(
            "لم يُحدد منتج للحجز: مرّر product_id أو product_name في السياق، أو أضف JSON في رد الـ AI يحتوي product_id / product_name."
        )

    channel = str(context.get("channel") or data.get("channel_default") or "telegram").strip() or "telegram"
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
            raise RuntimeError(check.get("message") or "الكمية غير متوفرة في المخزون")

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
    comment_text = (context.get("comment_text") or context.get("text") or "").lower()
    matched = any(kw in comment_text for kw in keywords) if keywords else True
    result: Dict[str, Any] = {"keyword_matched": matched}
    context["keyword_matched"] = matched
    return result


def run_duplicate_protection_node(node: NodeDef, context: Dict[str, Any]) -> Dict[str, Any]:
    """التحقق من أن التعليق لم يُرد عليه مسبقاً (حماية من التكرار)."""
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
    """تأخير بين الردود وحد أقصى للردود في الدقيقة."""
    data = node.data or {}
    delay_sec = float(data.get("delay_between_replies") or 5)
    max_per_minute = int(data.get("max_replies_per_minute") or 20)
    key = str(context.get("workflow_id") or "default")
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
    log_row = CommentLog(
        tenant_slug=context.get("tenant_slug"),
        platform=context.get("platform") or "facebook",
        comment_id=str(context.get("comment_id") or ""),
        username=context.get("username"),
        comment_text=context.get("comment_text") or context.get("text") or "",
        ai_reply=context.get("reply_text") or context.get("ai_reply"),
        execution_id=execution.id,
    )
    db.session.add(log_row)
    db.session.commit()
    return {"logged": True, "log_id": log_row.id}


def execute_workflow(execution: AgentExecution, initial_context: Dict[str, Any] | None = None) -> None:
    """تنفيذ بسيط للـWorkflow بدعم العقد الأساسية."""
    workflow = execution.workflow
    nodes = _build_graph(workflow)
    context: Dict[str, Any] = dict(initial_context or {})
    context.setdefault("workflow_id", workflow.id)
    context.setdefault("tenant_slug", getattr(workflow.agent, "tenant_slug", None))
    if context.get("chat_id"):
        context["conversation_history"] = _load_conversation_history(context)

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

        # رد احتياطي لتيليجرام: إذا وُجد رد من الـ AI ولم يُرسل عبر telegram_send
        if not context.get("_telegram_sent"):
            cid = context.get("chat_id")
            tok = (context.get("telegram_bot_token") or "").strip() or None
            reply = (context.get("reply_text") or context.get("text") or "").strip()
            if cid and tok and reply:
                send_telegram_message(str(cid), reply[:4096], bot_token=tok)
                context["_telegram_auto_reply"] = True
                context["telegram_message"] = reply
                _append_conversation_turn(context, reply)
    except Exception as e:  # pragma: no cover
        execution.status = "failed"
        execution.error_message = str(e)
        db.session.commit()

