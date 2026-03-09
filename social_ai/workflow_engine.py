from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from flask import current_app

from extensions import db
from models.ai_agent import AgentExecution, AgentExecutionLog, AgentWorkflow
from social_ai.ai_engine import generate_caption
from social_ai.image_generator import generate_image
from social_ai.publish_manager import publish_post_to_accounts
from models.social_account import SocialAccount
from models.social_post import SocialPost


@dataclass
class NodeDef:
    id: str
    type: str
    data: Dict[str, Any]


def _build_graph(workflow: AgentWorkflow) -> List[NodeDef]:
    graph = workflow.graph_json or {}
    nodes_data = graph.get("nodes") or []
    nodes: List[NodeDef] = []
    for n in nodes_data:
        nodes.append(NodeDef(id=str(n.get("id")), type=n.get("type") or "", data=n.get("data") or {}))
    return nodes


def execute_workflow(execution: AgentExecution) -> None:
    """تنفيذ بسيط للـWorkflow بدعم العقد الأساسية."""
    workflow = execution.workflow
    nodes = _build_graph(workflow)
    context: Dict[str, Any] = {}

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
                    # يمكن تمرير قيم ابتدائية من data لاحقاً
                    log(node, "success", node_input, context)
                elif node.type == "ai":
                    topic = node.data.get("topic") or node_input.get("topic") or ""
                    caption = generate_caption(topic or "منشور تسويقي")
                    context["caption"] = caption
                    log(node, "success", node_input, {"caption": caption})
                elif node.type == "image":
                    prompt = node.data.get("prompt") or node_input.get("image_prompt") or node_input.get("caption") or ""
                    image_url = generate_image(prompt or "social media marketing image")
                    context["image_url"] = image_url
                    log(node, "success", node_input, {"image_url": image_url})
                elif node.type == "caption":
                    # حالياً نعيد استخدام caption الموجود، يمكن توسيعها للهاشتاغات
                    caption = context.get("caption") or node_input.get("caption") or ""
                    context["caption"] = caption
                    log(node, "success", node_input, {"caption": caption})
                elif node.type == "publisher":
                    tenant_slug = getattr(execution.workflow.agent, "tenant_slug", None)
                    acc_q = SocialAccount.query
                    if tenant_slug:
                        acc_q = acc_q.filter_by(tenant_slug=tenant_slug)
                    accounts = acc_q.all()
                    if not accounts:
                        raise RuntimeError("لا توجد حسابات سوشيال للنشر.")
                    post = SocialPost(
                        tenant_slug=tenant_slug,
                        user_id=execution.workflow.agent.user_id,
                        topic=context.get("topic") or "",
                        caption=context.get("caption") or "",
                        image_url=context.get("image_url"),
                        status="draft",
                    )
                    db.session.add(post)
                    db.session.commit()
                    publish_post_to_accounts(post, accounts)
                    log(node, "success", node_input, {"published_post_id": post.id})
                elif node.type == "end":
                    log(node, "success", node_input, context)
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

