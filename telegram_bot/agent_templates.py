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
                        "tone": "مهني ومهذب",
                        "temperature": 0.4,
                        "max_tokens": 700,
                        "prompt": (
                            "ردّ على رسالة العميل التالية بأسلوب خدمة عملاء محترف: وضوح، لباقة، دون إطالة.\n"
                            "إذا وُجد سجل محادثة في تعليمات النظام فالتزم بالتماسق مع ما سبق.\n\n"
                            "{{message_text}}"
                        ),
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
                        "tone": "مهني ودود وواثق دون مبالغة",
                        "temperature": 0.38,
                        "max_tokens": 1000,
                        "prompt": (
                            "أنت مستشار مبيعات لمتجر إلكتروني عبر تيليجرام. اعتمد حصرياً على الكتالوج في تعليمات النظام للأسعار والمخزون والمواصفات.\n"
                            "قواعد الجودة:\n"
                            "- ردّ بلهجة مهنية ولطيفة؛ مباشر دون فضفاضة.\n"
                            "- إذا وُجد سجل محادثة في تعليمات النظام، التزم بالتماسك (نفس المنتج/الطلب دون تناقض).\n"
                            "- لا تخترع منتجات أو أسعاراً أو توفراً غير وارد في الكتالوج.\n"
                            "- للاستفسار عن منتج أو سعر أو توفر: اذكر الفائدة أو الميزة بجملة قصيرة إن ساعد الكتالوج، ثم ادعُ بلطف للخطوة التالية.\n"
                            "- إذا عبّر عن نية الشراء أو الحجز (أطلب، أكمل، احجز، نفّذ الطلب، إلخ): لا تكرر وصف المنتج كاملاً إن سبق ذكره. "
                            "اكتب رداً مختصراً: تأكيد لطيف + طلب **الاسم الكامل ورقم الهاتف والعنوان** إن نقصت. إذا اكتملت البيانات في رسالته، أكد بجملة واحدة.\n"
                            "- تجنّب الترحيب الطويل أو «شكراً لتواصلك» في كل رد؛ اجعل الافتتاح مناسباً لعمق المحادثة.\n\n"
                            "آخر رسالة من الزبون (الأولوية للرد عليها):\n{{message_text}}"
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
                        "max_chars": 8000,
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
                        "temperature": 0.22,
                        "max_tokens": 750,
                        "prompt": (
                            "استخرج من **سجل المحادثة** في تعليمات النظام (إن وُجد) ومن آخر رسالة للزبون أدناه ما إذا كان هناك طلب حجز واضح "
                            "(اسم، هاتف، عنوان إن لزم، منتج أو معرف، كمية).\n"
                            "إذا اكتملت البيانات من المحادثة أو من الرسالة الحالية: جملة تأكيد مهنية قصيرة، ثم في آخر الرسالة كتلة JSON فقط:\n"
                            '{"booking":{"name":"...","phone":"...","address":"...","product_name":"...","product_id":null,"quantity":1,"price":null}}\n'
                            "phone: أرقام حقيقية (مثل 07xxxxxxxx) كما وردت في النص.\n"
                            "product_name: يطابق الكتالوج قدر الإمكان.\n"
                            "إذا نقصت معلومة حاسمة للحجز، اكتب سؤالاً واحداً مهنياً ولا تضف JSON.\n\n"
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
