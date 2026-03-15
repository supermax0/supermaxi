from __future__ import annotations

import os
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


def _node_base_url() -> str:
    """
    Resolve external Node backend URL.
    Defaults to local dev service when config/env is not provided.
    """
    configured = (current_app.config.get("AI_AUTOMATION_NODE_URL") or "").strip()
    env_value = (os.getenv("AI_AUTOMATION_NODE_URL") or "").strip()
    return (configured or env_value or "http://127.0.0.1:4000").rstrip("/")


def _node_proxy_enabled() -> bool:
    configured = str(current_app.config.get("AI_AUTOMATION_NODE_PROXY") or "").strip().lower()
    env_value = (os.getenv("AI_AUTOMATION_NODE_PROXY") or "").strip().lower()
    raw = configured or env_value or "1"
    return raw not in {"0", "false", "off", "no"}


def _proxy_to_node(node_path: str, *, timeout_s: float = 8.0):
    """
    Transparent proxy to Node backend API.
    Returns Flask response tuple on success, None on transport failure.
    """
    if not _node_proxy_enabled():
        return None

    try:
        import requests  # type: ignore
    except Exception:
        return None

    url = f"{_node_base_url()}{node_path}"
    query = request.query_string.decode("utf-8", errors="ignore")
    if query:
        url = f"{url}?{query}"

    payload = None
    if request.method in {"POST", "PUT", "PATCH"}:
        payload = request.get_json(silent=True) or {}

    headers = {
        "accept": "application/json",
        "x-tenant-slug": (_tenant_slug() or "default"),
        "x-user-id": str(session.get("user_id") or "system"),
    }
    idem = request.headers.get("Idempotency-Key")
    if idem:
        headers["idempotency-key"] = idem

    try:
        resp = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            json=payload,
            timeout=(3.0, timeout_s),
        )
    except Exception as exc:
        current_app.logger.warning("Node proxy unavailable for %s: %s", node_path, exc)
        return None

    try:
        data = resp.json()
    except Exception:
        data = {
            "success": False,
            "error": "invalid_node_response",
            "status_code": resp.status_code,
            "body": (resp.text or "")[:800],
        }
    return jsonify(data), resp.status_code


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

    proxied = _proxy_to_node("/api/agents")
    if proxied is not None:
        return proxied

    agents = _base_agent_query().order_by(Agent.updated_at.desc(), Agent.id.desc()).all()
    return jsonify({"success": True, "agents": [a.to_dict() for a in agents]})


@workflow_api.route("/agents", methods=["POST"])
def create_agent():
    auth = _require_auth()
    if auth:
        return auth

    proxied = _proxy_to_node("/api/agents")
    if proxied is not None:
        return proxied

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

    proxied = _proxy_to_node("/api/workflows")
    if proxied is not None:
        return proxied

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

    proxied = _proxy_to_node("/api/workflows")
    if proxied is not None:
        return proxied

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

    proxied = _proxy_to_node(f"/api/workflows/{workflow_id}")
    if proxied is not None:
        return proxied

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

    proxied = _proxy_to_node(f"/api/workflows/{workflow_id}/run", timeout_s=15.0)
    if proxied is not None:
        return proxied

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

