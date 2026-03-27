from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

from flask import current_app

from extensions import db
from models.ai_agent import AgentExecution, AgentExecutionLog, AgentWorkflow
from models.comment_log import CommentLog, is_comment_already_replied
from models.social_account import SocialAccount
from models.social_post import SocialPost
from social_ai.ai_engine import generate_caption, generate_comment_reply, get_client
from social_ai.image_generator import generate_image
from social_ai.messaging import send_telegram_message, send_whatsapp_message
from social_ai.publish_manager import publish_post_to_accounts
from services.facebook_service import fetch_comments as fb_fetch_comments, reply_comment as fb_reply_comment
from services.instagram_service import fetch_comments as ig_fetch_comments, reply_comment as ig_reply_comment
from services.tiktok_service import fetch_comments as tiktok_fetch_comments, reply_comment as tiktok_reply_comment


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

    knowledge = context.get("knowledge")
    if isinstance(knowledge, str) and knowledge.strip():
        # نضيف جزء مختصر من الكتالوج إلى الـ system prompt حتى لا يطول كثيراً
        trimmed = knowledge.strip()
        if len(trimmed) > 4000:
            trimmed = trimmed[:4000]
        system_parts.append("استخدم معلومات الكتالوج التالية عند الإجابة عن الأسئلة أو كتابة المحتوى:\n" + trimmed)

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
    elif context.get("message_text"):
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

    if chat_id and message:
        send_telegram_message(chat_id, message, bot_token=bot_token)

    result: Dict[str, Any] = {
        "telegram_chat_id": chat_id,
        "telegram_message": message,
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
    catalog = str(data.get("catalog") or "").strip()
    mode = data.get("mode") or "replace"
    rendered = _render_template(catalog, context).strip()

    if not rendered:
        return {}

    if mode == "append" and isinstance(context.get("knowledge"), str):
        new_value = (context.get("knowledge") or "") + "\n" + rendered
    else:
        new_value = rendered

    context["knowledge"] = new_value
    return {"knowledge": new_value}

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
                    log(node, "success", node_input, tg_output)
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
                    # حفظ الطلب في DB يُنفَّذ بالكامل في Node backend؛ هنا نمرر السياق فقط
                    log(node, "success", node_input, {"note": "SQL حفظ الطلب يُنفَّذ عند التشغيل عبر Node backend"})
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
    except Exception as e:  # pragma: no cover
        execution.status = "failed"
        execution.error_message = str(e)
        db.session.commit()

