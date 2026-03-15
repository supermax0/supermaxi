from __future__ import annotations

import threading
from typing import Any, Dict

from flask import Blueprint, current_app, g, jsonify, request, session
from sqlalchemy import or_

from extensions import db
from models.ai_agent import Agent, AgentExecution, AgentWorkflow
from social_ai.workflow_engine import execute_workflow


workflow_api = Blueprint("workflow_api", __name__, url_prefix="/autoposter/api")


def _tenant_slug() -> str | None:
    tenant = getattr(g, "tenant", None)
    if isinstance(tenant, str):
        return tenant
    return getattr(tenant, "slug", None)


def _require_auth():
    if not session.get("user_id"):
        return jsonify({"success": False, "error": "not_authenticated"}), 401
    return None


def _base_agent_query():
    tenant_slug = _tenant_slug()
    user_id = session.get("user_id")

    q = Agent.query
    if tenant_slug:
        q = q.filter(Agent.tenant_slug == tenant_slug)
    if user_id:
        q = q.filter(or_(Agent.user_id == user_id, Agent.user_id.is_(None)))
    return q


def _base_workflow_query():
    tenant_slug = _tenant_slug()
    user_id = session.get("user_id")

    q = AgentWorkflow.query.join(Agent, Agent.id == AgentWorkflow.agent_id)
    if tenant_slug:
        q = q.filter(Agent.tenant_slug == tenant_slug)
    if user_id:
        q = q.filter(or_(Agent.user_id == user_id, Agent.user_id.is_(None)))
    return q


def _normalize_graph(graph: Any) -> Dict[str, Any]:
    if not isinstance(graph, dict):
        return {"nodes": [], "edges": []}
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    return {
        "nodes": nodes if isinstance(nodes, list) else [],
        "edges": edges if isinstance(edges, list) else [],
    }


def _run_workflow_in_background(app_obj, execution_id: int) -> None:
    """Run workflow in separate thread to avoid request timeouts."""
    with app_obj.app_context():
        execution = AgentExecution.query.get(execution_id)
        if not execution:
            return
        try:
            execute_workflow(execution)
        except Exception as exc:  # pragma: no cover
            current_app.logger.exception("Workflow background run failed: %s", exc)
            execution.status = "failed"
            execution.error_message = str(exc)
            db.session.commit()


@workflow_api.route("/agents", methods=["GET"])
def list_agents():
    auth = _require_auth()
    if auth:
        return auth

    agents = _base_agent_query().order_by(Agent.updated_at.desc(), Agent.id.desc()).all()
    return jsonify({"success": True, "agents": [a.to_dict() for a in agents]})


@workflow_api.route("/agents", methods=["POST"])
def create_agent():
    auth = _require_auth()
    if auth:
        return auth

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "Agent افتراضي").strip()
    if not name:
        return jsonify({"success": False, "error": "name_required"}), 400
    if len(name) > 150:
        return jsonify({"success": False, "error": "name_too_long"}), 400

    agent = Agent(
        tenant_slug=_tenant_slug(),
        user_id=session.get("user_id"),
        name=name,
        description=(data.get("description") or "").strip() or None,
        default_model=(data.get("default_model") or "").strip() or None,
        instructions=(data.get("instructions") or "").strip() or None,
    )
    db.session.add(agent)
    db.session.commit()
    return jsonify({"success": True, "agent": agent.to_dict()}), 201


@workflow_api.route("/workflows", methods=["GET"])
def list_workflows():
    auth = _require_auth()
    if auth:
        return auth

    workflow_id_raw = (request.args.get("workflow_id") or "").strip()
    q = _base_workflow_query()

    if workflow_id_raw:
        try:
            workflow_id = int(workflow_id_raw)
        except ValueError:
            return jsonify({"success": False, "error": "invalid_workflow_id"}), 400
        workflow = q.filter(AgentWorkflow.id == workflow_id).first()
        if not workflow:
            return jsonify({"success": False, "error": "workflow_not_found"}), 404
        return jsonify({"success": True, "workflow": workflow.to_dict()})

    workflows = q.order_by(AgentWorkflow.updated_at.desc(), AgentWorkflow.id.desc()).all()
    return jsonify({"success": True, "workflows": [w.to_dict() for w in workflows]})


@workflow_api.route("/workflows", methods=["POST"])
def create_workflow():
    auth = _require_auth()
    if auth:
        return auth

    data = request.get_json(silent=True) or {}
    try:
        agent_id = int(data.get("agent_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "agent_id_required"}), 400

    agent = _base_agent_query().filter(Agent.id == agent_id).first()
    if not agent:
        return jsonify({"success": False, "error": "agent_not_found"}), 404

    name = (data.get("name") or "").strip() or "وورك فلو بدون اسم"
    if len(name) > 150:
        return jsonify({"success": False, "error": "name_too_long"}), 400

    workflow = AgentWorkflow(
        agent_id=agent.id,
        name=name,
        description=(data.get("description") or "").strip() or None,
        is_active=bool(data.get("is_active", True)),
        graph_json=_normalize_graph(data.get("graph")),
    )
    db.session.add(workflow)
    db.session.commit()
    return jsonify({"success": True, "workflow": workflow.to_dict()}), 201


@workflow_api.route("/workflows/<int:workflow_id>", methods=["PUT"])
def update_workflow(workflow_id: int):
    auth = _require_auth()
    if auth:
        return auth

    workflow = _base_workflow_query().filter(AgentWorkflow.id == workflow_id).first()
    if not workflow:
        return jsonify({"success": False, "error": "workflow_not_found"}), 404

    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    if name:
        if len(name) > 150:
            return jsonify({"success": False, "error": "name_too_long"}), 400
        workflow.name = name

    if "description" in data:
        workflow.description = (data.get("description") or "").strip() or None
    if "is_active" in data:
        workflow.is_active = bool(data.get("is_active"))
    if "graph" in data:
        workflow.graph_json = _normalize_graph(data.get("graph"))

    if "agent_id" in data:
        try:
            new_agent_id = int(data.get("agent_id"))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "invalid_agent_id"}), 400
        new_agent = _base_agent_query().filter(Agent.id == new_agent_id).first()
        if not new_agent:
            return jsonify({"success": False, "error": "agent_not_found"}), 404
        workflow.agent_id = new_agent.id

    db.session.commit()
    return jsonify({"success": True, "workflow": workflow.to_dict()})


@workflow_api.route("/workflows/<int:workflow_id>/run", methods=["POST"])
def run_workflow(workflow_id: int):
    auth = _require_auth()
    if auth:
        return auth

    workflow = _base_workflow_query().filter(AgentWorkflow.id == workflow_id).first()
    if not workflow:
        return jsonify({"success": False, "error": "workflow_not_found"}), 404

    execution = AgentExecution(
        workflow_id=workflow.id,
        status="running",
    )
    db.session.add(execution)
    db.session.commit()

    app_obj = current_app._get_current_object()
    threading.Thread(
        target=_run_workflow_in_background,
        args=(app_obj, execution.id),
        daemon=True,
    ).start()

    return jsonify({"success": True, "execution": execution.to_dict()}), 202


@workflow_api.route("/logout", methods=["POST"])
def autoposter_logout():
    session.clear()
    return jsonify({"success": True})

