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
                {"id": "tg-listener", "type": "telegram_listener", "data": {}},
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
            "edges": [],
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
