# telegram_bot/ready_agent.py — إنشاء وكيل تيليجرام جاهز (Agent + Workflow)
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from extensions import db
from models.ai_agent import Agent, AgentWorkflow

logger = logging.getLogger(__name__)

# اسم الوكيل والـ workflow الافتراضي
DEFAULT_AGENT_NAME = "بوت تيليجرام"
DEFAULT_WORKFLOW_NAME = "رد تلقائي تيليجرام"

# رسم الـ workflow: استقبال تيليجرام → AI يولد الرد → إرسال إلى تيليجرام
DEFAULT_GRAPH: Dict[str, Any] = {
    "nodes": [
        {
            "id": "tg-listener",
            "type": "telegram_listener",
            "data": {},
        },
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
            "data": {
                "chat_id": "{{chat_id}}",
                "message": "{{reply_text}}",
            },
        },
    ],
    "edges": [],
}


def ensure_telegram_agent(tenant_slug: Optional[str] = None) -> Tuple[Agent, AgentWorkflow]:
    """
    إنشاء وكيل تيليجرام جاهز إن لم يكن موجوداً.

    يرجع (agent, workflow). إذا وُجد وكيل بنفس الاسم يُستخدم مع أول workflow له،
    وإلا يُنشأ وكيل جديد وworkflow واحد.
    """
    agent = Agent.query.filter_by(name=DEFAULT_AGENT_NAME).first()
    if agent:
        wf = AgentWorkflow.query.filter_by(agent_id=agent.id).first()
        if wf:
            logger.info("Telegram ready agent already exists: agent_id=%s workflow_id=%s", agent.id, wf.id)
            return agent, wf
        wf = AgentWorkflow(
            agent_id=agent.id,
            name=DEFAULT_WORKFLOW_NAME,
            description="استقبال رسائل تيليجرام والرد تلقائياً بالذكاء الاصطناعي",
            is_active=True,
            graph_json=DEFAULT_GRAPH,
        )
        db.session.add(wf)
        db.session.commit()
        logger.info("Created default Telegram workflow: workflow_id=%s", wf.id)
        return agent, wf

    agent = Agent(
        tenant_slug=tenant_slug,
        name=DEFAULT_AGENT_NAME,
        description="وكيل تيليجرام للرد التلقائي على الرسائل باستخدام الذكاء الاصطناعي",
    )
    db.session.add(agent)
    db.session.flush()

    wf = AgentWorkflow(
        agent_id=agent.id,
        name=DEFAULT_WORKFLOW_NAME,
        description="استقبال رسائل تيليجرام والرد تلقائياً بالذكاء الاصطناعي",
        is_active=True,
        graph_json=DEFAULT_GRAPH,
    )
    db.session.add(wf)
    db.session.commit()
    logger.info("Created Telegram ready agent: agent_id=%s workflow_id=%s", agent.id, wf.id)
    return agent, wf
