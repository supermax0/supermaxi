# telegram_bot/agent_templates.py — قوالب جاهزة لإنشاء وكلاء (Agent + Workflow)
"""
قالب وكيل: تعريفات جاهزة لإنشاء Agent مع Workflow من رسم ومعنى ثابت.
استخدم create_agent_from_template(template_id, ...) لإنشاء وكيل جديد من قالب.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from extensions import db
from models.ai_agent import Agent, AgentWorkflow

logger = logging.getLogger(__name__)

# تعريف كل قالب: id, اسم الوكيل، وصف، اسم الـ workflow، الرسم
AGENT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "telegram": {
        "id": "telegram",
        "agent_name": "بوت تيليجرام",
        "agent_description": "وكيل تيليجرام للرد التلقائي على الرسائل باستخدام الذكاء الاصطناعي",
        "workflow_name": "رد تلقائي تيليجرام",
        "workflow_description": "استقبال رسائل تيليجرام والرد تلقائياً بالذكاء الاصطناعي",
        "graph": {
            "nodes": [
                {"id": "tg-listener", "type": "telegram_listener", "data": {"enabled": False}},
                {
                    "id": "ai-reply",
                    "type": "ai",
                    "data": {
                        "task": "reply_comment",
                        "prompt": "رد على رسالة العميل التالية بشكل مفيد ومهني. بالعربية.\n\n{{message_text}}",
                        "language": "ar",
                    },
                },
                {
                    "id": "tg-send",
                    "type": "telegram_send",
                    "data": {"chat_id": "{{chat_id}}", "message": "{{reply_text}}"},
                },
            ],
            "edges": [
                {"id": "e-tg-ai", "source": "tg-listener", "target": "ai-reply", "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-ai-send", "source": "ai-reply", "target": "tg-send", "sourceHandle": "out", "targetHandle": "in"},
            ],
        },
    },
    "whatsapp": {
        "id": "whatsapp",
        "agent_name": "بوت واتساب",
        "agent_description": "وكيل واتساب للرد التلقائي على الرسائل باستخدام الذكاء الاصطناعي",
        "workflow_name": "رد تلقائي واتساب",
        "workflow_description": "استقبال رسائل واتساب والرد تلقائياً بالذكاء الاصطناعي",
        "graph": {
            "nodes": [
                {"id": "wa-listener", "type": "whatsapp_listener", "data": {}},
                {
                    "id": "ai-reply",
                    "type": "ai",
                    "data": {
                        "task": "reply_comment",
                        "prompt": "رد على رسالة العميل التالية بشكل مفيد ومهني. بالعربية.\n\n{{message_text}}",
                        "language": "ar",
                    },
                },
                {
                    "id": "wa-send",
                    "type": "whatsapp_send",
                    "data": {"phone": "{{phone}}", "message": "{{reply_text}}"},
                },
            ],
            "edges": [],
        },
    },
    "comment_reply": {
        "id": "comment_reply",
        "agent_name": "ردّاد التعليقات",
        "agent_description": "وكيل للرد التلقائي على تعليقات فيسبوك باستخدام الذكاء الاصطناعي",
        "workflow_name": "رد على التعليقات",
        "workflow_description": "مراقبة التعليقات والرد عليها تلقائياً",
        "graph": {
            "nodes": [
                {"id": "listener", "type": "comment-listener", "data": {}},
                {"id": "filter", "type": "keyword-filter", "data": {}},
                {
                    "id": "ai",
                    "type": "ai",
                    "data": {
                        "task": "reply_comment",
                        "prompt": "اكتب رداً لبقاً ومهنياً على هذا التعليق:\n\n{{comment_text}}",
                        "language": "ar",
                    },
                },
                {"id": "publish", "type": "publish-reply", "data": {}},
            ],
            "edges": [],
        },
    },
    # تدفق كامل: استفسار من الكتالوج → رد واحد للزبون → تحديث السياق → استخراج حجز → SQL (بدون رد ثانٍ)
    "telegram_shop": {
        "id": "telegram_shop",
        "agent_name": "متجر تيليجرام — مبيعات وحجز",
        "agent_description": "رد على الاستفسارات من كتالوج المخزون، حجز تلقائي في قاعدة البيانات، رسالة واحدة للزبون لكل تحديث",
        "workflow_name": "تيليجرام: مبيعات + حجز SQL",
        "workflow_description": "Listener → مخزون → AI مبيعات → إرسال → سياق محادثة → AI حجز → حفظ الطلب → نهاية",
        "graph": {
            "nodes": [
                {
                    "id": "tg-listener",
                    "type": "telegram_listener",
                    "position": {"x": 320, "y": 0},
                    "data": {
                        "label": "Telegram Listener",
                        "bot_token": "",
                        "enabled": False,
                        "subtitle": "ضع Bot Token ثم احفظ وفعّل Webhook أو استخدم «تحقق من تيليجرام»",
                    },
                },
                {
                    "id": "kb-inventory",
                    "type": "knowledge_base",
                    "position": {"x": 320, "y": 110},
                    "data": {
                        "label": "المخزون / الكتالوج",
                        "source": "inventory",
                        "inventory_mode": "match",
                        "match_limit": 12,
                        "subtitle": "من جدول المنتجات حسب رسالة الزبون",
                    },
                },
                {
                    "id": "ai-sales",
                    "type": "ai",
                    "position": {"x": 320, "y": 240},
                    "data": {
                        "label": "AI — رد للزبون",
                        "task": "reply_comment",
                        "language": "ar",
                        "tone": "ودود ومهني",
                        "temperature": 0.45,
                        "max_tokens": 900,
                        "prompt": (
                            "أنت مساعد مبيعات بالعربية. اعتمد فقط على الكتالوج في تعليمات النظام للأسعار والمخزون والمواصفات.\n"
                            "- أجب عن استفسار الزبون بوضوح وباختصار.\n"
                            "- لا تخترع منتجات أو أسعاراً غير موجودة في الكتالوج.\n"
                            "- إذا سأل عن التوفر أو السعر فقط، استخدم بيانات الكتالوج.\n"
                            "- **إذا قال إنه يريد الطلب أو الحجز أو إتمام الشراء** (مثل: أريد أطلب، أكمل الطلب، اريد اكمل الطلب، احجز، نفّذ الطلب): "
                            "لا تكرر وصف المنتج والسعر والمواصفات من الرسالة السابقة. "
                            "اكتب رداً قصيراً جداً: رحّب بطلبه واطلب **الاسم الكامل ورقم الهاتف والعنوان** إن لم يذكرها في رسالته الحالية. "
                            "إذا ذكرها كلها، أكد الحجز بجملة واحدة فقط.\n"
                            "- ردّك للزبون: جملة أو جملتان كحد أقصى في حالة نية الشراء؛ فقرة واحدة في حالة سؤال عن المنتج فقط.\n\n"
                            "رسالة الزبون:\n{{message_text}}"
                        ),
                    },
                },
                {
                    "id": "tg-send",
                    "type": "telegram_send",
                    "position": {"x": 320, "y": 400},
                    "data": {
                        "label": "Telegram Send",
                        "chat_id": "{{chat_id}}",
                        "template": "{{reply_text}}",
                        "send_product_images": True,
                        "max_product_photos": 5,
                        "subtitle": "رد واحد للزبون",
                    },
                },
                {
                    "id": "conv-ctx",
                    "type": "conversation_context",
                    "position": {"x": 320, "y": 530},
                    "data": {
                        "label": "محادثة (سياق)",
                        "max_chars": 6000,
                        "include_current_message": True,
                        "include_last_reply": True,
                    },
                },
                {
                    "id": "ai-booking",
                    "type": "ai",
                    "position": {"x": 320, "y": 660},
                    "data": {
                        "label": "AI — استخراج الحجز",
                        "task": "booking",
                        "language": "ar",
                        "temperature": 0.25,
                        "max_tokens": 700,
                        "prompt": (
                            "من سياق المحادثة في تعليمات النظام ومن رسالة الزبون أدناه، حدّد هل يوجد طلب حجز واضح "
                            "(اسم، هاتف، منتج أو معرف، كمية إن وُجدت).\n"
                            "إذا اكتملت البيانات: اكتب جملة تأكيد قصيرة ثم في آخر الرسالة كتلة JSON فقط بهذا الشكل:\n"
                            '{"booking":{"name":"...","phone":"...","address":"...","product_name":"...","product_id":null,"quantity":1,"price":null}}\n'
                            "phone يجب أن يكون أرقاماً حقيقية (مثل 07xxxxxxxx) إن وُجدت في النص.\n"
                            "product_name يطابق اسم المنتج من الكتالوج قدر الإمكان.\n"
                            "إذا نقصت معلومات أساسية للحجز، اسأل سؤالاً واحداً قصيراً ولا تضف JSON.\n\n"
                            "آخر رسالة من الزبون:\n{{message_text}}"
                        ),
                    },
                },
                {
                    "id": "sql-order",
                    "type": "sql_save_order",
                    "position": {"x": 320, "y": 820},
                    "data": {
                        "label": "SQL حفظ الطلب",
                        "channel_default": "telegram",
                        "invoice_status": "حجز",
                        "deduct_stock": True,
                        "skip_if_incomplete": True,
                        "require_phone": False,
                        "subtitle": "يتخطى إن لم يكتمل الحجز — لا يفشل الوورك فلو",
                    },
                },
                {
                    "id": "end",
                    "type": "end",
                    "position": {"x": 320, "y": 940},
                    "data": {"label": "End", "subtitle": "انتهاء التشغيل"},
                },
            ],
            # أسلاك كاملة حتى لا يختلط ترتيب التنفيذ عند إضافة المستخدم أسهمًا جزئية فقط
            "edges": [
                {"id": "e-tg-kb", "source": "tg-listener", "target": "kb-inventory", "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-kb-ai", "source": "kb-inventory", "target": "ai-sales", "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-ai-send", "source": "ai-sales", "target": "tg-send", "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-send-ctx", "source": "tg-send", "target": "conv-ctx", "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-ctx-book", "source": "conv-ctx", "target": "ai-booking", "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-book-sql", "source": "ai-booking", "target": "sql-order", "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-sql-end", "source": "sql-order", "target": "end", "sourceHandle": "out", "targetHandle": "in"},
            ],
        },
    },
}


def list_templates() -> List[Dict[str, Any]]:
    """إرجاع قائمة القوالب الجاهزة (بدون الرسم الكامل إن أردت تقليل الحجم)."""
    return [
        {
            "id": t["id"],
            "agent_name": t["agent_name"],
            "agent_description": t["agent_description"],
            "workflow_name": t["workflow_name"],
            "workflow_description": t["workflow_description"],
        }
        for t in AGENT_TEMPLATES.values()
    ]


def get_template(template_id: str) -> Optional[Dict[str, Any]]:
    """إرجاع تعريف القالب بالكامل إن وُجد."""
    return AGENT_TEMPLATES.get(template_id)


def create_agent_from_template(
    template_id: str,
    *,
    tenant_slug: Optional[str] = None,
    user_id: Optional[int] = None,
    agent_name: Optional[str] = None,
    workflow_name: Optional[str] = None,
) -> Tuple[Agent, AgentWorkflow]:
    """
    إنشاء وكيل جديد + workflow من قالب معرّف بـ template_id.

    يمكن تخصيص اسم الوكيل واسم الـ workflow؛ وإلا يُستخدم الاسم الموجود في القالب.
    """
    tpl = get_template(template_id)
    if not tpl:
        raise ValueError(f"قالب غير موجود: {template_id}")

    name = (agent_name or tpl["agent_name"] or "").strip() or tpl["agent_name"]
    wf_name = (workflow_name or tpl["workflow_name"] or "").strip() or tpl["workflow_name"]
    graph = tpl.get("graph") or {"nodes": [], "edges": []}

    agent = Agent(
        tenant_slug=tenant_slug,
        user_id=user_id,
        name=name,
        description=tpl.get("agent_description"),
    )
    db.session.add(agent)
    db.session.flush()

    workflow = AgentWorkflow(
        agent_id=agent.id,
        name=wf_name,
        description=tpl.get("workflow_description"),
        is_active=True,
        graph_json=graph,
    )
    db.session.add(workflow)
    db.session.commit()

    logger.info(
        "Created agent from template: template_id=%s agent_id=%s workflow_id=%s",
        template_id,
        agent.id,
        workflow.id,
    )
    return agent, workflow
